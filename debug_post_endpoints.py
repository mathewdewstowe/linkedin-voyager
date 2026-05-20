"""Test different LinkedIn post search endpoints."""
import sys, json
sys.path.insert(0, '/Users/matthew_dewstowe/Chome Plugin + LinkedIn MCP/linkedin-mcp-skills/linked-voyager')
from browser import LinkedInBrowser
from urllib.parse import quote

def try_endpoint(br, name, url):
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"URL: {url[:100]}")
    d = br._voyager_fetch(url)
    if not d:
        print("  -> NO RESPONSE")
        return
    size = len(json.dumps(d))
    print(f"  -> Response size: {size} bytes")
    print(f"  -> Top keys: {list(d.keys())}")
    included = d.get('included', [])
    print(f"  -> Included count: {len(included)}")
    if included:
        types = {}
        for i in included:
            t = i.get('$type', 'NONE')
            types[t] = types.get(t, 0) + 1
        print(f"  -> Types: {types}")
        # Show first item
        print(f"  -> First item sample: {json.dumps(included[0], default=str)[:400]}")
    elements = d.get('elements', [])
    if elements:
        print(f"  -> elements: {len(elements)}, first keys: {list(elements[0].keys())[:10]}")
    data_section = d.get('data', {})
    if data_section:
        print(f"  -> data keys: {list(data_section.keys())[:10]}")

query = "interim"
q = quote(query, safe='')

with LinkedInBrowser(headless=True) as br:
    # Endpoint 1: legacy blended search
    try_endpoint(br, "blended REST",
        f"https://www.linkedin.com/voyager/api/search/blended?count=10&filters=List(resultType-%3ECONTENT)&keywords={q}&origin=GLOBAL_SEARCH_HEADER&q=blended")

    import time; time.sleep(2)

    # Endpoint 2: hits REST
    try_endpoint(br, "hits REST",
        f"https://www.linkedin.com/voyager/api/search/hits?count=10&filters=List(resultType-%3ECONTENT)&keywords={q}&q=filter")

    time.sleep(2)

    # Endpoint 3: cluster REST
    try_endpoint(br, "cluster REST",
        f"https://www.linkedin.com/voyager/api/search/cluster?count=10&filters=List(resultType-%3ECONTENT)&keywords={q}&origin=GLOBAL_SEARCH_HEADER&q=seoUrl")

    time.sleep(2)

    # Endpoint 4: voyager feed search
    try_endpoint(br, "feed search",
        f"https://www.linkedin.com/voyager/api/feed/updatesV2?q=search&keywords={q}&count=10")

    time.sleep(2)

    # Endpoint 5: different graphql query
    variables5 = f'(keywords:{q},origin:GLOBAL_SEARCH_HEADER)'
    try_endpoint(br, "search graphql v2",
        f"https://www.linkedin.com/voyager/api/graphql?queryId=voyagerSearchDashClusters.b0928897b71bd00a5a7291755dcd64f0&variables=(query:(keywords:{q},flagshipSearchIntent:SEARCH_SRP,queryParameters:List((key:resultType,value:List(CONTENT))),includeFiltersInResponse:false),start:0,count:10)")
