import json
import logging
from typing import Dict, List, Set, Any, Optional
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from config import settings
from utils.helpers import google_api_retry

logger = logging.getLogger(__name__)

class GoogleSheetsConnector:
    def __init__(self):
        self.client = None
        self.source_sheet = None
        self.dest_sheet = None
        self.authenticate()

    def authenticate(self):
        """
        Performs dual-auth:
        1. Checks for GOOGLE_CREDENTIALS env var containing service account JSON string.
        2. Falls back to loading GOOGLE_CREDENTIALS_FILE path.
        """
        scopes = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
        
        try:
            if settings.GOOGLE_CREDENTIALS_JSON:
                logger.info("Authenticating via GOOGLE_CREDENTIALS environment variable...")
                creds_dict = json.loads(settings.GOOGLE_CREDENTIALS_JSON)
                # Supports modern gspread service_account_from_dict or oauth2client fallback
                try:
                    self.client = gspread.service_account_from_dict(creds_dict)
                except AttributeError:
                    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scopes)
                    self.client = gspread.authorize(creds)
            else:
                logger.info(f"Authenticating via credentials file: {settings.GOOGLE_CREDENTIALS_FILE}...")
                self.client = gspread.service_account(filename=settings.GOOGLE_CREDENTIALS_FILE)
                
            logger.info("Successfully authenticated with Google Sheets API.")
        except Exception as e:
            logger.error(f"Authentication failed: {e}")
            raise

    @google_api_retry(max_retries=settings.MAX_RETRIES, initial_delay=settings.INITIAL_DELAY, backoff_factor=settings.BACKOFF_FACTOR)
    def open_sheets(self):
        """
        Opens source and destination spreadsheets and worksheets.
        """
        try:
            logger.info(f"Opening source: Spreadsheet '{settings.SOURCE_SPREADSHEET}', Worksheet '{settings.SOURCE_WORKSHEET}'")
            source_ss = self.client.open(settings.SOURCE_SPREADSHEET)
            self.source_sheet = source_ss.worksheet(settings.SOURCE_WORKSHEET)
            
            logger.info(f"Opening destination: Spreadsheet '{settings.DEST_SPREADSHEET}', Worksheet '{settings.DEST_WORKSHEET}'")
            dest_ss = self.client.open(settings.DEST_SPREADSHEET)
            self.dest_sheet = dest_ss.worksheet(settings.DEST_WORKSHEET)
        except Exception as e:
            logger.error(f"Failed to open spreadsheets/worksheets: {e}")
            raise

    @google_api_retry(max_retries=settings.MAX_RETRIES, initial_delay=settings.INITIAL_DELAY, backoff_factor=settings.BACKOFF_FACTOR)
    def get_processed_ids(self) -> Set[str]:
        """
        Reads the destination sheet (single column of JSON strings).
        To prevent memory and API response size issues, it only parses the last LOOKBACK_ROWS items 
        to populate our processed IDs cache.
        """
        processed_ids = set()
        if not self.dest_sheet:
            return processed_ids
            
        try:
            logger.info(f"Fetching processed IDs from destination sheet with lookback limit: {settings.LOOKBACK_ROWS}")
            # Fetch all values in the first column
            all_rows = self.dest_sheet.col_values(1)
            
            if not all_rows:
                logger.info("Destination sheet is empty.")
                return processed_ids
                
            # If the first row is a header, skip it if present, but since it's just JSON strings, 
            # we slice the last LOOKBACK_ROWS.
            lookback_rows = all_rows[-settings.LOOKBACK_ROWS:]
            
            for idx, cell_val in enumerate(lookback_rows):
                if not cell_val or cell_val.strip() == "" or cell_val.lower() == "json" or cell_val.lower() == "extraction json":
                    continue
                try:
                    data = json.loads(cell_val)
                    art_id = data.get("article_id")
                    if art_id is not None:
                        processed_ids.add(str(art_id))
                except json.JSONDecodeError:
                    # Ignore rows that aren't valid JSON (e.g. headers or manual text)
                    continue
                    
            logger.info(f"Loaded {len(processed_ids)} processed article IDs from destination sliding window.")
            return processed_ids
        except Exception as e:
            logger.error(f"Error fetching processed IDs: {e}")
            raise

    @google_api_retry(max_retries=settings.MAX_RETRIES, initial_delay=settings.INITIAL_DELAY, backoff_factor=settings.BACKOFF_FACTOR)
    def get_source_articles(self) -> List[Dict[str, Any]]:
        """
        Reads all articles from the source Google Sheet.
        Parses rows, supporting direct columns or a single JSON column layout.
        """
        articles = []
        if not self.source_sheet:
            return articles
            
        try:
            logger.info("Fetching articles from source sheet...")
            # Retrieve all rows as records (maps column header -> value)
            records = self.source_sheet.get_all_records()
            logger.info(f"Retrieved {len(records)} total records from source sheet.")
            
            for idx, record in enumerate(records):
                parsed = self.parse_source_record(record, idx + 2) # +2 for 1-based index and header
                if parsed:
                    articles.append(parsed)
                    
            if len(records) > 0 and len(articles) == 0:
                # Log detailed diagnostics for automatic auditing in GitHub Actions workflow
                logger.warning("=" * 70)
                logger.warning("             AUTOMATED PIPELINE DATA DIAGNOSTIC REPORT")
                logger.warning("=" * 70)
                logger.warning(f"Total raw records retrieved: {len(records)}")
                logger.warning(f"Successfully parsed articles: 0 (all rows were empty or missing matching keys)")
                
                # Print parsed headers
                first_record = records[0]
                headers = list(first_record.keys())
                logger.warning(f"Detected Sheet Column Headers: {headers}")
                
                # Inspect the first 5 records for debugging
                logger.warning("--- First 5 Records Sample Analysis ---")
                for i in range(min(5, len(records))):
                    rec = records[i]
                    non_empty = {k: v for k, v in rec.items() if str(v).strip() != ""}
                    if non_empty:
                        logger.warning(f"Row {i+2} non-empty fields: {json.dumps(non_empty, ensure_ascii=False)}")
                    else:
                        logger.warning(f"Row {i+2}: [Completely Empty Grid Row]")
                logger.warning("=" * 70)
                
            return articles
        except Exception as e:
            logger.error(f"Error retrieving source articles: {e}")
            raise

    def parse_source_record(self, record: Dict[str, Any], row_num: int) -> Optional[Dict[str, Any]]:
        """
        Helper that parses a single row record from the source sheet.
        Supports:
        - A single column named 'json' or 'article' containing the serialized JSON string.
        - Robust fallback: search for any column containing a valid JSON object string.
        - Multiple columns matching 'id' / 'article_id', 'title', 'summary' / 'description',
          'content' / 'body', 'published_at', 'source', 'url'.
        """
        if not record or not isinstance(record, dict):
            return None

        # Check if record is completely empty (all values are empty strings, None, or just whitespace)
        is_empty = all(val is None or str(val).strip() == "" for val in record.values())
        if is_empty:
            return None

        # 1. Search for a JSON string column first
        json_col_keys = [k for k in record.keys() if k.lower() in ["json", "article", "article_json"]]
        if not json_col_keys:
            # Fallback: search for any column containing a valid JSON object string
            for k, v in record.items():
                if isinstance(v, str) and v.strip().startswith("{") and v.strip().endswith("}"):
                    json_col_keys.append(k)
                    break

        if json_col_keys:
            json_str = record[json_col_keys[0]]
            if json_str and str(json_str).strip() != "":
                try:
                    data = json.loads(json_str)
                    return self.extract_fields_from_dict(data, row_num)
                except json.JSONDecodeError:
                    logger.warning(f"Row {row_num}: JSON column matched but contains invalid JSON string. Falling back to columns.")

        # 2. Extract fields directly from row columns
        return self.extract_fields_from_dict(record, row_num)

    def extract_fields_from_dict(self, d: Dict[str, Any], row_num: int) -> Optional[Dict[str, Any]]:
        """
        Extracts expected fields from a dictionary (whether parsed JSON or columns).
        Normalizes keys efficiently up-front to minimize repeated regex/dictionary iterations.
        """
        if not d or not isinstance(d, dict):
            return None

        # Check if d is completely empty
        is_empty = all(val is None or str(val).strip() == "" for val in d.values())
        if is_empty:
            return None

        import re
        # Construct pre-normalized key dictionary for O(1) case-insensitive lookups
        norm_d = {}
        for k, v in d.items():
            norm_k = re.sub(r"[\s_\-]", "", k.lower())
            norm_d[norm_k] = v

        # Universal ID Mapping (identifies fields representing ID)
        id_keys = ["id", "articleid", "uid", "uuid", "key"]
        article_id = None
        for k in id_keys:
            if k in norm_d and norm_d[k] is not None and str(norm_d[k]).strip() != "":
                article_id = str(norm_d[k]).strip()
                break
                
        # Helper to extract case-insensitive and symbol-agnostic fields
        def get_field(keys: List[str], default: str = "") -> str:
            for k in keys:
                k_norm = re.sub(r"[\s_\-]", "", k.lower())
                if k_norm in norm_d and norm_d[k_norm] is not None and str(norm_d[k_norm]).strip() != "":
                    return str(norm_d[k_norm]).strip()
            return default

        title = get_field(["title", "headline", "subject"])
        summary = get_field(["summary", "description", "excerpt", "rephrase", "summary_text"])
        content = get_field(["content", "body", "text", "article_body"])
        published_at = get_field(["published_at", "published", "date", "created_at"])
        source = get_field(["source", "publisher", "rss_source"])
        url = get_field(["url", "link", "source_url"])

        if article_id is None:
            # Check if there is any meaningful text content in the row
            has_content = any(val != "" for val in [title, summary, content, url])
            if has_content:
                logger.warning(
                    f"Row {row_num}: Skipping because it contains content "
                    f"(title: '{title[:30]}...', url: '{url[:30]}...') "
                    f"but no valid ID field ('id', 'article_id') was found."
                )
            return None

        # Fallback: if published_at is empty, use processed_at or general empty string
        # If content is empty, use summary
        if not content and summary:
            content = summary
            
        return {
            "article_id": article_id,
            "title": title,
            "summary": summary,
            "content": content,
            "published_at": published_at,
            "source": source,
            "url": url
        }

    @google_api_retry(max_retries=settings.MAX_RETRIES, initial_delay=settings.INITIAL_DELAY, backoff_factor=settings.BACKOFF_FACTOR)
    def push_extraction_results(self, json_rows: List[str]):
        """
        Appends newly extracted entity payloads (JSON strings) as single-column rows 
        into the destination sheet in a single batch call.
        """
        if not self.dest_sheet or not json_rows:
            return
            
        try:
            logger.info(f"Appending batch of {len(json_rows)} entity records to destination Google Sheet...")
            # We must wrap each JSON string inside a list to represent a single cell in a row
            rows_to_append = [[row] for row in json_rows]
            
            # gspread's append_rows performs a highly optimized batch append in one API call
            self.dest_sheet.append_rows(rows_to_append, value_input_option="RAW")
            logger.info("Batch push completed successfully.")
        except Exception as e:
            logger.error(f"Error appending batch to Google Sheets: {e}")
            raise
