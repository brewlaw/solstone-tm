import os
import re
import time
import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

def scrape_uspto(page, primary_query, excel_filename, secondary_query=None, target_classes=None, max_retries=3):
    print("\nLaunching browser for USPTO Trademark Search...")
    
    print("  -> Executing Primary USPTO Search...")
    primary_df, p_raw = _run_single_search(page, primary_query, max_retries)

    secondary_df = pd.DataFrame()
    s_raw = 0
    if secondary_query:
        print("  -> Executing Secondary USPTO Search...")
        secondary_df, s_raw = _run_single_search(page, secondary_query, max_retries)

    print("  -> Merging and Deduplicating USPTO Results...")
    combined_df = pd.concat([primary_df, secondary_df], ignore_index=True)

    if combined_df.empty:
        print("  -> No USPTO records found for this query.")
        return []

    # Dynamic Column Mapping
    cols = combined_df.columns
    sn_col = next((c for c in cols if 'serial' in str(c).lower()), None)
    rn_col = next((c for c in cols if 'registrationnumber' in str(c).lower() or 'reg' in str(c).lower() and 'num' in str(c).lower()), None)
    status_col = next((c for c in cols if 'status' in str(c).lower()), None)
    mark_col = next((c for c in cols if 'wordmark' in str(c).lower() or 'mark' in str(c).lower()), None)
    image_col = next((c for c in cols if 'image' in str(c).lower()), None)
    owner_col = next((c for c in cols if 'owner' in str(c).lower() or 'applicant' in str(c).lower()), None)
    goods_col = next((c for c in cols if 'good' in str(c).lower() or 'service' in str(c).lower()), None)
    filed_col = next((c for c in cols if 'file' in str(c).lower() and 'date' in str(c).lower()), None)
    reg_date_col = next((c for c in cols if 'registrationdate' in str(c).lower() or 'reg' in str(c).lower() and 'date' in str(c).lower()), None)

    if sn_col:
        combined_df.drop_duplicates(subset=[sn_col], keep='first', inplace=True)
    else:
        combined_df.drop_duplicates(keep='first', inplace=True)

    if status_col:
        combined_df[status_col] = combined_df[status_col].astype(str)
        live_df = combined_df[~combined_df[status_col].str.contains('DEAD', case=False, na=False)].copy()
    else:
        live_df = combined_df

    try:
        live_df.to_excel(excel_filename, index=False)
        print(f"  -> Saved unified USPTO Excel to: {excel_filename}")
    except Exception as e:
        print(f"  🚨 Failed to save USPTO Excel: {e}")

    uspto_results = []
    default_classes = ['030', '032', '033', '043'] if target_classes is None else target_classes
    
    for _, row in live_df.iterrows():
        serial_raw = str(row[sn_col]).strip() if sn_col and pd.notna(row[sn_col]) else "N/A"
        if serial_raw == "nan" or not serial_raw or serial_raw == "N/A": 
            continue

        raw_goods = str(row[goods_col]).strip() if goods_col and pd.notna(row[goods_col]) else "N/A"
        short_goods = "N/A"
        
        filed_date = "N/A"
        if filed_col and pd.notna(row[filed_col]):
            val = str(row[filed_col]).strip().split()[0]
            filed_date = val if val != "nan" else "N/A"

        reg_date = "N/A"
        if reg_date_col and pd.notna(row[reg_date_col]):
            val = str(row[reg_date_col]).strip().split()[0]
            reg_date = val if val != "nan" else "N/A"

        reg_number = str(row[rn_col]).strip() if rn_col and pd.notna(row[rn_col]) else "N/A"
        if reg_number == "nan": reg_number = "N/A"

        # Parse Goods & Services
        if raw_goods != "N/A" and raw_goods != "nan":
            parsed_classes = []
            class_matches = list(re.finditer(r'IC\s*(\d{1,3})\b[\s:.]*(.*?)(?=\bIC\s*\d{1,3}\b|$)', raw_goods, re.IGNORECASE | re.DOTALL))
            
            if class_matches:
                for match in class_matches:
                    c_num = match.group(1).zfill(3)
                    if not default_classes or c_num in default_classes:
                        text_chunk = match.group(2)
                        text_chunk = re.sub(r'(?i)US\s*[\d\s,]+[.:]\s*', '', text_chunk)
                        text_chunk = re.sub(r'(?i)G\s*&\s*S\s*[:.]\s*', '', text_chunk)
                        c_first_good = re.split(r'[;.]', text_chunk)[0].strip()
                        formatted_class = f"IC {c_num}: {c_first_good}"
                        if formatted_class not in parsed_classes:
                            parsed_classes.append(formatted_class)
                if parsed_classes:
                    short_goods = "; ".join(parsed_classes)
            
            if short_goods == "N/A":
                text_chunk = re.sub(r'(?i)US\s*[\d\s,]+[.:]\s*', '', raw_goods)
                text_chunk = re.sub(r'(?i)G\s*&\s*S\s*[:.]\s*', '', text_chunk)
                short_goods = re.split(r'[;.]', text_chunk)[0].strip()

        owner_val = str(row[owner_col]).strip() if owner_col and pd.notna(row[owner_col]) else "OWNER NOT LISTED"
        mark_val = str(row[mark_col]).strip() if mark_col and pd.notna(row[mark_col]) else "N/A"
        
        # Fallback to image name if mark is blank
        if mark_val in ["nan", "N/A", ""]:
            img_val = str(row[image_col]).strip() if image_col and pd.notna(row[image_col]) else "N/A"
            mark_val = f"[{img_val}]" if img_val not in ["N/A", "nan", ""] else "[Logo Design]"

        if owner_val == "nan": owner_val = "OWNER NOT LISTED"
        if short_goods == "nan": short_goods = "N/A"

        uspto_results.append({
            "serial": serial_raw,
            "reg_number": reg_number,
            "mark": mark_val,
            "owner": owner_val,
            "status": str(row[status_col]).strip() if status_col and pd.notna(row[status_col]) else "Live",
            "goods": short_goods,
            "filed_date": filed_date,
            "reg_date": reg_date
        })

    print(f"Successfully extracted {len(uspto_results)} USPTO records!")
    return uspto_results

def _run_single_search(page, search_query, max_retries=3):
    attempt = 0
    while attempt < max_retries:
        try:
            page.goto("https://tmsearch.uspto.gov/search/search-information", timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)

            search_input = page.locator('input[aria-label="Search field"], textarea[aria-label="Search field"], input[placeholder*="Search"]').first
            
            try:
                search_input.wait_for(state="visible", timeout=5000)
            except PlaywrightTimeoutError:
                builder_toggle = page.locator("text='Field tag and Search builder'").last
                if builder_toggle.is_visible():
                    builder_toggle.click(force=True)
                    time.sleep(1)
                search_input = page.get_by_placeholder("Search using field tags")
                search_input.wait_for(state="visible", timeout=10000)

            search_input.fill(search_query)
            page.keyboard.press("Enter")
            time.sleep(4)
            
            export_btn = page.locator("text='Export'").last
            try:
                export_btn.wait_for(state="visible", timeout=5000)
            except PlaywrightTimeoutError:
                print("    -> No results found for this query.")
                return pd.DataFrame(), 0

            export_btn.click(force=True)
            time.sleep(1)

            with page.expect_download(timeout=45000) as download_info:
                try:
                    page.locator("text='First 10000 results'").last.click(timeout=3000, force=True)
                except PlaywrightTimeoutError:
                    page.locator("text='First 500 results'").last.click(force=True)

            download = download_info.value
            downloaded_file = download.path()

            df = pd.read_excel(downloaded_file)

            # Header row detection for shifted metadata
            header_idx = None
            for i, row in df.iterrows():
                row_strs = [str(cell).lower() for cell in row]
                if any('serialnumber' in s or 'wordmark' in s for s in row_strs):
                    header_idx = i
                    break
            
            if header_idx is not None:
                df.columns = df.iloc[header_idx]
                df = df.iloc[header_idx + 1:].reset_index(drop=True)

            try:
                os.remove(downloaded_file)
            except:
                pass

            return df, len(df)

        except Exception as e:
            attempt += 1
            print(f"    🚨 USPTO Server glitched. Retrying {attempt}/{max_retries}...")
            print(f"    [DEBUG] Exact Error: {str(e)}")
            time.sleep(3)

    return pd.DataFrame(), 0import os
import re
import time
import pandas as pd
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

def scrape_uspto(page, primary_query, excel_filename, secondary_query=None, target_classes=None, max_retries=3):
    print("\nLaunching browser for USPTO Trademark Search...")
    
    print("  -> Executing Primary USPTO Search...")
    primary_df, p_raw = _run_single_search(page, primary_query, max_retries)

    secondary_df = pd.DataFrame()
    s_raw = 0
    if secondary_query:
        print("  -> Executing Secondary USPTO Search...")
        secondary_df, s_raw = _run_single_search(page, secondary_query, max_retries)

    print("  -> Merging and Deduplicating USPTO Results...")
    combined_df = pd.concat([primary_df, secondary_df], ignore_index=True)

    if combined_df.empty:
        print("  -> No USPTO records found for this query.")
        return []

    # Dynamic Column Mapping
    cols = combined_df.columns
    sn_col = next((c for c in cols if 'serial' in str(c).lower()), None)
    rn_col = next((c for c in cols if 'registrationnumber' in str(c).lower() or 'reg' in str(c).lower() and 'num' in str(c).lower()), None)
    status_col = next((c for c in cols if 'status' in str(c).lower()), None)
    mark_col = next((c for c in cols if 'wordmark' in str(c).lower() or 'mark' in str(c).lower()), None)
    image_col = next((c for c in cols if 'image' in str(c).lower()), None)
    owner_col = next((c for c in cols if 'owner' in str(c).lower() or 'applicant' in str(c).lower()), None)
    goods_col = next((c for c in cols if 'good' in str(c).lower() or 'service' in str(c).lower()), None)
    filed_col = next((c for c in cols if 'file' in str(c).lower() and 'date' in str(c).lower()), None)
    reg_date_col = next((c for c in cols if 'registrationdate' in str(c).lower() or 'reg' in str(c).lower() and 'date' in str(c).lower()), None)

    if sn_col:
        combined_df.drop_duplicates(subset=[sn_col], keep='first', inplace=True)
    else:
        combined_df.drop_duplicates(keep='first', inplace=True)

    if status_col:
        combined_df[status_col] = combined_df[status_col].astype(str)
        live_df = combined_df[~combined_df[status_col].str.contains('DEAD', case=False, na=False)].copy()
    else:
        live_df = combined_df

    try:
        live_df.to_excel(excel_filename, index=False)
        print(f"  -> Saved unified USPTO Excel to: {excel_filename}")
    except Exception as e:
        print(f"  🚨 Failed to save USPTO Excel: {e}")

    uspto_results = []
    default_classes = ['030', '032', '033', '043'] if target_classes is None else target_classes
    
    for _, row in live_df.iterrows():
        serial_raw = str(row[sn_col]).strip() if sn_col and pd.notna(row[sn_col]) else "N/A"
        if serial_raw == "nan" or not serial_raw or serial_raw == "N/A": 
            continue

        raw_goods = str(row[goods_col]).strip() if goods_col and pd.notna(row[goods_col]) else "N/A"
        short_goods = "N/A"
        
        filed_date = "N/A"
        if filed_col and pd.notna(row[filed_col]):
            val = str(row[filed_col]).strip().split()[0]
            filed_date = val if val != "nan" else "N/A"

        reg_date = "N/A"
        if reg_date_col and pd.notna(row[reg_date_col]):
            val = str(row[reg_date_col]).strip().split()[0]
            reg_date = val if val != "nan" else "N/A"

        reg_number = str(row[rn_col]).strip() if rn_col and pd.notna(row[rn_col]) else "N/A"
        if reg_number == "nan": reg_number = "N/A"

        # Parse Goods & Services
        if raw_goods != "N/A" and raw_goods != "nan":
            parsed_classes = []
            class_matches = list(re.finditer(r'IC\s*(\d{1,3})\b[\s:.]*(.*?)(?=\bIC\s*\d{1,3}\b|$)', raw_goods, re.IGNORECASE | re.DOTALL))
            
            if class_matches:
                for match in class_matches:
                    c_num = match.group(1).zfill(3)
                    if not default_classes or c_num in default_classes:
                        text_chunk = match.group(2)
                        text_chunk = re.sub(r'(?i)US\s*[\d\s,]+[.:]\s*', '', text_chunk)
                        text_chunk = re.sub(r'(?i)G\s*&\s*S\s*[:.]\s*', '', text_chunk)
                        c_first_good = re.split(r'[;.]', text_chunk)[0].strip()
                        formatted_class = f"IC {c_num}: {c_first_good}"
                        if formatted_class not in parsed_classes:
                            parsed_classes.append(formatted_class)
                if parsed_classes:
                    short_goods = "; ".join(parsed_classes)
            
            if short_goods == "N/A":
                text_chunk = re.sub(r'(?i)US\s*[\d\s,]+[.:]\s*', '', raw_goods)
                text_chunk = re.sub(r'(?i)G\s*&\s*S\s*[:.]\s*', '', text_chunk)
                short_goods = re.split(r'[;.]', text_chunk)[0].strip()

        owner_val = str(row[owner_col]).strip() if owner_col and pd.notna(row[owner_col]) else "OWNER NOT LISTED"
        mark_val = str(row[mark_col]).strip() if mark_col and pd.notna(row[mark_col]) else "N/A"
        
        # Fallback to image name if mark is blank
        if mark_val in ["nan", "N/A", ""]:
            img_val = str(row[image_col]).strip() if image_col and pd.notna(row[image_col]) else "N/A"
            mark_val = f"[{img_val}]" if img_val not in ["N/A", "nan", ""] else "[Logo Design]"

        if owner_val == "nan": owner_val = "OWNER NOT LISTED"
        if short_goods == "nan": short_goods = "N/A"

        uspto_results.append({
            "serial": serial_raw,
            "reg_number": reg_number,
            "mark": mark_val,
            "owner": owner_val,
            "status": str(row[status_col]).strip() if status_col and pd.notna(row[status_col]) else "Live",
            "goods": short_goods,
            "filed_date": filed_date,
            "reg_date": reg_date
        })

    print(f"Successfully extracted {len(uspto_results)} USPTO records!")
    return uspto_results

def _run_single_search(page, search_query, max_retries=3):
    attempt = 0
    while attempt < max_retries:
        try:
            page.goto("https://tmsearch.uspto.gov/search/search-information", timeout=30000, wait_until="domcontentloaded")
            time.sleep(2)

            search_input = page.locator('input[aria-label="Search field"], textarea[aria-label="Search field"], input[placeholder*="Search"]').first
            
            try:
                search_input.wait_for(state="visible", timeout=5000)
            except PlaywrightTimeoutError:
                builder_toggle = page.locator("text='Field tag and Search builder'").last
                if builder_toggle.is_visible():
                    builder_toggle.click(force=True)
                    time.sleep(1)
                search_input = page.get_by_placeholder("Search using field tags")
                search_input.wait_for(state="visible", timeout=10000)

            search_input.fill(search_query)
            page.keyboard.press("Enter")
            time.sleep(4)
            
            export_btn = page.locator("text='Export'").last
            try:
                export_btn.wait_for(state="visible", timeout=5000)
            except PlaywrightTimeoutError:
                print("    -> No results found for this query.")
                return pd.DataFrame(), 0

            export_btn.click(force=True)
            time.sleep(1)

            with page.expect_download(timeout=45000) as download_info:
                try:
                    page.locator("text='First 10000 results'").last.click(timeout=3000, force=True)
                except PlaywrightTimeoutError:
                    page.locator("text='First 500 results'").last.click(force=True)

            download = download_info.value
            downloaded_file = download.path()

            df = pd.read_excel(downloaded_file)

            # Header row detection for shifted metadata
            header_idx = None
            for i, row in df.iterrows():
                row_strs = [str(cell).lower() for cell in row]
                if any('serialnumber' in s or 'wordmark' in s for s in row_strs):
                    header_idx = i
                    break
            
            if header_idx is not None:
                df.columns = df.iloc[header_idx]
                df = df.iloc[header_idx + 1:].reset_index(drop=True)

            try:
                os.remove(downloaded_file)
            except:
                pass

            return df, len(df)

        except Exception as e:
            attempt += 1
            print(f"    🚨 USPTO Server glitched. Retrying {attempt}/{max_retries}...")
            print(f"    [DEBUG] Exact Error: {str(e)}")
            time.sleep(3)

    return pd.DataFrame(), 0