import streamlit as st
import time
import re
import gc
import os
import pandas as pd
from playwright.sync_api import sync_playwright

# Import your actual USPTO scraper
from scrapers.uspto_scraper import scrape_uspto

# ==========================================
# 1. HELPER: PARSE GOODS INTO CHECKLIST
# ==========================================
def parse_goods_to_df(raw_goods):
    """Splits raw goods text by semicolons/newlines into a DataFrame for the checklist UI."""
    if not raw_goods or "Goods boundaries not found" in raw_goods:
        return pd.DataFrame({"Select": [False], "Keyword": [raw_goods]})
    
    # Split by semicolon or new line
    raw_items = re.split(r'[;\n]', raw_goods)
    
    cleaned_items = []
    for item in raw_items:
        clean_item = item.strip()
        if clean_item:
            cleaned_items.append(clean_item)
            
    seen = set()
    unique_items = [x for x in cleaned_items if not (x in seen or seen.add(x))]
    
    if not unique_items:
        return pd.DataFrame({"Select": [], "Keyword": []})
        
    return pd.DataFrame({"Select": [False] * len(unique_items), "Keyword": unique_items})

# ==========================================
# 2. TSDR SCRAPER FUNCTION (With 3x Retry Loop)
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
        with st.spinner("Scraping Client Data (Browser 1 of 2)..."):
            c_mark, c_goods = fetch_tsdr_data(client_sn, client_class)
            st.session_state['c_mark'] = c_mark
            st.session_state['c_goods_df'] = parse_goods_to_df(c_goods)
            
        gc.collect() 
        time.sleep(2) 

        with st.spinner("Scraping Applicant Data (Browser 2 of 2)..."):
            a_mark, a_goods = fetch_tsdr_data(app_sn, app_class)
            st.session_state['a_mark'] = a_mark
            st.session_state['a_goods_df'] = parse_goods_to_df(a_goods)
            
        st.rerun()

    st.info("Check the boxes next to the specific goods/services you want to cross-reference. You can double-click a keyword in the table to manually edit it!")

    col3, col4 = st.columns(2)
    with col3:
        st.markdown(f"**Mark:** {st.session_state.get('c_mark', 'None')}")
        if 'c_goods_df' in st.session_state:
            edited_c_df = st.data_editor(
                st.session_state['c_goods_df'],
                hide_index=True,
                use_container_width=True,
                key="c_goods_editor",
                column_config={
                    "Select": st.column_config.CheckboxColumn("Select", width="small"),
                    "Keyword": st.column_config.TextColumn("Client Keywords", width="large")
                }
            )
            st.session_state['c_goods_df'] = edited_c_df

    with col4:
        st.markdown(f"**Mark:** {st.session_state.get('a_mark', 'None')}")
        if 'a_goods_df' in st.session_state:
            edited_a_df = st.data_editor(
                st.session_state['a_goods_df'],
                hide_index=True,
                use_container_width=True,
                key="a_goods_editor",
                column_config={
                    "Select": st.column_config.CheckboxColumn("Select", width="small"),
                    "Keyword": st.column_config.TextColumn("Applicant Keywords", width="large")
                }
            )
            st.session_state['a_goods_df'] = edited_a_df

    # --- STEP 2: BRIDGING SEARCH ---
    st.divider()
    st.markdown("### Step 2: Bridging Search")
    if st.button("Execute Bridging Search"):
        raw_c = st.session_state.get('client_class', '')
        raw_t = st.session_state.get('applicant_class', '')
        c_class = str(raw_c).strip().zfill(3)
        t_class = str(raw_t).strip().zfill(3)
        
        if c_class == "000" or t_class == "000" or not raw_c or not raw_t:
            st.error("Please enter both the Client and Applicant classes in Step 1 before searching!")
            st.stop()
            
        if 'c_goods_df' not in st.session_state or 'a_goods_df' not in st.session_state:
            st.error("Please fetch TSDR data first.")
            st.stop()
            
        c_df = st.session_state['c_goods_df']
        a_df = st.session_state['a_goods_df']
        c_selected = c_df[c_df['Select'] == True]['Keyword'].tolist()
        a_selected = a_df[a_df['Select'] == True]['Keyword'].tolist()
        
        if not c_selected or not a_selected:
            st.error("Please check at least one box for BOTH the Client and the Applicant keywords.")
            st.stop()
            
        with st.spinner("Searching USPTO via tmsearch.uspto.gov..."):
            c_clean = [kw.strip().replace('"', '') for kw in c_selected]
            t_clean = [kw.strip().replace('"', '') for kw in a_selected]
            c_kw_str = " OR ".join([f'"{kw}"' for kw in c_clean])
            t_kw_str = " OR ".join([f'"{kw}"' for kw in t_clean])

            search_query = f'GS:({t_kw_str}) AND GS:({c_kw_str}) AND IC:{c_class} AND IC:{t_class} AND LD:true'
            
            excel_out = "temp_bridging_search.xlsx" 
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        headless=True,
                        args=['--no-sandbox', '--disable-dev-shm-usage']
                    )
                    page = browser.new_page()
                    # We run the scraper, but we will ignore its formatted output and steal the raw Excel file instead!
                    _ = scrape_uspto(
                        page=page,
                        primary_query=search_query,
                        excel_filename=excel_out
                    )
                    browser.close()
            except Exception as e:
                st.error(f"Error scraping USPTO: {e}")
                st.stop()
                
            if not os.path.exists(excel_out):
                st.warning(f"No bridging registrations found for query: `{search_query}`.")
                st.stop()
                
            # Read the RAW Excel data so we don't lose the full goods list
            raw_df = pd.read_excel(excel_out)
            
            # Map the dynamic column names
            cols = raw_df.columns
            sn_col = next((c for c in cols if 'serial' in str(c).lower()), None)
            rn_col = next((c for c in cols if 'registrationnumber' in str(c).lower() or 'reg' in str(c).lower() and 'num' in str(c).lower()), None)
            mark_col = next((c for c in cols if 'wordmark' in str(c).lower() or 'mark' in str(c).lower()), None)
            owner_col = next((c for c in cols if 'owner' in str(c).lower() or 'applicant' in str(c).lower()), None)
            goods_col = next((c for c in cols if 'good' in str(c).lower() or 'service' in str(c).lower()), None)
            status_col = next((c for c in cols if 'status' in str(c).lower()), None)
            
            # STRICT FILTER: Only keep Registered Marks
            if rn_col:
                raw_df = raw_df[raw_df[rn_col].notna()]
                raw_df = raw_df[raw_df[rn_col].astype(str).str.strip() != '']
                raw_df = raw_df[raw_df[rn_col].astype(str).str.strip() != 'nan']
                raw_df = raw_df[raw_df[rn_col].astype(str).str.strip() != 'N/A']
            
            if raw_df.empty:
                st.warning("No REGISTERED marks found. Try broadening your keywords.")
                st.stop()
                
            # Build the clean UI DataFrame
            ui_df = pd.DataFrame()
            ui_df['Serial'] = raw_df[sn_col].astype(str).str.replace(r'\.0$', '', regex=True)
            ui_df['Reg Number'] = raw_df[rn_col].astype(str).str.replace(r'\.0$', '', regex=True)
            ui_df['Mark'] = raw_df[mark_col].astype(str)
            ui_df['Owner'] = raw_df[owner_col].astype(str)
            ui_df['Status'] = raw_df[status_col].astype(str) if status_col else "Live"
            ui_df['Raw Goods'] = raw_df[goods_col].astype(str)
            
            # EXACT MATCH FILTER & SCORING ALGORITHM
            def clean_goods_exact_scored(text, c_cls, t_cls, c_kws, t_kws):
                if not isinstance(text, str): return "", 0
                segments = re.finditer(r'IC\s*0*(\d+)[\s.:]+(.*?)(?=IC\s*\d+|$)', text, re.IGNORECASE | re.DOTALL)
                
                class_kws = {}
                if c_cls: class_kws[c_cls.lstrip('0')] = [k.lower().strip(".;, ") for k in c_kws]
                if t_cls: 
                    t_str = t_cls.lstrip('0')
                    class_kws[t_str] = class_kws.get(t_str, []) + [k.lower().strip(".;, ") for k in t_kws]
                    
                filtered = []
                score = 0
                
                for match in segments:
                    cls_num = match.group(1)
                    raw_desc = match.group(2).strip().rstrip(';')
                    
                    # ENFORCE STRICT CLASS MATCHING (Ignores IC 018, 025, etc.)
                    if cls_num in class_kws:
                        kws = class_kws[cls_num]
                        clean_desc = re.sub(r'(?i)US\s*[\d\s,]+[.:]\s*', '', raw_desc)
                        clean_desc = re.sub(r'(?i)G\s*&\s*S\s*[:.]\s*', '', clean_desc)
                        clauses = [c.strip() for c in clean_desc.split(';')]
                        
                        exact_matches = []
                        partial_matches = []
                        
                        for clause in clauses:
                            c_lower = clause.lower().strip(".;, ")
                            matched_exact = False
                            matched_list = False
                            
                            for kw in kws:
                                if c_lower == kw:
                                    matched_exact = True
                                    break
                                sub_items = [x.strip(".;, ") for x in c_lower.split(',')]
                                if kw in sub_items:
                                    matched_list = True
                                    break
                                    
                            if matched_exact:
                                exact_matches.append(clause)
                                score += 100 
                            elif matched_list:
                                exact_matches.append(clause)
                                score += 50  
                            else:
                                for kw in kws:
                                    if re.search(rf'\b{re.escape(kw)}\b', c_lower):
                                        partial_matches.append(clause)
                                        score += 10 
                                        break
                                        
                        if exact_matches:
                            display_desc = "; ".join(exact_matches)
                        elif partial_matches:
                            display_desc = "; ".join(partial_matches)
                        else:
                            display_desc = clean_desc 
                            
                        filtered.append(f"IC {cls_num.zfill(3)}: {display_desc}")
                        
                # Use double-newlines so Streamlit stacks them perfectly
                return "\n\n".join(filtered) if filtered else "", score

            # Apply Logic
            applied = ui_df['Raw Goods'].apply(lambda x: clean_goods_exact_scored(x, c_class, t_class, c_clean, t_clean))
            ui_df['Filtered Goods'] = applied.apply(lambda x: x[0])
            ui_df['MatchScore'] = applied.apply(lambda x: x[1])
            
            # Remove rows that had 0 matching classes (This eliminates the IC 018 glitch)
            ui_df = ui_df[ui_df['Filtered Goods'] != ""]
            
            # Sort by highest match score, then drop the hidden utility columns
            ui_df = ui_df.sort_values(by='MatchScore', ascending=False).reset_index(drop=True)
            ui_df = ui_df.drop(columns=['Raw Goods', 'MatchScore'])
            
            st.session_state['bridging_results'] = ui_df
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
        
        # Configure the TextColumn to explicitly allow multiline text wrapping
        edited_df = st.data_editor(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Select": st.column_config.CheckboxColumn("Select", help="Check to include in LOP"),
                "Filtered Goods": st.column_config.TextColumn("Filtered Goods", width="large")
            }
        )