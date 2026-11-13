#!/usr/bin/env python3
"""Verify the role statement Flask signs at login, which Spring uses to give a verified mentor ROLE_MENTOR.

Runs the real app against a throwaway SQLite database, and checksums the real dev DB before and after to
prove it was never touched. The signature is checked here with its own HMAC code, not the code under test.

Usage:  python scripts/verify_role_attestation.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import base64, copy, hashlib, hmac, json, os, secrets, sys, tempfile, time
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
os.environ.setdefault("SECRET_KEY", "verify-role-attestation")
SHARED = "attestation-test-secret-" + secrets.token_hex(8)
os.environ["RESET_TOKEN_SECRET"] = SHARED  # the secret both backends already share

REAL_DB = os.path.join(REPO, "instance", "volumes", "user_management.db")
PASSWORD = "Aa1!TestPass9"
PURPOSE = "mentor-role-v1:"
_failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        _failures.append(label)


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def independent_check(token, secret, now=None):
    """The statement's payload if the signature and the expiry are good, else None."""
    try:
        body, sig = token.split(".")
        want = b64(hmac.new(secret.encode(), (PURPOSE + body).encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(want, sig):
            return None
        payload = json.loads(unb64(body))
        return payload if payload["exp"] > (now or time.time()) else None
    except Exception:
        return None


def main():
    real_before = sha256(REAL_DB) if os.path.exists(REAL_DB) else None

    from sqlalchemy import create_engine
    from main import app, db
    from model import account_types, role_attestation
    from model.user import User
    engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(prefix='attest-'), 'new.db')}")
    with app.app_context():
        db.engines[None] = engine
    app.config["TESTING"] = True
    app.config["RESET_TOKEN_SECRET"] = SHARED

    with app.app_context():
        db.create_all()
        for uid, role, active in (("ment", "Mentor", True), ("ment_waiting", "Mentor", False), ("stud", "User", True),
                                  ("teach", "Teacher", True), ("boss", "Admin", True), ("guest1", "Guest", True)):
            u = User(name=uid.title() + " Person", uid=uid, password=PASSWORD, role=role)
            u.create()
            if active:
                u.activate()

    def login(uid):
        with app.test_client() as c:
            r = c.post("/api/authenticate", json={"uid": uid, "password": PASSWORD})
            return r.status_code, r.get_json() or {}

    code, body = login("ment")
    token = body.get("role_attestation")
    payload = independent_check(token or "", SHARED)
    check("an active mentor's login carries a signed statement", code == 200 and isinstance(token, str) and payload is not None, f"{code} {body}")
    check("it says who, which role, that it is granted, and when it ends (about 5 minutes)",
          payload == {**(payload or {}), "uid": "ment", "role": "ROLE_MENTOR", "granted": True} and 240 < (payload or {"exp": 0})["exp"] - time.time() <= 300,
          str(payload))
    code, body = login("ment_waiting")
    payload = independent_check(body.get("role_attestation") or "", SHARED)
    check("a mentor still waiting for verification gets a statement saying NOT granted, so Spring can take the role away",
          code == 200 and payload is not None and payload["granted"] is False and payload["role"] == "ROLE_MENTOR", f"{code} {payload}")
    for uid in ("stud", "teach", "boss", "guest1"):
        code, body = login(uid)
        check(f"{uid}'s login has no statement, and still works", code == 200 and "role_attestation" not in body, f"{code} {sorted(body)}")

    app.config["RESET_TOKEN_SECRET"] = None
    code, body = login("ment")
    check("with no shared secret there is no statement, and login still works", code == 200 and "role_attestation" not in body, f"{code} {sorted(body)}")
    app.config["RESET_TOKEN_SECRET"] = SHARED

    check("the statement cannot be read with another secret", independent_check(token, "another-secret") is None)
    body_part, sig = token.split(".")
    forged = {**json.loads(unb64(body_part)), "uid": "stud"}
    check("a changed payload no longer verifies", independent_check(b64(json.dumps(forged).encode()) + "." + sig, SHARED) is None)
    check("a changed signature no longer verifies", independent_check(body_part + "." + sig[:-2] + "AA", SHARED) is None)
    check("one past its end no longer verifies", independent_check(token, SHARED, now=time.time() + 400) is None)
    reset_style = b64(hmac.new(SHARED.encode(), f"ment.{int(time.time()) + 300}.nonce".encode(), hashlib.sha256).digest())
    check("a password-reset signature made with the same secret cannot stand in for it", independent_check(body_part + "." + reset_style, SHARED) is None)
    check("the signed string has a label that a reset token's never has, and no dots in it, so the two can never be equal",
          "." not in (PURPOSE + body_part))

    # a fixed example, so Spring's tests can check the same bytes
    fixed = role_attestation.sign({"uid": "vector", "role": "ROLE_MENTOR", "granted": True, "exp": 1900000000}, "vector-secret")
    print("VECTOR " + fixed)
    check("a fixed example signs the same way every time, to be shared with Spring's test",
          fixed == role_attestation.sign({"uid": "vector", "role": "ROLE_MENTOR", "granted": True, "exp": 1900000000}, "vector-secret")
          and independent_check(fixed, "vector-secret", now=1) is not None)

    # which roles are mapped comes from the data
    changed = copy.deepcopy(account_types._data)
    changed["account_types"]["student"]["spring_role"] = "ROLE_STUDENT"
    with patch.object(account_types, "_data", changed):
        code, body = login("stud")
        payload = independent_check(body.get("role_attestation") or "", SHARED)
        check("which roles Spring is told about comes from the data: a student mapped to ROLE_STUDENT gets one", payload is not None and payload["role"] == "ROLE_STUDENT", str(payload))
    check("and a role with no mapping gets none", "role_attestation" not in login("stud")[1])

    def refused(mutate):
        bad = copy.deepcopy(account_types._data)
        mutate(bad)
        try:
            account_types._check(bad)
            return False
        except ValueError:
            return True
    mentor = lambda d: d["account_types"]["mentor"]
    check("startup refuses a spring_role that is not a ROLE_ name", all(refused(lambda d, v=v: mentor(d).update(spring_role=v)) for v in ("", "mentor", "role_mentor", 7, "ROLE_ ADMIN")))
    check("startup refuses a staff role, or the Admin role, being given to Spring this way",
          refused(lambda d: mentor(d).update(spring_role="ROLE_ADMIN")) and refused(lambda d: mentor(d).update(spring_role="ROLE_TEACHER")))

    real_after = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    check("the real dev database was not touched", real_before == real_after)
    print(f"\n{'ALL PASSED' if not _failures else f'{len(_failures)} FAILED'}")
    sys.exit(1 if _failures else 0)


if __name__ == "__main__":
    main()
