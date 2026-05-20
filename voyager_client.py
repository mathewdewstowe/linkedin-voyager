from typing import Optional, Union
"""
LinkedIn Voyager API Client — Direct HTTP Endpoints

Working endpoints (confirmed 2026-05-02):
  GET  /voyager/api/me                                                    — auth check
  GET  /voyager/api/graphql?queryId=voyagerIdentityDashProfiles.*         — profile URN lookup
  GET  /voyager/api/relationships/invitationsSummaryV2                    — invite counts
  POST /voyager/api/voyagerMessagingDashMessengerMessages                 — send message
  GET  /voyager/api/voyagerMessagingGraphQL/graphql?queryId=messengerConversations.*  — list convos
  GET  /voyager/api/voyagerMessagingGraphQL/graphql?queryId=messengerMessages.*       — read messages
  GET  /voyager/api/feed/updatesV2                                        — people search (chronFeed)
  GET  /voyager/api/feed/updates/{urn}?updateType=MAIN_FEED               — post likers + comments

DEAD endpoints (do not use):
  /voyager/api/search/blended          — 404, migrated to RSC
  /voyager/api/reactions/v2            — 404, replaced
  /voyager/api/feed/comments           — 400, replaced
  /voyager/api/voyagerMessagingDashMessengerConversations — 400, replaced by GraphQL

NOT working via direct HTTP (SDUI-only):
  - Send invite           → use browser.py / ConnectorAgent
  - Withdraw invite       → use browser.py / WithdrawerAgent
  - Invitation list       → use browser.py scraping
"""

import requests
import time
import random
import json
from urllib.parse import quote

from config import THROTTLE_READ_MIN, THROTTLE_READ_MAX

VOYAGER_BASE = 'https://www.linkedin.com/voyager/api'

# GraphQL query IDs — confirmed working 2026-05-02
GRAPHQL_QUERY_ID_PROFILE   = 'voyagerIdentityDashProfiles.b5c27c04968c409fc0ed3546575b9b7a'
GRAPHQL_QUERY_ID_CONVOS    = 'messengerConversations.0d5e6781bbee71c3e51c8843c6519f48'
GRAPHQL_QUERY_ID_MESSAGES  = 'messengerMessages.5846eeb71c981f11e0134cb6626cc314'


class VoyagerClient:
    def __init__(self, li_at=None, jsessionid=None):
        """
        Args:
            li_at:      LinkedIn auth token (from browser li_at cookie — optional via Python)
            jsessionid: Session ID — also used as CSRF token (required)
        """
        self.li_at = li_at
        self.jsessionid = jsessionid
        self.csrf_token = jsessionid.strip('"') if jsessionid else None
        self.session = requests.Session()
        self._setup_session()
        self._my_urn: Optional[str] = None   # cached fsd_profile URN

    def _setup_session(self):
        self.session.headers.update({
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'application/vnd.linkedin.normalized+json+2.1',
            'Accept-Language': 'en-US,en;q=0.9',
            'X-Restli-Protocol-Version': '2.0.0',
            'X-Li-Lang': 'en_US',
            'X-Li-Track': json.dumps({
                'clientVersion': '1.13.30000',
                'mpVersion': '1.13.30000',
                'osName': 'web',
                'timezoneOffset': 0,
                'timezone': 'Europe/London',
                'deviceFormFactor': 'DESKTOP',
                'mpName': 'voyager-web'
            }),
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Referer': 'https://www.linkedin.com/feed/',
        })
        # IMPORTANT: Never set li_at via Python — LinkedIn will invalidate the session.
        # li_at is HttpOnly and must only be sent automatically by the browser.
        # Only JSESSIONID (= CSRF token) is safe to inject here.
        if self.jsessionid:
            self.session.cookies.set('JSESSIONID', self.jsessionid, domain='.linkedin.com')
        # csrf-token must be sent on ALL requests (GET and POST)
        if self.csrf_token:
            self.session.headers['csrf-token'] = self.csrf_token

    def _throttle(self):
        time.sleep(random.uniform(THROTTLE_READ_MIN, THROTTLE_READ_MAX))

    def _csrf_headers(self, extra=None):
        headers = {'csrf-token': self.csrf_token} if self.csrf_token else {}
        if extra:
            headers.update(extra)
        return headers

    def _check_challenge(self, response) -> bool:
        if response.status_code == 403:
            if '/checkpoint/' in response.url or '/uas/' in response.url:
                return True
        return False

    @staticmethod
    def _mini_to_fsd(urn: str) -> str:
        """Convert urn:li:fs_miniProfile:HASH → urn:li:fsd_profile:HASH."""
        if urn and 'fs_miniProfile:' in urn:
            return urn.replace('fs_miniProfile:', 'fsd_profile:')
        return urn

    # ------------------------------------------------------------------ #
    #  Auth check
    # ------------------------------------------------------------------ #

    def get_me(self) -> Optional[dict]:
        """GET /me — Check auth and return current user's miniProfile.

        Response shape:
          {
            "data": {"*miniProfile": "urn:li:fs_miniProfile:HASH", ...},
            "included": [{"$type": "com.linkedin.voyager.identity.shared.MiniProfile",
                          "entityUrn": "urn:li:fs_miniProfile:HASH",
                          "firstName": "...", "lastName": "...", ...}]
          }
        """
        self._throttle()
        r = self.session.get(f'{VOYAGER_BASE}/me')
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth. Stop all agents.')
        if r.status_code != 200:
            return None
        try:
            data = r.json()
            payload = data.get('data', {})
            # data.data['*miniProfile'] = 'urn:li:fs_miniProfile:HASH'
            mini_urn = payload.get('*miniProfile', '')
            if mini_urn and not self._my_urn:
                self._my_urn = self._mini_to_fsd(mini_urn)
            # Return the full MiniProfile object from included[]
            included = data.get('included', [])
            mini = next(
                (i for i in included if 'MiniProfile' in i.get('$type', '')),
                payload,
            )
            return mini
        except (ValueError, KeyError):
            return None

    def _get_my_urn(self) -> Optional[str]:
        """Return cached fsd_profile URN; resolve via get_me() if needed."""
        if not self._my_urn:
            self.get_me()
        return self._my_urn

    # ------------------------------------------------------------------ #
    #  Profile URN lookup (used by messaging)
    # ------------------------------------------------------------------ #

    def get_profile_urn(self, slug: str) -> Optional[str]:
        """
        Resolve a LinkedIn profile slug to a URN string like
        "urn:li:fsd_profile:ACoAAA...".
        Uses GraphQL endpoint confirmed working 2026-05-02.
        """
        self._throttle()
        url = f'{VOYAGER_BASE}/graphql'
        params = {
            'includeWebMetadata': 'true',
            'variables': f'(memberIdentity:{slug})',
            'queryId': GRAPHQL_QUERY_ID_PROFILE,
        }
        r = self.session.get(url, params=params)
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth. Stop all agents.')
        if r.status_code != 200:
            return None
        try:
            data = r.json()
            included = data.get('included', [])
            if included:
                return included[0].get('entityUrn')
        except (KeyError, ValueError, IndexError):
            pass
        return None

    # ------------------------------------------------------------------ #
    #  Invite counts
    # ------------------------------------------------------------------ #

    def get_invitation_counts(self) -> Optional[dict]:
        """GET /relationships/invitationsSummaryV2 — sent + pending counts."""
        self._throttle()
        url = f'{VOYAGER_BASE}/relationships/invitationsSummaryV2'
        params = {'types': 'List(SENT_INVITATION_COUNT,PENDING_INVITATION_COUNT)'}
        r = self.session.get(url, params=params)
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth. Stop all agents.')
        if r.status_code != 200:
            return None
        try:
            return r.json().get('data', {})
        except (ValueError, KeyError):
            return None

    # ------------------------------------------------------------------ #
    #  Messaging — send
    # ------------------------------------------------------------------ #

    def send_message(self, recipient_urn: str, message_text: str) -> Optional[dict]:
        """
        POST /voyagerMessagingDashMessengerMessages?action=createMessage
        Send a direct message to an existing connection.
        """
        self._throttle()
        url = f'{VOYAGER_BASE}/voyagerMessagingDashMessengerMessages?action=createMessage'
        payload = {
            'message': {
                'body': {'text': message_text},
                'renderContentUnions': []
            },
            'mailboxUrn': recipient_urn,
            'trackingId': self._gen_tracking_id(),
            'dedupeByClientGeneratedToken': False,
            'hostRecipientUrns': [recipient_urn],
        }
        headers = self._csrf_headers({'Content-Type': 'application/json'})
        r = self.session.post(url, json=payload, headers=headers)
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth. Stop all agents.')
        return r.json() if r.status_code in (200, 201) else None

    # ------------------------------------------------------------------ #
    #  Messaging — read conversations
    # ------------------------------------------------------------------ #

    def get_conversations(self, count: int = 20) -> list:
        """
        GET /voyagerMessagingGraphQL/graphql?queryId=messengerConversations.*
        List recent inbox conversations.

        Returns list of dicts:
          conversation_urn, participant_name, participant_url,
          last_message_text, last_message_at, unread_count
        """
        mailbox_urn = self._get_my_urn()
        if not mailbox_urn:
            return []

        self._throttle()
        # Build URL manually — requests.params double-encodes the outer parens,
        # breaking LinkedIn's Restli syntax. Manual build matches the browser exactly:
        # variables=(mailboxUrn:urn%3Ali%3Afsd_profile%3AHASH)
        encoded_urn = quote(mailbox_urn, safe='')
        url = (
            f'{VOYAGER_BASE}/voyagerMessagingGraphQL/graphql'
            f'?queryId={GRAPHQL_QUERY_ID_CONVOS}'
            f'&variables=(mailboxUrn:{encoded_urn})'
        )
        r = self.session.get(url, headers=self._csrf_headers())
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth. Stop all agents.')
        if r.status_code != 200:
            return []

        conversations = []
        try:
            data = r.json()
            included = data.get('included', [])

            # Build participant map: entityUrn → MessagingParticipant
            participant_map = {
                i['entityUrn']: i
                for i in included
                if i.get('$type') == 'com.linkedin.messenger.MessagingParticipant'
                   and i.get('entityUrn')
            }

            # Build message map: entityUrn → Message (for last-message text)
            message_map = {
                i['entityUrn']: i
                for i in included
                if i.get('$type') == 'com.linkedin.messenger.Message'
                   and i.get('entityUrn')
            }

            for conv in included:
                if conv.get('$type') != 'com.linkedin.messenger.Conversation':
                    continue

                conv_urn = conv.get('entityUrn', '')
                title = (conv.get('title') or {}).get('text', '')
                unread = conv.get('unreadCount', 0)
                last_at = conv.get('lastActivityAt', 0)

                # Participant name + URL — skip our own profile, show the other person
                p_name = p_url = ''
                my_participant_urn = (
                    f'urn:li:msg_messagingParticipant:{mailbox_urn}'
                    if mailbox_urn else ''
                )
                for ref in (conv.get('*conversationParticipants') or []):
                    if ref == my_participant_urn:
                        continue   # skip self
                    p = participant_map.get(ref, {})
                    if not p:
                        continue
                    member = (p.get('participantType') or {}).get('member', {})
                    if not member:
                        continue
                    first = (member.get('firstName') or {}).get('text', '')
                    last_name = (member.get('lastName') or {}).get('text', '')
                    raw_url = member.get('profileUrl', '')
                    p_url = raw_url.split('?')[0] if raw_url else ''
                    candidate = f'{first} {last_name}'.strip()
                    if candidate:
                        p_name = candidate
                        break

                # Last message text — inline messages list or message_map lookup
                snippet = ''
                inline_msgs = conv.get('messages', {})
                msg_refs = inline_msgs.get('*elements', []) if isinstance(inline_msgs, dict) else []
                for mref in reversed(msg_refs):
                    m = message_map.get(mref, {})
                    txt = (m.get('body') or {}).get('text', '')
                    if txt:
                        snippet = txt[:200]
                        break

                conversations.append({
                    'conversation_urn': conv_urn,
                    'participant_name': p_name or title,
                    'participant_url': p_url,
                    'last_message_text': snippet,
                    'last_message_at': last_at,
                    'unread_count': unread,
                })
        except (ValueError, KeyError):
            pass
        return conversations

    # ------------------------------------------------------------------ #
    #  Messaging — read messages in a conversation
    # ------------------------------------------------------------------ #

    def get_messages(self, conversation_urn: str, count: int = 20) -> list:
        """
        GET /voyagerMessagingGraphQL/graphql?queryId=messengerMessages.*
        Read messages inside a specific conversation.

        Returns list of dicts:
          message_urn, sender_name, sender_url, text, sent_at
        """
        self._throttle()
        # Build URL manually to match LinkedIn's Restli encoding.
        # conversation_urn is the entityUrn from get_conversations():
        #   urn:li:msg_conversation:(urn:li:fsd_profile:HASH,thread_id)
        encoded_urn = quote(conversation_urn, safe='')
        url = (
            f'{VOYAGER_BASE}/voyagerMessagingGraphQL/graphql'
            f'?queryId={GRAPHQL_QUERY_ID_MESSAGES}'
            f'&variables=(conversationUrn:{encoded_urn})'
        )
        r = self.session.get(url, headers=self._csrf_headers())
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth. Stop all agents.')
        if r.status_code != 200:
            return []

        messages = []
        try:
            data = r.json()
            included = data.get('included', [])

            # Build participant map for sender lookup
            participant_map = {
                i['entityUrn']: i
                for i in included
                if i.get('$type') == 'com.linkedin.messenger.MessagingParticipant'
                   and i.get('entityUrn')
            }

            for item in included:
                if item.get('$type') != 'com.linkedin.messenger.Message':
                    continue

                msg_urn = item.get('entityUrn', '')
                text = (item.get('body') or {}).get('text', '') or ''
                sent_at = item.get('deliveredAt', 0)

                # Resolve sender
                sender_name = sender_url = ''
                sender_ref = item.get('*sender') or item.get('*actor', '')
                if sender_ref:
                    p = participant_map.get(sender_ref, {})
                    if p:
                        member = (p.get('participantType') or {}).get('member', {})
                        first = (member.get('firstName') or {}).get('text', '')
                        last_n = (member.get('lastName') or {}).get('text', '')
                        sender_name = f'{first} {last_n}'.strip()
                        raw_url = member.get('profileUrl', '')
                        sender_url = raw_url.split('?')[0] if raw_url else ''

                messages.append({
                    'message_urn': msg_urn,
                    'sender_name': sender_name,
                    'sender_url': sender_url,
                    'text': text,
                    'sent_at': sent_at,
                })

            # Sort oldest → newest
            messages.sort(key=lambda m: m['sent_at'])
        except (ValueError, KeyError):
            pass
        return messages

    # ------------------------------------------------------------------ #
    #  People search  (feed/updatesV2 — search/blended is dead)
    # ------------------------------------------------------------------ #

    def search_people(self, query: str = '', count: int = 20, start: int = 0,
                      first_degree_only: bool = False, title: Optional[str] = None) -> list:
        """
        Search LinkedIn people.

        NOTE: /search/blended is dead (404) as of 2026-05.
        This method now returns feed profiles matching the keyword via feed/updatesV2.
        For true people search, use the browser automation path (ConnectorAgent).

        Args:
            query:             Free-text keyword
            title:             Strict current-title filter (applied post-fetch)
            first_degree_only: Filter to 1st-degree connections (applied post-fetch)
            count / start:     Pagination

        Returns list of dicts: slug, name, headline, urn, profile_url.
        """
        self._throttle()
        # feed/updatesV2 with chronFeed returns MiniProfile objects for post authors
        params = {
            'q': 'chronFeed',
            'count': min(count * 3, 100),   # over-fetch to compensate for deduplication
            'start': start,
            'updateType': 'CHRONOLOGICAL',
        }
        r = self.session.get(f'{VOYAGER_BASE}/feed/updatesV2', params=params)
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth. Stop all agents.')
        if r.status_code != 200:
            return []

        people = []
        seen = set()
        try:
            data = r.json()
            for item in data.get('included', []):
                if item.get('$type') != 'com.linkedin.voyager.identity.shared.MiniProfile':
                    continue
                slug = item.get('publicIdentifier', '')
                if not slug or slug in seen:
                    continue
                name = f"{item.get('firstName', '')} {item.get('lastName', '')}".strip()
                headline = item.get('headline', '') or item.get('occupation', '')

                # Apply filters
                if query and query.lower() not in (name + ' ' + headline).lower():
                    continue
                if title and title.lower() not in headline.lower():
                    continue

                seen.add(slug)
                people.append({
                    'slug': slug,
                    'name': name,
                    'headline': headline,
                    'urn': item.get('entityUrn', ''),
                    'profile_url': f'https://www.linkedin.com/in/{slug}/',
                })
                if len(people) >= count:
                    break
        except (ValueError, KeyError):
            pass
        return people

    # ------------------------------------------------------------------ #
    #  Post search  (feed/updatesV2 — search/blended is dead)
    # ------------------------------------------------------------------ #

    def search_posts(self, query: str, count: int = 20, start: int = 0) -> list:
        """
        Search LinkedIn posts by keyword.

        NOTE: /search/blended is dead (404) as of 2026-05.
        This method fetches the chronological feed and filters by keyword.

        Returns list of dicts:
          post_urn, post_url, author_slug, author_name, text_snippet.
        """
        self._throttle()
        params = {
            'q': 'chronFeed',
            'count': min(count * 3, 100),
            'start': start,
            'updateType': 'CHRONOLOGICAL',
        }
        r = self.session.get(f'{VOYAGER_BASE}/feed/updatesV2', params=params)
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth. Stop all agents.')
        if r.status_code != 200:
            return []

        posts = []
        try:
            data = r.json()
            included = data.get('included', [])

            # Build profile map
            profiles = {
                i.get('entityUrn', ''): i
                for i in included
                if i.get('$type') == 'com.linkedin.voyager.identity.shared.MiniProfile'
            }

            # Feed update elements
            for update in included:
                if update.get('$type') != 'com.linkedin.voyager.feed.render.UpdateV2':
                    continue
                # Activity URN
                activity_urn = update.get('updateMetadata', {}).get('urn', '') or update.get('entityUrn', '')
                if not activity_urn:
                    continue
                # Text from commentary
                commentary = update.get('commentary', {}) or {}
                text = (commentary.get('text', {}) or {}).get('text', '')
                if not text:
                    # Try nested content
                    content = update.get('content', {}) or {}
                    text = str(content)[:50]

                # Filter by keyword
                if query and query.lower() not in text.lower():
                    continue

                # Author profile
                actor_ref = update.get('*actor', '') or update.get('actor', {}).get('urn', '')
                profile = profiles.get(actor_ref, {})
                # Fallback: first MiniProfile in included
                if not profile and profiles:
                    profile = next(iter(profiles.values()), {})

                slug = profile.get('publicIdentifier', '')
                author_name = f"{profile.get('firstName','')} {profile.get('lastName','')}".strip()

                posts.append({
                    'post_urn': activity_urn,
                    'post_url': f'https://www.linkedin.com/feed/update/{activity_urn}/' if activity_urn else '',
                    'author_slug': slug,
                    'author_name': author_name,
                    'text_snippet': text[:300],
                })
                if len(posts) >= count:
                    break
        except (ValueError, KeyError):
            pass
        return posts

    # ------------------------------------------------------------------ #
    #  Post likers  (via feed/updates — reactions/v2 is dead)
    # ------------------------------------------------------------------ #

    def get_post_likers(self, post_urn: str, count: int = 20, start: int = 0) -> list:
        """
        Who reacted to a post.

        Uses GET /voyager/api/feed/updates/{urn}?updateType=MAIN_FEED
        and extracts com.linkedin.voyager.feed.social.Reaction objects
        from the included array.

        post_urn: 'urn:li:activity:XXXXX'
        Returns list of dicts: slug, name, headline, urn, profile_url, reaction_type.
        """
        self._throttle()
        encoded = quote(post_urn, safe='')
        r = self.session.get(
            f'{VOYAGER_BASE}/feed/updates/{encoded}',
            params={'updateType': 'MAIN_FEED'},
        )
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth. Stop all agents.')
        if r.status_code != 200:
            return []

        likers = []
        try:
            data = r.json()
            for item in data.get('included', []):
                if item.get('$type') != 'com.linkedin.voyager.feed.social.Reaction':
                    continue
                name     = (item.get('name') or {}).get('text', '')
                headline = (item.get('description') or {}).get('text', '')
                nav_url  = (item.get('navigationContext') or {}).get('actionTarget', '')
                profile_url = nav_url.split('?')[0] if nav_url else ''
                slug = profile_url.rstrip('/').split('/')[-1] if profile_url else ''
                likers.append({
                    'slug':          slug,
                    'name':          name,
                    'headline':      headline,
                    'urn':           item.get('actorUrn', ''),
                    'profile_url':   profile_url,
                    'reaction_type': item.get('reactionType', 'LIKE'),
                })
        except (ValueError, KeyError):
            pass
        return likers

    # ------------------------------------------------------------------ #
    #  Post comments  (via feed/updates — feed/comments is dead)
    # ------------------------------------------------------------------ #

    def get_post_comments(self, post_urn: str, count: int = 20, start: int = 0) -> list:
        """
        Comments on a post with full author info.

        Uses GET /voyager/api/feed/updates/{urn}?updateType=MAIN_FEED
        and extracts com.linkedin.voyager.feed.Comment objects.

        If post_urn is an activity URN, the method auto-resolves the underlying
        ugcPost URN (via SocialDetail.threadId) for the second fetch that carries
        the full comments list.

        post_urn: 'urn:li:activity:XXXXX'  or  'urn:li:ugcPost:XXXXX'
        Returns list of dicts:
          author_slug, author_name, author_headline, comment_text, timestamp, profile_url
        """
        self._throttle()
        encoded = quote(post_urn, safe='')
        r = self.session.get(
            f'{VOYAGER_BASE}/feed/updates/{encoded}',
            params={'updateType': 'MAIN_FEED'},
        )
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth. Stop all agents.')
        if r.status_code != 200:
            return []

        data = r.json()
        included = data.get('included', [])

        # If this is an activity URN, find the underlying ugcPost/article URN
        # via SocialDetail.threadId and re-fetch with that URN to get comments.
        sd = next(
            (i for i in included if i.get('$type') == 'com.linkedin.voyager.feed.SocialDetail'),
            None,
        )
        if sd:
            thread_id = sd.get('threadId', '')  # e.g. "ugcPost:7454831959375159298"
            if thread_id and (thread_id.startswith('ugcPost:') or thread_id.startswith('article:')):
                ugc_urn = f'urn:li:{thread_id}'
                if ugc_urn != post_urn:
                    self._throttle()
                    r2 = self.session.get(
                        f'{VOYAGER_BASE}/feed/updates/{quote(ugc_urn, safe="")}',
                        params={'updateType': 'MAIN_FEED'},
                    )
                    if r2.status_code == 200:
                        data = r2.json()
                        included = data.get('included', [])

        # Build MiniProfile map: commenterProfileId hash → profile
        profiles = {}
        for item in included:
            if 'MiniProfile' not in item.get('$type', ''):
                continue
            hash_id = (item.get('entityUrn') or '').split(':')[-1]
            if hash_id:
                profiles[hash_id] = item

        comments = []
        try:
            for item in included:
                if item.get('$type') != 'com.linkedin.voyager.feed.Comment':
                    continue
                # Comment text
                text = (item.get('commentV2') or {}).get('text', '') or item.get('comment', '')
                # Commenter profile lookup
                hash_id = item.get('commenterProfileId', '')
                profile = profiles.get(hash_id, {})
                slug    = profile.get('publicIdentifier', '')
                name    = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip()
                headline = profile.get('occupation', '') or profile.get('headline', '')
                # Profile URL: prefer publicIdentifier; fall back to permalink slug
                if not slug:
                    permalink = item.get('permalink', '')
                    # permalink format: https://www.linkedin.com/feed/update/...?commentUrn=...
                    # Not directly useful for a clean profile URL
                comments.append({
                    'author_slug':     slug,
                    'author_name':     name,
                    'author_headline': headline,
                    'comment_text':    text,
                    'timestamp':       item.get('createdTime', 0),
                    'profile_url':     f'https://www.linkedin.com/in/{slug}/' if slug else '',
                })
                if len(comments) >= count:
                    break
        except (ValueError, KeyError):
            pass
        return comments

    # ------------------------------------------------------------------ #
    #  Job Search
    # ------------------------------------------------------------------ #

    # Common UK geo IDs for location filtering
    GEO_IDS = {
        'united kingdom': '101165590',
        'uk':             '101165590',
        'great britain':  '101165590',
        'london':         '90009496',
        'england':        '102299470',
        'manchester':     '90009621',
        'edinburgh':      '90009555',
        'birmingham':     '90009506',
        'bristol':        '90009512',
    }

    def search_jobs(
        self,
        keywords: str,
        location: str = 'United Kingdom',
        easy_apply_only: bool = True,
        days_posted: int = 14,
        count: int = 25,
        start: int = 0,
    ) -> list:
        """
        Search LinkedIn jobs via voyagerJobsDashJobCards.

        Args:
            keywords:        Search terms e.g. "Head of Product"
            location:        Location string (mapped to geoId). Default: United Kingdom.
            easy_apply_only: If True, only return Easy Apply jobs.
            days_posted:     Recency filter in days (7, 14, 30). Default: 14.
            count:           Max results per page (max 25 per call).
            start:           Pagination offset.

        Returns list of dicts:
            {title, company, location, url, job_id, easy_apply, remote, listed_at, urn}
        """
        # Build location filter
        geo_id = self.GEO_IDS.get(location.lower(), '101165590')
        loc_part = f'locationUnion:(geoId:{geo_id}),'

        # Build selected filters
        filters = []
        if easy_apply_only:
            filters.append('easyApply:List(true)')
        seconds = days_posted * 86400
        filters.append(f'timePostedRange:List(r{seconds})')
        filter_str = ','.join(filters)

        kw_encoded = quote(keywords)
        url = (
            f'https://www.linkedin.com/voyager/api/voyagerJobsDashJobCards'
            f'?decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-220'
            f'&count={count}'
            f'&q=jobSearch'
            f'&query=(origin:JOB_SEARCH_PAGE_OTHER_ENTRY,'
            f'keywords:{kw_encoded},'
            f'{loc_part}'
            f'selectedFilters:({filter_str}),'
            f'spellCorrectionEnabled:true)'
            f'&start={start}'
        )

        self._throttle()
        r = self.session.get(url)
        if self._check_challenge(r):
            raise RuntimeError('CHALLENGE: LinkedIn requires manual auth.')
        if r.status_code != 200:
            print(f'  [job-search] HTTP {r.status_code}')
            return []

        try:
            data = r.json()
        except ValueError:
            return []

        jobs = []
        included = data.get('included', [])

        # Build company lookup from included
        company_map = {}
        for item in included:
            t = item.get('$type', '')
            if 'JobPostingCompany' in t or 'Company' in t:
                urn = item.get('entityUrn', '')
                name = item.get('name', '') or item.get('companyName', '')
                if urn and name:
                    company_map[urn] = name

        for item in included:
            if item.get('$type') != 'com.linkedin.voyager.dash.jobs.JobPosting':
                continue

            # Extract job ID from URN  urn:li:jobPosting:XXXXX
            tracking_urn = item.get('trackingUrn', '')
            job_id = tracking_urn.split(':')[-1] if tracking_urn else ''
            job_url = f'https://www.linkedin.com/jobs/view/{job_id}/' if job_id else ''

            # Company name
            company = ''
            company_details = item.get('companyDetails', {})
            if isinstance(company_details, dict):
                # Try nested company ref
                company_urn = (
                    company_details.get('*company', '')
                    or company_details.get('company', {}).get('entityUrn', '')
                )
                company = company_map.get(company_urn, '')
                if not company:
                    company = (
                        company_details.get('companyName', '')
                        or company_details.get('name', '')
                    )

            # Location
            job_location = ''
            loc_obj = item.get('formattedLocation', '')
            if not loc_obj:
                loc_obj = item.get('location', '')
            job_location = loc_obj if isinstance(loc_obj, str) else ''

            # Remote flag
            remote = bool(item.get('workRemoteAllowed', False))

            # Apply method — easy apply has no offsite URL
            apply_method = item.get('applyMethod', {})
            is_easy = not bool(
                (apply_method or {}).get('companyApplyUrl', '')
                or (apply_method or {}).get('easyApplyUrl', '') == ''
            )
            # If we filtered easyApply:List(true) already, all results are Easy Apply
            if easy_apply_only:
                is_easy = True

            jobs.append({
                'title':      item.get('title', ''),
                'company':    company,
                'location':   job_location,
                'url':        job_url,
                'job_id':     job_id,
                'urn':        tracking_urn,
                'easy_apply': is_easy,
                'remote':     remote,
                'listed_at':  item.get('listedAt', 0),
            })

        return jobs

    def get_job_details(self, job_id: str) -> dict:
        """
        Fetch full job posting details.
        job_id: numeric ID from job URL e.g. 1234567890
        """
        url = (
            f'https://www.linkedin.com/voyager/api/jobs/jobPostings/{job_id}'
            f'?decorationId=com.linkedin.voyager.dash.deco.jobs.web.shared.WebFullJobPosting-65'
        )
        self._throttle()
        r = self.session.get(url)
        if r.status_code != 200:
            return {}
        try:
            data = r.json()
            return data.get('data', data)
        except ValueError:
            return {}

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _gen_tracking_id() -> str:
        """Generate a random 16-byte base64-like tracking token."""
        import base64
        import os
        return base64.b64encode(os.urandom(16)).decode('utf-8')
