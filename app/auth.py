
import functools

from flask import g, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash

import db


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
