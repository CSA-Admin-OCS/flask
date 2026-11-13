""" User Preferences """
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


class UserPreferences(db.Model):
    """
    UserPreferences Model

    One row of styling, language and text-to-speech preferences per user, moved over from Spring.
    The JSON keys match Spring's, so the frontend only changes its base URL.

    A preference the user has not set is stored as null (None), not as a copy of a default.
    The site owns its defaults and applies them to whatever is unset, so changing a site default
    reaches every user who never picked that preference. unset() says which ones those are.

    Attributes:
        id (db.Column): The primary key.
        user_id (db.Column): The user these preferences belong to, one row per user.
        backgroundColor ... customThemes (db.Column): One nullable column per key in FIELDS.
    """
    __tablename__ = 'user_preferences'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    backgroundColor = db.Column(db.String(20), nullable=True)
    textColor = db.Column(db.String(20), nullable=True)
    fontFamily = db.Column(db.String(255), nullable=True)
    fontSize = db.Column(db.Integer, nullable=True)
    accentColor = db.Column(db.String(20), nullable=True)
    selectionColor = db.Column(db.String(20), nullable=True)
    buttonStyle = db.Column(db.String(20), nullable=True)
    language = db.Column(db.String(10), nullable=True)
    ttsVoice = db.Column(db.String(100), nullable=True)
    ttsRate = db.Column(db.Float, nullable=True)
    ttsPitch = db.Column(db.Float, nullable=True)
    ttsVolume = db.Column(db.Float, nullable=True)
    customThemes = db.Column(db.Text, nullable=True)

    # Deleting a user deletes their preferences.
    user = db.relationship('User', backref=db.backref('preferences', uselist=False, cascade='all, delete-orphan'))

    # Constructor: every preference starts unset
    def __init__(self, user_id):
        self.user_id = user_id

    def __repr__(self):
        return f"UserPreferences(id={self.id}, user_id={self.user_id}, unset={self.unset()})"

    # Which preferences the user has not set, so the site's defaults apply to them
    def unset(self):
        return [key for key in FIELDS if getattr(self, key) is None]

    # CRUD read: every preference (None when unset), plus the list of unset ones
    def read(self):
        data = {key: getattr(self, key) for key in FIELDS}
        data['id'] = self.id
        data['unset'] = self.unset()
        return data

    # CRUD create and update: a key with a value sets it, a key with null unsets it, a missing
    # key is left as is. Returns an error message, or None once saved.
    def update(self, inputs):
        values, error = UserPreferences.validate(inputs)
        if error:
            return error
        for key, value in values.items():
            setattr(self, key, value)
        db.session.add(self)
        db.session.commit()
        return None

    # CRUD delete: every preference goes back to unset
    def delete(self):
        db.session.delete(self)
        db.session.commit()
        return None

    @staticmethod
    def validate(inputs):
        """(values, error) from a request body. Unknown keys are dropped. Numbers may arrive as
        numbers or numeric strings, as Spring accepted, and a decimal font size is cut to a whole one."""
        values = {}
        for key, (kind, max_len) in FIELDS.items():
            if key not in inputs:
                continue
            value = inputs[key]
            if value is None:
                values[key] = None
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
