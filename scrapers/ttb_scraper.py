import logging
import re

logger = logging.getLogger(__name__)


def scrape_ttb(page, start_date, end_date, brand_terms):
  """Scrapes TTB Public COLA Registry with stealth anti-detection and fallback portals."""
  results = []
  if not brand_terms or not page:
    return results

  clean_terms = []
  for term in brand_terms:
    t = str(term).strip()
    if t and t not in clean_terms:
      clean_terms.append(t)

  if not clean_terms:
    return results

  # Inject stealth override to bypass TTB Cloudflare/WAF bot detection
  try:
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
  except Exception:
    pass

  search_urls = [
      "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do",
      "https://www.ttbonline.gov/colasonline/publicSearchColasAdvanced.do",
  ]

  for term in clean_terms:
    term_success = False
    for ttb_url in search_urls:
      if term_success:
        break
      try:
        logger.info(f"TTB scraping '{term}' at {ttb_url}...")
        response = page.goto(
            ttb_url, timeout=25000, wait_until="domcontentloaded"
        )

        if response and response.status in [403, 406, 429]:
          logger.warning(
              f"TTB returned HTTP {response.status} block for {ttb_url}"
          )
          continue

        # Locate text input field dynamically
        input_field = None
        selectors = [
            "input[name='searchCriteria.brandName']",
            "input[name='brandName']",
            "input[name='brandname']",
            "input[name='searchCriteria.productName']",
            "input[name='productName']",
            "form input[type='text']",
        ]

        for sel in selectors:
          if page.query_selector(sel):
            input_field = sel
            break

        if not input_field:
          logger.warning(
              f"No text field found on {ttb_url}. Page title:"
              f" '{page.title()}'"
          )
          continue

        # Fill brand search term
        page.fill(input_field, term)

        # Fill dates if advanced form
        if page.query_selector("input[name='searchCriteria.issueDateFrom']"):
          page.fill("input[name='searchCriteria.issueDateFrom']", start_date)
        if page.query_selector("input[name='searchCriteria.issueDateTo']"):
          page.fill("input[name='searchCriteria.issueDateTo']", end_date)

        # Submit form via Submit button or Enter key
        submit_btn = page.query_selector(
            "input[type='submit'], input[name='search'], input[value*='Search']"
        )
        if submit_btn:
          submit_btn.click()
        else:
          page.focus(input_field)
          page.keyboard.press("Enter")

        # Wait for table or results page
        try:
          page.wait_for_selector(
              "table.searchResultsTable, table[summary*='search results'],"
              " table tr td",
              timeout=15000,
          )
        except Exception:
          content = page.content().lower()
          if (
              "0 matching" in content
              or "no records" in content
              or "no results" in content
          ):
            term_success = True
            continue
          logger.warning(
              f"Timeout waiting for TTB results table on {ttb_url}"
          )
          continue

        # Extract table rows
        rows = page.query_selector_all(
            "table.searchResultsTable tr, table[summary*='search results'] tr,"
            " table tr"
        )

        for row in rows:
          cols = row.query_selector_all("td")
          if len(cols) < 3:
            continue

          col_texts = [c.inner_text().strip() for c in cols]
          row_text = " ".join(col_texts)

          # Extract TTB ID
          ttb_id = None
          if col_texts[0].isdigit() and len(col_texts[0]) >= 8:
            ttb_id = col_texts[0]
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

            # Extract MM/DD/YYYY date pattern
            issue_date = ""
            date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", row_text)
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

        term_success = True
      except Exception as e:
        logger.warning(f"TTB error scraping '{term}' on {ttb_url}: {e}")
        continue

  return results