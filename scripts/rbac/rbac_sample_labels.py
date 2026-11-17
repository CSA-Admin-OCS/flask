"""Routes labelled by a person reading each handler's source: the decorators on the function and its class, with role
lists worked out from model/dataconfigs/account_types.json. scripts/rbac/rbac_reconcile.py --sample checks that the tools read
the same guard.

who          who the guard lets through in production: "anyone", "signed_in" (any active account), "session" (the Flask
             session login), "device_key", or a list of roles
development  given only where it differs from production

The guarded routes were drawn at random within each kind of guard; the open ones were picked from routes that are open
on purpose.
"""

ROUTES = [
    {"request": "GET /api/analytics/issues/<string:uid>", "who": "signed_in"},
    {"request": "POST /api/export/import", "who": "signed_in"},
    {"request": "PUT /api/microblog/topics", "who": "signed_in"},
    {"request": "POST /api/post/reply", "who": "signed_in"},
    {"request": "PUT /api/id/pfp", "who": "signed_in"},
    {"request": "POST /api/microblog", "who": "signed_in"},
    {"request": "GET /api/user/personas", "who": "signed_in"},
    {"request": "PUT /api/classrooms/<int:id>", "who": "signed_in"},
    {"request": "GET /api/microblog", "who": "signed_in"},
    {"request": "GET /api/analytics/github/user/issue_comments", "who": "signed_in"},
    {"request": "GET /api/grade_data", "who": "signed_in"},
    {"request": "GET /users/table2", "who": "session"},
    {"request": "GET /congrats", "who": "session"},
    {"request": "POST /api/rfid/tags", "who": ["Admin", "Teacher"]},
    {"request": "DELETE /api/presence/rooms/<int:room_id>", "who": ["Admin", "Teacher"]},
    {"request": "POST /api/guest/disable", "who": ["Admin", "Teacher"]},
    {"request": "GET /api/rfid/tags", "who": ["Admin", "Teacher"]},
    {"request": "POST /api/user/<string:uid>/deactivate", "who": ["Admin", "Teacher"]},
    {"request": "DELETE /api/presence/schedules/overrides/<int:override_id>", "who": ["Admin", "Teacher"]},
    {"request": "GET /api/rfid/rooms/<int:room_id>/events", "who": ["Admin", "Teacher"]},
    {"request": "GET /api/presence/schedules", "who": ["Admin", "Teacher"]},
    {"request": "GET /api/presence/rooms", "who": ["Admin", "Teacher"]},
    {"request": "POST /api/section", "who": ["Admin"]},
    {"request": "GET /", "who": "anyone"},
    {"request": "GET /login", "who": "anyone"},
    {"request": "POST /login", "who": "anyone"},
    {"request": "POST /api/authenticate", "who": "anyone"},
    {"request": "GET /api/jokes/", "who": "anyone"},
    {"request": "GET /api/jokes/<int:id>/", "who": "anyone"},
    {"request": "GET /api/microblog/topics", "who": "anyone"},
    {"request": "GET /api/rfid/", "who": "anyone"},
    {"request": "PUT /api/presence/<path:unknown>", "who": "anyone"},
    {"request": "POST /api/jokes/create/<string:joke>", "who": "anyone"},
    {"request": "POST /api/rfid/scan", "who": "device_key"},
    {"request": "POST /api/presence/event", "who": "device_key"},
    {"request": "GET /api/presence/rooms/<int:room_id>/taps/pending", "who": "device_key"},
    {"request": "POST /api/gemini/upload", "who": "signed_in", "development": "anyone"},
    {"request": "POST /api/gemini/debug", "who": "signed_in", "development": "anyone"},
    {"request": "POST /api/gemini", "who": "signed_in", "development": "anyone"},
    {"request": "POST /api/gemini/summarize-submissions", "who": ["Admin", "Teacher"], "development": "anyone"},
]
