"""
ConnectorAgent — Send no-note connection invites via browser automation.

LinkedIn migrated invite send to SDUI (Server-Driven UI), so direct
Voyager HTTP calls are not possible. This agent uses Playwright to
navigate to each profile and click Connect → Send without a note.
"""

import uuid
from datetime import datetime
from browser import LinkedInBrowser
from store import LinkedVoyagerStore
from config import DAILY_INVITE_CAP, THROTTLE_WRITE_MIN, THROTTLE_WRITE_MAX

import time
import random


class ConnectorAgent:
    def __init__(self, store: LinkedVoyagerStore):
        self.store = store

    def run(self, limit=None) -> dict:
        """
        Send no-note invites from the pending queue using browser automation.

        Returns:
            dict with sent_count, skipped, errors, daily_cap_hit
        """
        if limit is None:
            limit = DAILY_INVITE_CAP

        results = {
            'sent_count': 0,
            'skipped': 0,
            'errors': [],
            'daily_cap_hit': False
        }

        # Check daily counter
        daily = self.store.get_daily_counters()
        sent_today = daily.get('invites_sent', 0)

        if sent_today >= DAILY_INVITE_CAP:
            results['daily_cap_hit'] = True
            print(f'[ConnectorAgent] Daily invite cap hit ({sent_today}/{DAILY_INVITE_CAP})')
            return results

        remaining_today = DAILY_INVITE_CAP - sent_today
        batch_size = min(limit, remaining_today)

        print(f'[ConnectorAgent] Sending up to {batch_size} invites ({sent_today}/{DAILY_INVITE_CAP} sent today)')

        pending = self.store.get_pending_queue(limit=batch_size)
        print(f'[ConnectorAgent] Found {len(pending)} pending in queue')

        if not pending:
            return results

        with LinkedInBrowser() as browser:
            for author in pending:
                author_name = author.get('author_name', 'Unknown')
                author_id = author.get('author_id')   # profile slug
                author_urn = author.get('author_urn')

                print(f'[ConnectorAgent] → {author_name} ({author_id})')

                try:
                    result = browser.send_invite(author_id)

                    if not result.get('success'):
                        err = result.get('error', 'Unknown error')
                        results['errors'].append(f'{author_name}: {err}')
                        results['skipped'] += 1
                        continue

                    # Log to DB
                    invite_id = str(uuid.uuid4())
                    self.store.log_invite(
                        invite_id=invite_id,
                        recipient_id=author_id,
                        recipient_name=author_name,
                        recipient_urn=author_urn or '',
                        sent_from_post_id=author.get('from_post_id', ''),
                        invitation_id=invite_id
                    )

                    results['sent_count'] += 1
                    sent_today += 1
                    print(f'  ✓ Sent')

                    if sent_today >= DAILY_INVITE_CAP:
                        results['daily_cap_hit'] = True
                        break

                    # Human-like delay between sends
                    delay = random.uniform(THROTTLE_WRITE_MIN, THROTTLE_WRITE_MAX)
                    print(f'  Waiting {delay:.0f}s...')
                    time.sleep(delay)

                except Exception as e:
                    results['errors'].append(f'{author_name}: {str(e)}')
                    results['skipped'] += 1

        return results
