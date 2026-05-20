#!/usr/bin/env python3
"""
Lead enrichment test — 3 leads.
Step 1: Experience page innerText → current role + company name + company numeric ID.
Step 2a: Voyager company API (by universalName slug) — fast path.
Step 2b: Navigate company/about page → innerText → website, size, sector — reliable fallback.
Brave + profile-matthew (matthew@sonesse.ai).
"""
from __future__ import annotations
import re, sqlite3, sys
from playwright.sync_api import sync_playwright

BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
PROFILE_DIR = "/Users/matthew_dewstowe/.brave-paginator/profile-matthew"
DB_PATH = "/Users/matthew_dewstowe/Documents/claude-cli/data/job_apply.db"
TEST_LIMIT = 3

TENURE_RE = re.compile(r"^\d+\s+(?:yr|mo|month|year)", re.I)
DATE_WITH_PRESENT_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}.*Present", re.I
)
EMPLOYMENT_TYPES = {
    "full-time", "part-time", "self-employed", "freelance",
    "contract", "internship", "seasonal", "temporary", "permanent",
}


def public_id_from_url(url: str) -> str | None:
    m = re.search(r"/in/([^/?#]+)", url or "")
    return m.group(1).rstrip("/") if m else None


def parse_experience_text(text: str) -> dict:
    """Extract current role from LinkedIn experience page innerText."""
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
        if " · " in candidate:
            # Format B: "Company · EmploymentType" — title is above
            company = candidate.split(" · ")[0].strip()
            ti = j - 1
            while ti >= 0 and lines[ti].lower() in EMPLOYMENT_TYPES:
                ti -= 1
            title = lines[ti] if ti >= 0 else ""
        else:
            # Format A: candidate is title, company is above (after optional tenure)
            title = candidate
            k = j - 1
            while k >= 0 and TENURE_RE.match(lines[k]):
                k -= 1
            company = lines[k] if k >= 0 else ""
        if company and title and company.lower() != "experience":
            return {"title": title, "company": company, "date_range": line}
        break
    return {}


def get_company_id_from_dom(page) -> str | None:
    """Extract the LinkedIn company numeric ID from the experience page DOM near 'Present'."""
    dom = page.content()
    for m in re.finditer(r"Present", dom):
        ctx = dom[max(0, m.start() - 2500): m.start() + 200]
        ids = re.findall(r"/company/([0-9]+)/", ctx)
        if ids:
            return ids[-1]
    return None


def parse_company_about_text(text: str) -> dict:
    """
    Parse LinkedIn company /about page innerText.
    Extracts: website, employee_size, sector.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    result = {}

    for i, line in enumerate(lines):
        if line == "Website" and i + 1 < len(lines):
            url = lines[i + 1].strip()
            if url.startswith("http"):
                result["website"] = url
        elif line == "Industry" and i + 1 < len(lines):
            result["sector"] = lines[i + 1]
        elif line == "Company size" and i + 1 < len(lines):
            result["employee_size"] = lines[i + 1]

    # Header fallback: "NNK-NNK employees" or "N,NNN-N,NNN employees"
    if not result.get("employee_size"):
        for line in lines[:30]:
            m = re.search(r"(\d[\d,.KkMm\-]+)\s+employees?", line)
            if m:
                result["employee_size"] = m.group(0)
                break

    return result


def slugify_company(name: str) -> list[str]:
    """Generate Voyager universalName slug candidates."""
    raw = name.strip().lower()
    base_and = re.sub(r"[^a-z0-9 -]", "", raw.replace("&", "and"))
    base_and = re.sub(r"\s+", "-", base_and.strip()).strip("-")
    base_hyp = re.sub(r"[^a-z0-9 -]", "", raw.replace("&", " "))
    base_hyp = re.sub(r"\s+", "-", base_hyp.strip()).strip("-")

    candidates = [base_and, base_hyp]
    for base in [base_and, base_hyp]:
        for sfx in ["-plc", "-group"]:
            if not base.endswith(sfx):
                candidates.append(base + sfx)
        for sfx in ["-plc", "-ltd", "-group", "-llc"]:
            if base.endswith(sfx):
                candidates.append(base[: -len(sfx)])
    return list(dict.fromkeys(c for c in candidates if c))


def voyager_company(page, slug: str) -> dict:
    return page.evaluate("""async (slug) => {
        const m = document.cookie.match(/JSESSIONID="?([^";]+)"?/);
        const csrf = m ? m[1] : "";
        const r = await fetch(
            "https://www.linkedin.com/voyager/api/organization/companies"
            + "?decorationId=com.linkedin.voyager.deco.organization.web.WebFullCompanyMain-12"
            + "&q=universalName&universalName=" + encodeURIComponent(slug),
            {credentials:"include", headers:{"csrf-token":csrf,
             "accept":"application/vnd.linkedin.normalized+json+2.1",
             "x-restli-protocol-version":"2.0.0"}}
        );
        return {status: r.status, body: await r.json()};
    }""", slug)


def extract_company_info_voyager(result: dict, search_name: str) -> dict:
    """Parse Voyager company response and validate name matches."""
    included = result.get("body", {}).get("included", [])
    company_item = None
    industry_map = {}
    for item in included:
        t = item.get("$type", "")
        if "organization.Company" in t:
            company_item = item
        elif "common.Industry" in t:
            industry_map[item.get("entityUrn", "")] = (
                item.get("localizedName") or item.get("name", "")
            )
    if not company_item:
        return {}

    # Name validation
    returned = re.sub(r"[^a-z ]", "", company_item.get("name", "").lower()).split()
    searched = re.sub(r"[^a-z ]", "", search_name.lower()).split()
    stop = {"the", "and", "of", "a", "in", "plc", "ltd", "llc", "inc"}
    if not (set(returned) & set(searched) - stop):
        return {}

    website = (
        company_item.get("companyPageUrl")
        or (company_item.get("callToAction") or {}).get("url", "")
    )
    staff_range = company_item.get("staffCountRange")
    if staff_range and isinstance(staff_range, dict):
        size = f"{staff_range.get('start','')}-{staff_range.get('end','')}"
    else:
        size = str(company_item.get("staffCount", "") or "")
    sector = ""
    for urn in (company_item.get("*companyIndustries") or []):
        sector = industry_map.get(urn, "")
        if sector:
            break
    return {
        "name": company_item.get("name", ""),
        "website": website,
        "employee_size": size,
        "sector": sector,
        "source": "voyager",
    }


def main():
    conn = sqlite3.connect(DB_PATH)
    leads = conn.execute(
        "SELECT id, name, linkedin_url FROM leads WHERE deleted_at IS NULL LIMIT ?",
        (TEST_LIMIT,)
    ).fetchall()

    print(f"Testing {len(leads)} leads...\n")

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            executable_path=BRAVE_PATH,
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        page = browser.pages[0] if browser.pages else browser.new_page()
        for extra in browser.pages[1:]:
            extra.close()

        print("Warming up session...")
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        if "authwall" in page.url or "login" in page.url:
            print("ERROR: Not logged in.")
            browser.close()
            sys.exit(1)
        print(f"Session OK. URL: {page.url}\n")

        for lead_id, name, linkedin_url in leads:
            print(f"=== {name} ===")
            pid = public_id_from_url(linkedin_url)

            # Step 1: experience page → current role
            page.goto(
                f"https://www.linkedin.com/in/{pid}/details/experience/",
                wait_until="domcontentloaded", timeout=30000,
            )
            page.wait_for_timeout(5000)

            exp = parse_experience_text(page.evaluate("() => document.body.innerText"))
            company_id = get_company_id_from_dom(page)

            if not exp:
                print(f"  No experience data extracted.")
                print()
                continue

            print(f"  Title:      {exp['title']}")
            print(f"  Company:    {exp['company']}")
            print(f"  Period:     {exp['date_range']}")
            print(f"  Company ID: {company_id}")

            co_info = {}

            # Step 2a: Voyager fast-path
            for slug in slugify_company(exp["company"]):
                r = voyager_company(page, slug)
                if r.get("status") == 200:
                    info = extract_company_info_voyager(r, exp["company"])
                    if info:
                        co_info = info
                        print(f"  [Voyager] slug={slug}")
                        break

            # Step 2b: Company page body text fallback
            if not co_info and company_id:
                about_url = f"https://www.linkedin.com/company/{company_id}/about/"
                page.goto(about_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)

                # Canonical URL slug from redirect
                final_url = page.url
                m = re.search(r"/company/([^/?#]+)/", final_url)
                canonical_slug = m.group(1) if m else None

                about_text = page.evaluate("() => document.body.innerText")
                co_info = parse_company_about_text(about_text)
                co_info["source"] = f"page:{canonical_slug}"

            if co_info:
                print(f"  Source:       {co_info.get('source', '?')}")
                print(f"  Website:      {co_info.get('website', 'n/a')}")
                print(f"  Size:         {co_info.get('employee_size', 'n/a')}")
                print(f"  Sector:       {co_info.get('sector', 'n/a')}")
            else:
                print(f"  Company data not found.")

            print()
            page.wait_for_timeout(1000)

        browser.close()
    conn.close()
    print("Test complete.")


if __name__ == "__main__":
    main()
