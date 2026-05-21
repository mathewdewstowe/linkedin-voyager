"""
PostClassifierAgent — Score and classify posts, draft comments.

Reads unclassified posts from linkedin_outreach.db for the given account.
Scores each 0–100 across ICP relevance, engagement signal, comment angle.
Drafts a comment per post using the account's persona.
Writes approved batch to outputs/pending/.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from outreach_db import _conn, now_utc, init_db

CONFIG_PATH = os.path.expanduser('~/Claude Projects/config/linkedin-accounts.json')
PENDING_DIR  = os.path.expanduser('~/Claude Projects/outputs/pending')
ACCOUNT = os.environ.get('LI_PROFILE', 'sonesse')


def _load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def _score_post(post: dict, stream_config: dict, account_cfg: dict) -> int:
    """
    Score a post 0–100.
    ICP relevance (40) + engagement signal (30) + comment opportunity (30).
    """
    text = (post.get('text_snippet', '') + ' ' + post.get('author_headline', '')).lower()
    score = 0

    # ICP relevance (40 pts) — keyword matching per stream
    queries = stream_config.get('queries', [])
    keywords = set(w for q in queries for w in re.findall(r'\b\w{4,}\b', q.lower()))
    hits = sum(1 for kw in keywords if kw in text)
    score += min(40, hits * 5)

    # Engagement signal (30 pts) — placeholder (no reaction count from search-posts)
    # When post-likers data is available this can be upgraded
    if len(post.get('text_snippet', '')) > 100:
        score += 15  # substantive post
    if post.get('author_slug'):
        score += 10  # identifiable author
    if post.get('post_url'):
        score += 5

    # Comment opportunity (30 pts) — question, opinion, data point
    snippet = post.get('text_snippet', '').lower()
    if '?' in snippet:
        score += 15
    if any(w in snippet for w in ['thoughts', 'agree', 'disagree', 'experience', 'lessons']):
        score += 10
    if any(w in snippet for w in ['%', 'data', 'study', 'report', 'results']):
        score += 5

    return min(100, score)


def _draft_comment(post: dict, account_cfg: dict) -> str:
    """
    Placeholder comment draft. In production this would call Claude API.
    Returns a structured prompt that the master agent will use to generate
    the actual comment via Claude.
    """
    persona = account_cfg.get('comment_persona_description', '')
    snippet = post.get('text_snippet', '')[:200]
    author = post.get('author_name', 'the author')

    return (
        f"[DRAFT NEEDED] Persona: {persona[:100]}. "
        f"Post by {author}: \"{snippet}\". "
        f"Write a 2–3 sentence comment: specific, adds value, no pitch."
    )


class PostClassifierAgent:
    def __init__(self, account: str = None, min_score: int = None):
        self.account = account or ACCOUNT
        init_db()
        cfg = _load_config()
        self.account_cfg = cfg.get(self.account, {})
        self.streams = {s['name']: s for s in self.account_cfg.get('streams', [])}
        self.global_min_score = min_score  # override per-stream min if set

    def run(self) -> dict:
        conn = _conn()
        posts = conn.execute("""
            SELECT * FROM posts
            WHERE account = ?
              AND status = 'new'
              AND deleted_at IS NULL
            ORDER BY seen_at DESC
        """, (self.account,)).fetchall()
        posts = [dict(p) for p in posts]

        print(f'  Classifying {len(posts)} posts for account: {self.account}')

        classified = []
        skipped = 0

        for post in posts:
            stream_name = post.get('stream_name', 'feed')
            stream_cfg = self.streams.get(stream_name, {})
            min_score = self.global_min_score or stream_cfg.get('min_score', 50)

            score = _score_post(post, stream_cfg, self.account_cfg)
            comment = _draft_comment(post, self.account_cfg)

            if score >= min_score:
                conn.execute("""
                    UPDATE posts SET score=?, drafted_comment=?, status='classified'
                    WHERE id=?
                """, (score, comment, post['id']))
                classified.append({**post, 'score': score, 'drafted_comment': comment})
            else:
                conn.execute("UPDATE posts SET score=?, status='skipped' WHERE id=?",
                             (score, post['id']))
                skipped += 1

        conn.commit()
        conn.close()

        # Sort by score desc
        classified.sort(key=lambda p: p['score'], reverse=True)

        # Write pending batch
        batch_path = self._write_pending(classified)

        print(f'  Classified: {len(classified)} | Skipped (low score): {skipped}')
        print(f'  Pending batch: {batch_path}')

        return {
            'account': self.account,
            'classified': len(classified),
            'skipped': skipped,
            'pending_file': batch_path,
        }

    def _write_pending(self, posts: list[dict]) -> str:
        os.makedirs(PENDING_DIR, exist_ok=True)
        date = datetime.now().strftime('%Y-%m-%d')
        path = os.path.join(PENDING_DIR, f'{date}-posts-{self.account}.md')

        lines = [
            f'# LinkedIn Post Classifier — {date}',
            f'Account: {self.account} ({self.account_cfg.get("email","")})',
            f'Total classified: {len(posts)}',
            '',
        ]

        # Group by stream
        by_stream: dict[str, list] = {}
        for p in posts:
            by_stream.setdefault(p.get('stream_name', 'feed'), []).append(p)

        for stream_name, stream_posts in by_stream.items():
            lines.append(f'## Stream: {stream_name}')
            for p in stream_posts:
                lines += [
                    f"- [ ] **{p.get('author_name','Unknown')}** · Score: {p.get('score',0)}",
                    f"  URL: {p.get('post_url','')}",
                    f"  Snippet: {p.get('text_snippet','')[:150]}",
                    f"  Draft comment: {p.get('drafted_comment','')}",
                    f"  Action: Like + Comment / Like only / Skip",
                    '',
                ]

        with open(path, 'w') as f:
            f.write('\n'.join(lines))

        return path


if __name__ == '__main__':
    agent = PostClassifierAgent()
    result = agent.run()
    print(result)
