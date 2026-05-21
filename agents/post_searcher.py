"""
PostSearcherAgent — Voyager-based LinkedIn post search.

Reads account config from config/linkedin-accounts.json.
Runs search-posts + my-feed for the specified account.
Deduplicates against posts seen in last 30 days.
Writes new posts to linkedin_outreach.db → posts table.
"""
from __future__ import annotations

import json
import os
import sys
import time
import random
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from browser import LinkedInBrowser
from outreach_db import _conn, now_utc, init_db

CONFIG_PATH = os.path.expanduser(
    '~/Claude Projects/config/linkedin-accounts.json'
)
ACCOUNT = os.environ.get('LI_PROFILE', 'sonesse')


def _ensure_posts_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            account          TEXT    NOT NULL,
            stream_name      TEXT    NOT NULL,
            post_urn         TEXT    UNIQUE,
            post_url         TEXT,
            author_name      TEXT,
            author_slug      TEXT,
            author_headline  TEXT,
            text_snippet     TEXT,
            seen_at          TEXT    NOT NULL,
            score            INTEGER,
            drafted_comment  TEXT,
            status           TEXT    NOT NULL DEFAULT 'new',
            actioned_at      TEXT,
            deleted_at       TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_account ON posts(account)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_status  ON posts(status)")
    conn.commit()


def _already_seen(conn, post_urn: str, days: int = 30) -> bool:
    row = conn.execute("""
        SELECT 1 FROM posts
        WHERE post_urn = ?
          AND deleted_at IS NULL
          AND julianday('now') - julianday(seen_at) <= ?
    """, (post_urn, days)).fetchone()
    return bool(row)


def _save_post(conn, account: str, stream: str, post: dict):
    conn.execute("""
        INSERT OR IGNORE INTO posts
            (account, stream_name, post_urn, post_url, author_name,
             author_slug, author_headline, text_snippet, seen_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        account, stream,
        post.get('post_urn', ''),
        post.get('post_url', ''),
        post.get('author_name', ''),
        post.get('author_slug', ''),
        post.get('headline', ''),
        post.get('text_snippet', '')[:500],
        now_utc(),
    ))
    conn.commit()


class PostSearcherAgent:
    def __init__(self, account: str = None):
        self.account = account or ACCOUNT
        init_db()
        self.config = self._load_config()
        self.account_cfg = self.config.get(self.account)
        if not self.account_cfg:
            raise ValueError(f'Account "{self.account}" not found in config')

    def _load_config(self) -> dict:
        with open(CONFIG_PATH) as f:
            return json.load(f)

    def run(self) -> dict:
        conn = _conn()
        _ensure_posts_table(conn)

        total_new = 0
        results = {}

        with LinkedInBrowser(headless=True) as br:
            # Search each stream
            for stream in self.account_cfg.get('streams', []):
                stream_name = stream['name']
                new_in_stream = 0
                print(f'\n  [stream] {stream_name}')

                for query in stream.get('queries', []):
                    print(f'    search-posts: "{query}"')
                    try:
                        posts = br.voyager_search_posts(query, count=20)
                    except Exception as e:
                        print(f'      ERROR: {e}')
                        posts = []

                    for post in posts:
                        urn = post.get('post_urn', '')
                        if not urn or _already_seen(conn, urn):
                            continue
                        _save_post(conn, self.account, stream_name, post)
                        new_in_stream += 1

                    time.sleep(random.uniform(5, 8))

                results[stream_name] = new_in_stream
                total_new += new_in_stream

            # Feed sweep
            feed_count = self.account_cfg.get('feed_count', 30)
            print(f'\n  [feed] my-feed ({feed_count} posts)')
            try:
                feed_posts = br.voyager_get_feed(count=feed_count)
            except Exception as e:
                print(f'    ERROR: {e}')
                feed_posts = []

            feed_new = 0
            for post in feed_posts:
                urn = post.get('post_urn', '')
                if not urn or _already_seen(conn, urn):
                    continue
                _save_post(conn, self.account, 'feed', post)
                feed_new += 1

            results['feed'] = feed_new
            total_new += feed_new

        conn.close()

        print(f'\n  Total new posts: {total_new}')
        return {'account': self.account, 'new_posts': total_new, 'by_stream': results}


if __name__ == '__main__':
    agent = PostSearcherAgent()
    result = agent.run()
    print(result)
