"""
LinkedIn Outreach SQLite store.
DB: ~/Job Apply/linkedin_outreach.db
"""
import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.expanduser('~/Job Apply/linkedin_outreach.db')


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS outreach (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            linkedin_url    TEXT    NOT NULL UNIQUE,
            name            TEXT,
            company         TEXT,
            title           TEXT,
            account         TEXT    NOT NULL,  -- 'sonesse' | 'nth-layer'
            status          TEXT    NOT NULL DEFAULT 'new',
                                               -- new | messaged | replied | meeting_booked | closed
            created_at      TEXT    NOT NULL,
            last_activity_at TEXT,
            deleted_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            outreach_id     INTEGER NOT NULL REFERENCES outreach(id),
            message_num     INTEGER NOT NULL,  -- 1 / 2 / 3
            body            TEXT    NOT NULL,
            sent_at         TEXT    NOT NULL,
            status          TEXT    NOT NULL DEFAULT 'sent',  -- sent | failed
            UNIQUE(outreach_id, message_num)
        );

        CREATE TABLE IF NOT EXISTS replies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            outreach_id     INTEGER NOT NULL REFERENCES outreach(id),
            body            TEXT    NOT NULL,
            received_at     TEXT    NOT NULL,
            direction       TEXT    NOT NULL DEFAULT 'inbound'  -- inbound | outbound
        );

        CREATE INDEX IF NOT EXISTS idx_outreach_account  ON outreach(account);
        CREATE INDEX IF NOT EXISTS idx_outreach_status   ON outreach(status);
        CREATE INDEX IF NOT EXISTS idx_messages_outreach ON messages(outreach_id);
        CREATE INDEX IF NOT EXISTS idx_replies_outreach  ON replies(outreach_id);
    """)
    conn.commit()
    conn.close()


# ── Outreach ─────────────────────────────────────────────────── #

def upsert_lead(linkedin_url: str, name: str, company: str,
                title: str, account: str) -> int:
    """Insert or update a lead. Returns outreach id."""
    conn = _conn()
    existing = conn.execute(
        'SELECT id FROM outreach WHERE linkedin_url=?', (linkedin_url,)
    ).fetchone()
    if existing:
        conn.execute(
            'UPDATE outreach SET name=?, company=?, title=?, last_activity_at=? WHERE id=?',
            (name, company, title, now_utc(), existing['id'])
        )
        conn.commit()
        lead_id = existing['id']
    else:
        cur = conn.execute(
            'INSERT INTO outreach (linkedin_url, name, company, title, account, created_at) VALUES (?,?,?,?,?,?)',
            (linkedin_url, name, company, title, account, now_utc())
        )
        conn.commit()
        lead_id = cur.lastrowid
    conn.close()
    return lead_id


def set_status(outreach_id: int, status: str):
    conn = _conn()
    conn.execute(
        'UPDATE outreach SET status=?, last_activity_at=? WHERE id=?',
        (status, now_utc(), outreach_id)
    )
    conn.commit()
    conn.close()


def get_lead_by_url(linkedin_url: str) -> dict | None:
    conn = _conn()
    row = conn.execute(
        'SELECT * FROM outreach WHERE linkedin_url=? AND deleted_at IS NULL',
        (linkedin_url,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_leads_for_followup(account: str, days_since_msg1: int = 7) -> list[dict]:
    """Return leads messaged with msg 1 but no reply, past follow-up threshold."""
    conn = _conn()
    rows = conn.execute("""
        SELECT o.* FROM outreach o
        JOIN messages m ON m.outreach_id = o.id AND m.message_num = 1
        WHERE o.account = ?
          AND o.status = 'messaged'
          AND o.deleted_at IS NULL
          AND NOT EXISTS (SELECT 1 FROM messages WHERE outreach_id=o.id AND message_num=2)
          AND NOT EXISTS (SELECT 1 FROM replies WHERE outreach_id=o.id)
          AND julianday('now') - julianday(m.sent_at) >= ?
    """, (account, days_since_msg1)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Messages ─────────────────────────────────────────────────── #

def log_message(outreach_id: int, message_num: int,
                body: str, status: str = 'sent') -> int:
    conn = _conn()
    cur = conn.execute(
        'INSERT OR IGNORE INTO messages (outreach_id, message_num, body, sent_at, status) VALUES (?,?,?,?,?)',
        (outreach_id, message_num, body, now_utc(), status)
    )
    conn.commit()
    conn.close()
    return cur.lastrowid


def get_messages(outreach_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        'SELECT * FROM messages WHERE outreach_id=? ORDER BY message_num',
        (outreach_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def already_sent(outreach_id: int, message_num: int) -> bool:
    conn = _conn()
    exists = conn.execute(
        'SELECT 1 FROM messages WHERE outreach_id=? AND message_num=?',
        (outreach_id, message_num)
    ).fetchone()
    conn.close()
    return bool(exists)


# ── Replies ──────────────────────────────────────────────────── #

def log_reply(outreach_id: int, body: str,
              direction: str = 'inbound', received_at: str = None):
    conn = _conn()
    conn.execute(
        'INSERT INTO replies (outreach_id, body, received_at, direction) VALUES (?,?,?,?)',
        (outreach_id, body, received_at or now_utc(), direction)
    )
    conn.commit()
    set_status(outreach_id, 'replied')
    conn.close()


def get_replies(outreach_id: int) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        'SELECT * FROM replies WHERE outreach_id=? ORDER BY received_at',
        (outreach_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Reports ──────────────────────────────────────────────────── #

def summary(account: str = None) -> dict:
    conn = _conn()
    where = 'WHERE deleted_at IS NULL' + (f" AND account='{account}'" if account else '')
    total    = conn.execute(f'SELECT COUNT(*) FROM outreach {where}').fetchone()[0]
    by_status = conn.execute(
        f'SELECT status, COUNT(*) FROM outreach {where} GROUP BY status'
    ).fetchall()
    conn.close()
    return {'total': total, 'by_status': {r[0]: r[1] for r in by_status}}


if __name__ == '__main__':
    init_db()
    print(f'DB initialised at {DB_PATH}')
    print(summary())
