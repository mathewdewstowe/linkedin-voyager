"""
Endpoint smoke-test — runs all 6 Voyager endpoints and prints results.
Usage:  python test_endpoints.py
Reads JSESSIONID from ~/Job Apply/voyager-campaign.json
"""
import json, os, sys, textwrap, time

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL_DIR)
from voyager_client import VoyagerClient

CAMPAIGN_PATH = os.path.expanduser('~/Job Apply/voyager-campaign.json')

PASS = '✅'
FAIL = '❌'
WARN = '⚠️ '

def sep(title):
    print(f'\n{"─"*60}')
    print(f'  {title}')
    print('─'*60)

def load_client():
    with open(CAMPAIGN_PATH) as f:
        cfg = json.load(f)
    jsessionid = cfg.get('sessionToken', '')
    li_at = cfg.get('liAt', '')
    if not jsessionid:
        raise RuntimeError(f'No sessionToken in {CAMPAIGN_PATH}')
    return VoyagerClient(jsessionid=jsessionid, li_at=li_at or None)


def test_auth(client):
    sep('1. Auth check  — GET /me')
    me = client.get_me()
    if me:
        mini = me.get('miniProfile', me)
        first = mini.get('firstName', '?')
        last  = mini.get('lastName', '?')
        print(f'{PASS} Logged in as: {first} {last}')
        return True
    else:
        print(f'{FAIL} Auth failed — check sessionToken')
        return False


def test_search_people_keyword(client):
    sep('2. People search — keyword  (query="Head of Engineering")')
    people = client.search_people(query='Head of Engineering', count=5)
    if people:
        print(f'{PASS} Got {len(people)} results:')
        for p in people[:3]:
            print(f'   • {p["name"]}  |  {p["headline"][:60]}')
            print(f'     {p["profile_url"]}')
    else:
        print(f'{FAIL} No results (or parse error)')
    return people


def test_search_people_title(client):
    sep('3. People search — title facet  (--title "VP of Sales")')
    people = client.search_people(title='VP of Sales', count=5)
    if people:
        print(f'{PASS} Got {len(people)} results with title facet:')
        for p in people[:3]:
            print(f'   • {p["name"]}  |  {p["headline"][:60]}')
            print(f'     {p["profile_url"]}')
    else:
        print(f'{FAIL} No results — title facet may need URL-encoding tweak')
    return people


def test_search_people_1st(client):
    sep('4. People search — 1st degree only  (query="Sales")')
    people = client.search_people(query='Sales', first_degree_only=True, count=5)
    if people:
        print(f'{PASS} Got {len(people)} 1st-degree results:')
        for p in people[:3]:
            print(f'   • {p["name"]}  |  {p["headline"][:60]}')
    else:
        print(f'{WARN} 0 results — may have no 1st-degree connections matching "Sales"')
    return people


def test_search_posts(client):
    sep('5. Post search  — GET /search/blended CONTENT  (query="AI sales")')
    posts = client.search_posts(query='AI sales', count=5)
    if posts:
        print(f'{PASS} Got {len(posts)} posts:')
        for p in posts[:3]:
            print(f'   • Author: {p["author_name"]}')
            print(f'     URN:   {p["post_urn"]}')
            if p['text_snippet']:
                snippet = textwrap.shorten(p['text_snippet'], 100, placeholder='…')
                print(f'     Text:  {snippet}')
        return posts
    else:
        print(f'{FAIL} No posts returned')
        return []


def test_post_likers(client, post_urn):
    sep(f'6. Post likers  — GET /reactions/v2')
    print(f'   URN: {post_urn}')
    likers = client.get_post_likers(post_urn, count=10)
    if likers:
        print(f'{PASS} Got {len(likers)} likers:')
        for l in likers[:3]:
            print(f'   • {l["name"]}  ({l["reaction_type"]})')
            print(f'     {l["headline"][:60]}')
            print(f'     {l["profile_url"]}')
    else:
        print(f'{FAIL} No likers returned — URN may be wrong or post has 0 likes')
    return likers


def test_post_comments(client, post_urn):
    sep(f'7. Post comments  — GET /feed/comments')
    print(f'   URN: {post_urn}')
    comments = client.get_post_comments(post_urn, count=10)
    if comments:
        print(f'{PASS} Got {len(comments)} comments:')
        for c in comments[:3]:
            print(f'   • {c["author_name"]}  |  {c["author_headline"][:50]}')
            text = textwrap.shorten(c['comment_text'], 120, placeholder='…')
            print(f'     "{text}"')
            print(f'     {c["profile_url"]}')
    else:
        print(f'{FAIL} No comments returned')
    return comments


def test_conversations(client):
    sep('8. Conversations (inbox)  — GET /voyagerMessagingDashMessengerConversations')
    convs = client.get_conversations(count=5)
    if convs:
        print(f'{PASS} Got {len(convs)} conversations:')
        for c in convs[:3]:
            unread = f'  [{c["unread_count"]} unread]' if c['unread_count'] else ''
            print(f'   • {c["participant_name"]}{unread}')
            print(f'     {c["participant_url"]}')
            if c['last_message_text']:
                snippet = textwrap.shorten(c['last_message_text'], 100, placeholder='…')
                print(f'     Last: "{snippet}"')
        return convs
    else:
        print(f'{FAIL} No conversations returned')
        return []


def test_messages(client, conversation_urn):
    sep(f'9. Messages in conversation  — GET /voyagerMessagingDashMessengerMessages')
    print(f'   URN: {conversation_urn}')
    msgs = client.get_messages(conversation_urn, count=5)
    if msgs:
        print(f'{PASS} Got {len(msgs)} messages:')
        for m in msgs[:3]:
            text = textwrap.shorten(m['text'], 120, placeholder='…') if m['text'] else '(no text)'
            print(f'   • {m["sender_name"]}: "{text}"')
    else:
        print(f'{FAIL} No messages returned')
    return msgs


def main():
    print('\n🔬 LinkedIn Voyager — Endpoint Smoke Test')
    print(f'   Session: {CAMPAIGN_PATH}')

    client = load_client()

    # 1. Auth
    ok = test_auth(client)
    if not ok:
        print('\n⛔ Aborting — fix auth first')
        sys.exit(1)

    # 2-4. People search variants
    test_search_people_keyword(client)
    time.sleep(1)
    test_search_people_title(client)
    time.sleep(1)
    test_search_people_1st(client)
    time.sleep(1)

    # 5. Post search — grab a URN for likers/comments tests
    posts = test_search_posts(client)
    time.sleep(1)

    post_urn = None
    if posts:
        post_urn = posts[0]['post_urn']
    else:
        # Fallback: hardcode a known public post URN if search fails
        post_urn = 'urn:li:activity:7321498765432109876'
        print(f'\n{WARN} Using fallback post URN for likers/comments test: {post_urn}')

    # 6-7. Likers + comments
    test_post_likers(client, post_urn)
    time.sleep(1)
    test_post_comments(client, post_urn)
    time.sleep(1)

    # 8. Inbox
    convs = test_conversations(client)
    time.sleep(1)

    # 9. Messages inside first conversation
    if convs:
        test_messages(client, convs[0]['conversation_urn'])
    else:
        sep('9. Messages — SKIPPED (no conversations found)')

    print(f'\n{"═"*60}')
    print('  Smoke test complete.')
    print('═'*60)


if __name__ == '__main__':
    main()
