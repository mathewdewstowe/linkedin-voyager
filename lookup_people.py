"""Quick lookup: get first LinkedIn result for each name."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

# Force matthew profile (direct HTTP, no Playwright)
os.environ['LI_PROFILE'] = 'matthew'

from browser import LinkedInBrowser

names = [
    "Colleen Barraclough",
    "Ruth McGuinness",
    "Jessica Brooks",
    "Chris Wirt",
    "Jane Serra",
    "Carter Baldwin",
    "Ross Eaton",
    "Andy Wyschna",
    "Barbara Kovacs",
    "Sergei Mak",
    "Terry Bustamante",
    "David Bernstein",
    "Barry Quinn",
    "Sam Rowlands",
    "Nick Alkins",
    "Gordon Duff",
]

results = []

with LinkedInBrowser() as br:
    for name in names:
        print(f"\nSearching: {name}...", flush=True)
        try:
            people = br.voyager_search_people(
                query=name,
                count=1,          # just the top result
                page_size=49,
                delay_between_pages=0,
            )
            if people:
                p = people[0]
                result = f"{name} | {p['name']} | {p.get('headline','--')} | {p.get('profile_url','')}"
                print(f"  RESULT: {result}", flush=True)
                results.append(result)
            else:
                result = f"{name} | NOT FOUND"
                print(f"  {result}", flush=True)
                results.append(result)
        except Exception as e:
            result = f"{name} | ERROR: {e}"
            print(f"  {result}", flush=True)
            results.append(result)

print("\n\n=== FINAL RESULTS ===")
for r in results:
    print(r)
