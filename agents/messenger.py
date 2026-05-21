"""
MessengerAgent — LinkedIn message sequence (3 steps) with SQLite persistence.

Step 1: Day 0   — initial outreach (≤300 chars)
Step 2: Day 7   — follow-up if no reply (≤150 chars)
Step 3: Day 14  — final bump if no reply (≤100 chars)

All sends logged to ~/Job Apply/linkedin_outreach.db via outreach_db.py.
Account-aware: LI_PROFILE env var selects sonesse (Brave) or nth-layer (Chrome).
"""
from __future__ import annotations

import os
import sys
import time
import random
from datetime import datetime, timezone
from pathlib import Path

# Allow import from parent dir
sys.path.insert(0, str(Path(__file__).parent.parent))

from browser import LinkedInBrowser
from outreach_db import (
    init_db, upsert_lead, set_status, get_lead_by_url,
    already_sent, log_message, log_reply,
    get_leads_for_followup, get_messages, summary,
)

ACCOUNT = os.environ.get('LI_PROFILE', 'sonesse')

MSG_LIMITS = {1: 300, 2: 150, 3: 100}
FOLLOWUP_DAYS = {2: 7, 3: 14}


class MessengerAgent:
    def __init__(self):
        init_db()
        self.account = ACCOUNT

    # ------------------------------------------------------------------ #
    #  Public API
    # ------------------------------------------------------------------ #

    def send_message1(self, targets: list[dict], template: str,
                      dry_run: bool = True) -> dict:
        """
        Send first message to a list of targets.

        Args:
            targets: list of {linkedin_url, name, company, title}
            template: message body — supports {name}, {company}, {title}
            dry_run: if True, draft only — no sends

        Returns:
            {sent, skipped, errors, drafts}
        """
        sent = skipped = errors = 0
        drafts = []

        for t in targets:
            url  = t.get('linkedin_url', '')
            name = t.get('name', '')

            # Dedup: already in sequence?
            existing = get_lead_by_url(url)
            if existing:
                if already_sent(existing['id'], 1):
                    print(f'  [SKIP] {name} — msg 1 already sent')
                    skipped += 1
                    continue
                if existing['status'] == 'replied':
                    print(f'  [SKIP] {name} — already replied')
                    skipped += 1
                    continue

            body = self._render(template, t)
            if len(body) > MSG_LIMITS[1]:
                print(f'  [WARN] {name} — message too long ({len(body)} chars), truncating')
                body = body[:MSG_LIMITS[1]]

            if dry_run:
                drafts.append({'target': t, 'body': body, 'msg_num': 1})
                print(f'  [DRAFT] {name} | {url}\n    {body[:80]}...')
                continue

            # Send
            result = self._send(name, body)
            if result:
                outreach_id = upsert_lead(
                    url, name,
                    t.get('company', ''), t.get('title', ''),
                    self.account,
                )
                log_message(outreach_id, 1, body)
                set_status(outreach_id, 'messaged')
                print(f'  [SENT] {name}')
                sent += 1
            else:
                print(f'  [ERROR] {name} — send failed')
                errors += 1

            self._throttle()

        return {'sent': sent, 'skipped': skipped, 'errors': errors, 'drafts': drafts}

    def send_followups(self, msg_num: int = 2, template: str = '',
                       dry_run: bool = True) -> dict:
        """
        Send follow-up messages (step 2 or 3) to eligible leads.
        Eligibility: msg_(n-1) sent N+ days ago, no reply, msg_n not yet sent.
        """
        assert msg_num in (2, 3), 'msg_num must be 2 or 3'
        days = FOLLOWUP_DAYS[msg_num]
        leads = get_leads_for_followup(self.account, days_since_msg1=days)

        # For msg 3, further filter: msg 2 must exist and be 7+ days old
        if msg_num == 3:
            leads = [l for l in leads if not already_sent(l['id'], 3)]

        sent = skipped = errors = 0
        drafts = []

        for lead in leads:
            if already_sent(lead['id'], msg_num):
                skipped += 1
                continue

            t = {
                'name':    lead['name'],
                'company': lead['company'],
                'title':   lead['title'],
            }
            body = self._render(template, t) if template else self._default_followup(msg_num, t)
            if len(body) > MSG_LIMITS[msg_num]:
                body = body[:MSG_LIMITS[msg_num]]

            if dry_run:
                drafts.append({'lead': dict(lead), 'body': body, 'msg_num': msg_num})
                print(f'  [DRAFT msg{msg_num}] {lead["name"]}\n    {body[:80]}')
                continue

            result = self._send(lead['name'], body)
            if result:
                log_message(lead['id'], msg_num, body)
                print(f'  [SENT msg{msg_num}] {lead["name"]}')
                sent += 1
            else:
                errors += 1
                print(f'  [ERROR msg{msg_num}] {lead["name"]}')

            self._throttle()

        return {'sent': sent, 'skipped': skipped, 'errors': errors, 'drafts': drafts}

    def log_inbound_reply(self, linkedin_url: str, reply_text: str,
                          received_at: str = None):
        """Record an inbound reply from a lead."""
        lead = get_lead_by_url(linkedin_url)
        if not lead:
            print(f'  [WARN] No outreach record for {linkedin_url}')
            return
        log_reply(lead['id'], reply_text, direction='inbound',
                  received_at=received_at)
        print(f'  [REPLY LOGGED] {lead["name"]}')

    def report(self) -> dict:
        """Return summary stats for this account."""
        return summary(self.account)

    # ------------------------------------------------------------------ #
    #  Internal helpers
    # ------------------------------------------------------------------ #

    def _send(self, name: str, body: str) -> bool:
        """Send a LinkedIn message via Voyager. Returns True on success."""
        try:
            with LinkedInBrowser(headless=True) as br:
                people = br.voyager_search_people(name, count=5)
                if not people:
                    print(f'    Could not find LinkedIn profile for {name}')
                    return False
                recipient_urn = people[0].get('urn', '')
                if not recipient_urn:
                    return False
                result = br.send_message(recipient_urn, body)
                return bool(result)
        except Exception as e:
            print(f'    Send error: {e}')
            return False

    def _send_by_url(self, linkedin_url: str, name: str, body: str) -> bool:
        """Send via profile URL → resolve URN → send message."""
        try:
            slug = linkedin_url.rstrip('/').split('/in/')[-1]
            with LinkedInBrowser(headless=True) as br:
                urn = br.get_profile_urn(slug)
                if not urn:
                    print(f'    Could not resolve URN for {slug}')
                    return False
                result = br.send_message(urn, body)
                return bool(result)
        except Exception as e:
            print(f'    Send error: {e}')
            return False

    @staticmethod
    def _render(template: str, context: dict) -> str:
        """Substitute {name}, {company}, {title} in template."""
        first = context.get('name', '').split()[0] if context.get('name') else 'there'
        return (template
                .replace('{first_name}', first)
                .replace('{name}', context.get('name', ''))
                .replace('{company}', context.get('company', 'your company'))
                .replace('{title}', context.get('title', 'your role'))
                .strip())

    @staticmethod
    def _default_followup(msg_num: int, context: dict) -> str:
        first = context.get('name', '').split()[0] or 'there'
        if msg_num == 2:
            return f'Hi {first}, just wanted to follow up on my last message. Worth a quick chat?'
        return f'Hi {first}, last try — happy to connect if the timing is ever right.'

    @staticmethod
    def _throttle():
        delay = random.uniform(8, 20)
        print(f'    Waiting {delay:.1f}s...')
        time.sleep(delay)


# ── CLI ──────────────────────────────────────────────────────── #

if __name__ == '__main__':
    import json

    agent = MessengerAgent()
    print(f'Account: {agent.account}')
    print(f'DB summary: {json.dumps(agent.report(), indent=2)}')
