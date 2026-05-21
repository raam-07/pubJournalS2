import os
from pathlib import Path
from dotenv import load_dotenv

# Load local .env file if it exists (for local development)
load_dotenv()

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"

# Ensure necessary directories exist
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Google Sheets Configuration
SOURCE_SPREADSHEET = os.getenv("SOURCE_SPREADSHEET_NAME", "News Scraper Sources")
SOURCE_WORKSHEET = os.getenv("SOURCE_WORKSHEET_NAME", "Articles")

DEST_SPREADSHEET = os.getenv("DEST_SPREADSHEET_NAME", "News Scraper Entities")
DEST_WORKSHEET = os.getenv("DEST_WORKSHEET_NAME", "Entities")

# Google Credentials JSON string or filepath
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

# Pipeline Configuration
SPACY_MODEL = os.getenv("SPACY_MODEL", "en_core_web_sm")
LOOKBACK_ROWS = int(os.getenv("LOOKBACK_ROWS", "2000"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "100"))

# Retry limits for Google Sheets API requests
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "5"))
BACKOFF_FACTOR = float(os.getenv("BACKOFF_FACTOR", "2.0"))
INITIAL_DELAY = float(os.getenv("INITIAL_DELAY", "1.0"))

# Logging Configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = LOGS_DIR / "pipeline.log"
