import io
import os

from flask import Flask, jsonify, request, send_from_directory

import auth
import db
import game
import parser as tiktok_parser
import videos

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = os.environ.get("SECRET_KEY")
db.init_app(app)

MIN_PASSWORD_LENGTH = 8


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/health")
def health():
    return jsonify(status="ok")


def _parse_uploaded_zip(raw_bytes):
    try:
        likes = tiktok_parser.parse_export(io.BytesIO(raw_bytes))
    except Exception:
        return None, (jsonify(error="Export invalide, impossible de le lire"), 400)
    if not likes:
        return None, (jsonify(error="Aucune vidéo likée trouvée dans l'export"), 400)
    return likes, None


@app.route("/api/register", methods=["POST"])
def register():
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    file = request.files.get("file")

    if "@" not in email:
        return jsonify(error="Email invalide"), 400
    if len(password) < MIN_PASSWORD_LENGTH:
        return jsonify(error=f"Mot de passe trop court ({MIN_PASSWORD_LENGTH} caractères minimum)"), 400
    if auth.get_user_by_email(email) is not None:
        return jsonify(error="Un compte existe déjà avec cet email"), 409

    raw, likes = None, []
    if file and file.filename:
        raw = file.read()
        likes, error_response = _parse_uploaded_zip(raw)
        if error_response:
            return error_response

    user_id = auth.create_user(email, password)
    if likes:
        videos.add_videos(user_id, likes)
        videos.save_raw_export(user_id, raw)

    user = auth.get_user_by_id(user_id)
    auth.login_user(user)
    return jsonify(user_id=user["id"], email=user["email"], video_count=videos.count_videos(user_id))


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    user = auth.verify_credentials(email, password)
    if user is None:
        return jsonify(error="Email ou mot de passe incorrect"), 401

    auth.login_user(user)
    return jsonify(user_id=user["id"], email=user["email"], video_count=videos.count_videos(user["id"]))


@app.route("/api/logout", methods=["POST"])
def logout():
    auth.logout_user()
    return jsonify(status="ok")


@app.route("/api/me")
def me():
    user = auth.current_user()
    if user is None:
        return jsonify(error="Non authentifié"), 401
    return jsonify(user_id=user["id"], email=user["email"], video_count=videos.count_videos(user["id"]))


@app.route("/api/upload", methods=["POST"])
@auth.login_required
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="Fichier requis"), 400

    raw = file.read()
    likes, error_response = _parse_uploaded_zip(raw)
    if error_response:
        return error_response

    user = auth.current_user()
    videos.add_videos(user["id"], likes)
    videos.save_raw_export(user["id"], raw)
    return jsonify(video_count=videos.count_videos(user["id"]))


@app.route("/api/rooms", methods=["POST"])
@auth.login_required
def rooms_create():
    user = auth.current_user()
    room = game.create_room(user["id"])
    return jsonify(room.to_dict(user["id"]))


@app.route("/api/rooms/<code>/join", methods=["POST"])
@auth.login_required
def rooms_join(code):
    user = auth.current_user()
    room, error = game.join_room(code, user["id"])
    if error:
        return jsonify(error=error), 400
    return jsonify(room.to_dict(user["id"]))


@app.route("/api/rooms/<code>")
@auth.login_required
def room_state(code):
    room = game.get_room(code)
    if room is None:
        return jsonify(error="Room introuvable"), 404
    user = auth.current_user()
    if user["id"] not in room.player_ids:
        return jsonify(error="Tu ne fais pas partie de cette room"), 403
    return jsonify(room.to_dict(user["id"]))


@app.route("/api/rooms/<code>/config", methods=["POST"])
@auth.login_required
def room_config(code):
    room = game.get_room(code)
    if room is None:
        return jsonify(error="Room introuvable"), 404
    data = request.get_json(silent=True) or {}
    user = auth.current_user()
    error = game.update_config(
        room,
        user["id"],
        num_rounds=data.get("num_rounds"),
        period_filter=data.get("period_filter"),
        timer_seconds=data.get("timer_seconds"),
    )
    if error:
        return jsonify(error=error), 400
    return jsonify(room.to_dict(user["id"]))


@app.route("/api/rooms/<code>/start", methods=["POST"])
@auth.login_required
def room_start(code):
    room = game.get_room(code)
    if room is None:
        return jsonify(error="Room introuvable"), 404
    user = auth.current_user()
    error = game.start_game(room, user["id"])
    if error:
        return jsonify(error=error), 400
    return jsonify(room.to_dict(user["id"]))


@app.route("/api/rooms/<code>/vote", methods=["POST"])
@auth.login_required
def room_vote(code):
    room = game.get_room(code)
    if room is None:
        return jsonify(error="Room introuvable"), 404
    data = request.get_json(silent=True) or {}
    try:
        guessed_user_id = int(data.get("guessed_user_id"))
    except (TypeError, ValueError):
        return jsonify(error="guessed_user_id invalide"), 400

    user = auth.current_user()
    error = game.submit_vote(room, user["id"], guessed_user_id)
    if error:
        return jsonify(error=error), 400
    return jsonify(room.to_dict(user["id"]))


@app.route("/api/rooms/<code>/next", methods=["POST"])
@auth.login_required
def room_next(code):
    room = game.get_room(code)
    if room is None:
        return jsonify(error="Room introuvable"), 404
    user = auth.current_user()
    error = game.advance_round(room, user["id"])
    if error:
        return jsonify(error=error), 400
    return jsonify(room.to_dict(user["id"]))


if __name__ == "__main__":
    port = int(os.environ.get("APP_PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
