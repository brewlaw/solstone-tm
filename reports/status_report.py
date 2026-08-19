import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from playwright.sync_api import sync_playwright
from scrapers.uspto_scraper import scrape_uspto

def calculate_deadline(reg_date_str):
    if not reg_date_str or reg_date_str == "N/A": 
        return "Not Registered"
    try:
        reg_date = pd.to_datetime(reg_date_str)
        current_date = datetime.now()
        
        year_5 = reg_date + relativedelta(years=5)
        year_6 = reg_date + relativedelta(years=6)
        year_9 = reg_date + relativedelta(years=9)
        year_10 = reg_date + relativedelta(years=10)
        
        if current_date <= year_6:
            return f"Sec 8: {year_5.strftime('%Y-%m-%d')} to {year_6.strftime('%Y-%m-%d')}"
        else:
            return f"Sec 8 & 9: {year_9.strftime('%Y-%m-%d')} to {year_10.strftime('%Y-%m-%d')}"
    except:
        return "Unknown"

def run():
    st.header("Trademark Status Report Generator")
    st.write("Generate a clean maintenance and status report for an exact owner/applicant.")

    col1, col2 = st.columns(2)
    with col1:
        owner_name = st.text_input("Exact Owner / Applicant Name", placeholder="e.g. Virginia Ciderworks")
    with col2:
        ic_classes = st.text_input("International Classes (optional, comma-separated)", placeholder="e.g. 032, 033")

    exclude_marks = st.text_input("Marks to Exclude (optional, comma-separated)", placeholder="e.g. HAZY HOPPED")

    if st.button("Generate Status Report", type="primary"):
        if not owner_name.strip():
            st.warning("Please enter an Owner/Applicant Name.")
            return

        # Build query using modern USPTO syntax
        query_parts = [f'ON:"{owner_name.strip().lower()}"', 'LD:true']
        if ic_classes.strip():
            classes = [c.strip().zfill(3) for c in ic_classes.split(",") if c.strip()]
            if classes:
                class_str = " OR ".join([f'IC:{c}' for c in classes])
                query_parts.append(f'({class_str})')
        
        primary_query = " AND ".join(query_parts)
        target_class_list = [c.strip().zfill(3) for c in ic_classes.split(",") if c.strip()] if ic_classes.strip() else None

        with st.spinner("Scraping USPTO trademark records..."):
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    excel_out = f"temp_{owner_name.replace(' ', '_')}.xlsx"
                    raw_results = scrape_uspto(
                        page=page,
                        primary_query=primary_query,
                        excel_filename=excel_out,
                        target_classes=target_class_list
                    )
                    browser.close()
            except Exception as e:
                st.error(f"Error scraping USPTO: {e}")
                return

        if not raw_results:
            st.info("No live marks found matching your query.")
            return

        df = pd.DataFrame(raw_results)

        # Apply exclusions
        if exclude_marks.strip():
            exclusions = [m.strip().upper() for m in exclude_marks.split(",") if m.strip()]
            df = df[~df['mark'].str.upper().isin(exclusions)]

        # Calculate deadlines
        df['next_deadline'] = df['reg_date'].apply(calculate_deadline)

        # Format table for display
        report_df = df[['mark', 'serial', 'reg_number', 'status', 'next_deadline', 'reg_date', 'goods']].copy()
        report_df.columns = ['Mark', 'S/N', 'R/N', 'Status', 'Next Deadline', 'Registration Date', 'Goods & Services']

        st.success(f"Found {len(report_df)} mark(s)!")
        st.dataframe(report_df, use_container_width=True)

        # Download HTML report
        html_table = report_df.to_html(index=False, escape=False)
        html_report = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 30px; }}
                h1 {{ color: #2F5496; }}
                table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
                th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; font-size: 13px; }}
                th {{ background-color: #f2f2f2; color: #333; }}
                tr:nth-child(even) {{ background-color: #f9f9f9; }}
            </style>
        </head>
        <body>
            <h1>Trademark Status Report</h1>
            <p><strong>Owner Searched:</strong> {owner_name}</p>
            <p><strong>Class Filter:</strong> {ic_classes if ic_classes else 'All Live Classes'}</p>
            <p><strong>Date Generated:</strong> {datetime.now().strftime('%B %d, %Y')}</p>
            <hr>
            {html_table}
        </body>
        </html>
        """
        
        st.download_button(
            label="Download HTML Report",
            data=html_report,
            file_name=f"Trademark_Report_{owner_name.replace(' ', '_')}.html",
            mime="text/html"
        )