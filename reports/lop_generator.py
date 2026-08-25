import re
import os
import time
import pandas as pd
import streamlit as st
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
def format_class_input(class_input):
    """Pads classes to 3 digits (e.g., '32' -> '032')."""
    if not class_input: return []
    return [c.strip().zfill(3) for c in class_input.split(",") if c.strip()]

# ---------------------------------------------------------
# SCRAPERS
# ---------------------------------------------------------

def fetch_tsdr_data(serial_number, target_classes):
    """Scrapes TSDR using Direct URLs and precise HTML locators."""
    if not serial_number: return None, None
        
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox', 
                '--disable-dev-shm-usage', 
                '--disable-gpu', 
                '--disable-blink-features=AutomationControlled'
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            java_script_enabled=True
        )
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = context.new_page()
        
        try:
            # 1. Use the direct URL (we know this successfully bypasses the firewall from your earlier screenshot!)
            url = f"https://tsdr.uspto.gov/#caseNumber={serial_number}&caseSearchType=US_APPLICATION&caseType=DEFAULT&searchType=statusSearch"
            page.goto(url, timeout=30000)
            
            # 2. Hard pause for 5 seconds to let the USPTO Javascript render the accordion tables
            page.wait_for_timeout(5000)
            
            # Check for firewall block just in case
            if "Access Denied" in page.content():
                browser.close()
                return None, "USPTO Firewall Blocked the Connection."

            # 3. Extract Mark Name using the exact HTML structure
            mark_name = "Unknown Mark"
            try:
                mark_locator = page.locator("div.row:has(div.key:has-text('Mark:')) > div.value").first
                if mark_locator.count() > 0:
                    mark_name = mark_locator.text_content().strip()
                else:
                    # Quick visual fallback for the Mark name
                    import re
                    full_text = page.locator("body").inner_text()
                    mark_match = re.search(r'(?i)(?:Word Mark|Mark):\s*([^\n]+)', full_text)
                    if mark_match:
                        mark_name = mark_match.group(1).strip()
            except:
                pass

            # 4. Extract Goods and Services using the exact HTML "For:" key you found!
            goods_locators = page.locator("div.row:has(div.key:has-text('For:')) > div.value")
            goods_count = goods_locators.count()
            
            if goods_count > 0:
                goods_list = []
                for i in range(goods_count):
                    text = goods_locators.nth(i).text_content()
                    if text:
                        # Clean up tabs/newlines that USPTO hides in the HTML
                        clean_text = " ".join(text.split()).strip()
                        goods_list.append(clean_text)
                
                goods_text = "\n\n".join(goods_list)
            else:
                goods_text = "Could not find 'For:' tags. Please manually paste goods from TSDR."
            
            # Clean up the debug image if it succeeds
            import os
            if os.path.exists(f"debug_{serial_number}.png"):
                os.remove(f"debug_{serial_number}.png")
                
            browser.close()
            return mark_name, goods_text
            
        except Exception as e:
            page.screenshot(path=f"debug_{serial_number}.png")
            browser.close()
            return None, f"Error fetching data: {str(e)}"

def run_uspto_bridging_search(search_query, max_results=10):
    """Executes a tmsearch.uspto.gov search and downloads the Excel export."""
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        try:
            # Navigate and Search
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

            # Export to Excel
            export_btn = page.locator("text='Export'").last
            try:
                export_btn.wait_for(state="visible", timeout=5000)
            except PlaywrightTimeoutError:
                browser.close()
                return pd.DataFrame() 

            export_btn.click(force=True)
            time.sleep(1)

            with page.expect_download(timeout=45000) as download_info:
                try:
                    page.locator("text='First 500 results'").last.click(timeout=3000, force=True)
                except PlaywrightTimeoutError:
                    page.locator("text='First 10000 results'").last.click(force=True)

            download = download_info.value
            downloaded_file = download.path()

            # Parse the downloaded Excel file
            df = pd.read_excel(downloaded_file)

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

            browser.close()

            # Map Columns
            cols = df.columns
            sn_col = next((c for c in cols if 'serial' in str(c).lower()), None)
            rn_col = next((c for c in cols if 'registrationnumber' in str(c).lower() or 'reg' in str(c).lower() and 'num' in str(c).lower()), None)
            status_col = next((c for c in cols if 'status' in str(c).lower()), None)
            mark_col = next((c for c in cols if 'wordmark' in str(c).lower() or 'mark' in str(c).lower()), None)
            goods_col = next((c for c in cols if 'good' in str(c).lower() or 'service' in str(c).lower()), None)

            clean_records = []
            for _, row in df.head(max_results).iterrows():
                clean_records.append({
                    "Select": False,
                    "Mark": str(row[mark_col]).strip() if mark_col and pd.notna(row[mark_col]) else "N/A",
                    "Reg Num": str(row[rn_col]).strip() if rn_col and pd.notna(row[rn_col]) else "N/A",
                    "Serial Num": str(row[sn_col]).strip() if sn_col and pd.notna(row[sn_col]) else "N/A",
                    "Status": str(row[status_col]).strip() if status_col and pd.notna(row[status_col]) else "LIVE",
                    "Goods": str(row[goods_col]).strip()[:200] + "..." if goods_col and pd.notna(row[goods_col]) else "N/A"
                })

            return pd.DataFrame(clean_records)

        except Exception as e:
            browser.close()
            print(f"Error in USPTO Search: {e}")
            return pd.DataFrame()


# ---------------------------------------------------------
# MAIN APP FLOW
# ---------------------------------------------------------
def run():
    st.header("Letter of Protest Generator")
    st.write("Extract goods/services, run a bridging search, and generate a compliant Exhibit A PDF.")
    
    if 'lop_step' not in st.session_state:
        st.session_state['lop_step'] = 1
    if 'bridging_results' not in st.session_state:
        st.session_state['bridging_results'] = pd.DataFrame()

    # ==========================================
    # STEP 1: EXTRACTION & VERIFICATION
    # ==========================================
    st.markdown("### Step 1: Extract & Verify")
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Client Details")
        client_sn = st.text_input("Client Serial / Reg Number", placeholder="e.g., 88331779")
        client_class = st.text_input("Client Class(es)", placeholder="e.g., 032", help="Comma separated")
        
    with col2:
        st.subheader("Applicant Details")
        target_sn = st.text_input("Applicant Serial Number", placeholder="e.g., 90590952")
        target_class = st.text_input("Applicant Class(es)", placeholder="e.g., 043", help="Comma separated")
        
    if st.button("Fetch TSDR Data", type="primary"):
        with st.spinner("Scraping TSDR with stealth mode..."):
            client_mark, client_goods = fetch_tsdr_data(client_sn.strip(), format_class_input(client_class))
            target_mark, target_goods = fetch_tsdr_data(target_sn.strip(), format_class_input(target_class))
            
            st.session_state['client_mark'] = client_mark
            st.session_state['client_goods'] = client_goods
            st.session_state['target_mark'] = target_mark
            st.session_state['target_goods'] = target_goods
            st.session_state['client_class_fmt'] = format_class_input(client_class)
            st.session_state['target_class_fmt'] = format_class_input(target_class)
            st.session_state['lop_step'] = 2

            if os.path.exists(f"debug_{client_sn.strip()}.png"):
                st.error("Client Fetch Failed. Here is what the bot saw:")
                st.image(f"debug_{client_sn.strip()}.png")
            if os.path.exists(f"debug_{target_sn.strip()}.png"):
                st.error("Applicant Fetch Failed. Here is what the bot saw:")
                st.image(f"debug_{target_sn.strip()}.png")

    if st.session_state['lop_step'] >= 2:
        st.info("Trim down the text below to isolate the exact goods/services you want to cross-reference.")
        
        edit_col1, edit_col2 = st.columns(2)
        with edit_col1:
            st.markdown(f"**Mark:** {st.session_state.get('client_mark', '')}")
            core_client = st.text_area("Client Keywords", value=st.session_state.get('client_goods', ''), height=150)
            
        with edit_col2:
            st.markdown(f"**Mark:** {st.session_state.get('target_mark', '')}")
            core_target = st.text_area("Applicant Keywords", value=st.session_state.get('target_goods', ''), height=150)
            
        # ==========================================
        # STEP 2: BRIDGING SEARCH
        # ==========================================
        st.divider()
        st.markdown("### Step 2: Bridging Search")
        if st.button("Execute Bridging Search"):
            with st.spinner("Searching USPTO via tmsearch.uspto.gov..."):
                c_class = st.session_state.get('client_class_fmt', ["032"])[0] if st.session_state.get('client_class_fmt') else "032"
                t_class = st.session_state.get('target_class_fmt', ["043"])[0] if st.session_state.get('target_class_fmt') else "043"
                
                c_kw = core_client.strip().replace('"', '')
                t_kw = core_target.strip().replace('"', '')

                search_query = f'GS:"{c_kw}" AND GS:"{t_kw}" AND (IC:{c_class} AND IC:{t_class}) AND LD:true AND RN > 0'
                
                results_df = run_uspto_bridging_search(search_query, max_results=10)
                
                if results_df.empty:
                    st.warning(f"No bridging registrations found for query: `{search_query}`. Try broadening your keywords.")
                else:
                    st.session_state['bridging_results'] = results_df
                    st.session_state['lop_step'] = 3
                    st.rerun()

    # ==========================================
    # STEP 3: RESULTS & SELECTION
    # ==========================================
    if st.session_state['lop_step'] >= 3:
        st.divider()
        st.markdown("### Step 3: Select Evidence (Max 5)")
        st.caption("Select up to 5 of the strongest bridging registrations. Evidence must be based on USE in commerce.")
        
        edited_df = st.data_editor(
            st.session_state['bridging_results'],
            column_config={"Select": st.column_config.CheckboxColumn("Select", help="Check to include in LoP", default=False)},
            disabled=["Mark", "Reg Num", "Serial Num", "Status", "Goods"],
            hide_index=True,
            use_container_width=True
        )
        
        selected_rows = edited_df[edited_df["Select"] == True]
        selected_count = len(selected_rows)
        
        if selected_count > 5:
            st.error(f"⚠️ Selected: {selected_count}/5 - You have exceeded the USPTO maximum limit of 5 registrations.")
        else:
            st.success(f"✅ Selected: {selected_count}/5")

        # ==========================================
        # STEP 4: PREVIEW & GENERATE
        # ==========================================
        if 0 < selected_count <= 5:
            st.divider()
            st.markdown("### Step 4: Preview & Export")
            st.dataframe(selected_rows[["Mark", "Reg Num", "Goods"]], hide_index=True, use_container_width=True)
            
            if st.button("📄 Generate Exhibit A (PDF)", type="primary"):
                st.info(f"PDF generator coming next! Ready to compile {selected_count} marks.")