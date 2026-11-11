#!/usr/bin/env python3
"""Verify which origins Flask answers with credentialed CORS headers.

Sends real requests with each Origin header through the app and checks that only our own sites are echoed
back with Access-Control-Allow-Credentials. Touches no database.

Usage:  python scripts/verify_cors.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import os, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
os.environ.setdefault("SECRET_KEY", "verify-cors")

from __init__ import app

ALLOWED = [
    "https://opencodingsociety.com",
    "https://flask.opencodingsociety.com",
    "https://a.b.opencodingsociety.com",
    "https://open-coding-society.github.io",
    "http://localhost:4000",
]
REFUSED = [
    "https://x.opencodingsociety.com.evil.example",       # our name as the start of someone else's
    "https://opencodingsociety.com.evil.example",
    "https://xopencodingsociety.com",                     # no dot before our name
    "https://x.opencodingsociety.community",
    "http://x.opencodingsociety.com",                     # not https
    "https://x.opencodingsociety.com@evil.example",
    "https://evil.example",
    "null",
]
_failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail}]" if detail else ""))
    if not cond:
        _failures.append(label)


def answer(origin, method, path="/api/user"):
    headers = {"Origin": origin}
    if method == "OPTIONS":
        headers["Access-Control-Request-Method"] = "POST"
    r = app.test_client().open(path, method=method, headers=headers)
    return r.headers.get("Access-Control-Allow-Origin"), r.headers.get("Access-Control-Allow-Credentials")


for origin in ALLOWED:
    for method in ("GET", "OPTIONS"):
        got, creds = answer(origin, method)
        check(f"{method} from {origin} is allowed with credentials", got == origin and creds == "true", f"{got!r}, {creds!r}")
for origin in REFUSED:
    for method in ("GET", "OPTIONS"):
        got, creds = answer(origin, method)
        check(f"{method} from {origin} gets no CORS headers", got is None and creds is None, f"{got!r}, {creds!r}")

print(f"\n{len(_failures)} failed" if _failures else "\nall checks passed")
sys.exit(1 if _failures else 0)
