""" Request Body """
from flask import jsonify, request
from werkzeug.exceptions import BadRequest

from __init__ import app


class NotJsonObjectError(BadRequest):
    """Raised when a request body is not a JSON object: missing, not JSON, a list, a string or null.
    It is a 400, so the API sends back {"message": description} without any route handling it."""
    description = 'Send a JSON object as the request body'


def json_object():
    """The request's JSON body when it is an object. Anything else raises NotJsonObjectError (400)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise NotJsonObjectError()
    return body


@app.errorhandler(NotJsonObjectError)
def not_json_object(error):
    """Routes outside Flask-RESTful get the same JSON 400 that Flask-RESTful routes send."""
    return jsonify({'message': error.description}), 400
