import gevent
from gevent import pywsgi

from flask import Flask, jsonify, request
from flask_socketio import SocketIO

import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="gevent")

@app.get("/health")
def health():
    server_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    ping = request.args.get("ping")
    latency = None
    if ping:
        try:
            latency = time.time() - float(ping)
        except Exception:
            latency = None
    resp = {
        "ok": True,
        "service": "websocket",
        "server_time_utc": server_time,
        "client_ip": client_ip,
        "latency_seconds": latency,
        "info": "Send ?ping=<epoch_seconds> to measure latency."
    }
    return jsonify(resp), 200

players = {}
playercount = 0
tagger_id = None  # track who is "it"


@app.get("/")
def index():
    return jsonify({"message": "websocket service running"}), 200

@socketio.on('connect')
def handle_connect():
    global playercount, tagger_id
    sid = request.sid
    players[sid] = {"x": 100, "y": 100}
    playercount += 1
    print(f"[SERVER] Player joined: {sid} | count: {playercount}")

    # First player to join becomes the tagger
    if tagger_id is None:
        tagger_id = sid
        print(f"[SERVER] {sid} is now IT (first player)")

    socketio.emit('player_update', {"players": players, "taggerId": tagger_id})
    # Also send a dedicated tag_update so the new joiner knows who is "it"
    socketio.emit('tag_update', {"taggerId": tagger_id})

@socketio.on('move')
def handle_move(data):
    sid = request.sid
    if sid in players and "x" in data and "y" in data:
        players[sid]["x"] = data["x"]
        players[sid]["y"] = data["y"]
        socketio.emit('player_update', {"players": players, "taggerId": tagger_id})

@socketio.on('tag')
def handle_tag(data):
    global tagger_id
    sid = request.sid

    # Server-side validation: only accept if sender is actually "it"
    if sid != tagger_id:
        print(f"[SERVER] Rejected tag from {sid} — they are not IT")
        return

    tagged_id = data.get("taggedId")
    if not tagged_id or tagged_id not in players:
        print(f"[SERVER] Rejected tag — target {tagged_id} not found")
        return

    tagger_id = tagged_id
    print(f"[SERVER] {sid} tagged {tagged_id} — {tagged_id} is now IT")
    socketio.emit('tag_update', {"taggerId": tagger_id})

@socketio.on('disconnect')
def handle_disconnect():
    global playercount, tagger_id
    sid = request.sid
    if sid in players:
        del players[sid]
        playercount -= 1
        print(f"[SERVER] Player disconnected: {sid} | count: {playercount}")

        # If the tagger disconnected, assign to another player
        if tagger_id == sid:
            remaining = list(players.keys())
            tagger_id = remaining[0] if remaining else None
            print(f"[SERVER] Tagger left — new IT: {tagger_id}")
            socketio.emit('tag_update', {"taggerId": tagger_id})

        socketio.emit('player_left', {"sid": sid})
        socketio.emit('player_update', {"players": players, "taggerId": tagger_id})

@socketio.on('get_live_status')
def handle_live_status(data=None):
    server_time = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    ping = None
    latency = None
    if data and isinstance(data, dict):
        ping = data.get("ping")
    if ping:
        try:
            latency = time.time() - float(ping)
        except Exception:
            latency = None
    resp = {
        "ok": True,
        "service": "websocket",
        "server_time_utc": server_time,
        "client_ip": client_ip,
        "latency_seconds": latency,
        "info": "Send {ping: <epoch_seconds>} as payload to measure latency."
    }
    socketio.emit('live_status', resp, room=request.sid)

if __name__ == "__main__":
    print("\n" + "="*60)
    print("WebSocket Server Starting...")
    print("="*60)
    print("Host: 0.0.0.0:8590")
    print("Connect with: ws://localhost:8590/")
    print("CORS enabled for all origins")
    print("⚡ Async mode: gevent")
    print("="*60 + "\n")
    socketio.run(app, host="0.0.0.0", port=8590, debug=False)