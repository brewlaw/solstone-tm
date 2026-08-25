import streamlit as st
import pandas as pd
from playwright.sync_api import sync_playwright

# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------
def format_class_input(class_input):
    """Pads classes to 3 digits (e.g., '32' -> '032')."""
    if not class_input: return []
    return [c.strip().zfill(3) for c in class_input.split(",") if c.strip()]

def fetch_tsdr_data(serial_number, target_classes):
    """Scrapes the Mark Name and specific Class Goods from TSDR."""
    if not serial_number: return None, None
        
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu', '--single-process']
        )
        page = browser.new_page()
        
        try:
            url = f"https://tsdr.uspto.gov/#caseNumber={serial_number}&caseSearchType=US_APPLICATION&caseType=DEFAULT&searchType=statusSearch"
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.wait_for_selector("div.goodsServicesList", timeout=10000)
            
            mark_name = page.locator("div.markElement").first.inner_text().strip() if page.locator("div.markElement").is_visible() else "Unknown Mark"
            
            # For now, grabbing all goods text. We can refine this to target specific classes in a future update.
            goods_text = page.locator("div.goodsServicesList").inner_text().strip() 
            
            browser.close()
            return mark_name, goods_text
        except Exception as e:
            browser.close()
            return None, f"Error fetching data: {str(e)}"

# ---------------------------------------------------------
# MAIN APP FLOW
# ---------------------------------------------------------
def run():
    st.header("Letter of Protest Generator")
    st.write("Extract goods/services, run a bridging search, and generate a compliant Exhibit A PDF.")
    
    # Initialize Session State Variables
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
        with st.spinner("Scraping TSDR..."):
            client_mark, client_goods = fetch_tsdr_data(client_sn.strip(), format_class_input(client_class))
            target_mark, target_goods = fetch_tsdr_data(target_sn.strip(), format_class_input(target_class))
            
            st.session_state['client_mark'] = client_mark
            st.session_state['client_goods'] = client_goods
            st.session_state['target_mark'] = target_mark
            st.session_state['target_goods'] = target_goods
            st.session_state['client_class_fmt'] = format_class_input(client_class)
            st.session_state['target_class_fmt'] = format_class_input(target_class)
            st.session_state['lop_step'] = 2

    # Display Editable Text Areas
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
            with st.spinner("Searching USPTO for Bridging Registrations..."):
                # TODO: Connect to your actual USPTO Scraper here!
                # For UI demonstration, generating dummy data:
                dummy_data = [
                    {"Select": False, "Mark": "MOUNTAIN BREW", "Reg Num": "5432109", "Status": "LIVE/REGISTRATION", "Goods": "Beer; Restaurant services"},
                    {"Select": False, "Mark": "RIVER RUNNERS", "Reg Num": "6543210", "Status": "LIVE/REGISTRATION", "Goods": "Ale; Taproom services"},
                    {"Select": False, "Mark": "VALLEY HOPS", "Reg Num": "7654321", "Status": "LIVE/REGISTRATION", "Goods": "Craft beer; Brewpub services"},
                    {"Select": False, "Mark": "CITY TAPS", "Reg Num": "8765432", "Status": "LIVE/REGISTRATION", "Goods": "Lager; Bar services"},
                    {"Select": False, "Mark": "ISLAND ALES", "Reg Num": "9876543", "Status": "LIVE/REGISTRATION", "Goods": "Porter; Providing of food and drink"},
                    {"Select": False, "Mark": "DESERT STOUT", "Reg Num": "1098765", "Status": "LIVE/REGISTRATION", "Goods": "Stout; Tavern services"},
                ]
                st.session_state['bridging_results'] = pd.DataFrame(dummy_data)
                st.session_state['lop_step'] = 3

    # ==========================================
    # STEP 3: RESULTS & SELECTION
    # ==========================================
    if st.session_state['lop_step'] >= 3:
        st.divider()
        st.markdown("### Step 3: Select Evidence (Max 5)")
        st.caption("Select up to 5 of the strongest bridging registrations. Evidence must be based on USE in commerce.")
        
        # Interactive Data Editor with Checkboxes
        edited_df = st.data_editor(
            st.session_state['bridging_results'],
            column_config={"Select": st.column_config.CheckboxColumn("Select", help="Check to include in LoP", default=False)},
            disabled=["Mark", "Reg Num", "Status", "Goods"],
            hide_index=True,
            use_container_width=True
        )
        
        # Calculate Selected
        selected_rows = edited_df[edited_df["Select"] == True]
        selected_count = len(selected_rows)
        
        # Real-time counter
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
            st.write("These registrations will be fetched from TSDR and compiled into Exhibit A:")
            st.dataframe(selected_rows[["Mark", "Reg Num", "Goods"]], hide_index=True, use_container_width=True)
            
            if st.button("📄 Generate Exhibit A (PDF)", type="primary"):
                st.info(f"Initiating Playwright to download TSDR status pages for {selected_count} marks and compile Exhibit A...")
                # TODO: Trigger TSDR PDF Generation, Merge, and Download Button here!
