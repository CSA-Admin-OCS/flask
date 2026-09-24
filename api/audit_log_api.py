from flask import Blueprint, request, jsonify
from flask_restful import Api, Resource
from model.audit_log import AuditLog
from api.authorize import auth_required

audit_log_api = Blueprint('audit_log_api', __name__, url_prefix='/api/audit')
api = Api(audit_log_api)


class AuditLogList(Resource):
    @auth_required(roles=["Admin", "Mentor"])
    def get(self):
        limit = request.args.get('limit', 200, type=int)
        event_type = request.args.get('event_type')
        query = AuditLog.query.order_by(AuditLog.timestamp.desc())
        if event_type:
            query = query.filter_by(event_type=event_type)
        return jsonify([log.to_dict() for log in query.limit(limit).all()])


api.add_resource(AuditLogList, '/logs')
