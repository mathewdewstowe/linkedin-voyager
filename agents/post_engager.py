"""
PostEngagerAgent — Like and comment on approved posts.

Reads approved posts from linkedin_outreach.db (status='approved').
Fires like + comment via Voyager.
Logs each action back to DB.

NOTE: like (react-post) and comment-post Voyager endpoints are not yet
captured. This agent is structured and ready — payload capture needed
before live sends work. See SKILL.md "Built but need payload capture".
"""
from __future__ import annotations

import os
import sys
import time
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from browser import LinkedInBrowser
from outreach_db import _conn, now_utc, init_db

ACCOUNT = os.environ.get('LI_PROFILE', 'sonesse')


class PostEngagerAgent:
    def __init__(self, account: str = None):
        self.account = account or ACCOUNT
        init_db()

    def run(self, dry_run: bool = True) -> dict:
        conn = _conn()
        posts = conn.execute("""
            SELECT * FROM posts
            WHERE account = ?
              AND status = 'approved'
              AND deleted_at IS NULL
            ORDER BY score DESC
        """, (self.account,)).fetchall()
        posts = [dict(p) for p in posts]

        print(f'  Engaging {len(posts)} approved posts (dry_run={dry_run})')

        liked = commented = errors = 0

        with LinkedInBrowser(headless=True) as br:
            for post in posts:
                urn = post.get('post_urn', '')
                comment = post.get('drafted_comment', '')
                print(f'  Post: {post.get("author_name")} | Score: {post.get("score")}')

                if dry_run:
                    print(f'    [DRY RUN] Would like + comment: {comment[:80]}')
                    continue

                # Like
                try:
                    result = br.react_post(urn, reaction='LIKE')
                    if result:
                        liked += 1
                        print(f'    ✅ Liked')
                    else:
                        print(f'    ❌ Like failed (endpoint needs payload capture)')
                except Exception as e:
                    print(f'    ❌ Like error: {e}')
                    errors += 1

                time.sleep(random.uniform(3, 8))

                # Comment
                if comment and not comment.startswith('[DRAFT NEEDED]'):
                    try:
                        result = br.comment_post(urn, comment)
                        if result:
                            commented += 1
                            print(f'    ✅ Commented')
                        else:
                            print(f'    ❌ Comment failed (endpoint needs payload capture)')
                    except Exception as e:
                        print(f'    ❌ Comment error: {e}')
                        errors += 1

                # Update DB
                conn.execute("""
                    UPDATE posts SET status='actioned', actioned_at=? WHERE id=?
                """, (now_utc(), post['id']))
                conn.commit()

                time.sleep(random.uniform(8, 20))

        conn.close()
        return {
            'account': self.account,
            'liked': liked,
            'commented': commented,
            'errors': errors,
            'dry_run': dry_run,
        }


if __name__ == '__main__':
    agent = PostEngagerAgent()
    result = agent.run(dry_run=True)
    print(result)
