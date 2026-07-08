
import functools

from flask import g, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

import db

# Display name, in-memory only (no DB column): defaults to the email,
# customizable via /api/username. Must be visible to other players in a room,
# so it's stored here rather than in the Flask session (which is per-browser
# and invisible to other players' requests).
_usernames = {}


def get_username(user_id):
    user = get_user_by_id(user_id)
    default = user["email"] if user else "?"
    return _usernames.get(user_id, default)


def set_username(user_id, name):
    _usernames[user_id] = name


def create_user(email, password):
    password_hash = generate_password_hash(password)
    conn = db.get_db()
    cur = conn.execute(
        "INSERT INTO users (email, password_hash) VALUES (?, ?)",
        (email, password_hash),
    )
    conn.commit()
    return cur.lastrowid


def get_user_by_email(email):
    conn = db.get_db()
    return conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(user_id):
    conn = db.get_db()
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def verify_credentials(email, password):
    user = get_user_by_email(email)
    if user is None or not check_password_hash(user["password_hash"], password):
        return None
    return user


def login_user(user):
    session.clear()
    session["user_id"] = user["id"]


def logout_user():
    session.clear()


def current_user():
    if "user" not in g:
        user_id = session.get("user_id")
        g.user = get_user_by_id(user_id) if user_id else None
    return g.user


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return jsonify(error="Authentification requise"), 401
        return view(*args, **kwargs)

    return wrapped
