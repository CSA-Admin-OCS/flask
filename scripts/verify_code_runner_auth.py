#!/usr/bin/env python3
"""Verify that only a signed-in, active account can run code through /run/python and /run/javascript.

Runs against a throwaway SQLite DB. The code runners are replaced by a stub that records the call, so no
code is ever executed; the point is whether the request gets that far. Checksums the real dev DB before
and after to prove it was never touched.

Usage:  python scripts/verify_code_runner_auth.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import hashlib, os, secrets, sys, tempfile
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
os.environ.setdefault("SECRET_KEY", "verify-code-runner-auth")

REAL_DB = os.path.join(REPO, "instance", "volumes", "user_management.db")
PASSWORD = "Aa1!" + secrets.token_urlsafe(16)  # new every run; the accounts live only in a throwaway database
_failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail}]" if detail else ""))
    if not cond:
        _failures.append(label)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def main():
    real_before = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    tmp = tempfile.mkdtemp(prefix="code-runner-auth-")

    import __init__ as pkg
    from sqlalchemy import create_engine
    app, db = pkg.app, pkg.db
    with app.app_context():
        db.engines[None] = create_engine(f"sqlite:///{os.path.join(tmp, 'new.db')}")
    import main  # noqa: F401  registers every model and blueprint
    from model.user import User
    import api.python_exec_api as py_api
    import api.javascript_exec_api as js_api

    app.config["TESTING"] = True
    with app.app_context():
        db.create_all()
        for uid, role in (("zz_student", "User"), ("zz_pending", "User")):
            db.session.add(User(name=uid, uid=uid, password=PASSWORD, role=role))
        for u in User.query.all():
            if u.uid != "zz_pending":
                u.activate()

    ran = []

    def fake_local(code):
        ran.append(code)
        return {"output": "stub"}

    def login(c, uid):
        r = c.post("/api/authenticate", json={"uid": uid, "password": PASSWORD})
        assert r.status_code == 200, (uid, r.status_code)

    for path, mod in (("/run/python", py_api), ("/run/javascript", js_api)):
        with patch.object(mod, "_execute_local", fake_local), patch.object(mod, "_execute_remote", fake_local), \
                patch.dict(os.environ, {"IS_PRODUCTION": "false"}):
            ran.clear()
            with app.test_client() as c:
                r = c.post(path, json={"code": "print(1)"})
                check(f"{path}: anonymous is refused with 401", r.status_code == 401, str(r.status_code))
                check(f"{path}: anonymous code is not run", not ran, str(ran))
            with app.test_client() as c:
                r = c.post(path, json={"code": "print(1)"}, headers={"Authorization": "Bearer not-a-real-token"})
                check(f"{path}: a bad token is refused", r.status_code in (401, 403) and not ran, str(r.status_code))
            with app.test_client() as c:
                login(c, "zz_pending")
                r = c.post(path, json={"code": "print(1)"})
                check(f"{path}: an inactive account is refused", r.status_code == 403 and not ran, str(r.status_code))
            with app.test_client() as c:
                login(c, "zz_student")
                r = c.post(path, json={"code": "print(1)"})
                check(f"{path}: an active account can run code", r.status_code == 200 and ran == ["print(1)"], f"{r.status_code} {ran}")
                ran.clear()
                r = c.post(path, json={"code": "   "})
                check(f"{path}: empty code still answers 400", r.status_code == 400 and not ran, str(r.status_code))
        with patch.object(mod, "_execute_local", fake_local), patch.object(mod, "_execute_remote", fake_local), \
                patch.dict(os.environ, {"IS_PRODUCTION": "true"}):
            ran.clear()
            with app.test_client() as c:
                r = c.post(path, json={"code": "print(1)"})
                check(f"{path}: anonymous is refused in production mode too", r.status_code == 401 and not ran, str(r.status_code))

    real_after = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    check("the real dev database was not touched", real_before == real_after)
    print(f"\n{len(_failures)} failed" if _failures else "\nall checks passed")
    sys.exit(1 if _failures else 0)


main()
