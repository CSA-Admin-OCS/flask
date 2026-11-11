"""One row of styling, language and text-to-speech preferences per user, moved over from
Spring's UserPreferences. The JSON keys match Spring's, so the frontend only changes its base URL."""
import math

from __init__ import db

# JSON key (also the column name): (python type, max string length or None)
FIELDS = {
    'backgroundColor': (str, 20),
    'textColor': (str, 20),
    'fontFamily': (str, 255),
    'fontSize': (int, None),
    'accentColor': (str, 20),
    'selectionColor': (str, 20),
    'buttonStyle': (str, 20),
    'language': (str, 10),
    'ttsVoice': (str, 100),
    'ttsRate': (float, None),
    'ttsPitch': (float, None),
    'ttsVolume': (float, None),
    'customThemes': (str, None),
}

DEFAULTS = {
    'backgroundColor': '#0b1220',
    'textColor': '#e6eef8',
    'fontFamily': "Inter, system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial",
    'fontSize': 14,
    'accentColor': '#3b82f6',
    'selectionColor': '#3b82f6',
    'buttonStyle': 'rounded',
    'language': '',
    'ttsVoice': '',
    'ttsRate': 1.0,
    'ttsPitch': 1.0,
    'ttsVolume': 1.0,
    'customThemes': '{}',
}


class UserPreferences(db.Model):
    __tablename__ = 'user_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    backgroundColor = db.Column(db.String(20), default=DEFAULTS['backgroundColor'])
    textColor = db.Column(db.String(20), default=DEFAULTS['textColor'])
    fontFamily = db.Column(db.String(255), default=DEFAULTS['fontFamily'])
    fontSize = db.Column(db.Integer, default=DEFAULTS['fontSize'])
    accentColor = db.Column(db.String(20), default=DEFAULTS['accentColor'])
    selectionColor = db.Column(db.String(20), default=DEFAULTS['selectionColor'])
    buttonStyle = db.Column(db.String(20), default=DEFAULTS['buttonStyle'])
    language = db.Column(db.String(10), default=DEFAULTS['language'])
    ttsVoice = db.Column(db.String(100), default=DEFAULTS['ttsVoice'])
    ttsRate = db.Column(db.Float, default=DEFAULTS['ttsRate'])
    ttsPitch = db.Column(db.Float, default=DEFAULTS['ttsPitch'])
    ttsVolume = db.Column(db.Float, default=DEFAULTS['ttsVolume'])
    customThemes = db.Column(db.Text, default=DEFAULTS['customThemes'])

    # Deleting a user deletes their preferences.
    user = db.relationship('User', backref=db.backref('preferences', uselist=False, cascade='all, delete-orphan'))

    def __init__(self, user_id):
        self.user_id = user_id
        for key, value in DEFAULTS.items():
            setattr(self, key, value)

    @staticmethod
    def clean(body):
        """(values, error) from a request body. Unknown keys are dropped and null means "leave as
        is", like Spring's PreferencesDto. Numbers may arrive as numbers or numeric strings, as
        Spring accepted, and a decimal font size is cut to a whole one."""
        values = {}
        for key, (kind, max_len) in FIELDS.items():
            value = body.get(key)
            if value is None:
                continue
            if kind is str:
                if not isinstance(value, str):
                    return None, f"{key} must be a string"
                if max_len and len(value) > max_len:
                    return None, f"{key} must be at most {max_len} characters"
            else:
                try:
                    if isinstance(value, bool):  # bool is an int in Python
                        raise ValueError
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError
                except (TypeError, ValueError):
                    return None, f"{key} must be a number"
                value = kind(number)
            values[key] = value
        return values, None

    def apply(self, values):
        for key, value in values.items():
            setattr(self, key, value)

    def read(self):
        data = {key: getattr(self, key) for key in FIELDS}
        if self.id is not None:
            data['id'] = self.id
        return data

    @staticmethod
    def defaults():
        return dict(DEFAULTS)
