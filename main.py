# scrape_jobyaari.py
import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
from time import sleep

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9"
}

CATEGORIES = {
    "Engineering": "https://jobyaari.com/category/engineering?type=graduate",
    "Science":     "https://jobyaari.com/category/science?type=graduate",
    "Commerce":    "https://jobyaari.com/category/commerce?type=graduate",
    "Education":   "https://jobyaari.com/category/education?type=graduate",
}

def parse_listing_text(text):
    """Heuristic parser for the listing page text dump."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    jobs = []
    i = 0
    while i < len(lines) - 2:
        # On JobYaari listing pages titles often appear twice in a row:
        # e.g. Title \n Title \n Organization \n Unlock Now \n salary/experience ...
        if lines[i] == lines[i+1]:
            title = lines[i]
            org = lines[i+2] if i+2 < len(lines) else ""
            # look ahead for the salary / experience / qualification / location
            salary = ""
            experience = ""
            qualification = ""
            location = ""
            for offset in range(3, 12):  # small sliding window
                if i + offset < len(lines):
                    la = lines[i + offset]
                    # heuristic: salary/exp line usually contains 'Fresher' or 'Years' or a number/currency
                    if ('Fresher' in la) or ('Years' in la) or ('₹' in la) or re.search(r'\d{3,6}', la):
                        # parse salary
                        m = re.search(r'₹\s*[\d,]+(?:\s*-\s*₹?[\d,]+)?', la)
                        if m:
                            salary = m.group(0)
                        else:
                            m2 = re.search(r'(\d{3,6}(?:\s*-\s*\d{3,6})?)', la)
                            if m2:
                                salary = m2.group(1)
                        if 'Fresher' in la:
                            experience = 'Fresher'
                        elif re.search(r'\d+\+?\s*Years', la):
                            expm = re.search(r'(\d+\+?\s*Years)', la)
                            experience = expm.group(1) if expm else ''

                        # qualification and location are often next couple of lines
                        if i + offset + 1 < len(lines):
                            qualification = lines[i + offset + 1]
                        if i + offset + 2 < len(lines):
                            location = lines[i + offset + 2]
                        break

            jobs.append({
                "Title": title,
                "Organization": org,
                "Salary": salary,
                "Experience": experience,
                "Qualification": qualification,
                "Location": location
            })
            # jump forward a bit (avoid re-detecting same block)
            i += 3
        else:
            i += 1
    return jobs

def scrape_category(url):
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"Failed to fetch {url} (status {r.status_code})")
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(separator="\n")
    return parse_listing_text(text)

def main():
    all_jobs = []
    for cat, url in CATEGORIES.items():
        print("Fetching", cat, url)
        try:
            jobs = scrape_category(url)
        except Exception as e:
            print("ERROR fetching", url, e)
            continue
        for j in jobs:
            j["Category"] = cat
        print(f"  -> found {len(jobs)} job(s) in {cat}")
        all_jobs.extend(jobs)
        sleep(1)  # polite

    df = pd.DataFrame(all_jobs)
    df.drop_duplicates(inplace=True)
    csv_path = "jobyaari_jobs.csv"
    df.to_csv(csv_path, index=False)
    print("Saved:", csv_path, "rows:", len(df))
    if not df.empty:
        print(df.head(10).to_markdown())

if __name__ == "__main__":
    main()
