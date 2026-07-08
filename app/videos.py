import json
import logging
import os
import zipfile
from datetime import datetime, timedelta

import db

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/data/uploads")
logger = logging.getLogger(__name__)


def save_raw_export(user_id, likes):
    """Save a slimmed-down version of the export (just the already-parsed
    likes: date + link), not the full TikTok zip with its sections that are
    irrelevant to the game (favorites, sounds, hashtags...). Overwrites the
    previous export for the same user.

    Purely a backup: never read back by the app. A failure here must never
    fail registration/upload (the data is already in the DB at this point).
    """
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        path = os.path.join(UPLOAD_DIR, f"{user_id}.zip")
        payload = json.dumps({"likes": likes}, ensure_ascii=False)
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("likes.json", payload)
    except OSError:
        logger.exception("Failed to save the slimmed-down export for user_id=%s", user_id)


def add_videos(user_id, likes):
    conn = db.get_db()
    conn.executemany(
        "INSERT OR IGNORE INTO videos (user_id, link, liked_at) VALUES (?, ?, ?)",
        [(user_id, item["link"], item.get("date")) for item in likes],
    )
    conn.commit()


def count_videos(user_id):
    conn = db.get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM videos WHERE user_id = ?", (user_id,)
    ).fetchone()
    return row["c"]


def has_videos(user_id):
    return count_videos(user_id) > 0


def get_links(user_id, period_days=None):
    """Return the videos liked by this user, filtered to the last
    `period_days` days (None = entire history)."""
    conn = db.get_db()
    query = "SELECT link, liked_at FROM videos WHERE user_id = ?"
    params = [user_id]
    if period_days is not None:
        cutoff = (datetime.utcnow() - timedelta(days=period_days)).strftime("%Y-%m-%d %H:%M:%S")
        query += " AND liked_at >= ?"
        params.append(cutoff)
    rows = conn.execute(query, params).fetchall()
    return [{"link": row["link"], "liked_at": row["liked_at"]} for row in rows]
