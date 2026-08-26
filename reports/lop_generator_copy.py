import streamlit as st
import time
import re
import gc
import pandas as pd
from playwright.sync_api import sync_playwright

# Import your actual USPTO scraper
from scrapers.uspto_scraper import scrape_uspto

# ==========================================
# 1. TSDR SCRAPER FUNCTION (With 3x Retry Loop)
# ==========================================
def fetch_tsdr_data(serial_number, target_classes):
    """Scrapes TSDR with a 3-attempt automatic retry loop to bypass intermittent USPTO blocks."""
    if not serial_number: return None, None
        
    max_retries = 3
    
    for attempt in range(max_retries):
        try:
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
                
                url = f"https://tsdr.uspto.gov/#caseNumber={serial_number}&caseSearchType=US_APPLICATION&caseType=DEFAULT&searchType=statusSearch"
                page.goto(url, timeout=30000)
                
                # BULLETPROOF WAIT: Wait for the actual data value boxes to physically attach to the DOM
                try:
                    page.wait_for_selector("div.value", state="attached", timeout=15000)
                except:
                    try:
                        page.locator('#searchNumber').fill(serial_number)
                        page.locator('#searchNumber').press("Enter")
                        page.wait_for_selector("div.value", state="attached", timeout=15000)
                    except:
                        pass 
                    
                page.wait_for_timeout(2000) 
                
                if "Access Denied" in page.content():
                    browser.close()
                    raise Exception("USPTO Firewall Blocked the Connection.")

                js_extract = """
                () => {
                    let markName = "Unknown Mark";
                    let goodsArray = [];
                    
                    let keys = document.querySelectorAll('div.key');
                    for (let k of keys) {
                        let text = k.textContent.trim();
                        if (text === 'Mark:' || text === 'Word Mark:') {
                            let val = k.nextElementSibling;
                            if (val && val.classList.contains('value')) {
                                markName = val.textContent.trim();
                                break;
                            }
                        }
                    }
                    
                    let rows = document.querySelectorAll('div.row');
                    for (let row of rows) {
                        let keyNode = row.querySelector('div.key');
                        let valNode = row.querySelector('div.value');
                        
                        if (keyNode && valNode) {
                            if (keyNode.textContent.trim() === 'For:') {
                                let cleanGoods = valNode.textContent.replace(/\\s+/g, ' ').trim();
                                if (cleanGoods) {
                                    goodsArray.push(cleanGoods);
                                }
                            }
                        }
                    }
                    
                    return { 
                        mark: markName, 
                        goods: goodsArray.length > 0 ? goodsArray.join("\\n\\n") : "Goods boundaries not found. Please manually copy from TSDR."
                    };
                }
                """
                
                result = page.evaluate(js_extract)
                mark_name = result.get('mark', 'Unknown Mark')
                goods_text = result.get('goods', 'Goods boundaries not found. Please manually copy from TSDR.')
                
                browser.close()
                
                # SAFEGUARD: If it somehow still pulled blank data, throw an error to force a retry!
                if mark_name == "Unknown Mark":
                    raise Exception("Page loaded but data was missing. Retrying...")
                    
                return mark_name, goods_text
                
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            else:
                return None, f"Error fetching data after 3 attempts: {str(e)}"

# ==========================================
# PAGE UI & LAYOUT (WRAPPED IN RUN FUNCTION)
# ==========================================
def run():
    st.title("Letter of Protest Generator")
    st.markdown("Extract goods/services, run a bridging search, and generate a compliant Exhibit A PDF.")

    # --- STEP 1: EXTRACT & VERIFY ---
    st.markdown("### Step 1: Extract & Verify")

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Client Details")
        client_sn = st.text_input("Client Serial / Reg Number", key="client_sn")
        client_class = st.text_input("Client Class(es)", placeholder="e.g., 032", key="client_class")
    with col2:
        st.markdown("#### Applicant Details")
        app_sn = st.text_input("Applicant Serial Number", key="app_sn")
        app_class = st.text_input("Applicant Class(es)", placeholder="e.g., 043", key="applicant_class")

    if st.button("Fetch TSDR Data", type="primary"):
        # Prevent Memory Spikes (Code: 1ST Error)
        with st.spinner("Scraping Client Data (Browser 1 of 2)..."):
            c_mark, c_goods = fetch_tsdr_data(client_sn, client_class)
            st.session_state['c_mark'] = c_mark
            st.session_state['c_goods'] = c_goods
            
        gc.collect() 
        time.sleep(2) 

        with st.spinner("Scraping Applicant Data (Browser 2 of 2)..."):
            a_mark, a_goods = fetch_tsdr_data(app_sn, app_class)
            st.session_state['a_mark'] = a_mark
            st.session_state['a_goods'] = a_goods
            
        st.rerun()

    st.info("Trim down the text below to isolate the exact goods/services you want to cross-reference.")

    col3, col4 = st.columns(2)
    with col3:
        st.markdown(f"**Mark:** {st.session_state.get('c_mark', 'None')}")
        core_client = st.text_area("Client Keywords", value=st.session_state.get('c_goods', ''), height=150)
    with col4:
        st.markdown(f"**Mark:** {st.session_state.get('a_mark', 'None')}")
        core_target = st.text_area("Applicant Keywords", value=st.session_state.get('a_goods', ''), height=150)

    # --- STEP 2: BRIDGING SEARCH ---
    st.divider()
    st.markdown("### Step 2: Bridging Search")
    if st.button("Execute Bridging Search"):
        
        # Pull directly from whatever the user typed in Step 1
        raw_c = st.session_state.get('client_class', '')
        raw_t = st.session_state.get('applicant_class', '')
        
        # Ensure they are 3 digits
        c_class = str(raw_c).strip().zfill(3)
        t_class = str(raw_t).strip().zfill(3)
        
        if c_class == "000" or t_class == "000" or not raw_c or not raw_t:
            st.error("Please enter both the Client and Applicant classes in Step 1 before searching!")
            st.stop()
            
        with st.spinner("Searching USPTO via tmsearch.uspto.gov..."):
            
            c_kw = core_client.strip().replace('"', '')
            t_kw = core_target.strip().replace('"', '')

            # The Exact Search Query with the Live Document parameter
            search_query = f'GS:"{t_kw}" AND GS:"{c_kw}" AND IC:{c_class} AND IC:{t_class} AND LD:true'
            
            # Execute search using your real USPTO Scraper
            raw_results = []
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True,
                        args=['--no-sandbox', '--disable-dev-shm-usage']
                    )
                    page = browser.new_page()
                    excel_out = "temp_bridging_search.xlsx" 
                    
                    raw_results = scrape_uspto(
                        page=page,
                        primary_query=search_query,
                        excel_filename=excel_out
                    )
                    browser.close()
            except Exception as e:
                st.error(f"Error scraping USPTO: {e}")
                st.stop()
                
            results_df = pd.DataFrame(raw_results)
            
            if results_df.empty:
                st.warning(f"No bridging registrations found for query: `{search_query}`. Try broadening your keywords.")
            else:
                # FILTER AND FORMAT THE GOODS
                def clean_goods(text, c_cls, t_cls):
                    if not isinstance(text, str): return text
                    
                    segments = re.finditer(r'IC\s+0*(\d+)[\s:]+(.*?)(?=IC\s+\d+|$)', text, re.IGNORECASE | re.DOTALL)
                    target_classes = {c_cls.lstrip('0'), t_cls.lstrip('0'), c_cls, t_cls}
                    filtered = []
                    
                    for match in segments:
                        cls_num = match.group(1)
                        goods_desc = match.group(2).strip().rstrip(';')
                        if cls_num in target_classes:
                            filtered.append(f"IC {cls_num.zfill(3)}: {goods_desc}")
                            
                    return "\n\n".join(filtered) if filtered else text
                
                # Check for the dynamic column name your scraper creates
                col_name = "goods" if "goods" in results_df.columns else "Goods"
                if col_name not in results_df.columns and "Goods & services" in results_df.columns:
                    col_name = "Goods & services"
                    
                if col_name in results_df.columns:
                    results_df[col_name] = results_df[col_name].apply(lambda x: clean_goods(x, c_class, t_class))

                st.session_state['bridging_results'] = results_df
                st.session_state['lop_step'] = 3
                st.rerun()

    # --- STEP 3: RESULTS TABLE ---
    if st.session_state.get('lop_step') == 3:
        st.divider()
        st.markdown("### Step 3: Select Evidence")
        st.write("Select the best records below to include in your Exhibit A.")
        
        df = st.session_state['bridging_results']
        
        if "Select" not in df.columns:
            df.insert(0, "Select", False)
        
        edited_df = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Select": st.column_config.CheckboxColumn("Select", help="Check to include in LOP"),
                "goods": st.column_config.TextColumn("Filtered Goods", width="large"),
                "Goods": st.column_config.TextColumn("Filtered Goods", width="large"),
                "Goods & services": st.column_config.TextColumn("Filtered Goods", width="large")
            }
        )