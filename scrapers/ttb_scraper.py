import logging
import re

logger = logging.getLogger(__name__)


def scrape_ttb(page, start_date, end_date, brand_terms):
  """Scrapes TTB Public COLA Registry using Playwright browser page."""
  results = []
  if not brand_terms or not page:
    return results

  clean_terms = []
  for term in brand_terms:
    cleaned = str(term).replace("%", "").strip()
    if cleaned and cleaned not in clean_terms:
      clean_terms.append(cleaned)

  if not clean_terms:
    return results

  ttb_url = "https://www.ttbonline.gov/colasonline/publicSearchColasAdvanced.do"

  for term in clean_terms:
    try:
      logger.info(
          f"Navigating to TTB for term '{term}' ({start_date} - {end_date})..."
      )
      page.goto(ttb_url, timeout=25000, wait_until="domcontentloaded")

      # Wait for search form to render
      page.wait_for_selector(
          "input[name='searchCriteria.brandName'], input[name='brandName']",
          timeout=15000,
      )

      # Target the brand name field
      brand_sel = (
          "input[name='searchCriteria.brandName']"
          if page.query_selector("input[name='searchCriteria.brandName']")
          else "input[name='brandName']"
      )
      page.fill(brand_sel, term)

      date_from_sel = "input[name='searchCriteria.issueDateFrom']"
      date_to_sel = "input[name='searchCriteria.issueDateTo']"

      if page.query_selector(date_from_sel):
        page.fill(date_from_sel, start_date)
      if page.query_selector(date_to_sel):
        page.fill(date_to_sel, end_date)

      # Click submit search button
      submit_btn = (
          "input[name='search']"
          if page.query_selector("input[name='search']")
          else "input[type='submit']"
      )
      page.click(submit_btn)

      # Wait for results table
      try:
        page.wait_for_selector(
            "table.searchResultsTable, table[summary*='search results'],"
            " table tr",
            timeout=15000,
        )
      except Exception:
        logger.info(
            f"TTB search for '{term}' ({start_date}-{end_date}) yielded no"
            " results table or exceeded limit."
        )
        continue

      # Extract table rows
      rows = page.query_selector_all(
          "table.searchResultsTable tr, table[summary*='search results'] tr,"
          " table tr"
      )
      for row in rows:
        cols = row.query_selector_all("td")
        if len(cols) >= 5:
          col_texts = [c.inner_text().strip() for c in cols]
          first_cell = col_texts[0]

          # Verify cell 0 is a valid 14-digit TTB ID
          if first_cell and (
              first_cell.isdigit()
              or (len(first_cell) >= 8 and first_cell[:4].isdigit())
          ):
            # TTB COLA Table Column Index Mapping:
            # Col 0: TTB ID
            # Col 1: Vendor Code / Permit No
            # Col 2: Serial No
            # Col 3: Brand Name
            # Col 4: Fanciful Name
            # Col 5: Class/Type Code & Description
            # Col 6+: Origin / Status / Issue Date

            brand_name = col_texts[3] if len(col_texts) > 3 else ""
            fanciful_name = col_texts[4] if len(col_texts) > 4 else ""
            class_desc = col_texts[5] if len(col_texts) > 5 else ""

            # Extract MM/DD/YYYY date string across all row cells
            issue_date = ""
            for text in reversed(col_texts):
              date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", text)
              if date_match:
                issue_date = date_match.group(0)
                break

            results.append({
                "ttb_id": first_cell,
                "brand_name": brand_name,
                "fanciful_name": fanciful_name,
                "class_desc": class_desc,
                "issue_date": issue_date,
                "search_term": term,
            })

    except Exception as e:
      logger.warning(f"TTB scraping exception for term '{term}': {e}")
      continue

  return results