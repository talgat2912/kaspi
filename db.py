import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "bot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS codes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                code        TEXT NOT NULL,
                added_at    TEXT DEFAULT (datetime('now')),
                UNIQUE(user_id, code)
            );

            CREATE TABLE IF NOT EXISTS positions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                code            TEXT NOT NULL,
                product_name    TEXT,
                position        INTEGER,
                page            INTEGER,
                place_on_page   INTEGER,
                checked_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS schedules (
                user_id     INTEGER PRIMARY KEY,
                hour        INTEGER NOT NULL,
                minute      INTEGER NOT NULL DEFAULT 0
            );
        """)


def upsert_user(user_id: int, username: str | None):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username)
        )


def add_code(user_id: int, code: str) -> bool:
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO codes (user_id, code) VALUES (?, ?)",
                (user_id, code)
            )
        return True
    except sqlite3.IntegrityError:
        return False


def remove_code(user_id: int, code: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM codes WHERE user_id=? AND code=?",
            (user_id, code)
        )
        return cur.rowcount > 0


def get_codes(user_id: int) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT code FROM codes WHERE user_id=? ORDER BY added_at",
            (user_id,)
        ).fetchall()
    return [r["code"] for r in rows]


def save_position(user_id, code, product_name, position, page, place_on_page):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO positions
               (user_id, code, product_name, position, page, place_on_page)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, code, product_name, position, page, place_on_page)
        )


def get_last_position(user_id: int, code: str):
    with get_conn() as conn:
        return conn.execute(
            """SELECT position FROM positions
               WHERE user_id=? AND code=?
               ORDER BY checked_at DESC LIMIT 1""",
            (user_id, code)
        ).fetchone()


def get_history(user_id: int, code: str, limit: int = 10) -> list:
    with get_conn() as conn:
        return conn.execute(
            """SELECT * FROM positions
               WHERE user_id=? AND code=?
               ORDER BY checked_at DESC LIMIT ?""",
            (user_id, code, limit)
        ).fetchall()


def get_all_history(user_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            """SELECT p.* FROM positions p
               INNER JOIN (
                   SELECT code, MAX(checked_at) as max_at
                   FROM positions WHERE user_id=?
                   GROUP BY code
               ) latest ON p.code = latest.code AND p.checked_at = latest.max_at
               WHERE p.user_id=?
               ORDER BY p.code""",
            (user_id, user_id)
        ).fetchall()


def set_schedule(user_id: int, hour: int, minute: int = 0):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO schedules (user_id, hour, minute) VALUES (?, ?, ?)",
            (user_id, hour, minute)
        )


def remove_schedule(user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM schedules WHERE user_id=?", (user_id,))


def get_schedule(user_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT hour, minute FROM schedules WHERE user_id=?", (user_id,)
        ).fetchone()


def get_all_schedules() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM schedules").fetchall()
