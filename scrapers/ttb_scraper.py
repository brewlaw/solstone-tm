import logging
import re

logger = logging.getLogger(__name__)


def scrape_ttb(page, start_date, end_date, brand_terms):
  """Scrapes TTB Public COLA Registry with term-level error isolation."""
  results = []
  if not brand_terms or not page:
    return results

  # Clean terms while keeping unique queries
  clean_terms = []
  for term in brand_terms:
    t = str(term).strip()
    if t and t not in clean_terms:
      clean_terms.append(t)

  if not clean_terms:
    return results

  ttb_url = "https://www.ttbonline.gov/colasonline/publicSearchColasAdvanced.do"

  for term in clean_terms:
    try:
      logger.info(
          f"Navigating to TTB for term '{term}' ({start_date} - {end_date})..."
      )
      page.goto(ttb_url, timeout=20000, wait_until="domcontentloaded")

      # Find Brand Name or Product Name field
      target_field = None
      for selector in [
          "input[name='searchCriteria.brandName']",
          "input[name='brandName']",
          "input[name='searchCriteria.productName']",
          "input[name='productName']",
      ]:
        if page.query_selector(selector):
          target_field = selector
          break

      if not target_field:
        logger.warning(f"Could not find input selector on TTB for '{term}'")
        continue

      page.fill(target_field, term)

      # Fill Issue Date range
      if page.query_selector("input[name='searchCriteria.issueDateFrom']"):
        page.fill("input[name='searchCriteria.issueDateFrom']", start_date)
      elif page.query_selector("input[name='issueDateFrom']"):
        page.fill("input[name='issueDateFrom']", start_date)

      if page.query_selector("input[name='searchCriteria.issueDateTo']"):
        page.fill("input[name='searchCriteria.issueDateTo']", end_date)
      elif page.query_selector("input[name='issueDateTo']"):
        page.fill("input[name='issueDateTo']", end_date)

      # Submit form
      submit_btn = page.query_selector(
          "input[name='search'], input[type='submit'], input[value='Search']"
      )
      if submit_btn:
        submit_btn.click()
      else:
        page.focus(target_field)
        page.keyboard.press("Enter")

      # Wait for result table or response
      try:
        page.wait_for_selector(
            "table.searchResultsTable, table[summary*='search results'], table"
            " tr td",
            timeout=15000,
        )
      except Exception:
        logger.info(
            f"No results table loaded for term '{term}' ({start_date} -"
            f" {end_date})"
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

            # Search row text for date pattern
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
      logger.warning(f"Error scraping TTB for term '{term}': {e}")
      continue

  return results