import os
import re
import gc
import datetime
from datetime import timedelta
import streamlit as st
from playwright.sync_api import sync_playwright

from scrapers.uspto_scraper import scrape_uspto
from scrapers.ttb_scraper import scrape_ttb
from scrapers.google_scraper import scrape_google
from reports.pdf_generator import generate_pdf
from reports.docx_generator_2 import generate_docx_2 
from utils.saved_searches import get_saved_searches, save_search_config

OUTPUT_DIR = "outputs"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def get_dynamic_names(timeframe, raw_mark):
    today = datetime.date.today()
    current_year = today.year
    clean_mark = re.sub(r'[\/*?:"<>|]', '', raw_mark).strip().upper()
    
    base_filename = f"{clean_mark}_Monitoring_Report_Raw_Results"
    report_title = f"Trademark Monitoring Report Raw Results - {clean_mark}"
    
    if 0.2 <= timeframe <= 0.4:
        q_ends = {
            1: datetime.date(current_year, 3, 31),
            2: datetime.date(current_year, 6, 30),
            3: datetime.date(current_year, 9, 30),
            4: datetime.date(current_year, 12, 31)
        }
        closest_q = None
        target_year = current_year
        min_delta = float('inf')
        
        for q, end_date in q_ends.items():
            delta = abs((today - end_date).days)
            if delta < min_delta:
                min_delta = delta
                closest_q = q
                
        prev_year_q4 = datetime.date(current_year - 1, 12, 31)
        if abs((today - prev_year_q4).days) < min_delta:
            min_delta = abs((today - prev_year_q4).days)
            closest_q = 4
            target_year = current_year - 1
            
        if min_delta <= 31:
            base_filename = f"Q{closest_q} {target_year} Monitoring Report Raw Results - {clean_mark}"
            report_title = f"Q{closest_q} {target_year} Trademark Monitoring Report Raw Results - {clean_mark}"
        else:
            base_filename = f"Mid-Quarter Monitoring Report Raw Results - {clean_mark}"
            report_title = f"Mid-Quarter Trademark Monitoring Report Raw Results - {clean_mark}"
            
    elif timeframe == 0.5:
        if today.month <= 6:
            base_filename = f"Q1-Q2 {current_year} Monitoring Report Raw Results - {clean_mark}"
            report_title = f"Q1-Q2 {current_year} Trademark Monitoring Report Raw Results - {clean_mark}"
        else:
            base_filename = f"Q3-Q4 {current_year} Monitoring Report Raw Results - {clean_mark}"
            report_title = f"Q3-Q4 {current_year} Trademark Monitoring Report Raw Results - {clean_mark}"
            
    elif timeframe == 1.0:
        base_filename = f"{current_year} Monitoring Report Raw Results - {clean_mark}"
        report_title = f"{current_year} Trademark Monitoring Report Raw Results - {clean_mark}"
        
    return base_filename, report_title

def run():
    st.header("Trademark Monitoring Suite")
    st.write("Run time-constrained monitoring sweeps across USPTO, TTB, and Google.")

    if 'monitoring_report_data' not in st.session_state:
        st.session_state['monitoring_report_data'] = None

    # --- SAVED MONITORING PROFILES ---
    saved_profiles = get_saved_searches()
    
    active_profile_key = st.session_state.get('load_monitoring_key', "-- Select a Saved Monitoring Profile --")
    if active_profile_key not in ["-- Select a Saved Monitoring Profile --"] + list(saved_profiles.keys()):
        active_profile_key = "-- Select a Saved Monitoring Profile --"

    col_profile, col_profile_info = st.columns([3, 2])
    with col_profile:
        selected_profile = st.selectbox(
            "📂 Load Saved Monitoring Profile:",
            ["-- Select a Saved Monitoring Profile --"] + list(saved_profiles.keys()),
            index=(["-- Select a Saved Monitoring Profile --"] + list(saved_profiles.keys())).index(active_profile_key)
        )
    
    if 'load_monitoring_key' in st.session_state:
        del st.session_state['load_monitoring_key']

    p_data = saved_profiles.get(selected_profile, {})
    with col_profile_info:
        if selected_profile != "-- Select a Saved Monitoring Profile --":
            st.info(f"🕒 **Last Ran:** {p_data.get('last_run', 'Never')}")

    # Set default values based on loaded profile
    def_client = p_data.get('client_name', '')
    def_attn = p_data.get('attention_name', '')
    def_email = p_data.get('client_email', '')
    def_lookback = float(p_data.get('lookback_years', 1.0))
    def_mark = p_data.get('raw_mark', '')
    def_dom = p_data.get('dominant_term', '')
    def_phon = p_data.get('phonetic_term', '')
    def_conc = p_data.get('conceptual_term', '')
    def_sub = p_data.get('substring_term', '')

    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input("Client Name:", value=def_client)
        attention_name = st.text_input("Attention Name (e.g. Adeline Druart):", value=def_attn)
        use_letterhead = st.checkbox("📄 Export Word Doc on Firm Letterhead", value=False)
    with col2:
        client_email = st.text_input("Client Email(s):", value=def_email)
        lookback_years = st.number_input("Lookback Years:", min_value=0.1, max_value=5.0, value=def_lookback, step=0.25)

    raw_mark = st.text_input("Full Trademark Name:", value=def_mark, placeholder="e.g. SUN SHINE (include spaces if applicable)")

    st.subheader("Search Term Expansions")
    st.caption("Expand your search to catch variations, sound-alikes, meaning-alikes, and substrings.")
    col_a, col_b = st.columns(2)
    with col_a:
        dominant_term = st.text_input("Dominant/Core Word (optional):", value=def_dom).upper()
        phonetic_term = st.text_input("Phonetic Equivalent (optional):", value=def_phon).upper()
    with col_b:
        conceptual_term = st.text_input("Conceptual Equivalent (optional):", value=def_conc).upper()
        substring_term = st.text_input("Root Substring / Pun (optional):", value=def_sub).upper()

    # --- SAVE PROFILE EXPANDER ---
    with st.expander("💾 Save / Update Monitoring Profile for Quarterly Sweeps", expanded=False):
        save_name_default = selected_profile if selected_profile != "-- Select a Saved Monitoring Profile --" else (f"{client_name} - {raw_mark}" if client_name and raw_mark else "")
        save_profile_name = st.text_input("Monitoring Profile Label:", value=save_name_default, placeholder="e.g. Ocelot Brewing - Quarterly Monitoring")
        if st.button("💾 Save Monitoring Profile"):
            if not save_profile_name.strip():
                st.error("Please enter a profile label.")
            else:
                params = {
                    'raw_mark': raw_mark,
                    'client_name': client_name,
                    'attention_name': attention_name,
                    'client_email': client_email,
                    'lookback_years': lookback_years,
                    'dominant_term': dominant_term,
                    'phonetic_term': phonetic_term,
                    'conceptual_term': conceptual_term,
                    'substring_term': substring_term,
                    'last_run': p_data.get('last_run', 'Not run yet')
                }
                save_search_config(save_profile_name.strip(), params)
                st.success(f"Monitoring profile '{save_profile_name.strip()}' saved!")
                st.rerun()

    if st.button("Run Monitoring Search", type="primary"):
        if not raw_mark.strip():
            st.error("Please enter a trademark name.")
            return

        squished_mark = raw_mark.replace(" ", "")
        today = datetime.datetime.now()
        
        timeframe = lookback_years
        start_date = today - timedelta(days=(timeframe * 365.25))

        ttb_date_to = today.strftime("%m/%d/%Y")
        uspto_date_to = today.strftime("%Y%m%d")
        google_date_to = today.strftime("%Y-%m-%d")
        ttb_date_from = start_date.strftime("%m/%d/%Y")
        uspto_date_from = start_date.strftime("%Y%m%d")
        google_date_from = start_date.strftime("%Y-%m-%d")

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
        date_filter = f" AND FD:[{uspto_date_from} TO {uspto_date_to}]" 

        primary_uspto_query = f"({uspto_mark}){class_filter}{date_filter}"
        secondary_uspto_query = f"({' OR '.join(secondary_terms)}){class_filter}{date_filter}" if secondary_terms else None

        safe_mark = re.sub(r'[^A-Z0-9]', '_', squished_mark.upper())
        timestamp = today.strftime("%H%M%S")
        excel_filename = os.path.join(OUTPUT_DIR, f"{safe_mark}-USPTO-EXPORT-{today.strftime('%Y-%m-%d')}_{timestamp}.xlsx")

        with st.spinner(f"Scraping USPTO, TTB, and Google from {ttb_date_from} to present..."):
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

                    # --- 2. Run TTB Search ---
                    browser = p.chromium.launch(headless=True, args=cloud_args)
                    context = browser.new_context(
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        accept_downloads=True
                    )
                    page = context.new_page()
                    ttb_data = scrape_ttb(page, ttb_date_from, ttb_date_to, list(set(ttb_marks_list)))
                    context.close()
                    browser.close() 
                    gc.collect()

                # --- 3. Run Google Search ---
                google_data = scrape_google(web_mark_base, raw_mark, google_date_from, google_date_to)

                # --- Report Generation ---
                base_filename, report_title = get_dynamic_names(timeframe, raw_mark)
                pdf_filename = os.path.join(OUTPUT_DIR, f"{base_filename}.pdf")
                docx_filename = os.path.join(OUTPUT_DIR, f"{base_filename}.docx")
                report_date = today.strftime("%B %d, %Y")

                page_data = generate_pdf(raw_mark, squished_mark, ttb_date_from, ttb_date_to, uspto_data, ttb_data, google_data, pdf_filename, report_title)
                
                generate_docx_2(
                    client_name=client_name,
                    attention_name=attention_name,
                    email=client_email,
                    report_date=report_date,
                    raw_mark=raw_mark,
                    report_title=report_title,
                    page_data=page_data,
                    output_filename=docx_filename,
                    feedback_summary=[],
                    use_letterhead=use_letterhead
                )

                with open(pdf_filename, "rb") as f:
                    pdf_bytes = f.read()
                with open(docx_filename, "rb") as f:
                    docx_bytes = f.read()

                # Update 'last_run' timestamp if profile is loaded
                if selected_profile != "-- Select a Saved Monitoring Profile --":
                    p_data['last_run'] = today.strftime("%B %d, %Y")
                    save_search_config(selected_profile, p_data)

                st.session_state['monitoring_report_data'] = {
                    'base_filename': base_filename,
                    'pdf_filename': pdf_filename,
                    'docx_filename': docx_filename,
                    'pdf_bytes': pdf_bytes,
                    'docx_bytes': docx_bytes
                }

            except Exception as e:
                st.error(f"Error during search execution: {e}")

    # --- DISPLAY REPORT OUTPUTS IF GENERATED ---
    if st.session_state.get('monitoring_report_data'):
        m_data = st.session_state['monitoring_report_data']
        st.success("Monitoring Search & Report Generation Complete!")

        col_d1, col_d2, col_d3 = st.columns(3)
        with col_d1:
            st.download_button(
                "📥 Download PDF Report",
                m_data['pdf_bytes'],
                file_name=f"{m_data['base_filename']}.pdf",
                mime="application/pdf",
                use_container_width=True
            )
        with col_d2:
            st.download_button(
                "📄 Download Word Doc Report",
                m_data['docx_bytes'],
                file_name=f"{m_data['base_filename']}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True
            )
        with col_d3:
            if st.button("☁️ Archive to Google Drive", use_container_width=True, key="archive_monitoring"):
                from utils.drive_uploader import upload_to_drive
                with st.spinner("Archiving reports to Google Drive..."):
                    pdf_link = upload_to_drive(m_data['pdf_filename'])
                    docx_link = upload_to_drive(m_data['docx_filename'])
                if pdf_link or docx_link:
                    st.success("☁️ Monitoring reports successfully archived to Google Drive!")