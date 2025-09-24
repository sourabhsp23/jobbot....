


import streamlit as st
import pandas as pd
import re
from rapidfuzz import process, fuzz
from groq import Groq


import os
import subprocess
import sys

# Delete and regenerate data file
if os.path.exists("jobyaari_jobs.csv"):
    os.remove("jobyaari_jobs.csv")
    print("🗑️ Deleted old data file")

print("🚀 Generating fresh data...")
try:
    if os.path.exists("main.py"):
        result = subprocess.run([sys.executable, "main.py"], check=True, timeout=120)
        print("✅ New data generated successfully!")
    else:
        print("❌ main.py not found")
except Exception as e:
    print(f"❌ Error: {e}")
# -------------------------------------------------
# 2️⃣  CONFIGURATION
# -------------------------------------------------
# 👉  Replace with your own Groq API key or set the env‑var GROQ_API_KEY
GROQ_API_KEY =  "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"
# Number of results we ask the LLM to consider
TOP_K_SEARCH = 20          # how many rows we pull from fuzzy search
TOP_K_FINAL  = 5           # how many of those we actually send to the LLM

# -------------------------------------------------
# 3️⃣  LOAD & PRE‑PROCESS DATA (cached)
# -------------------------------------------------
@st.cache_data(show_spinner=False)
def load_data() -> pd.DataFrame:
    df = pd.read_csv("jobyaari_jobs.csv")
    # Strip any stray spaces in column names
    df.columns = df.columns.str.strip()
    return df

df = load_data()

# -------------------------------------------------
# 4️⃣  Helper – turn a row into a single readable string
# -------------------------------------------------
def row_to_text(row: pd.Series) -> str:
    return (
        f"{row['Title']} at {row['Organization']} | "
        f"Salary: {row['Salary']} | Exp: {row['Experience']} | "
        f"Qualification: {row['Qualification']} | "
        f"Location: {row['Location']} | Category: {row['Category']}"
    )

# -------------------------------------------------
# 5️⃣  Parse simple filters from the user query
# -------------------------------------------------
def parse_filters(query: str) -> dict:
    """
    Very lightweight regex‑based parser.
    Recognises:
        - salary > 30000
        - experience level (fresher, entry, junior, mid, senior)
        - location “… in Delhi”, “… in Bangalore”, etc.
    Extend as needed.
    """
    salary_match   = re.search(r"salary\s*>\s*([0-9,]+)", query, re.I)
    exp_match      = re.search(r"\b(fresher|entry|junior|mid|senior)\b", query, re.I)
    location_match = re.search(r"in\s+([A-Za-z\s]+)", query, re.I)

    filters = {}
    if salary_match:
        filters["Salary"] = int(salary_match.group(1).replace(",", ""))
    if exp_match:
        filters["Experience"] = exp_match.group(1).lower()
    if location_match:
        filters["Location"] = location_match.group(1).strip()
    return filters

# -------------------------------------------------
# 6️⃣  Fuzzy / keyword search (RapidFuzz)
# -------------------------------------------------
def keyword_search(query: str, top_k: int = TOP_K_SEARCH) -> list[str]:
    """
    Returns a list of the raw text rows that best match the query.
    """
    choices = df.apply(row_to_text, axis=1).tolist()
    matches = process.extract(
        query,
        choices,
        scorer=fuzz.WRatio,   # good all‑round scorer
        limit=top_k,
    )
    # matches = [(text, score, idx), ...]
    return [m[0] for m in matches]

# -------------------------------------------------
# 7️⃣  Apply the numeric / categorical filters on the fuzzy hits
# -------------------------------------------------
def apply_structured_filters(rows_text: list[str], filters: dict) -> list[str]:
    """
    Takes the fuzzy‑matched text rows, maps them back to the original
    DataFrame rows, and then applies the parsed filters.
    Returns a list of text rows that survive the filtering.
    """
    # Map the text back to the original index (fast because the list is tiny)
    idx = [
        df.index[df.apply(row_to_text, axis=1) == txt][0]   # there is exactly one match
        for txt in rows_text
    ]
    sub = df.loc[idx].copy()

    # ---- Salary filter ----
    if "Salary" in filters:
        # Try to coerce Salary column to numeric (ignore errors)
        sub["SalaryNum"] = pd.to_numeric(sub["Salary"], errors="coerce")
        sub = sub[sub["SalaryNum"] > filters["Salary"]]

    # ---- Experience filter ----
    if "Experience" in filters:
        exp = filters["Experience"]
        # Simple contains‑check – you can replace with a richer mapping if needed
        sub = sub[sub["Experience"].str.lower().str.contains(exp, na=False)]

    # ---- Location filter ----
    if "Location" in filters:
        loc = filters["Location"].lower()
        sub = sub[sub["Location"].str.lower().str.contains(loc, na=False)]

    # Return the formatted strings again
    return sub.apply(row_to_text, axis=1).tolist()

# -------------------------------------------------
# 8️⃣  Initialise Groq client (cached)
# -------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_groq_client() -> Groq:
    return Groq(api_key=GROQ_API_KEY)

groq_client = get_groq_client()



# -------------------------------------------------
# 9️⃣  Build the prompt & call the LLM (humanoid style)
# -------------------------------------------------
def ask_chatbot(query: str) -> str:
    # 1️⃣  Get fuzzy hits
    fuzzy_hits = keyword_search(query, top_k=TOP_K_SEARCH)

    # 2️⃣  Parse filters
    filters = parse_filters(query)

    # 3️⃣  Apply filters (if any)
    if filters:
        filtered_hits = apply_structured_filters(fuzzy_hits, filters)
    else:
        filtered_hits = fuzzy_hits

    # 4️⃣  Take top results
    context_rows = filtered_hits[:TOP_K_FINAL]

    # Special handling for queries like "qualification" or "notifications"
    response_type = None
    if re.search(r"qualification|eligibility", query, re.I):
        response_type = "qualification"
    elif re.search(r"notification|latest", query, re.I):
        response_type = "notification"
    elif re.search(r"experience", query, re.I):
        response_type = "experience"

    # Prepare context for LLM
    context = "\n".join(context_rows) if context_rows else "No matching jobs found."

    # 5️⃣  Humanoid instruction prompt
    prompt = f"""
You are JobYaari, a friendly and helpful job-search assistant 🤖.
Your job is to read the job data below and respond to the user's query in a **natural, human-like tone**.

Rules:
- ONLY use the data in the context below.
- Speak conversationally, not like a machine.
- If multiple jobs match, list them clearly with bullet points.
- If the query is about qualifications, highlight the 'Qualification' part of matching jobs.
- If it's about notifications, say "Here are the latest notifications in XYZ…" and then show results.
- If it's about experience, focus on the 'Experience' column.
- If nothing matches, politely say no jobs are available right now.

Context (jobs):
{context}

User’s Question:
{query}
"""

    # 6️⃣  Call Groq (LLM just for rephrasing)
    response = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,   # a bit more creativity for human-like tone
        max_tokens=400,
    )

    return response.choices[0].message.content

# -------------------------------------------------
# 10️⃣  Streamlit UI
# -------------------------------------------------
st.set_page_config(page_title="JobYaari Chatbot", page_icon="🤖", layout="centered")
st.title("🤖 JobYaari AI Chatbot")
st.markdown(
    """
    Ask me about the latest jobs in **Engineering, Science, Commerce, Education**.  
    You can also add simple filters, e.g.:

    - `fresher engineering jobs with salary > 30000 in Delhi`  
    - `senior data analyst salary > 80000`  

    The bot will return a short natural‑language answer **and** the raw matching rows.
    """
)

# -----------------------------------------------------------------
# User input
# -----------------------------------------------------------------
query = st.text_input("💬 Your question:", placeholder="e.g. fresher engineering jobs with salary > 30000 in Bangalore")

if st.button("Search") and query:
    with st.spinner("🔎 Searching & generating answer…"):
        # 1️⃣  Get LLM answer
        answer = ask_chatbot(query)

        # 2️⃣  Show answer
        st.success("✅ Answer")
        st.write(answer)

        # 3️⃣  Show the raw matching rows (for transparency)
        st.info("🔎 Top matching jobs (raw rows)")
        matches = keyword_search(query, top_k=TOP_K_SEARCH)
        # Apply filters again just to display the same rows the LLM saw
        filters = parse_filters(query)
        if filters:
            matches = apply_structured_filters(matches, filters)
        for i, job in enumerate(matches[:TOP_K_FINAL], start=1):
            st.write(f"**{i}.** {job}")

# -----------------------------------------------------------------
# Optional: show the whole dataset (useful for debugging)
# -----------------------------------------------------------------
with st.expander("📊 Show full dataset (first 10 rows)"):
    st.dataframe(df.head(10))
       






