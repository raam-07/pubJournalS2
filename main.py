import sys
import logging
from logging.handlers import RotatingFileHandler
from config import settings
from processors.pipeline import Pipeline

def setup_logging():
    """
    Initializes structured dual-channel logging:
    1. Console Handler: Standard stdout logs for GitHub Actions.
    2. File Handler: Persists logs in logs/pipeline.log (auto-rotating) for local auditing.
    """
    # Create directory if it doesn't exist
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    
    # Check if level is string or int
    level_val = settings.LOG_LEVEL.upper()
    numeric_level = getattr(logging, level_val, logging.INFO)
    root_logger.setLevel(numeric_level)
    
    # Clear existing handlers
    if root_logger.handlers:
        root_logger.handlers.clear()
        
    log_format = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s [%(name)s:%(lineno)d] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Console Handler (Stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    console_handler.setLevel(numeric_level)
    root_logger.addHandler(console_handler)
    
    # Rotating File Handler
    try:
        file_handler = RotatingFileHandler(
            filename=settings.LOG_FILE,
            maxBytes=5 * 1024 * 1024, # 5MB rotating file
            backupCount=3,
            encoding="utf-8"
        )
        file_handler.setFormatter(log_format)
        file_handler.setLevel(numeric_level)
        root_logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Failed to initialize file logging handler: {e}")

def print_banner():
    """
    Prints a professional, premium startup banner to stdout.
    """
    banner = """
============================================================
       PUBLIC LEDGER - ENTITY EXTRACTION INTELLIGENCE
                      Version 1.0.0
============================================================
Autonomous Background Pipeline for News Processing
    - spaCy NER Augmentation
    - High-Precision Political Dictionaries
    - Dynamic Contextual Normalization
    - Resilient Google Sheets Integration
============================================================
"""
    print(banner)

def main():
    setup_logging()
    logger = logging.getLogger("main")
    
    print_banner()
    
    try:
        pipeline = Pipeline()
        metrics = pipeline.run()
        
        # Print a clean, readable final job report to console
        print("\n" + "=" * 40)
        print("           PIPELINE RUN REPORT")
        print("=" * 40)
        print(f"Job Started At:      {metrics['job_started_at']}")
        print(f"Total Source Rows:   {metrics['total_source_articles']}")
        print(f"Skipped (Processed): {metrics['skipped_already_processed']}")
        print(f"New Articles Found:  {metrics['new_articles_found']}")
        print(f"Successfully Extracted: {metrics['successfully_processed']}")
        print(f"Failed Extracted:    {metrics['failed_processing']}")
        print(f"Job Duration:        {metrics['job_duration_seconds']}s")
        print("=" * 40 + "\n")
        
        # If any article failed, exit with warning but clean status unless everything failed
        if metrics["failed_processing"] > 0 and metrics["successfully_processed"] == 0:
            logger.error("Job completed with 100% extraction failures. Exiting with error.")
            sys.exit(1)
            
        sys.exit(0)
        
    except Exception as e:
        logger.critical(f"Critical System Failure in pipeline execution: {e}", exc_info=True)
        print(f"\n[CRITICAL FAILURE] Pipeline aborted: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
