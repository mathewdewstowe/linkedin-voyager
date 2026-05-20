"""
LinkedInBrowser — Playwright browser automation for LinkedIn actions.

Two Brave profiles — select via LI_PROFILE env var:
  sonesse  (default) → Brave + ~/.brave-paginator/profile        (matthew@sonesse.ai)
  matthew            → Brave + ~/.brave-paginator/profile-matthew (matthewdewstowe@gmail.com)

To log into a profile for the first time, run:
  LI_PROFILE=matthew python3 main.py login
This launches Brave non-headless so you can sign in to LinkedIn.
"""

import os
import time
import random
from typing import Optional, Union
from urllib.parse import quote
from datetime import datetime


BRAVE_EXE   = '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser'
CHROME_EXE  = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'

_LI_PROFILE = os.environ.get('LI_PROFILE', 'sonesse')

USE_DIRECT_HTTP = False  # both profiles use Playwright now

_PROFILES = {
    'sonesse': {
        'exe':  BRAVE_EXE,
        'dir':  '/Users/matthew_dewstowe/.brave-paginator/profile',
        'account': 'matthew@sonesse.ai',
    },
    'matthew': {
        'exe':  BRAVE_EXE,
        'dir':  '/Users/matthew_dewstowe/.brave-paginator/profile-matthew',
        'account': 'matthewdewstowe@gmail.com',
    },
}
_active     = _PROFILES.get(_LI_PROFILE, _PROFILES['sonesse'])
PROFILE_DIR = _active['dir']
BROWSER_EXE = _active['exe']


def _make_direct_session():
    """Build a requests.Session using live Chrome cookies via browser_cookie3."""
    import requests, browser_cookie3
    cj = browser_cookie3.chrome(domain_name='.linkedin.com')
    cookies = {c.name: c.value for c in cj}
    jsid = cookies.get('JSESSIONID', '').strip('"')
    session = requests.Session()
    session.cookies.update(cookies)
    session.headers.update({
        'csrf-token': jsid,
        'accept': 'application/vnd.linkedin.normalized+json+2.1',
        'x-restli-protocol-version': '2.0.0',
        'x-li-lang': 'en_US',
        'user-agent': (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        ),
    })
    return session


class LinkedInBrowser:
    """Context manager that wraps either a Playwright browser or a direct HTTP session."""

    def __init__(self, headless=True, slow_mo=0):
        self.headless = headless
        self.slow_mo = slow_mo
        self._pw = None
        self._context = None
        self._page = None
        self._session = None   # requests.Session when USE_DIRECT_HTTP

    def __enter__(self):
        if USE_DIRECT_HTTP:
            self._session = _make_direct_session()
            return self
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            executable_path=BROWSER_EXE,
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
        )
        pages = self._context.pages
        # Use the first page; close any extras so we always have exactly one tab
        if pages:
            self._page = pages[0]
            for extra in pages[1:]:
                try:
                    extra.close()
                except Exception:
                    pass
        else:
            self._page = self._context.new_page()
        # Block new pages being opened (popups, target=_blank links, etc.)
        self._context.on('page', lambda p: p.close())
        return self

    def __exit__(self, *args):
        if USE_DIRECT_HTTP:
            self._session = None
            return
        # Close the Playwright context cleanly
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  Invite send
    # ------------------------------------------------------------------ #

    def send_invite(self, profile_slug: str) -> dict:
        """
        Navigate to /in/{slug}/ and click Connect → Send without a note.

        Returns: {'success': bool, 'error': str}
        """
        page = self._page
        print(f'  [Browser] Loading /in/{profile_slug}/')
        page.goto(f'https://www.linkedin.com/in/{profile_slug}/', wait_until='domcontentloaded', timeout=20000)
        page.wait_for_timeout(3000)
        # Scroll to top so y-coordinates are consistent
        page.evaluate('window.scrollTo(0, 0)')
        page.wait_for_timeout(500)

        # Step 1 — get Connect button coords then native-click.
        # JS el.click() doesn't fire React's event listeners; page.mouse.click() does.
        coords = page.evaluate('''() => {
            const spans = Array.from(document.querySelectorAll("span"));
            const s = spans.find(s => {
                const r = s.getBoundingClientRect();
                return s.textContent.trim() === "Connect" && r.y > 380 && r.y < 600 && r.width > 0;
            });
            if (!s) return null;
            let el = s;
            for (let i = 0; i < 6; i++) {
                el = el.parentElement;
                if (!el) break;
                if (el.tagName === "A" || el.tagName === "BUTTON") {
                    const r = el.getBoundingClientRect();
                    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
                }
            }
            return null;
        }''')

        if not coords:
            return {'success': False, 'error': 'Connect button not found on profile page'}

        print(f'  [Browser] Clicking Connect at ({coords["x"]:.0f}, {coords["y"]:.0f})')
        page.mouse.click(coords['x'], coords['y'])

        # Wait for shadow modal — poll up to 5s
        send_coords = None
        for _ in range(10):
            page.wait_for_timeout(500)
            btn_coords = page.evaluate('''() => {
                const interop = document.querySelector("#interop-outlet");
                if (!interop || !interop.shadowRoot) return null;
                const btns = Array.from(interop.shadowRoot.querySelectorAll("button"));
                const sendBtn = btns.find(b => b.textContent.trim() === "Send without a note");
                if (!sendBtn) return null;
                const r = sendBtn.getBoundingClientRect();
                return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
            }''')
            if btn_coords:
                send_coords = btn_coords
                break

        if not send_coords:
            # Capture what's in shadow for debugging
            debug = page.evaluate('''() => {
                const i = document.querySelector("#interop-outlet");
                if (!i || !i.shadowRoot) return "no shadow";
                return Array.from(i.shadowRoot.querySelectorAll("button"))
                    .map(b => b.textContent.trim().substring(0, 30)).join("|");
            }''')
            return {'success': False, 'error': f'Send without a note not found. Shadow: {debug}'}

        page.mouse.click(send_coords['x'], send_coords['y'])
        page.wait_for_timeout(2000)
        print(f'  [Browser] ✓ Invite sent to {profile_slug}')
        return {'success': True}

    # ------------------------------------------------------------------ #
    #  Invite withdrawal
    # ------------------------------------------------------------------ #

    def withdraw_invite(self, profile_slug: str) -> dict:
        """
        Navigate to a profile and withdraw a pending invite by clicking
        the Withdraw button (either on profile page or via invitation manager).

        Returns: {'success': bool, 'error': str}
        """
        page = self._page
        print(f'  [Browser] Withdrawing invite for {profile_slug}')
        page.goto(f'https://www.linkedin.com/in/{profile_slug}/', wait_until='domcontentloaded')
        page.wait_for_load_state('load')
        page.wait_for_timeout(3500)

        # Look for "Pending" button in the profile header (y > 350 filters out nav badges)
        clicked = page.evaluate('''() => {
            const allSpans = Array.from(document.querySelectorAll("span, button, a, [role=button]"));
            const pending = allSpans.find(el => {
                const t = el.textContent.trim();
                const r = el.getBoundingClientRect();
                return (t === "Pending" || t.includes("Withdraw invitation"))
                    && r.width > 0
                    && r.y > 350;
            });
            if (!pending) return false;
            // Walk up to clickable ancestor (A or BUTTON)
            let el = pending;
            let depth = 0;
            while (el && el.tagName !== "BUTTON" && el.tagName !== "A" && !el.getAttribute("role") && depth < 6) {
                el = el.parentElement;
                depth++;
            }
            if (el) { el.click(); return true; }
            pending.click();
            return true;
        }''')

        if not clicked:
            return {'success': False, 'error': 'No pending invite button found on profile page'}

        page.wait_for_timeout(1200)

        # Click Withdraw in shadow root modal or dropdown
        result = page.evaluate('''() => {
            // Check shadow root
            const interop = document.querySelector("#interop-outlet");
            if (interop && interop.shadowRoot) {
                const btns = Array.from(interop.shadowRoot.querySelectorAll("button"));
                const wb = btns.find(b => b.textContent.trim().toLowerCase().includes("withdraw"));
                if (wb) { wb.click(); return "shadow"; }
            }
            // Regular DOM fallback (dropdown items)
            const allBtns = Array.from(document.querySelectorAll("button, [role=menuitem]"));
            const wb = allBtns.find(b => b.textContent.trim().toLowerCase() === "withdraw");
            if (wb) { wb.click(); return "dom"; }
            return null;
        }''')

        if result:
            page.wait_for_timeout(1500)
            print(f'  [Browser] ✓ Invite withdrawn ({result})')
            return {'success': True}
        else:
            return {'success': False, 'error': 'Withdraw button not found in modal'}

    # ------------------------------------------------------------------ #
    #  People search
    # ------------------------------------------------------------------ #

    def search_people(self, query: str, first_degree_only: bool = False, max_results: int = 20) -> list:
        """
        Navigate to LinkedIn people search and return profile list.

        Returns list of dicts: {slug, name, title, company, profile_url}
        """
        page = self._page
        network_param = '&network=%5B%22F%22%5D' if first_degree_only else ''
        url = f'https://www.linkedin.com/search/results/people/?keywords={quote(query)}{network_param}'

        print(f'  [Browser] Searching people: {query}')
        page.goto(url, wait_until='domcontentloaded')
        page.wait_for_timeout(2500)

        people = page.evaluate('''() => {
            // LinkedIn dropped semantic class names in 2025 — use structural approach.
            // Primary result cards are identified by profile links that contain an <img>
            // (the photo link). Mutual-connection links have no img.
            const photoLinks = Array.from(document.querySelectorAll('a[href*="/in/"]'))
                .filter(a => a.querySelector('img'));

            const results = [];
            const seen = new Set();

            for (const link of photoLinks) {
                const slug = (link.href.match(/\\/in\\/([^/?#]+)/) || [])[1];
                if (!slug || seen.has(slug)) continue;
                seen.add(slug);

                // Walk up to a card ancestor: find the div that also has a sibling
                // containing the person's name text (not just the photo)
                let card = link.parentElement;
                for (let i = 0; i < 6; i++) {
                    if (!card) break;
                    if (card.children.length >= 2) break;
                    card = card.parentElement;
                }

                // Extract lines from card innerText (preserves line breaks)
                const raw = card ? (card.innerText || card.textContent) : link.innerText;
                const lines = raw.split("\\n")
                    .map(l => l.trim())
                    .filter(l => l.length > 1
                        && !l.match(/^(Connect|Follow|Message|·|•|1st|2nd|3rd|and \\d+ other)$/)
                        && !l.match(/^\\d+ (mutual|connection)/)
                    );

                // Name is first meaningful line (strip degree indicator)
                const name = lines[0]
                    ? lines[0].replace(/\\s*[•·]\\s*(1st|2nd|3rd).*/, "").trim()
                    : null;
                const title = lines[1] || null;
                const company = lines[2] || null;

                results.push({
                    slug,
                    name,
                    title,
                    company,
                    profile_url: "https://www.linkedin.com/in/" + slug + "/"
                });
            }
            return results.slice(0, 25);
        }''')

        print(f'  [Browser] Found {len(people)} people')
        return people

    # ------------------------------------------------------------------ #
    #  Get sent invitations from invitation manager
    # ------------------------------------------------------------------ #

    def get_sent_invitations(self) -> list:
        """
        Scrape /mynetwork/invitation-manager/sent/ to get pending sent invites.

        Returns list of dicts: {name, slug, profile_url, sent_days_ago}
        """
        page = self._page
        page.goto('https://www.linkedin.com/mynetwork/invitation-manager/sent/', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)

        items = page.evaluate('''() => {
            const listItems = Array.from(document.querySelectorAll("[role=listitem]"));
            return listItems.filter(li => li.textContent.includes("Withdraw")).map(li => {
                const profileLink = li.querySelector('a[href*="/in/"]');
                const href = profileLink ? profileLink.href : "";
                const slug = href.match(/\\/in\\/([^/?#]+)/)?.[1] || null;

                // Name — from the profile link's aria-label or visible text span
                let name = null;
                if (profileLink) {
                    name = profileLink.getAttribute("aria-label");
                    if (!name) {
                        const nameSpan = profileLink.querySelector("span[aria-hidden='true']") || profileLink.querySelector("span");
                        name = nameSpan ? nameSpan.textContent.trim() : null;
                    }
                }
                if (!name) {
                    // Fallback: first bold or heading-like element
                    const h = li.querySelector("span.t-bold, .t-16, .entity-result__title-text span");
                    name = h ? h.textContent.trim() : null;
                }

                // Sent time text
                const bodyText = li.textContent;
                const daysMatch = bodyText.match(/Sent (\\d+) days? ago/);
                const weeksMatch = bodyText.match(/Sent (\\d+) weeks? ago/);
                const monthsMatch = bodyText.match(/Sent (\\d+) months? ago/);
                let sentDaysAgo = 0; // default 0 = sent today
                if (daysMatch) sentDaysAgo = parseInt(daysMatch[1]);
                else if (weeksMatch) sentDaysAgo = parseInt(weeksMatch[1]) * 7;
                else if (monthsMatch) sentDaysAgo = parseInt(monthsMatch[1]) * 30;

                return {
                    name: name,
                    slug: slug,
                    profile_url: href.split("?")[0] || null,
                    sent_days_ago: sentDaysAgo
                };
            }).filter(i => i.slug);
        }''')

        return items

    # ------------------------------------------------------------------ #
    #  Post engagement — search, likers, commenters, comments
    # ------------------------------------------------------------------ #

    def search_posts(self, query: str, max_results: int = 20) -> list:
        """
        Search LinkedIn posts by keyword and return list of post objects.

        Returns list of dicts: {post_url, author_slug, author_name, post_title, timestamp}
        """
        page = self._page
        from urllib.parse import quote
        url = f'https://www.linkedin.com/search/results/content/?keywords={quote(query)}&type=posts'

        print(f'  [Browser] Searching posts: {query}')
        page.goto(url, wait_until='domcontentloaded')
        page.wait_for_timeout(2500)

        posts = page.evaluate('''() => {
            // Post containers are typically role="listitem" or divs with post structure
            // LinkedIn uses structural matching (no semantic classes after 2025)
            const listItems = Array.from(document.querySelectorAll('[role="listitem"], [data-test-id*="post"], .feed-shared-update-v2'));
            const results = [];
            const seen = new Set();

            for (const item of listItems) {
                // Extract author link — posts have author profile links
                const authorLink = item.querySelector('a[href*="/in/"]');
                if (!authorLink) continue;

                const authorHref = authorLink.href;
                const authorSlug = (authorHref.match(/\\/in\\/([^/?#]+)/) || [])[1];
                if (!authorSlug || seen.has(authorSlug)) continue;
                seen.add(authorSlug);

                // Extract post URL — look for main post link or feed link
                let postUrl = null;
                const postLink = item.querySelector('a[href*="/posts/"], a[href*="/feed/"]');
                if (postLink) {
                    postUrl = postLink.href.split('?')[0];
                } else {
                    // Fallback: construct from feed share ID if present
                    postUrl = authorHref.split('?')[0]; // Use author profile as fallback
                }

                // Extract post title (first 50 chars of text content)
                const textContent = item.innerText || item.textContent;
                const lines = textContent.split("\\n").filter(l => l.trim().length > 0);
                // Skip author name and filter UI elements
                const postTitle = lines.slice(1).join(" ").substring(0, 50).trim();

                // Extract timestamp (look for "X days ago", "X hours ago", etc.)
                const timeMatch = textContent.match(/(\\d+)\\s*(hours?|days?|weeks?|months?) ago/i);
                const timestamp = timeMatch ? timeMatch[0] : null;

                // Get author name from aria-label or visible text
                let authorName = authorLink.getAttribute('aria-label') || '';
                if (!authorName) {
                    const nameSpan = authorLink.querySelector('span[aria-hidden="true"]') || authorLink.querySelector('span');
                    authorName = nameSpan ? nameSpan.textContent.trim() : '';
                }

                results.push({
                    post_url: postUrl,
                    author_slug: authorSlug,
                    author_name: authorName,
                    post_title: postTitle || '(no title)',
                    timestamp: timestamp
                });

                if (results.length >= 25) break; // Hard limit to prevent memory issues
            }
            return results.slice(0, 25);
        }''')

        print(f'  [Browser] Found {len(posts)} posts')
        return posts

    def get_post_likers(self, post_url: str) -> list:
        """
        Navigate to a post and extract people who liked it.

        Returns list of dicts: {slug, name, title, company, profile_url}
        """
        page = self._page
        print(f'  [Browser] Getting likers for post')
        page.goto(post_url, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)

        # Find and click "X likes" button
        likes_coords = page.evaluate('''() => {
            const allElements = Array.from(document.querySelectorAll('button, a, span, [role="button"]'));
            const likesEl = allElements.find(el => {
                const text = el.textContent.trim();
                return /^\\d+\\s*likes?$/.test(text);
            });
            if (!likesEl) return null;
            // Walk up to clickable ancestor
            let el = likesEl;
            for (let i = 0; i < 6; i++) {
                if (!el) break;
                if (el.tagName === 'BUTTON' || el.tagName === 'A' || el.getAttribute('role') === 'button') {
                    const r = el.getBoundingClientRect();
                    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
                }
                el = el.parentElement;
            }
            return null;
        }''')

        if not likes_coords:
            print(f'  [Browser] ⚠ No likes button found on post')
            return []

        print(f'  [Browser] Clicking likes at ({likes_coords["x"]:.0f}, {likes_coords["y"]:.0f})')
        page.mouse.click(likes_coords['x'], likes_coords['y'])
        page.wait_for_timeout(1500)

        # Extract likers from modal or inline list
        likers = page.evaluate('''() => {
            // Check shadow root modal first (like send_invite pattern)
            let likerElements = [];
            const interop = document.querySelector("#interop-outlet");
            if (interop && interop.shadowRoot) {
                likerElements = Array.from(interop.shadowRoot.querySelectorAll('[role="listitem"], .artdeco-modal__content [role="listitem"]'));
            }
            // Fallback to inline list in regular DOM
            if (likerElements.length === 0) {
                likerElements = Array.from(document.querySelectorAll('[data-test-id*="like"] [role="listitem"], .modal-content [role="listitem"]'));
            }

            const results = [];
            const seen = new Set();

            for (const item of likerElements) {
                const profileLink = item.querySelector('a[href*="/in/"]');
                if (!profileLink) continue;

                const slug = (profileLink.href.match(/\\/in\\/([^/?#]+)/) || [])[1];
                if (!slug || seen.has(slug)) continue;
                seen.add(slug);

                // Extract name, title, company from text lines
                const textContent = item.innerText || item.textContent;
                const lines = textContent.split("\\n")
                    .map(l => l.trim())
                    .filter(l => l.length > 1);

                const name = lines[0] || null;
                const title = lines[1] || null;
                const company = lines[2] || null;

                results.push({
                    slug: slug,
                    name: name,
                    title: title,
                    company: company,
                    profile_url: profileLink.href.split("?")[0]
                });
            }
            return results;
        }''')

        print(f'  [Browser] ✓ Found {len(likers)} likers')
        return likers

    def get_post_commenters(self, post_url: str) -> list:
        """
        Navigate to a post and extract people who commented on it.

        Returns list of dicts: {slug, name, title, company, profile_url, timestamp}
        """
        page = self._page
        print(f'  [Browser] Getting commenters for post')
        page.goto(post_url, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)
        page.evaluate('window.scrollTo(0, 0)')

        # Scroll down to load comments
        page.wait_for_timeout(500)
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        page.wait_for_timeout(2000)

        commenters = page.evaluate('''() => {
            // Comment containers are role="listitem" under comments section
            const commentItems = Array.from(document.querySelectorAll('.comments-comments-list [role="listitem"], [data-test-id*="comment"] [role="listitem"]'));
            const results = [];
            const seen = new Set();

            for (const item of commentItems) {
                const profileLink = item.querySelector('a[href*="/in/"]');
                if (!profileLink) continue;

                const slug = (profileLink.href.match(/\\/in\\/([^/?#]+)/) || [])[1];
                if (!slug || seen.has(slug)) continue;
                seen.add(slug);

                // Extract name, title, company
                const textContent = item.innerText || item.textContent;
                const lines = textContent.split("\\n")
                    .map(l => l.trim())
                    .filter(l => l.length > 1 && !l.match(/^(Reply|Like|More|·|•)$/));

                const name = lines[0] || null;
                const title = lines[1] || null;
                const company = lines[2] || null;

                // Extract timestamp
                const timeMatch = textContent.match(/(\\d+)\\s*(hours?|days?|weeks?|months?) ago/i);
                const timestamp = timeMatch ? timeMatch[0] : null;

                results.push({
                    slug: slug,
                    name: name,
                    title: title,
                    company: company,
                    profile_url: profileLink.href.split("?")[0],
                    timestamp: timestamp
                });
            }
            return results;
        }''')

        print(f'  [Browser] ✓ Found {len(commenters)} commenters')
        return commenters

    def get_post_comments(self, post_url: str) -> list:
        """
        Navigate to a post and extract comments with text content.

        Returns list of dicts: {author_slug, author_name, comment_text, timestamp, reply_count}
        """
        page = self._page
        print(f'  [Browser] Getting comments for post')
        page.goto(post_url, wait_until='domcontentloaded')
        page.wait_for_timeout(3000)

        # Scroll to load comments
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        page.wait_for_timeout(2000)

        comments = page.evaluate('''() => {
            const commentItems = Array.from(document.querySelectorAll('.comments-comments-list [role="listitem"], [data-test-id*="comment"] [role="listitem"]'));
            const results = [];

            for (const item of commentItems) {
                const profileLink = item.querySelector('a[href*="/in/"]');
                if (!profileLink) continue;

                const authorSlug = (profileLink.href.match(/\\/in\\/([^/?#]+)/) || [])[1];
                if (!authorSlug) continue;

                // Extract author name
                let authorName = profileLink.getAttribute('aria-label') || '';
                if (!authorName) {
                    const nameSpan = profileLink.querySelector('span[aria-hidden="true"]') || profileLink.querySelector('span');
                    authorName = nameSpan ? nameSpan.textContent.trim() : '';
                }

                // Extract comment text (skip profile info and metadata)
                const textContent = item.innerText || item.textContent;
                const lines = textContent.split("\\n").map(l => l.trim());
                // Find the actual comment text (skip author name and metadata)
                let commentText = '';
                let foundStart = false;
                for (const line of lines) {
                    if (foundStart && line.match(/^(Reply|Like|\\d+ replies?)/)) break;
                    if (foundStart) commentText += line + " ";
                    if (!foundStart && line === authorName) foundStart = true;
                }
                commentText = commentText.trim().substring(0, 300); // Limit to 300 chars

                // Extract timestamp
                const timeMatch = textContent.match(/(\\d+)\\s*(hours?|days?|weeks?|months?) ago/i);
                const timestamp = timeMatch ? timeMatch[0] : null;

                // Extract reply count
                const replyMatch = textContent.match(/(\\d+)\\s*replies?/i);
                const replyCount = replyMatch ? parseInt(replyMatch[1]) : 0;

                results.push({
                    author_slug: authorSlug,
                    author_name: authorName,
                    comment_text: commentText || '(empty)',
                    timestamp: timestamp,
                    reply_count: replyCount
                });
            }
            return results;
        }''')

        print(f'  [Browser] ✓ Found {len(comments)} comments')
        return comments

    # ------------------------------------------------------------------ #
    #  Voyager API — all routed through Chrome headless (li_at auto-included)
    # ------------------------------------------------------------------ #
    #
    #  These methods execute JS fetch() inside the Playwright-controlled
    #  Chrome page.  Because the browser already has an active LinkedIn
    #  session, li_at is sent automatically — no need to extract it.
    #
    #  Encoding note: urllib.parse.quote(safe='') encodes ( → %28 and
    #  ) → %29 which LinkedIn's Restli variables parser requires.
    # ------------------------------------------------------------------ #

    def _ensure_linkedin_page(self):
        """Make sure the current page is on linkedin.com so cookies are accessible."""
        if USE_DIRECT_HTTP:
            return  # no browser page needed
        current = self._page.url or ''
        if 'linkedin.com' not in current:
            self._page.goto('https://www.linkedin.com/feed/', wait_until='domcontentloaded', timeout=20000)
            self._page.wait_for_timeout(1500)

    def _voyager_fetch(self, url: str) -> dict:
        """Run a Voyager API GET and return parsed JSON."""
        if USE_DIRECT_HTTP:
            r = self._session.get(url)
            if r.status_code != 200:
                return None
            return r.json()
        self._ensure_linkedin_page()
        result = self._page.evaluate('''async (url) => {
            const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
            const csrf = m ? m[1] : "";
            try {
                const r = await fetch(url, {
                    credentials: "include",
                    headers: {
                        "csrf-token": csrf,
                        "accept": "application/vnd.linkedin.normalized+json+2.1",
                        "x-restli-protocol-version": "2.0.0",
                        "x-li-lang": "en_US"
                    }
                });
                return {status: r.status, body: await r.json()};
            } catch(e) { return {status: 0, error: String(e)}; }
        }''', url)
        if not result or result.get('status') != 200:
            return None
        return result.get('body')

    def _venc(self, urn: str) -> str:
        """Encode a URN for Restli variables — encodes : ( ) , =."""
        return quote(urn, safe='')

    def _voyager_my_urn(self) -> str:
        """Return cached fsd_profile URN, resolving via /me if needed."""
        if not getattr(self, '_my_urn', None):
            self.voyager_get_me()
        return getattr(self, '_my_urn', None)

    # ── Auth ──────────────────────────────────────────────────────────── #

    def voyager_get_me(self) -> dict:
        """
        GET /voyager/api/me via browser.
        Caches fsd_profile URN in self._my_urn.
        Returns MiniProfile dict with firstName, lastName, headline, etc.
        """
        d = self._voyager_fetch('https://www.linkedin.com/voyager/api/me')
        if not d:
            return None
        payload = d.get('data', {})
        mini_urn = payload.get('*miniProfile', '')
        self._my_urn = (
            mini_urn.replace('fs_miniProfile:', 'fsd_profile:')
            if mini_urn else None
        )
        included = d.get('included', [])
        return next(
            (i for i in included if 'MiniProfile' in i.get('$type', '')),
            payload,
        )

    # ── Conversations ─────────────────────────────────────────────────── #

    def voyager_get_all_conversations(self, max_pages: int = 100,
                                      stop_at_timestamp: int = 0,
                                      sleep_ms: int = 250,
                                      category: str = 'INBOX') -> list:
        """
        Walk every page of the inbox via cursor-based pagination.

        Uses the messengerConversations.9501074288a12f3ae9e3c7ea243bccbf
        queryId (the one LinkedIn's own web UI uses for infinite scroll),
        which returns a `metadata.nextCursor` token used to fetch the
        next page.

        Args:
          max_pages: safety cap (100 pages × 20 = 2000 conversations)
          stop_at_timestamp: stop once we hit conversations older than this ms epoch
          sleep_ms: throttle between page requests
          category: INBOX | ARCHIVE | OTHER (matches LinkedIn UI tabs)

        Returns combined list of conversation dicts.
        """
        import time as _time
        all_convos = []
        seen_urns = set()
        cursor = None  # None = first page

        for page in range(max_pages):
            convs, next_cursor = self._voyager_get_conversations_page(
                cursor=cursor, category=category
            )
            if not convs:
                break
            new = [c for c in convs if c['conversation_urn'] not in seen_urns]
            for c in new:
                seen_urns.add(c['conversation_urn'])
                all_convos.append(c)
            if not new:
                break
            # Optional time-based stop
            if stop_at_timestamp:
                oldest = min(c['last_message_at'] for c in new if c['last_message_at']) \
                         if any(c['last_message_at'] for c in new) else 0
                if oldest and oldest <= stop_at_timestamp:
                    break
            # Stop if LinkedIn didn't return a next cursor
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            if sleep_ms:
                _time.sleep(sleep_ms / 1000.0)
        return all_convos

    def _voyager_get_conversations_page(self, cursor: str = None,
                                        category: str = 'INBOX') -> tuple:
        """
        Fetch one page (20 conversations) using the paginated queryId.

        Returns (list_of_conversations, next_cursor) tuple.
        """
        mailbox_urn = self._voyager_my_urn()
        if not mailbox_urn:
            return [], None
        # Pagination queryId (different from the non-paginating one)
        qid = 'messengerConversations.9501074288a12f3ae9e3c7ea243bccbf'
        base_vars = (
            f'(query:(predicateUnions:List((conversationCategoryPredicate:'
            f'(category:{category})))),count:20,mailboxUrn:{self._venc(mailbox_urn)}'
        )
        if cursor:
            base_vars += f',nextCursor:{self._venc(cursor)}'
        base_vars += ')'
        url = (
            'https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql'
            f'?queryId={qid}&variables={base_vars}'
        )
        d = self._voyager_fetch(url)
        if not d:
            return [], None
        # Parse conversations from included[]
        convs = self._parse_conversations(d)
        # Pull next cursor from response metadata
        next_cursor = None
        try:
            next_cursor = (d.get('data', {}).get('data', {})
                           .get('messengerConversationsByCategoryQuery', {})
                           .get('metadata', {}).get('nextCursor'))
        except Exception:
            pass
        return convs, next_cursor

    def _parse_conversations(self, d: dict) -> list:
        """Extract conversation dicts from a messengerConversations response."""
        mailbox_urn = self._voyager_my_urn()
        included = d.get('included', [])
        participant_map = {
            i['entityUrn']: i for i in included
            if i.get('$type') == 'com.linkedin.messenger.MessagingParticipant'
            and i.get('entityUrn')
        }
        message_map = {
            i['entityUrn']: i for i in included
            if i.get('$type') == 'com.linkedin.messenger.Message'
            and i.get('entityUrn')
        }
        my_part_urn = f'urn:li:msg_messagingParticipant:{mailbox_urn}'
        conversations = []
        for conv in included:
            if conv.get('$type') != 'com.linkedin.messenger.Conversation':
                continue
            conv_urn = conv.get('entityUrn', '')
            unread   = conv.get('unreadCount', 0)
            last_at  = conv.get('lastActivityAt', 0)
            title    = (conv.get('title') or {}).get('text', '')
            p_name = p_url = ''
            for ref in (conv.get('*conversationParticipants') or []):
                if ref == my_part_urn:
                    continue
                p = participant_map.get(ref, {})
                member = (p.get('participantType') or {}).get('member', {})
                if not member:
                    continue
                first  = (member.get('firstName') or {}).get('text', '')
                last_n = (member.get('lastName') or {}).get('text', '')
                raw_url = member.get('profileUrl', '')
                p_url = raw_url.split('?')[0] if raw_url else ''
                candidate = f'{first} {last_n}'.strip()
                if candidate:
                    p_name = candidate
                    break
            snippet = ''
            msg_refs = (conv.get('messages') or {}).get('*elements', [])
            for mref in reversed(msg_refs):
                txt = (message_map.get(mref, {}).get('body') or {}).get('text', '')
                if txt:
                    snippet = txt[:200]
                    break
            conversations.append({
                'conversation_urn':   conv_urn,
                'participant_name':   p_name or title,
                'participant_url':    p_url,
                'last_message_text':  snippet,
                'last_message_at':    last_at,
                'unread_count':       unread,
            })
        return conversations

    def voyager_get_conversations(self, count: int = 20) -> list:
        """
        GET messengerConversations via browser.

        Returns list of dicts:
          conversation_urn, participant_name, participant_url,
          last_message_text, last_message_at, unread_count
        """
        mailbox_urn = self._voyager_my_urn()
        if not mailbox_urn:
            return []

        url = (
            'https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql'
            f'?queryId=messengerConversations.0d5e6781bbee71c3e51c8843c6519f48'
            f'&variables=(mailboxUrn:{self._venc(mailbox_urn)})'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []

        included = d.get('included', [])
        participant_map = {
            i['entityUrn']: i
            for i in included
            if i.get('$type') == 'com.linkedin.messenger.MessagingParticipant'
               and i.get('entityUrn')
        }
        message_map = {
            i['entityUrn']: i
            for i in included
            if i.get('$type') == 'com.linkedin.messenger.Message'
               and i.get('entityUrn')
        }
        my_part_urn = f'urn:li:msg_messagingParticipant:{mailbox_urn}'

        conversations = []
        for conv in included:
            if conv.get('$type') != 'com.linkedin.messenger.Conversation':
                continue
            conv_urn = conv.get('entityUrn', '')
            unread   = conv.get('unreadCount', 0)
            last_at  = conv.get('lastActivityAt', 0)
            title    = (conv.get('title') or {}).get('text', '')

            p_name = p_url = ''
            for ref in (conv.get('*conversationParticipants') or []):
                if ref == my_part_urn:
                    continue
                p = participant_map.get(ref, {})
                member = (p.get('participantType') or {}).get('member', {})
                if not member:
                    continue
                first  = (member.get('firstName') or {}).get('text', '')
                last_n = (member.get('lastName') or {}).get('text', '')
                raw_url = member.get('profileUrl', '')
                p_url = raw_url.split('?')[0] if raw_url else ''
                candidate = f'{first} {last_n}'.strip()
                if candidate:
                    p_name = candidate
                    break

            snippet = ''
            msg_refs = (conv.get('messages') or {}).get('*elements', [])
            for mref in reversed(msg_refs):
                txt = (message_map.get(mref, {}).get('body') or {}).get('text', '')
                if txt:
                    snippet = txt[:200]
                    break

            conversations.append({
                'conversation_urn':   conv_urn,
                'participant_name':   p_name or title,
                'participant_url':    p_url,
                'last_message_text':  snippet,
                'last_message_at':    last_at,
                'unread_count':       unread,
            })
        return conversations

    # ── Messages ──────────────────────────────────────────────────────── #

    def voyager_search_conversation_by_name(self, name: str) -> Optional[dict]:
        """
        Search LinkedIn messaging for a conversation by person name.
        Uses the messaging keywords search — completely separate from people search,
        not rate-limited by the search API.

        Returns dict with conversation_urn, last_message_text, last_message_at, participant_name
        or None if no conversation found (never messaged).
        """
        from urllib.parse import quote as _quote
        mailbox_urn = self._voyager_my_urn()
        if not mailbox_urn:
            return None

        url = (
            'https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql'
            f'?queryId=messengerConversations.0d5e6781bbee71c3e51c8843c6519f48'
            f'&variables=(mailboxUrn:{self._venc(mailbox_urn)},keywords:{_quote(name, safe="")})'
        )
        d = self._voyager_fetch(url)
        if not d:
            return None

        included = d.get('included', []) or []
        message_map = {
            i['entityUrn']: i
            for i in included
            if i.get('$type') == 'com.linkedin.messenger.Message' and i.get('entityUrn')
        }
        participant_map = {
            i['entityUrn']: i
            for i in included
            if i.get('$type') == 'com.linkedin.messenger.MessagingParticipant' and i.get('entityUrn')
        }
        my_part_urn = f'urn:li:msg_messagingParticipant:{mailbox_urn}'

        for conv in included:
            if conv.get('$type') != 'com.linkedin.messenger.Conversation':
                continue
            conv_urn = conv.get('entityUrn', '')
            last_at = conv.get('lastActivityAt', 0)

            # Get participant name
            p_name = ''
            for ref in (conv.get('*conversationParticipants') or []):
                if ref == my_part_urn:
                    continue
                p = participant_map.get(ref, {})
                member = (p.get('participantType') or {}).get('member', {})
                if member:
                    first = (member.get('firstName') or {}).get('text', '')
                    last_n = (member.get('lastName') or {}).get('text', '')
                    p_name = f'{first} {last_n}'.strip()
                    break

            # Get last message snippet
            snippet = ''
            for mref in reversed((conv.get('messages') or {}).get('*elements', [])):
                txt = (message_map.get(mref, {}).get('body') or {}).get('text', '')
                if txt:
                    snippet = txt[:300]
                    break

            import datetime as _dt
            last_date = ''
            if last_at:
                try:
                    last_date = _dt.datetime.fromtimestamp(last_at / 1000).strftime('%Y-%m-%d %H:%M')
                except Exception:
                    last_date = str(last_at)

            return {
                'conversation_urn':  conv_urn,
                'participant_name':  p_name,
                'last_message_text': snippet,
                'last_message_at':   last_at,
                'last_message_date': last_date,
            }
        return None

    def voyager_get_conversation_with(self, fsd_urn: str) -> Optional[dict]:
        """
        Find the conversation with a specific person by their fsd_profile URN.
        Paginates through the inbox and matches by participant URN.

        Returns: { conversation_urn, last_message_text, last_message_at }
        or None if no conversation exists.
        """
        import time as _time
        mailbox = self._voyager_my_urn()
        if not mailbox:
            return None

        # fsd_urn appears inside the MessagingParticipant URN
        # e.g. urn:li:msg_messagingParticipant:urn:li:fsd_profile:HASH
        cursor = 0
        for _page in range(20):  # up to 20 pages × 20 convs = 400 conversations
            if cursor:
                variables = f'(mailboxUrn:{self._venc(mailbox)},lastUpdatedBefore:{cursor})'
            else:
                variables = f'(mailboxUrn:{self._venc(mailbox)})'

            url = (
                'https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql'
                f'?queryId=messengerConversations.0d5e6781bbee71c3e51c8843c6519f48'
                f'&variables={variables}'
            )
            d = self._voyager_fetch(url)
            if not d:
                break

            included = d.get('included', [])
            participant_map = {
                i['entityUrn']: i for i in included
                if i.get('$type') == 'com.linkedin.messenger.MessagingParticipant'
            }
            message_map = {
                i['entityUrn']: i for i in included
                if i.get('$type') == 'com.linkedin.messenger.Message'
            }

            conversations = [i for i in included
                             if i.get('$type') == 'com.linkedin.messenger.Conversation']
            if not conversations:
                break

            for conv in conversations:
                for p_ref in (conv.get('*conversationParticipants') or []):
                    # MessagingParticipant URN contains the fsd_profile URN as a substring
                    if fsd_urn in p_ref:
                        conv_urn = conv.get('entityUrn', '')
                        snippet = ''
                        for mref in reversed((conv.get('messages') or {}).get('*elements', [])):
                            txt = (message_map.get(mref, {}).get('body') or {}).get('text', '')
                            if txt:
                                snippet = txt[:300]
                                break
                        return {
                            'conversation_urn':  conv_urn,
                            'last_message_text': snippet,
                            'last_message_at':   conv.get('lastActivityAt', 0),
                        }

            # Advance cursor to oldest conversation's lastActivityAt
            oldest = min((c.get('lastActivityAt', 0) or 0) for c in conversations)
            if not oldest or oldest == cursor:
                break
            cursor = oldest
            _time.sleep(0.2)

        return None

    def voyager_get_messages(self, conversation_urn: str) -> list:
        """
        GET messengerMessages via browser.
        conversation_urn: entityUrn from voyager_get_conversations()
          e.g. 'urn:li:msg_conversation:(urn:li:fsd_profile:HASH,thread_id)'

        Returns list of dicts (oldest → newest):
          message_urn, sender_name, sender_url, text, sent_at
        """
        url = (
            'https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql'
            f'?queryId=messengerMessages.5846eeb71c981f11e0134cb6626cc314'
            f'&variables=(conversationUrn:{self._venc(conversation_urn)})'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []

        included = d.get('included', [])
        participant_map = {
            i['entityUrn']: i
            for i in included
            if i.get('$type') == 'com.linkedin.messenger.MessagingParticipant'
               and i.get('entityUrn')
        }

        messages = []
        for item in included:
            if item.get('$type') != 'com.linkedin.messenger.Message':
                continue
            text    = (item.get('body') or {}).get('text', '') or ''
            sent_at = item.get('deliveredAt', 0)

            sender_name = sender_url = ''
            sender_ref = item.get('*sender') or ''
            if sender_ref:
                p = participant_map.get(sender_ref, {})
                member = (p.get('participantType') or {}).get('member', {})
                first  = (member.get('firstName') or {}).get('text', '')
                last_n = (member.get('lastName') or {}).get('text', '')
                sender_name = f'{first} {last_n}'.strip()
                raw_url = member.get('profileUrl', '')
                sender_url = raw_url.split('?')[0] if raw_url else ''

            messages.append({
                'message_urn': item.get('entityUrn', ''),
                'sender_name': sender_name,
                'sender_url':  sender_url,
                'text':        text,
                'sent_at':     sent_at,
            })

        messages.sort(key=lambda m: m['sent_at'])
        return messages

    # ── Send message ──────────────────────────────────────────────────── #

    def voyager_start_conversation(self, recipient_profile_urn: str, text: str) -> bool:
        """
        Start a new conversation via Voyager API (createMessage with hostRecipientUrns).

        recipient_profile_urn: fsd_profile URN e.g. 'urn:li:fsd_profile:ACoAAA...'
        text: first message body

        Returns True on success, False on failure.
        """
        mailbox_urn = self._voyager_my_urn()
        self._ensure_linkedin_page()
        result = self._page.evaluate('''async ([recipientUrn, bodyText, mailboxUrn]) => {
            const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
            const csrf = m ? m[1] : "";
            const originToken = crypto.randomUUID();
            const trackingId = String.fromCharCode(...crypto.getRandomValues(new Uint8Array(16)));
            const payload = {
                message: {
                    body: { attributes: [], text: bodyText },
                    renderContentUnions: [],
                    originToken: originToken
                },
                mailboxUrn: mailboxUrn,
                hostRecipientUrns: [recipientUrn],
                trackingId: trackingId,
                dedupeByClientGeneratedToken: false
            };
            try {
                const r = await fetch(
                    "https://www.linkedin.com/voyager/api/voyagerMessagingDashMessengerMessages?action=createMessage",
                    {
                        method: "POST",
                        credentials: "include",
                        headers: {
                            "csrf-token": csrf,
                            "content-type": "application/json",
                            "accept": "application/json",
                            "x-restli-protocol-version": "2.0.0",
                            "x-li-lang": "en_US"
                        },
                        body: JSON.stringify(payload)
                    }
                );
                const txt = await r.text();
                return {status: r.status, body: txt.slice(0, 400)};
            } catch(e) { return {status: 0, error: String(e)}; }
        }''', [recipient_profile_urn, text, mailbox_urn])
        if not result:
            return False
        status = result.get('status', 0)
        if status not in (200, 201, 204):
            print(f'  [start_conversation] HTTP {status}: {result.get("body", "")[:200]}')
            return False
        return True

    def voyager_send_message(self, conversation_urn: str, text: str,
                             participant_name: str = '') -> bool:
        """
        Send a message via Voyager API (voyagerMessagingDashMessengerMessages?action=createMessage).

        conversation_urn: entityUrn from voyager_get_conversations()
        text: message body
        participant_name: unused (kept for backward compat)

        Returns True on success, False on failure.
        """
        mailbox_urn = self._voyager_my_urn()
        self._ensure_linkedin_page()
        result = self._page.evaluate('''async ([convUrn, bodyText, mailboxUrn]) => {
            const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
            const csrf = m ? m[1] : "";
            const originToken = crypto.randomUUID();
            // 16-byte binary trackingId — required by LinkedIn
            const trackingId = String.fromCharCode(...crypto.getRandomValues(new Uint8Array(16)));
            const payload = {
                message: {
                    body: { attributes: [], text: bodyText },
                    renderContentUnions: [],
                    conversationUrn: convUrn,
                    originToken: originToken
                },
                mailboxUrn: mailboxUrn,
                trackingId: trackingId,
                dedupeByClientGeneratedToken: false
            };
            try {
                const r = await fetch(
                    "https://www.linkedin.com/voyager/api/voyagerMessagingDashMessengerMessages?action=createMessage",
                    {
                        method: "POST",
                        credentials: "include",
                        headers: {
                            "csrf-token": csrf,
                            "content-type": "application/json",
                            "accept": "application/json",
                            "x-restli-protocol-version": "2.0.0",
                            "x-li-lang": "en_US"
                        },
                        body: JSON.stringify(payload)
                    }
                );
                const txt = await r.text();
                return {status: r.status, body: txt.slice(0, 400)};
            } catch(e) { return {status: 0, error: String(e)}; }
        }''', [conversation_urn, text, mailbox_urn])
        if not result:
            return False
        status = result.get('status', 0)
        if status not in (200, 201, 204):
            print(f'  [send_message] HTTP {status}: {result.get("body", "")[:200]}')
            return False
        return True

    # ── Post engagement via Voyager API (faster than UI scraping) ──────── #

    def voyager_get_post_likers(self, post_urn: str) -> list:
        """
        GET /feed/updates/{urn}?updateType=MAIN_FEED via browser.
        Extracts Reaction objects from included[].

        post_urn: 'urn:li:activity:XXXXX'
        Returns list of dicts: slug, name, headline, profile_url, reaction_type.
        """
        url = (
            f'https://www.linkedin.com/voyager/api/feed/updates/{self._venc(post_urn)}'
            '?updateType=MAIN_FEED'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []

        likers = []
        for item in d.get('included', []):
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
        return likers

    def voyager_get_post_comments(self, post_urn: str) -> list:
        """
        GET /feed/updates/{urn}?updateType=MAIN_FEED via browser.
        Extracts Comment objects; auto-resolves ugcPost URN if needed.

        post_urn: 'urn:li:activity:XXXXX'
        Returns list of dicts:
          author_slug, author_name, author_headline, comment_text, profile_url, timestamp
        """
        url = (
            f'https://www.linkedin.com/voyager/api/feed/updates/{self._venc(post_urn)}'
            '?updateType=MAIN_FEED'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []

        included = d.get('included', [])

        # Auto-resolve activity URN → ugcPost URN for full comment list
        sd = next(
            (i for i in included if i.get('$type') == 'com.linkedin.voyager.feed.SocialDetail'),
            None,
        )
        if sd:
            thread_id = sd.get('threadId', '')
            if thread_id and (thread_id.startswith('ugcPost:') or thread_id.startswith('article:')):
                ugc_urn = f'urn:li:{thread_id}'
                if ugc_urn != post_urn:
                    d2 = self._voyager_fetch(
                        f'https://www.linkedin.com/voyager/api/feed/updates/{self._venc(ugc_urn)}'
                        '?updateType=MAIN_FEED'
                    )
                    if d2:
                        included = d2.get('included', [])

        profiles = {}
        for item in included:
            if 'MiniProfile' not in item.get('$type', ''):
                continue
            hash_id = (item.get('entityUrn') or '').split(':')[-1]
            if hash_id:
                profiles[hash_id] = item

        comments = []
        for item in included:
            if item.get('$type') != 'com.linkedin.voyager.feed.Comment':
                continue
            text     = (item.get('commentV2') or {}).get('text', '') or item.get('comment', '')
            hash_id  = item.get('commenterProfileId', '')
            profile  = profiles.get(hash_id, {})
            slug     = profile.get('publicIdentifier', '')
            name     = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip()
            headline = profile.get('occupation', '') or profile.get('headline', '')
            comments.append({
                'author_slug':     slug,
                'author_name':     name,
                'author_headline': headline,
                'comment_text':    text,
                'timestamp':       item.get('createdTime', 0),
                'profile_url':     f'https://www.linkedin.com/in/{slug}/' if slug else '',
            })
        return comments

    # ── People / post search ──────────────────────────────────────────── #

    # Hardcoded geoUrns for fast/reliable UK + common locations
    GEO_URN_MAP = {
        'united kingdom':   '101165590',
        'uk':               '101165590',
        'great britain':    '101165590',
        'england':          '102299470',
        'scotland':         '100536993',
        'wales':            '101750022',
        'northern ireland': '105572676',
        'london':           '90009496',
        'greater london':   '90009496',
        'london area':      '90009496',
        'manchester':       '102257491',
        'birmingham':       '105712376',
        'bristol':          '105778963',
        'edinburgh':        '105530811',
        'glasgow':          '102299470',
        'leeds':            '101165590',  # fallback to UK if uncertain
        'cardiff':          '101750022',  # Wales
        'liverpool':        '105712376',
        'oxford':           '105778963',
        'cambridge':        '105778963',
        'bath':             '105778963',
        # Common non-UK
        'new york':         '105080838',
        'san francisco':    '102277331',
        'paris':            '104246759',
        'berlin':            '106967730',
        'dublin':            '104738515',
        'united states':    '103644278',
        'usa':              '103644278',
        'us':               '103644278',
        'america':          '103644278',
        # European countries
        'germany':          '101282230',
        'france':           '105015875',
        'netherlands':      '102890719',
        'sweden':           '105117694',
        'switzerland':      '106693272',
        'spain':            '105646813',
        'italy':            '103350119',
        'belgium':          '105703394',
        'norway':           '103819153',
        'denmark':          '104514075',
        'luxembourg':       '104042105',
        'austria':          '103883259',
        'finland':          '100456013',
        'europe':           '91000000',
    }

    # ── Profile (full) ────────────────────────────────────────────────── #

    def voyager_resolve_slug_to_urn(self, slug: str) -> str:
        """
        Resolve a LinkedIn public profile slug to an fsd_profile URN.
        Uses voyagerIdentityDashProfiles (the working endpoint).
        Falls back to people search only if needed.
        Returns 'urn:li:fsd_profile:...' or '' on failure.
        """
        import re as _re

        def _find_fsd_urn(data) -> str:
            if not data:
                return ''
            raw = str(data)
            m = _re.search(r'urn:li:fsd_profile:[A-Za-z0-9_\-]+', raw)
            return m.group(0) if m else ''

        # Strip trailing hex/numeric disambiguation suffix (e.g. mark-scott-bb854025 → mark-scott)
        clean_slug = _re.sub(r'-[0-9a-f]{6,}$', '', slug, flags=_re.IGNORECASE)
        clean_slug = _re.sub(r'-\d{5,}$', '', clean_slug) or slug

        # 1. voyagerIdentityDashProfiles — the reliable endpoint (try clean slug first, then full)
        for s in ([clean_slug, slug] if clean_slug != slug else [slug]):
            url = (f'https://www.linkedin.com/voyager/api/voyagerIdentityDashProfiles'
                   f'?q=memberIdentity&memberIdentity={s}')
            data = self._voyager_fetch(url)
            urn = _find_fsd_urn(data)
            if urn:
                return urn

        # 2. Legacy direct profile API (sometimes works)
        data2 = self._voyager_fetch(
            f'https://www.linkedin.com/voyager/api/identity/profiles/{slug}')
        urn = _find_fsd_urn(data2)
        if urn:
            return urn

        # 3. Search fallback (rate-limited — last resort)
        import re as _re
        name_part = _re.sub(r'-[0-9a-f]{6,}$', '', slug, flags=_re.IGNORECASE)
        name_part = _re.sub(r'-\d{5,}$', '', name_part)
        query = name_part.replace('-', ' ').strip() or slug
        people = self.voyager_search_people(query, count=20, first_degree_only=False)
        match = next((p for p in people if p.get('slug', '').lower() == slug.lower()), None)
        if match:
            m = _re.search(r'(urn:li:fsd_profile:[^,)]+)', match.get('urn', ''))
            return m.group(1) if m else ''
        return ''

    def voyager_get_profile_full(self, slug: str) -> dict:
        """
        Get profile data — uses search + profile activity since legacy
        /profileView endpoint is deprecated. Returns name, headline, location,
        recent posts (as a proxy for activity).
        Note: detailed positions/educations require modern GraphQL profile
        cards which need queryId capture (TODO).
        """
        slug = slug.rstrip('/').split('/')[-1].split('?')[0]
        # Step 1: search to find the profile + URN
        people = self.voyager_search_people(slug.replace('-', ' '), count=10)
        match = next((p for p in people if p.get('slug', '').lower() == slug.lower()),
                     people[0] if people else None)
        if not match:
            return None

        # Step 2: get recent posts for context
        posts = self.voyager_get_profile_posts(match['urn'].split(',')[0].split('(')[-1] if '(' in match['urn'] else slug, count=5)

        return {
            'name':       match['name'],
            'headline':   match['headline'],
            'location':   match.get('location', ''),
            'industry':   '',
            'summary':    '',
            'public_id':  match['slug'],
            'profile_url': match['profile_url'],
            'urn':        match['urn'],
            'positions':  [],
            'educations': [],
            'skills':     [],
            'recent_posts': posts,
        }

    def voyager_get_profile_current_company(self, linkedin_url: str) -> dict:
        """
        Get a person's CURRENT employer via Voyager positionGroups API.

        Calls /voyager/api/identity/profiles/{publicId}/positionGroups which
        returns Position objects (with timePeriod) and MiniCompany objects
        (with universalName = slug).

        Strategy:
          1. Extract publicId from the LinkedIn URL
          2. Fetch positionGroups endpoint (authenticated, in-browser)
          3. Find the Position with no timePeriod.endDate → current role
          4. Match its companyUrn to a MiniCompany in included[] → slug
          5. Also extract industry + employeeCountRange from Position inline data

        Returns dict: {company_slug, company_name, job_title, industry,
                       employee_count, company_id}
        company_slug will be '' if the company has no LinkedIn page.
        """
        import re as _re
        empty = {
            'company_slug': '', 'company_name': '', 'job_title': '',
            'industry': '', 'employee_count': '', 'company_id': ''
        }
        if not linkedin_url or 'linkedin.com' not in linkedin_url:
            return empty

        # Extract public profile ID from URL
        # Handles: /in/some-slug/, /in/some-slug?..., trailing slashes
        m = _re.search(r'linkedin\.com/in/([^/?#]+)', linkedin_url)
        if not m:
            return empty
        public_id = m.group(1).rstrip('/')

        url = f'https://www.linkedin.com/voyager/api/identity/profiles/{public_id}/positionGroups'
        data = self._voyager_fetch(url)
        if not data:
            return {**empty, 'error': 'positionGroups fetch failed'}

        included = data.get('included', [])

        # Build miniCompany lookup: entityUrn → {universalName, name, objectUrn}
        mini_map = {}
        for item in included:
            if item.get('$type') == 'com.linkedin.voyager.entities.shared.MiniCompany':
                urn = item.get('entityUrn', '')
                if urn:
                    mini_map[urn] = {
                        'name':          item.get('name', ''),
                        'universalName': item.get('universalName', ''),
                        'objectUrn':     item.get('objectUrn', ''),
                    }

        # Find current position: Position with no timePeriod.endDate
        positions = [i for i in included
                     if i.get('$type') == 'com.linkedin.voyager.identity.profile.Position']

        # Sort: no-endDate first, then by startDate descending
        def sort_key(p):
            tp = p.get('timePeriod', {})
            has_end = 1 if tp.get('endDate') else 0
            start = tp.get('startDate', {})
            start_year = start.get('year', 0)
            start_month = start.get('month', 0)
            return (has_end, -start_year, -start_month)

        positions.sort(key=sort_key)
        current = positions[0] if positions else None

        if not current:
            return {**empty, 'error': 'no positions found'}

        # Extract company info
        company_urn = current.get('companyUrn', '')  # e.g. "urn:li:fs_miniCompany:33229823"
        mini = mini_map.get(company_urn, {})
        company_slug = mini.get('universalName', '')
        company_name = current.get('companyName', '') or mini.get('name', '')

        # company_id from objectUrn: "urn:li:company:33229823" → "33229823"
        obj_urn = mini.get('objectUrn', '')
        company_id = obj_urn.split(':')[-1] if obj_urn else ''

        # Industry from inline company data
        inline_co = current.get('company') or {}
        industries = inline_co.get('industries', []) if inline_co else []
        industry = industries[0] if industries else ''

        # Employee count range
        ec = inline_co.get('employeeCountRange', {}) if inline_co else {}
        if ec and ec.get('start'):
            employee_count = f"{ec['start']}-{ec.get('end', ec['start'])}"
        else:
            employee_count = ''

        return {
            'company_slug':    company_slug,
            'company_name':    company_name,
            'job_title':       current.get('title', ''),
            'industry':        industry,
            'employee_count':  employee_count,
            'company_id':      company_id,
        }

    def voyager_get_profile_contact(self, slug: str) -> dict:
        """
        Get contact info via /voyager/api/identity/profiles/{slug}/profileContactInfo.
        Returns dict with: email, phones[], websites[], twitter, ims, birthday.
        Only fields the user has chosen to share with you.
        """
        slug = slug.rstrip('/').split('/')[-1].split('?')[0]
        d = self._voyager_fetch(
            f'https://www.linkedin.com/voyager/api/identity/profiles/{quote(slug, safe="")}/profileContactInfo'
        )
        if not d:
            return None
        data = d.get('data') or d
        return {
            'email':     data.get('emailAddress', ''),
            'phones':    [p.get('number', '') for p in (data.get('phoneNumbers') or [])],
            'websites':  [w.get('url', '') for w in (data.get('websites') or [])],
            'twitter':   [t.get('name', '') for t in (data.get('twitterHandles') or [])],
            'ims':       [{'provider': im.get('provider', ''), 'id': im.get('id', '')}
                          for im in (data.get('ims') or [])],
            'birthday':  data.get('birthDateOn', {}),
            'address':   data.get('address', ''),
            'connected_at': data.get('connectedAt', 0),
        }

    def voyager_get_profile_activity(self, slug_or_urn: str, count: int = 20) -> list:
        """
        Get all recent profile activity (posts + likes + comments + reposts).
        Uses identity/profileUpdatesV2 with q=memberFeed (more inclusive than memberShareFeed).
        """
        if slug_or_urn.startswith('urn:li:fsd_profile:'):
            profile_urn = slug_or_urn
        else:
            slug = slug_or_urn.rstrip('/').split('/')[-1].split('?')[0]
            people = self.voyager_search_people(slug.replace('-', ' '), count=10)
            match = next((p for p in people if p.get('slug', '').lower() == slug.lower()),
                         people[0] if people else None)
            if not match:
                return []
            import re as _re
            m = _re.search(r'(urn:li:fsd_profile:[^,)]+)', match.get('urn', ''))
            profile_urn = m.group(1) if m else ''
        if not profile_urn:
            return []

        # memberFeed includes all activity types
        url = (
            'https://www.linkedin.com/voyager/api/identity/profileUpdatesV2'
            f'?profileUrn={quote(profile_urn, safe="")}'
            f'&q=memberFeed&count={count}'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []
        included = d.get('included', [])
        social_counts = {
            it.get('entityUrn', ''): {
                'reactions': it.get('numLikes', 0),
                'comments':  it.get('numComments', 0),
            }
            for it in included
            if it.get('$type') == 'com.linkedin.voyager.feed.shared.SocialActivityCounts'
        }

        activities = []
        for it in included:
            if it.get('$type') != 'com.linkedin.voyager.feed.render.UpdateV2':
                continue
            urn = (it.get('updateMetadata') or {}).get('urn', '')
            commentary = it.get('commentary') or {}
            text = (commentary.get('text') or {}).get('text', '') or ''
            actor = (it.get('actor') or {})
            actor_name = (actor.get('name') or {}).get('text', '')
            social_ref = it.get('*socialDetail', '')
            sc = social_counts.get(social_ref, {})
            if not sc and urn:
                for c_key, c_val in social_counts.items():
                    if urn in c_key:
                        sc = c_val; break
            # Determine activity type
            header = it.get('header') or {}
            header_text = (header.get('text') or {}).get('text', '') if header else ''
            activities.append({
                'type':      'repost' if 'reposted' in header_text.lower() else
                             ('like'  if 'liked'    in header_text.lower() else
                             ('comment' if 'commented' in header_text.lower() else 'post')),
                'header':    header_text,
                'actor':     actor_name,
                'post_urn':  urn,
                'post_url':  f'https://www.linkedin.com/feed/update/{urn}/' if urn else '',
                'text':      text,
                'reactions': sc.get('reactions', 0),
                'comments':  sc.get('comments', 0),
            })
            if len(activities) >= count:
                break
        return activities

    # ── Company ───────────────────────────────────────────────────────── #

    def voyager_get_company(self, slug: str) -> dict:
        """
        Get company info via search (legacy /organization/companies is deprecated).
        Returns dict with: name, tagline, industry, urn, company_id, public_url.
        """
        slug = slug.rstrip('/').split('/')[-1].split('?')[0]
        # Use search to find the company
        keywords = slug.replace('-', ' ').replace('_', ' ')
        variables = (
            f'(query:(keywords:{quote(keywords, safe="")},'
            f'flagshipSearchIntent:SEARCH_SRP,'
            f'queryParameters:List((key:resultType,value:List(COMPANIES))),'
            f'includeFiltersInResponse:false))'
        )
        url = (
            'https://www.linkedin.com/voyager/api/graphql'
            '?queryId=voyagerSearchDashClusters.b0928897b71bd00a5a7291755dcd64f0'
            f'&variables={variables}'
        )
        d = self._voyager_fetch(url)
        if not d:
            return None
        # Collect candidates, prefer exact slug match
        import re as _re
        candidates = []
        for item in d.get('included', []):
            if 'EntityResultViewModel' not in item.get('$type', ''):
                continue
            nav_url = (item.get('navigationContext') or {}).get('url', '') or item.get('navigationUrl', '')
            if '/company/' not in nav_url:
                continue
            company_slug = nav_url.split('/company/')[-1].split('?')[0].rstrip('/')
            candidates.append((item, company_slug, nav_url))
        # Sort: exact match > startswith > contains
        slug_l = slug.lower()
        def rank(c):
            cs = c[1].lower()
            if cs == slug_l: return 0
            if cs.startswith(slug_l): return 1
            if slug_l in cs: return 2
            return 3
        candidates.sort(key=rank)
        for item, company_slug, nav_url in candidates:
            if rank((item, company_slug, nav_url)) <= 2:
                name     = (item.get('title') or {}).get('text', '')
                tagline  = (item.get('primarySubtitle') or {}).get('text', '')
                location = (item.get('secondarySubtitle') or {}).get('text', '')
                summary  = (item.get('summary') or {}).get('text', '') if item.get('summary') else ''
                urn      = item.get('entityUrn', '')
                # Extract numeric company id
                m = _re.search(r'urn:li:fsd_company:(\d+)', urn) or _re.search(r'(\d+)', urn)
                company_id = m.group(1) if m else ''
                # Also check trackingUrn for company id
                track = item.get('trackingUrn', '')
                m2 = _re.search(r'urn:li:company:(\d+)', track)
                if m2:
                    company_id = m2.group(1)
                return {
                    'name':       name,
                    'tagline':    tagline,
                    'industry':   tagline,  # LinkedIn shows industry in primarySubtitle
                    'location':   location,
                    'description':summary,
                    'urn':        urn,
                    'company_id': company_id,
                    'slug':       company_slug,
                    'public_url': f'https://www.linkedin.com/company/{company_slug}/',
                    'employee_count': '',  # not available in search hit
                    'follower_count': '',
                    'website':    '',
                    'hq':         {'country': '', 'city': location, 'line1': ''},
                }
        # Nothing matched
        return None

    def voyager_get_company_size(self, company_slug: str) -> dict:
        """
        Navigate to a company's 'about' page and extract:
          - employee_count_range (e.g. "51-200 employees")
          - employee_count_exact (clickable LinkedIn count if present)
          - industry (text)
          - hq (location)
          - company_type (Public / Private / Self-employed / etc)
          - founded (year if visible)
        Returns dict with these fields.
        """
        page = self._page
        slug = company_slug.rstrip('/').split('/')[-1].split('?')[0]
        url = f'https://www.linkedin.com/company/{slug}/about/'
        try:
            page.goto(url, wait_until='domcontentloaded', timeout=25000)
            page.wait_for_timeout(2500)
        except Exception:
            return {}
        # Extract via JS evaluation
        try:
            data = page.evaluate('''() => {
                const out = { employee_count_range: '', employee_count_exact: '', industry: '', hq: '', company_type: '', founded: '', website: '' };
                // The about page has dt/dd or h3/p pairs. Look for each label.
                const allDt = Array.from(document.querySelectorAll('dt, h3, p, span'));
                for (const el of allDt) {
                    const t = el.textContent.trim().toLowerCase();
                    if (!t || t.length > 30) continue;
                    let next = el.nextElementSibling;
                    if (!next) continue;
                    const nt = next.textContent.trim();
                    if (t === 'company size' && !out.employee_count_range) out.employee_count_range = nt;
                    else if (t === 'industry' && !out.industry) out.industry = nt;
                    else if ((t === 'headquarters' || t === 'location') && !out.hq) out.hq = nt;
                    else if (t === 'type' && !out.company_type) out.company_type = nt;
                    else if (t === 'founded' && !out.founded) out.founded = nt;
                    else if (t === 'website' && !out.website) out.website = nt;
                }
                // Also search for the "X associated members" or "X employees" text
                const memberMatch = document.body.textContent.match(/(\\d[\\d,]*)\\s+(?:associated members|employees on LinkedIn)/i);
                if (memberMatch) out.employee_count_exact = memberMatch[1].replace(/,/g, '');
                return out;
            }''')
            return data or {}
        except Exception:
            return {}

    def voyager_get_company_employees(self, slug: str, title: str = None,
                                      count: int = 20, first_degree_only: bool = False,
                                      location: str = None) -> list:
        """
        Get employees at a company, optionally filtered by job title.
        Uses voyagerSearchDashClusters with currentCompany filter.
        """
        # First resolve company slug → company ID
        company = self.voyager_get_company(slug)
        if not company:
            return []
        company_id = company['company_id']

        kw = title or ''
        filters = f'List((key:resultType,value:List(PEOPLE)),(key:currentCompany,value:List({company_id}))'
        if first_degree_only:
            filters += ',(key:network,value:List(F))'
        if location:
            geo_id = self.voyager_geo_lookup(location)
            if geo_id:
                filters += f',(key:geoUrn,value:List({geo_id}))'
        filters += ')'

        variables = (
            f'(query:(keywords:{quote(kw, safe="")},'
            f'flagshipSearchIntent:SEARCH_SRP,'
            f'queryParameters:{filters},'
            f'includeFiltersInResponse:false))'
        )
        url = (
            'https://www.linkedin.com/voyager/api/graphql'
            '?queryId=voyagerSearchDashClusters.b0928897b71bd00a5a7291755dcd64f0'
            f'&variables={variables}'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []

        people, seen = [], set()
        for item in d.get('included', []):
            if 'EntityResultViewModel' not in item.get('$type', ''):
                continue
            name     = (item.get('title') or {}).get('text', '')
            headline = (item.get('primarySubtitle') or {}).get('text', '')
            loc      = (item.get('secondarySubtitle') or {}).get('text', '')
            nav_url  = (item.get('navigationContext') or {}).get('url', '') or item.get('navigationUrl', '')
            ps       = nav_url.split('/in/')[-1].split('?')[0].strip('/') if '/in/' in nav_url else ''
            urn      = item.get('entityUrn', '')
            if not name or not ps or ps in seen:
                continue
            if title and title.lower() not in headline.lower():
                continue
            seen.add(ps)
            people.append({
                'slug':        ps,
                'name':        name,
                'headline':    headline,
                'location':    loc,
                'urn':         urn,
                'profile_url': f'https://www.linkedin.com/in/{ps}/',
            })
            if len(people) >= count:
                break
        return people

    def voyager_search_company_jobs(self, company_id: str, keywords: str = '', count: int = 50) -> list:
        """
        Get ALL open job postings at a specific company via Voyager API.
        No keyword filter — returns everything, caller filters by sales keywords.
        Uses voyagerJobsDashJobCards endpoint (confirmed working).
        Returns list of job dicts: {title, url, urn}
        """
        # No keyword filter — get all jobs and filter client-side
        kw_part = f'keywords:{keywords},' if keywords.strip() else ''
        url = (
            f'https://www.linkedin.com/voyager/api/voyagerJobsDashJobCards'
            f'?decorationId=com.linkedin.voyager.dash.deco.jobs.search.JobSearchCardsCollection-220'
            f'&count={count}'
            f'&q=jobSearch'
            f'&query=(origin:JOB_SEARCH_PAGE_OTHER_ENTRY,'
            f'{kw_part}'
            f'selectedFilters:(company:List({company_id})),'
            f'spellCorrectionEnabled:true)'
            f'&start=0'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []
        jobs = []
        for item in d.get('included', []):
            if item.get('$type') != 'com.linkedin.voyager.dash.jobs.JobPosting':
                continue
            title = item.get('title', '')
            urn = item.get('trackingUrn', '') or item.get('entityUrn', '')
            job_id = urn.split(':')[-1] if urn else ''
            jurl = f'https://www.linkedin.com/jobs/view/{job_id}/' if job_id else ''
            if title:
                jobs.append({'title': title, 'url': jurl, 'urn': urn})
        return jobs

    # GEO ID map (LinkedIn geoIds for common UK locations)
    _JOB_GEO_IDS = {
        'united kingdom': '101165590',
        'uk':             '101165590',
        'great britain':  '101165590',
        'london':         '90009496',
        'england':        '102299470',
        'manchester':     '90009621',
        'edinburgh':      '90009555',
        'birmingham':     '90009506',
        'bristol':        '90009512',
        'remote':         '101165590',
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
        Search LinkedIn jobs via the public jobs search page (DOM scraping).
        Company names, titles, locations and URLs all reliably present.

        Returns list of dicts: {title, company, location, url, job_id, easy_apply, remote, listed_at, urn}
        """
        from urllib.parse import quote as _q

        # Build search URL — LinkedIn's own search page which includes company names
        kw_enc = _q(keywords, safe='')
        loc_enc = _q(location, safe='')
        filters = f'&location={loc_enc}'
        if easy_apply_only:
            filters += '&f_LF=f_AL'      # Easy Apply filter
        if days_posted:
            filters += f'&f_TPR=r{days_posted * 86400}'  # e.g. r1209600 = 14 days

        search_url = (
            f'https://www.linkedin.com/jobs/search/'
            f'?keywords={kw_enc}{filters}&start={start}'
        )

        page = self._page
        try:
            page.goto(search_url, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(3500)
        except Exception as e:
            print(f'[search_jobs] navigation error: {e}')
            return []

        # Scroll to trigger lazy-load of results
        try:
            page.evaluate('window.scrollBy(0, 600)')
            page.wait_for_timeout(1000)
        except Exception:
            pass

        # Extract job cards from DOM — uses exact selectors from the logged-in LinkedIn jobs search page
        raw_jobs = page.evaluate(r'''(maxCount) => {
            const jobs = [];
            const seen = new Set();
            const cards = document.querySelectorAll('li[data-occludable-job-id], div[data-job-id]');
            for (const card of cards) {
                if (jobs.length >= maxCount) break;

                // Job ID from data attribute (most reliable)
                const job_id = card.getAttribute('data-occludable-job-id') ||
                               card.getAttribute('data-job-id') || '';
                if (!job_id || seen.has(job_id)) continue;
                seen.add(job_id);

                // Title — use aria-label to avoid doubled visually-hidden span text
                const linkEl = card.querySelector('a.job-card-list__title--link, a.job-card-container__link');
                const title = (linkEl && linkEl.getAttribute('aria-label'))
                    ? linkEl.getAttribute('aria-label').trim()
                    : (linkEl ? (linkEl.querySelector('span[aria-hidden="true"]') || linkEl).textContent.trim() : '');

                // URL — strip query params/tracking
                let url = linkEl ? linkEl.href : '';
                if (url) {
                    try { const u = new URL(url); url = u.origin + u.pathname; } catch(e) {}
                }
                if (!url && job_id) url = 'https://www.linkedin.com/jobs/view/' + job_id + '/';

                // Company — subtitle div contains company name span
                const compEl = card.querySelector(
                    'div.artdeco-entity-lockup__subtitle span, ' +
                    '.job-card-container__primary-description, ' +
                    'h4.base-search-card__subtitle'
                );
                const company = compEl ? compEl.textContent.trim() : '';

                // Location — first li in metadata wrapper
                const locEl = card.querySelector(
                    'ul.job-card-container__metadata-wrapper li span, ' +
                    '.job-card-container__metadata-item span, ' +
                    'span.job-search-card__location'
                );
                const location = locEl ? locEl.textContent.trim() : '';

                jobs.push({ title, company, location, url, job_id });
            }
            return jobs;
        }''', count)

        if not raw_jobs:
            print('[search_jobs] DOM extraction returned 0 results — page may not have loaded correctly')

        jobs = []
        for r in raw_jobs:
            job_id = r.get('job_id', '')
            url = r.get('url', '') or (f'https://www.linkedin.com/jobs/view/{job_id}/' if job_id else '')
            jobs.append({
                'title':      r.get('title', ''),
                'company':    r.get('company', ''),
                'location':   r.get('location', ''),
                'url':        url,
                'job_id':     job_id,
                'urn':        f'urn:li:jobPosting:{job_id}' if job_id else '',
                'easy_apply': easy_apply_only,
                'remote':     False,
                'listed_at':  0,
            })

        return jobs

    def voyager_search_company_jobs_page(self, company_slug: str,
                                          search_query: str = 'sales',
                                          company_id: str = '') -> list:
        """
        Search LinkedIn jobs filtered to a specific company using the jobs search URL.
        Uses f_C (company filter) so results are company-specific.
        Returns list of job title strings.
        """
        import re as _re
        page = self._page
        slug = company_slug.rstrip('/').split('/')[-1].split('?')[0]

        # If no company_id passed, try to resolve it
        cid = company_id
        if not cid:
            try:
                comp = self.voyager_get_company(slug)
                if comp:
                    cid = comp.get('company_id', '')
            except Exception:
                pass

        if not cid:
            return []

        from urllib.parse import quote as _q
        kw = _q(search_query, safe='')
        url = f'https://www.linkedin.com/jobs/search/?keywords={kw}&f_C={cid}&position=1&pageNum=0'

        try:
            page.goto(url, wait_until='domcontentloaded', timeout=25000)
            page.wait_for_timeout(4000)
        except Exception:
            return []

        try:
            jobs = page.evaluate('''() => {
                const titles = new Set();
                document.querySelectorAll("a[href*='/jobs/view/']").forEach(el => {
                    // Prefer aria-label (cleanest source)
                    let t = el.getAttribute("aria-label") || "";
                    if (!t) {
                        // Fall back to textContent, de-duplicate doubled text
                        t = el.textContent.trim().replace(/\\s+/g, " ");
                        t = t.replace(/^Job Title\\s+/i, "");
                        // De-duplicate: "Account ExecutiveAccount Executive" -> "Account Executive"
                        const half = Math.ceil(t.length / 2);
                        for (let len = half; len >= 5; len--) {
                            if (t.slice(0, len).trim() === t.slice(len).trim()) {
                                t = t.slice(0, len).trim();
                                break;
                            }
                        }
                    }
                    if (t && t.length > 3 && t.length < 120) titles.add(t.trim());
                });
                return [...titles];
            }''')
            return jobs or []
        except Exception:
            return []

    # ── Feed ──────────────────────────────────────────────────────────── #

    def voyager_get_my_feed(self, count: int = 20) -> list:
        """Get my homepage feed posts. Returns list of dicts with author, text, urn, counts."""
        url = (
            'https://www.linkedin.com/voyager/api/feed/updatesV2'
            f'?q=chronFeed&count={count}'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []
        included = d.get('included', [])
        social_counts = {
            it.get('entityUrn', ''): {
                'reactions': it.get('numLikes', 0),
                'comments':  it.get('numComments', 0),
            }
            for it in included
            if it.get('$type') == 'com.linkedin.voyager.feed.shared.SocialActivityCounts'
        }
        posts = []
        for it in included:
            if it.get('$type') != 'com.linkedin.voyager.feed.render.UpdateV2':
                continue
            urn = (it.get('updateMetadata') or {}).get('urn', '')
            commentary = it.get('commentary') or {}
            text = (commentary.get('text') or {}).get('text', '') or ''
            actor = it.get('actor') or {}
            actor_name = (actor.get('name') or {}).get('text', '')
            actor_sub = (actor.get('subDescription') or actor.get('description') or {}).get('text', '')
            social_ref = it.get('*socialDetail', '')
            sc = social_counts.get(social_ref, {})
            if not sc and urn:
                for c_key, c_val in social_counts.items():
                    if urn in c_key:
                        sc = c_val; break
            posts.append({
                'author':    actor_name,
                'sub':       actor_sub,
                'post_urn':  urn,
                'post_url':  f'https://www.linkedin.com/feed/update/{urn}/' if urn else '',
                'text':      text,
                'reactions': sc.get('reactions', 0),
                'comments':  sc.get('comments', 0),
            })
            if len(posts) >= count:
                break
        return posts

    # ── Find conversation URN for an arbitrary contact ────────────────── #

    def voyager_find_conversation_with(self, profile_slug: str) -> dict:
        """
        Open the contact's profile, click Message, and capture the resulting
        conversation URN — works whether LinkedIn navigates or opens a drawer.

        Returns: {
          'conversation_urn': 'urn:li:msg_conversation:(...)',
          'thread_id':        'base64_thread_id',
          'is_new':           bool,    # True if no existing thread
          'recipient_hash':   'ACoA...'
        }
        """
        import re as _re

        page = self._context.new_page()
        captured = {}

        def _on_request(req):
            url = req.url
            # Capture any messaging conversation load
            if 'voyagerMessagingGraphQL' in url or 'messengerConversations' in url:
                m = _re.search(r'conversationUrn=([^&%]+)', url)
                if m and not captured.get('conv_urn'):
                    captured['conv_urn'] = m.group(1)

        page.on('request', _on_request)

        try:
            page.goto(f'https://www.linkedin.com/in/{profile_slug}/',
                      wait_until='domcontentloaded', timeout=25000)
            page.wait_for_timeout(3000)

            # Click Message via JS (SDUI button)
            clicked = page.evaluate('''() => {
                const btns = Array.from(document.querySelectorAll("button, a"));
                const m = btns.find(b => b.innerText && b.innerText.trim() === "Message");
                if (m) { m.click(); return true; }
                return false;
            }''')
            if not clicked:
                return {'error': 'no Message button on profile'}

            # Wait up to 8s for either a URL nav or drawer to settle
            page.wait_for_timeout(4000)
            url = page.url

            # Case 1: URL navigated to /messaging/thread/XXX
            thread_id = ''
            m = _re.search(r'/messaging/thread/([^/?#]+)', url)
            if m:
                thread_id = m.group(1)

            # Case 2: URL didn't navigate — check for conversation URN in intercepted requests
            if not thread_id and captured.get('conv_urn'):
                raw_urn = captured['conv_urn']
                # Extract thread_id from URN like urn:li:msg_conversation:(urn:li:fsd_profile:HASH,THREAD)
                tm = _re.search(r',([^)]+)\)$', raw_urn)
                if tm:
                    thread_id = tm.group(1)

            # Case 3: Check DOM for a conversation link or data attribute
            if not thread_id:
                thread_id = page.evaluate('''() => {
                    // Check if a messaging panel opened — look for conversation links
                    const links = Array.from(document.querySelectorAll('a[href*="/messaging/thread/"]'));
                    if (links.length) {
                        const m = links[0].href.match(/\\/messaging\\/thread\\/([^/?#]+)/);
                        return m ? m[1] : '';
                    }
                    return '';
                }''') or ''

            # Determine is_new
            is_new = not bool(thread_id) or thread_id == 'new'
            recipient_hash = ''
            conversation_urn = ''

            if is_new:
                rm = _re.search(r'recipient=([^&]+)', url)
                if rm:
                    recipient_hash = rm.group(1)
                # Also try from DOM
                if not recipient_hash:
                    recipient_hash = page.evaluate('''() => {
                        const u = new URL(window.location.href);
                        return u.searchParams.get("recipient") || "";
                    }''') or ''
            else:
                mailbox = self._voyager_my_urn()
                conversation_urn = f'urn:li:msg_conversation:({mailbox},{thread_id})'
                # Override with captured full URN if available
                if captured.get('conv_urn') and 'msg_conversation' in captured['conv_urn']:
                    conversation_urn = captured['conv_urn']

            return {
                'conversation_urn': conversation_urn,
                'thread_id':        thread_id,
                'is_new':           is_new,
                'recipient_hash':   recipient_hash,
                'url':              url,
            }
        finally:
            page.close()

    # ── Messages pagination (for full sync) ──────────────────────────── #

    def voyager_get_messages_paginated(self, conversation_urn: str,
                                       max_pages: int = 100,
                                       stop_at_timestamp: int = 0,
                                       sleep_ms: int = 250) -> list:
        """
        Fetch ALL messages in a conversation by paginating with deliveredAt cursor.

        Args:
          conversation_urn: full URN
          max_pages: safety cap (default 100 pages × 20 msgs = 2000 max)
          stop_at_timestamp: stop once we hit a message older than this ms epoch
                             (use for incremental sync — pass last_synced_at)
          sleep_ms: throttle between page requests

        Returns: list of message dicts (oldest → newest), each with
                 message_urn, sender_name, sender_url, sender_slug, text,
                 sent_at, conversation_urn.
        """
        import time as _time
        all_msgs = []
        seen_urns = set()
        cursor = 0  # deliveredAt cursor (0 = newest first)

        for page in range(max_pages):
            # Build URL with optional deliveredAt cursor
            base = (
                'https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql'
                f'?queryId=messengerMessages.5846eeb71c981f11e0134cb6626cc314'
            )
            if cursor:
                vars_str = f'(conversationUrn:{self._venc(conversation_urn)},deliveredAt:{cursor})'
            else:
                vars_str = f'(conversationUrn:{self._venc(conversation_urn)})'
            url = f'{base}&variables={vars_str}'

            d = self._voyager_fetch(url)
            if not d:
                break

            included = d.get('included', [])
            participants = {
                i['entityUrn']: i for i in included
                if i.get('$type') == 'com.linkedin.messenger.MessagingParticipant'
                and i.get('entityUrn')
            }

            page_msgs = []
            for item in included:
                if item.get('$type') != 'com.linkedin.messenger.Message':
                    continue
                urn = item.get('entityUrn', '')
                if not urn or urn in seen_urns:
                    continue
                seen_urns.add(urn)

                text = (item.get('body') or {}).get('text', '') or ''
                sent_at = item.get('deliveredAt', 0)

                sender_name = sender_slug = sender_url = ''
                sref = item.get('*sender') or ''
                if sref:
                    p = participants.get(sref, {})
                    # Defensive: participantType / member can be None for
                    # system messages, removed users, "LinkedIn Member"
                    # placeholders, etc.
                    mem = ((p.get('participantType') or {}).get('member') or {})
                    first = ((mem.get('firstName') or {}).get('text', '') or '')
                    last_n = ((mem.get('lastName') or {}).get('text', '') or '')
                    sender_name = f'{first} {last_n}'.strip()
                    raw = mem.get('profileUrl', '') or ''
                    sender_url = raw.split('?')[0] if raw else ''
                    sender_slug = sender_url.rstrip('/').split('/')[-1]

                page_msgs.append({
                    'message_urn':      urn,
                    'conversation_urn': conversation_urn,
                    'sender_name':      sender_name,
                    'sender_slug':      sender_slug,
                    'sender_url':       sender_url,
                    'text':             text,
                    'sent_at':          sent_at,
                })

            if not page_msgs:
                break

            page_msgs.sort(key=lambda m: m['sent_at'], reverse=True)
            all_msgs.extend(page_msgs)

            # Stop conditions
            oldest = page_msgs[-1]['sent_at']
            if stop_at_timestamp and oldest <= stop_at_timestamp:
                break
            if len(page_msgs) < 5:  # under typical page size → end of thread
                break

            # Next page: anything older than the oldest we just got
            cursor = oldest
            if sleep_ms:
                _time.sleep(sleep_ms / 1000.0)

        # Final sort oldest → newest
        all_msgs.sort(key=lambda m: m['sent_at'])
        return all_msgs

    # ── Connections ───────────────────────────────────────────────────── #

    def voyager_get_recent_connections(self, count: int = 50,
                                       since_hours=None) -> list:
        """
        List your connections sorted by most-recently-added.
        Equivalent to: LinkedIn → My Network → Connections → Recently added.

        Args:
          count: how many to return (max ~100 per LinkedIn page)
          since_hours: optional — only return connections accepted within
                       the last N hours (client-side filter on createdAt)

        Returns list of dicts: name, headline, slug, profile_url, urn,
                               connected_at (ms epoch), connected_at_iso
        """
        url = (
            'https://www.linkedin.com/voyager/api/relationships/connections'
            f'?count={count}&start=0&sortType=RECENTLY_ADDED'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []

        # Build profile lookup from included
        profiles = {}
        for it in d.get('included', []):
            if 'MiniProfile' in it.get('$type', ''):
                profiles[it.get('entityUrn', '')] = it

        import time as _time
        now_ms = int(_time.time() * 1000)
        cutoff = (now_ms - since_hours * 3600 * 1000) if since_hours else 0

        # Connections are in `included` (not `elements`) as Connection objects.
        # Each references a MiniProfile via *miniProfile.
        from datetime import datetime as _dt
        connections = []
        for it in d.get('included', []):
            if it.get('$type') != 'com.linkedin.voyager.relationships.shared.connection.Connection':
                continue
            created_at = it.get('createdAt', 0)
            if since_hours and created_at < cutoff:
                continue
            mini_urn = it.get('*miniProfile', '')
            profile = profiles.get(mini_urn, {})
            first   = profile.get('firstName', '')
            last_n  = profile.get('lastName', '')
            slug    = profile.get('publicIdentifier', '')
            headline= profile.get('occupation', '') or profile.get('headline', '')
            iso = _dt.utcfromtimestamp(created_at / 1000).strftime('%Y-%m-%d %H:%M UTC') if created_at else ''
            connections.append({
                'name':             f'{first} {last_n}'.strip(),
                'headline':         headline,
                'slug':             slug,
                'profile_url':      f'https://www.linkedin.com/in/{slug}/' if slug else '',
                'urn':              profile.get('entityUrn', ''),
                'connected_at':     created_at,
                'connected_at_iso': iso,
            })
        # Sort newest first (just in case)
        connections.sort(key=lambda c: c['connected_at'], reverse=True)
        return connections

    # ── Invites ───────────────────────────────────────────────────────── #

    def voyager_get_invites_received(self, count: int = 50) -> list:
        """Pending invites received (people asking to connect with me)."""
        url = (
            'https://www.linkedin.com/voyager/api/relationships/invitationViews'
            f'?q=receivedInvitation&start=0&count={count}'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []
        invites = []
        for el in d.get('elements', []):
            inv = (el.get('invitation') or {})
            inviter = el.get('genericInvitationView') or {}
            from_member = (inv.get('fromMember') or inviter.get('inviterMiniProfile') or {})
            invites.append({
                'invitation_urn': inv.get('entityUrn', ''),
                'invitation_id':  inv.get('invitationId', '') or inv.get('entityUrn', '').split(':')[-1],
                'shared_secret':  inv.get('sharedSecret', ''),
                'message':        (inv.get('customMessage') or {}).get('text', ''),
                'from_name':      f"{from_member.get('firstName', '')} {from_member.get('lastName', '')}".strip(),
                'from_headline':  from_member.get('occupation', '') or from_member.get('headline', ''),
                'from_slug':      from_member.get('publicIdentifier', ''),
                'sent_at':        inv.get('sentTime', 0),
            })
        return invites

    def voyager_get_invites_sent(self, count: int = 50) -> list:
        """Pending invites I've sent (still waiting for accept)."""
        url = (
            'https://www.linkedin.com/voyager/api/relationships/invitationViews'
            f'?q=sentInvitation&start=0&count={count}'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []
        invites = []
        for el in d.get('elements', []):
            inv = (el.get('invitation') or {})
            recipient = (inv.get('toMember') or {})
            invites.append({
                'invitation_urn': inv.get('entityUrn', ''),
                'invitation_id':  inv.get('invitationId', '') or inv.get('entityUrn', '').split(':')[-1],
                'shared_secret':  inv.get('sharedSecret', ''),
                'to_name':        f"{recipient.get('firstName', '')} {recipient.get('lastName', '')}".strip(),
                'to_headline':    recipient.get('occupation', '') or recipient.get('headline', ''),
                'to_slug':        recipient.get('publicIdentifier', ''),
                'sent_at':        inv.get('sentTime', 0),
            })
        return invites

    def voyager_invite_action(self, invitation_urn: str, shared_secret: str,
                              action: str = 'accept') -> bool:
        """
        Accept or ignore a received invite.
        action: 'accept' | 'ignore'
        """
        if action not in ('accept', 'ignore'):
            return False
        endpoint = 'closeInvitations' if action == 'ignore' else 'acceptInvite'
        # Use REST endpoint for accept/ignore
        self._ensure_linkedin_page()
        result = self._page.evaluate('''async ([url, payload]) => {
            const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
            const csrf = m ? m[1] : "";
            const r = await fetch(url, {
                method: "POST", credentials: "include",
                headers: {"csrf-token": csrf, "content-type": "application/json",
                          "accept": "application/json", "x-restli-protocol-version": "2.0.0"},
                body: JSON.stringify(payload)
            });
            return {status: r.status, body: (await r.text()).slice(0, 200)};
        }''', [
            f'https://www.linkedin.com/voyager/api/relationships/invitations?action={endpoint}',
            {'invitationId': invitation_urn.split(':')[-1], 'sharedSecret': shared_secret,
             'isGenericInvitation': False}
        ])
        return result and result.get('status') in (200, 201, 204)

    # ── Reactions / comments ──────────────────────────────────────────── #

    def voyager_create_post(self, text: str, visibility: str = 'PUBLIC') -> dict:
        """
        Create a new LinkedIn post.
        visibility: PUBLIC | CONNECTIONS
        Returns: {'urn': '...', 'url': '...'} on success, None on failure.
        """
        my_urn = self._voyager_my_urn()
        # Convert fsd_profile URN to person URN if needed
        person_urn = my_urn.replace('fsd_profile:', 'person:') if my_urn else ''
        self._ensure_linkedin_page()
        result = self._page.evaluate('''async ([text, visibility, ownerUrn]) => {
            const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
            const csrf = m ? m[1] : "";
            const trackingId = String.fromCharCode(...crypto.getRandomValues(new Uint8Array(16)));
            const originToken = crypto.randomUUID();
            const payload = {
                visibleToConnectionsOnly: visibility === "CONNECTIONS",
                allowedCommentersScope: "ALL",
                origin: "FEED",
                commentary: { text: text, attributes: [] },
                contentEntities: [],
                media: null,
                trackingId: trackingId,
                originToken: originToken
            };
            const url = "https://www.linkedin.com/voyager/api/contentcreation/normShares";
            const r = await fetch(url, {
                method: "POST",
                credentials: "include",
                headers: {
                    "csrf-token": csrf,
                    "content-type": "application/json",
                    "accept": "application/json",
                    "x-restli-protocol-version": "2.0.0",
                    "x-li-lang": "en_US"
                },
                body: JSON.stringify(payload)
            });
            const txt = await r.text();
            return {status: r.status, body: txt.slice(0, 500)};
        }''', [text, visibility, person_urn])
        if not result:
            return None
        if result.get('status') not in (200, 201):
            print(f'  [create_post] HTTP {result.get("status")}: {result.get("body","")[:300]}')
            return None
        # Parse activity URN from response
        import json as _json, re as _re
        try:
            body = _json.loads(result.get('body', '{}'))
            urn = body.get('updateUrn', '') or body.get('entityUrn', '') or ''
            if not urn:
                # Fallback: scan response for activity URN
                m = _re.search(r'urn:li:activity:\d+', result.get('body', ''))
                urn = m.group(0) if m else ''
        except Exception:
            urn = ''
        return {
            'urn': urn,
            'url': f'https://www.linkedin.com/feed/update/{urn}/' if urn else '',
        }

    def voyager_react_post(self, post_urn: str, reaction: str = 'LIKE') -> bool:
        """
        React to a post.
        reaction: LIKE | PRAISE | EMPATHY | INTEREST | APPRECIATION | ENTERTAINMENT
        """
        # Resolve activity URN if needed
        if not post_urn.startswith('urn:li:'):
            import re as _re
            m = _re.search(r'urn:li:\w+:\d+', post_urn)
            post_urn = m.group(0) if m else post_urn
        my_urn = self._voyager_my_urn()
        self._ensure_linkedin_page()
        result = self._page.evaluate('''async ([postUrn, reaction, myUrn]) => {
            const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
            const csrf = m ? m[1] : "";
            // Use the dash voyager actions endpoint
            const url = "https://www.linkedin.com/voyager/api/voyagerSocialDashReactions?threadUrn=" + encodeURIComponent(postUrn);
            const payload = {reactionType: reaction};
            const r = await fetch(url, {
                method: "POST", credentials: "include",
                headers: {"csrf-token": csrf, "content-type": "application/json",
                          "accept": "application/json", "x-restli-protocol-version": "2.0.0"},
                body: JSON.stringify(payload)
            });
            return {status: r.status, body: (await r.text()).slice(0, 200)};
        }''', [post_urn, reaction, my_urn])
        if not result:
            return False
        if result.get('status') not in (200, 201, 204):
            print(f'  [react_post] HTTP {result.get("status")}: {result.get("body", "")[:200]}')
            return False
        return True

    def voyager_comment_post(self, post_urn: str, text: str) -> bool:
        """Comment on a post."""
        if not post_urn.startswith('urn:li:'):
            import re as _re
            m = _re.search(r'urn:li:\w+:\d+', post_urn)
            post_urn = m.group(0) if m else post_urn
        my_urn = self._voyager_my_urn()
        self._ensure_linkedin_page()
        result = self._page.evaluate('''async ([postUrn, text, myUrn]) => {
            const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
            const csrf = m ? m[1] : "";
            const url = "https://www.linkedin.com/voyager/api/feed/comments?action=create";
            const payload = {
                actor: myUrn,
                threadUrn: postUrn,
                commentV2: {text: text, attributes: []}
            };
            const r = await fetch(url, {
                method: "POST", credentials: "include",
                headers: {"csrf-token": csrf, "content-type": "application/json",
                          "accept": "application/json", "x-restli-protocol-version": "2.0.0"},
                body: JSON.stringify(payload)
            });
            return {status: r.status, body: (await r.text()).slice(0, 300)};
        }''', [post_urn, text, my_urn])
        if not result:
            return False
        if result.get('status') not in (200, 201, 204):
            print(f'  [comment_post] HTTP {result.get("status")}: {result.get("body", "")[:200]}')
            return False
        return True

    def voyager_get_following(self, count: int = 100, start: int = 0) -> list:
        """
        Fetch people the logged-in user is following via the CurationHub search endpoint.
        Returns list of dicts: {name, slug, profile_url, fsd_urn}.
        Total following count is ~1612 (available in metadata.totalResultCount).
        """
        self._ensure_linkedin_page()
        result = self._page.evaluate('''async ([count, start]) => {
            const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
            const csrf = m ? m[1] : "";
            const vars = `(start:${start},count:${count},origin:CurationHub,query:(flagshipSearchIntent:MYNETWORK_CURATION_HUB,includeFiltersInResponse:true,queryParameters:List((key:resultType,value:List(PEOPLE_FOLLOW)))))`;
            const queryId = "voyagerSearchDashClusters.843215f2a3455f1bed85762a45d71be8";
            const url = `https://www.linkedin.com/voyager/api/graphql?variables=${vars}&queryId=${queryId}&includeWebMetadata=true`;
            const r = await fetch(url, {
                method: "GET", credentials: "include",
                headers: {
                    "csrf-token": csrf,
                    "accept": "application/vnd.linkedin.normalized+json+2.1",
                    "x-restli-protocol-version": "2.0.0"
                }
            });
            const body = await r.text();
            return {status: r.status, body: body.slice(0, 500000)};
        }''', [count, start])
        if not result or result.get('status') not in (200, 201):
            print(f'  [get_following] HTTP {result.get("status") if result else 0}: {(result or {}).get("body","")[:300]}')
            return []
        import json as _json, re as _re
        try:
            data = _json.loads(result['body'])
        except Exception:
            return []
        # Build name/slug map from included[] — entityResultViewModel objects have
        # title (name) and primarySubtitle, and a navigationUrl with slug
        included = data.get('included', [])
        # Map from fsd_entityResultViewModel URN → {name, slug, fsd_urn}
        entity_map = {}
        for obj in included:
            t = obj.get('$type', '')
            urn = obj.get('entityUrn', '')
            if 'entityResultViewModel' in t or 'fsd_entityResultViewModel' in urn:
                # Extract fsd_profile URN from the entityUrn
                m = _re.search(r'urn:li:fsd_profile:([A-Za-z0-9_\-]+)', urn)
                fsd_urn = f'urn:li:fsd_profile:{m.group(1)}' if m else ''
                # Extract slug from navigationUrl
                nav = obj.get('navigationUrl', '') or ''
                slug_m = _re.search(r'/in/([^/?#]+)', nav)
                slug = slug_m.group(1) if slug_m else ''
                name = ''
                title = obj.get('title', {})
                if isinstance(title, dict):
                    name = title.get('text', '')
                entity_map[urn] = {
                    'name': name,
                    'slug': slug,
                    'profile_url': f'https://www.linkedin.com/in/{slug}/' if slug else nav,
                    'fsd_urn': fsd_urn,
                }
        # Walk the cluster items to get ordered list + extract any missing fsd_urns
        following = []
        clusters = (data.get('data', {}).get('data', {})
                       .get('searchDashClustersByAll', {})
                       .get('elements', []))
        for cluster in clusters:
            for item in cluster.get('items', []):
                entity_ref = item.get('item', {}).get('*entityResult', '')
                if not entity_ref:
                    continue
                if entity_ref in entity_map:
                    following.append(entity_map[entity_ref])
                else:
                    # Extract fsd_profile URN directly from the ref string
                    m = _re.search(r'urn:li:fsd_profile:([A-Za-z0-9_\-]+)', entity_ref)
                    if m:
                        fsd_urn = f'urn:li:fsd_profile:{m.group(1)}'
                        following.append({'name': '', 'slug': '', 'profile_url': '', 'fsd_urn': fsd_urn})
        return following

    # ------------------------------------------------------------------
    # React-fiber unfollow helpers
    # LinkedIn routes unfollow through its SPA internals (not plain fetch).
    # The only reliable method is to navigate to the "Following" manager
    # page, find the "Following" button in the DOM, and trigger its React
    # onClick handler directly — which opens the confirm dialog, then we
    # trigger the confirm button's handler too.
    # ------------------------------------------------------------------

    _UNFOLLOW_JS = """
async (nameHint) => {
    // Works with both LinkedIn UI versions:
    //   React (new):  aria-label = "Following, click to unfollow X"   + React fiber
    //   Ember (old):  aria-label = "Click to stop following X"         + plain DOM click

    function getReactOnClick(el) {
        const fk = Object.keys(el).find(k =>
            k.startsWith('__reactFiber') || k.startsWith('__reactInternalInstance'));
        if (!fk) return null;
        let cur = el[fk];
        while (cur) {
            if (cur.memoizedProps && cur.memoizedProps.onClick) return cur.memoizedProps.onClick;
            cur = cur.return;
        }
        return null;
    }

    function clickEl(el) {
        const handler = getReactOnClick(el);
        if (handler) {
            handler(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        } else {
            el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, view: window}));
        }
    }

    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    // Match both "unfollow" (React) and "stop following" (Ember) aria-labels
    function isFollowingBtn(b) {
        if (b.textContent.trim() !== 'Following') return false;
        const a = (b.getAttribute('aria-label') || '').toLowerCase();
        return a.includes('unfollow') || a.includes('stop following');
    }

    const allFollowingBtns = Array.from(document.querySelectorAll('button')).filter(isFollowingBtn);
    let btn = null;
    if (nameHint) {
        btn = allFollowingBtns.find(b => (b.getAttribute('aria-label') || '').toLowerCase().includes(nameHint.toLowerCase()));
    }
    if (!btn) btn = allFollowingBtns[0];
    if (!btn) return {ok: false, error: 'no Following button found', label: ''};

    const label = btn.getAttribute('aria-label') || '';

    // Click the button to trigger unfollow (or open confirm dialog)
    clickEl(btn);
    await sleep(800);

    // Check if a confirm dialog appeared (React UI shows one; Ember UI unfollows directly)
    const confirmBtn = Array.from(document.querySelectorAll('button')).find(b =>
        b.textContent.trim() === 'Unfollow' && b !== btn
    );
    if (confirmBtn) {
        // React UI — click the confirm button
        clickEl(confirmBtn);
        await sleep(800);
    }
    // Ember UI unfollows immediately on first click — no dialog needed

    return {ok: true, label};
}
"""

    def _navigate_to_following_page(self):
        """Navigate to the LinkedIn following manager page and wait for buttons to render."""
        url = 'https://www.linkedin.com/mynetwork/network-manager/people-follow/following/'
        if self._page and self._page.url != url:
            self._page.goto(url, wait_until='domcontentloaded', timeout=30000)
        # Wait for Following buttons — match both React ("unfollow") and Ember ("stop following")
        try:
            self._page.wait_for_function(
                """() => Array.from(document.querySelectorAll('button')).some(b => {
                    if (b.textContent.trim() !== 'Following') return false;
                    const a = (b.getAttribute('aria-label') || '').toLowerCase();
                    return a.includes('unfollow') || a.includes('stop following');
                })""",
                timeout=15000
            )
        except Exception:
            time.sleep(5)  # fallback if wait times out

    def voyager_unfollow_by_urn(self, fsd_urn: str) -> dict:
        """
        Unfollow directly by fsd_profile URN.
        Uses UI automation via React fiber click — navigates to the following
        manager page and triggers the React onClick handler on the matching button.
        Returns {'ok': bool, 'name': str}.
        """
        # We don't use the URN to find the button since we're on the page;
        # delegate to bulk_unfollow with limit=1 and filter by URN if needed.
        # For single unfollow by URN, navigate to following page and unfollow first visible.
        self._ensure_linkedin_page()
        self._navigate_to_following_page()
        result = self._page.evaluate(self._UNFOLLOW_JS, '')
        if not result:
            return {'ok': False, 'name': '', 'error': 'no result from page'}
        name = result.get('label', '').replace('Following, click to unfollow ', '')
        if not result.get('ok'):
            print(f'  [unfollow] {result.get("error")}: {name}')
        return {'ok': result.get('ok', False), 'name': name}

    def voyager_unfollow_person(self, slug_or_url: str) -> dict:
        """
        Unfollow a specific person by LinkedIn slug or URL.
        Navigates to the following manager page and clicks their Following button.
        Returns {'ok': bool, 'name': str}.
        """
        import re as _re
        slug = slug_or_url.rstrip('/').split('/')[-1].split('?')[0]
        self._ensure_linkedin_page()
        self._navigate_to_following_page()
        # Use slug as the nameHint (partial match against aria-label)
        result = self._page.evaluate(self._UNFOLLOW_JS, slug)
        if not result:
            return {'ok': False, 'name': slug, 'error': 'no result from page'}
        name = result.get('label', '').replace('Following, click to unfollow ', '')
        if not result.get('ok'):
            print(f'  [unfollow] {result.get("error")}: {name}')
        return {'ok': result.get('ok', False), 'name': name}

    def ui_bulk_unfollow(self, limit: int = 10, delay: float = 2.0, dry_run: bool = False) -> dict:
        """
        Unfollow up to `limit` people from the following manager page.
        Uses React fiber click — works with LinkedIn's modern SPA architecture.
        Scrolls down to load more as needed.
        Returns {'unfollowed': int, 'names': list}.
        """
        self._ensure_linkedin_page()
        self._navigate_to_following_page()

        unfollowed = []
        attempts = 0
        max_scroll_attempts = 20

        def count_visible_buttons():
            return self._page.evaluate("""() => {
                return Array.from(document.querySelectorAll('button')).filter(b => {
                    if (b.textContent.trim() !== 'Following') return false;
                    const a = (b.getAttribute('aria-label') || '').toLowerCase();
                    return a.includes('unfollow') || a.includes('stop following');
                }).length;
            }""")

        def get_visible_names():
            return self._page.evaluate("""() => {
                return Array.from(document.querySelectorAll('button')).filter(b => {
                    if (b.textContent.trim() !== 'Following') return false;
                    const a = (b.getAttribute('aria-label') || '').toLowerCase();
                    return a.includes('unfollow') || a.includes('stop following');
                }).map(b => {
                    const a = b.getAttribute('aria-label') || '';
                    return a.replace('Following, click to unfollow ', '')
                             .replace('Click to stop following ', '');
                });
            }""")

        def extract_name(label):
            return (label
                    .replace('Following, click to unfollow ', '')
                    .replace('Click to stop following ', ''))

        while len(unfollowed) < limit and attempts < max_scroll_attempts:
            btn_count = count_visible_buttons()

            if btn_count == 0:
                self._page.evaluate("window.scrollBy(0, 600)")
                time.sleep(2.5)
                attempts += 1
                continue

            if dry_run:
                names = get_visible_names()
                for n in names[:limit - len(unfollowed)]:
                    unfollowed.append(n)
                    print(f'  [dry-run] Would unfollow: {n}')
                break

            # Unfollow the next person
            result = self._page.evaluate(self._UNFOLLOW_JS, '')
            if result and result.get('ok'):
                name = extract_name(result.get('label', ''))
                unfollowed.append(name)
                print(f'  [{len(unfollowed)}/{limit}] Unfollowed: {name}')
                attempts = 0
                time.sleep(delay)
            else:
                err = (result or {}).get('error', 'unknown error')
                print(f'  [warn] {err} — scrolling for more')
                self._page.evaluate("window.scrollBy(0, 600)")
                time.sleep(2.5)
                attempts += 1

        return {'unfollowed': len(unfollowed), 'names': unfollowed}

    def voyager_geo_lookup(self, location: str) -> str:
        """Resolve a location string to a LinkedIn geoUrn id.
        Uses hardcoded map first, then typeahead as fallback."""
        key = location.lower().strip()
        if key in self.GEO_URN_MAP:
            return self.GEO_URN_MAP[key]
        # Typeahead fallback (queryId may rotate — best-effort)
        url = (
            'https://www.linkedin.com/voyager/api/graphql'
            '?queryId=voyagerSearchDashReusableTypeahead.b8f1adee2f8def6d50d4d54b2b8b4a76'
            f'&variables=(query:(typeaheadFilterQuery:(geoSearchTypes:List(MARKET_AREA,COUNTRY_REGION,ADMIN_DIVISION_1,CITY)),'
            f'typeaheadUseCase:GEO,keywords:{quote(location, safe="")}))'
        )
        d = self._voyager_fetch(url)
        if not d:
            return None
        import json as _json, re as _re
        m = _re.search(r'urn:li:geo:(\d+)', _json.dumps(d))
        return m.group(1) if m else None

    # LinkedIn industry URN map — add more as needed
    INDUSTRY_URN_MAP = {
        # Core tech
        'software development': '4',
        'computer software': '4',
        'it services and it consulting': '96',
        'information technology and services': '96',
        'it services': '96',
        'internet': '6',
        'internet publishing': '6',
        'technology, information and internet': '6',
        'computer & network security': '118',
        'computer network security': '118',
        'cybersecurity': '118',
        'computer hardware': '3',
        'computer networking products': '5',
        'computer networking': '5',
        'telecommunications': '8',
        'wireless': '7',
        'data infrastructure and analytics': '3247',
        'information services': '84',
        'mobile computing software products': '1810',
        # Vertical SaaS plays
        'financial services': '43',
        'fintech': '1742',
        'insurance': '42',
        'banking': '41',
        'investment banking': '45',
        'investment management': '50',
        'real estate': '44',
        'marketing and advertising': '80',
        'marketing services': '80',
        'advertising services': '80',
        'legal services': '10',
        'e-learning': '132',
        'e-learning providers': '132',
        'higher education': '68',
        'hospital & health care': '14',
        'hospitals and health care': '14',
        'pharmaceuticals': '15',
        'biotechnology': '16',
        'biotechnology research': '16',
        'staffing and recruiting': '104',
        'human resources services': '137',
        'management consulting': '11',
        'business consulting and services': '11',
        'media production': '126',
        'broadcast media': '36',
        'publishing': '82',
        'newspaper publishing': '81',
        'professional training and coaching': '105',
        'venture capital and private equity principals': '106',
    }

    def voyager_industry_lookup(self, industry: str) -> str:
        """Resolve an industry string to a LinkedIn industry URN id.
        Uses hardcoded map first, then typeahead as fallback."""
        key = industry.lower().strip()
        if key in self.INDUSTRY_URN_MAP:
            return self.INDUSTRY_URN_MAP[key]
        # Typeahead fallback
        url = (
            'https://www.linkedin.com/voyager/api/graphql'
            '?queryId=voyagerSearchDashReusableTypeahead.b8f1adee2f8def6d50d4d54b2b8b4a76'
            f'&variables=(query:(typeaheadUseCase:INDUSTRY,keywords:{quote(industry, safe="")}))'
        )
        d = self._voyager_fetch(url)
        if not d:
            return None
        import json as _json, re as _re
        m = _re.search(r'urn:li:industry:(\d+)', _json.dumps(d))
        return m.group(1) if m else None

    def voyager_search_people(self, query: str = '', title: str = None,
                              first_degree_only: bool = False, count: int = 500,
                              location: str = None,
                              title_strict: bool = False,
                              titles_any: list = None,
                              industry: str = None,
                              industries_any: list = None,
                              page_size: int = 49,
                              delay_between_pages: float = 8.0) -> list:
        """
        Search people via Voyager GraphQL search — paginated, server-side title filter.

        Args:
          query: keywords for full-text search
          title: job title — uses server-side (key:title,...) filter for accuracy
          titles_any: list of titles — each searched separately and merged (OR logic)
          first_degree_only: filter to 1st-degree connections
          location: optional location name, resolved to geoUrn server-side
          title_strict: legacy param — server-side filter is accurate by default now
          count: max total results to return (default 500)
          page_size: LinkedIn page size, default 49 (do not lower — causes cutoff)
          delay_between_pages: seconds to sleep between pages (default 8.0)

        Returns list of dicts: slug, name, headline, location, profile_url, urn.
        """
        # If titles_any has multiple titles, recurse once per title and merge
        if titles_any and len(titles_any) > 1:
            all_people, seen_slugs = [], set()
            for t in titles_any:
                results = self.voyager_search_people(
                    query=query, title=t, first_degree_only=first_degree_only,
                    count=count, location=location, title_strict=True,
                    titles_any=None, industry=industry, industries_any=industries_any,
                    page_size=page_size,
                    delay_between_pages=delay_between_pages,
                )
                for p in results:
                    if p['slug'] not in seen_slugs:
                        seen_slugs.add(p['slug'])
                        all_people.append(p)
            return all_people

        # If industries_any has multiple, recurse once per industry and merge
        if industries_any and len(industries_any) > 1:
            all_people, seen_slugs = [], set()
            for ind in industries_any:
                results = self.voyager_search_people(
                    query=query, title=title, first_degree_only=first_degree_only,
                    count=count, location=location, title_strict=title_strict,
                    titles_any=None, industry=ind, industries_any=None,
                    page_size=page_size,
                    delay_between_pages=delay_between_pages,
                )
                for p in results:
                    if p['slug'] not in seen_slugs:
                        seen_slugs.add(p['slug'])
                        p['industry_matched'] = ind
                        all_people.append(p)
            return all_people

        # Keyword for the free-text field
        effective_title = (titles_any[0] if titles_any else title) or ''
        kw = query or effective_title

        # Resolve location → geoUrn for server-side filtering
        HARDCODED_URNS = {
            'uk': '101165590', 'united kingdom': '101165590',
            'england': '102299470', 'scotland': '104049318',
            'wales': '100268168', 'northern ireland': '104233521',
            'london': '90009496', 'manchester': '103940630',
            'birmingham': '102445284', 'bristol': '105154330',
            'edinburgh': '104075587', 'cardiff': '104989790',
            # European countries
            'germany': '101282230', 'france': '105015875',
            'netherlands': '102890719', 'sweden': '105117694',
            'switzerland': '106693272', 'spain': '105646813',
            'italy': '103350119', 'belgium': '105703394',
            'norway': '103819153', 'denmark': '104514075',
            'luxembourg': '104042105', 'austria': '103883259',
            'finland': '100456013', 'europe': '91000000',
            'paris': '104246759', 'berlin': '106967730',
            'amsterdam': '102890719', 'zurich': '106693272',
        }
        geo_id = None
        if location:
            geo_id = HARDCODED_URNS.get(location.lower()) or self.voyager_geo_lookup(location)
            if geo_id:
                print(f'  [search] Resolved "{location}" → geoUrn {geo_id}')
            else:
                print(f'  [search] Could not resolve location "{location}" — client-side fallback')

        # Resolve industry → industry URN for server-side filtering
        industry_id = None
        if industry:
            industry_id = self.voyager_industry_lookup(industry)
            if industry_id:
                print(f'  [search] Resolved industry "{industry}" → industry URN {industry_id}')
            else:
                print(f'  [search] Could not resolve industry "{industry}"')

        # Build server-side queryParameters filter list
        filters = 'List((key:resultType,value:List(PEOPLE))'
        if first_degree_only:
            filters += ',(key:network,value:List(F))'
        if geo_id:
            filters += f',(key:geoUrn,value:List({geo_id}))'
        if industry_id:
            filters += f',(key:industry,value:List({industry_id}))'
        # Server-side title filter — far more accurate than client-side headline matching
        if effective_title:
            filters += f',(key:title,value:List({quote(effective_title, safe="")}))'
        filters += ')'

        # Paginated fetch loop — page_size=49 is required to avoid early cutoff
        people, seen = [], set()
        for page in range(50):           # max 50 pages ≈ 2,450 results
            start = page * page_size
            variables = (
                f'(query:(keywords:{quote(kw, safe="")},'
                f'flagshipSearchIntent:SEARCH_SRP,'
                f'queryParameters:{filters},'
                f'includeFiltersInResponse:false),'
                f'start:{start},count:{page_size})'
            )
            url = (
                'https://www.linkedin.com/voyager/api/graphql'
                '?queryId=voyagerSearchDashClusters.b0928897b71bd00a5a7291755dcd64f0'
                f'&variables={variables}'
            )
            d = self._voyager_fetch(url)
            if not d:
                break

            page_people = []
            for item in d.get('included', []):
                if 'EntityResultViewModel' not in item.get('$type', ''):
                    continue
                name     = (item.get('title') or {}).get('text', '')
                headline = (item.get('primarySubtitle') or {}).get('text', '')
                loc      = (item.get('secondarySubtitle') or {}).get('text', '')
                nav_url  = (item.get('navigationContext') or {}).get('url', '') or item.get('navigationUrl', '')
                slug     = nav_url.split('/in/')[-1].split('?')[0].strip('/') if '/in/' in nav_url else ''
                urn      = item.get('entityUrn', '')
                if not name or not slug or slug in seen:
                    continue
                # Client-side location fallback only when geoUrn resolution failed
                if location and not geo_id:
                    if location.lower() not in loc.lower():
                        continue
                seen.add(slug)
                page_people.append({
                    'slug':        slug,
                    'name':        name,
                    'headline':    headline,
                    'location':    loc,
                    'urn':         urn,
                    'profile_url': f'https://www.linkedin.com/in/{slug}/',
                })

            people.extend(page_people)
            total_hint = ''
            try:
                total_hint = f" / {d['data']['data']['searchDashClustersByAll']['paging']['total']} total"
            except (KeyError, TypeError):
                pass
            print(f'  [search] page {page + 1}: +{len(page_people)} (running: {len(people)}{total_hint})')

            if len(page_people) == 0 or len(people) >= count:
                break

            time.sleep(delay_between_pages)

        return people[:count]

    def voyager_get_profile_posts(self, slug_or_urn: str, count: int = 10) -> list:
        """
        Get a member's recent posts via identity/profileUpdatesV2 (memberShareFeed).

        slug_or_urn: search-result fsd_profile URN OR a public identifier like 'zhu-amanda'.
        Returns list of dicts: post_urn, post_url, text, reactions, comments, share_url.
        """
        # Resolve slug → fsd_profile URN
        if slug_or_urn.startswith('urn:li:fsd_profile:'):
            profile_urn = slug_or_urn
        else:
            slug = slug_or_urn.rstrip('/').split('/')[-1].split('?')[0]
            people = self.voyager_search_people(slug.replace('-', ' '), count=10)
            match = next((p for p in people if p.get('slug', '').lower() == slug.lower()), None) \
                    or (people[0] if people else None)
            if not match:
                return []
            import re as _re
            m = _re.search(r'(urn:li:fsd_profile:[^,)]+)', match.get('urn', ''))
            profile_urn = m.group(1) if m else ''
        if not profile_urn:
            return []

        url = (
            'https://www.linkedin.com/voyager/api/identity/profileUpdatesV2'
            f'?profileUrn={quote(profile_urn, safe="")}'
            f'&q=memberShareFeed&count={count}'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []

        included = d.get('included', [])
        # Build lookup: socialDetail URN -> counts
        social_counts = {}
        for it in included:
            if it.get('$type') == 'com.linkedin.voyager.feed.shared.SocialActivityCounts':
                key = it.get('entityUrn', '')
                social_counts[key] = {
                    'reactions': it.get('numLikes', 0) or it.get('numImpressions', 0),
                    'comments':  it.get('numComments', 0),
                }

        # Now scan UpdateV2 items
        posts = []
        for it in included:
            if it.get('$type') != 'com.linkedin.voyager.feed.render.UpdateV2':
                continue
            meta = it.get('updateMetadata') or {}
            urn = meta.get('urn', '')
            share_url = (it.get('socialContent') or {}).get('shareUrl', '')
            commentary = it.get('commentary') or {}
            text = (commentary.get('text') or {}).get('text', '') or ''

            # Counts via socialDetail ref
            social_ref = it.get('*socialDetail', '')
            sc = social_counts.get(social_ref, {})
            # Fallback: scan included for SocialActivityCounts whose entityUrn contains this activity
            if not sc and urn:
                for c_key, c_val in social_counts.items():
                    if urn in c_key:
                        sc = c_val; break

            posts.append({
                'post_urn':   urn,
                'post_url':   f'https://www.linkedin.com/feed/update/{urn}/' if urn else '',
                'share_url':  share_url,
                'text':       text,
                'reactions':  sc.get('reactions', 0),
                'comments':   sc.get('comments', 0),
            })
            if len(posts) >= count:
                break
        return posts

    def voyager_search_posts(self, query: str, count: int = 20) -> list:
        """
        Search posts via the real LinkedIn search API (resultType:CONTENT).
        Returns list of dicts: post_urn, post_url, author_name, author_headline, text_snippet.
        """
        from urllib.parse import quote
        page_size = min(count, 49)
        variables = (
            f'(query:(keywords:{quote(query, safe="")},'
            f'flagshipSearchIntent:SEARCH_SRP,'
            f'queryParameters:List((key:resultType,value:List(CONTENT))),'
            f'includeFiltersInResponse:false),'
            f'start:0,count:{page_size})'
        )
        url = (
            'https://www.linkedin.com/voyager/api/graphql'
            '?queryId=voyagerSearchDashClusters.b0928897b71bd00a5a7291755dcd64f0'
            f'&variables={variables}'
        )
        d = self._voyager_fetch(url)
        if not d:
            return []

        posts = []
        for item in d.get('included', []):
            item_type = item.get('$type', '')
            # Content results come through as EntityResultViewModel
            if 'EntityResultViewModel' not in item_type:
                continue
            title_obj    = item.get('title') or {}
            subtitle_obj = item.get('primarySubtitle') or {}
            summary_obj  = item.get('summary') or {}
            nav_url      = (item.get('navigationContext') or {}).get('url', '') or item.get('navigationUrl', '')
            author_name  = title_obj.get('text', '')
            author_hl    = subtitle_obj.get('text', '')
            snippet      = summary_obj.get('text', '') if isinstance(summary_obj, dict) else ''
            post_url     = nav_url if nav_url.startswith('http') else f'https://www.linkedin.com{nav_url}'
            urn          = item.get('entityUrn', '')
            if not author_name:
                continue
            posts.append({
                'post_urn':        urn,
                'post_url':        post_url,
                'author_name':     author_name,
                'author_headline': author_hl,
                'text_snippet':    snippet[:400],
            })
            if len(posts) >= count:
                break
        return posts

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    def _random_wait(self, min_s=2, max_s=6):
        """Human-like random delay."""
        time.sleep(random.uniform(min_s, max_s))

    def get_csrf_token(self) -> str:
        """Extract CSRF token (= JSESSIONID without quotes) from page cookies."""
        token = self._page.evaluate('''() => {
            const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
            return m ? m[1] : "";
        }''')
        return token

    def get_profile_urn(self, slug: str) -> str:
        """
        Get fsd_profile URN for a LinkedIn slug via GraphQL Voyager API.
        Returns urn:li:fsd_profile:ACoAA... or None.
        """
        result = self._page.evaluate('''async (slug) => {
            const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
            const token = m ? m[1] : "";
            const url = "https://www.linkedin.com/voyager/api/graphql?includeWebMetadata=true&variables=(memberIdentity:" + slug + ")&queryId=voyagerIdentityDashProfiles.273a499c117721535e6da078bee17e9c";
            try {
                const r = await fetch(url, {
                    headers: {"csrf-token": token, "accept": "application/vnd.linkedin.normalized+json+2.1", "x-restli-protocol-version": "2.0.0"},
                    credentials: "include"
                });
                const d = await r.json();
                const included = d.included || [];
                const profile = included.find(i => i && i.entityUrn && i.entityUrn.includes("fsd_profile"));
                return profile ? profile.entityUrn : null;
            } catch(e) { return null; }
        }''', slug)
        return result

    # ------------------------------------------------------------------ #
    #  LinkedIn Easy Apply
    # ------------------------------------------------------------------ #

    # Matthew Dewstowe's application defaults — used to auto-fill common fields
    _APPLY_PROFILE = {
        'first_name':    'Matthew',
        'last_name':     'Dewstowe',
        'email':         'matthewdewstowe@gmail.com',
        'phone':         '+44 7825 765501',
        'phone_country': 'United Kingdom (+44)',
        'city':          'London',
        'linkedin':      'https://www.linkedin.com/in/matthewdewstowe',
        'website':       'https://nthlayer.co.uk',
        'salary':        '130000',
        'salary_text':   '£130,000',
        'notice':        '1 month',
        'notice_weeks':  '4',
        'cv_path':       '/Users/matthew_dewstowe/Claude Code/job-apply-firecrawl/public/cv.pdf',
    }

    # Keyword → answer mappings for common Easy Apply questions
    _EASY_APPLY_ANSWERS = {
        # Right to work / visa
        'right to work':             'yes',
        'work in the uk':            'yes',
        'authorised to work':        'yes',
        'authorized to work':        'yes',
        'eligible to work':          'yes',
        'legally entitled':          'yes',
        'work permit':               'yes',
        'visa sponsorship':          'no',
        'require sponsorship':       'no',
        'need sponsorship':          'no',
        'require a visa':            'no',
        # Notice / availability
        'notice period':             '1 month',
        'how soon':                  '1 month',
        'when can you start':        '1 month',
        'available to start':        '1 month',
        # Salary
        'salary expectation':        '130000',
        'expected salary':           '130000',
        'desired salary':            '130000',
        'base salary':               '130000',
        'compensation':              '130000',
        # Source
        'how did you hear':          'LinkedIn',
        'how did you find':          'LinkedIn',
        'referral':                  'LinkedIn',
        'source':                    'LinkedIn',
        # Gender / diversity (self-describe or prefer not to say)
        'gender':                    'Prefer not to say',
        'ethnicity':                 'Prefer not to say',
        'disability':                'Prefer not to say',
        'veteran':                   'No',
        # Remote / hybrid
        'work remotely':             'yes',
        'hybrid working':            'yes',
        # Relocate
        'willing to relocate':       'no',
        'relocation':                'no',
        # Experience years
        'years of experience':       '15',
        'years experience':          '15',
    }

    def easy_apply_job(self, job_url: str, dry_run: bool = False) -> dict:
        """
        Apply to a LinkedIn Easy Apply job via Playwright browser automation.

        Args:
            job_url:  Full LinkedIn job URL  e.g. https://www.linkedin.com/jobs/view/1234567890/
                      or just the numeric job ID.
            dry_run:  If True, navigate and check the button but don't click Apply.

        Returns:
            {success, title, company, url, applied, skipped, error, unanswered_questions}
        """
        page = self._page
        cv_path = self._APPLY_PROFILE['cv_path']

        # Normalise URL — extract job ID, then use two-pane URL which renders Easy Apply button
        import re as _re_ea
        job_id_match = _re_ea.search(r'/jobs/view/(\d+)', str(job_url))
        if str(job_url).isdigit():
            job_id = str(job_url)
        elif job_id_match:
            job_id = job_id_match.group(1)
        else:
            job_id = ''

        # Use two-pane search URL (?currentJobId=) — this is the only layout that renders the Easy Apply button
        if job_id:
            nav_url = f'https://www.linkedin.com/jobs/search/?currentJobId={job_id}'
        else:
            nav_url = job_url if job_url.startswith('http') else f'https://www.linkedin.com/jobs/view/{job_url}/'

        job_url = f'https://www.linkedin.com/jobs/view/{job_id}/' if job_id else nav_url

        # ── Warm up the session on /jobs/ first ──────────────────────────
        # Navigating cold to ?currentJobId= can trigger LinkedIn's consent overlay.
        # Going to /jobs/ first ensures the session cookie is active.
        current_url = page.url or ''
        if '/jobs' not in current_url and 'linkedin.com' not in current_url:
            try:
                page.goto('https://www.linkedin.com/jobs/', wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(2000)
            except Exception:
                pass
        elif 'linkedin.com' not in current_url:
            try:
                page.goto('https://www.linkedin.com/jobs/', wait_until='domcontentloaded', timeout=20000)
                page.wait_for_timeout(2000)
            except Exception:
                pass

        print(f'  [EasyApply] Navigating → {nav_url}')
        try:
            page.goto(nav_url, wait_until='domcontentloaded', timeout=30000)
        except Exception as _nav_err:
            print(f'  [EasyApply] Navigation warning: {_nav_err}')
        # LinkedIn SPA keeps making API calls — networkidle never settles cleanly.
        # Use a fixed 4 s wait which matches what worked in manual debug tests.
        page.wait_for_timeout(4000)
        # Scroll slightly to trigger lazy rendering of the apply button in the right pane
        try:
            page.evaluate('window.scrollBy(0, 300)')
        except Exception:
            pass
        page.wait_for_timeout(1000)

        # ── Extract job meta ──────────────────────────────────────────────
        # ── Dismiss any consent / cookie overlay ─────────────────────────
        # LinkedIn shows a consent overlay with plain "Accept" / "Reject" buttons (no aria-label)
        try:
            consent_btn = page.evaluate('''() => {
                // Find visible button whose text is exactly "Accept" or "Reject"
                for (const btn of document.querySelectorAll("button")) {
                    const t = btn.textContent.trim();
                    if ((t === "Accept" || t === "Reject") && btn.offsetParent !== null) {
                        return true;  // signal found
                    }
                }
                return false;
            }''')
            if consent_btn:
                # Use Playwright locator to find and click it
                btn_loc = page.locator('button', has_text='Accept').first
                if btn_loc.is_visible():
                    print(f'  [EasyApply] Dismissing consent overlay...')
                    btn_loc.click(timeout=3000)
                    page.wait_for_timeout(2000)
        except Exception:
            pass

        # ── Check for Easy Apply button first ────────────────────────────
        # Two-pane layout has TWO buttons with the same aria-label — one in the left job-card
        # list (off-screen/invisible) and one in the right detail pane (the one to click).
        # Always pick the VISIBLE one.
        def _find_visible_ea_btn(pg):
            for selector in [
                'button[aria-label^="Easy Apply to"]',
                'button[aria-label="Easy Apply"]',
                'button[aria-label*="Easy Apply"]',
                'button.jobs-apply-button[aria-label*="Easy Apply"]',
                'button.jobs-apply-button',
            ]:
                candidates = pg.query_selector_all(selector)
                for c in candidates:
                    try:
                        if c.is_visible():
                            return c
                    except Exception:
                        pass
                if candidates:
                    return candidates[0]  # fallback to first if none visible
            return None

        ea_btn = _find_visible_ea_btn(page)

        # ── Extract job meta ──────────────────────────────────────────────
        # Primary: parse title+company from the Easy Apply button aria-label
        #   e.g. "Easy Apply to VP Product at Unitary"
        title, company = '', ''
        if ea_btn:
            btn_label_raw = ea_btn.get_attribute('aria-label') or ''
            # "Easy Apply to TITLE at COMPANY"
            import re as _re_meta
            m = _re_meta.match(r'Easy Apply to (.+?) at (.+?)$', btn_label_raw.strip())
            if m:
                title   = m.group(1).strip()
                company = m.group(2).strip()

        # Fallback: parse from page DOM (job detail pane or single-pane)
        if not title or not company:
            meta = page.evaluate('''() => {
                let title = '', company = '';
                // Job detail right-pane title heading
                const titleEl = document.querySelector(
                    '.job-details-jobs-unified-top-card__job-title h1, ' +
                    '.jobs-unified-top-card__job-title h2, ' +
                    'h2.t-24.t-bold, ' +
                    'h1.t-24, ' +
                    'h1'
                );
                if (titleEl) title = titleEl.textContent.trim();

                // Company name
                const co = document.querySelector(
                    '.job-details-jobs-unified-top-card__company-name a, ' +
                    '.jobs-unified-top-card__company-name a, ' +
                    'a[href*="/company/"]'
                );
                if (co) company = co.textContent.trim();
                return {title, company};
            }''')
            if not title:   title   = meta.get('title', '')
            if not company: company = meta.get('company', '')
        if not ea_btn:
            return {
                'success': False, 'title': title, 'company': company,
                'url': job_url, 'applied': False, 'skipped': True,
                'error': 'No Easy Apply button found — may be external application',
            }

        print(f'  [EasyApply] Job: "{title}" at "{company}"')

        # ── Already applied? ──────────────────────────────────────────────
        btn_label = (ea_btn.get_attribute('aria-label') or '').lower() if ea_btn else ''
        if 'applied' in btn_label or 'withdraw' in btn_label:
            print(f'  [EasyApply] Already applied — skipping')
            return {
                'success': True, 'title': title, 'company': company,
                'url': job_url, 'applied': False, 'skipped': True,
                'error': 'Already applied',
            }

        if dry_run:
            print(f'  [EasyApply] DRY RUN — would click Easy Apply')
            return {
                'success': True, 'title': title, 'company': company,
                'url': job_url, 'applied': False, 'skipped': False, 'dry_run': True,
            }

        # ── Click Easy Apply ──────────────────────────────────────────────
        # In the two-pane layout there are two EA buttons; the right-pane one is visible
        # but may not be in viewport. Use JS click (bypasses viewport check) then wait.
        try:
            page.evaluate('(el) => el.click()', ea_btn)
            page.wait_for_timeout(2000)
            print(f'  [EasyApply] Clicked Easy Apply (JS click)')
        except Exception as _click_err:
            # Fallback: scroll into view and use Playwright click
            try:
                ea_btn.scroll_into_view_if_needed()
                page.wait_for_timeout(800)
                ea_btn.click(timeout=8000)
                page.wait_for_timeout(2000)
                print(f'  [EasyApply] Clicked Easy Apply (scroll+click)')
            except Exception as _retry_err:
                return {
                    'success': False, 'title': title, 'company': company,
                    'url': job_url, 'applied': False, 'skipped': True,
                    'error': f'Easy Apply click failed: {_retry_err}',
                }

        unanswered = []
        cv_uploaded = False

        # ── Multi-step form loop ──────────────────────────────────────────
        for step_num in range(12):
            # Check modal is open
            modal = (
                page.query_selector('.jobs-easy-apply-modal')
                or page.query_selector('[data-test-modal]')
                or page.query_selector('[role="dialog"]')
            )
            if not modal:
                print(f'  [EasyApply] Modal closed after step {step_num}')
                break

            print(f'  [EasyApply] Step {step_num + 1} — filling fields...')

            # ── Fill contact/text fields ──────────────────────────────────
            unanswered += self._fill_easy_apply_step(page, modal)

            # ── Handle CV/resume selection or upload ──────────────────────
            if not cv_uploaded:
                # Case 1: LinkedIn shows a "choose saved resume" list — always pick the first option
                saved_resume_first = (
                    # Radio buttons for previously uploaded CVs
                    modal.query_selector(
                        'input[type="radio"][name*="resume"], '
                        'input[type="radio"][name*="cv"], '
                        'div[data-test-resume-list-item] input[type="radio"], '
                        'li[data-test-resume-list-item] input[type="radio"]'
                    )
                    # Selectable card-style resume items (click the card itself)
                    or modal.query_selector(
                        '.jobs-document-upload-redesign-card__container, '
                        '[data-test-resume-list-item]'
                    )
                )
                if saved_resume_first:
                    try:
                        if saved_resume_first.get_attribute('type') == 'radio':
                            saved_resume_first.click()
                        else:
                            # Card-style — click the first item
                            saved_resume_first.click()
                        page.wait_for_timeout(800)
                        cv_uploaded = True
                        print(f'  [EasyApply] ✓ Selected first saved CV option')
                    except Exception as e:
                        print(f'  [EasyApply] Saved CV selection failed: {e}')

                # Case 2: Standard file upload input
                if not cv_uploaded:
                    file_input = modal.query_selector('input[type="file"]')
                    if file_input:
                        try:
                            file_input.set_input_files(cv_path)
                            page.wait_for_timeout(1500)
                            cv_uploaded = True
                            print(f'  [EasyApply] ✓ CV uploaded via file input')
                        except Exception as e:
                            print(f'  [EasyApply] CV upload failed: {e}')

            page.wait_for_timeout(800)

            # ── Decide what button to press ───────────────────────────────
            # Priority: Submit > Review > Next > Continue
            submit_btn = (
                modal.query_selector('button[aria-label="Submit application"]')
                or modal.query_selector('button:text("Submit application")')
            )
            if submit_btn and submit_btn.is_enabled():
                print(f'  [EasyApply] Clicking Submit application...')
                submit_btn.click()
                page.wait_for_timeout(3000)

                # Check for success confirmation
                success_el = (
                    page.query_selector('[data-test-success]')
                    or page.query_selector('.jobs-easy-apply-modal__post-apply-status')
                    or page.query_selector('[aria-label*="Application submitted"]')
                    or page.query_selector('h2:text("Your application was sent")')
                    or page.query_selector('[class*="post-apply"]')
                )
                # Also check modal disappeared = success
                modal_gone = not (
                    page.query_selector('.jobs-easy-apply-modal')
                    or page.query_selector('[data-test-modal]')
                )
                applied = bool(success_el or modal_gone)
                print(f'  [EasyApply] {"✅ Applied!" if applied else "⚠️  Submit clicked but confirmation unclear"}')

                # Dismiss any post-apply modal
                dismiss = page.query_selector('button[aria-label="Dismiss"]')
                if dismiss:
                    dismiss.click()
                    page.wait_for_timeout(500)

                return {
                    'success': applied,
                    'title': title, 'company': company, 'url': job_url,
                    'applied': applied,
                    'skipped': False,
                    'cv_uploaded': cv_uploaded,
                    'unanswered_questions': unanswered,
                    'error': None if applied else 'Submit clicked but could not confirm success',
                }

            # Review step — click Review first, then loop will hit Submit
            review_btn = (
                modal.query_selector('button[aria-label="Review your application"]')
                or modal.query_selector('button:text("Review")')
            )
            if review_btn and review_btn.is_enabled():
                print(f'  [EasyApply] Clicking Review...')
                review_btn.click()
                page.wait_for_timeout(1500)
                continue

            # Next step
            next_btn = (
                modal.query_selector('button[aria-label="Continue to next step"]')
                or modal.query_selector('footer button:last-child')
            )
            if next_btn and next_btn.is_enabled():
                print(f'  [EasyApply] Clicking Next...')
                next_btn.click()
                page.wait_for_timeout(1500)
                continue

            # Nothing clickable — bail
            print(f'  [EasyApply] No actionable button found at step {step_num + 1}')
            break

        # If we exit loop without submitting, dismiss and report
        dismiss = page.query_selector('button[aria-label="Dismiss"]')
        if dismiss:
            dismiss.click()
            page.wait_for_timeout(500)
            # Confirm discard if dialog appears
            discard = page.query_selector('button[data-control-name="discard_application_confirm_btn"]')
            if discard:
                discard.click()

        return {
            'success': False,
            'title': title, 'company': company, 'url': job_url,
            'applied': False, 'skipped': False,
            'cv_uploaded': cv_uploaded,
            'unanswered_questions': unanswered,
            'error': 'Could not complete application — max steps reached or no Submit button found',
        }

    def _fill_easy_apply_step(self, page, modal) -> list:
        """
        Fill all visible form fields in the current Easy Apply modal step.
        Returns list of question labels that couldn't be auto-answered.
        """
        unanswered = []
        p = self._APPLY_PROFILE
        answers = self._EASY_APPLY_ANSWERS

        # ── Text / tel inputs ─────────────────────────────────────────────
        inputs = modal.query_selector_all('input:not([type="file"]):not([type="hidden"]):not([type="radio"]):not([type="checkbox"])')
        for inp in inputs:
            # Skip already-filled inputs
            current_val = inp.input_value() if inp.is_visible() else ''
            if current_val.strip():
                continue
            if not inp.is_enabled():
                continue

            # Get label
            label = self._get_field_label(page, inp).lower()

            # Match known profile fields first
            val = None
            if 'first' in label and 'name' in label:
                val = p['first_name']
            elif 'last' in label and 'name' in label:
                val = p['last_name']
            elif 'full' in label and 'name' in label:
                val = f"{p['first_name']} {p['last_name']}"
            elif 'email' in label:
                val = p['email']
            elif 'phone' in label or 'mobile' in label or 'tel' in label:
                val = p['phone']
            elif 'city' in label or ('location' in label and 'url' not in label):
                val = p['city']
            elif 'linkedin' in label:
                val = p['linkedin']
            elif 'website' in label or 'portfolio' in label:
                val = p['website']
            else:
                # Try keyword answers
                for kw, answer in answers.items():
                    if kw in label:
                        # Only apply text answers for text inputs (not yes/no)
                        if answer.lower() not in ('yes', 'no'):
                            val = answer
                        break

            if val:
                try:
                    inp.fill(val)
                    page.wait_for_timeout(200)
                except Exception:
                    pass
            elif inp.is_visible() and inp.get_attribute('required') == 'true':
                unanswered.append(f'[text] {label}')

        # ── Textareas ─────────────────────────────────────────────────────
        textareas = modal.query_selector_all('textarea')
        for ta in textareas:
            if not ta.is_visible() or not ta.is_enabled():
                continue
            current_val = ta.input_value()
            if current_val.strip():
                continue
            label = self._get_field_label(page, ta).lower()
            # Leave cover letter / open-ended blank but note it
            unanswered.append(f'[textarea] {label}')

        # ── Select dropdowns ──────────────────────────────────────────────
        selects = modal.query_selector_all('select')
        for sel in selects:
            if not sel.is_visible() or not sel.is_enabled():
                continue
            current_val = sel.input_value()
            if current_val and current_val not in ('', 'Select an option', 'Please select'):
                continue
            label = self._get_field_label(page, sel).lower()

            chosen = None
            for kw, answer in answers.items():
                if kw in label:
                    chosen = answer
                    break

            if chosen:
                # Try exact option text match then partial
                options = sel.query_selector_all('option')
                for opt in options:
                    txt = (opt.text_content() or '').strip().lower()
                    if txt == chosen.lower() or chosen.lower() in txt:
                        try:
                            sel.select_option(label=opt.text_content().strip())
                            page.wait_for_timeout(200)
                        except Exception:
                            pass
                        break
            else:
                unanswered.append(f'[select] {label}')

        # ── Radio buttons (Yes/No questions) ──────────────────────────────
        # Group radios by name attribute
        radios = modal.query_selector_all('input[type="radio"]')
        seen_groups = set()
        for radio in radios:
            name = radio.get_attribute('name') or ''
            if name in seen_groups:
                continue
            seen_groups.add(name)
            if not radio.is_visible():
                continue

            # Get label for the whole group (use fieldset legend or nearby text)
            group_label = self._get_radio_group_label(page, modal, name).lower()

            # Match answer
            target_val = None
            for kw, answer in answers.items():
                if kw in group_label and answer.lower() in ('yes', 'no'):
                    target_val = answer.lower()
                    break

            if target_val:
                # Find the radio with matching value or label
                group_radios = modal.query_selector_all(f'input[type="radio"][name="{name}"]')
                for r in group_radios:
                    r_val = (r.get_attribute('value') or '').lower()
                    r_label = self._get_field_label(page, r).lower()
                    if r_val == target_val or target_val in r_label:
                        try:
                            r.click()
                            page.wait_for_timeout(200)
                        except Exception:
                            pass
                        break
            else:
                unanswered.append(f'[radio] {group_label}')

        # ── Combobox / typeahead dropdowns (LinkedIn custom selects) ──────
        combos = modal.query_selector_all('[role="combobox"]')
        for combo in combos:
            if not combo.is_visible() or not combo.is_enabled():
                continue
            current_val = (combo.input_value() if combo.tag_name() == 'input' else '').strip()
            if current_val:
                continue
            label = self._get_field_label(page, combo).lower()

            chosen = None
            for kw, answer in answers.items():
                if kw in label:
                    chosen = answer
                    break

            if chosen:
                try:
                    combo.click()
                    page.wait_for_timeout(400)
                    combo.fill(chosen)
                    page.wait_for_timeout(600)
                    # Click first listbox option
                    option = page.query_selector('[role="option"]:first-child')
                    if option:
                        option.click()
                    page.wait_for_timeout(300)
                except Exception:
                    pass
            else:
                unanswered.append(f'[combobox] {label}')

        return unanswered

    @staticmethod
    def _get_field_label(page, element) -> str:
        """Get the visible label text for a form element."""
        try:
            # Try for= attribute pointing to this input's id
            el_id = element.get_attribute('id') or ''
            if el_id:
                label_el = page.query_selector(f'label[for="{el_id}"]')
                if label_el:
                    return label_el.text_content().strip()

            # aria-label
            aria = element.get_attribute('aria-label') or ''
            if aria:
                return aria.strip()

            # aria-labelledby
            labelledby = element.get_attribute('aria-labelledby') or ''
            if labelledby:
                label_el = page.query_selector(f'#{labelledby}')
                if label_el:
                    return label_el.text_content().strip()

            # Walk up to find a label/legend sibling
            text = element.evaluate('''el => {
                let node = el.parentElement;
                for (let i = 0; i < 5; i++) {
                    if (!node) break;
                    const label = node.querySelector("label, legend, span.t-bold, [class*='label']");
                    if (label && label.textContent.trim()) return label.textContent.trim();
                    node = node.parentElement;
                }
                return "";
            }''')
            return text or ''
        except Exception:
            return ''

    @staticmethod
    def _get_radio_group_label(page, modal, group_name: str) -> str:
        """Get the legend/label for a radio group by name attribute."""
        try:
            text = modal.evaluate('''(name) => {
                const radio = document.querySelector('input[type="radio"][name="' + name + '"]');
                if (!radio) return "";
                let node = radio.parentElement;
                for (let i = 0; i < 8; i++) {
                    if (!node) break;
                    if (node.tagName === "FIELDSET") {
                        const legend = node.querySelector("legend");
                        if (legend) return legend.textContent.trim();
                    }
                    const label = node.querySelector("label, legend, span.t-bold, [class*='label']");
                    if (label && label !== radio.parentElement && label.textContent.trim())
                        return label.textContent.trim();
                    node = node.parentElement;
                }
                return "";
            }''', group_name)
            return text or group_name
        except Exception:
            return group_name

    def job_search_and_apply(
        self,
        keywords: str,
        location: str = 'United Kingdom',
        limit: int = 5,
        days_posted: int = 7,
        dry_run: bool = False,
    ) -> list:
        """
        Search for Easy Apply jobs and apply to them sequentially.

        Returns list of result dicts from easy_apply_job().
        """
        import time as _time

        print(f'  [JobSearch] Searching: "{keywords}" | location: {location} | limit: {limit}')
        jobs = self.search_jobs(keywords, location=location, easy_apply_only=True, days_posted=days_posted)
        print(f'  [JobSearch] Found {len(jobs)} Easy Apply jobs')

        results = []
        for i, job in enumerate(jobs[:limit]):
            print(f'\n  [{i+1}/{min(limit, len(jobs))}] {job["title"]} @ {job["company"]}')
            print(f'       URL: {job["url"]}')
            result = self.easy_apply_job(job['url'], dry_run=dry_run)
            result['search_meta'] = job
            results.append(result)

            if i < limit - 1:
                delay = __import__('random').uniform(8, 20)
                print(f'  [JobSearch] Waiting {delay:.1f}s before next application...')
                _time.sleep(delay)

        return results
