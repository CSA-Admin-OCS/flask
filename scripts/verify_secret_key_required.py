#!/usr/bin/env python3
"""Verify that a production server will not start with the SECRET_KEY written in the source.

Starts the app in fresh processes with different environments and checks which ones start. Touches no
database: the app is imported, never served, and no connection to MySQL is made.

Usage:  python scripts/verify_secret_key_required.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import os, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEEP = ("PATH", "HOME", "LANG", "VIRTUAL_ENV", "PYTHONPATH")
_failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail}]" if detail else ""))
    if not cond:
        _failures.append(label)


def starts(**env):
    """(started?, everything it printed) for a fresh process importing the app with only this environment."""
    clean = {k: v for k, v in os.environ.items() if k in KEEP}
    clean.update(env)
    r = subprocess.run([sys.executable, "-c", "import __init__"], cwd=REPO, env=clean, capture_output=True, text=True)
    return r.returncode == 0, r.stdout + r.stderr


MYSQL = dict(DB_ENDPOINT="db.invalid", DB_USERNAME="u", DB_PASSWORD="p")
KEY = dict(SECRET_KEY="x" * 40)

ok, out = starts()
check("development with no key still starts", ok, out[-200:])
ok, out = starts(IS_PRODUCTION="false")
check("IS_PRODUCTION=false with no key still starts", ok, out[-200:])
ok, out = starts(IS_PRODUCTION="true")
check("IS_PRODUCTION=true with no key does not start", not ok and "SECRET_KEY is not set" in out, out[-200:])
ok, out = starts(IS_PRODUCTION="TRUE")
check("IS_PRODUCTION=TRUE (any case) with no key does not start", not ok and "SECRET_KEY is not set" in out, out[-200:])
ok, out = starts(**MYSQL)
check("a MySQL server with no key does not start", not ok and "SECRET_KEY is not set" in out, out[-200:])
ok, out = starts(IS_PRODUCTION="true", SECRET_KEY="SECRET_KEY")
check("production with the placeholder written out as the key does not start", not ok and "SECRET_KEY is not set" in out, out[-200:])
ok, out = starts(IS_PRODUCTION="true", SECRET_KEY="")
check("production with an empty key does not start", not ok and "SECRET_KEY is not set" in out, out[-200:])
ok, out = starts(IS_PRODUCTION="true", DEFAULT_PASSWORD="Aa1!" + "z" * 12, **KEY)
check("production with its own key starts, with no warnings", ok and "WARNING" not in out, out[-200:])
ok, out = starts(**MYSQL, DEFAULT_PASSWORD="Aa1!" + "z" * 12, **KEY)
check("a MySQL server with its own key starts", ok, out[-200:])
ok, out = starts(IS_PRODUCTION="true", **KEY)
check("production without DEFAULT_PASSWORD starts but warns", ok and "WARNING: DEFAULT_PASSWORD is not set" in out, out[-200:])
ok, out = starts()
check("development does not warn about DEFAULT_PASSWORD", "WARNING: DEFAULT_PASSWORD" not in out, out[-200:])

print(f"\n{len(_failures)} failed" if _failures else "\nall checks passed")
sys.exit(1 if _failures else 0)
