"""The one check every request passes before it reaches a route: is this caller allowed to make this request,
by model/dataconfigs/permissions.json?

It runs before every request, whatever the route's own decorators are, so a route added with no guard and no entry
in the file is caught here. The guards on the routes stay; this is the same decision made once more, from data, in
one place.

For each request it works out a decision and keeps it on the request as access_decision: {"allow", "why", "caller"}.
What happens next depends on the caller and on the "enforce" list in permissions.json:

  * a caller in "enforce" (anonymous, or a role) who is not allowed is refused here, with the answer the route's own
    guard would have given;
  * for every other caller the request goes on as before (shadow mode). If the decision was to refuse and the route
    answered anyway, that is written to the log, so the file can be corrected before it is enforced.

In shadow mode an error in this check is logged and the request goes on: it must never be the reason a request fails.
"""
import os

from flask import current_app, request
from flask_login import current_user

from api.authorize import account_refusal, identify, role_refusal
from model import permissions

# The mode is decided when the process starts, as it is for the guards that depend on it
IS_PRODUCTION = os.environ.get("IS_PRODUCTION", "false").lower() == "true"
ANONYMOUS = "anonymous"
_NOT_LISTED = "This request is not in permissions.json, so nobody may make it."


def _refuse(why, caller, answer):
    return {"allow": False, "why": why, "caller": caller}, answer


def _allow(why, caller=None):
    return {"allow": True, "why": why, "caller": caller}, None


def decide(method, route, production):
    """(decision, answer): the decision for this request, and the answer to give if it is refused and enforced.

    The answer is a function, called only when the refusal is enforced, because making it can change something
    (an expired account is made inactive).
    """
    who = permissions.who_may_call(method, route, production)
    if who == "anyone":
        return _allow("open to anyone")
    if who == "device_key":
        return _allow("the route checks the device key")
    if who == "session":
        # the Flask session login decides, and it asks only whether there is a session
        if current_user.is_authenticated:
            return _allow("has a session", current_user.role)
        return _refuse("no session", ANONYMOUS, lambda: current_app.login_manager.unauthorized())

    user, no_login = identify()
    if user is None:
        if who is None:
            return _refuse("not in permissions.json", ANONYMOUS, lambda: ({"message": _NOT_LISTED, "data": None, "error": "Unauthorized"}, 401))
        return _refuse("no login", ANONYMOUS, lambda: no_login)
    if who is None:
        return _refuse("not in permissions.json", user.role, lambda: ({"message": _NOT_LISTED, "data": None, "error": "Forbidden"}, 403))
    if account_refusal(user, deactivate_expired=False):
        return _refuse("the account is expired or inactive", user.role, lambda: account_refusal(user))
    if who != "signed_in" and role_refusal(user, who):
        return _refuse("the role is not one that may", user.role, lambda: role_refusal(user, who))
    return _allow("signed in" if who == "signed_in" else "the role may", user.role)


def check_access():
    """Before every request: decide, and refuse here when the caller is one the file says to enforce for."""
    if request.method == "OPTIONS" or request.url_rule is None:
        return None  # a CORS preflight carries no login; an unknown address has no route to guard
    method = "GET" if request.method == "HEAD" else request.method
    try:
        decision, answer = decide(method, request.url_rule.rule, IS_PRODUCTION)
    except Exception:
        if permissions.enforcing():
            raise
        current_app.logger.exception("permissions (shadow): the check failed for %s %s", method, request.url_rule.rule)
        return None
    request.access_decision = decision
    if not decision["allow"] and permissions.enforced(decision["caller"]):
        decision["enforced"] = True
        return answer()
    return None


def _was_refused(response):
    if response.status_code in (401, 403):
        return True
    return 300 <= response.status_code < 400 and "/login" in (response.headers.get("Location") or "")


def note_access(response):
    """After every request: in shadow mode, log a request the file would refuse that the route answered."""
    decision = getattr(request, "access_decision", None)
    if decision and not decision["allow"] and not decision.get("enforced") and not _was_refused(response):
        current_app.logger.warning("permissions (shadow): would refuse %s %s for %s (%s), and the route answered %s",
                                   request.method, request.url_rule.rule, decision["caller"], decision["why"], response.status_code)
    return response


def init_app(app):
    """Put the check before every request of this app, and the shadow note after."""
    app.before_request(check_access)
    app.after_request(note_access)
