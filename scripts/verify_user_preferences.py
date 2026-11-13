#!/usr/bin/env python3
"""Verify /api/user/preferences (moved from Spring) end to end.

Runs the real app against a throwaway SQLite database and checksums the real dev DB
before and after to prove it was never touched.

Usage:  python scripts/verify_user_preferences.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import hashlib, os, secrets, sys, tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.environ.setdefault("SECRET_KEY", "verify-user-preferences")

REAL_DB = os.path.join(REPO, "instance", "volumes", "user_management.db")
PASSWORD = "Aa1!" + secrets.token_urlsafe(16)
URL = "/api/user/preferences"
_failures = []

# Spring's user_preferences table exactly as Hibernate made it (spring/volumes/sqlite.db), and the person columns used
SPRING_SCHEMA = """
CREATE TABLE person (id integer primary key, uid varchar(255));
CREATE TABLE "user_preferences" ("font_size" integer, "tts_pitch" float, "tts_rate" float, "tts_volume" float, "id" integer, "person_id" bigint unique, "language" varchar(10), "accent_color" varchar(20), "background_color" varchar(20), "button_style" varchar(20), "selection_color" varchar(20), "text_color" varchar(20), "tts_voice" varchar(100), "custom_themes" "TEXT", "font_family" varchar(255), primary key ("id"));
"""


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
    engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(prefix='prefs-'), 'new.db')}")
    with app.app_context():
        db.engines[None] = engine
    import main  # noqa: F401  registers every model and blueprint
    from model.user import User
    from model.user_preferences import UserPreferences, FIELDS
    UNSET = {**{key: None for key in FIELDS}, "id": None, "unset": list(FIELDS)}
    app.config["TESTING"] = True

    with app.app_context():
        db.create_all()
        for uid in ("zz_alice", "zz_bob"):
            db.session.add(User(name=uid, uid=uid, password=PASSWORD))
        db.session.commit()
        for uid in ("zz_alice", "zz_bob"):
            User.query.filter_by(_uid=uid).first().activate()

        anon = app.test_client()
        check("GET without login is refused", anon.get(URL).status_code == 401)
        check("PUT without login is refused", anon.put(URL, json={"fontSize": 20}).status_code == 401)

        alice, bob = app.test_client(), app.test_client()
        check("alice logs in", alice.post("/api/authenticate", json={"uid": "zz_alice", "password": PASSWORD}).status_code == 200)
        check("bob logs in", bob.post("/api/authenticate", json={"uid": "zz_bob", "password": PASSWORD}).status_code == 200)

        r = alice.get(URL)
        check("GET with nothing saved reads every preference as unset", r.status_code == 200 and r.get_json() == UNSET, r.get_json())
        check("GET does not save a row", UserPreferences.query.count() == 0)

        r = alice.post(URL, json={"backgroundColor": "#ffffff", "fontSize": 18})
        body = r.get_json()
        check("POST creates with 201", r.status_code == 201, r.status_code)
        check("POST sets the given fields and leaves the rest unset",
              body["backgroundColor"] == "#ffffff" and body["fontSize"] == 18 and body["textColor"] is None and body["id"]
              and "backgroundColor" not in body["unset"] and "textColor" in body["unset"], body)
        check("unset preferences are stored as null, not as a default",
              UserPreferences.query.first().textColor is None and len(UserPreferences.query.first().unset()) == len(FIELDS) - 2)
        check("a second POST is a 409", alice.post(URL, json={"fontSize": 12}).status_code == 409)

        alice.put(URL, json={"textColor": "#000000"})
        r = alice.put(URL, json={"ttsRate": 2, "language": "es", "textColor": None, "unknown": "x"})
        body = r.get_json()
        check("PUT sets the given fields, unsets the null ones, leaves the missing ones", r.status_code == 200
              and body["ttsRate"] == 2.0 and body["language"] == "es" and body["backgroundColor"] == "#ffffff"
              and body["textColor"] is None and "textColor" in body["unset"] and "unknown" not in body, body)
        check("PUT stores an int rate as a float", isinstance(body["ttsRate"], float))

        themes = '{"cozy": {"backgroundColor": "#2b1d14"}}'
        alice.put(URL, json={"customThemes": themes})
        check("customThemes round-trips as a JSON string", alice.get(URL).get_json()["customThemes"] == themes)

        check("a too-long color is a 400", alice.put(URL, json={"accentColor": "#" * 21}).status_code == 400)
        check("a word fontSize is a 400", alice.put(URL, json={"fontSize": "big"}).status_code == 400)
        check("a NaN rate is a 400", alice.put(URL, data='{"ttsRate": NaN}', content_type="application/json").status_code == 400)
        check("a list color is a 400", alice.put(URL, json={"textColor": ["#fff"]}).status_code == 400)
        check("a boolean fontSize is a 400", alice.put(URL, json={"fontSize": True}).status_code == 400)
        check("a non-object body is a 400", alice.put(URL, json=[1, 2]).status_code == 400)
        check("a rejected PUT changed nothing", alice.get(URL).get_json()["fontSize"] == 18)
        r = alice.put(URL, json={"fontSize": "16", "ttsPitch": "1.5"})
        check("numeric strings are accepted, as Spring did", r.status_code == 200
              and r.get_json()["fontSize"] == 16 and r.get_json()["ttsPitch"] == 1.5, r.get_json())
        check("a decimal fontSize is cut to a whole one", alice.put(URL, json={"fontSize": 14.7}).get_json()["fontSize"] == 14)
        alice.put(URL, json={"fontSize": 18})

        check("bob still sees everything unset", bob.get(URL).get_json() == UNSET)
        r = bob.put(URL, json={"buttonStyle": "square"})
        check("PUT with nothing saved creates the row", r.status_code == 200 and r.get_json()["buttonStyle"] == "square")
        check("bob's save did not touch alice's", alice.get(URL).get_json()["buttonStyle"] is None)
        check("one row per user", UserPreferences.query.count() == 2)

        r = alice.delete(URL)
        check("DELETE removes the row with a 204", r.status_code == 204 and UserPreferences.query.count() == 1)
        check("GET after DELETE reads every preference as unset", alice.get(URL).get_json() == UNSET)
        check("DELETE with nothing saved is still 204", alice.delete(URL).status_code == 204)

        User.query.filter_by(_uid="zz_bob").first().delete()
        check("deleting a user deletes their preferences", UserPreferences.query.count() == 0)

        # The one-time copy from Spring, against a fake Spring database with Spring's real schema
        import sqlite3
        from copy_spring_preferences import read_spring, copy
        spring_path = os.path.join(tempfile.mkdtemp(prefix='spring-'), 'sqlite.db')
        con = sqlite3.connect(spring_path)
        con.executescript(SPRING_SCHEMA)
        con.executemany("INSERT INTO person (id, uid) VALUES (?, ?)", [(1, "zz_alice"), (2, "zz_carol"), (3, "zz_nobody"), (4, "zz_dave")])
        con.executemany("INSERT INTO user_preferences (id, person_id, background_color, text_color, font_family, font_size,"
                        " accent_color, selection_color, button_style, language, tts_voice, tts_rate, tts_pitch, tts_volume,"
                        " custom_themes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
            (1, 1, "#000000", "#ffffff", "Arial", 20, "#ff0000", "#ff0000", "square", "fr", "Amelie", 1.2, 0.9, 0.5, '{"a": {}}'),
            (2, 2, "#111111", "#eeeeee", "Georgia", 16, "#00ff00", "#00ff00", "rounded", "", "", 1.0, 1.0, 0.0, "{}"),
            (3, 3, "#222222", "#dddddd", "Arial", 14, "#0000ff", "#0000ff", "rounded", "", "", 1.0, 1.0, 1.0, "{}"),
            (4, 4, "#" * 30, "#cccccc", "Arial", 14, "#0000ff", "#0000ff", "rounded", "", "", 1.0, 1.0, 1.0, "{}"),
        ])
        con.commit(); con.close()
        spring_before = sha256(spring_path)
        for uid in ("zz_carol", "zz_dave"):
            db.session.add(User(name=uid, uid=uid, password=PASSWORD))
        db.session.commit()
        alice.put(URL, json={"backgroundColor": "#abcdef"})  # alice already saved on Flask

        rows = read_spring(f"sqlite:///{spring_path}")
        check("all Spring rows are read with their uid", sorted(u for u, _ in rows) == ["zz_alice", "zz_carol", "zz_dave", "zz_nobody"])
        done = copy(rows, check=True)
        check("--check writes nothing", UserPreferences.query.count() == 1 and done["copied"] == ["zz_carol"], done)
        done = copy(rows, check=False)
        check("a user with no Flask preferences is copied", done["copied"] == ["zz_carol"], done)
        check("a user who saved on Flask keeps the Flask copy", done["kept Flask copy"] == ["zz_alice"]
              and alice.get(URL).get_json()["backgroundColor"] == "#abcdef", done)
        check("a uid with no Flask user is skipped", done["no Flask user"] == ["zz_nobody"], done)
        check("a row that fails the checks is skipped", len(done["invalid"]) == 1 and done["invalid"][0].startswith("zz_dave"), done)
        carol = UserPreferences.query.filter_by(user_id=User.query.filter_by(_uid="zz_carol").first().id).first().read()
        check("every copied field matches Spring's", carol["backgroundColor"] == "#111111" and carol["fontFamily"] == "Georgia"
              and carol["fontSize"] == 16 and carol["ttsVolume"] == 0.0 and carol["customThemes"] == "{}", carol)
        check("running it again copies nothing", copy(rows, check=False)["copied"] == [])
        check("the Spring database was only read", sha256(spring_path) == spring_before)

    real_after = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    check("the real dev database was not touched", real_before == real_after)

    print(f"\n{'ALL PASSED' if not _failures else f'{len(_failures)} FAILED'}")
    return 0 if not _failures else 1


if __name__ == "__main__":
    sys.exit(main())
