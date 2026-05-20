"""
PostSearchAgent — Find ICP prospects via LinkedIn people search.

LinkedIn search results are RSC server-rendered (no Voyager API).
This agent uses browser automation to scrape the search results page
and queue matching profiles for connection invites.
"""

import time
import random
from browser import LinkedInBrowser
from store import LinkedVoyagerStore
from config import ICP_QUERIES, ICP_TITLE_KEYWORDS, THROTTLE_READ_MIN, THROTTLE_READ_MAX


class PostSearchAgent:
    def __init__(self, store: LinkedVoyagerStore):
        self.store = store

    def run(self, query_override=None, first_degree_only=False) -> dict:
        """
        Search LinkedIn for people matching ICP queries and queue them.

        Args:
            query_override: Run a single custom query instead of all ICP_QUERIES
            first_degree_only: Restrict to 1st-degree connections

        Returns:
            dict with found_people, queued_authors, queries_run, errors
        """
        queries = [query_override] if query_override else ICP_QUERIES

        results = {
            'found_people': 0,
            'queued_authors': 0,
            'queries_run': 0,
            'errors': []
        }

        with LinkedInBrowser() as browser:
            for query in queries:
                try:
                    print(f'[PostSearchAgent] Searching: {query}')

                    people = browser.search_people(
                        query,
                        first_degree_only=first_degree_only,
                        max_results=20
                    )

                    for person in people:
                        slug = person.get('slug')
                        name = person.get('name')
                        title = person.get('title', '')
                        company = person.get('company', '')

                        if not slug or not name:
                            continue

                        results['found_people'] += 1

                        # Check if title matches ICP keywords
                        title_lower = title.lower() if title else ''
                        matching = [kw for kw in ICP_TITLE_KEYWORDS if kw.lower() in title_lower]

                        if not matching and ICP_TITLE_KEYWORDS:
                            # Skip if title doesn't match any ICP keyword
                            continue

                        # Add to invite queue (store uses author_id = profile slug)
                        self.store.queue_author(
                            author_id=slug,
                            author_name=name,
                            author_urn='',   # We'll resolve URN at connect time
                            from_post_id='',
                            reason=f'People search: {query} | Title: {title}'
                        )
                        results['queued_authors'] += 1
                        print(f'  → Queued {name} | {title}')

                    results['queries_run'] += 1

                    # Delay between searches
                    delay = random.uniform(THROTTLE_READ_MIN, THROTTLE_READ_MAX)
                    time.sleep(delay)

                except Exception as e:
                    results['errors'].append(f'Error in query "{query}": {str(e)}')

        return results
