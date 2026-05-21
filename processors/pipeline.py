import time
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any
from config import settings
from utils.google_sheets import GoogleSheetsConnector
from processors.normalizer import Normalizer
from processors.entity_extractor import EntityExtractor

logger = logging.getLogger(__name__)

class Pipeline:
    def __init__(self):
        self.sheets = GoogleSheetsConnector()
        self.normalizer = Normalizer()
        self.extractor = EntityExtractor(self.normalizer)

    def run(self) -> Dict[str, Any]:
        """
        Orchestrates the entire incremental entity extraction pipeline:
        1. Establishes Google Sheets connections.
        2. Fetches recently processed article IDs from destination lookback window.
        3. Retrieves all articles from source sheet.
        4. Filters out duplicate IDs.
        5. Extracts, normalizes, and packages entity results in batches.
        6. Batch-writes outputs as single-cell JSON strings.
        7. Returns detailed execution metrics.
        """
        start_time = time.time()
        
        logger.info("Initializing Entity Extraction Pipeline Job...")
        self.sheets.open_sheets()
        
        # 1. Fetch processed IDs cache
        processed_ids = self.sheets.get_processed_ids()
        
        # 2. Fetch all articles from source
        source_articles = self.sheets.get_source_articles()
        
        # 3. Filter new articles
        new_articles = []
        for article in source_articles:
            art_id = str(article["article_id"])
            if art_id not in processed_ids:
                new_articles.append(article)
                
        total_retrieved = len(source_articles)
        total_new = len(new_articles)
        total_skipped = total_retrieved - total_new
        
        # Apply MAX_ARTICLES_PER_RUN cap to restrict maximum items processed in a single execution
        max_limit = settings.MAX_ARTICLES_PER_RUN
        capped = False
        if total_new > max_limit:
            logger.info(
                f"New articles found ({total_new}) exceeds MAX_ARTICLES_PER_RUN limit ({max_limit}). "
                f"Capping this run to the first {max_limit} articles. Rest of backlog will catch up in subsequent runs."
            )
            new_articles = new_articles[:max_limit]
            total_new = len(new_articles)
            capped = True
            
        logger.info(
            f"Pipeline Scan Complete. Total Source Articles: {total_retrieved} | "
            f"Already Processed (Skipped): {total_skipped} | "
            f"New to Process (Capped={capped}): {total_new}"
        )
        
        metrics = {
            "job_started_at": datetime.now(timezone.utc).isoformat() + "Z",
            "total_source_articles": total_retrieved,
            "skipped_already_processed": total_skipped,
            "new_articles_found": total_new,
            "successfully_processed": 0,
            "failed_processing": 0,
            "job_duration_seconds": 0.0
        }
        
        if total_new == 0:
            logger.info("No new articles to process. Pipeline shutting down successfully.")
            metrics["job_duration_seconds"] = round(time.time() - start_time, 2)
            return metrics
            
        # 4. Batch-wise Processing Loop
        batch_size = settings.BATCH_SIZE
        for i in range(0, total_new, batch_size):
            batch_articles = new_articles[i:i + batch_size]
            batch_json_rows = []
            
            logger.info(f"Processing Batch {i//batch_size + 1} ({len(batch_articles)} articles)...")
            
            for article in batch_articles:
                art_id_str = article["article_id"]
                title = article["title"]
                summary = article["summary"]
                content = article["content"]
                published_at = article["published_at"]
                source = article["source"]
                url = article["url"]
                
                try:
                    # Cast integer IDs cleanly to preserve native types
                    try:
                        article_id = int(art_id_str) if art_id_str.isdigit() else art_id_str
                    except Exception:
                        article_id = art_id_str
                        
                    # Perform spaCy NER + Dictionary Match + Normalize
                    entities = self.extractor.extract_entities(title, summary, content)
                    
                    # Package structured output JSON payload
                    # Preserves: article_id, published_at, processed_at, source, url, title, entities
                    payload = {
                        "article_id": article_id,
                        "published_at": published_at,
                        "processed_at": datetime.now(timezone.utc).isoformat() + "Z",
                        "title": title,
                        "source": source,
                        "url": url,
                        "people": entities["people"],
                        "political_parties": entities["political_parties"],
                        "countries": entities["countries"],
                        "states": entities["states"],
                        "cities": entities["cities"],
                        "organizations": entities["organizations"],
                        "topics": entities["topics"]
                    }
                    
                    # Serialize to raw string
                    serialized = json.dumps(payload, ensure_ascii=False)
                    batch_json_rows.append(serialized)
                    metrics["successfully_processed"] += 1
                    
                except Exception as e:
                    logger.error(f"Failed to extract entities for Article ID {art_id_str}: {e}", exc_info=True)
                    metrics["failed_processing"] += 1
                    
            # 5. Push batch output to destination sheet in one transaction
            if batch_json_rows:
                logger.info(f"Pushing Batch {i//batch_size + 1} results to destination Google Sheet...")
                self.sheets.push_extraction_results(batch_json_rows)
                
        metrics["job_duration_seconds"] = round(time.time() - start_time, 2)
        logger.info(
            f"Pipeline Job Completed! Successful: {metrics['successfully_processed']} | "
            f"Failed: {metrics['failed_processing']} | "
            f"Duration: {metrics['job_duration_seconds']}s"
        )
        return metrics
