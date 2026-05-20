#!/usr/bin/env python3
"""
Pass 2 (v2) — Enrich leads using voyager_get_profile_current_company.
Uses the positionGroups Voyager endpoint — correct title/company, no DOM parsing.
Re-enriches ALL Voyager leads regardless of previous state.
"""
import sys, sqlite3
from datetime import datetime, timezone

sys.path.insert(0, "/Users/matthew_dewstowe/Chome Plugin + LinkedIn MCP/linkedin-mcp-skills/linked-voyager")
from browser import LinkedInBrowser

DB_PATH = "/Users/matthew_dewstowe/Documents/claude-cli/data/job_apply.db"
SOURCE = "voyager_search_2026-05-20"


def now_utc():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def get_website(br, company_slug: str) -> str:
    if not company_slug:
        return ""
    result = br._voyager_fetch(
        f"https://www.linkedin.com/voyager/api/organization/companies"
        f"?decorationId=com.linkedin.voyager.deco.organization.web.WebFullCompanyMain-12"
        f"&q=universalName&universalName={company_slug}"
    )
    if not result:
        return ""
    for item in result.get("included", []):
        if "organization.Company" in item.get("$type", ""):
            return (
                item.get("companyPageUrl")
                or (item.get("callToAction") or {}).get("url", "")
                or ""
            )
    return ""


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")

    leads = conn.execute("""
        SELECT id, name, linkedin_url, region, title_searched
        FROM leads
        WHERE deleted_at IS NULL AND source_file = ?
        ORDER BY region, title_searched, id
    """, (SOURCE,)).fetchall()

    total = len(leads)
    done = skipped = errors = 0
    print(f"Re-enriching {total} leads via positionGroups Voyager endpoint...\n")

    with LinkedInBrowser(headless=True) as br:
        br._ensure_linkedin_page()
        print(f"Session OK. Starting...\n")

        for i, (lead_id, name, linkedin_url, region, title_searched) in enumerate(leads, 1):
            pct = i / total * 100
            try:
                result = br.voyager_get_profile_current_company(linkedin_url)

                if result.get("error") or not result.get("job_title"):
                    skipped += 1
                    print(f"  [{i}/{total} {pct:.0f}%] {name} — {result.get('error','no data')}")
                    continue

                # Get website via Voyager company API
                website = get_website(br, result.get("company_slug", ""))

                conn.execute("""
                    UPDATE leads SET
                        job_title       = ?,
                        company         = ?,
                        company_website = ?,
                        employee_count  = ?,
                        sector          = ?,
                        outreach_status = CASE WHEN outreach_status = 'new' THEN 'enriched' ELSE outreach_status END
                    WHERE id = ?
                """, (
                    result["job_title"],
                    result["company_name"],
                    website,
                    result.get("employee_count", ""),
                    result.get("industry", ""),
                    lead_id,
                ))
                conn.commit()
                done += 1

                print(
                    f"  [{i}/{total} {pct:.0f}%] [{region}] {name} | "
                    f"{result['job_title'][:35]} @ {result['company_name'][:30]} | "
                    f"{website[:40]} | {result.get('industry','')[:25]}"
                )

            except Exception as e:
                errors += 1
                print(f"  [{i}/{total} {pct:.0f}%] ERROR {name}: {e}")

    conn.close()
    print(f"\n{'='*60}")
    print(f"Done: {done} | Skipped: {skipped} | Errors: {errors} | Total: {total}")


if __name__ == "__main__":
    main()
