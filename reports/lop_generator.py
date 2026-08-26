import streamlit as st
import time
import re
import gc
import os
import pandas as pd
from playwright.sync_api import sync_playwright

# Import your actual USPTO scraper
from scrapers.uspto_scraper import scrape_uspto

# Default related terms lookup for popular classes
DEFAULT_RELATED_TERMS = {
    "032": ["malt beverages", "ale", "porter", "stout", "lager", "hard seltzer", "non-alcoholic beverages", "fruit-flavored beverages", "cider"],
    "043": ["bar services", "restaurant services", "cocktail lounge services", "pub services", "taproom services", "catering", "bar and restaurant services"],
    "033": ["alcoholic beverages", "wine", "spirits", "liquor", "cocktails", "distilled spirits", "vodka", "whiskey"],
    "030": ["coffee", "tea", "bakery goods", "confectionery", "snacks", "sauces"],
    "025": ["clothing", "shirts", "hats", "apparel", "footwear", "headwear"],
    "035": ["retail store services", "online retail store services", "advertising services"],
    "041": ["entertainment services", "organizing events", "nightclub services"]
}

# ==========================================
# 1. HELPER: PARSE GOODS INTO CHECKLIST
# ==========================================
def parse_goods_to_df(raw_goods):
    """Splits raw goods text by semicolons/newlines into a DataFrame for the checklist UI."""
    if not raw_goods or "Goods boundaries not found" in raw_goods:
        return pd.DataFrame({"Select": [False], "Keyword": [raw_goods]})
    
    raw_items = re.split(r'[;\n]', raw_goods)
    cleaned_items = [item.strip() for item in raw_items if item.strip()]
            
    seen = set()
    unique_items = [x for x in cleaned_items if not (x in seen or seen.add(x))]
    
    if not unique_items:
        return pd.DataFrame({"Select": [], "Keyword": []})
        
    return pd.DataFrame({"Select": [False] * len(unique_items), "Keyword": unique_items})

# ==========================================
# 2. TSDR COMBINED SCRAPER (SINGLE BROWSER)
# ==========================================
def fetch_both_tsdr_data(client_sn, app_sn):
    """Fetches Client AND Applicant TSDR data inside a single browser tab using human search box navigation."""
    results = {
        "client": ("Unknown Mark", "Goods boundaries not found. Please manually copy from TSDR."),
        "applicant": ("Unknown Mark", "Goods boundaries not found. Please manually copy from TSDR.")
    }
    
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
        
        js_extract = """
        () => {
            let markName = "Unknown Mark";
            let goodsArray = [];
            
            // Extract Mark Name
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
            
            // Extract Goods
            let rows = document.querySelectorAll('div.row');
            for (let row of rows) {
                let keyNode = row.querySelector('div.key');
                let valNode = row.querySelector('div.value');
                if (keyNode && valNode) {
                    if (keyNode.textContent.trim() === 'For:') {
                        let cleanGoods = valNode.textContent.replace(/\\s+/g,' ').trim();
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

        # --- STEP A: FETCH CLIENT DATA ---
        if client_sn:
            try:
                url = f"https://tsdr.uspto.gov/#caseNumber={client_sn}&caseSearchType=US_APPLICATION&caseType=DEFAULT&searchType=statusSearch"
                page.goto(url, timeout=30000)
                page.wait_for_function("() => document.body.innerText.includes('Mark:')", timeout=15000)
                page.wait_for_timeout(1500)
                res = page.evaluate(js_extract)
                results["client"] = (res.get('mark'), res.get('goods'))
            except Exception as e:
                results["client"] = (None, f"Error fetching client: {str(e)}")

        # --- STEP B: FETCH APPLICANT DATA (RE-USING SAME BROWSER & TAB) ---
        if app_sn:
            try:
                # If page is already open, use search box like a human
                if "tsdr.uspto.gov" in page.url:
                    search_box = page.locator('#searchNumber')
                    search_box.fill('')
                    search_box.fill(str(app_sn))
                    search_box.press("Enter")
                    
                    # Wait for TSDR to render new record
                    page.wait_for_timeout(3000)
                    page.wait_for_function("() => document.body.innerText.includes('Mark:')", timeout=15000)
                    res = page.evaluate(js_extract)
                    results["applicant"] = (res.get('mark'), res.get('goods'))
                else:
                    # Direct load fallback if client was empty
                    url = f"https://tsdr.uspto.gov/#caseNumber={app_sn}&caseSearchType=US_APPLICATION&caseType=DEFAULT&searchType=statusSearch"
                    page.goto(url, timeout=30000)
                    page.wait_for_function("() => document.body.innerText.includes('Mark:')", timeout=15000)
                    page.wait_for_timeout(1500)
                    res = page.evaluate(js_extract)
                    results["applicant"] = (res.get('mark'), res.get('goods'))
            except Exception as e:
                results["applicant"] = (None, f"Error fetching applicant: {str(e)}")

        browser.close()
        return results["client"], results["applicant"]

# ==========================================
# 3. HELPER: CLEAN & SCORE RESULTS
# ==========================================
def clean_goods_exact_scored(text, c_cls, t_cls, c_kws, t_kws):
    """Filters goods to relevant classes, isolates exact matches, and assigns a ranking score."""
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
                display_desc = exact_matches[0] 
            elif partial_matches:
                display_desc = partial_matches[0] 
            else:
                display_desc = clauses[0] if clauses else clean_desc 
                
            filtered.append(f"IC {cls_num.zfill(3)}: {display_desc}")
            
    return "\n | ".join(filtered) if filtered else "", score

def process_uspto_excel_results(excel_out, c_class, t_class, c_clean, t_clean):
    """Reads raw Excel file from scrape_uspto, filters live registrations, scores matches, and builds DF."""
    if not os.path.exists(excel_out):
        return pd.DataFrame()
        
    raw_df = pd.read_excel(excel_out)
    if raw_df.empty:
        return pd.DataFrame()
        
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
    else:
        return pd.DataFrame()
        
    if raw_df.empty:
        return pd.DataFrame()
        
    ui_df = pd.DataFrame()
    ui_df['Serial'] = raw_df[sn_col].astype(str).str.replace(r'\.0$', '', regex=True)
    ui_df['Reg Number'] = raw_df[rn_col].astype(str).str.replace(r'\.0$', '', regex=True)
    ui_df['Mark'] = raw_df[mark_col].astype(str)
    ui_df['Owner'] = raw_df[owner_col].astype(str)
    ui_df['Status'] = raw_df[status_col].astype(str) if status_col else "Live"
    ui_df['Raw Goods'] = raw_df[goods_col].astype(str)
    
    applied = ui_df['Raw Goods'].apply(lambda x: clean_goods_exact_scored(x, c_class, t_class, c_clean, t_clean))
    ui_df['Filtered Goods'] = applied.apply(lambda x: x[0])
    ui_df['MatchScore'] = applied.apply(lambda x: x[1])
    
    ui_df = ui_df[ui_df['Filtered Goods'] != ""]
    return ui_df

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
        with st.spinner("Scraping Client and Applicant Data in single browser session..."):
            c_data, a_data = fetch_both_tsdr_data(client_sn, app_sn)
            
            c_mark, c_goods = c_data
            a_mark, a_goods = a_data
            
            st.session_state['c_mark'] = c_mark
            st.session_state['c_goods_df'] = parse_goods_to_df(c_goods)
            
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
    if st.button("Execute Bridging Search", type="primary"):
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
            
            st.session_state['primary_c_kws'] = c_clean
            st.session_state['primary_t_kws'] = t_clean

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
                    _ = scrape_uspto(
                        page=page,
                        primary_query=search_query,
                        excel_filename=excel_out
                    )
                    browser.close()
            except Exception as e:
                st.error(f"Error scraping USPTO: {e}")
                st.stop()
                
            ui_df = process_uspto_excel_results(excel_out, c_class, t_class, c_clean, t_clean)
            
            if ui_df.empty:
                st.warning(f"No bridging registrations found for query: `{search_query}`. Try checking different keyword boxes.")
                st.session_state['bridging_results'] = pd.DataFrame()
            else:
                ui_df = ui_df.sort_values(by='MatchScore', ascending=False).reset_index(drop=True)
                ui_df_clean = ui_df.drop(columns=['Raw Goods', 'MatchScore'])
                st.session_state['bridging_results'] = ui_df_clean

            st.session_state['lop_step'] = 3
            st.rerun()

    # --- STEP 3: RESULTS TABLE & TERM EXPANSION ---
    if st.session_state.get('lop_step') == 3:
        st.divider()
        st.markdown("### Step 3: Select Evidence")
        
        df = st.session_state.get('bridging_results', pd.DataFrame())
        results_count = len(df)
        
        # --- EXPANSION PROMPT IF LESS THAN 10 RESULTS ---
        if results_count < 10:
            st.warning(f"⚠️ **Found {results_count} bridging registration(s).** A strong Letter of Protest ideally includes 5–10 solid evidence marks.")
            
            with st.expander("🔍 **Expand Search with Related Terms** to get 10+ results", expanded=True):
                st.write("Select or enter related USPTO terms to expand your bridging search:")
                
                raw_c = st.session_state.get('client_class', '').strip().zfill(3)
                raw_t = st.session_state.get('applicant_class', '').strip().zfill(3)
                
                # Fetch default terms for the classes
                default_c_terms = DEFAULT_RELATED_TERMS.get(raw_c.lstrip('0'), ["goods", "products"])
                default_t_terms = DEFAULT_RELATED_TERMS.get(raw_t.lstrip('0'), ["services", "providing services"])
                
                exp_col1, exp_col2 = st.columns(2)
                with exp_col1:
                    add_c_terms = st.multiselect(
                        f"Additional Client (Class {raw_c}) Terms:",
                        options=default_c_terms,
                        default=[t for t in default_c_terms[:3] if t not in st.session_state.get('primary_c_kws', [])],
                        key="add_c_terms"
                    )
                    custom_c = st.text_input("Other Client Terms (comma-separated):", placeholder="e.g., hard cider, craft beer", key="custom_c")
                
                with exp_col2:
                    add_t_terms = st.multiselect(
                        f"Additional Applicant (Class {raw_t}) Terms:",
                        options=default_t_terms,
                        default=[t for t in default_t_terms[:3] if t not in st.session_state.get('primary_t_kws', [])],
                        key="add_t_terms"
                    )
                    custom_t = st.text_input("Other Applicant Terms (comma-separated):", placeholder="e.g., restaurant services, tavern", key="custom_t")

                if st.button("🚀 Run Expanded Search", type="secondary"):
                    # Combine original and new terms
                    c_clean = list(st.session_state.get('primary_c_kws', []))
                    t_clean = list(st.session_state.get('primary_t_kws', []))
                    
                    c_clean.extend(add_c_terms)
                    if custom_c.strip():
                        c_clean.extend([x.strip() for x in custom_c.split(',') if x.strip()])
                        
                    t_clean.extend(add_t_terms)
                    if custom_t.strip():
                        t_clean.extend([x.strip() for x in custom_t.split(',') if x.strip()])
                        
                    c_clean = list(set(c_clean))
                    t_clean = list(set(t_clean))

                    with st.spinner("Running expanded USPTO search..."):
                        c_kw_str = " OR ".join([f'"{kw}"' for kw in c_clean])
                        t_kw_str = " OR ".join([f'"{kw}"' for kw in t_clean])

                        expanded_query = f'GS:({t_kw_str}) AND GS:({c_kw_str}) AND IC:{raw_c} AND IC:{raw_t} AND LD:true'
                        excel_exp_out = "temp_expanded_bridging_search.xlsx"
                        
                        try:
                            with sync_playwright() as p:
                                browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                                page = browser.new_page()
                                _ = scrape_uspto(page=page, primary_query=expanded_query, excel_filename=excel_exp_out)
                                browser.close()
                        except Exception as e:
                            st.error(f"Error during expanded search: {e}")
                            st.stop()
                            
                        exp_df = process_uspto_excel_results(excel_exp_out, raw_c, raw_t, c_clean, t_clean)
                        
                        if exp_df.empty:
                            st.warning("No additional registrations found with expanded terms.")
                        else:
                            # Merge with existing results if any existed
                            if not df.empty:
                                combined = pd.concat([df, exp_df.drop(columns=['Raw Goods', 'MatchScore'])], ignore_index=True)
                                combined = combined.drop_duplicates(subset=['Reg Number'], keep='first').reset_index(drop=True)
                                st.session_state['bridging_results'] = combined
                            else:
                                exp_df = exp_df.sort_values(by='MatchScore', ascending=False).reset_index(drop=True)
                                st.session_state['bridging_results'] = exp_df.drop(columns=['Raw Goods', 'MatchScore'])
                                
                            st.success(f"Updated results! Total registrations found: {len(st.session_state['bridging_results'])}")
                            st.rerun()

        # --- STEP 3 DISPLAY TABLE ---
        if not df.empty:
            st.write("Select the best records below to include in your Exhibit A.")
            
            if "Select" not in df.columns:
                df.insert(0, "Select", False)
            
            edited_df = st.data_editor(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Select": st.column_config.CheckboxColumn("Select", help="Check to include in LOP"),
                    "Filtered Goods": st.column_config.TextColumn("Filtered Goods", width="large")
                }
            )