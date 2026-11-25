"""
db.py
-----
MySQL / MariaDB helpers + schema for CareerAI (works with WAMP out of the box).

Connection settings come from .env (see .env.example):
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

init_db() creates the database and all tables automatically if they don't exist.

Tables:
    users              accounts (is_admin, is_verified, created_at)
    predictions        one row per career prediction (history timeline)
    progress           ticked roadmap items
    learned_skills     skills the user marked "learned" on the Skill Gap page
    user_state         small per-user JSON blobs (resume text, interview state...)
    interview_results  finished mock interviews
"""

import json
from contextlib import contextmanager
from datetime import datetime

import pymysql
from pymysql.cursors import DictCursor

from config import env

DB_HOST = env("DB_HOST", "127.0.0.1")
DB_PORT = int(env("DB_PORT", "3306"))
DB_USER = env("DB_USER", "root")
DB_PASSWORD = env("DB_PASSWORD", "")          # WAMP's default root password is empty
DB_NAME = env("DB_NAME", "careerai")

IntegrityError = pymysql.err.IntegrityError


def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


class _Conn:
    """Thin wrapper so callers can write conn.execute(sql, params) and get a
    cursor back (rows are dicts, so row["col"] and dict(row) both work)."""

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, params=None):
        cur = self.raw.cursor()
        cur.execute(sql, params)
        return cur

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()



def _raw_connect(database=DB_NAME):
    import os

    ca_path = os.environ.get(
        "DB_SSL_CA",
        os.path.join(os.path.dirname(__file__), "isrgrootx1.pem")
    )

    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        ssl={"ca": ca_path}
    )



def connect():
    return _Conn(_raw_connect())


@contextmanager
def get_db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _create_database():
    """Create the schema (database) if it doesn't exist yet."""
    raw = _raw_connect(database=None)
    try:
        with raw.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        raw.commit()
    finally:
        raw.close()


def init_db():
    try:
        _create_database()
    except pymysql.err.OperationalError as e:
        raise SystemExit(
            f"\n[db] Could not connect to MySQL at {DB_HOST}:{DB_PORT} as '{DB_USER}': {e}\n"
            "     Make sure WAMP is running (icon is GREEN) and DB_* in .env are correct.\n")

    with get_db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE,
            password VARCHAR(255) NOT NULL,
            is_admin TINYINT NOT NULL DEFAULT 0,
            is_verified TINYINT NOT NULL DEFAULT 0,
            created_at VARCHAR(19)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions(
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            career VARCHAR(150) NOT NULL,
            confidence DOUBLE,
            education VARCHAR(255),
            specialization VARCHAR(255),
            skills TEXT,
            certification VARCHAR(255),
            cgpa DOUBLE,
            readiness INT,
            created_at VARCHAR(19) NOT NULL,
            INDEX idx_pred_user (user_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS progress(
            user_id INT NOT NULL,
            career VARCHAR(150) NOT NULL,
            item VARCHAR(255) NOT NULL,
            PRIMARY KEY(user_id, career, item),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS learned_skills(
            user_id INT NOT NULL,
            skill VARCHAR(150) NOT NULL,
            created_at VARCHAR(19) NOT NULL,
            PRIMARY KEY(user_id, skill),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS user_state(
            user_id INT NOT NULL,
            `key` VARCHAR(100) NOT NULL,
            `value` LONGTEXT,
            PRIMARY KEY(user_id, `key`),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")

        conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_results(
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            career VARCHAR(150) NOT NULL,
            kind VARCHAR(50),
            avg_score DOUBLE,
            num_questions INT,
            created_at VARCHAR(19) NOT NULL,
            INDEX idx_int_user (user_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")


# ---------------- generic per-user state ----------------

def get_state(user_id, key, default=None):
    with get_db() as conn:
        row = conn.execute(
            "SELECT `value` FROM user_state WHERE user_id=%s AND `key`=%s", (user_id, key)
        ).fetchone()
    if not row or row["value"] is None:
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return default


def set_state(user_id, key, value):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO user_state(user_id,`key`,`value`) VALUES(%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",
            (user_id, key, json.dumps(value)),
        )


def del_state(user_id, key):
    with get_db() as conn:
        conn.execute("DELETE FROM user_state WHERE user_id=%s AND `key`=%s", (user_id, key))


# ---------------- users ----------------

def get_user_by_email(email):
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE lower(email)=lower(%s)", (email,)).fetchone()


def get_user(user_id):
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE id=%s", (user_id,)).fetchone()


# ---------------- predictions ----------------

def add_prediction(user_id, career, confidence, education, specialization,
                   skills, certification, cgpa, readiness):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO predictions(user_id,career,confidence,education,specialization,"
            "skills,certification,cgpa,readiness,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (user_id, career, confidence, education, specialization,
             json.dumps(skills), certification, cgpa, readiness, now()),
        )


def list_predictions(user_id, limit=30):
    """Oldest -> newest, each row annotated with skills added/removed vs the
    previous prediction, so the timeline can show *why* the fit changed."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM predictions WHERE user_id=%s ORDER BY id DESC LIMIT %s",
            (user_id, limit),
        ).fetchall()
    rows = list(reversed(rows))

    out, prev_skills, prev_career = [], None, None
    for r in rows:
        skills = json.loads(r["skills"] or "[]")
        item = {
            "id": r["id"],
            "career": r["career"],
            "confidence": r["confidence"],
            "education": r["education"],
            "specialization": r["specialization"],
            "skills": skills,
            "certification": r["certification"],
            "cgpa": r["cgpa"],
            "readiness": r["readiness"],
            "created_at": r["created_at"],
            "added": [s for s in skills if prev_skills is not None and s not in prev_skills],
            "removed": [s for s in (prev_skills or []) if s not in skills],
            "career_changed": prev_career is not None and prev_career != r["career"],
            "first": prev_skills is None,
        }
        out.append(item)
        prev_skills, prev_career = skills, r["career"]
    return out


def latest_prediction(user_id):
    with get_db() as conn:
        r = conn.execute(
            "SELECT * FROM predictions WHERE user_id=%s ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
    if not r:
        return None
    return {
        "career": r["career"],
        "skills": json.loads(r["skills"] or "[]"),
        "education": r["education"],
    }


# ---------------- progress / learned skills ----------------

def get_progress(user_id, career):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT item FROM progress WHERE user_id=%s AND career=%s", (user_id, career)
        ).fetchall()
    return {r["item"] for r in rows}


def set_progress(user_id, career, item, done):
    with get_db() as conn:
        if done:
            conn.execute("INSERT IGNORE INTO progress(user_id,career,item) VALUES(%s,%s,%s)",
                         (user_id, career, item))
        else:
            conn.execute("DELETE FROM progress WHERE user_id=%s AND career=%s AND item=%s",
                         (user_id, career, item))


def get_learned(user_id):
    with get_db() as conn:
        rows = conn.execute("SELECT skill FROM learned_skills WHERE user_id=%s", (user_id,)).fetchall()
    return [r["skill"] for r in rows]


def set_learned(user_id, skill, learned):
    with get_db() as conn:
        if learned:
            conn.execute("INSERT IGNORE INTO learned_skills(user_id,skill,created_at) VALUES(%s,%s,%s)",
                         (user_id, skill, now()))
        else:
            conn.execute("DELETE FROM learned_skills WHERE user_id=%s AND skill=%s", (user_id, skill))


# ---------------- interviews ----------------

def add_interview_result(user_id, career, kind, avg_score, n):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO interview_results(user_id,career,kind,avg_score,num_questions,created_at) "
            "VALUES(%s,%s,%s,%s,%s,%s)", (user_id, career, kind, avg_score, n, now()))


def list_interview_results(user_id, limit=10):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM interview_results WHERE user_id=%s ORDER BY id DESC LIMIT %s",
            (user_id, limit)).fetchall()
    return [dict(r) for r in rows]
