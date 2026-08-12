"""SQLite-шар. Асинхронний доступ через aiosqlite."""
import difflib
from datetime import date, datetime
from typing import Any, Optional

import aiosqlite

import config

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id        INTEGER NOT NULL UNIQUE,
    username     TEXT,
    full_name    TEXT NOT NULL,
    position     TEXT,
    phone        TEXT,
    role         TEXT NOT NULL DEFAULT 'employee',   -- employee | manager
    group_id     INTEGER REFERENCES groups(id) ON DELETE SET NULL,
    hourly_rate  REAL,
    status       TEXT NOT NULL DEFAULT 'active',     -- active | fired
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shifts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,              -- YYYY-MM-DD
    start_at    TEXT,                       -- HH:MM
    end_at      TEXT,                       -- HH:MM
    hours       REAL,                       -- відпрацьовано годин
    kind        TEXT NOT NULL DEFAULT 'regular',  -- regular | extra
    comment     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_shifts_user_day ON shifts(user_id, day);

CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,              -- dayoff | sick | extra_shift
    date_from   TEXT NOT NULL,
    date_to     TEXT NOT NULL,
    comment     TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | approved | rejected
    decided_by  INTEGER,
    decided_at  TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    text        TEXT NOT NULL,
    is_read     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS absences (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day         TEXT NOT NULL,
    reason      TEXT,
    created_by  INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS cover_offers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,  -- кому запропонували
    absent_user INTEGER REFERENCES users(id) ON DELETE SET NULL,          -- кого замінює
    day         TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',   -- pending | accepted | declined
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reminders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    remind_at   TEXT NOT NULL,              -- YYYY-MM-DD HH:MM
    text        TEXT NOT NULL,
    is_sent     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL,
    role        TEXT NOT NULL,              -- user | assistant
    content     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_history_tg ON history(tg_id, id);
"""


async def _conn() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(config.DB_PATH)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA foreign_keys=ON")
    return conn


async def init_db() -> None:
    async with aiosqlite.connect(config.DB_PATH) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()


async def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    conn = await _conn()
    try:
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def fetch_one(sql: str, params: tuple = ()) -> Optional[dict]:
    rows = await fetch_all(sql, params)
    return rows[0] if rows else None


async def execute(sql: str, params: tuple = ()) -> int:
    conn = await _conn()
    try:
        cur = await conn.execute(sql, params)
        await conn.commit()
        return cur.lastrowid
    finally:
        await conn.close()


# ---------------- users ----------------

async def get_user_by_tg(tg_id: int) -> Optional[dict]:
    return await fetch_one(
        "SELECT u.*, g.name AS group_name FROM users u "
        "LEFT JOIN groups g ON g.id = u.group_id WHERE u.tg_id = ?",
        (tg_id,),
    )


async def get_user(user_id: int) -> Optional[dict]:
    return await fetch_one(
        "SELECT u.*, g.name AS group_name FROM users u "
        "LEFT JOIN groups g ON g.id = u.group_id WHERE u.id = ?",
        (user_id,),
    )


async def create_user(tg_id: int, full_name: str, position: str | None,
                      phone: str | None, username: str | None,
                      role: str = "employee", status: str = "active") -> int:
    return await execute(
        "INSERT INTO users (tg_id, username, full_name, position, phone, role, hourly_rate, status) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (tg_id, username, full_name.strip(), position, phone, role,
         config.DEFAULT_HOURLY_RATE, status),
    )


async def list_users(group_id: int | None = None, only_active: bool = True) -> list[dict]:
    sql = ("SELECT u.*, g.name AS group_name FROM users u "
           "LEFT JOIN groups g ON g.id = u.group_id WHERE 1=1")
    params: list[Any] = []
    if group_id is not None:
        sql += " AND u.group_id = ?"
        params.append(group_id)
    if only_active:
        sql += " AND u.status = 'active'"
    sql += " ORDER BY u.full_name"
    return await fetch_all(sql, tuple(params))


async def search_users(query: str, limit: int = 5) -> list[dict]:
    """Нечіткий пошук по частині ПІБ: 'Кравець' знайде 'Кравець Василь'."""
    q = (query or "").strip().lower()
    if not q:
        return []
    users = await list_users(only_active=False)

    scored: list[tuple[float, dict]] = []
    for u in users:
        name = u["full_name"].lower()
        parts = name.split()
        if q in name:                              # пряме входження підрядка
            score = 1.0
        elif any(p.startswith(q) for p in parts):  # початок будь-якого слова
            score = 0.9
        else:                                      # опечатки
            score = max(
                [difflib.SequenceMatcher(None, q, p).ratio() for p in parts] + [0.0]
            )
        if score >= 0.62:
            scored.append((score, u))
    scored.sort(key=lambda x: (-x[0], x[1]["full_name"]))
    return [u for _, u in scored[:limit]]


async def set_user_group(user_id: int, group_id: int) -> None:
    await execute("UPDATE users SET group_id = ? WHERE id = ?", (group_id, user_id))


async def set_user_rate(user_id: int, rate: float) -> None:
    await execute("UPDATE users SET hourly_rate = ? WHERE id = ?", (rate, user_id))


async def set_user_status(user_id: int, status: str) -> None:
    await execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))


# ---------------- groups ----------------

async def create_group(name: str) -> int:
    exists = await fetch_one("SELECT id FROM groups WHERE lower(name) = lower(?)", (name.strip(),))
    if exists:
        return exists["id"]
    return await execute("INSERT INTO groups (name) VALUES (?)", (name.strip(),))


async def list_groups() -> list[dict]:
    return await fetch_all(
        "SELECT g.*, (SELECT COUNT(*) FROM users u WHERE u.group_id = g.id AND u.status='active') "
        "AS members FROM groups g ORDER BY g.name"
    )


async def find_group(query: str) -> Optional[dict]:
    q = (query or "").strip().lower()
    groups = await list_groups()
    for g in groups:
        if g["name"].lower() == q:
            return g
    for g in groups:
        if q and q in g["name"].lower():
            return g
    names = [g["name"].lower() for g in groups]
    match = difflib.get_close_matches(q, names, n=1, cutoff=0.7)
    if match:
        return next(g for g in groups if g["name"].lower() == match[0])
    return None


# ---------------- shifts ----------------

async def add_shift(user_id: int, day: str, hours: float, kind: str = "regular",
                    start_at: str | None = None, end_at: str | None = None,
                    comment: str | None = None) -> int:
    return await execute(
        "INSERT INTO shifts (user_id, day, start_at, end_at, hours, kind, comment) "
        "VALUES (?,?,?,?,?,?,?)",
        (user_id, day, start_at, end_at, hours, kind, comment),
    )


async def open_shift(user_id: int, day: str, start_at: str) -> int:
    return await execute(
        "INSERT INTO shifts (user_id, day, start_at, kind) VALUES (?,?,?,'regular')",
        (user_id, day, start_at),
    )


async def get_open_shift(user_id: int) -> Optional[dict]:
    return await fetch_one(
        "SELECT * FROM shifts WHERE user_id = ? AND end_at IS NULL ORDER BY id DESC LIMIT 1",
        (user_id,),
    )


async def close_shift(shift_id: int, end_at: str, hours: float) -> None:
    await execute("UPDATE shifts SET end_at = ?, hours = ? WHERE id = ?", (end_at, hours, shift_id))


async def shifts_between(date_from: str, date_to: str, user_id: int | None = None,
                         group_id: int | None = None) -> list[dict]:
    sql = ("SELECT s.*, u.full_name, u.hourly_rate, u.group_id, g.name AS group_name "
           "FROM shifts s JOIN users u ON u.id = s.user_id "
           "LEFT JOIN groups g ON g.id = u.group_id "
           "WHERE s.day BETWEEN ? AND ?")
    params: list[Any] = [date_from, date_to]
    if user_id:
        sql += " AND s.user_id = ?"
        params.append(user_id)
    if group_id:
        sql += " AND u.group_id = ?"
        params.append(group_id)
    sql += " ORDER BY s.day, u.full_name"
    return await fetch_all(sql, tuple(params))


async def total_hours(user_id: int, date_from: str, date_to: str) -> float:
    row = await fetch_one(
        "SELECT COALESCE(SUM(hours),0) AS h FROM shifts "
        "WHERE user_id = ? AND day BETWEEN ? AND ?",
        (user_id, date_from, date_to),
    )
    return float(row["h"] if row else 0)


# ---------------- requests ----------------

async def add_request(user_id: int, kind: str, date_from: str, date_to: str,
                      comment: str | None) -> int:
    return await execute(
        "INSERT INTO requests (user_id, kind, date_from, date_to, comment) VALUES (?,?,?,?,?)",
        (user_id, kind, date_from, date_to, comment),
    )


async def list_requests(status: str | None = "pending", user_id: int | None = None,
                        date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    sql = ("SELECT r.*, u.full_name, u.tg_id, g.name AS group_name FROM requests r "
           "JOIN users u ON u.id = r.user_id LEFT JOIN groups g ON g.id = u.group_id WHERE 1=1")
    params: list[Any] = []
    if status:
        sql += " AND r.status = ?"
        params.append(status)
    if user_id:
        sql += " AND r.user_id = ?"
        params.append(user_id)
    if date_from and date_to:
        sql += " AND NOT (r.date_to < ? OR r.date_from > ?)"
        params += [date_from, date_to]
    sql += " ORDER BY r.date_from"
    return await fetch_all(sql, tuple(params))


async def get_request(req_id: int) -> Optional[dict]:
    return await fetch_one(
        "SELECT r.*, u.full_name, u.tg_id FROM requests r JOIN users u ON u.id = r.user_id "
        "WHERE r.id = ?",
        (req_id,),
    )


async def decide_request(req_id: int, status: str, manager_tg: int) -> None:
    await execute(
        "UPDATE requests SET status = ?, decided_by = ?, decided_at = datetime('now') WHERE id = ?",
        (status, manager_tg, req_id),
    )


# ---------------- notes / absences / offers / reminders ----------------

async def add_note(user_id: int, text: str) -> int:
    return await execute("INSERT INTO notes (user_id, text) VALUES (?,?)", (user_id, text))


async def list_notes(unread_only: bool = True, limit: int = 20) -> list[dict]:
    sql = ("SELECT n.*, u.full_name FROM notes n JOIN users u ON u.id = n.user_id "
           "WHERE 1=1")
    if unread_only:
        sql += " AND n.is_read = 0"
    sql += " ORDER BY n.id DESC LIMIT ?"
    return await fetch_all(sql, (limit,))


async def mark_notes_read() -> None:
    await execute("UPDATE notes SET is_read = 1 WHERE is_read = 0")


async def add_absence(user_id: int, day: str, reason: str | None, created_by: int) -> int:
    return await execute(
        "INSERT INTO absences (user_id, day, reason, created_by) VALUES (?,?,?,?)",
        (user_id, day, reason, created_by),
    )


async def absences_between(date_from: str, date_to: str) -> list[dict]:
    return await fetch_all(
        "SELECT a.*, u.full_name FROM absences a JOIN users u ON u.id = a.user_id "
        "WHERE a.day BETWEEN ? AND ? ORDER BY a.day",
        (date_from, date_to),
    )


async def is_unavailable(user_id: int, day: str) -> bool:
    """Чи людина вже недоступна цього дня (відсутність / вихідний / лікарняний)."""
    a = await fetch_one("SELECT 1 AS x FROM absences WHERE user_id = ? AND day = ?", (user_id, day))
    if a:
        return True
    r = await fetch_one(
        "SELECT 1 AS x FROM requests WHERE user_id = ? AND status IN ('approved','pending') "
        "AND kind IN ('dayoff','sick') AND ? BETWEEN date_from AND date_to",
        (user_id, day),
    )
    return bool(r)


async def add_cover_offer(user_id: int, absent_user: int | None, day: str) -> int:
    return await execute(
        "INSERT INTO cover_offers (user_id, absent_user, day) VALUES (?,?,?)",
        (user_id, absent_user, day),
    )


async def last_pending_offer(user_id: int) -> Optional[dict]:
    return await fetch_one(
        "SELECT * FROM cover_offers WHERE user_id = ? AND status = 'pending' "
        "ORDER BY id DESC LIMIT 1",
        (user_id,),
    )


async def set_offer_status(offer_id: int, status: str) -> None:
    await execute("UPDATE cover_offers SET status = ? WHERE id = ?", (status, offer_id))


async def add_reminder(user_id: int, remind_at: str, text: str) -> int:
    return await execute(
        "INSERT INTO reminders (user_id, remind_at, text) VALUES (?,?,?)",
        (user_id, remind_at, text),
    )


async def due_reminders(now: str) -> list[dict]:
    return await fetch_all(
        "SELECT r.*, u.tg_id FROM reminders r JOIN users u ON u.id = r.user_id "
        "WHERE r.is_sent = 0 AND r.remind_at <= ?",
        (now,),
    )


async def mark_reminder_sent(rid: int) -> None:
    await execute("UPDATE reminders SET is_sent = 1 WHERE id = ?", (rid,))


# ---------------- history ----------------

async def add_history(tg_id: int, role: str, content: str) -> None:
    await execute("INSERT INTO history (tg_id, role, content) VALUES (?,?,?)",
                  (tg_id, role, content))


async def get_history(tg_id: int, limit: int = 12) -> list[dict]:
    rows = await fetch_all(
        "SELECT role, content FROM history WHERE tg_id = ? ORDER BY id DESC LIMIT ?",
        (tg_id, limit),
    )
    return list(reversed(rows))


async def clear_history(tg_id: int) -> None:
    await execute("DELETE FROM history WHERE tg_id = ?", (tg_id,))
