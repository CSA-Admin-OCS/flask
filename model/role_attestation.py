"""A statement Flask signs at login so Spring can give, or take away, a role: "this uid is a mentor right now".

Spring cannot see who a Teacher or Admin has verified: that is kept here. So at login Flask signs a short
statement and hands it to the page, which passes it to Spring (POST /api/person/mentor/confirm). Spring checks the
signature with the same shared secret, RESET_TOKEN_SECRET, and then acts on it. Nothing is sent from Flask to Spring.

    token     = base64url(json) + "." + signature
    json      = {"exp": <seconds>, "granted": <bool>, "role": "ROLE_MENTOR", "uid": <uid>}, keys sorted, no spaces
    signature = base64url(HMAC-SHA256(secret, "mentor-role-v1:" + base64url(json)))

The label before the payload, and having no dots in what is signed, mean a signature made for another purpose
(a password-reset token signs "uid.exp.nonce") can never be accepted here.

Which account types are told to Spring, and as which role, is spring_role in dataconfigs/account_types.json.
"""
import base64
import hashlib
import hmac
import json
import time

from flask import current_app

from model import account_types

PURPOSE = "mentor-role-v1:"
LIFETIME_SECONDS = 300  # long enough for the page to pass it on, too short to be worth keeping


def _b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def sign(payload, secret):
    body = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = _b64(hmac.new(secret.encode(), (PURPOSE + body).encode(), hashlib.sha256).digest())
    return f"{body}.{signature}"


def issue(user):
    """The signed statement for this user's login, or None when their type is not told to Spring or no shared
    secret is set. granted is whether the account is active, so a mentor who is deactivated can lose the role."""
    spring_role = account_types.spring_role(user.role)
    secret = current_app.config.get("RESET_TOKEN_SECRET")
    if spring_role is None or not secret:
        return None
    return sign({"uid": user.uid, "role": spring_role, "granted": bool(user.active),
                 "exp": int(time.time()) + LIFETIME_SECONDS}, secret)
