import streamlit as st
import pandas as pd
import tempfile
import os
from fpdf import FPDF
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
        owner_name = st.text_input("Exact Owner / Applicant Name", placeholder="e.g. ABC BREWING")
    with col2:
        ic_classes = st.text_input("International Classes (optional, comma-separated)", placeholder="e.g. 032, 033")

    exclude_marks = st.text_input("Marks to Exclude (optional, comma-separated)", placeholder="e.g. ABC ALE")

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

        # ----------------------------------------
        # REPORT GENERATION (HTML & PDF)
        # ----------------------------------------
        
        # 1. Generate HTML
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
        
# 2. Generate PDF
        class PDF(FPDF):
            def header(self):
                # --- Embed Logo ---
                if os.path.exists("logo.jpg"):
                    self.image("logo.jpg", 10, 8, 30) # x, y, width in mm
                
                # --- Shift text to the right (x=45) ---
                self.set_x(45) 
                self.set_font('Arial', 'B', 15)
                self.set_text_color(47, 84, 150)
                self.cell(0, 8, 'Trademark Status Report', 0, 1, 'L')
                
                self.set_x(45)
                self.set_font('Arial', '', 10)
                self.set_text_color(51, 51, 51)
                self.cell(0, 5, f'Owner Searched: {owner_name}', 0, 1, 'L')
                
                self.set_x(45)
                self.cell(0, 5, f'Date Generated: {datetime.now().strftime("%B %d, %Y")}', 0, 1, 'L')
                self.ln(10) # Add a line break below the header

        pdf = PDF(orientation='P') # Set to Portrait
        pdf.add_page()
        pdf.set_font('Arial', 'B', 8)
        pdf.set_fill_color(242, 242, 242)
        
        # Setup Table Columns for Portrait (190mm total width)
        headers = ['Mark', 'S/N', 'R/N', 'Status', 'Next Deadline', 'Reg Date', 'Goods']
        col_widths = [35, 17, 17, 13, 35, 18, 55] 
        
        for i in range(len(headers)):
            pdf.cell(col_widths[i], 8, headers[i], 1, 0, 'C', 1)
        pdf.ln()
        
        # Add Data to PDF Table
        pdf.set_font('Arial', '', 7)
        line_height = 4
        
        for _, row in report_df.iterrows():
            def clean(val):
                # Clean unsupported characters
                return str(val).replace('“', '"').replace('”', '"').replace("’", "'").encode('latin-1', 'replace').decode('latin-1')
            
            texts = [
                clean(row['Mark']),
                clean(row['S/N']),
                clean(row['R/N']),
                clean(row['Status']),
                clean(row['Next Deadline']),
                clean(row['Registration Date']),
                clean(row['Goods & Services'])
            ]
            
            # Calculate row height based on text wrapping
            max_lines = 1
            for i, text in enumerate(texts):
                text_width = pdf.get_string_width(text)
                # Calculate how many lines this specific text will take up
                lines = max(1, int((text_width * 1.05) / (col_widths[i] - 2)) + 1)
                if lines > max_lines:
                    max_lines = lines
                    
            row_height = max_lines * line_height
            
            # Check if we need a page break before drawing the row
            if pdf.get_y() + row_height > 275:
                pdf.add_page()
            
            x_start = pdf.get_x()
            y_start = pdf.get_y()
            
            # Draw cells
            for i, text in enumerate(texts):
                # 1. Draw the border rectangle
                pdf.rect(x_start, y_start, col_widths[i], row_height)
                
                # 2. Position cursor inside the rectangle with 1mm padding
                pdf.set_xy(x_start + 1, y_start + 1)
                
                # 3. Print the wrapping text without drawing new borders
                align = 'L' if i in [0, 4, 6] else 'C' # Left align Mark, Deadline, Goods
                pdf.multi_cell(col_widths[i] - 2, line_height - 0.5, text, border=0, align=align)
                
                x_start += col_widths[i]
            
            # Reset cursor to the next line
            pdf.set_xy(10, y_start + row_height)
            
        # Save PDF to temporary memory
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            pdf.output(tmp.name)
            with open(tmp.name, "rb") as f:
                pdf_bytes = f.read()

        # 3. Display Side-by-Side Download Buttons
        dl_col1, dl_col2 = st.columns(2)
        
        with dl_col1:
            st.download_button(
                label="📄 Download HTML Report",
                data=html_report,
                file_name=f"Trademark_Report_{owner_name.replace(' ', '_')}.html",
                mime="text/html",
                use_container_width=True
            )
            
        with dl_col2:
            st.download_button(
                label="📥 Download PDF Report",
                data=pdf_bytes,
                file_name=f"Trademark_Report_{owner_name.replace(' ', '_')}.pdf",
                mime="application/pdf",
                use_container_width=True
            )