#!/usr/bin/env python3
"""Reconcile Flask's single role string with Spring's role list.

Spring and Flask keep separate databases and separate accounts, joined only by
uid. Spring stores a list of ROLE_* rows and is the source of truth for
authorization; Flask stores one `users._role` string that drives its own pages
(`/users/table2`, the admin panels, `/api/id`).

Signup dual-writes to both, so new accounts start in step. Accounts created
before that, or changed on only one side since, can drift -- and a Spring admin
whose Flask role still says "User" cannot use the Flask admin pages at all.

This reports the drift and, with --apply, fixes the role mismatches.

It deliberately does NOT create missing accounts. An account present in one
backend and not the other needs a password, and inventing one here would either
lock the person out or hand out a known credential. Those are listed for a human
to deal with.

Usage:
    python3 scripts/reconcile_roles.py                 # dry run (default)
    python3 scripts/reconcile_roles.py --apply         # write the role fixes
    python3 scripts/reconcile_roles.py --spring-db ... --flask-db ...

Exit: 0 if nothing needs changing, 1 if drift was found (dry run) or on error.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_FLASK_DB = REPO / "instance" / "volumes" / "user_management.db"
DEFAULT_SPRING_DB = REPO.parent / "spring" / "volumes" / "sqlite.db"

# Highest privilege wins: an account holding ROLE_ADMIN and ROLE_STUDENT is an
# admin on the Flask side, which only has room for one value.
PRECEDENCE = (
    ("ROLE_ADMIN", "Admin"),
    ("ROLE_TEACHER", "Teacher"),
    ("ROLE_MENTOR", "Mentor"),
    ("ROLE_PENDING", "Pending"),
)
FALLBACK = "User"


def expected_flask_role(spring_roles: set[str]) -> str:
    for role, flask_role in PRECEDENCE:
        if role in spring_roles:
            return flask_role
    return FALLBACK


def read_spring(db: Path) -> dict[str, set[str]]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT p.uid, r.name FROM person p "
            "JOIN person_roles pr ON pr.person_id = p.id "
            "JOIN person_role r ON r.id = pr.roles_id"
        ).fetchall()
    finally:
        conn.close()
    out: dict[str, set[str]] = {}
    for uid, role in rows:
        out.setdefault(uid, set()).add(role)
    return out


def read_flask(db: Path) -> dict[str, str]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return dict(conn.execute("SELECT _uid, _role FROM users").fetchall())
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile Flask roles with Spring roles.")
    ap.add_argument("--flask-db", default=str(DEFAULT_FLASK_DB))
    ap.add_argument("--spring-db", default=str(DEFAULT_SPRING_DB))
    ap.add_argument("--apply", action="store_true",
                    help="Write the role fixes. Without this, reports only.")
    args = ap.parse_args()

    flask_db, spring_db = Path(args.flask_db), Path(args.spring_db)
    for label, db in (("Flask", flask_db), ("Spring", spring_db)):
        if not db.exists():
            print(f"error: {label} database not found at {db}", file=sys.stderr)
            return 1

    spring, flask = read_spring(spring_db), read_flask(flask_db)
    shared = set(spring) & set(flask)

    mismatches = []
    for uid in sorted(shared):
        want = expected_flask_role(spring[uid])
        if flask[uid] != want:
            mismatches.append((uid, sorted(spring[uid]), flask[uid], want))

    only_spring = sorted(set(spring) - set(flask))
    only_flask = sorted(set(flask) - set(spring))

    print(f"Spring persons : {len(spring)}")
    print(f"Flask users    : {len(flask)}")
    print(f"Shared by uid  : {len(shared)}\n")

    if mismatches:
        print(f"Role mismatches ({len(mismatches)}):")
        for uid, roles, have, want in mismatches:
            print(f"  {uid:<24} spring={','.join(roles):<45} flask={have:<8} -> {want}")
    else:
        print("Role mismatches: none")

    # Reported, never auto-created: see the module docstring.
    print(f"\nIn Spring but not Flask : {len(only_spring)}"
          + (f"  e.g. {', '.join(only_spring[:5])}" if only_spring else ""))
    print(f"In Flask but not Spring : {len(only_flask)}"
          + (f"  e.g. {', '.join(only_flask[:5])}" if only_flask else ""))
    if only_spring or only_flask:
        print("  (not created automatically -- a new account needs a password)")

    if not mismatches:
        return 0

    if not args.apply:
        print(f"\nDry run. Re-run with --apply to update {len(mismatches)} Flask role(s).")
        return 1

    conn = sqlite3.connect(str(flask_db))
    try:
        with conn:
            for uid, _roles, _have, want in mismatches:
                conn.execute("UPDATE users SET _role = ? WHERE _uid = ?", (want, uid))
    finally:
        conn.close()

    after = read_flask(flask_db)
    bad = [uid for uid, _r, _h, want in mismatches if after.get(uid) != want]
    if bad:
        print(f"\nERROR: {len(bad)} role(s) did not persist: {bad}", file=sys.stderr)
        return 1
    print(f"\nUpdated {len(mismatches)} Flask role(s); re-read and verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
