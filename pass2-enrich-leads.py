#!/usr/bin/env python3
"""
Pass 2 — Enrich leads with current role + company data.
For each lead from voyager_search_2026-05-20:
  1. Navigate to /details/experience/ -> current title + company name
  2. Get company numeric ID from DOM
  3. Voyager company API -> website, employee size, sector
  4. Fallback: company /about/ page -> website, employee size, sector
Writes back to leads table. Skips already-enriched rows. Safe to resume.
Brave + profile (matthew@sonesse.ai).
"""
from __future__ import annotations
import re, sqlite3, sys
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
PROFILE_DIR = "/Users/matthew_dewstowe/.brave-paginator/profile"
DB_PATH = "/Users/matthew_dewstowe/Documents/claude-cli/data/job_apply.db"
SOURCE = "voyager_search_2026-05-20"

TENURE_RE = re.compile(r"^\d+\s+(?:yr|mo|month|year)", re.I)
DATE_WITH_PRESENT_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}.*Present", re.I
)
EMPLOYMENT_TYPES = {
    "full-time", "part-time", "self-employed", "freelance",
    "contract", "internship", "seasonal", "temporary", "permanent",
}


def public_id_from_url(url):
    m = re.search(r"/in/([^/?#]+)", url or "")
    return m.group(1).rstrip("/") if m else None


def parse_experience(text):
    idx = text.find("Experience")
    if idx < 0:
        return {}
    lines = [l.strip() for l in text[idx + len("Experience"):].splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if not DATE_WITH_PRESENT_RE.search(line):
            continue
        j = i - 1
        while j >= 0 and lines[j].lower() in EMPLOYMENT_TYPES:
            j -= 1
        if j < 0:
            continue
        candidate = lines[j]
        if " . " in candidate or " · " in candidate:
            company = re.split(r" [.·] ", candidate)[0].strip()
            ti = j - 1
            while ti >= 0 and lines[ti].lower() in EMPLOYMENT_TYPES:
                ti -= 1
            title = lines[ti] if ti >= 0 else ""
        else:
            title = candidate
            k = j - 1
            while k >= 0 and TENURE_RE.match(lines[k]):
                k -= 1
            company = lines[k] if k >= 0 else ""
        if company and title and company.lower() != "experience":
            return {"title": title, "company": company, "date_range": line}
        break
    return {}


def get_company_id(page):
    dom = page.content()
    for m in re.finditer(r"Present", dom):
        ctx = dom[max(0, m.start() - 2500): m.start() + 200]
        ids = re.findall(r"/company/([0-9]+)/", ctx)
        if ids:
            return ids[-1]
    return None


def voyager_company(page, slug):
    return page.evaluate("""async (slug) => {
        const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
        const csrf = m ? m[1] : "";
        const r = await fetch(
            "https://www.linkedin.com/voyager/api/organization/companies"
            + "?decorationId=com.linkedin.voyager.deco.organization.web.WebFullCompanyMain-12"
            + "&q=universalName&universalName=" + encodeURIComponent(slug),
            {credentials:"include", headers:{
                "csrf-token":csrf,
                "accept":"application/vnd.linkedin.normalized+json+2.1",
                "x-restli-protocol-version":"2.0.0"
            }}
        );
        return {status: r.status, body: await r.json()};
    }""", slug)


def extract_voyager_company(result, search_name):
    included = result.get("body", {}).get("included", [])
    co = next((i for i in included if "organization.Company" in i.get("$type", "")), None)
    if not co:
        return {}
    ind_map = {i.get("entityUrn", ""): i.get("localizedName") or i.get("name", "")
               for i in included if "common.Industry" in i.get("$type", "")}
    returned = set(re.sub(r"[^a-z ]", "", co.get("name", "").lower()).split())
    searched = set(re.sub(r"[^a-z ]", "", search_name.lower()).split())
    if not (returned & searched - {"the", "and", "of", "a", "in", "plc", "ltd"}):
        return {}
    website = co.get("companyPageUrl") or (co.get("callToAction") or {}).get("url", "")
    sr = co.get("staffCountRange") or {}
    size = f"{sr.get('start','')}-{sr.get('end','')}" if sr else str(co.get("staffCount", "") or "")
    sector = next((ind_map.get(u, "") for u in (co.get("*companyIndustries") or [])
                   if ind_map.get(u)), "")
    return {"website": website, "employee_size": size, "sector": sector}


def slugify(name):
    raw = name.strip().lower()
    a = re.sub(r"\s+", "-", re.sub(r"[^a-z0-9 -]", "", raw.replace("&", "and"))).strip("-")
    h = re.sub(r"\s+", "-", re.sub(r"[^a-z0-9 -]", "", raw.replace("&", " "))).strip("-")
    cands = [a, h]
    for base in [a, h]:
        for sfx in ["-plc", "-group"]:
            if not base.endswith(sfx):
                cands.append(base + sfx)
        for sfx in ["-plc", "-ltd", "-group"]:
            if base.endswith(sfx):
                cands.append(base[:-len(sfx)])
    return list(dict.fromkeys(c for c in cands if c))


def parse_about(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    result = {}
    for i, line in enumerate(lines):
        if line == "Website" and i + 1 < len(lines) and lines[i + 1].startswith("http"):
            result["website"] = lines[i + 1]
        elif line == "Industry" and i + 1 < len(lines):
            result["sector"] = lines[i + 1]
        elif line == "Company size" and i + 1 < len(lines):
            result["employee_size"] = lines[i + 1]
    if not result.get("employee_size"):
        for line in lines[:30]:
            m = re.search(r"(\d[\d,KkMm\-]+)\s+employees?", line)
            if m:
                result["employee_size"] = m.group(0)
                break
    return result


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    leads = conn.execute("""
        SELECT id, name, linkedin_url, region, title_searched
        FROM leads WHERE deleted_at IS NULL AND source_file=?
        AND (job_title IS NULL OR job_title = '')
        ORDER BY region, title_searched, id
    """, (SOURCE,)).fetchall()

    total = len(leads)
    print(f"Leads to enrich: {total}\n")
    done = skipped = errors = 0

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR, executable_path=BRAVE_PATH,
            headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        for extra in browser.pages[1:]:
            extra.close()

        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        print(f"Session OK. Starting...\n")

        for i, (lead_id, name, linkedin_url, region, title_searched) in enumerate(leads, 1):
            pid = public_id_from_url(linkedin_url)
            pct = i / total * 100
            try:
                page.goto(f"https://www.linkedin.com/in/{pid}/details/experience/",
                          wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)
                exp = parse_experience(page.evaluate("() => document.body.innerText"))
                company_id = get_company_id(page)
                if not exp:
                    skipped += 1
                    print(f"  [{i}/{total} {pct:.0f}%] {name} — no experience found")
                    continue
                co = {}
                for slug in slugify(exp["company"]):
                    r = voyager_company(page, slug)
                    if r.get("status") == 200:
                        info = extract_voyager_company(r, exp["company"])
                        if info:
                            co = info
                            break
                if not co and company_id:
                    page.goto(f"https://www.linkedin.com/company/{company_id}/about/",
                              wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)
                    co = parse_about(page.evaluate("() => document.body.innerText"))
                conn.execute("""UPDATE leads SET job_title=?, company=?, company_website=?,
                    employee_count=?, sector=?,
                    outreach_status=CASE WHEN outreach_status='new' THEN 'enriched' ELSE outreach_status END
                    WHERE id=?""",
                    (exp.get("title",""), exp.get("company",""), co.get("website",""),
                     co.get("employee_size",""), co.get("sector",""), lead_id))
                conn.commit()
                done += 1
                print(f"  [{i}/{total} {pct:.0f}%] [{region}] {name} | "
                      f"{exp['title'][:35]} @ {exp['company'][:30]} | "
                      f"{co.get('website','')[:40]} | {co.get('sector','')[:25]}")
            except Exception as e:
                errors += 1
                print(f"  [{i}/{total} {pct:.0f}%] ERROR {name}: {e}")
                try:
                    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
            page.wait_for_timeout(1200)
        browser.close()
    conn.close()
    print(f"\nDone: {done} | Skipped: {skipped} | Errors: {errors}")

if __name__ == "__main__":
    main()
