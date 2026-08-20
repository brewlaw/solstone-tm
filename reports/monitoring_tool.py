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
from analyzers.section_2e_analyzer import Section2EAnalyzer

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

    analyzer = Section2EAnalyzer(data_dir="data")
    feedback_summary = []

    raw_mark = st.text_input("Full Trademark Name:", placeholder="e.g. SUN SHINE (include spaces if applicable)")

    # Real-time Section 2(e) Risk Analysis
    if raw_mark.strip():
        raw_risk_data, feedback_summary = analyzer.analyze_mark(raw_mark, "Monitoring")
        with st.expander("⚠️ Section 2(e) Analysis & Risk Feedback", expanded=True):
            for statement in feedback_summary:
                st.warning(f"- {statement}")

    col1, col2 = st.columns(2)
    with col1:
        client_name = st.text_input("Client Name:")
        attention_name = st.text_input("Attention Name (e.g. Adeline Druart):")
    with col2:
        client_email = st.text_input("Client Email(s):")
        lookback_years = st.number_input("Lookback Years:", min_value=0.1, max_value=5.0, value=1.0, step=0.25)

    st.subheader("Search Term Expansions")
    st.caption("Expand your search to catch variations, sound-alikes, meaning-alikes, and substrings.")
    col_a, col_b = st.columns(2)
    with col_a:
        dominant_term = st.text_input("Dominant/Core Word (optional):").upper()
        phonetic_term = st.text_input("Phonetic Equivalent (optional):").upper()
    with col_b:
        conceptual_term = st.text_input("Conceptual Equivalent (optional):").upper()
        substring_term = st.text_input("Root Substring / Pun (optional):").upper()

    if st.button("Run Monitoring Search", type="primary"):
        if not raw_mark.strip():
            st.error("Please enter a trademark name.")
            return

        squished_mark = raw_mark.replace(" ", "")
        today = datetime.datetime.now()
        
        # Calculate Date Bounds for Monitoring
        timeframe = lookback_years
        start_date = today - timedelta(days=(timeframe * 365.25))

        ttb_date_to = today.strftime("%m/%d/%Y")
        uspto_date_to = today.strftime("%Y%m%d")
        google_date_to = today.strftime("%Y-%m-%d")
        ttb_date_from = start_date.strftime("%m/%d/%Y")
        uspto_date_from = start_date.strftime("%Y%m%d")
        google_date_from = start_date.strftime("%Y-%m-%d")

        # Build Original USPTO & TTB Queries
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

        # USPTO Strict Date Filters
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

                    # --- 2. Run TTB Search (Single Pass) ---
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
                    feedback_summary=feedback_summary
                )

                st.success("Monitoring Search & Report Generation Complete!")

                with open(pdf_filename, "rb") as f:
                    st.download_button("Download PDF Report", f, file_name=f"{base_filename}.pdf", mime="application/pdf")
                with open(docx_filename, "rb") as f:
                    st.download_button("Download Word Doc Report", f, file_name=f"{base_filename}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

            except Exception as e:
                st.error(f"Error during search execution: {e}")