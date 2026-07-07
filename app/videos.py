import logging
import os

import db

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/data/uploads")
logger = logging.getLogger(__name__)


def save_raw_export(user_id, raw_bytes):
    """Conserve une copie du zip brut uploadé (écrase l'export précédent du même user).

    Purement une sauvegarde de secours : jamais relue par l'appli. Un échec ici
    ne doit donc jamais faire échouer l'inscription/upload (déjà en base à ce stade).
    """
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        path = os.path.join(UPLOAD_DIR, f"{user_id}.zip")
        with open(path, "wb") as f:
            f.write(raw_bytes)
    except OSError:
        logger.exception("Échec de la sauvegarde du zip brut pour user_id=%s", user_id)


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
