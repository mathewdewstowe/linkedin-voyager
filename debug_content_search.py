"""Debug content search response structure."""
import sys, json
sys.path.insert(0, '/Users/matthew_dewstowe/Chome Plugin + LinkedIn MCP/linkedin-mcp-skills/linked-voyager')
from browser import LinkedInBrowser
from urllib.parse import quote

query = "interim"
variables = f'(query:(keywords:{quote(query, safe="")},flagshipSearchIntent:SEARCH_SRP,queryParameters:List((key:resultType,value:List(CONTENT))),includeFiltersInResponse:false),start:0,count:10)'
url = 'https://www.linkedin.com/voyager/api/graphql?queryId=voyagerSearchDashClusters.b0928897b71bd00a5a7291755dcd64f0&variables=' + variables

with LinkedInBrowser(headless=True) as br:
    d = br._voyager_fetch(url)

# Save full response for analysis
with open('/tmp/li_content_search.json', 'w') as f:
    json.dump(d, f, indent=2)
print("Saved to /tmp/li_content_search.json")

included = d.get('included', [])
print(f"\nIncluded count: {len(included)}")
for i, item in enumerate(included[:5]):
    print(f"  [{i}] type={item.get('$type','?')} urn={item.get('entityUrn','?')[:80]}")

clusters = d.get('data', {}).get('data', {}).get('searchDashClustersByAll', {})
elements = clusters.get('elements', [])
print(f"\nElements: {len(elements)}")

# Element 1 (the main results cluster) — dump ALL keys including star-refs
el1 = elements[1] if len(elements) > 1 else {}
items1 = el1.get('items', [])
print(f"Element[1] items: {len(items1)}")
for ii, it in enumerate(items1[:3]):
    print(f"\n  --- Item {ii} ---")
    # Print ALL keys at top level
    for k, v in it.items():
        if v is not None:
            print(f"    {k}: {str(v)[:200]}")
    # Recurse into 'item'
    item_inner = it.get('item') or {}
    print(f"  item_inner keys: {list(item_inner.keys())}")
    for k, v in item_inner.items():
        if v is not None:
            print(f"    item.{k}: {str(v)[:200]}")
