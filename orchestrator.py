"""
LinkedVoyagerOrchestrator — Schedules and runs agents
Enforces throttling, daily caps, and business hours.

Architecture (2025): LinkedIn migrated to SDUI/RSC so all browser
interactions (invite, withdraw, search) use Playwright automation.
"""

import time
import random
from datetime import datetime
import pytz

from store import LinkedVoyagerStore
from agents.post_search import PostSearchAgent
from agents.connector import ConnectorAgent
from agents.withdrawer import WithdrawerAgent
from config import (
    BUSINESS_HOURS_START, BUSINESS_HOURS_END, ACCOUNT_TIMEZONE,
    THROTTLE_PHASE_MIN, THROTTLE_PHASE_MAX,
    DAILY_INVITE_CAP, DAILY_COMMENT_CAP, DAILY_WITHDRAW_CAP
)


class LinkedVoyagerOrchestrator:
    def __init__(self):
        self.store = LinkedVoyagerStore()
        self.searcher = PostSearchAgent(self.store)
        self.connector = ConnectorAgent(self.store)
        self.withdrawer = WithdrawerAgent(self.store)

    def run(self, skip_hours_check=False) -> dict:
        """
        Run full orchestrator cycle:
        1. Search people → queue prospects
        2. Send invites (FIFO from queue)
        3. Withdraw stale invites

        Args:
            skip_hours_check: For testing, bypass business hours check

        Returns:
            Complete results from all agents
        """
        if not skip_hours_check and not self._in_business_hours():
            print(f'[Orchestrator] Outside business hours ({BUSINESS_HOURS_START}am–{BUSINESS_HOURS_END}pm {ACCOUNT_TIMEZONE}). Stopping.')
            return None

        print(f'\n{"="*60}')
        print(f'[Orchestrator] Starting cycle at {datetime.now().isoformat()}')
        print(f'{"="*60}\n')

        all_results = {
            'timestamp': datetime.now().isoformat(),
            'search': None,
            'invites': None,
            'withdrawals': None,
            'errors': []
        }

        try:
            # 1. SEARCH
            print(f'[Phase 1/3] PEOPLE SEARCH')
            print(f'{"-"*40}')
            all_results['search'] = self.searcher.run()
            r = all_results['search']
            print(f'Found: {r["found_people"]} people, Queued: {r["queued_authors"]} authors\n')

            self._throttle_phase()

            # 2. INVITE
            print(f'[Phase 2/3] SENDING INVITES')
            print(f'{"-"*40}')
            all_results['invites'] = self.connector.run(limit=DAILY_INVITE_CAP)
            print(f'Sent: {all_results["invites"]["sent_count"]} invites\n')

            self._throttle_phase()

            # 3. WITHDRAW
            print(f'[Phase 3/3] WITHDRAWING STALE')
            print(f'{"-"*40}')
            all_results['withdrawals'] = self.withdrawer.run(limit=DAILY_WITHDRAW_CAP)
            print(f'Withdrawn: {all_results["withdrawals"]["withdrawn_count"]} stale invites\n')

            self._print_summary(all_results)

        except Exception as e:
            all_results['errors'].append(f'Orchestrator error: {str(e)}')
            print(f'[Orchestrator] ERROR: {str(e)}')

        return all_results

    def _in_business_hours(self) -> bool:
        tz = pytz.timezone(ACCOUNT_TIMEZONE)
        now = datetime.now(tz)
        return BUSINESS_HOURS_START <= now.hour < BUSINESS_HOURS_END

    def _throttle_phase(self):
        delay = random.uniform(THROTTLE_PHASE_MIN, THROTTLE_PHASE_MAX)
        print(f'[Throttle] Waiting {delay:.0f}s before next phase...\n')
        time.sleep(delay)

    def _print_summary(self, results):
        print(f'{"="*60}')
        print(f'CYCLE SUMMARY')
        print(f'{"="*60}')

        search = results.get('search', {}) or {}
        invites = results.get('invites', {}) or {}
        withdrawals = results.get('withdrawals', {}) or {}

        print(f'🔍 Search:     {search.get("found_people", 0)} found, {search.get("queued_authors", 0)} queued')
        print(f'📨 Invites:    {invites.get("sent_count", 0)} sent{"  (DAILY CAP)" if invites.get("daily_cap_hit") else ""}')
        print(f'🗑  Withdrawals: {withdrawals.get("withdrawn_count", 0)} removed')

        daily = self.store.get_daily_counters()
        print(f'\nDaily totals:')
        print(f'  Invites sent:  {daily.get("invites_sent", 0)}/{DAILY_INVITE_CAP}')
        print(f'  Withdrawals:   {daily.get("withdrawals", 0)}/{DAILY_WITHDRAW_CAP}')

        queue = self.store.get_queue_status()
        print(f'\nQueue status:')
        print(f'  Pending invites: {queue["pending_invites"]}')
        print(f'  Total sent:      {queue["invites_sent"]}')

        all_errors = []
        for key in ['search', 'invites', 'withdrawals']:
            res = results.get(key) or {}
            all_errors.extend(res.get('errors', []))
        all_errors.extend(results.get('errors', []))

        if all_errors:
            print(f'\n⚠️  Errors:')
            for err in all_errors:
                print(f'  - {err}')

        print(f'{"="*60}\n')

    def check_status(self) -> dict:
        """Get current queue and daily counter status"""
        queue = self.store.get_queue_status()
        daily = self.store.get_daily_counters()

        print(f'Queue Status:')
        print(f'  Pending invites: {queue["pending_invites"]}')
        print(f'  Invites sent:    {queue["invites_sent"]}')

        print(f'\nDaily Counters ({daily.get("date", "today")}):')
        print(f'  Invites:     {daily.get("invites_sent", 0)}/{DAILY_INVITE_CAP}')
        print(f'  Withdrawals: {daily.get("withdrawals", 0)}/{DAILY_WITHDRAW_CAP}')

        return {'queue': queue, 'daily': daily}
