from flask import Blueprint, g
from flask_restful import Api, Resource # used for REST API building
from api.authorize import token_required
from api.request_body import json_object
from model.user_preferences import UserPreferences

user_preferences_api = Blueprint('user_preferences_api', __name__,
                   url_prefix='/api')

# API docs https://flask-restful.readthedocs.io/en/latest/api.html
api = Api(user_preferences_api)

class UserPreferencesAPI:
    """
    Styling, language and text-to-speech preferences of the logged-in user, moved over from
    Spring with the same route and JSON. A preference the user has not set comes back as null
    and is listed in "unset"; the site applies its own default to it.
    """

    class _CRUD(Resource):  # Preferences API operation for Create, Read, Update, Delete
        @token_required()
        def post(self): # Create method
            ''' Read data for json body '''
            body = json_object()

            ''' Avoid duplicates, PUT updates an existing row '''
            user = g.current_user
            if user.preferences:
                return {'message': 'Preferences already exist. Use PUT to update.'}, 409

            ''' Setup PREFERENCES OBJECT and add it to DATABASE '''
            preferences = UserPreferences(user.id)
            error = preferences.update(body)
            if error:
                return {'message': error}, 400
            return preferences.read(), 201

        @token_required()
        def get(self): # Read method
            ''' Nothing saved yet reads as every preference unset; nothing is written '''
            user = g.current_user
            preferences = user.preferences or UserPreferences(user.id)
            return preferences.read()

        @token_required()
        def put(self): # Update method
            ''' Read data for json body '''
            body = json_object()

            ''' Update the row, creating it on the first save '''
            user = g.current_user
            preferences = user.preferences or UserPreferences(user.id)
            error = preferences.update(body)
            if error:
                return {'message': error}, 400
            return preferences.read()

        @token_required()
        def delete(self): # Delete method
            ''' Every preference goes back to unset; nothing saved is not an error '''
            preferences = g.current_user.preferences
            if preferences:
                preferences.delete()
            # 204 is the status code for delete with no json response
            return '', 204

    # building RESTapi endpoint
    api.add_resource(_CRUD, '/user/preferences')
