#!/usr/bin/env python3
"""rbac_inventory.py
List every route of the Flask app with what the code says about who may call it. Read-only: it loads the app,
reads its route table and the source of each route's function, and never calls a route.

This is RBAC phase 0, evidence A (the source) and B (the route table and hooks). Evidence C, what each route
answers to each kind of caller, is gathered separately. Nothing here says whether a route is meant to be open;
it records what is written and leaves the decision to triage.

  python scripts/rbac_inventory.py                      # counts only (the route list can show what is open)
  python scripts/rbac_inventory.py --out report.json    # the full record for every method-and-route pair
  python scripts/rbac_inventory.py --both-modes --out report.json   # development and IS_PRODUCTION=true, merged

The full record lists which routes are open, so write it outside the repo and do not commit or post it.

One record per method and route, with the keys documented at RECORD_KEYS below.
"""
import argparse
import ast
import collections
import inspect
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# What each guard decorator means. The name is all the source tells us, so a decorator that is not here is
# recorded as "unknown" and never as "no guard".
GUARD_DECORATORS = {
    "token_required": "login",
    "auth_required": "login",
    "login_required": "login",
    "require_device_api_key": "device_key",
    "require_auth_if_production": "login_in_production_only",
    "require_admin_if_production": "admin_in_production_only",
}
ROLE_ARG_DECORATORS = {"token_required", "auth_required"}
AUTHENTICATION_CHECKS = {"is_authenticated", "is_anonymous"}
ROLE_ATTRIBUTES = {"role", "_role"}
ROLE_CALLS = {"is_admin", "is_teacher", "is_student", "is_mentor", "is_guest"}
CREDENTIAL_ATTRIBUTES = {"headers", "cookies", "authorization"}
REFUSAL_CODES = {401, 403}

RECORD_KEYS = """
method, rule         the HTTP method and Flask's route template, for example POST /api/user/<uid>/verify
endpoint, blueprint  Flask's names for the route
file, line, function where the handler is written, relative to the repo
decorators           every decorator on the handler and on its class, as written: [{name, args}]
guard                what the decorators add up to: {kind, roles, unknown}
                     kind is one of: none, login, roles, device_key, login_in_production_only,
                     admin_in_production_only, unknown. roles is the argument text, or null.
wrapper_depth        how many wrappers the running app has around the handler
body                 what the function does about the caller, itself and one level into the helpers it
                     calls: {reads_current_user, checks_authenticated, role_checks, refusals,
                     credential_reads, via_helper}. reads_current_user means it uses an attribute of the
                     user, which an anonymous caller does not have; checks_authenticated means it asks
                     is_authenticated or is_anonymous first, so it expects anonymous callers.
hooks                before_request hooks that run for this route
flags                findings that need a human: reads_current_user_without_a_guard (uses the user's attributes
                     with no guard and no is_authenticated check: an anonymous caller would meet an error,
                     not a refusal), wrapped_outside_the_source, source_not_found,
                     guarded_differently_by_mode
"""


# ---------------------------------------------------------------- the source (evidence A)

_trees = {}


def _tree(path):
    if path not in _trees:
        with open(path, encoding="utf-8") as fh:
            _trees[path] = ast.parse(fh.read(), filename=path)
    return _trees[path]


def _in_project(path):
    if not path:
        return False
    path = os.path.abspath(path)
    return path.startswith(REPO + os.sep) and os.sep + "venv" + os.sep not in path


def _find_def(func):
    """(path, FunctionDef) for the function as written in the source, or (None, None)."""
    func = inspect.unwrap(func)
    try:
        path = inspect.getsourcefile(func)
    except TypeError:
        return None, None
    if not _in_project(path):
        return None, None
    first = func.__code__.co_firstlineno
    for node in ast.walk(_tree(path)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.__name__:
            start = min([node.lineno] + [d.lineno for d in node.decorator_list])
            if start == first or node.lineno == first:
                return path, node
    return path, None


def _decorator_record(node):
    call = node if isinstance(node, ast.Call) else None
    target = call.func if call else node
    name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", ast.unparse(target))
    args = ", ".join([ast.unparse(a) for a in call.args] + [ast.unparse(k) for k in call.keywords]) if call else ""
    return {"name": name, "args": args}


def _class_decorators(view_class):
    """Decorators a Flask-RESTful class applies to all its methods (method_decorators = [...])."""
    path, found = None, None
    try:
        path = inspect.getsourcefile(view_class)
    except TypeError:
        return []
    if not _in_project(path):
        return []
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ClassDef) and node.name == view_class.__name__:
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and any(getattr(t, "id", None) == "method_decorators" for t in stmt.targets):
                    value = stmt.value
                    items = value.elts if isinstance(value, (ast.List, ast.Tuple)) else value.values if isinstance(value, ast.Dict) else []
                    return [_decorator_record(i) for i in items]
    return []


# Decorators that only attach a function to a route: they do not wrap it
REGISTERING_DECORATORS = {"route", "get", "post", "put", "delete", "patch", "errorhandler"}

# Decorators that register or reshape a function without guarding it
HARMLESS_DECORATORS = {"route", "wraps", "staticmethod", "classmethod", "json_errors", "errorhandler", "get", "post",
                       "put", "delete", "patch", "cache", "csrf_exempt", "doc", "expect", "marshal_with", "response"}


def _guard(decorators):
    unknown = []
    kinds, roles = [], None
    for d in decorators:
        kind = GUARD_DECORATORS.get(d["name"])
        if kind:
            kinds.append(kind)
            if d["name"] in ROLE_ARG_DECORATORS and d["args"]:
                roles = d["args"]
        elif d["name"] not in HARMLESS_DECORATORS:
            unknown.append(d["name"])
    if "login" in kinds and roles:
        return {"kind": "roles", "roles": roles, "unknown": unknown}
    for kind in ("login", "device_key", "admin_in_production_only", "login_in_production_only"):
        if kind in kinds:
            return {"kind": kind, "roles": None, "unknown": unknown}
    return {"kind": "unknown" if unknown else "none", "roles": None, "unknown": unknown}


class _Body(ast.NodeVisitor):
    """What a function body does about the caller."""

    def __init__(self):
        self.reads_current_user = False
        self.checks_authenticated = False
        self.assigns_current_user = False
        self.role_checks = []
        self.refusals = []
        self.credential_reads = []
        self.calls = []

    def visit_Name(self, node):
        # a local variable that happens to be called current_user is not Flask-Login's
        if node.id == "current_user" and isinstance(node.ctx, ast.Store):
            self.assigns_current_user = True

    def visit_Attribute(self, node):
        if node.attr == "current_user" and getattr(node.value, "id", None) == "g":
            self.reads_current_user = True
        if getattr(node.value, "id", None) == "current_user":
            if node.attr in AUTHENTICATION_CHECKS:
                self.checks_authenticated = True
            else:
                self.reads_current_user = True  # an attribute of the user: an anonymous caller has none of them
        if node.attr in CREDENTIAL_ATTRIBUTES and getattr(node.value, "id", None) == "request":
            self.credential_reads.append(ast.unparse(node))
        self.generic_visit(node)

    def visit_Compare(self, node):
        parts = [node.left] + node.comparators
        if any(isinstance(p, ast.Attribute) and p.attr in ROLE_ATTRIBUTES for p in parts):
            self.role_checks.append(ast.unparse(node)[:100])
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in ROLE_CALLS:
            self.role_checks.append(ast.unparse(node)[:100])
        if name == "abort" and node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value in REFUSAL_CODES:
            self.refusals.append(f"abort({node.args[0].value})")
        if name == "decode" and getattr(func.value, "id", None) == "jwt":
            self.credential_reads.append("jwt.decode")
        if isinstance(func, ast.Name):
            self.calls.append(func.id)
        self.generic_visit(node)

    def visit_Return(self, node):
        if isinstance(node.value, ast.Tuple):
            for element in node.value.elts:
                if isinstance(element, ast.Constant) and element.value in REFUSAL_CODES:
                    self.refusals.append(f"return {element.value}")
        self.generic_visit(node)


def _read_body(node):
    visitor = _Body()
    for stmt in node.body:
        visitor.visit(stmt)
    for arg in node.args.args + node.args.kwonlyargs:
        visitor.assigns_current_user = visitor.assigns_current_user or arg.arg == "current_user"
    if visitor.assigns_current_user:
        # the name is a local variable here, so its attributes say nothing about Flask-Login's user
        visitor.reads_current_user = any(isinstance(n, ast.Attribute) and n.attr == "current_user" and getattr(n.value, "id", None) == "g"
                                         for n in ast.walk(node))
    return visitor


def _body_record(func, depth=1):
    path, node = _find_def(func)
    if node is None:
        return {"reads_current_user": False, "checks_authenticated": False, "role_checks": [], "refusals": [],
                "credential_reads": [], "via_helper": []}
    visitor = _read_body(node)
    record = {"reads_current_user": visitor.reads_current_user, "checks_authenticated": visitor.checks_authenticated,
              "role_checks": list(visitor.role_checks),
              "refusals": list(visitor.refusals), "credential_reads": list(visitor.credential_reads), "via_helper": []}
    if depth:
        seen = set()
        for name in visitor.calls:
            helper = inspect.unwrap(func).__globals__.get(name)
            if name in seen or not inspect.isfunction(helper) or helper is inspect.unwrap(func):
                continue
            seen.add(name)
            inner = _body_record(helper, depth - 1)
            found = [key for key in ("role_checks", "refusals", "credential_reads") if inner[key]]
            if found or inner["reads_current_user"]:
                record["via_helper"].append(name)
                record["reads_current_user"] = record["reads_current_user"] or inner["reads_current_user"]
                record["checks_authenticated"] = record["checks_authenticated"] or inner["checks_authenticated"]
                for key in ("role_checks", "refusals", "credential_reads"):
                    record[key] += inner[key]
    return record


# ---------------------------------------------------------------- the route table (evidence B)


def _handlers(app, rule):
    """[(method, function, class or None)] for one rule: what Flask would call for each method."""
    view = app.view_functions[rule.endpoint]
    view_class = getattr(view, "view_class", None)
    methods = sorted(m for m in rule.methods if m not in ("HEAD", "OPTIONS"))
    out = []
    for method in methods:
        if view_class is not None:
            handler = getattr(view_class, method.lower(), None)
            if handler is not None:
                out.append((method, handler, view_class))
        else:
            out.append((method, view, None))
    return out


def _wrapper_depth(func):
    depth = 0
    while hasattr(func, "__wrapped__"):
        func, depth = func.__wrapped__, depth + 1
    return depth


def _hooks(app, endpoint):
    names = [f.__name__ for f in app.before_request_funcs.get(None, [])]
    blueprint = endpoint.split(".")[0] if "." in endpoint else None
    if blueprint:
        names += [f.__name__ for f in app.before_request_funcs.get(blueprint, [])]
    return names


def inventory(app):
    """A record for every method-and-route pair in this app. Sorted, so two runs give the same list."""
    records = []
    for rule in app.url_map.iter_rules():
        hooks = _hooks(app, rule.endpoint)
        for method, handler, view_class in _handlers(app, rule):
            path, node = _find_def(handler)
            decorators = []
            if node is not None:
                decorators += [_decorator_record(d) for d in node.decorator_list]
            expected_wrappers = len([d for d in decorators if d["name"] not in REGISTERING_DECORATORS])
            if view_class is not None:
                decorators += _class_decorators(view_class)
            guard = _guard(decorators)
            body = _body_record(handler)
            flags = []
            if node is None:
                flags.append("source_not_found")
            if _wrapper_depth(handler) > expected_wrappers:
                flags.append("wrapped_outside_the_source")  # something wraps it that no decorator in the source explains
            if body["reads_current_user"] and not body["checks_authenticated"] and guard["kind"] == "none":
                flags.append("reads_current_user_without_a_guard")
            records.append({
                "method": method, "rule": rule.rule, "endpoint": rule.endpoint,
                "blueprint": rule.endpoint.split(".")[0] if "." in rule.endpoint else None,
                "file": os.path.relpath(path, REPO) if path else None,
                "line": node.lineno if node is not None else None,
                "function": f"{view_class.__name__}.{handler.__name__}" if view_class else handler.__name__,
                "decorators": decorators, "guard": guard, "body": body, "hooks": hooks, "flags": flags,
                "wrapper_depth": _wrapper_depth(handler),
            })
    records.sort(key=lambda r: (r["rule"], r["method"]))
    return records


def summary(records):
    kinds = collections.Counter(r["guard"]["kind"] for r in records)
    flags = collections.Counter(f for r in records for f in r["flags"])
    inline_only = sum(1 for r in records if r["guard"]["kind"] == "none" and (r["body"]["role_checks"] or r["body"]["refusals"]))
    return {"pairs": len(records), "by_guard": dict(sorted(kinds.items())), "inline_check_without_decorator": inline_only,
            "flags": dict(sorted(flags.items()))}


# ---------------------------------------------------------------- running it


def _load_project_app():
    sys.path.insert(0, REPO)
    os.chdir(REPO)
    os.environ.setdefault("SECRET_KEY", "rbac-inventory")
    import __init__ as package
    import main  # noqa: F401  registers every model and blueprint
    return package.app


def merge_modes(dev, prod):
    """One list from a development run and a production run, saying where the two differ."""
    key = lambda r: (r["rule"], r["method"])
    by_dev, by_prod = {key(r): r for r in dev}, {key(r): r for r in prod}
    merged = []
    for k in sorted(set(by_dev) | set(by_prod)):
        record = dict(by_prod.get(k) or by_dev.get(k))
        d, p = by_dev.get(k), by_prod.get(k)
        record["modes"] = {"development": None if d is None else {"wrapper_depth": d["wrapper_depth"]},
                           "production": None if p is None else {"wrapper_depth": p["wrapper_depth"]}}
        record["differs_by_mode"] = d is None or p is None or d["wrapper_depth"] != p["wrapper_depth"]
        if record["differs_by_mode"]:
            record["flags"] = sorted(set(record["flags"]) | {"guarded_differently_by_mode"})
        merged.append(record)
    return merged


def main_cli():
    parser = argparse.ArgumentParser(description="List every route and what the code says about who may call it.")
    parser.add_argument("--out", help="write the full records here (JSON)")
    parser.add_argument("--both-modes", action="store_true", help="run in development and in production mode and merge")
    parser.add_argument("--mode-run", choices=["development", "production"], help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.both_modes:
        runs = {}
        for mode, flag in (("development", "false"), ("production", "true")):
            env = {k: v for k, v in os.environ.items() if k not in ("IS_PRODUCTION",)}
            env["IS_PRODUCTION"] = flag
            env.setdefault("SECRET_KEY", "rbac-inventory")
            done = subprocess.run([sys.executable, os.path.abspath(__file__), "--mode-run", mode],
                                  env=env, capture_output=True, text=True)
            marker = "RBAC_JSON:"
            line = next((l for l in done.stdout.splitlines() if l.startswith(marker)), None)
            if done.returncode != 0 or line is None:
                sys.exit(f"{mode} run failed:\n{done.stderr[-800:]}")
            runs[mode] = json.loads(line[len(marker):])
        records = merge_modes(runs["development"], runs["production"])
    elif args.mode_run:
        records = inventory(_load_project_app())
        print("RBAC_JSON:" + json.dumps(records))
        return
    else:
        records = inventory(_load_project_app())

    print(json.dumps(summary(records), indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=1, sort_keys=True)
        print(f"wrote {len(records)} records to {args.out}")


if __name__ == "__main__":
    main_cli()
