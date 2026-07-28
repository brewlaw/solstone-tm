import os
import re
import textwrap 
from fpdf import FPDF

def write_safe_multiline(pdf_obj, text, max_width=85):
    clean_text = str(text).encode('latin-1', 'ignore').decode('latin-1')
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    lines = textwrap.wrap(clean_text, width=max_width, break_long_words=True)
    if not lines:
        pdf_obj.cell(0, 6, "N/A", new_x="LMARGIN", new_y="NEXT")
        return
    for line in lines:
        pdf_obj.cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")

def generate_pdf(
        raw_mark, squished_mark, ttb_date_from, ttb_date_to, uspto_results, ttb_results, web_results, output_filename, report_title):
    print("\nCompiling Master PDF Report...")

    class MasterReportPDF(FPDF):
        def header(self):
            # Uses the dynamic title (e.g. "Q2 2026 Trademark Monitoring Report Raw Results - BEAR")
            self.set_font("helvetica", "B", 14)
            self.cell(0, 10, report_title, align="C", new_x="LMARGIN", new_y="NEXT")
            self.ln(5)
            
        def footer(self):
            # Automatically add "Page X" to the bottom of every page
            self.set_y(-15)
            self.set_font("helvetica", "I", 8)
            self.cell(0, 10, f"Page {self.page_no()}", align="C", new_x="LMARGIN", new_y="NEXT")

    def build_pdf(toc_data=None):
        pdf = MasterReportPDF()
        pdf.set_margins(left=15, top=15, right=15)
        pdf.set_auto_page_break(auto=True, margin=15)
        
        # --- PAGE 1: TABLE OF CONTENTS ---
        pdf.add_page()
        
        if toc_data:
            pdf.set_font("helvetica", "B", 16)
            pdf.cell(0, 15, "Table of Contents", align="C", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(5)
            
            pdf.set_font("helvetica", "", 12)
            
            def fmt_pgs(start, end):
                return f"(page {start})" if start == end else f"(pages {start}-{end})"
            
            pdf.cell(0, 10, f"USPTO TRADEMARK REGISTRY RESULTS {fmt_pgs(toc_data['uspto_start'], toc_data['uspto_end'])}", new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 10, f"TTB COLA REGISTRY RESULTS {fmt_pgs(toc_data['ttb_start'], toc_data['ttb_end'])}", new_x="LMARGIN", new_y="NEXT")
            pdf.cell(0, 10, f"WEB SEARCH RESULTS {fmt_pgs(toc_data['web_start'], toc_data['web_end'])}", new_x="LMARGIN", new_y="NEXT")

        tracked_pages = {}

        # --- USPTO RESULTS ---
        pdf.add_page()
        tracked_pages['uspto_start'] = pdf.page_no()
        
        pdf.set_font("helvetica", "B", 12)
        pdf.set_fill_color(200, 200, 200)
        pdf.cell(0, 8, f" USPTO TRADEMARK REGISTRY RESULTS ({len(uspto_results)} Found) ", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        if not uspto_results:
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 6, "No USPTO records found for these parameters.", new_x="LMARGIN", new_y="NEXT")
        else:
            for idx, item in enumerate(uspto_results, 1):
                pdf.set_font("helvetica", "B", 10)
                write_safe_multiline(pdf, f"{idx}. {item['mark']} (Serial: {item['serial']})")
                pdf.set_font("helvetica", "", 10)
                write_safe_multiline(pdf, f"Filed: {item['filed_date']} | Status: {item['status']} | Goods: {item['goods']}")
                uspto_url = f"https://tsdr.uspto.gov/#caseNumber={item['serial']}&caseSearchType=US_APPLICATION&caseType=DEFAULT&searchType=statusSearch"
                pdf.set_font("helvetica", "U", 9)
                pdf.set_text_color(0, 0, 255)
                pdf.cell(0, 6, "View TSDR Record", link=uspto_url, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(2)
                
        tracked_pages['uspto_end'] = pdf.page_no()

        # --- TTB RESULTS ---
        pdf.add_page()
        tracked_pages['ttb_start'] = pdf.page_no()
        
        pdf.set_font("helvetica", "B", 12)
        pdf.set_fill_color(200, 200, 200)
        pdf.cell(0, 8, f" TTB COLA REGISTRY RESULTS ({len(ttb_results)} Found) ", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        if not ttb_results:
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 6, "No COLA records found.", new_x="LMARGIN", new_y="NEXT")
        else:
            for idx, item in enumerate(ttb_results, 1):
                clean_ttb_id = item['ttb_id'].replace("'", "").replace('"', '').replace("=", "").strip()
                pdf.set_font("helvetica", "B", 10)
                write_safe_multiline(pdf, f"{idx}. {item['brand_name']} - {item['fanciful_name']} (ID: {clean_ttb_id})")
                pdf.set_font("helvetica", "", 10)
                write_safe_multiline(pdf, f"Approved: {item['approval_date']} | Type: {item['class_desc']}")
                ttb_url = f"https://ttbonline.gov/colasonline/viewColaDetails.do?action=publicFormDisplay&ttbid={clean_ttb_id}"
                pdf.set_font("helvetica", "U", 9)
                pdf.set_text_color(0, 0, 255)
                pdf.cell(0, 6, "View TTB COLA Record", link=ttb_url, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(2)

        tracked_pages['ttb_end'] = pdf.page_no()

        # --- WEB RESULTS ---
        pdf.add_page()
        tracked_pages['web_start'] = pdf.page_no()
        
        pdf.set_font("helvetica", "B", 12)
        pdf.set_fill_color(200, 200, 200)
        pdf.cell(0, 8, f" WEB SEARCH RESULTS ({len(web_results)} Found) ", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        if not web_results:
            pdf.set_font("helvetica", "I", 10)
            pdf.cell(0, 6, "No Web results found.", new_x="LMARGIN", new_y="NEXT")
        else:
            for idx, item in enumerate(web_results, 1):
                title = f"[{item.get('domain', '')}] {item.get('title', 'No Title')}"
                link = str(item.get('link', ''))
                pdf.set_font("helvetica", "B", 10)
                write_safe_multiline(pdf, f"{idx}. {title}")
                pdf.set_font("helvetica", "U", 9)
                pdf.set_text_color(0, 0, 255)
                visible_link = link[:80] + "..." if len(link) > 80 else link
                pdf.cell(0, 6, visible_link, link=link, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(2)

        tracked_pages['web_end'] = pdf.page_no()

        return pdf, tracked_pages

    # PASS 1: "Dummy" run to calculate exactly how many pages each section takes
    print(" -> Calculating pagination...")
    _, calculated_pages = build_pdf(toc_data=None)

    # PASS 2: Real run, injecting the calculated pages into the Table of Contents on Page 1
    print(" -> Building final document...")
    final_pdf, _ = build_pdf(toc_data=calculated_pages)

    full_path = os.path.join(os.getcwd(), output_filename)
    try:
        final_pdf.output(full_path)
        print(f"\nSUCCESS! Master PDF saved exactly here:\n -> {full_path}")
    except Exception as e:
        print(f"\n🚨 CRITICAL PDF ERROR: Something broke while generating the file: {e}")

    # ADD THIS LINE: Return the page mapping so the DOCX generator can use it!
    return calculated_pages