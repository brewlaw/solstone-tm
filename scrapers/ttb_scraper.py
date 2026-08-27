import logging

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
      logger.info(f"Navigating to TTB for term '{term}'...")
      page.goto(ttb_url, timeout=20000, wait_until="domcontentloaded")

      # Wait for search form to render
      page.wait_for_selector(
          "input[name='searchCriteria.brandName'], input[name='brandName']",
          timeout=10000,
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
            "table.searchResultsTable, table[summary*='search results']",
            timeout=12000,
        )
      except Exception:
        logger.info(
            f"TTB search for '{term}' returned no results table or hit limit."
        )
        continue

      # Extract table rows
      rows = page.query_selector_all(
          "table.searchResultsTable tr, table[summary*='search results'] tr"
      )
      for row in rows:
        cols = row.query_selector_all("td")
        if len(cols) >= 5:
          col_texts = [c.inner_text().strip() for c in cols]
          ttb_id = col_texts[0]
          if ttb_id and (ttb_id.isdigit() or len(ttb_id) >= 8):
            results.append({
                "ttb_id": ttb_id,
                "brand_name": col_texts[1] if len(col_texts) > 1 else "",
                "fanciful_name": col_texts[2] if len(col_texts) > 2 else "",
                "class_desc": col_texts[3] if len(col_texts) > 3 else "",
                "issue_date": col_texts[4] if len(col_texts) > 4 else "",
                "search_term": term,
            })

    except Exception as e:
      logger.warning(f"TTB scraping warning for '{term}': {e}")
      continue

  return results