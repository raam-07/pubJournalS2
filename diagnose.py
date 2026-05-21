import os
import json
from dotenv import load_dotenv
from utils.google_sheets import GoogleSheetsConnector

def main():
    load_dotenv()
    print("Initializing Google Sheets Connector...")
    connector = GoogleSheetsConnector()
    print("Opening spreadsheets...")
    connector.open_sheets()
    
    sheet = connector.source_sheet
    if not sheet:
        print("Error: Source sheet could not be opened.")
        return
        
    print(f"Reading records from worksheet '{sheet.title}'...")
    records = sheet.get_all_records()
    total = len(records)
    print(f"Total records retrieved: {total}")
    
    if total == 0:
        print("The worksheet is completely empty.")
        return
        
    print("\n--- Columns (Headers) in sheet ---")
    first_record = records[0]
    print(list(first_record.keys()))
    
    print("\n--- First 5 Records ---")
    for i in range(min(5, total)):
        print(f"\nRow {i+2}:")
        rec = records[i]
        # Print non-empty columns
        non_empty = {k: v for k, v in rec.items() if str(v).strip() != ""}
        if non_empty:
            print(json.dumps(non_empty, indent=2, ensure_ascii=False))
        else:
            print("[Completely Empty Row]")

if __name__ == "__main__":
    main()
