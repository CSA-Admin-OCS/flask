"""
user_preferences_api.py - styling, language and text-to-speech preferences of the logged-in user,
moved over from Spring's UserPreferencesApiController with the same routes and JSON.

Routes (all require login):
  GET    /api/user/preferences  - saved preferences, or the defaults (nothing is saved)
  POST   /api/user/preferences  - first save; 409 when preferences already exist
  PUT    /api/user/preferences  - save, creating the row when missing; null fields are left as is
  DELETE /api/user/preferences  - back to the defaults
"""
from flask import Blueprint, request, g
from flask_restful import Api, Resource

from __init__ import db
from api.authorize import token_required
from model.user_preferences import UserPreferences

user_preferences_api = Blueprint('user_preferences_api', __name__, url_prefix='/api')
api = Api(user_preferences_api)


def _save(prefs, status):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {'error': 'Request body must be a JSON object'}, 400
    values, error = UserPreferences.clean(body)
    if error:
        return {'error': error}, 400
    prefs.apply(values)
    db.session.add(prefs)
    db.session.commit()
    return prefs.read(), status


class _Preferences(Resource):

    @token_required()
    def get(self):
        prefs = g.current_user.preferences
        return (prefs.read() if prefs else UserPreferences.defaults()), 200

    @token_required()
    def post(self):
        if g.current_user.preferences:
            return {'error': 'Preferences already exist. Use PUT to update.'}, 409
        return _save(UserPreferences(g.current_user.id), 201)

    @token_required()
    def put(self):
        return _save(g.current_user.preferences or UserPreferences(g.current_user.id), 200)

    @token_required()
    def delete(self):
        prefs = g.current_user.preferences
        if not prefs:
            return {'message': 'No preferences found to delete'}, 200
        db.session.delete(prefs)
        db.session.commit()
        return {'message': 'Preferences deleted successfully'}, 200


api.add_resource(_Preferences, '/user/preferences')
