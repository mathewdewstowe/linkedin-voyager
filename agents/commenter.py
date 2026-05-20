"""
CommenterAgent — NOT IMPLEMENTED

LinkedIn migrated feed commenting to SDUI in 2024-2025.
Direct POST to /voyager/api/feed/normComments returns 400.

To implement commenting, browser automation (Playwright) would be required —
similar to ConnectorAgent / WithdrawerAgent.

This file is kept as a stub so the orchestrator import doesn't break if
commenter is referenced. The `run()` method is a no-op.
"""

from store import LinkedVoyagerStore


class CommenterAgent:
    def __init__(self, store: LinkedVoyagerStore):
        self.store = store

    def run(self, limit=5) -> dict:
        print('[CommenterAgent] Commenting is not implemented (SDUI-only endpoint).')
        return {
            'posted_count': 0,
            'skipped': 0,
            'errors': ['CommenterAgent not implemented — requires browser automation'],
        }
