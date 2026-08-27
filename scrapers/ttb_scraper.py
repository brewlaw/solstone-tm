import logging
import re

logger = logging.getLogger(__name__)


def scrape_ttb(page, start_date, end_date, brand_terms):
  """Scrapes TTB Public COLA Registry across Basic and Advanced search forms."""
  results = []
  if not brand_terms or not page:
    return results

  # Clean SQL wildcards (%) for web form input
  clean_terms = []
  for term in brand_terms:
    cleaned = str(term).replace("%", "").strip()
    if cleaned and cleaned not in clean_terms:
      clean_terms.append(cleaned)

  if not clean_terms:
    return results

  # Fallback search URLs
  ttb_urls = [
      "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do",
      "https://www.ttbonline.gov/colasonline/publicSearchColasAdvanced.do",
  ]

  for term in clean_terms:
    term_success = False
    for ttb_url in ttb_urls:
      if term_success:
        break
      try:
        logger.info(
            f"Navigating to {ttb_url} for term '{term}' ({start_date} -"
            f" {end_date})..."
        )
        page.goto(ttb_url, timeout=20000, wait_until="domcontentloaded")

        # Selectors matching Product Name / Brand Name fields across TTB portals
        input_selectors = [
            "input[name='searchCriteria.productName']",
            "input[name='productName']",
            "input[name='searchCriteria.brandName']",
            "input[name='brandName']",
            "form input[type='text']",
        ]

        target_input = None
        for sel in input_selectors:
          if page.query_selector(sel):
            target_input = sel
            break

        if not target_input:
          logger.warning(f"No valid text input field found on {ttb_url}")
          continue

        # Fill term
        page.fill(target_input, term)

        # Fill Date fields if available
        if page.query_selector("input[name='searchCriteria.issueDateFrom']"):
          page.fill("input[name='searchCriteria.issueDateFrom']", start_date)
        elif page.query_selector("input[name='issueDateFrom']"):
          page.fill("input[name='issueDateFrom']", start_date)

        if page.query_selector("input[name='searchCriteria.issueDateTo']"):
          page.fill("input[name='searchCriteria.issueDateTo']", end_date)
        elif page.query_selector("input[name='issueDateTo']"):
          page.fill("input[name='issueDateTo']", end_date)

        # Submit search via Enter key
        page.focus(target_input)
        page.keyboard.press("Enter")

        # Wait for results table or content load
        try:
          page.wait_for_selector(
              "table.searchResultsTable, table[summary*='search results'],"
              " table tr td",
              timeout=10000,
          )
        except Exception:
          # Click submit button directly as fallback
          submit_btn = page.query_selector(
              "input[type='submit'], input[value*='Search'],"
              " input[name='search']"
          )
          if submit_btn:
            submit_btn.click()
            page.wait_for_selector(
                "table.searchResultsTable, table[summary*='search results'],"
                " table tr td",
                timeout=10000,
            )

        # Extract table rows
        rows = page.query_selector_all(
            "table.searchResultsTable tr, table[summary*='search results'] tr,"
            " table tr"
        )
        found_rows = 0

        for row in rows:
          cols = row.query_selector_all("td")
          if len(cols) < 3:
            continue

          col_texts = [c.inner_text().strip() for c in cols]

          # Extract TTB ID from href parameters or first column cell
          ttb_id = None
          links = row.query_selector_all("a")
          for link in links:
            href = link.get_attribute("href") or ""
            text = link.inner_text().strip()
            if "ttbid=" in href:
              m = re.search(r"ttbid=(\w+)", href)
              if m:
                ttb_id = m.group(1)
                break
            if text.isdigit() and len(text) >= 10:
              ttb_id = text
              break

          if not ttb_id and col_texts[0].isdigit() and len(col_texts[0]) >= 10:
            ttb_id = col_texts[0]

          if ttb_id:
            brand_name = ""
            fanciful_name = ""
            class_desc = ""
            issue_date = ""

            # Extract MM/DD/YYYY date string across all row cells
            for text in reversed(col_texts):
              date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", text)
              if date_match:
                issue_date = date_match.group(0)
                break

            if len(col_texts) >= 5:
              brand_name = (
                  col_texts[1]
                  if col_texts[1] != ttb_id
                  else (col_texts[3] if len(col_texts) > 3 else "")
              )
              fanciful_name = col_texts[2] if len(col_texts) > 2 else ""
              class_desc = col_texts[3] if len(col_texts) > 3 else ""
            elif len(col_texts) >= 3:
              brand_name = col_texts[1]
              fanciful_name = col_texts[2]

            results.append({
                "ttb_id": ttb_id,
                "brand_name": brand_name,
                "fanciful_name": fanciful_name,
                "class_desc": class_desc,
                "issue_date": issue_date,
                "search_term": term,
            })
            found_rows += 1

        if found_rows > 0 or "0 matching" in page.content():
          term_success = True

      except Exception as e:
        logger.warning(f"Error searching TTB on {ttb_url} for '{term}': {e}")
        continue

  return results