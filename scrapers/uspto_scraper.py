import os
import re
import time
import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

def scrape_uspto(page, primary_query, excel_filename, secondary_query=None, max_retries=3):
    print("\nLaunching browser for USPTO Trademark Search...")
    
    print("  -> Executing Primary USPTO Search (Exact Match)...")
    primary_df, p_raw = _run_single_search(page, primary_query, max_retries)

    secondary_df = pd.DataFrame()
    s_raw = 0
    if secondary_query:
        print("  -> Executing Secondary USPTO Search (Variations)...")
        secondary_df, s_raw = _run_single_search(page, secondary_query, max_retries)

    print("  -> Merging and Deduplicating USPTO Results...")
    combined_df = pd.concat([primary_df, secondary_df], ignore_index=True)

    if combined_df.empty:
        print("  -> No USPTO records found for this query.")
        return []

    sn_col = next((c for c in combined_df.columns if 'serial' in c.lower()), None)
    status_col = next((c for c in combined_df.columns if 'status' in c.lower()), None)
    mark_col = next((c for c in combined_df.columns if 'mark' in c.lower() or 'word' in c.lower()), None)
    owner_col = next((c for c in combined_df.columns if 'owner' in c.lower()), None)
    goods_col = next((c for c in combined_df.columns if 'good' in c.lower()), None)
    filed_col = next((c for c in combined_df.columns if 'file' in c.lower() and 'date' in c.lower()), None)

    if sn_col:
        combined_df.drop_duplicates(subset=[sn_col], keep='first', inplace=True)
    else:
        combined_df.drop_duplicates(keep='first', inplace=True)

    if status_col:
        combined_df[status_col] = combined_df[status_col].astype(str)
        live_df = combined_df[~combined_df[status_col].str.contains('DEAD', case=False, na=False)]
    else:
        live_df = combined_df

    try:
        live_df.to_excel(excel_filename, index=False)
        print(f"  -> Saved unified USPTO Excel to: {excel_filename}")
    except Exception as e:
        print(f"  🚨 Failed to save USPTO Excel: {e}")

    uspto_results = []
    
    for _, row in live_df.iterrows():
        serial_raw = str(row[sn_col]).strip() if sn_col else "N/A"
        if serial_raw == "nan" or not serial_raw: continue

        raw_goods = str(row[goods_col]).strip() if goods_col else "N/A"
        short_goods = "N/A"
        filed_date = str(row[filed_col]).strip().split()[0] if filed_col and str(row[filed_col]) != "nan" else "N/A"

        if raw_goods != "N/A" and raw_goods != "nan":
            target_classes = ['030', '032', '033', '043']
            parsed_classes = []
            class_matches = list(re.finditer(r'IC\s*(\d{1,3})\b[\s:.]*(.*?)(?=\bIC\s*\d{1,3}\b|$)', raw_goods, re.IGNORECASE | re.DOTALL))
            
            if class_matches:
                for match in class_matches:
                    c_num = match.group(1).zfill(3)
                    if c_num in target_classes:
                        text_chunk = match.group(2)
                        text_chunk = re.sub(r'(?i)US\s*[\d\s,]+[.:]\s*', '', text_chunk)
                        text_chunk = re.sub(r'(?i)G\s*&\s*S\s*[:.]\s*', '', text_chunk)
                        c_first_good = re.split(r'[;.]', text_chunk)[0].strip()
                        formatted_class = f"{c_num}: {c_first_good}"
                        if formatted_class not in parsed_classes:
                            parsed_classes.append(formatted_class)
                if parsed_classes:
                    short_goods = "; ".join(parsed_classes)
            
            if short_goods == "N/A":
                text_chunk = re.sub(r'(?i)US\s*[\d\s,]+[.:]\s*', '', raw_goods)
                text_chunk = re.sub(r'(?i)G\s*&\s*S\s*[:.]\s*', '', text_chunk)
                short_goods = re.split(r'[;.]', text_chunk)[0].strip()

        owner_val = str(row[owner_col]).strip() if owner_col and str(row[owner_col]) != "nan" else "OWNER NOT LISTED"

        uspto_results.append({
            "serial": serial_raw,
            "mark": str(row[mark_col]).strip() if mark_col and str(row[mark_col]) != "nan" else "N/A",
            "owner": owner_val,
            "status": str(row[status_col]).strip() if status_col and str(row[status_col]) != "nan" else "N/A",
            "goods": short_goods,
            "filed_date": filed_date
        })

    print(f"Successfully extracted {len(uspto_results)} USPTO records!")
    return uspto_results

def _run_single_search(page, search_query, max_retries=3):
    attempt = 0
    while attempt < max_retries:
        try:
            page.goto("https://tmsearch.uspto.gov/search/search-information", timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)

            search_input = page.locator("input[aria-label=\"Search field\"]")
            if not search_input.is_visible():
                page.locator("text='Field tag and Search builder'").last.click(force=True)
                search_input = page.get_by_placeholder("Search using field tags")

            search_input.wait_for(state="visible", timeout=15000)
            search_input.fill(search_query)
            page.keyboard.press("Enter")

            time.sleep(4)
            
            # --- FIX: Gracefully handle 0 results by catching the timeout ---
            export_btn = page.locator("text='Export'").last
            try:
                # Wait 5 seconds for the export button to appear. 
                # If it doesn't, we assume there are 0 results.
                export_btn.wait_for(state="visible", timeout=5000)
            except PlaywrightTimeoutError:
                print("    -> No results found for this query.")
                return pd.DataFrame(), 0

            # If we get here, results exist. Proceed with export.
            export_btn.click(force=True)
            time.sleep(1)

            with page.expect_download(timeout=45000) as download_info:
                page.locator("text='First 500 results'").last.click(force=True)

            download = download_info.value
            downloaded_file = download.path()

            df = pd.read_excel(downloaded_file)

            try:
                os.remove(downloaded_file)
            except:
                pass

            return df, len(df)

        except Exception as e:
            attempt += 1
            print(f"    🚨 USPTO Server glitched. Retrying {attempt}/{max_retries}...")
            print(f"    [DEBUG] Exact Error: {str(e)}") # <-- Add this line!
            time.sleep(3)

    return pd.DataFrame(), 0