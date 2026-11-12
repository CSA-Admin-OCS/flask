"""A small Flask app with one route for each way this codebase guards a route, and the ways it does not.

scripts/verify_rbac_inventory.py checks that rbac_inventory.py reads each one correctly. The decorators have the
names the project's own use, because that is what the inventory reads; here they do nothing.
"""
import os
from functools import wraps

from flask import Blueprint, Flask, abort, g, jsonify, request
from flask_login import current_user
from flask_restful import Api, Resource


def _passthrough(*args, **kwargs):
    if len(args) == 1 and callable(args[0]) and not kwargs:
        return args[0]
    return lambda f: f


token_required = _passthrough
auth_required = _passthrough
login_required = _passthrough
require_device_api_key = _passthrough


def require_auth_if_production(f):
    """Guards only when the process started in production mode: decided when the module is loaded."""
    if os.environ.get("IS_PRODUCTION", "false").lower() == "true":
        @wraps(f)
        def guarded(*args, **kwargs):
            return f(*args, **kwargs)
        return guarded
    return f


def some_custom_guard(f):
    return f


def _refuse_non_staff():
    if current_user.role != "Admin":
        abort(403)


def make_app(wrap_open=False):
    """wrap_open puts a wrapper around /open that no decorator in the source explains."""
    app = Flask(__name__)

    @app.route("/open")
    def open_route():
        return jsonify({"hello": "anyone"})

    @app.route("/any-login")
    @token_required()
    def any_login():
        return jsonify({})

    @app.route("/admin-only", methods=["POST"])
    @token_required(["Admin"])
    def admin_only():
        return jsonify({})

    @app.route("/auth-roles")
    @auth_required(roles=["Teacher", "Admin"])
    def auth_roles():
        return jsonify({})

    @app.route("/session-login")
    @login_required
    def session_login():
        return jsonify({})

    @app.route("/inline-check", methods=["PUT"])
    def inline_check():
        if current_user.role != "Admin":
            return jsonify({"error": "no"}), 403
        return jsonify({})

    @app.route("/helper-check", methods=["DELETE"])
    def helper_check():
        _refuse_non_staff()
        return jsonify({})

    @app.route("/crashes-for-anonymous")
    def crashes_for_anonymous():
        return jsonify({"id": g.current_user.id})

    @app.route("/crashes-on-the-user-object", methods=["PUT"])
    def crashes_on_the_user_object():
        if not current_user.is_admin():
            return jsonify({}), 403
        return jsonify({})

    @app.route("/optional-auth")
    def optional_auth():
        user_id = current_user.id if current_user.is_authenticated else None
        return jsonify({"user": user_id})

    @app.route("/prints-the-user")
    def prints_the_user():
        print("who:", current_user)
        return jsonify({})

    @app.route("/local-variable-named-current-user")
    def local_variable_named_current_user():
        current_user = None
        try:
            current_user = g.optional_user
        except Exception:
            pass
        return jsonify({"user": current_user.id if current_user else None})

    @app.route("/custom-guard")
    @some_custom_guard
    def custom_guard():
        return jsonify({})

    @app.route("/production-only")
    @require_auth_if_production
    def production_only():
        return jsonify({})

    @app.route("/device", methods=["POST"])
    @require_device_api_key
    def device():
        return jsonify({})

    @app.route("/reads-header")
    def reads_header():
        if request.headers.get("X-Key") != "k":
            abort(401)
        return jsonify({})

    class ClassWide(Resource):
        method_decorators = [token_required()]

        def get(self):
            return {}

        def post(self):
            return {}

    class PerMethod(Resource):
        def get(self):
            return {}

        @token_required(["Admin"])
        def delete(self):
            return {}

    api_bp = Blueprint("fixture_api", __name__, url_prefix="/api/fixture")
    api = Api(api_bp)
    api.add_resource(ClassWide, "/class-wide")
    api.add_resource(PerMethod, "/per-method")

    @api_bp.before_request
    def blueprint_hook():
        return None

    app.register_blueprint(api_bp)

    @app.before_request
    def app_hook():
        return None

    @app.route("/<path:anything>")
    def catch_all(anything):
        return jsonify({"message": "not found"}), 404

    if wrap_open:
        original = app.view_functions["open_route"]

        @wraps(original)
        def wrapped_elsewhere(*args, **kwargs):
            return original(*args, **kwargs)

        app.view_functions["open_route"] = wrapped_elsewhere
    return app
