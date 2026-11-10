#!/usr/bin/env python3
"""Verify PUT /update_user/<uid> refuses a caller who is not signed in with a 401, not an error.

Runs against a throwaway SQLite DB and checksums the real dev DB before and after to prove it was never touched.

Usage:  python scripts/verify_update_user_guard.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import hashlib, os, secrets, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
os.environ.setdefault("SECRET_KEY", "verify-update-user-guard")

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
    tmp = tempfile.mkdtemp(prefix="update-user-guard-")

    import __init__ as pkg
    from sqlalchemy import create_engine
    app, db = pkg.app, pkg.db
    with app.app_context():
        db.engines[None] = create_engine(f"sqlite:///{os.path.join(tmp, 'new.db')}")
    import main  # noqa: F401  registers every model and blueprint
    from model.user import User

    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = False  # an error in a route answers 500, as it does in production
    with app.app_context():
        db.create_all()
        for uid, role in (("zz_admin", "Admin"), ("zz_student", "User"), ("zz_target", "User")):
            db.session.add(User(name=f"Name {uid}", uid=uid, password=PASSWORD, role=role))
        for u in User.query.all():
            u.activate()

    def name_of(uid):
        with app.app_context():
            return User.query.filter_by(_uid=uid).first().name

    def login(c, uid):
        r = c.post("/login", data={"username": uid, "password": PASSWORD})
        assert r.status_code in (200, 302), (uid, r.status_code)

    url = "/update_user/zz_target"
    with app.test_client() as c:
        r = c.put(url, json={"name": "Changed"})
        check("a caller who is not signed in gets 401", r.status_code == 401, str(r.status_code))
        check("and nothing is changed", name_of("zz_target") == "Name zz_target")
    with app.test_client() as c:
        login(c, "zz_student")
        r = c.put(url, json={"name": "Changed"})
        check("a signed-in non-admin still gets 403", r.status_code == 403, str(r.status_code))
        check("and nothing is changed", name_of("zz_target") == "Name zz_target")
    with app.test_client() as c:
        login(c, "zz_admin")
        r = c.put(url, json={"name": "Changed"})
        check("an admin still updates the user", r.status_code == 200 and name_of("zz_target") == "Changed", f"{r.status_code} {name_of('zz_target')}")
        check("an admin gets 404 for a user that does not exist", c.put("/update_user/zz_nobody", json={"name": "x"}).status_code == 404)

    real_after = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    check("the real dev database was not touched", real_before == real_after)
    print(f"\n{len(_failures)} failed" if _failures else "\nall checks passed")
    sys.exit(1 if _failures else 0)


main()
