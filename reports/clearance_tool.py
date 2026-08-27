import datetime
import gc
import os
import re
from playwright.sync_api import sync_playwright
import streamlit as st

from reports.docx_generator_2 import generate_docx_2
from reports.pdf_generator import generate_pdf
from scrapers.google_scraper import scrape_google
from scrapers.ttb_scraper import scrape_ttb
from scrapers.uspto_scraper import scrape_uspto

OUTPUT_DIR = "outputs"
if not os.path.exists(OUTPUT_DIR):
  os.makedirs(OUTPUT_DIR)


def run():
  st.header("Full Trademark Clearance Search")
  st.write(
      "Run a comprehensive, all-time clearance search across USPTO, TTB, and"
      " Google."
  )

  if "clearance_report_data" not in st.session_state:
    st.session_state["clearance_report_data"] = None

  def_client = st.session_state.get("client_name", "")
  def_attn = st.session_state.get("attention_name", "")
  def_email = st.session_state.get("client_email", "")

  col1, col2 = st.columns(2)
  with col1:
    client_name = st.text_input(
        "Client Name:", value=def_client, key="clearance_client_name"
    )
    attention_name = st.text_input(
        "Attention Name (e.g. Adeline Druart):",
        value=def_attn,
        key="clearance_attention_name",
    )
  with col2:
    client_email = st.text_input(
        "Client Email:", value=def_email, key="clearance_client_email"
    )
    use_letterhead = st.checkbox(
        "📄 Export Word Doc on LBL Letterhead",
        value=False,
        key="clearance_use_letterhead",
    )

  raw_mark = st.text_input(
      "Full Trademark Name:",
      placeholder="e.g. SUN SHINE (include spaces if applicable)",
      key="clearance_raw_mark",
  )

  st.subheader("Search Term Expansions")
  st.caption(
      "Expand your search to catch variations, sound-alikes, meaning-alikes,"
      " and substrings."
  )
  col_a, col_b = st.columns(2)
  with col_a:
    dominant_term = st.text_input(
        "Dominant/Core Word (optional):", key="clearance_dominant_term"
    ).upper()
    phonetic_term = st.text_input(
        "Phonetic Equivalent (optional):", key="clearance_phonetic_term"
    ).upper()
  with col_b:
    conceptual_term = st.text_input(
        "Conceptual Equivalent (optional):", key="clearance_conceptual_term"
    ).upper()
    substring_term = st.text_input(
        "Root Substring / Pun (optional):", key="clearance_substring_term"
    ).upper()

  if st.button(
      "Run Full Clearance Search", type="primary", key="btn_run_clearance"
  ):
    if not raw_mark.strip():
      st.error("Please enter a trademark name.")
      return

    squished_mark = raw_mark.replace(" ", "")
    today = datetime.datetime.now()

    words = raw_mark.split()
    web_mark_base = (
        f'("{raw_mark}" OR "{squished_mark}")'
        if raw_mark != squished_mark
        else f'"{raw_mark}"'
    )
    uspto_spaced = " AND ".join([f"CM2:{w}*" for w in words])
    uspto_mark = (
        f"({uspto_spaced}) OR (CM2:{squished_mark}*)"
        if raw_mark != squished_mark
        else uspto_spaced
    )

    clean_ttb_terms = list(set([raw_mark.strip(), squished_mark.strip()]))

    secondary_terms = []
    if dominant_term:
      web_mark_base += f' OR "{dominant_term}"'
      secondary_terms.append(f"(CM2:{dominant_term}*)")
      clean_ttb_terms.append(dominant_term)
    if phonetic_term:
      web_mark_base += f' OR "{phonetic_term}"'
      secondary_terms.append(f"(CM2:{phonetic_term}*)")
      clean_ttb_terms.append(phonetic_term)
    if conceptual_term:
      web_mark_base += f' OR "{conceptual_term}"'
      secondary_terms.append(f"(CM2:{conceptual_term}*)")
      clean_ttb_terms.append(conceptual_term)
    if substring_term:
      web_mark_base += f' OR "{substring_term}"'
      secondary_terms.append(f"(CM2:{substring_term}*)")
      clean_ttb_terms.append(substring_term)

    class_filter = ' AND IC:("030" OR "032" OR "033" OR "043")'
    date_filter = ""

    primary_uspto_query = f"({uspto_mark}){class_filter}{date_filter}"
    secondary_uspto_query = (
        f"({' OR '.join(secondary_terms)}){class_filter}{date_filter}"
        if secondary_terms
        else None
    )

    safe_mark = re.sub(r"[^A-Z0-9]", "_", squished_mark.upper())
    timestamp = today.strftime("%H%M%S")
    excel_filename = os.path.join(
        OUTPUT_DIR,
        f"{safe_mark}-USPTO-EXPORT-{today.strftime('%Y-%m-%d')}_{timestamp}.xlsx",
    )

    with st.spinner("Scraping USPTO, TTB, and Google..."):
      try:
        # --- 1. USPTO SEARCH (Isolated Playwright Session) ---
        uspto_data = []
        try:
          with sync_playwright() as p1:
            browser1 = p1.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                    '--js-flags="--max-old-space-size=256"',
                ],
            )
            ctx1 = browser1.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    " AppleWebKit/537.36"
                ),
                accept_downloads=True,
            )
            page1 = ctx1.new_page()
            page1.set_default_timeout(30000)

            uspto_data = scrape_uspto(
                page1,
                primary_uspto_query,
                excel_filename,
                secondary_uspto_query,
            )
            ctx1.close()
            browser1.close()
        except Exception as e:
          st.warning(f"USPTO scraping warning: {e}")

        gc.collect()

        # --- 2. TTB COLA SEARCH (Isolated Playwright Session) ---
        ttb_data = []
        try:
          with sync_playwright() as p2:
            browser2 = p2.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--single-process",
                ],
            )
            ctx2 = browser2.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    " AppleWebKit/537.36"
                )
            )
            page2 = ctx2.new_page()
            page2.set_default_timeout(15000)

            start_date = "01/01/1985"
            end_date = today.strftime("%m/%d/%Y")

            raw_ttb_data = scrape_ttb(
                page2, start_date, end_date, clean_ttb_terms
            )
            ctx2.close()
            browser2.close()

            if raw_ttb_data:
              unique_ttb = {
                  item["ttb_id"]: item
                  for item in raw_ttb_data
                  if "ttb_id" in item
              }
              ttb_data = list(unique_ttb.values())
        except Exception as e:
          st.warning(f"TTB COLA search warning: {e}")

        gc.collect()

        # --- 3. GOOGLE SEARCH ---
        google_data = []
        try:
          google_date_from = "1900-01-01"
          google_date_to = today.strftime("%Y-%m-%d")
          google_data = scrape_google(
              web_mark_base, raw_mark, google_date_from, google_date_to
          )
        except Exception as e:
          st.warning(f"Google web search warning: {e}")

        # --- REPORT GENERATION ---
        base_filename = f"Clearance_Report_{safe_mark}"
        report_title = f"Clearance Report - {raw_mark.upper()}"
        pdf_filename = os.path.join(OUTPUT_DIR, f"{base_filename}.pdf")
        docx_filename = os.path.join(OUTPUT_DIR, f"{base_filename}.docx")
        report_date = today.strftime("%B %d, %Y")

        page_data = generate_pdf(
            raw_mark,
            squished_mark,
            "01/01/1985",
            today.strftime("%m/%d/%Y"),
            uspto_data,
            ttb_data,
            google_data,
            pdf_filename,
            report_title,
        )

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
            use_letterhead=use_letterhead,
        )

        with open(pdf_filename, "rb") as f:
          pdf_bytes = f.read()
        with open(docx_filename, "rb") as f:
          docx_bytes = f.read()

        st.session_state["clearance_report_data"] = {
            "base_filename": base_filename,
            "pdf_filename": pdf_filename,
            "docx_filename": docx_filename,
            "pdf_bytes": pdf_bytes,
            "docx_bytes": docx_bytes,
        }

      except Exception as e:
        st.error(f"Error during search execution: {e}")

  # --- DISPLAY OUTPUTS ---
  if st.session_state.get("clearance_report_data"):
    c_data = st.session_state["clearance_report_data"]
    st.success("Search & Report Generation Complete!")

    col_d1, col_d2, col_d3 = st.columns(3)
    with col_d1:
      st.download_button(
          "📥 Download PDF Report",
          c_data["pdf_bytes"],
          file_name=f"{c_data['base_filename']}.pdf",
          mime="application/pdf",
          use_container_width=True,
          key="download_clearance_pdf",
      )
    with col_d2:
      st.download_button(
          "📄 Download Word Doc Report",
          c_data["docx_bytes"],
          file_name=f"{c_data['base_filename']}.docx",
          mime=(
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          ),
          use_container_width=True,
          key="download_clearance_docx",
      )
    with col_d3:
      if st.button(
          "☁️ Archive to Google Drive",
          use_container_width=True,
          key="archive_clearance",
      ):
        from utils.drive_uploader import upload_to_drive

        with st.spinner("Archiving reports to Google Drive..."):
          pdf_link = upload_to_drive(c_data["pdf_filename"])
          docx_link = upload_to_drive(c_data["docx_filename"])
        if pdf_link or docx_link:
          st.success(
              "☁️ Clearance reports successfully archived to Google Drive!"
          )