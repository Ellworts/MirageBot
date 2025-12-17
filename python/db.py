import json
import os
import random
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")
ITEMS_PATH = os.path.join(os.path.dirname(__file__), "items.json")


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA foreign_keys=ON;")
    return con


def load_items() -> List[Dict[str, Any]]:
    with open(ITEMS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def init_db() -> None:
    con = _conn()
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            created_at TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS world_items (
            item_id TEXT PRIMARY KEY,
            owner_user_id INTEGER,
            claimed_at TEXT,
            FOREIGN KEY(owner_user_id) REFERENCES players(user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS player_items (
            user_id INTEGER,
            item_id TEXT,
            equipped INTEGER DEFAULT 0,
            acquired_at TEXT,
            PRIMARY KEY(user_id, item_id),
            FOREIGN KEY(user_id) REFERENCES players(user_id),
            FOREIGN KEY(item_id) REFERENCES world_items(item_id)
        )
        """
    )

    con.commit()

    items = load_items()
    for it in items:
        cur.execute(
            "INSERT OR IGNORE INTO world_items(item_id, owner_user_id, claimed_at) VALUES(?, NULL, NULL)",
            (it["id"],),
        )

    con.commit()
    con.close()


def ensure_player(user_id: int, username: Optional[str]) -> None:
    con = _conn()
    cur = con.cursor()
    cur.execute("SELECT user_id FROM players WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if row is None:
        cur.execute(
            "INSERT INTO players(user_id, username, created_at) VALUES(?, ?, ?)",
            (user_id, username or "", datetime.utcnow().isoformat()),
        )
    else:
        cur.execute(
            "UPDATE players SET username = ? WHERE user_id = ?",
            (username or "", user_id),
        )
    con.commit()
    con.close()


def get_unclaimed_item_ids() -> List[str]:
    con = _conn()
    cur = con.cursor()
    cur.execute("SELECT item_id FROM world_items WHERE owner_user_id IS NULL")
    rows = cur.fetchall()
    con.close()
    return [r["item_id"] for r in rows]


def pick_random_unclaimed_item_id() -> Optional[str]:
    ids = get_unclaimed_item_ids()
    if not ids:
        return None
    return random.choice(ids)


def claim_item(user_id: int, username: Optional[str], item_id: str) -> bool:
    ensure_player(user_id, username)
    con = _conn()
    cur = con.cursor()

    cur.execute("SELECT owner_user_id FROM world_items WHERE item_id = ?", (item_id,))
    row = cur.fetchone()
    if row is None:
        con.close()
        return False

    if row["owner_user_id"] is not None:
        con.close()
        return False

    now = datetime.utcnow().isoformat()
    cur.execute(
        "UPDATE world_items SET owner_user_id = ?, claimed_at = ? WHERE item_id = ? AND owner_user_id IS NULL",
        (user_id, now, item_id),
    )
    if cur.rowcount == 0:
        con.close()
        return False

    cur.execute(
        "INSERT OR IGNORE INTO player_items(user_id, item_id, equipped, acquired_at) VALUES(?, ?, 0, ?)",
        (user_id, item_id, now),
    )

    con.commit()
    con.close()
    return True


def get_player_items(user_id: int) -> List[sqlite3.Row]:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        """
        SELECT pi.item_id, pi.equipped, pi.acquired_at
        FROM player_items pi
        WHERE pi.user_id = ?
        ORDER BY pi.acquired_at DESC
        """,
        (user_id,),
    )
    rows = cur.fetchall()
    con.close()
    return rows


def count_equipped(user_id: int) -> int:
    con = _conn()
    cur = con.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM player_items WHERE user_id = ? AND equipped = 1",
        (user_id,),
    )
    row = cur.fetchone()
    con.close()
    return int(row["c"]) if row else 0


def set_equipped(user_id: int, item_id: str, equipped: bool, max_equipped: int = 3) -> Tuple[bool, str]:
    con = _conn()
    cur = con.cursor()

    cur.execute(
        "SELECT equipped FROM player_items WHERE user_id = ? AND item_id = ?",
        (user_id, item_id),
    )
    row = cur.fetchone()
    if row is None:
        con.close()
        return False, "У тебя нет этого предмета"

    if equipped:
        cur.execute(
            "SELECT COUNT(*) AS c FROM player_items WHERE user_id = ? AND equipped = 1",
            (user_id,),
        )
        c = int(cur.fetchone()["c"])
        if c >= max_equipped:
            con.close()
            return False, "Можно носить максимум 3 предмета. Сними один"
        cur.execute(
            "UPDATE player_items SET equipped = 1 WHERE user_id = ? AND item_id = ?",
            (user_id, item_id),
        )
        con.commit()
        con.close()
        return True, "Надето"

    cur.execute(
        "UPDATE player_items SET equipped = 0 WHERE user_id = ? AND item_id = ?",
        (user_id, item_id),
    )
    con.commit()
    con.close()
    return True, "Снято"


def item_index_by_id(items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {it["id"]: it for it in items}
