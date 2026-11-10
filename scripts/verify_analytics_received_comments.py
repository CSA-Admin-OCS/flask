#!/usr/bin/env python3
"""Verify GET /api/analytics/github/user/received_issue_comments needs a signed-in account, and works for one.

It had no guard, so the signed-in user it reads was never set: every caller, signed in or not, got a 500.
GitHub is replaced by a stub that records the uid it is asked about. Runs against a throwaway SQLite DB and
checksums the real dev DB before and after to prove it was never touched.

Usage:  python scripts/verify_analytics_received_comments.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import hashlib, os, secrets, sys, tempfile
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
os.environ.setdefault("SECRET_KEY", "verify-analytics-received")

REAL_DB = os.path.join(REPO, "instance", "volumes", "user_management.db")
PASSWORD = "Aa1!" + secrets.token_urlsafe(16)  # new every run; the accounts live only in a throwaway database
URL = "/api/analytics/github/user/received_issue_comments"
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
    tmp = tempfile.mkdtemp(prefix="analytics-received-")

    import __init__ as pkg
    from sqlalchemy import create_engine
    app, db = pkg.app, pkg.db
    with app.app_context():
        db.engines[None] = create_engine(f"sqlite:///{os.path.join(tmp, 'new.db')}")
    import main  # noqa: F401  registers every model and blueprint
    import api.analytics as analytics
    from model.user import User

    app.config["TESTING"] = True
    app.config["PROPAGATE_EXCEPTIONS"] = False  # an error in a route answers 500, as it does in production
    with app.app_context():
        db.create_all()
        for uid in ("zz_one", "zz_two", "zz_pending"):
            db.session.add(User(name=uid, uid=uid, password=PASSWORD, role="User"))
        for u in User.query.all():
            if u.uid != "zz_pending":
                u.activate()

    asked = []

    def fake_received(self, uid, start, end):
        asked.append(uid)
        return {"total": 3}, 200

    def login(c, uid):
        r = c.post("/api/authenticate", json={"uid": uid, "password": PASSWORD})
        assert r.status_code == 200, (uid, r.status_code)

    with patch.object(analytics.GitHubUser, "get_total_received_issue_comments", fake_received):
        with app.test_client() as c:
            r = c.get(URL)
            check("a caller who is not signed in gets 401", r.status_code == 401 and not asked, f"{r.status_code} {asked}")
        with app.test_client() as c:
            r = c.get(URL, headers={"Authorization": "Bearer not-a-real-token"})
            check("a bad token is refused", r.status_code in (401, 403) and not asked, str(r.status_code))
        with app.test_client() as c:
            login(c, "zz_pending")
            r = c.get(URL)
            check("an inactive account is refused", r.status_code == 403 and not asked, str(r.status_code))
        with app.test_client() as c:
            login(c, "zz_one")
            r = c.get(URL)
            check("a signed-in account gets its numbers", r.status_code == 200 and r.get_json() == {"total": 3}, f"{r.status_code} {r.get_data(as_text=True)[:80]}")
            check("and only about itself", asked == ["zz_one"], str(asked))
        with app.test_client() as c:
            login(c, "zz_two")
            c.get(URL)
            check("another account is asked about itself, not the first", asked == ["zz_one", "zz_two"], str(asked))

    real_after = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    check("the real dev database was not touched", real_before == real_after)
    print(f"\n{len(_failures)} failed" if _failures else "\nall checks passed")
    sys.exit(1 if _failures else 0)


main()
