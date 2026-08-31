#!/usr/bin/env python3
"""Verify that only admins can change a user's role.

Role changes are a privilege boundary: PUT /api/user is reachable by any
authenticated user editing themselves, so the "role" key must never be honoured
for a non-admin. This script proves that end-to-end through the real request
stack (auth, decorators, handler) rather than by reading the code.

Runs entirely against a throwaway copy of the SQLite DB -- it re-binds the
SQLAlchemy engine before anything touches the real file, and checksums the real
DB afterwards to prove it was untouched.

Usage:  python scripts/verify_role_guard.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import hashlib
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
os.environ.setdefault("SECRET_KEY", "verify-role-guard")

REAL_DB = os.path.join(REPO, "instance", "volumes", "user_management.db")
PASSWORD = "Passw0rd!123"

_failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail}]" if detail else ""))
    if not cond:
        _failures.append(label)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    if not os.path.exists(REAL_DB):
        print(f"No SQLite DB at {REAL_DB}; run scripts/db_init.py first.")
        return 1

    before = sha256(REAL_DB)
    tmpdir = tempfile.mkdtemp(prefix="role-guard-")
    copy_db = os.path.join(tmpdir, "user_management.db")
    shutil.copy2(REAL_DB, copy_db)

    import __init__ as pkg
    from sqlalchemy import create_engine

    app, db = pkg.app, pkg.db
    # Re-bind BEFORE any model import touches the real file.
    with app.app_context():
        db.engines[None] = create_engine(f"sqlite:///{copy_db}")

    import main  # noqa: F401  registers every model + api blueprint (__main__-guarded)
    from model.user import User

    app.config["TESTING"] = True

    with app.app_context():
        assert str(db.engine.url).endswith(os.path.basename(copy_db)), db.engine.url
        for uid in ("zz_admin", "zz_student"):
            existing = User.query.filter_by(_uid=uid).first()
            if existing:
                db.session.delete(existing)
                db.session.commit()
        db.session.add_all([
            User(name="ZZ Admin", uid="zz_admin", password=PASSWORD, role="Admin"),
            User(name="ZZ Student", uid="zz_student", password=PASSWORD, role="User"),
        ])
        db.session.commit()

    def login(client, uid):
        resp = client.post("/api/authenticate", json={"uid": uid, "password": PASSWORD})
        assert resp.status_code == 200, (uid, resp.status_code, resp.get_data(as_text=True)[:200])

    def role_of(uid):
        with app.app_context():
            return User.query.filter_by(_uid=uid).first().role

    # A non-admin must not be able to promote themselves.
    with app.test_client() as c:
        login(c, "zz_student")
        r = c.put("/api/user", json={"role": "Admin"})
        check("non-admin self role change -> 403", r.status_code == 403, f"got {r.status_code}")
        check("role unchanged in DB", role_of("zz_student") == "User", f"role={role_of('zz_student')}")

        # Naming their own uid skips the GitHub-uid branch and reaches the role check directly.
        r = c.put("/api/user", json={"uid": "zz_student", "role": "Admin"})
        check("non-admin self-escalation by own uid -> 403", r.status_code == 403, f"got {r.status_code}")
        check("self-escalation did not persist", role_of("zz_student") != "Admin", f"role={role_of('zz_student')}")

        # 404 rather than 403: for a non-admin the handler pins user=current_user and the
        # pre-existing GitHub-account validation rejects the foreign uid first. Either way
        # the target is never modified, which is the property that matters.
        r = c.put("/api/user", json={"uid": "zz_admin", "role": "User"})
        check("non-admin cannot touch another user", r.status_code in (403, 404), f"got {r.status_code}")
        check("admin's role untouched", role_of("zz_admin") == "Admin")

        # Ordinary self-edits must keep working.
        r = c.put("/api/user", json={"name": "Renamed"})
        check("non-admin self edit without role -> 200", r.status_code == 200, f"got {r.status_code}")

    # An admin can set a valid role, and only a valid one.
    with app.test_client() as c:
        login(c, "zz_admin")
        r = c.put("/api/user", json={"uid": "zz_student", "role": "Mentor"})
        check("admin sets Mentor -> 200", r.status_code == 200, f"got {r.status_code}")
        check("role persisted as Mentor", role_of("zz_student") == "Mentor", f"role={role_of('zz_student')}")

        r = c.put("/api/user", json={"uid": "zz_student", "role": "Wizard"})
        check("admin sets unknown role -> 400", r.status_code == 400, f"got {r.status_code}")
        check("unknown role rejected, still Mentor", role_of("zz_student") == "Mentor", f"role={role_of('zz_student')}")

    shutil.rmtree(tmpdir, ignore_errors=True)

    check("real dev DB untouched", sha256(REAL_DB) == before)

    print("\n" + ("ALL PASSED" if not _failures else f"FAILURES: {_failures}"))
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
