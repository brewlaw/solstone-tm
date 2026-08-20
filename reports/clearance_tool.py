import os
import re
import gc
import datetime
import streamlit as st
from playwright.sync_api import sync_playwright

from scrapers.uspto_scraper import scrape_uspto
from scrapers.ttb_scraper import scrape_ttb
from scrapers.google_scraper import scrape_google
from reports.pdf_generator import generate_pdf
from reports.docx_generator_2 import generate_docx_2 
from utils.saved_searches import get_saved_searches, save_search_config, delete_saved_search

OUTPUT_DIR = "outputs"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def run():
    st.header("Full Trademark Clearance Search")
    st.write("Run a comprehensive, all-time clearance search across USPTO, TTB, and Google.")

    if 'clearance_report_data' not in st.session_state:
        st.session_state['clearance_report_data'] = None

    # --- SAVED SEARCHES SELECTION ---
    saved_profiles = get_saved_searches()
    
    # Check if coming from Saved Searches Manager redirect
    active_profile_key = st.session_state.get('load_profile_key', "-- Select a Saved Search --")
    if active_profile_key not in ["-- Select a Saved Search --"] + list(saved_profiles.keys()):
        active_profile_key = "-- Select a Saved Search --"

    col_profile, col_profile_info = st.columns([3, 2])
    with col_profile:
        selected_profile = st.selectbox(
            "📂 Load Saved Quarterly Search Profile:",
            ["-- Select a Saved Search --"] + list(saved_profiles.keys()),
            index=(["-- Select a Saved Search --"] + list(saved_profiles.keys())).index(active_profile_key)
        )
    
    # Clear redirect key after loading
    if 'load_profile_key' in st.session_state:
        del st.session_state['load_profile_key']

    p_data = saved_profiles.get(selected_profile, {})
    with col_profile_info:
        if selected_profile != "-- Select a Saved Search --":
            st.info(f"🕒 **Last Ran:** {p_data.get('last_run', 'Never')}")

    # Set default values based on loaded profile
    def_client = p_data.get('client_name', '')
    def_attn = p_data.get('attention_name', '')
    def_email = p_data.get('client_email', '')
    def_mark = p_data.get('raw_mark', '')
    def_dom = p_data.get('dominant_term', '')
    def_phon = p_data.get('phonetic_term', '')
    def_conc = p_data.get('conceptual_term', '')
    def_sub = p_data.get('substring_term', '')

    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input("Client Name:", value=def_client)
        attention_name = st.text_input("Attention Name (e.g. Adeline Druart):", value=def_attn)
    with col2:
        client_email = st.text_input("Client Email(s):", value=def_email)

    raw_mark = st.text_input("Full Trademark Name:", value=def_mark, placeholder="e.g. SUN SHINE")

    st.subheader("Search Term Expansions")
    st.caption("Expand your search to catch variations, sound-alikes, meaning-alikes, and substrings.")
    col_a, col_b = st.columns(2)
    with col_a:
        dominant_term = st.text_input("Dominant/Core Word (optional):", value=def_dom).upper()
        phonetic_term = st.text_input("Phonetic Equivalent (optional):", value=def_phon).upper()
    with col_b:
        conceptual_term = st.text_input("Conceptual Equivalent (optional):", value=def_conc).upper()
        substring_term = st.text_input("Root Substring / Pun (optional):", value=def_sub).upper()

    # --- SAVE PROFILE FORM EXPANDER ---
    with st.expander("💾 Save / Update Search Profile for Quarterly Re-Runs", expanded=False):
        save_name_default = selected_profile if selected_profile != "-- Select a Saved Search --" else (f"{client_name} - {raw_mark}" if client_name and raw_mark else "")
        save_profile_name = st.text_input("Search Profile Label:", value=save_name_default, placeholder="e.g. Ocelot Brewing - Sip of Sunshine")
        if st.button("💾 Save Search Configuration"):
            if not save_profile_name.strip():
                st.error("Please enter a profile label.")
            else:
                params = {
                    'raw_mark': raw_mark,
                    'client_name': client_name,
                    'attention_name': attention_name,
                    'client_email': client_email,
                    'dominant_term': dominant_term,
                    'phonetic_term': phonetic_term,
                    'conceptual_term': conceptual_term,
                    'substring_term': substring_term,
                    'last_run': p_data.get('last_run', 'Not run yet')
                }
                save_search_config(save_profile_name.strip(), params)
                st.success(f"Search profile '{save_profile_name.strip()}' saved!")
                st.rerun()

    if st.button("Run Full Clearance Search", type="primary"):
        if not raw_mark.strip():
            st.error("Please enter a trademark name.")
            return

        squished_mark = raw_mark.replace(" ", "")
        today = datetime.datetime.now()

        words = raw_mark.split()
        web_mark_base = f'("{raw_mark}" OR "{squished_mark}")' if raw_mark != squished_mark else f'"{raw_mark}"'
        uspto_spaced = " AND ".join([f"CM2:{w}*" for w in words])
        uspto_mark = f"({uspto_spaced}) OR (CM2:{squished_mark}*)" if raw_mark != squished_mark else uspto_spaced
        ttb_marks_list = ["%" + "%".join(words) + "%"]

        secondary_terms = []
        if dominant_term:
            web_mark_base += f' OR "{dominant_term}"'
            secondary_terms.append(f"(CM2:*{dominant_term}*)") 
            ttb_marks_list.append(f"%{dominant_term}%")
        if phonetic_term:
            web_mark_base += f' OR "{phonetic_term}"'
            secondary_terms.append(f"(CM2:*{phonetic_term}*)")
            ttb_marks_list.append(f"%{phonetic_term}%")
        if conceptual_term:
            web_mark_base += f' OR "{conceptual_term}"'
            secondary_terms.append(f"(CM2:*{conceptual_term}*)")
            ttb_marks_list.append(f"%{conceptual_term}%")
        if substring_term:
            web_mark_base += f' OR "{substring_term}"'
            secondary_terms.append(f"(CM2:*{substring_term}*)")
            ttb_marks_list.append(f"%{substring_term}%")

        class_filter = ' AND IC:("030" OR "032" OR "033" OR "043")'
        date_filter = "" 

        primary_uspto_query = f"({uspto_mark}){class_filter}{date_filter}"
        secondary_uspto_query = f"({' OR '.join(secondary_terms)}){class_filter}{date_filter}" if secondary_terms else None

        safe_mark = re.sub(r'[^A-Z0-9]', '_', squished_mark.upper())
        timestamp = today.strftime("%H%M%S")
        excel_filename = os.path.join(OUTPUT_DIR, f"{safe_mark}-USPTO-EXPORT-{today.strftime('%Y-%m-%d')}_{timestamp}.xlsx")

        with st.spinner("Scraping USPTO, TTB, and Google... This may take a few minutes."):
            try:
                with sync_playwright() as p:
                    cloud_args = [
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--single-process',
                        '--no-zygote',
                        '--disable-blink-features=AutomationControlled'
                    ]

                    # --- 1. Run USPTO Search ---
                    browser = p.chromium.launch(headless=True, args=cloud_args)
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        accept_downloads=True,
                        permissions=[]
                    )
                    page = context.new_page()
                    uspto_data = scrape_uspto(page, primary_uspto_query, excel_filename, secondary_uspto_query)
                    context.close()
                    browser.close() 
                    gc.collect()

                    # --- 2. Run TTB Search (IN CHUNKS) ---
                    ttb_chunks = [
                        ("01/01/1985", "12/31/1999"),
                        ("01/01/2000", "12/31/2014"),
                        ("01/01/2015", today.strftime("%m/%d/%Y"))
                    ]
                    
                    raw_ttb_data = []
                    for start_date, end_date in ttb_chunks:
                        # FIX: Launch a brand new browser for EVERY chunk to prevent memory crashes!
                        browser = p.chromium.launch(headless=True, args=cloud_args)
                        context = browser.new_context(
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            accept_downloads=True
                        )
                        chunk_page = context.new_page()
                        
                        chunk_results = scrape_ttb(chunk_page, start_date, end_date, list(set(ttb_marks_list)))
                        if chunk_results:
                            raw_ttb_data.extend(chunk_results)
                        
                        # Close this browser entirely before looping to the next chunk
                        chunk_page.close()
                        context.close()
                        browser.close() 
                        gc.collect()
                    
                    unique_ttb = {item['ttb_id']: item for item in raw_ttb_data}
                    ttb_data = list(unique_ttb.values())

                # --- 3. Run Google Search ---
                google_date_from = "1900-01-01"
                google_date_to = today.strftime("%Y-%m-%d")
                google_data = scrape_google(web_mark_base, raw_mark, google_date_from, google_date_to)

                # --- Report Generation ---
                base_filename = f"Clearance_Report_{safe_mark}"
                report_title = f"Clearance Report - {raw_mark.upper()}"
                pdf_filename = os.path.join(OUTPUT_DIR, f"{base_filename}.pdf")
                docx_filename = os.path.join(OUTPUT_DIR, f"{base_filename}.docx")
                report_date = today.strftime("%B %d, %Y")

                page_data = generate_pdf(raw_mark, squished_mark, "01/01/1985", today.strftime("%m/%d/%Y"), uspto_data, ttb_data, google_data, pdf_filename, report_title)
                
                generate_docx_2(
                    client_name=client_name,
                    attention_name=attention_name,
                    email=client_email,
                    report_date=report_date,
                    raw_mark=raw_mark,
                    report_title=report_title,
                    page_data=page_data,
                    output_filename=docx_filename,
                    feedback_summary=[]
                )

                with open(pdf_filename, "rb") as f:
                    pdf_bytes = f.read()
                with open(docx_filename, "rb") as f:
                    docx_bytes = f.read()

                # Automatically update 'last_run' timestamp if profile is active
                if selected_profile != "-- Select a Saved Search --":
                    p_data['last_run'] = today.strftime("%B %d, %Y")
                    save_search_config(selected_profile, p_data)

                st.session_state['clearance_report_data'] = {
                    'base_filename': base_filename,
                    'pdf_filename': pdf_filename,
                    'docx_filename': docx_filename,
                    'pdf_bytes': pdf_bytes,
                    'docx_bytes': docx_bytes
                }

            except Exception as e:
                st.error(f"Error during search execution: {e}")

    # --- DISPLAY REPORT OUTPUTS IF GENERATED ---
    if st.session_state.get('clearance_report_data'):
        c_data = st.session_state['clearance_report_data']
        st.success("Search & Report Generation Complete!")

        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1:
            st.download_button(
                "📥 Download PDF Report",
                c_data['pdf_bytes'],
                file_name=f"{c_data['base_filename']}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        with col_d2:
            st.download_button(
                "📄 Download Word Doc Report",
                c_data['docx_bytes'],
                file_name=f"{c_data['base_filename']}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )
        with col_d3:
            if st.button("☁️ Archive to Google Drive", use_container_width=True, key="archive_clearance"):
                from utils.drive_uploader import upload_to_drive
                with st.spinner("Archiving reports to Google Drive..."):
                    pdf_link = upload_to_drive(c_data['pdf_filename'])
                    docx_link = upload_to_drive(c_data['docx_filename'])
                if pdf_link or docx_link:
                    st.success("☁️ Clearance reports successfully archived to Google Drive!")