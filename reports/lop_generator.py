import os
import re
from io import BytesIO
import pandas as pd
import requests
from playwright.sync_api import sync_playwright
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import streamlit as st

# Import your actual USPTO scraper for Step 2
from scrapers.uspto_scraper import scrape_uspto

# Default related terms lookup for popular classes
DEFAULT_RELATED_TERMS = {
    "032": [
        "malt beverages",
        "ale",
        "porter",
        "stout",
        "lager",
        "hard seltzer",
        "non-alcoholic beverages",
        "fruit-flavored beverages",
        "cider",
    ],
    "043": [
        "bar services",
        "restaurant services",
        "cocktail lounge services",
        "pub services",
        "taproom services",
        "catering",
        "bar and restaurant services",
    ],
    "033": [
        "alcoholic beverages",
        "wine",
        "spirits",
        "liquor",
        "cocktails",
        "distilled spirits",
        "vodka",
        "whiskey",
    ],
    "030": [
        "coffee",
        "tea",
        "bakery goods",
        "confectionery",
        "snacks",
        "sauces",
    ],
    "025": ["clothing", "shirts", "hats", "apparel", "footwear", "headwear"],
    "035": [
        "retail store services",
        "online retail store services",
        "advertising services",
    ],
    "041": [
        "entertainment services",
        "organizing events",
        "nightclub services",
    ],
}


# ==========================================
# 0. HELPER: OWNER NAME NORMALIZATION
# ==========================================
def normalize_owner_name(owner_str):
  """Strips entity types, brackets, parentheses, addresses, and corporate suffixes to create a canonical key for 100% owner deduplication."""
  if not isinstance(owner_str, str) or not owner_str.strip():
    return ""
  base_name = re.split(r"[\(\[\;\,]", owner_str)[0]
  clean = re.sub(r"[^A-Z0-9]", "", base_name.upper())

  suffixes = [
      "LIMITEDLIABILITYCOMPANY",
      "LLC",
      "INC",
      "INCORPORATED",
      "CORP",
      "CORPORATION",
      "LIMITED",
      "LTD",
      "COMPANY",
      "CO",
  ]
  for s in suffixes:
    if clean.endswith(s):
      clean = clean[: -len(s)]
      break
  return clean


# ==========================================
# 1. HELPER: PARSE GOODS INTO CHECKLIST
# ==========================================
def parse_goods_to_df(raw_goods):
  """Splits raw goods text by semicolons/newlines into a DataFrame for the checklist UI."""
  if not raw_goods or not raw_goods.strip():
    return pd.DataFrame(
        {"Select": pd.Series([], dtype=bool), "Keyword": pd.Series([], dtype=str)}
    )

  raw_items = re.split(r"[;\n]", raw_goods)
  cleaned_items = [item.strip() for item in raw_items if item.strip()]

  seen = set()
  unique_items = [x for x in cleaned_items if not (x in seen or seen.add(x))]

  if not unique_items:
    return pd.DataFrame(
        {"Select": pd.Series([], dtype=bool), "Keyword": pd.Series([], dtype=str)}
    )

  return pd.DataFrame({
      "Select": pd.Series([False] * len(unique_items), dtype=bool),
      "Keyword": pd.Series(unique_items, dtype=str),
  })


# ==========================================
# 2. HELPER: CLEAN & SCORE RESULTS
# ==========================================
def clean_goods_exact_scored(text, c_cls, t_cls, c_kws, t_kws):
  """Filters goods to relevant classes, isolates exact matches, and assigns a ranking score."""
  if not isinstance(text, str):
    return "", 0
  segments = re.finditer(
      r"IC\s*0*(\d+)[\s.:]+(.*?)(?=IC\s*\d+|$)", text, re.IGNORECASE | re.DOTALL
  )

  class_kws = {}
  if c_cls:
    class_kws[c_cls.lstrip("0")] = [k.lower().strip(".;, ") for k in c_kws]
  if t_cls:
    t_str = t_cls.lstrip("0")
    class_kws[t_str] = class_kws.get(t_str, []) + [
        k.lower().strip(".;, ") for k in t_kws
    ]

  filtered = []
  score = 0

  for match in segments:
    cls_num = match.group(1)
    raw_desc = match.group(2).strip().rstrip(";")

    if cls_num in class_kws:
      kws = class_kws[cls_num]
      clean_desc = re.sub(r"(?i)US\s*[\d\s,]+[.:]\s*", "", raw_desc)
      clean_desc = re.sub(r"(?i)G\s*&\s*S\s*[:.]\s*", "", clean_desc)
      clauses = [c.strip() for c in clean_desc.split(";")]

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
          sub_items = [x.strip(".;, ") for x in c_lower.split(",")]
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
            if re.search(rf"\b{re.escape(kw)}\b", c_lower):
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
  sn_col = next((c for c in cols if "serial" in str(c).lower()), None)
  rn_col = next(
      (
          c
          for c in cols
          if "registrationnumber" in str(c).lower()
          or ("reg" in str(c).lower() and "num" in str(c).lower())
      ),
      None,
  )
  mark_col = next(
      (c for c in cols if "wordmark" in str(c).lower() or "mark" in str(c).lower()),
      None,
  )
  owner_col = next(
      (
          c
          for c in cols
          if "owner" in str(c).lower() or "applicant" in str(c).lower()
      ),
      None,
  )
  goods_col = next(
      (
          c
          for c in cols
          if "good" in str(c).lower() or "service" in str(c).lower()
      ),
      None,
  )
  status_col = next((c for c in cols if "status" in str(c).lower()), None)

  if rn_col:
    raw_df = raw_df[raw_df[rn_col].notna()]
    raw_df = raw_df[raw_df[rn_col].astype(str).str.strip() != ""]
    raw_df = raw_df[raw_df[rn_col].astype(str).str.strip() != "nan"]
    raw_df = raw_df[raw_df[rn_col].astype(str).str.strip() != "N/A"]
  else:
    return pd.DataFrame()

  if raw_df.empty:
    return pd.DataFrame()

  ui_df = pd.DataFrame()
  ui_df["Serial"] = (
      raw_df[sn_col].astype(str).str.replace(r"\.0$", "", regex=True)
  )
  ui_df["Reg Number"] = (
      raw_df[rn_col].astype(str).str.replace(r"\.0$", "", regex=True)
  )
  ui_df["Mark"] = raw_df[mark_col].astype(str)
  ui_df["Owner"] = raw_df[owner_col].astype(str)
  ui_df["Status"] = (
      raw_df[status_col].astype(str) if status_col else "REGISTERED"
  )
  ui_df["Raw Goods"] = raw_df[goods_col].astype(str)

  applied = ui_df["Raw Goods"].apply(
      lambda x: clean_goods_exact_scored(x, c_class, t_class, c_clean, t_clean)
  )
  ui_df["Filtered Goods"] = applied.apply(lambda x: x[0])
  ui_df["MatchScore"] = applied.apply(lambda x: x[1])

  ui_df = ui_df[ui_df["Filtered Goods"] != ""]

  # STRICT OWNER DEDUPLICATION USING NORMALIZED KEY
  ui_df["Owner_Key"] = ui_df["Owner"].apply(normalize_owner_name)
  ui_df = (
      ui_df.drop_duplicates(subset=["Owner_Key"], keep="first")
      .drop(columns=["Owner_Key"])
      .reset_index(drop=True)
  )

  return ui_df


# ==========================================
# 3. HELPER: GENERATE COVER PAGE PDF
# ==========================================
def generate_exhibit_cover_pdf(selected_df):
  """Generates an official USPTO Exhibit A Cover Page and Master Index."""
  buffer = BytesIO()
  doc = SimpleDocTemplate(
      buffer,
      pagesize=letter,
      rightMargin=36,
      leftMargin=36,
      topMargin=36,
      bottomMargin=36,
  )
  elements = []
  styles = getSampleStyleSheet()

  title_style = ParagraphStyle(
      "ExTitle",
      parent=styles["Heading1"],
      fontSize=14,
      leading=18,
      alignment=1,
      textColor=colors.HexColor("#1E3A8A"),
  )
  sub_style = ParagraphStyle(
      "ExSub",
      parent=styles["Normal"],
      fontSize=9,
      leading=12,
      alignment=1,
      textColor=colors.HexColor("#475569"),
  )
  h2_style = ParagraphStyle(
      "ExH2",
      parent=styles["Heading2"],
      fontSize=11,
      leading=14,
      textColor=colors.HexColor("#1E3A8A"),
  )
  val_style = ParagraphStyle(
      "ExVal", parent=styles["Normal"], fontSize=8.5, leading=11
  )
  hdr_style = ParagraphStyle(
      "HStyle",
      parent=styles["Normal"],
      fontSize=8.5,
      leading=10,
      textColor=colors.white,
      fontName="Helvetica-Bold",
  )

  elements.append(
      Paragraph(
          "<b>EXHIBIT A: BRIDGING REGISTRATIONS EVIDENCE</b>", title_style
      )
  )
  elements.append(
      Paragraph(
          "Official TSDR Record Evidence Package — Live Registrations Used in"
          " Commerce",
          sub_style,
      )
  )
  elements.append(Spacer(1, 14))

  elements.append(
      Paragraph("<b>Master Index of Cited Evidence Registrations</b>", h2_style)
  )
  elements.append(Spacer(1, 6))

  index_data = [["Item", "Word Mark", "Reg. No.", "Serial No.", "Status"]]
  for idx, (_, row) in enumerate(selected_df.iterrows(), 1):
    index_data.append([
        Paragraph(f"<b>{idx}</b>", val_style),
        Paragraph(f"<b>{row.get('Mark', '')}</b>", val_style),
        Paragraph(str(row.get("Reg Number", "")), val_style),
        Paragraph(str(row.get("Serial", "")), val_style),
        Paragraph(f"{row.get('Status', 'REGISTERED')}", val_style),
    ])

  index_data[0] = [Paragraph(h, hdr_style) for h in index_data[0]]
  t_index = Table(index_data, colWidths=[35, 175, 95, 95, 140])
  t_index.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
          ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
          ("TOPPADDING", (0, 0), (-1, -1), 5),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
          ("VALIGN", (0, 0), (-1, -1), "TOP"),
      ])
  )
  elements.append(t_index)

  doc.build(elements)
  buffer.seek(0)
  return buffer


# ==========================================
# 4. HELPER: AUTOMATED TSDR PDF DOWNLOAD VIA DIRECT ENDPOINTS & PLAYWRIGHT
# ==========================================
def download_official_tsdr_pdfs_batch(selected_df):
  """Automates Playwright to navigate TSDR, wait for full record load, click 'Download > Status (PDF)', and capture official USPTO PDFs."""
  pdf_dict = {}
  errors = []

  with sync_playwright() as p:
    try:
      browser = p.chromium.launch(
          headless=True,
          args=[
              "--no-sandbox",
              "--disable-dev-shm-usage",
              "--disable-gpu",
              "--disable-blink-features=AutomationControlled",
          ],
      )
      context = browser.new_context(
          user_agent=(
              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
              " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
          ),
          viewport={"width": 1920, "height": 1080},
      )
      page = context.new_page()

      for _, row in selected_df.iterrows():
        reg_num = str(row.get("Reg Number", "")).strip().replace(".0", "")
        sn_num = str(row.get("Serial", "")).strip().replace(".0", "")
        num_to_use = (
            reg_num
            if reg_num and reg_num.lower() != "nan" and reg_num != ""
            else sn_num
        )

        if not num_to_use or num_to_use.lower() == "nan":
          continue

        try:
          # 1. Direct navigate to TSDR case URL
          tsdr_url = f"https://tsdr.uspto.gov/#caseNumber={num_to_use}&caseSearchType=US_APPLICATION&caseType=DEFAULT&searchType=statusSearch"
          page.goto(tsdr_url, timeout=25000)

          # 2. Wait up to 15s for TSDR dynamic content rendering
          page.wait_for_selector("text=Generated on:", timeout=15000)
          page.wait_for_timeout(1000)

          # 3. Click the main "Download" dropdown button
          download_menu = page.locator(
              "a:has-text('Download'), button:has-text('Download')"
          ).first
          download_menu.click()
          page.wait_for_timeout(600)

          # 4. Trigger download event and capture PDF bytes
          with page.expect_download(timeout=15000) as download_info:
            inner_download_btn = page.locator(
                "a:has-text('Download'), input[value='Download']"
            ).last
            inner_download_btn.click()

          download = download_info.value
          with open(download.path(), "rb") as f:
            pdf_bytes = f.read()

          if pdf_bytes and pdf_bytes.startswith(b"%PDF"):
            pdf_dict[num_to_use] = pdf_bytes
          else:
            errors.append(
                f"Reg #{num_to_use}: Captured file was not a valid PDF."
            )

        except Exception as e:
          errors.append(f"Reg #{num_to_use}: {str(e)}")

      browser.close()
    except Exception as e:
      errors.append(f"Browser automation error: {str(e)}")

  return pdf_dict, errors


# ==========================================
# PAGE UI & LAYOUT (WRAPPED IN RUN FUNCTION)
# ==========================================
def run():
  st.title("Letter of Protest Generator")
  st.markdown(
      "Enter goods/services manually, run a bridging search, and generate a"
      " compliant Exhibit A PDF."
  )

  # --- STEP 1: MANUAL INPUT & VERIFY ---
  st.markdown("### Step 1: Input Classes & Goods/Services")
  col1, col2 = st.columns(2)
  with col1:
    st.markdown("#### Client Details")
    client_class = st.text_input(
        "Client Class(es)", placeholder="e.g., 032", key="client_class"
    )
    client_raw = st.text_area(
        "Client Goods / Services",
        placeholder="Paste client goods here (e.g., Beer; Malt beverages)",
        height=120,
        key="client_raw",
    )

  with col2:
    st.markdown("#### Applicant Details")
    app_class = st.text_input(
        "Applicant Class(es)", placeholder="e.g., 043", key="applicant_class"
    )
    app_raw = st.text_area(
        "Applicant Goods / Services",
        placeholder=(
            "Paste applicant goods here (e.g., Bar and restaurant services)"
        ),
        height=120,
        key="applicant_raw",
    )

  st.info(
      "Check the boxes next to the specific keywords you want to"
      " cross-reference in the bridging search."
  )

  c_df = parse_goods_to_df(client_raw)
  a_df = parse_goods_to_df(app_raw)

  col3, col4 = st.columns(2)
  with col3:
    st.markdown("**Client Keywords**")
    edited_c_df = st.data_editor(
        c_df,
        hide_index=True,
        width="stretch",
        key="c_goods_editor",
        column_config={
            "Select": st.column_config.CheckboxColumn("Select", width="small"),
            "Keyword": st.column_config.TextColumn(
                "Client Keywords", width="large"
            ),
        },
    )
    st.session_state["c_goods_df"] = edited_c_df

  with col4:
    st.markdown("**Applicant Keywords**")
    edited_a_df = st.data_editor(
        a_df,
        hide_index=True,
        width="stretch",
        key="a_goods_editor",
        column_config={
            "Select": st.column_config.CheckboxColumn("Select", width="small"),
            "Keyword": st.column_config.TextColumn(
                "Applicant Keywords", width="large"
            ),
        },
    )
    st.session_state["a_goods_df"] = edited_a_df

  # --- STEP 2: BRIDGING SEARCH ---
  st.divider()
  st.markdown("### Step 2: Bridging Search")
  if st.button("Execute Bridging Search", type="primary"):
    raw_c = st.session_state.get("client_class", "")
    raw_t = st.session_state.get("applicant_class", "")
    c_class = str(raw_c).strip().zfill(3)
    t_class = str(raw_t).strip().zfill(3)

    if c_class == "000" or t_class == "000" or not raw_c or not raw_t:
      st.error(
          "Please enter both the Client and Applicant classes in Step 1 before"
          " searching!"
      )
      st.stop()

    c_df_current = st.session_state.get("c_goods_df", pd.DataFrame())
    a_df_current = st.session_state.get("a_goods_df", pd.DataFrame())

    c_selected = (
        c_df_current[c_df_current["Select"] == True]["Keyword"].tolist()
        if not c_df_current.empty
        else []
    )
    a_selected = (
        a_df_current[a_df_current["Select"] == True]["Keyword"].tolist()
        if not a_df_current.empty
        else []
    )

    if not c_selected or not a_selected:
      st.error(
          "Please check at least one box for BOTH the Client and the Applicant"
          " keywords."
      )
      st.stop()

    with st.spinner("Searching USPTO via tmsearch.uspto.gov..."):
      c_clean = [kw.strip().replace('"', "") for kw in c_selected]
      t_clean = [kw.strip().replace('"', "") for kw in a_selected]

      st.session_state["primary_c_kws"] = c_clean
      st.session_state["primary_t_kws"] = t_clean

      c_kw_str = " OR ".join([f'"{kw}"' for kw in c_clean])
      t_kw_str = " OR ".join([f'"{kw}"' for kw in t_clean])

      search_query = (
          f"GS:({t_kw_str}) AND GS:({c_kw_str}) AND IC:{c_class} AND"
          f" IC:{t_class} AND LD:true"
      )

      excel_out = "temp_bridging_search.xlsx"
      try:
        with sync_playwright() as p:
          browser = p.chromium.launch(
              headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
          )
          page = browser.new_page()
          _ = scrape_uspto(
              page=page, primary_query=search_query, excel_filename=excel_out
          )
          browser.close()
      except Exception as e:
        st.error(f"Error scraping USPTO: {e}")
        st.stop()

      ui_df = process_uspto_excel_results(
          excel_out, c_class, t_class, c_clean, t_clean
      )

      if ui_df.empty:
        st.warning(
            f"No bridging registrations found for query: `{search_query}`. Try"
            " checking different keyword boxes."
        )
        st.session_state["bridging_results"] = pd.DataFrame()
      else:
        ui_df = ui_df.sort_values(by="MatchScore", ascending=False).reset_index(
            drop=True
        )
        ui_df_clean = ui_df.drop(columns=["Raw Goods", "MatchScore"])
        if "Select" not in ui_df_clean.columns:
          ui_df_clean.insert(0, "Select", False)
        ui_df_clean["Select"] = ui_df_clean["Select"].fillna(False).astype(bool)
        st.session_state["bridging_results"] = ui_df_clean

      st.session_state["lop_step"] = 3
      st.rerun()

  # --- STEP 3: RESULTS TABLE & TERM EXPANSION ---
  if st.session_state.get("lop_step") == 3:
    st.divider()
    st.markdown("### Step 3: Select Evidence")

    df = st.session_state.get("bridging_results", pd.DataFrame())
    if not df.empty:
      df["Owner_Key"] = df["Owner"].apply(normalize_owner_name)
      df = (
          df.drop_duplicates(subset=["Owner_Key"], keep="first")
          .drop(columns=["Owner_Key"])
          .reset_index(drop=True)
      )
      if "Select" not in df.columns:
        df.insert(0, "Select", False)
      df["Select"] = df["Select"].fillna(False).astype(bool)
      st.session_state["bridging_results"] = df

    results_count = len(df)

    if results_count < 10:
      st.warning(
          f"⚠️ **Found {results_count} bridging registration(s).** A strong"
          " Letter of Protest ideally includes 5–10 solid evidence marks."
      )

      with st.expander(
          "🔍 **Expand Search with Related Terms** to get 10+ results",
          expanded=True,
      ):
        st.write(
            "Select or enter related USPTO terms to expand your bridging"
            " search:"
        )

        raw_c = (
            st.session_state.get("client_class", "")
            .strip()
            .lstrip("0")
            .zfill(3)
        )
        raw_t = (
            st.session_state.get("applicant_class", "")
            .strip()
            .lstrip("0")
            .zfill(3)
        )

        default_c_terms = DEFAULT_RELATED_TERMS.get(
            raw_c, ["goods", "products"]
        )
        default_t_terms = DEFAULT_RELATED_TERMS.get(
            raw_t, ["services", "providing services"]
        )

        exp_col1, exp_col2 = st.columns(2)
        with exp_col1:
          add_c_terms = st.multiselect(
              f"Additional Client (Class {raw_c}) Terms:",
              options=default_c_terms,
              default=[
                  t
                  for t in default_c_terms[:3]
                  if t not in st.session_state.get("primary_c_kws", [])
              ],
              key="add_c_terms",
          )
          custom_c = st.text_input(
              "Other Client Terms (comma-separated):",
              placeholder="e.g., hard cider, craft beer",
              key="custom_c",
          )

        with exp_col2:
          add_t_terms = st.multiselect(
              f"Additional Applicant (Class {raw_t}) Terms:",
              options=default_t_terms,
              default=[
                  t
                  for t in default_t_terms[:3]
                  if t not in st.session_state.get("primary_t_kws", [])
              ],
              key="add_t_terms",
          )
          custom_t = st.text_input(
              "Other Applicant Terms (comma-separated):",
              placeholder="e.g., restaurant services, tavern",
              key="custom_t",
          )

        if st.button("🚀 Run Expanded Search", type="secondary"):
          c_clean = list(st.session_state.get("primary_c_kws", []))
          t_clean = list(st.session_state.get("primary_t_kws", []))

          c_clean.extend(add_c_terms)
          if custom_c.strip():
            c_clean.extend(
                [x.strip() for x in custom_c.split(",") if x.strip()]
            )

          t_clean.extend(add_t_terms)
          if custom_t.strip():
            t_clean.extend(
                [x.strip() for x in custom_t.split(",") if x.strip()]
            )

          c_clean = list(set(c_clean))
          t_clean = list(set(t_clean))

          with st.spinner("Running expanded USPTO search..."):
            c_kw_str = " OR ".join([f'"{kw}"' for kw in c_clean])
            t_kw_str = " OR ".join([f'"{kw}"' for kw in t_clean])

            expanded_query = (
                f"GS:({t_kw_str}) AND GS:({c_kw_str}) AND IC:{raw_c} AND"
                f" IC:{raw_t} AND LD:true"
            )
            excel_exp_out = "temp_expanded_bridging_search.xlsx"

            try:
              with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                page = browser.new_page()
                _ = scrape_uspto(
                    page=page,
                    primary_query=expanded_query,
                    excel_filename=excel_exp_out,
                )
                browser.close()
            except Exception as e:
              st.error(f"Error during expanded search: {e}")
              st.stop()

            exp_df = process_uspto_excel_results(
                excel_exp_out, raw_c, raw_t, c_clean, t_clean
            )

            if exp_df.empty:
              st.warning("No additional registrations found with expanded terms.")
            else:
              exp_df_clean = exp_df.drop(columns=["Raw Goods", "MatchScore"])
              if not df.empty:
                combined = pd.concat([df, exp_df_clean], ignore_index=True)
                combined = combined.drop_duplicates(
                    subset=["Reg Number"], keep="first"
                )

                combined["Owner_Key"] = combined["Owner"].apply(
                    normalize_owner_name
                )
                combined = (
                    combined.drop_duplicates(
                        subset=["Owner_Key"], keep="first"
                    )
                    .drop(columns=["Owner_Key"])
                    .reset_index(drop=True)
                )

                if "Select" not in combined.columns:
                  combined.insert(0, "Select", False)
                combined["Select"] = (
                    combined["Select"].fillna(False).astype(bool)
                )
                st.session_state["bridging_results"] = combined
              else:
                exp_df_sorted = exp_df_clean.sort_values(
                    by="MatchScore", ascending=False
                )
                exp_df_sorted["Owner_Key"] = exp_df_sorted["Owner"].apply(
                    normalize_owner_name
                )
                exp_df_sorted = (
                    exp_df_sorted.drop_duplicates(
                        subset=["Owner_Key"], keep="first"
                    )
                    .drop(columns=["Owner_Key"])
                    .reset_index(drop=True)
                )

                if "Select" not in exp_df_sorted.columns:
                  exp_df_sorted.insert(0, "Select", False)
                exp_df_sorted["Select"] = (
                    exp_df_sorted["Select"].fillna(False).astype(bool)
                )
                st.session_state["bridging_results"] = exp_df_sorted

              st.success(
                  "Updated results! Total registrations found:"
                  f" {len(st.session_state['bridging_results'])}"
              )
              st.rerun()

    if not df.empty:
      st.write("Select the best records below to include in your Exhibit A.")

      edited_df = st.data_editor(
          df,
          hide_index=True,
          width="stretch",
          column_config={
              "Select": st.column_config.CheckboxColumn(
                  "Select", help="Check to include in LOP"
              ),
              "Filtered Goods": st.column_config.TextColumn(
                  "Filtered Goods", width="large"
              ),
          },
      )
      st.session_state["bridging_results"] = edited_df

      # --- STEP 4: AUTOMATED EXPORT & STITCHING ---
      selected_rows = edited_df[edited_df["Select"] == True]

      st.divider()
      st.markdown("### Step 4: Export Exhibit A Package")

      if selected_rows.empty:
        st.info(
            "💡 Check the boxes next to the marks in Step 3 above to compile"
            " your Exhibit A package."
        )
      else:
        st.success(
            f"Ready! **{len(selected_rows)}** registration(s) selected for"
            " Exhibit A."
        )

        if st.button(
            "📦 Generate & Download Official Exhibit A Package", type="primary"
        ):
          with st.spinner(
              f"Fetching official TSDR status PDFs from USPTO for"
              f" {len(selected_rows)} mark(s)..."
          ):
            pdf_dict, errors = download_official_tsdr_pdfs_batch(selected_rows)

            cover_buffer = generate_exhibit_cover_pdf(selected_rows)

            writer = PdfWriter()
            cover_reader = PdfReader(cover_buffer)
            for page in cover_reader.pages:
              writer.add_page(page)

            attached_count = 0
            for _, row in selected_rows.iterrows():
              reg_num = str(row.get("Reg Number", "")).strip().replace(".0", "")
              sn_num = str(row.get("Serial", "")).strip().replace(".0", "")
              num_key = (
                  reg_num
                  if reg_num and reg_num.lower() != "nan" and reg_num != ""
                  else sn_num
              )

              if num_key in pdf_dict:
                tsdr_reader = PdfReader(BytesIO(pdf_dict[num_key]))
                for page in tsdr_reader.pages:
                  writer.add_page(page)
                attached_count += 1

            final_buffer = BytesIO()
            writer.write(final_buffer)
            final_buffer.seek(0)

            st.session_state["exhibit_pdf_bytes"] = final_buffer.getvalue()
            st.session_state["attached_count"] = attached_count
            st.session_state["download_errors"] = errors

        if "exhibit_pdf_bytes" in st.session_state:
          st.download_button(
              label=(
                  "📄 Download Completed Exhibit A Package"
                  f" ({st.session_state.get('attached_count', 0)} Official"
                  " TSDR PDFs Attached)"
              ),
              data=st.session_state["exhibit_pdf_bytes"],
              file_name="Exhibit_A_Bridging_Registrations_Package.pdf",
              mime="application/pdf",
              type="primary",
              width="stretch",
          )

          # If Akamai blocked any automated cloud downloads, show direct links + 1-click uploader
          if st.session_state.get("download_errors"):
            st.divider()
            st.warning(
                "⚠️ **Streamlit Cloud Firewall Notice:** The USPTO Akamai"
                " firewall blocked direct automated downloads for some records."
                " Click the links below to open TSDR, hit **Download > Status"
                " (PDF)**, and upload to re-stitch:"
            )

            link_cols = st.columns(2)
            for idx, (_, row) in enumerate(selected_rows.iterrows()):
              reg_num = str(row.get("Reg Number", "")).strip().replace(".0", "")
              sn_num = str(row.get("Serial", "")).strip().replace(".0", "")
              num_to_use = (
                  reg_num
                  if reg_num and reg_num.lower() != "nan" and reg_num != ""
                  else sn_num
              )
              mark_txt = str(row.get("Mark", "Unknown"))

              tsdr_url = (
                  f"https://tsdr.uspto.gov/#caseNumber={num_to_use}&caseSearchType=US_APPLICATION&caseType=DEFAULT&searchType=statusSearch"
              )
              col_target = link_cols[0] if idx % 2 == 0 else link_cols[1]
              col_target.markdown(
                  f"🔗 **[{idx+1}. {mark_txt} (Reg #{num_to_use})]({tsdr_url})**"
              )

            uploaded_tsdr_files = st.file_uploader(
                "Upload downloaded TSDR Status PDFs to re-stitch:",
                type=["pdf"],
                accept_multiple_files=True,
                key="manual_tsdr_uploader",
            )

            if uploaded_tsdr_files:
              writer = PdfWriter()
              cover_buffer = generate_exhibit_cover_pdf(selected_rows)
              cover_reader = PdfReader(cover_buffer)
              for page in cover_reader.pages:
                writer.add_page(page)

              for u_file in uploaded_tsdr_files:
                reader = PdfReader(u_file)
                for page in reader.pages:
                  writer.add_page(page)

              restitched_buffer = BytesIO()
              writer.write(restitched_buffer)
              restitched_buffer.seek(0)

              st.download_button(
                  label=(
                      "📦 Download Re-Stitched Exhibit A Package"
                      f" ({len(uploaded_tsdr_files)} Uploaded PDFs Attached)"
                  ),
                  data=restitched_buffer.getvalue(),
                  file_name="Exhibit_A_Bridging_Registrations_Package.pdf",
                  mime="application/pdf",
                  type="primary",
                  width="stretch",
              )