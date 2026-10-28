#!/usr/bin/env python3
"""Verify what the sign-up form is told by Flask: the schools to choose from (model/dataconfigs/schools.json) and the
account types it offers and how each behaves (model/dataconfigs/account_types.json).

Runs the real app against a throwaway SQLite database, and checksums the real dev DB before and
after to prove it was never touched.

Usage:  python scripts/verify_signup_options.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import copy, hashlib, json, os, sys, tempfile
from unittest.mock import patch

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
os.environ.setdefault("SECRET_KEY", "verify-signup-options")

REAL_DB = os.path.join(REPO, "instance", "volumes", "user_management.db")
# the schools the sign-up form listed before they became data
FORM_SCHOOLS = [("Abraxas High School", "Abraxas"), ("Del Norte High School", "Del Norte"), ("Mt Carmel High School", "Mt Carmel"),
                ("Poway High School", "Poway"), ("Poway to Palomar", "Poway to Palomar"),
                ("Rancho Bernardo High School", "Rancho Bernardo"), ("Westview High School", "Westview")]
_failures = []


def check(label, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + label + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        _failures.append(label)


def sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main():
    real_before = sha256(REAL_DB) if os.path.exists(REAL_DB) else None

    import __init__ as pkg
    from sqlalchemy import create_engine
    app, db = pkg.app, pkg.db
    with app.app_context():
        db.engines[None] = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(prefix='signupopts-'), 'new.db')}")
    import main  # noqa: F401  registers every model and blueprint
    from model import account_types, schools
    app.config["TESTING"] = True

    with open(os.path.join(REPO, "model", "dataconfigs", "schools.json"), encoding="utf-8") as fh:
        on_disk = json.load(fh)

    with app.test_client() as c:  # nobody is logged in: the sign-up form is shown to people with no account
        r = c.get("/api/signup-options")
        body = r.get_json() or {}
        check("anyone can ask what the sign-up form offers, with no login (200)", r.status_code == 200, r.status_code)
        check("it lists the schools from model/dataconfigs/schools.json, in that order", body.get("schools") == on_disk["schools"], str(body.get("schools"))[:120])
        check("each school has a name to send and a label to show", all(set(s) == {"name", "label"} and s["name"] and s["label"] for s in body.get("schools", [])))
        check("the list is the seven schools the form had before it was data",
              [(s["name"], s["label"]) for s in body.get("schools", [])] == FORM_SCHOOLS, str(body.get("schools"))[:160])
        check("it offers the schools and the account types, and the type to start on", set(body) == {"schools", "account_types", "default_account_type"}, str(sorted(body)))
        check("it only answers GET (POST 405, DELETE 405)", c.post("/api/signup-options", json={}).status_code == 405 and c.delete("/api/signup-options").status_code == 405)

        changed = copy.deepcopy(schools._data)
        changed["schools"] = [{"name": "Test Academy", "label": "Test"}]
        with patch.object(schools, "_data", changed):
            check("the list follows the data: change the data and the answer changes", c.get("/api/signup-options").get_json()["schools"] == [{"name": "Test Academy", "label": "Test"}])
        check("and follows it back again", c.get("/api/signup-options").get_json()["schools"] == on_disk["schools"])

        # ---- the account types
        types = {t["id"]: t for t in body.get("account_types", [])}
        check("the types are listed in the order of the data, and the type to start on is the data's default",
              list(types) == ["student", "mentor", "guest"] and body.get("default_account_type") == account_types._data["default_account_type"], str(list(types)))
        keys = {"id", "label", "asks_school", "email_required", "spring_account", "google_step", "requires_open_window", "note"}
        check("each type says only what the form needs: how to show it and how it behaves", all(set(t) == keys for t in types.values()), str([sorted(set(t) ^ keys) for t in types.values()]))
        check("it does not tell anyone the roles, lifetimes or limits behind a type",
              not any(k in t for t in types.values() for k in ("role", "lifetime_hours", "allowed_requests", "google_verified_domains", "github_check")))
        behaviour = lambda t: (t["label"], t["asks_school"], t["email_required"], t["spring_account"], t["google_step"], t["requires_open_window"])
        check("a student: asks the school, needs an email, gets a Spring account, verifies with Google", behaviour(types["student"]) == ("I am a Student", True, True, True, True, False), str(types["student"]))
        check("a mentor: no school, needs an email, gets a Spring account, no Google step", behaviour(types["mentor"]) == ("I am a Mentor", False, True, True, False, False), str(types["mentor"]))
        check("a guest: no school, email optional, no Spring account, no Google step, only while the Guest Window is open",
              behaviour(types["guest"]) == ("I am a guest", False, False, False, False, True), str(types["guest"]))
        check("only a guest has a note to show, and it is text", types["student"]["note"] is None and types["mentor"]["note"] is None
              and isinstance(types["guest"]["note"], str) and types["guest"]["note"].strip() != "", str(types["guest"]["note"]))

        extra = copy.deepcopy(account_types._data)
        extra["account_types"]["observer"] = {"role": "Observer", "google_verified_domains": ["school.example"], "staff_created": False,
                                              "signup_label": "I am an observer", "asks_school": False, "email_required": False, "spring_account": False, "signup_note": "Watch only."}
        with patch.object(account_types, "_data", extra):
            seen = {t["id"]: t for t in c.get("/api/signup-options").get_json()["account_types"]}
            check("a type added to the data is offered, with its own behaviour, and a Google step because it has a Google domain",
                  "observer" in seen and behaviour(seen["observer"]) == ("I am an observer", False, False, False, True, False) and seen["observer"]["note"] == "Watch only.", str(seen.get("observer")))
        hidden = copy.deepcopy(account_types._data)
        del hidden["account_types"]["mentor"]["signup_label"]
        with patch.object(account_types, "_data", hidden):
            check("a type with no signup_label is not offered at sign-up", [t["id"] for t in c.get("/api/signup-options").get_json()["account_types"]] == ["student", "guest"])
        school = copy.deepcopy(account_types._data)
        school["account_types"]["mentor"]["asks_school"] = True
        with patch.object(account_types, "_data", school):
            check("what a type does follows the data: a mentor made to ask the school does", {t["id"]: t for t in c.get("/api/signup-options").get_json()["account_types"]}["mentor"]["asks_school"] is True)

    def refused(mutate):
        bad = copy.deepcopy(schools._data)
        mutate(bad)
        try:
            schools._check(bad)
            return False
        except ValueError:
            return True
    check("startup refuses data with no schools key, an empty list, or a list that is not a list",
          refused(lambda d: d.pop("schools")) and refused(lambda d: d.update(schools=[])) and refused(lambda d: d.update(schools="Poway")))
    check("startup refuses a school that is not a name and a label", refused(lambda d: d["schools"].append("Poway"))
          and refused(lambda d: d["schools"].append({"name": "X"})) and refused(lambda d: d["schools"].append({"name": "X", "label": "X", "extra": 1})))
    check("startup refuses a blank or non-text name or label",
          refused(lambda d: d["schools"].append({"name": " ", "label": "X"})) and refused(lambda d: d["schools"].append({"name": "X", "label": ""}))
          and refused(lambda d: d["schools"].append({"name": 7, "label": "X"})))
    check("startup refuses two schools with the same name", refused(lambda d: d["schools"].append(dict(d["schools"][0]))))

    def type_refused(mutate):
        bad = copy.deepcopy(account_types._data)
        mutate(bad)
        try:
            account_types._check(bad)
            return False
        except ValueError:
            return True
    guest = lambda d: d["account_types"]["guest"]
    check("startup refuses asks_school, email_required or spring_account that is not true or false",
          all(type_refused(lambda d, k=k: guest(d).update({k: "no"})) for k in ("asks_school", "email_required", "spring_account")))
    check("startup refuses a signup_label or signup_note that is blank or not text",
          all(type_refused(lambda d, k=k, v=v: guest(d).update({k: v})) for k in ("signup_label", "signup_note") for v in ("", "  ", 7, True)))
    check("startup refuses a default account type that the form does not offer", type_refused(lambda d: d["account_types"]["student"].pop("signup_label")))

    real_after = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    check("the real dev database was not touched", real_before == real_after)

    print(f"\n{'ALL PASSED' if not _failures else f'{len(_failures)} FAILED'}")
    sys.exit(1 if _failures else 0)


if __name__ == "__main__":
    main()
