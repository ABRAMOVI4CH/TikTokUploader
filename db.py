"""SQLite database for accounts and tasks."""

import json
import os
import sqlite3
from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(
    os.environ.get("DB_DIR", os.path.dirname(os.path.abspath(__file__))),
    "data.db",
)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            tiktok_username TEXT DEFAULT '',
            tiktok_nickname TEXT DEFAULT '',
            avatar_path TEXT    DEFAULT '',
            cookies     TEXT    NOT NULL,
            created_at  TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS admin_users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            created_at    TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id          TEXT    PRIMARY KEY,
            account_id  INTEGER REFERENCES accounts(id),
            status      TEXT    NOT NULL DEFAULT 'pending',
            filename    TEXT    NOT NULL,
            description TEXT    DEFAULT '',
            tags        TEXT    DEFAULT '',
            message     TEXT    DEFAULT '',
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        );
    """)
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# Account helpers
# ------------------------------------------------------------------

def add_account(name: str, cookies: list, tiktok_username: str = "",
                tiktok_nickname: str = "", avatar_path: str = "") -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO accounts (name, tiktok_username, tiktok_nickname, avatar_path, cookies, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, tiktok_username, tiktok_nickname, avatar_path,
         json.dumps(cookies, ensure_ascii=False), datetime.utcnow().isoformat()),
    )
    conn.commit()
    account_id = cur.lastrowid
    conn.close()
    return account_id


def get_account(account_id: int) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["cookies"] = json.loads(d["cookies"])
    return d


def list_accounts() -> list[dict]:
    conn = get_db()
    rows = conn.execute("SELECT * FROM accounts ORDER BY created_at DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["cookies"] = json.loads(d["cookies"])
        result.append(d)
    return result


def update_account(account_id: int, **kwargs):
    conn = get_db()
    if "cookies" in kwargs and isinstance(kwargs["cookies"], list):
        kwargs["cookies"] = json.dumps(kwargs["cookies"], ensure_ascii=False)
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [account_id]
    conn.execute(f"UPDATE accounts SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def delete_account(account_id: int):
    conn = get_db()
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# Admin helpers
# ------------------------------------------------------------------

def admin_exists() -> bool:
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) as cnt FROM admin_users").fetchone()
    conn.close()
    return row["cnt"] > 0

def create_admin(username: str, password: str) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO admin_users (username, password_hash, created_at) VALUES (?, ?, ?)",
        (username, generate_password_hash(password), datetime.utcnow().isoformat()),
    )
    conn.commit()
    admin_id = cur.lastrowid
    conn.close()
    return admin_id

def verify_admin(username: str, password: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM admin_users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row and check_password_hash(row["password_hash"], password):
        return {"id": row["id"], "username": row["username"]}
    return None


# ------------------------------------------------------------------
# Task helpers
# ------------------------------------------------------------------

def add_task(task_id: str, account_id: int, filename: str,
             description: str = "", tags: str = "") -> str:
    now = datetime.utcnow().isoformat()
    conn = get_db()
    conn.execute(
        "INSERT INTO tasks (id, account_id, status, filename, description, tags, message, created_at, updated_at) "
        "VALUES (?, ?, 'IN_QUEUE', ?, ?, ?, 'Queued for upload.', ?, ?)",
        (task_id, account_id, filename, description, tags, now, now),
    )
    conn.commit()
    conn.close()
    return task_id


def update_task(task_id: str, **kwargs):
    conn = get_db()
    kwargs["updated_at"] = datetime.utcnow().isoformat()
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [task_id]
    conn.execute(f"UPDATE tasks SET {sets} WHERE id = ?", vals)
    conn.commit()
    conn.close()


def get_task(task_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute(
        "SELECT t.*, a.name as account_name FROM tasks t "
        "LEFT JOIN accounts a ON t.account_id = a.id WHERE t.id = ?",
        (task_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_tasks() -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT t.*, a.name as account_name FROM tasks t "
        "LEFT JOIN accounts a ON t.account_id = a.id "
        "ORDER BY t.created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
