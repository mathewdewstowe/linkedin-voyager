"""
Sync LinkedIn messages to the Supabase `global_messaging` table.

Schema (existing):
  id, conversation_urn, participant_name, participant_url,
  sender_name, sender_is_me, message_text, message_date, created_at

Reads credentials from ~/.claude/config/supabase.json (key: service_key).
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', 'requests'])
    import requests


def load_creds():
    p = Path.home() / '.claude' / 'config' / 'supabase.json'
    with open(p) as f:
        c = json.load(f)
    return c['url'], c.get('service_key') or c.get('key')


def existing_message_keys(conversation_urn: str) -> set:
    """Return set of (message_date, sender_name) tuples already in Supabase for a conv."""
    url_root, key = load_creds()
    hdr = {'apikey': key, 'Authorization': f'Bearer {key}'}
    # PostgREST exact-equality on conversation_urn
    r = requests.get(
        f'{url_root}/rest/v1/global_messaging'
        f'?conversation_urn=eq.{conversation_urn}'
        f'&select=message_date,sender_name,message_text',
        headers=hdr,
    )
    if r.status_code != 200:
        return set()
    keys = set()
    for row in r.json():
        # Use (date, sender, text-prefix) as natural key for dedup
        key_tuple = (
            row.get('message_date', '') or '',
            row.get('sender_name', '') or '',
            (row.get('message_text', '') or '')[:50],
        )
        keys.add(key_tuple)
    return keys


def upsert_messages(rows: list) -> dict:
    """
    POST rows into global_messaging with row-level upsert.

    Uses `Prefer: resolution=ignore-duplicates` so existing rows
    (matching the unique constraint on conversation_urn + message_date
    + sender_name) are silently skipped instead of raising 409.

    Each row dict needs: conversation_urn, participant_name, participant_url,
                        sender_name, sender_is_me, message_text, message_date.

    Returns: {'inserted': N, 'skipped': N, 'errors': [...]}
    """
    if not rows:
        return {'inserted': 0, 'skipped': 0, 'errors': []}
    url_root, key = load_creds()
    hdr = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'resolution=ignore-duplicates,return=minimal',
    }
    inserted = skipped = 0
    errors = []
    # POST one at a time so a single conflict doesn't kill the whole batch
    for r in rows:
        resp = requests.post(
            f'{url_root}/rest/v1/global_messaging',
            headers=hdr, json=r,
        )
        if resp.status_code in (200, 201):
            inserted += 1
        elif resp.status_code == 409 or '23505' in resp.text:
            skipped += 1
        else:
            errors.append(f'HTTP {resp.status_code}: {resp.text[:150]}')
    return {'inserted': inserted, 'skipped': skipped, 'errors': errors}


def conversation_count() -> int:
    """How many distinct conversations are in global_messaging?"""
    url_root, key = load_creds()
    hdr = {'apikey': key, 'Authorization': f'Bearer {key}'}
    r = requests.get(
        f'{url_root}/rest/v1/global_messaging?select=conversation_urn',
        headers=hdr,
    )
    return len({row['conversation_urn'] for row in r.json()}) if r.status_code == 200 else 0


def message_count() -> int:
    """Total messages in global_messaging."""
    url_root, key = load_creds()
    hdr = {'apikey': key, 'Authorization': f'Bearer {key}'}
    r = requests.get(
        f'{url_root}/rest/v1/global_messaging?select=*',
        headers={**hdr, 'Prefer': 'count=exact', 'Range': '0-0'},
    )
    return int(r.headers.get('content-range', '0/0').split('/')[-1])
