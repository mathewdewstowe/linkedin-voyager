"""
SQLite store for LinkedIn message sync.
DB lives at ~/Job Apply/linked-voyager.db (shared with the campaign tables).
"""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.expanduser('~/Job Apply/linked-voyager.db')


def _conn():
    """Open a connection and ensure schema exists. Idempotent."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS msg_conversations (
            conversation_urn   TEXT PRIMARY KEY,
            participant_name   TEXT,
            participant_slug   TEXT,
            participant_url    TEXT,
            last_message_at    INTEGER,
            unread_count       INTEGER,
            last_synced_at     INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS msg_messages (
            message_urn        TEXT PRIMARY KEY,
            conversation_urn   TEXT,
            sender_name        TEXT,
            sender_slug        TEXT,
            sender_url         TEXT,
            text               TEXT,
            sent_at            INTEGER,
            sent_at_iso        TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_conv ON msg_messages(conversation_urn)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_sent ON msg_messages(sent_at)")
    conn.commit()
    return conn


def upsert_conversation(conv: dict) -> None:
    conn = _conn()
    conn.execute("""
        INSERT INTO msg_conversations
          (conversation_urn, participant_name, participant_slug,
           participant_url, last_message_at, unread_count, last_synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(conversation_urn) DO UPDATE SET
          participant_name = excluded.participant_name,
          participant_url  = excluded.participant_url,
          last_message_at  = excluded.last_message_at,
          unread_count     = excluded.unread_count,
          last_synced_at   = excluded.last_synced_at
    """, (
        conv['conversation_urn'],
        conv.get('participant_name', ''),
        (conv.get('participant_url', '') or '').rstrip('/').split('/')[-1],
        conv.get('participant_url', ''),
        conv.get('last_message_at', 0),
        conv.get('unread_count', 0),
        int(datetime.utcnow().timestamp() * 1000),
    ))
    conn.commit()
    conn.close()


def insert_messages(messages: list) -> int:
    """Insert messages. Returns count of NEW rows added."""
    if not messages:
        return 0
    conn = _conn()
    before = conn.execute('SELECT COUNT(*) FROM msg_messages').fetchone()[0]
    conn.executemany("""
        INSERT OR IGNORE INTO msg_messages
          (message_urn, conversation_urn, sender_name, sender_slug,
           sender_url, text, sent_at, sent_at_iso)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (
            m['message_urn'],
            m['conversation_urn'],
            m.get('sender_name', ''),
            m.get('sender_slug', ''),
            m.get('sender_url', ''),
            m.get('text', ''),
            m.get('sent_at', 0),
            datetime.utcfromtimestamp((m.get('sent_at', 0) or 0) / 1000).strftime('%Y-%m-%d %H:%M:%S UTC')
                if m.get('sent_at') else '',
        )
        for m in messages
    ])
    conn.commit()
    after = conn.execute('SELECT COUNT(*) FROM msg_messages').fetchone()[0]
    conn.close()
    return after - before


def latest_message_timestamp(conversation_urn: str) -> int:
    """Return the most recent sent_at for a conversation (0 if empty)."""
    conn = _conn()
    row = conn.execute(
        'SELECT MAX(sent_at) FROM msg_messages WHERE conversation_urn = ?',
        (conversation_urn,)
    ).fetchone()
    conn.close()
    return row[0] or 0


def stats() -> dict:
    conn = _conn()
    convo_count = conn.execute('SELECT COUNT(*) FROM msg_conversations').fetchone()[0]
    msg_count   = conn.execute('SELECT COUNT(*) FROM msg_messages').fetchone()[0]
    sender_count = conn.execute('SELECT COUNT(DISTINCT sender_slug) FROM msg_messages WHERE sender_slug != ""').fetchone()[0]
    last_msg = conn.execute('SELECT MAX(sent_at_iso) FROM msg_messages').fetchone()[0]
    by_person = conn.execute("""
        SELECT
          c.participant_name,
          c.participant_slug,
          COUNT(m.message_urn) AS msg_count,
          MAX(m.sent_at_iso)   AS last_msg
        FROM msg_conversations c
        LEFT JOIN msg_messages m ON m.conversation_urn = c.conversation_urn
        GROUP BY c.conversation_urn
        ORDER BY msg_count DESC
        LIMIT 20
    """).fetchall()
    conn.close()
    return {
        'conversations': convo_count,
        'messages':      msg_count,
        'unique_senders': sender_count,
        'last_message':  last_msg,
        'top_by_volume': by_person,
        'db_path':       DB_PATH,
    }


def messages_with(slug_or_name: str, limit: int = 200) -> list:
    """Get all messages exchanged with a person, by slug OR partial name match."""
    conn = _conn()
    rows = conn.execute("""
        SELECT m.sent_at_iso, m.sender_name, m.text
        FROM msg_messages m
        JOIN msg_conversations c ON c.conversation_urn = m.conversation_urn
        WHERE c.participant_slug = ?
           OR c.participant_name LIKE ?
        ORDER BY m.sent_at ASC
        LIMIT ?
    """, (slug_or_name, f'%{slug_or_name}%', limit)).fetchall()
    conn.close()
    return rows
