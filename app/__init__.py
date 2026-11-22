"""Pixel Wars: a shared, real-time pixel canvas."""

import os
import socket
import time

from flask import Flask, Response, jsonify, render_template, request

from .store import HEIGHT, SIZE, WIDTH, make_store

PALETTE = [
    "#ffffff", "#e4e4e4", "#888888", "#222222",
    "#ffa7d1", "#e50000", "#e59500", "#a06a42",
    "#e5d900", "#94e044", "#02be01", "#00d3dd",
    "#0083c7", "#0000ea", "#cf6ee4", "#820080",
]

HOSTNAME = socket.gethostname()
STARTED = time.time()


def create_app(store=None) -> Flask:
    app = Flask(__name__)
    app.store = store or make_store()
    cooldown = int(os.getenv("COOLDOWN_SECONDS", "3"))
    admin_token = os.getenv("ADMIN_TOKEN", "")

    def client_id() -> str:
        # Behind Nginx the real client IP arrives in X-Real-IP.
        return request.headers.get("X-Real-IP") or request.remote_addr or "anon"

    @app.after_request
    def tag_replica(resp):
        # Lets you see which container answered each request.
        resp.headers["X-Served-By"] = HOSTNAME
        return resp

    @app.get("/")
    def index():
        return render_template(
            "index.html", width=WIDTH, height=HEIGHT, palette=PALETTE, cooldown=cooldown
        )

    @app.get("/api/board")
    def board():
        since = request.args.get("since", type=int)
        if since is not None and since == app.store.version():
            return Response(status=204)  # nothing changed: tiny response
        version, pixels = app.store.board()
        return jsonify(version=version, pixels=pixels, served_by=HOSTNAME)

    @app.post("/api/pixel")
    def pixel():
        data = request.get_json(silent=True) or {}
        try:
            x, y, c = int(data["x"]), int(data["y"]), int(data["c"])
        except (KeyError, TypeError, ValueError):
            return jsonify(error="send JSON like {x, y, c}"), 400
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT and 0 <= c < len(PALETTE)):
            return jsonify(error="out of range"), 400

        wait = app.store.try_cooldown(client_id(), cooldown)
        if wait:
            return jsonify(error="cooldown", retry_in=wait), 429

        version = app.store.place(y * WIDTH + x, format(c, "x"))
        return jsonify(ok=True, version=version, cooldown=cooldown, served_by=HOSTNAME)

    @app.get("/api/stats")
    def stats():
        return jsonify(
            served_by=HOSTNAME,
            replica_uptime=round(time.time() - STARTED),
            pixels_placed=app.store.placed(),
            board_size=SIZE,
            storage=type(app.store).__name__,
        )

    @app.post("/api/reset")
    def reset():
        if not admin_token or request.headers.get("X-Admin-Token") != admin_token:
            return jsonify(error="forbidden"), 403
        app.store.reset()
        return jsonify(ok=True)

    @app.get("/healthz")
    def healthz():
        try:
            app.store.ping()
            return jsonify(status="ok", replica=HOSTNAME)
        except Exception as exc:  # Redis down => container reports unhealthy
            return jsonify(status="error", detail=str(exc)), 503

    return app


app = create_app()
