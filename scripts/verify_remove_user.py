#!/usr/bin/env python3
"""Verify scripts/remove_user.py: a dry run changes nothing, staff and accounts with other data are refused,
and a real run removes the user and exactly their own data.

Runs the real app against a throwaway SQLite database with foreign keys enforced (like production), and
checksums the real dev DB before and after to prove it was never touched.

Usage:  python scripts/verify_remove_user.py        (from the flask repo root)
Exit:   0 all checks passed, 1 otherwise.
"""
import hashlib, io, os, sys, tempfile
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "scripts"))
os.environ.setdefault("SECRET_KEY", "verify-remove-user")

REAL_DB = os.path.join(REPO, "instance", "volumes", "user_management.db")
PASSWORD = "Aa1!TestPass9"
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

    from sqlalchemy import create_engine, event, text
    from main import app, db  # registers every model
    engine = create_engine(f"sqlite:///{os.path.join(tempfile.mkdtemp(prefix='removeuser-'), 'new.db')}")

    @event.listens_for(engine, "connect")
    def foreign_keys_on(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")  # the database refuses what production's would
    with app.app_context():
        db.engines[None] = engine
    app.config["TESTING"] = True
    import remove_user
    from model.user import User, Section
    from model.microblog import MicroBlog
    from model.persona import Persona, UserPersona
    from model.classroom import Classroom

    with app.app_context():
        db.create_all()
        for uid, role in (("gone", "User"), ("bystander", "User"), ("teach", "Teacher"), ("boss", "Admin"), ("owner", "User"),
                          ("poster", "User"), ("extra", "User"), ("member", "User"), ("alsogone", "User")):
            User(name=uid.title() + " Person", uid=uid, password=PASSWORD, role=role).create()
        ids = {u._uid: u.id for u in User.query.all()}
        section = Section(name="Section", abbreviation="S"); db.session.add(section)
        persona = Persona(_alias="p", _category="student", _bio_map={}); db.session.add(persona)
        db.session.commit()
        for who in ("gone", "bystander"):
            db.session.add(MicroBlog(user_id=ids[who], content=f"{who} post"))
            db.session.add(UserPersona(User.query.get(ids[who]), persona))
            db.session.execute(text("INSERT INTO user_sections (user_id, section_id) VALUES (:u, :s)"), {"u": ids[who], "s": section.id})
        classroom = Classroom(name="Class", school_name="School", owner_teacher_id=ids["owner"]); db.session.add(classroom); db.session.commit()
        db.session.execute(text("INSERT INTO classroom_student (student_id, classroom_id) VALUES (:u, :c)"), {"u": ids["gone"], "c": classroom.id})
        db.session.commit()
        # a table the models know nothing about, that still points at a user: only the database knows it
        db.session.execute(text("CREATE TABLE zz_unknown (id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id))"))
        db.session.execute(text("INSERT INTO zz_unknown (user_id) VALUES (:u)"), {"u": ids["extra"]})
        db.session.commit()

    def n(sql, **p):
        with app.app_context():
            return db.session.execute(text(sql), p).scalar()

    def run(uids, apply=False, also=()):
        out = io.StringIO()
        with redirect_stdout(out):
            code = remove_user.remove_users(uids, apply=apply, also=also)
        return code, out.getvalue()

    users, posts = n("SELECT COUNT(*) FROM users"), n("SELECT COUNT(*) FROM microblogs")
    code, out = run(["gone"])
    check("a dry run lists the user, their post and their links, and says it changed nothing (exit 0)",
          code == 0 and "gone" in out and "microblogs: 1" in out and "DRY RUN" in out, f"{code} {out}")
    check("and changes nothing", n("SELECT COUNT(*) FROM users") == users and n("SELECT COUNT(*) FROM microblogs") == posts and n("SELECT COUNT(*) FROM user_sections") == 2)
    code, out = run(["nobody-here"], apply=True)
    check("a uid nobody has is reported and fails (exit 1), changing nothing", code == 1 and "no user" in out.lower() and n("SELECT COUNT(*) FROM users") == users, f"{code} {out}")
    for staff in ("teach", "boss"):
        code, out = run([staff], apply=True)
        check(f"a {'Teacher' if staff == 'teach' else 'Admin'} is refused even with --apply", code == 1 and "staff" in out.lower() and n("SELECT COUNT(*) FROM users WHERE _uid=:u", u=staff) == 1, f"{code} {out}")
    code, out = run(["owner"], apply=True)
    check("a user who owns a classroom is refused, naming it, and nothing changes", code == 1 and "classrooms" in out and n("SELECT COUNT(*) FROM users WHERE _uid='owner'") == 1, f"{code} {out}")
    code, out = run(["extra"], apply=True)
    check("a table only the database knows about, that points at the user, stops it too", code == 1 and "zz_unknown" in out and n("SELECT COUNT(*) FROM users WHERE _uid='extra'") == 1, f"{code} {out}")
    code, out = run(["gone"], apply=True, also=("no_such_table",))
    check("--also a table that does not point at users is an error, and nothing changes", code == 1 and n("SELECT COUNT(*) FROM users WHERE _uid='gone'") == 1, f"{code} {out}")
    code, out = run(["extra"], apply=True, also=("zz_unknown",))
    check("--also names a table to delete the user's rows from too, as a deliberate choice", code == 0 and n("SELECT COUNT(*) FROM users WHERE _uid='extra'") == 0 and n("SELECT COUNT(*) FROM zz_unknown") == 0, f"{code} {out}")

    code, out = run(["gone"], apply=True)
    check("a real run removes the user and says so (exit 0)", code == 0 and "DONE" in out and n("SELECT COUNT(*) FROM users WHERE _uid='gone'") == 0, f"{code} {out}")
    check("with their post, persona link, section link and classroom link", n("SELECT COUNT(*) FROM microblogs") == posts - 1 and n("SELECT COUNT(*) FROM user_personas") == 1
          and n("SELECT COUNT(*) FROM user_sections") == 1 and n("SELECT COUNT(*) FROM classroom_student") == 0)
    check("and nobody else's account, post or links", n("SELECT COUNT(*) FROM users WHERE _uid='bystander'") == 1 and n("SELECT COUNT(*) FROM microblogs") == posts - 1 and n("SELECT COUNT(*) FROM user_sections") == 1)
    check("it reminds you that a Spring account, if there is one, is separate", "Spring" in out, out)
    code, out = run(["gone"], apply=True)
    check("running it again finds nobody (exit 1)", code == 1 and "no user" in out.lower())

    code, out = run(["alsogone", "owner"], apply=True)
    check("with several uids, each is its own transaction: one is removed, the one that is refused is not, and the exit is 1",
          code == 1 and n("SELECT COUNT(*) FROM users WHERE _uid='alsogone'") == 0 and n("SELECT COUNT(*) FROM users WHERE _uid='owner'") == 1, f"{code} {out}")

    real_after = sha256(REAL_DB) if os.path.exists(REAL_DB) else None
    check("the real dev database was not touched", real_before == real_after)
    print(f"\n{'ALL PASSED' if not _failures else f'{len(_failures)} FAILED'}")
    sys.exit(1 if _failures else 0)


if __name__ == "__main__":
    main()
