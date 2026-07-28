import time

def scrape_ttb(page, ttb_date_from, ttb_date_to, mark_list):
    print("\nNavigating to TTB COLA Registry...")
    
    ttb_results = []
    seen_ttb_ids = set() 
    
    if isinstance(mark_list, str):
        mark_list = [mark_list]

    for mark in mark_list:
        if not mark:
            continue
            
        print(f" -> Searching TTB for variation: '{mark}'...")
        
        for attempt in range(3):
            try:
                if attempt > 0:
                    print(f"    -> TTB Connection Retry {attempt + 1}/3...")
                    
                page.goto("https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do", timeout=30000)
                
                if page.locator("input[value='I Agree']").is_visible():
                    page.locator("input[value='I Agree']").evaluate("node => node.click()")
                    page.wait_for_timeout(5000)
                    
                print("    [DEBUG] Filling TTB form data...")
                text_boxes = page.locator("input[type='text']")
                text_boxes.nth(0).fill(ttb_date_from)
                text_boxes.nth(1).fill(ttb_date_to)
                text_boxes.nth(2).fill(mark) 
                
                print("    [DEBUG] Selecting 'Either' for Brand Name / Fanciful Name...")
                page.locator("text='Either'").last.evaluate("node => node.click()")
                page.wait_for_timeout(500)
                
                page.locator("input[value='Search']").evaluate("node => node.click()")
                page.wait_for_timeout(5000) 
                
                # --- FIX: Added .first to avoid strict mode crash on 0 results ---
                if page.locator("text='Save Search Results To File'").is_visible() or page.locator("table").first.is_visible():
                    variation_count = 0
                    
                    while True:
                        # --- FIX: Added .first here as well just in case ---
                        if not page.locator("table").first.is_visible():
                            break
                            
                        rows = page.locator("tr").all()
                        for row in rows:
                            row_text = row.inner_text()
                            if "TTB ID" in row_text or "Results" in row_text:
                                continue 
                                
                            cols = row.locator("td").all_inner_texts()
                            if len(cols) >= 6 and cols[0].strip().isdigit():
                                ttb_id = cols[0].strip()
                                
                                if ttb_id in seen_ttb_ids:
                                    continue
                                seen_ttb_ids.add(ttb_id)
                                variation_count += 1
                                
                                ttb_results.append({
                                    "ttb_id": ttb_id,
                                    "approval_date": cols[3].strip() if len(cols) > 3 else "N/A",
                                    "fanciful_name": cols[4].strip() if len(cols) > 4 else "N/A",
                                    "brand_name": cols[5].strip() if len(cols) > 5 else "N/A",
                                    "class_desc": cols[9].strip() if len(cols) > 9 else "N/A" 
                                })
                        
                        next_btn = page.locator("a:has-text('Next'), a:has-text('NEXT')").last
                        if next_btn.is_visible():
                            btn_class = next_btn.get_attribute("class") or ""
                            if "disabled" in btn_class.lower():
                                break 
                            else:
                                print("    [DEBUG] Flipping to the next page of results...")
                                next_btn.evaluate("node => node.click()")
                                page.wait_for_timeout(3000) 
                        else:
                            break 
                            
                    print(f"    Successfully scraped {variation_count} NEW records for '{mark}'!")
                    break 
                    
                else:
                    print(f"    No TTB records found for '{mark}'.")
                    break 
                    
            except Exception as e:
                print(f"    TTB Scraper error: {e}")
                if attempt < 2:
                    print("    🚨 TTB Server glitched. Waiting 5 seconds and refreshing...")
                    page.wait_for_timeout(5000)
                else:
                    print(f"    🚨 TTB Scraper failed for '{mark}' after 3 attempts.")
                    
        time.sleep(1)
        
    return ttb_results