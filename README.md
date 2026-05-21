# Public Ledger - Entity Extraction Intelligence Pipeline

A lightweight, production-grade, and highly reliable Python-based entity extraction pipeline. Built as an autonomous intelligence layer for background news processing, it runs incrementally via GitHub Actions, reading processed articles from a source Google Sheet, extracting/normalizing contextual political entities, and pushing structured JSON results to a single-column destination Google Sheet.

---

## ─── Architecture & Data Flow ───

```
  Source Google Sheet (Articles)
              │
              ▼
   gspread Connector (Dual-Auth) ── [Check LOOKBACK_ROWS (2,000) in Dest]
              │
              ├──► Skip Already Processed IDs (Incremental processing)
              ▼
     New Articles Batching (Size: 100)
              │
              ▼
    Entity Extraction Engine (spaCy en_core_web_sm)
              │
              ├──► default spaCy Named Entity Recognition (NER)
              ├──► custom Word-Bounded Dictionary Matching
              └──► lightweight Keyword Topic Mapping (Step 1)
              │
              ▼
    Normalization & Resolution Engine
              │
              ├──► Title/Honorific Stripping (e.g. "PM Modi" -> "Modi")
              ├──► Canonical Alias Translation (e.g. "bjp" -> "Bharatiya Janata Party")
              └──► Dynamic Contextual Resolution (e.g. "Rahul" -> "Rahul Gandhi" in scope)
              │
              ▼
    Output JSON Payload Construction
              │
              ▼
  Destination Google Sheet (Single JSON Column)
```

---

## ─── Codebase Structure ───

The codebase is organized in a highly modular, clean, and extensible structure:

```
Public_ledger/Step2/
├── .github/
│   └── workflows/
│       └── entity_pipeline.yml  # GitHub Actions automated workflow (Hourly Cron)
├── config/
│   ├── __init__.py
│   └── settings.py              # Central settings, logging & env loading
├── data/
│   ├── abbreviations.json       # General political/administrative abbreviations
│   ├── cities.json              # Indian metropolitan capitals & historical names
│   ├── countries.json           # Geopolitical country lists
│   ├── ministries.json          # Indian central government ministries & shorthand
│   ├── parties.json             # Indian political parties & aliases
│   ├── politicians.json         # Indian politicians & comprehensive aliases
│   ├── states.json              # Indian states/union territories & variations
│   └── topics.json              # Curated keyword lists for lightweight topics (Step 1)
├── logs/
│   └── pipeline.log             # Persisted local rotating log trace
├── processors/
│   ├── __init__.py
│   ├── entity_extractor.py      # spaCy NER + Dictionary matcher + Topic mapping
│   ├── normalizer.py            # Honorific strip, mapping lookups, Contextual Resolver
│   └── pipeline.py              # Incremental orchestrator & batch loop
├── utils/
│   ├── __init__.py
│   ├── google_sheets.py         # Resilient gspread driver & row parsers
│   └── helpers.py               # Rate-limit exponential backoff retry decorator
├── tests/
│   └── test_pipeline.py         # Zero-dependency local unit test suite
├── main.py                      # CLI runner and entrypoint
├── requirements.txt             # Project library dependencies
└── README.md                    # System documentation
```

---

## ─── Core Engineering Highlights ───

### 1. Memory-Safe Sliding Window Cache
To prevent memory leaks and API request size explosions as your database grows to tens of thousands of rows, the connector **never loads or parses the entire sheet**. Instead, it retrieves only the last `LOOKBACK_ROWS` (default: 2,000) rows from the destination sheet, parses their JSON values, and extracts `article_id` keys to build our processed cache. Since the hourly scrapers run sequentially, a 2,000-article lookback is more than sufficient.

### 2. Dynamic Article-Scoped Contextual Resolver
To prevent a fragmented knowledge graph caused by short references (e.g. `"Modi"`, `"Rahul"`, or `"Kejriwal"`), the engine dynamically resolves partial mentions *within the scope of a single article*. If `"Rahul Gandhi"` appears in the article text, any standalone `"Rahul"` is automatically normalized to `"Rahul Gandhi"`. If there is no specific anchor, it falls back to global dictionaries or preserves the clean name.

### 3. Word-Bounded Dictionary Augmentation
Standard spaCy NER frequently misses Indian names, political acronyms, and ministries. The extractor compiles the custom JSON dictionaries into highly efficient, word-bounded (`\b`), case-insensitive regex patterns and matches them sequentially (longest aliases first) to capture missing items cleanly.

### 4. Exponential Backoff Rate-Limit Resiliency
Google Sheets free-tier API quotas are strictly limited. Every Sheets API call is wrapped in a custom `@google_api_retry` decorator. If a `429 Too Many Requests` or `RESOURCE_EXHAUSTED` error is encountered, the pipeline pauses, applies an exponential delay with random jitter (to prevent collision herds), and transparently retries.

---

## ─── Environment Setup ───

### Local Installation
1. Clone your repository locally.
2. Navigate to the pipeline workspace:
   ```bash
   cd Public_ledger/Step2
   ```
3. Initialize a virtual environment and activate it:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
4. Install the required libraries:
   ```bash
   pip install -r requirements.txt
   ```
5. Download the spaCy language model:
   ```bash
   python3 -m spacy download en_core_web_sm
   ```

---

## ─── Google Sheets & Google Cloud Setup ───

To connect the pipeline to your Google Sheets, you need to set up a service account:

### Step 1: Create a Google Cloud Project & Credentials
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g., `Public Ledger Intelligence`).
3. Search for the **Google Sheets API** and click **Enable**.
4. Search for the **Google Drive API** and click **Enable**.
5. Navigate to **APIs & Services** > **Credentials**.
6. Click **Create Credentials** and select **Service Account**.
7. Provide a name and click **Create**. You don't need to specify roles.
8. Locate your newly created Service Account under the credentials list and click the edit pencil icon.
9. Navigate to the **Keys** tab, click **Add Key** > **Create New Key**, and select **JSON**.
10. A JSON file will automatically download to your computer.
    * For **Local Dev**: Save this file in the `Public_ledger/Step2` folder and rename it to `credentials.json` (ensure `.gitignore` includes it).
    * For **Production**: Keep this file handy to add as a GitHub Action secret.

### Step 2: Share Google Sheets with the Service Account
1. Open the JSON credentials file and find the `"client_email"` key (it will look like `your-service-account@your-project.iam.gserviceaccount.com`).
2. Open your **Source Google Sheet** (containing raw articles).
3. Click the blue **Share** button in the top right.
4. Paste the service account email, assign **Viewer** access, and click Share.
5. Open your **Destination Google Sheet** (dedicated for JSON entities).
6. Share it with the same service account email, assign **Editor** access, and click Share.

---

## ─── Production Deployment via GitHub Actions ───

To automate the background runs, commit this codebase to your repository and configure secrets.

### GitHub Secrets Configuration
Navigate to your GitHub repository > **Settings** > **Secrets and variables** > **Actions** and add the following secrets:

| Secret Name | Value Example | Description |
| :--- | :--- | :--- |
| `GOOGLE_CREDENTIALS` | `{"type": "service_account", ...}` | The entire contents of your downloaded Service Account JSON keyfile. |
| `SOURCE_SPREADSHEET_NAME` | `News Scraper Sources` | Name of the spreadsheet holding the scraped articles. |
| `SOURCE_WORKSHEET_NAME` | `Articles` | Worksheet tab name for source rows. |
| `DEST_SPREADSHEET_NAME` | `News Scraper Entities` | Name of the spreadsheet to append extractions to. |
| `DEST_WORKSHEET_NAME` | `Entities` | Worksheet tab name where single-column JSON strings are pushed. |

The GitHub Action is scheduled to run at the **top of every hour** automatically, caching dependencies to run in under 45 seconds on average.

---

## ─── Running Local Unit Tests ───

To verify normalization, mapping lookups, and sheets parsing without hitting any Google Sheets API quota limits, run the test suite:

```bash
python3 -m unittest tests/test_pipeline.py
```
