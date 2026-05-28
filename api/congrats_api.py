"""
Congrats API (stub)

Provides a minimal blueprint so the application can import and register
the `congrats_api` blueprint. This is intentionally lightweight and does
not depend on a missing `model.congrats_message` implementation.
"""
from flask import Blueprint, request, jsonify, g, current_app
from flask_restful import Api, Resource
from api.authorize import token_required


congrats_api = Blueprint('congrats_api', __name__, url_prefix='/api/congrats')
api = Api(congrats_api)


class CongratsList(Resource):
    """GET returns a small list of placeholder congrats messages."""
    def get(self):
        try:
            # Non-destructive placeholder response so app can start
            messages = []
            return {'messages': messages}, 200
        except Exception as e:
            current_app.logger.error(f"Congrats API get error: {e}")
            return {'message': f'Error: {str(e)}'}, 500


class CongratsCreate(Resource):
    """POST accepts a message payload and returns a success response.

    This endpoint is token-protected in case callers expect auth to be
    required. It does not persist data — it's a safe stub.
    """
    @token_required()
    def post(self):
        body = request.get_json() or {}
        text = body.get('text')
        if not text:
            return {'message': 'Text is required'}, 400

        current_user = g.get('current_user')
        user_id = getattr(current_user, 'uid', None) if current_user else None

        return {
            'success': True,
            'message': 'Congrats message received (not persisted in stub).',
            'user': user_id,
            'text': text
        }, 201


api.add_resource(CongratsList, '')        # GET /api/congrats
api.add_resource(CongratsCreate, '/create')  # POST /api/congrats/create
