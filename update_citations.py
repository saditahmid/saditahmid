"""
update_citations.py
- Updates citation counts for existing papers in README.md
- Auto-detects and adds new papers where Mohammed Tahmid Hossain
  or Sabrina Masum Meem appear as authors
Run by the GitHub Actions workflow on a monthly schedule.
"""

import os
import re
import time
from scholarly import scholarly

SCHOLAR_ID = os.environ.get("SCHOLAR_ID", "-ThWYkwAAAAJ")

# If either of these names appears in a paper's authors, it's his paper
AUTHOR_TRIGGERS = [
    "mohammed tahmid hossain",
    "sabrina masum meem",
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def is_his_paper(pub: dict) -> bool:
    """Return True if any trigger author appears in the publication's author list."""
    authors_raw = pub.get("bib", {}).get("author", "")
    return any(trigger in authors_raw.lower() for trigger in AUTHOR_TRIGGERS)


def make_short_key(title: str) -> str:
    """Lowercase, strip punctuation, first 60 chars for dedup matching."""
    clean = re.sub(r"[^\w\s]", "", title.lower())
    return " ".join(clean.split())[:60]


def extract_existing_keys(content: str) -> set:
    """Parse README and return short keys for papers already in the table."""
    keys = set()
    section = re.search(r"## Publications.*?(?=\n## )", content, re.DOTALL)
    if not section:
        return keys
    for match in re.finditer(r"\[\*\*(.*?)\*\*", section.group()):
        keys.add(make_short_key(match.group(1)))
    return keys


def venue_string(pub: dict) -> str:
    bib = pub.get("bib", {})
    venue = bib.get("venue") or bib.get("journal") or bib.get("booktitle") or ""
    year  = bib.get("pub_year", "")
    return f"{venue} · {year}".strip(" .") if venue else str(year)


def paper_url(pub: dict) -> str:
    url = pub.get("pub_url") or ""
    if url:
        return url
    title   = pub.get("bib", {}).get("title", "")
    encoded = title.replace(" ", "+")
    return f"https://scholar.google.com/scholar?q={encoded}"


def build_new_row(pub: dict, row_num: int) -> str:
    title   = pub.get("bib", {}).get("title", "Untitled")
    cited   = pub.get("num_citations", 0)
    url     = paper_url(pub)
    venue   = venue_string(pub)
    cited_s = f"**{cited}**" if cited else "—"

    # Bold the first phrase (up to first colon or 6 words)
    words    = title.split()
    split_at = next((i for i, w in enumerate(words) if ":" in w), min(6, len(words)))
    bold_part = " ".join(words[:split_at])
    rest_part = " ".join(words[split_at:])
    display   = f"**{bold_part}** {rest_part}".strip() if rest_part else f"**{bold_part}**"

    return f"| {row_num} | [{display}]({url}) | {venue} | {cited_s} |"


# ── Core update functions ─────────────────────────────────────────────────────

def fetch_scholar_data(scholar_id: str):
    print(f"Fetching Google Scholar profile: {scholar_id}")
    author = scholarly.search_author_id(scholar_id)
    author = scholarly.fill(author, sections=["basics", "indices", "publications"])

    metrics = {
        "citations": author.get("citedby", 0),
        "h_index":   author.get("hindex", 0),
        "i10_index": author.get("i10index", 0),
    }

    publications = []
    for pub in author.get("publications", []):
        filled = scholarly.fill(pub)
        if is_his_paper(filled):
            publications.append(filled)
        time.sleep(1.5)

    print(f"Metrics   : {metrics}")
    print(f"His papers: {len(publications)}")
    return metrics, publications


def update_readme(metrics: dict, publications: list, readme_path: str = "README.md"):
    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    # ── 1. Update metric badges ───────────────────────────────────────────────
    content = re.sub(
        r'!\[Citations\]\(https://img\.shields\.io/badge/Citations-\d+-',
        f'![Citations](https://img.shields.io/badge/Citations-{metrics["citations"]}-',
        content
    )
    content = re.sub(
        r'!\[h-index\]\(https://img\.shields\.io/badge/h--index-\d+-',
        f'![h-index](https://img.shields.io/badge/h--index-{metrics["h_index"]}-',
        content
    )
    content = re.sub(
        r'!\[i10-index\]\(https://img\.shields\.io/badge/i10--index-\d+-',
        f'![i10-index](https://img.shields.io/badge/i10--index-{metrics["i10_index"]}-',
        content
    )

    # ── 2. Update existing citation counts ────────────────────────────────────
    pub_lookup = {make_short_key(p["bib"]["title"]): p.get("num_citations", 0)
                  for p in publications}

    def replace_cited_by(match):
        row = match.group(0)
        title_match = re.search(r"\[\*\*(.*?)\*\*", row)
        if not title_match:
            return row
        key = make_short_key(title_match.group(1))
        for pub_key, count in pub_lookup.items():
            if key[:40] in pub_key or pub_key[:40] in key:
                return re.sub(r'\|\s*(\*\*\d+\*\*|—)\s*\|$', f'| **{count}** |', row)
        return row

    content = re.sub(
        r'^\|.*?\|\s*(\*\*\d+\*\*|—)\s*\|$',
        replace_cited_by,
        content,
        flags=re.MULTILINE
    )

    # ── 3. Detect and insert NEW papers ───────────────────────────────────────
    existing_keys = extract_existing_keys(content)
    new_papers = []

    for pub in publications:
        title = pub.get("bib", {}).get("title", "")
        if not title:
            continue
        key = make_short_key(title)
        already_there = any(key[:40] in ek or ek[:40] in key for ek in existing_keys)
        if not already_there:
            new_papers.append(pub)
            print(f"  New paper detected: {title}")

    if new_papers:
        existing_rows = re.findall(r"^\| \d+", content, re.MULTILINE)
        next_num = len(existing_rows) + 1
        new_rows  = "\n".join(build_new_row(p, next_num + i) for i, p in enumerate(new_papers))

        # Append after the last row of the publications table
        table_section = re.search(r"(## Publications.*?)(\n---)", content, re.DOTALL)
        if table_section:
            insert_at = table_section.end(1)
            content   = content[:insert_at] + "\n" + new_rows + content[insert_at:]
            print(f"  Added {len(new_papers)} new paper(s) to README.")
    else:
        print("  No new papers found.")

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(content)

    print("README.md updated successfully.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        metrics, publications = fetch_scholar_data(SCHOLAR_ID)
        update_readme(metrics, publications)
    except Exception as e:
        print(f"Error: {e}")
        print("Skipping README update — will retry next scheduled run.")
        raise SystemExit(0)
