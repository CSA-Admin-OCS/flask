from datetime import datetime
from __init__ import db


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(64), nullable=False)
    uid = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    user_agent = db.Column(db.String(512), nullable=True)
    details = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __init__(self, event_type, uid=None, ip_address=None, user_agent=None, details=None):
        self.event_type = event_type
        self.uid = uid
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.details = details

    def to_dict(self):
        return {
            "id": self.id,
            "event_type": self.event_type,
            "uid": self.uid,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "details": self.details,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "source": "flask"
        }


def log_event(event_type, uid=None, req=None, details=None):
    """Record a security audit event. Safe to call anywhere — swallows DB errors."""
    ip = None
    ua = None
    if req is not None:
        forwarded = req.headers.get('X-Forwarded-For')
        ip = (forwarded.split(',')[0].strip() if forwarded else req.remote_addr or '')[:45]
        ua = (req.user_agent.string or '')[:512] if req.user_agent else None
    try:
        entry = AuditLog(event_type=event_type, uid=uid, ip_address=ip, user_agent=ua, details=details)
        db.session.add(entry)
        db.session.commit()
    except Exception:
        db.session.rollback()
