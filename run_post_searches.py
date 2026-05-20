"""Run all post searches in a single Brave/Playwright session."""
import sys, json
sys.path.insert(0, '/Users/matthew_dewstowe/Chome Plugin + LinkedIn MCP/linkedin-mcp-skills/linked-voyager')
from browser import LinkedInBrowser
from urllib.parse import quote

SEARCHES = [
    "interim",
    "fractional",
    "product director",
    "head of product",
    "product manager",
    "vp product",
    "chief product officer",
]

def search_posts(br, query, count=20):
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
    d = br._voyager_fetch(url)
    if not d:
        return []

    inner = d.get('data', {}).get('data', {})
    clusters_data = inner.get('searchDashClustersByAll', {})
    total = clusters_data.get('paging', {}).get('total', 0)
    elements = clusters_data.get('elements', [])

    posts = []
    for el in elements:
        for it in el.get('items', []):
            entity = (it.get('item') or {}).get('entityResult')
            if not entity:
                continue
            title_obj    = entity.get('title') or {}
            subtitle_obj = entity.get('primarySubtitle') or {}
            summary_obj  = entity.get('summary') or {}
            nav_url      = (entity.get('navigationContext') or {}).get('url', '') or entity.get('navigationUrl', '')
            author_name  = title_obj.get('text', '')
            author_hl    = subtitle_obj.get('text', '')
            snippet      = summary_obj.get('text', '') if isinstance(summary_obj, dict) else ''
            post_url     = nav_url if nav_url.startswith('http') else f'https://www.linkedin.com{nav_url}'
            if not author_name:
                continue
            posts.append({
                'author_name':     author_name,
                'author_headline': author_hl,
                'post_url':        post_url,
                'text_snippet':    snippet[:500],
            })
            if len(posts) >= count:
                return posts, total
    return posts, total

results = {}
with LinkedInBrowser(headless=True) as br:
    import time
    for query in SEARCHES:
        posts, total = search_posts(br, query)
        results[query] = {'total': total, 'posts': posts}
        print(f"[DONE] {query!r}: {total} total, {len(posts)} returned", flush=True)
        time.sleep(3)

print("\n=== FULL RESULTS ===")
print(json.dumps(results, indent=2))
