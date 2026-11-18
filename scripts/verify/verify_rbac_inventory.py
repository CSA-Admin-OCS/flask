#!/usr/bin/env python3
"""Verify that rbac_inventory.py reads every way a route is guarded, or not guarded, correctly.

Runs the inventory over scripts/rbac/rbac_fixture_app.py, which has one route for each pattern, and compares each
record with what the fixture's source says. Also checks that the inventory is the same on two runs, that it
notices a guard the source does not show, and that the project's own app can be inventoried. Calls no route and
touches no database.

Usage:  python scripts/verify/verify_rbac_inventory.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import json, os, subprocess, sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts", "rbac"))
os.environ.setdefault("SECRET_KEY", "verify-rbac-inventory")

import rbac_inventory as inv
from rbac_fixture_app import make_app

_failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail}]" if detail else ""))
    if not cond:
        _failures.append(label)


def records_by(records):
    return {(r["method"], r["rule"]): r for r in records}


def run_fixture(production, **kwargs):
    code = ("import json,sys; sys.path.insert(0,'scripts/rbac'); import rbac_inventory as i; from rbac_fixture_app import make_app;"
            f"print('J:'+json.dumps(i.inventory(make_app(**{kwargs!r}))))")
    env = {k: v for k, v in os.environ.items() if k != "IS_PRODUCTION"}
    env["IS_PRODUCTION"] = "true" if production else "false"
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, cwd=REPO)
    line = next(l for l in out.stdout.splitlines() if l.startswith("J:"))
    return json.loads(line[2:])


def main():
    records = inv.inventory(make_app())
    got = records_by(records)

    def route(method, rule):
        return got[(method, rule)]

    kinds = {
        ("GET", "/open"): "none",
        ("GET", "/any-login"): "login",
        ("POST", "/admin-only"): "roles",
        ("GET", "/auth-roles"): "roles",
        ("GET", "/roles-from-data"): "roles",
        ("GET", "/one-role-as-text"): "roles",
        ("GET", "/two-role-lists"): "roles",
        ("GET", "/admin-in-production"): "admin_in_production_only",
        ("GET", "/api/fixture/class-wide-roles"): "roles",
        ("GET", "/session-login"): "login",
        ("PUT", "/inline-check"): "none",
        ("DELETE", "/helper-check"): "none",
        ("GET", "/crashes-for-anonymous"): "none",
        ("PUT", "/crashes-on-the-user-object"): "none",
        ("GET", "/optional-auth"): "none",
        ("GET", "/prints-the-user"): "none",
        ("GET", "/local-variable-named-current-user"): "none",
        ("GET", "/custom-guard"): "unknown",
        ("GET", "/production-only"): "login_in_production_only",
        ("POST", "/device"): "device_key",
        ("GET", "/reads-header"): "none",
        ("GET", "/api/fixture/class-wide"): "login",
        ("POST", "/api/fixture/class-wide"): "login",
        ("GET", "/api/fixture/per-method"): "none",
        ("DELETE", "/api/fixture/per-method"): "roles",
        ("GET", "/<path:anything>"): "none",
    }
    for (method, rule), kind in kinds.items():
        check(f"{method} {rule} is read as guard '{kind}'", route(method, rule)["guard"]["kind"] == kind,
              route(method, rule)["guard"]["kind"] if (method, rule) in got else "no record")
    check("every method of every fixture route has a record (no extras beyond Flask's static route)",
          set(got) - set(kinds) <= {("GET", "/static/<path:filename>")}, str(sorted(set(got) - set(kinds))))

    check("roles are recorded as written", route("POST", "/admin-only")["guard"]["roles"] == "['Admin']"
          and route("GET", "/auth-roles")["guard"]["roles"] == "roles=['Teacher', 'Admin']"
          and route("DELETE", "/api/fixture/per-method")["guard"]["roles"] == "['Admin']")
    runtime = lambda method, rule: route(method, rule)["guard"]["runtime_roles"]
    check("the role list the running app holds is read from the guard itself", runtime("POST", "/admin-only") == ["Admin"]
          and runtime("GET", "/auth-roles") == ["Admin", "Teacher"], str(runtime("GET", "/auth-roles")))
    check("a role list that comes from data is read as the roles it came to, not as its text",
          runtime("GET", "/roles-from-data") == ["Admin", "Teacher"] and "STAFF_ROLES" in route("GET", "/roles-from-data")["guard"]["roles"])
    check("one role given as text is a list of one", runtime("GET", "/one-role-as-text") == ["Admin"])
    check("two role lists on one route: only the roles in both pass", runtime("GET", "/two-role-lists") == ["Teacher"], str(runtime("GET", "/two-role-lists")))
    check("a login with no role list, and a route with no guard, hold no role list",
          runtime("GET", "/any-login") is None and runtime("GET", "/open") is None and runtime("GET", "/session-login") is None)
    check("a role list in a class's method_decorators is read for its methods", runtime("GET", "/api/fixture/class-wide-roles") == ["Admin"]
          and runtime("GET", "/api/fixture/class-wide") is None)
    check("a role list on one method is not given to the class's other methods",
          runtime("DELETE", "/api/fixture/per-method") == ["Admin"] and runtime("GET", "/api/fixture/per-method") is None)
    check("no fixture route has a role list in the source that the running app does not show",
          not any("role_list_not_read" in r["flags"] for r in records))
    check("a decorator on one method does not guard the class's other methods",
          route("GET", "/api/fixture/per-method")["guard"]["kind"] == "none")
    check("a custom decorator is 'unknown', named, and never 'none'",
          route("GET", "/custom-guard")["guard"]["unknown"] == ["some_custom_guard"])
    check("method_decorators on a class guard every method",
          route("GET", "/api/fixture/class-wide")["decorators"][0]["name"] == "token_required")

    inline = route("PUT", "/inline-check")["body"]
    check("an inline role check and refusal in the body are found", inline["role_checks"] and "return 403" in inline["refusals"], str(inline))
    helper = route("DELETE", "/helper-check")["body"]
    check("a check one level down in a helper is found, and the helper is named",
          helper["via_helper"] == ["_refuse_non_staff"] and "abort(403)" in helper["refusals"] and helper["role_checks"], str(helper))
    header = route("GET", "/reads-header")["body"]
    check("a header read and abort(401) are found", header["credential_reads"] == ["request.headers"] and header["refusals"] == ["abort(401)"], str(header))
    check("an open route has nothing in its body", route("GET", "/open")["body"] == {
        "reads_current_user": False, "checks_authenticated": False, "role_checks": [], "refusals": [],
        "credential_reads": [], "via_helper": []})

    check("a route that reads the current user with no guard is flagged",
          "reads_current_user_without_a_guard" in route("GET", "/crashes-for-anonymous")["flags"])
    check("using an attribute of the user with no guard is flagged too",
          "reads_current_user_without_a_guard" in route("PUT", "/crashes-on-the-user-object")["flags"])
    check("asking is_authenticated first is optional login, not flagged",
          route("GET", "/optional-auth")["body"]["checks_authenticated"] and route("GET", "/optional-auth")["flags"] == [])
    check("printing the user object is not flagged", route("GET", "/prints-the-user")["flags"] == [])
    check("a local variable named current_user is not Flask-Login's user",
          route("GET", "/local-variable-named-current-user")["flags"] == [])
    check("a guarded route that reads the current user is not flagged",
          not any("reads_current_user" in f for f in route("GET", "/any-login")["flags"]))
    check("the catch-all route has no guard and no flags", route("GET", "/<path:anything>")["flags"] == [])

    check("every route lists the app-level hook", all("app_hook" in r["hooks"] for r in records if r["endpoint"] != "static"))
    check("blueprint routes list the blueprint's hook, others do not",
          "blueprint_hook" in route("GET", "/api/fixture/class-wide")["hooks"] and "blueprint_hook" not in route("GET", "/open")["hooks"])

    check("two runs give the same records", json.dumps(inv.inventory(make_app()), sort_keys=True) == json.dumps(records, sort_keys=True))

    wrapped = records_by(inv.inventory(make_app(wrap_open=True)))
    check("a wrapper the source does not explain is flagged", "wrapped_outside_the_source" in wrapped[("GET", "/open")]["flags"]
          and "wrapped_outside_the_source" not in route("GET", "/open")["flags"])
    check("a wrapper changes the recorded wrapper depth",
          wrapped[("GET", "/open")]["wrapper_depth"] == route("GET", "/open")["wrapper_depth"] + 1)

    dev, prod = run_fixture(False), run_fixture(True)
    merged = records_by(inv.merge_modes(dev, prod))
    check("a route guarded only in production differs by mode", merged[("GET", "/production-only")]["differs_by_mode"]
          and "guarded_differently_by_mode" in merged[("GET", "/production-only")]["flags"])
    admin_in_production = merged[("GET", "/admin-in-production")]
    check("a role list held only in production is recorded for that mode alone", admin_in_production["differs_by_mode"]
          and admin_in_production["modes"]["production"]["runtime_roles"] == ["Admin", "Teacher"]
          and admin_in_production["modes"]["development"]["runtime_roles"] is None, str(admin_in_production["modes"]))
    check("other routes do not differ by mode",
          not any(r["differs_by_mode"] for k, r in merged.items() if k not in (("GET", "/production-only"), ("GET", "/admin-in-production"))))

    summary = inv.summary(records)
    check("the summary counts by guard kind and names no route", "/open" not in json.dumps(summary) and summary["pairs"] == len(records))

    # the real app: it loads, every pair has a record, nothing crashes the analyser
    done = subprocess.run([sys.executable, os.path.join(REPO, "scripts", "rbac", "rbac_inventory.py")], capture_output=True, text=True, cwd=REPO)
    real = json.loads(done.stdout[done.stdout.index("{"):])
    check("the project's own app can be inventoried", done.returncode == 0 and real["pairs"] > 200, f"exit {done.returncode}, pairs {real.get('pairs')}")
    check("the real app's summary names no route", "/api" not in done.stdout)

    print(f"\n{len(_failures)} failed" if _failures else "\nall checks passed")
    sys.exit(1 if _failures else 0)


main()
