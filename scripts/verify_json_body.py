#!/usr/bin/env python3
"""Verify that a request body that is not a JSON object gets a 400, not a 500, from every API route
that reads one (api/request_body.py), and that good bodies still work.

Sends each POST, PUT and DELETE route under /api no body, a list, null and a string, as a verified
Admin. Runs the real app against a throwaway SQLite database with the network blocked, and checksums
the real dev DB before and after to prove it was never touched.

Usage:  python scripts/verify_json_body.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import hashlib, logging, os, re, socket, sys, tempfile
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
os.environ.setdefault("SECRET_KEY", "verify-json-body")

REAL_DB = os.path.join(REPO, "instance", "volumes", "user_management.db")
PASSWORD = "Verify1!pass"
BAD_BODIES = {"no body": None, "a list": "[]", "null": "null", "a string": '"x"'}
# These answer 500 for a reason other than the body: a key the server has not been given, or Gemini's
# development login bypass. They return 500 for {} too.
NOT_THE_BODY = {"/api/gemini", "/api/gemini/debug", "/api/presence/event", "/api/rfid/scan",
                "/api/snapshot/aurora", "/api/snapshot/sqlite"}
_failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        _failures.append(label)


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    real_before = sha256(REAL_DB) if os.path.exists(REAL_DB) else None

    def no_network(*_args, **_kwargs):
        raise OSError("network blocked by verify_json_body.py")
    socket.socket.connect = no_network

    from sqlalchemy import create_engine
    from main import app, db  # registers every model and blueprint
    from model.user import User
    from api.request_body import NotJsonObjectError
    with app.app_context():
        db.engines[None] = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(prefix='jsonbody-'), 'new.db')}")
        db.create_all()
    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = False
    logging.disable(logging.CRITICAL)

    def admin_client():
        # a fresh verified Admin every time, since some routes log out or delete the caller
        with app.app_context():
            admin = User.query.filter_by(_uid="boss").first()
            if admin is None:
                admin = User(name="Boss Person", uid="boss", password=PASSWORD, role="Admin").create()
            admin.active, admin.last_verified = True, datetime.utcnow()
            db.session.commit()
        client = app.test_client()
        client.post("/api/authenticate", json={"uid": "boss", "password": PASSWORD})
        return client

    def send(method, url, raw):
        kwargs = {} if raw is None else {"data": raw, "content_type": "application/json"}
        try:
            return admin_client().open(url, method=method, **kwargs)
        except Exception as e:  # the app raised instead of answering
            return e

    crashes = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api") or rule.rule in NOT_THE_BODY:
            continue
        url = re.sub(r"<[^>]+>", "1", rule.rule)
        for method in sorted(rule.methods & {"POST", "PUT", "DELETE", "PATCH"}):
            for label, raw in BAD_BODIES.items():
                r = send(method, url, raw)
                if isinstance(r, Exception) or r.status_code >= 500:
                    crashes.append(f"{method} {rule.rule} with {label}: {r if isinstance(r, Exception) else r.status_code}")
    check("no POST, PUT or DELETE under /api answers a bad body with a 500", not crashes, "; ".join(crashes[:8]) + (f" (+{len(crashes) - 8} more)" if len(crashes) > 8 else ""))

    message = NotJsonObjectError.description
    for method, url in (("POST", "/api/user"), ("POST", "/api/authenticate"), ("POST", "/api/feedback/"), ("PUT", "/api/id/pfp")):
        for label, raw in BAD_BODIES.items():
            r = send(method, url, raw)
            check(f"{method} {url} with {label}: 400 saying to send a JSON object (Flask-RESTful route)",
                  r.status_code == 400 and (r.get_json() or {}).get("message") == message, f"{r.status_code} {r.get_data(as_text=True)[:100]}")
    for method, url in (("POST", "/api/study"), ("POST", "/api/classrooms/")):
        r = send(method, url, "[]")
        check(f"{method} {url} with a list: the same JSON 400 (plain Flask route)",
              r.status_code == 400 and (r.get_json() or {}).get("message") == message, f"{r.status_code} {r.get_data(as_text=True)[:100]}")

    # good bodies still work
    client = app.test_client()
    r = client.post("/api/authenticate", json={"uid": "boss", "password": PASSWORD})
    check("logging in with a uid and password still works (200)", r.status_code == 200, r.status_code)
    r = client.post("/api/authenticate", json={"uid": "boss", "password": "Wrong1!pass"})
    check("a wrong password is still a 401", r.status_code == 401, r.status_code)
    r = client.post("/api/authenticate", json={})
    check("an empty object still gets the login form's own 400", r.status_code == 400 and r.get_json()["message"] == "Please provide user details", r.get_data(as_text=True)[:100])
    r = admin_client().post("/api/section", json={"name": "Verify Section", "abbreviation": "VS"})
    check("creating a section still works (200)", r.status_code == 200, f"{r.status_code} {r.get_data(as_text=True)[:100]}")
    r = admin_client().post("/api/study", json={"topic": "t", "subtopic": "s", "studied": True, "timestamp": "2026-11-10"})
    check("saving a study record still works (201)", r.status_code == 201, f"{r.status_code} {r.get_data(as_text=True)[:100]}")
    r = admin_client().post("/api/user/guest", json={"uid": "g"})
    check("a body missing a field still gets that route's own 400", r.status_code == 400 and "Username" in r.get_json()["message"], r.get_data(as_text=True)[:100])

    real_after = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    check("the real dev database was not touched", real_before == real_after)

    print(f"\n{'ALL PASSED' if not _failures else f'{len(_failures)} FAILED'}")
    sys.exit(1 if _failures else 0)


if __name__ == "__main__":
    main()
