#!/usr/bin/env python3
"""
Pass 1 — LinkedIn Voyager people search.
Runs each job title separately across UK + US.
Writes raw leads to data/job_apply.db leads table.
Deduplicates by linkedin_url.
"""
import sys, sqlite3
from datetime import datetime, timezone

sys.path.insert(0, "/Users/matthew_dewstowe/Chome Plugin + LinkedIn MCP/linkedin-mcp-skills/linked-voyager")
from browser import LinkedInBrowser

DB_PATH = "/Users/matthew_dewstowe/Documents/claude-cli/data/job_apply.db"
SOURCE = "voyager_search_2026-05-20"

TITLES = [
    # Block 1 — Executive Leadership
    "CEO",
    "Managing Director",
    "President",
    "Chief Operating Officer",
    # Block 2 — Revenue/Sales Leadership
    "Chief Revenue Officer",
    "VP Sales",
    "Head of Sales",
    # Block 3 — Technology Leadership
    "Chief Technology Officer",
    "VP Engineering",
    "Head of Technology",
    # Block 4 — Product Leadership
    "Chief Product Officer",
    "Head of Product",
    # Block 5 — Founder/Executive
    "Founder",
    "Co-Founder",
    "Executive Director",
]

REGIONS = [
    ("United Kingdom", "UK"),
    ("United States", "US"),
]

INDUSTRY = "Staffing and Recruiting"


def now_utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title_searched TEXT,
            region TEXT,
            name TEXT,
            job_title TEXT,
            company TEXT,
            company_website TEXT,
            employee_count TEXT,
            sector TEXT,
            person_headline TEXT,
            location TEXT,
            linkedin_url TEXT UNIQUE,
            source_file TEXT,
            imported_at TEXT DEFAULT (datetime('now','utc')),
            outreach_status TEXT DEFAULT 'new',
            deleted_at TEXT
        )
    """)
    conn.commit()


def insert_lead(conn, row: dict) -> bool:
    try:
        cur = conn.execute("""
            INSERT OR IGNORE INTO leads
            (title_searched, region, name, person_headline, location, linkedin_url, source_file, imported_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (
            row["title_searched"], row["region"], row["name"],
            row["headline"], row["location"], row["linkedin_url"],
            SOURCE, now_utc(),
        ))
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        print(f"    DB error for {row.get('name')}: {e}")
        return False


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    ensure_schema(conn)

    total_found = 0
    total_inserted = 0
    total_dupes = 0

    grand_summary = []

    with LinkedInBrowser(headless=True) as br:
        for location_name, region_code in REGIONS:
            region_found = 0
            region_inserted = 0
            print(f"\n{'='*60}")
            print(f"REGION: {region_code} ({location_name})")
            print(f"{'='*60}")

            for title in TITLES:
                print(f"\n  [{region_code}] Searching: \"{title}\"")
                try:
                    people = br.voyager_search_people(
                        query="",
                        title=title,
                        first_degree_only=False,
                        location=location_name,
                        industry=INDUSTRY,
                        count=500,
                    )
                except Exception as e:
                    print(f"    ERROR: {e}")
                    people = []

                inserted = dupes = 0
                for p in people:
                    row = {
                        "title_searched": title,
                        "region": region_code,
                        "name": p.get("name", ""),
                        "headline": p.get("headline", ""),
                        "location": p.get("location", ""),
                        "linkedin_url": p.get("profile_url", ""),
                    }
                    if insert_lead(conn, row):
                        inserted += 1
                    else:
                        dupes += 1

                region_found += len(people)
                region_inserted += inserted
                total_dupes += dupes
                print(f"    Found: {len(people):>4}  |  New: {inserted:>4}  |  Dupes: {dupes:>3}")

            total_found += region_found
            total_inserted += region_inserted
            grand_summary.append((region_code, region_found, region_inserted))
            print(f"\n  {region_code} subtotal — Found: {region_found}  New: {region_inserted}")

    conn.close()

    print(f"\n{'='*60}")
    print("FINAL SUMMARY")
    print(f"{'='*60}")
    for region_code, found, inserted in grand_summary:
        print(f"  {region_code}: {found} found, {inserted} new leads written")
    print(f"  Dupes skipped: {total_dupes}")
    print(f"  TOTAL new leads: {total_inserted}")
    db_count = sqlite3.connect(DB_PATH).execute(
        "SELECT COUNT(*) FROM leads WHERE deleted_at IS NULL AND source_file=?", (SOURCE,)
    ).fetchone()[0]
    print(f"  DB total (this run): {db_count}")


if __name__ == "__main__":
    main()
