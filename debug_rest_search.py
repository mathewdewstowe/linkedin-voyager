"""Test legacy REST search endpoints for LinkedIn post search."""
import sys, json
sys.path.insert(0, '/Users/matthew_dewstowe/Chome Plugin + LinkedIn MCP/linkedin-mcp-skills/linked-voyager')
from browser import LinkedInBrowser
from urllib.parse import quote

def try_rest(br, name, url, use_json=True):
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"URL: {url[:150]}")

    # Make request using page.evaluate with application/json header
    result = br._page.evaluate('''async ({url, useJson}) => {
        const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
        const token = m ? m[1] : "";
        const accept = useJson ? "application/json" : "application/vnd.linkedin.normalized+json+2.1";
        try {
            const r = await fetch(url, {
                headers: {
                    "csrf-token": token,
                    "accept": accept,
                    "x-restli-protocol-version": "2.0.0",
                    "x-li-lang": "en_US",
                    "x-li-track": '{"clientVersion":"1.0","osName":"web","timezoneOffset":0,"timezone":"Europe/London","deviceFormFactor":"DESKTOP","mpName":"voyager-web"}'
                },
                credentials: "include"
            });
            const text = await r.text();
            return {status: r.status, body: text.substring(0, 3000), size: text.length};
        } catch(e) {
            return {error: e.message};
        }
    }''', {'url': url, 'useJson': use_json})

    print(f"  Status: {result.get('status', 'ERROR')}")
    print(f"  Size: {result.get('size', 0)} bytes")
    if 'error' in result:
        print(f"  Error: {result['error']}")
        return None

    body = result.get('body', '')
    try:
        d = json.loads(body) if body else {}
    except:
        d = {}
        print(f"  Raw (not JSON): {body[:200]}")
        return None

    included = d.get('included', d.get('elements', []))
    print(f"  included/elements: {len(included) if isinstance(included, list) else 'N/A'}")
    if isinstance(included, list) and included:
        types = {}
        for i in included:
            if isinstance(i, dict):
                t = i.get('$type', i.get('type', 'NONE'))
                types[t] = types.get(t, 0) + 1
        print(f"  Types: {json.dumps(types)}")
        print(f"  First item keys: {list(included[0].keys())[:15]}")

    # Check paging
    paging = d.get('paging', {})
    if paging:
        print(f"  Paging: total={paging.get('total')}, count={paging.get('count')}")

    return d

q = quote('interim', safe='')

with LinkedInBrowser(headless=True) as br:
    import time

    # Test 1: Legacy blended search
    try_rest(br, "blended/CONTENT",
        f"https://www.linkedin.com/voyager/api/search/blended?count=10&filters=List(resultType-%3ECONTENT)&keywords={q}&origin=GLOBAL_SEARCH_HEADER&q=blended")
    time.sleep(2)

    # Test 2: blended with sortBy
    try_rest(br, "blended/CONTENT sortBy date",
        f"https://www.linkedin.com/voyager/api/search/blended?count=10&filters=List(resultType-%3ECONTENT,timePosted-%3Epast-24h)&keywords={q}&origin=GLOBAL_SEARCH_HEADER&q=blended&sortBy=date_posted")
    time.sleep(2)

    # Test 3: search/hits
    try_rest(br, "search/hits CONTENT",
        f"https://www.linkedin.com/voyager/api/search/hits?count=10&filters=List(resultType-%3ECONTENT)&keywords={q}&q=filter")
    time.sleep(2)

    # Test 4: search/cluster
    try_rest(br, "search/cluster CONTENT",
        f"https://www.linkedin.com/voyager/api/search/cluster?count=10&filters=List(resultType-%3ECONTENT)&keywords={q}&origin=GLOBAL_SEARCH_HEADER&q=seoUrl")
    time.sleep(2)

    # Test 5: graphql with application/json
    variables = f'(query:(keywords:{q},flagshipSearchIntent:SEARCH_SRP,queryParameters:List((key:resultType,value:List(CONTENT))),includeFiltersInResponse:false),start:0,count:10)'
    try_rest(br, "graphql b0928897 app/json",
        f"https://www.linkedin.com/voyager/api/graphql?queryId=voyagerSearchDashClusters.b0928897b71bd00a5a7291755dcd64f0&variables={variables}",
        use_json=True)
