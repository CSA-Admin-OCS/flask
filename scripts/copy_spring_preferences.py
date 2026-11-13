#!/usr/bin/env python3
"""copy_spring_preferences.py
One-time copy of Spring's user_preferences rows into Flask's, matched by uid
(Spring person.uid = Flask users._uid).

Spring's database is only read. A Flask user who already has preferences keeps them (they
saved on Flask after the switch, so theirs is newer). Rows go through the same checks as
PUT /api/user/preferences; a row that fails, or whose uid has no Flask user, is listed and
skipped. Safe to run again: copied users now have preferences and are skipped.

Usage (from the flask repo root):
  python scripts/copy_spring_preferences.py --from sqlite:///../spring/volumes/sqlite.db --check
  python scripts/copy_spring_preferences.py --from 'mysql+pymysql://USER:PASS@HOST:3306/SPRING_DB'

--from is a SQLAlchemy URL to Spring's database. --check reports and changes nothing.
Exit: 0 done (or nothing to do), 1 failed.
"""
import argparse
import os
import sys

import sqlalchemy as sa

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Spring's snake_case columns -> the JSON keys Flask uses
COLUMNS = {
    'background_color': 'backgroundColor', 'text_color': 'textColor', 'font_family': 'fontFamily',
    'font_size': 'fontSize', 'accent_color': 'accentColor', 'selection_color': 'selectionColor',
    'button_style': 'buttonStyle', 'language': 'language', 'tts_voice': 'ttsVoice',
    'tts_rate': 'ttsRate', 'tts_pitch': 'ttsPitch', 'tts_volume': 'ttsVolume',
    'custom_themes': 'customThemes',
}


def read_spring(spring_url):
    """[(uid, {jsonKey: value})] for every Spring row, read-only."""
    cols = ', '.join(f'up.{c}' for c in COLUMNS)
    engine = sa.create_engine(spring_url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(sa.text(
                f'SELECT p.uid, {cols} FROM user_preferences up JOIN person p ON p.id = up.person_id'
            )).all()
    finally:
        engine.dispose()
    return [(row[0], dict(zip(COLUMNS.values(), row[1:]))) for row in rows]


def copy(spring_rows, check):
    """Copy into the Flask database the app is configured for. Returns counts by outcome."""
    from model.user import User
    from model.user_preferences import UserPreferences

    done = {'copied': [], 'kept Flask copy': [], 'no Flask user': [], 'invalid': []}
    for uid, body in spring_rows:
        user = User.query.filter_by(_uid=uid).first()
        if user is None:
            done['no Flask user'].append(uid)
            continue
        if user.preferences is not None:
            done['kept Flask copy'].append(uid)
            continue
        _, error = UserPreferences.validate(body)
        if error:
            done['invalid'].append(f'{uid} ({error})')
            continue
        if not check:
            UserPreferences(user.id).update(body)
        done['copied'].append(uid)
    return done


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    parser.add_argument('--from', dest='spring_url', required=True, help="SQLAlchemy URL of Spring's database")
    parser.add_argument('--check', action='store_true', help='report only, change nothing')
    args = parser.parse_args()

    from main import app  # registers every model
    spring_rows = read_spring(args.spring_url)
    with app.app_context():
        done = copy(spring_rows, args.check)

    print(f"Spring rows: {len(spring_rows)}{'   (--check: nothing written)' if args.check else ''}")
    for outcome, uids in done.items():
        label = 'Would copy' if args.check and outcome == 'copied' else outcome[0].upper() + outcome[1:]
        print(f"{label}: {len(uids)}")
        for uid in uids if outcome != 'copied' else []:
            print(f'    {uid}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
