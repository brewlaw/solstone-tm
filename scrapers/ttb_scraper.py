import logging
import re

logger = logging.getLogger(__name__)


def scrape_ttb(page, start_date, end_date, brand_terms):
  """Scrapes TTB Public COLA Registry using Playwright with wildcard query support."""
  results = []
  if not brand_terms or not page:
    return results

  # Clean duplicates while keeping wildcards
  formatted_terms = []
  for term in brand_terms:
    t = str(term).strip()
    if t and t not in formatted_terms:
      formatted_terms.append(t)

  if not formatted_terms:
    return results

  ttb_url = "https://www.ttbonline.gov/colasonline/publicSearchColasAdvanced.do"

  for term in formatted_terms:
    try:
      logger.info(
          f"Navigating to TTB for term '{term}' ({start_date} - {end_date})..."
      )
      page.goto(ttb_url, timeout=30000, wait_until="domcontentloaded")

      # Wait for input field on Advanced Search
      page.wait_for_selector(
          "input[name='searchCriteria.brandName'], input[name='brandName'],"
          " input[name='searchCriteria.productName']",
          timeout=15000,
      )

      # Target the brand name input field
      if page.query_selector("input[name='searchCriteria.brandName']"):
        target_field = "input[name='searchCriteria.brandName']"
      elif page.query_selector("input[name='brandName']"):
        target_field = "input[name='brandName']"
      else:
        target_field = "input[name='searchCriteria.productName']"

      page.fill(target_field, term)

      # Fill Date Range fields
      date_from_sel = "input[name='searchCriteria.issueDateFrom']"
      date_to_sel = "input[name='searchCriteria.issueDateTo']"

      if page.query_selector(date_from_sel):
        page.fill(date_from_sel, start_date)
      if page.query_selector(date_to_sel):
        page.fill(date_to_sel, end_date)

      # Submit the search form
      submit_btn = (
          "input[name='search']"
          if page.query_selector("input[name='search']")
          else "input[type='submit']"
      )
      page.click(submit_btn)

      # Wait up to 25 seconds for TTB database response
      try:
        page.wait_for_selector(
            "table.searchResultsTable, table[summary*='search results'], table"
            " tr td",
            timeout=25000,
        )
      except Exception:
        logger.info(
            f"TTB search for '{term}' ({start_date}-{end_date}) yielded no"
            " table within timeout."
        )
        continue

      # Extract table rows
      rows = page.query_selector_all(
          "table.searchResultsTable tr, table[summary*='search results'] tr,"
          " table tr"
      )
      for row in rows:
        cols = row.query_selector_all("td")
        if len(cols) >= 4:
          col_texts = [c.inner_text().strip() for c in cols]
          first_cell = col_texts[0]

          # Extract TTB ID from first cell or from link inside row
          ttb_id = None
          if first_cell and (
              first_cell.isdigit()
              or (len(first_cell) >= 8 and first_cell[:4].isdigit())
          ):
            ttb_id = first_cell
          else:
            link = row.query_selector("a[href*='ttbid=']")
            if link:
              href = link.get_attribute("href") or ""
              m = re.search(r"ttbid=(\w+)", href)
              if m:
                ttb_id = m.group(1)

          if ttb_id:
            # Map columns according to TTB results table layout
            brand_name = (
                col_texts[3]
                if len(col_texts) > 3
                else (col_texts[1] if len(col_texts) > 1 else "")
            )
            fanciful_name = (
                col_texts[4]
                if len(col_texts) > 4
                else (col_texts[2] if len(col_texts) > 2 else "")
            )
            class_desc = (
                col_texts[5]
                if len(col_texts) > 5
                else (col_texts[3] if len(col_texts) > 3 else "")
            )

            # Search full row text for MM/DD/YYYY date
            row_full_text = " ".join(col_texts)
            issue_date = ""
            date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", row_full_text)
            if date_match:
              issue_date = date_match.group(0)

            results.append({
                "ttb_id": ttb_id,
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