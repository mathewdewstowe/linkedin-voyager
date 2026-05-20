"""
WithdrawerAgent — Withdraw stale pending invites via browser automation.

LinkedIn's withdrawal flow uses SDUI — direct API not accessible.
This agent uses Playwright to navigate to each profile and click Withdraw.
"""

import time
import random
from datetime import datetime, timedelta
from browser import LinkedInBrowser
from store import LinkedVoyagerStore
from config import WITHDRAW_AFTER_DAYS, DAILY_WITHDRAW_CAP, THROTTLE_WRITE_MIN, THROTTLE_WRITE_MAX
import sqlite3
from pathlib import Path
from config import DB_PATH


class WithdrawerAgent:
    def __init__(self, store: LinkedVoyagerStore):
        self.store = store

    def run(self, limit=None) -> dict:
        """
        Withdraw stale pending invites (no response after WITHDRAW_AFTER_DAYS).

        Strategy:
        1. Get sent invites from SQLite that are older than threshold
        2. For each, navigate to the profile and click Withdraw
        3. Update SQLite status to 'withdrawn'

        Returns:
            dict with withdrawn_count, skipped, errors, daily_cap_hit
        """
        if limit is None:
            limit = DAILY_WITHDRAW_CAP

        results = {
            'withdrawn_count': 0,
            'skipped': 0,
            'errors': [],
            'daily_cap_hit': False
        }

        daily = self.store.get_daily_counters()
        withdrawn_today = daily.get('withdrawals', 0)

        if withdrawn_today >= DAILY_WITHDRAW_CAP:
            results['daily_cap_hit'] = True
            print(f'[WithdrawerAgent] Daily cap hit ({withdrawn_today}/{DAILY_WITHDRAW_CAP})')
            return results

        remaining_today = DAILY_WITHDRAW_CAP - withdrawn_today
        batch_size = min(limit, remaining_today)

        print(f'[WithdrawerAgent] Checking for invites older than {WITHDRAW_AFTER_DAYS} days')

        stale = self._get_stale_invites(batch_size)
        print(f'[WithdrawerAgent] Found {len(stale)} stale invites to withdraw')

        if not stale:
            return results

        with LinkedInBrowser() as browser:
            for invite in stale:
                slug = invite.get('recipient_id')   # We store slug as recipient_id
                name = invite.get('recipient_name', 'Unknown')
                invite_id = invite.get('id')

                print(f'[WithdrawerAgent] → Withdrawing: {name} ({slug})')

                try:
                    result = browser.withdraw_invite(slug)

                    if not result.get('success'):
                        err = result.get('error', 'Unknown')
                        results['errors'].append(f'{name}: {err}')
                        results['skipped'] += 1
                        continue

                    # Mark withdrawn in DB
                    self._mark_withdrawn(invite_id)

                    results['withdrawn_count'] += 1
                    withdrawn_today += 1
                    print(f'  ✓ Withdrawn')

                    if withdrawn_today >= DAILY_WITHDRAW_CAP:
                        results['daily_cap_hit'] = True
                        break

                    delay = random.uniform(THROTTLE_WRITE_MIN, THROTTLE_WRITE_MAX)
                    time.sleep(delay)

                except Exception as e:
                    results['errors'].append(f'{name}: {str(e)}')
                    results['skipped'] += 1

        return results

    def _get_stale_invites(self, limit: int) -> list:
        """Return invites sent > WITHDRAW_AFTER_DAYS ago with no response."""
        cutoff = datetime.now() - timedelta(days=WITHDRAW_AFTER_DAYS)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute('''
            SELECT * FROM invites_sent
            WHERE status = "sent"
              AND response IS NULL
              AND sent_at < ?
            ORDER BY sent_at ASC
            LIMIT ?
        ''', (cutoff.isoformat(), limit))
        rows = [dict(r) for r in c.fetchall()]
        conn.close()
        return rows

    def _mark_withdrawn(self, invite_id: str):
        """Mark an invite as withdrawn in the database."""
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            UPDATE invites_sent
            SET status = "withdrawn", withdrawn_at = CURRENT_TIMESTAMP
            WHERE id = ?
        ''', (invite_id,))
        # Increment daily counter
        c.execute('''
            INSERT INTO daily_counters (date, withdrawals, updated_at)
            VALUES (DATE("now"), 1, CURRENT_TIMESTAMP)
            ON CONFLICT(date) DO UPDATE SET
                withdrawals = withdrawals + 1,
                updated_at = CURRENT_TIMESTAMP
        ''')
        conn.commit()
        conn.close()
