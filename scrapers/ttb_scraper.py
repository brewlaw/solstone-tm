import logging
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def scrape_ttb(page, start_date, end_date, brand_terms):
  """Scrapes TTB Public COLA Registry for specified brand terms and date range.

  Args:
      page: Active Playwright page context.
      start_date (str): Start date in MM/DD/YYYY format.
      end_date (str): End date in MM/DD/YYYY format.
      brand_terms (list): List of brand name terms to search.

  Returns:
      list: Extracted COLA records as dictionaries.
  """
  results = []
  if not brand_terms:
    return results

  # Clean SQL wildcards (%) from terms so TTB search engine reads normal text
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
      page.goto(ttb_url, timeout=30000, wait_until="domcontentloaded")

      # Wait for the advanced search form
      page.wait_for_selector(
          "form[name='publicSearchColasAdvancedForm'], input[name='searchCriteria.brandName'], input[name='brandName']",
          timeout=15000,
      )

      # Fill Brand Name field (try primary and fallback selectors)
      brand_selector = (
          "input[name='searchCriteria.brandName']"
          if page.query_selector("input[name='searchCriteria.brandName']")
          else "input[name='brandName']"
      )
      page.fill(brand_selector, term)

      # Fill Date Range fields if available
      date_from_sel = "input[name='searchCriteria.issueDateFrom']"
      date_to_sel = "input[name='searchCriteria.issueDateTo']"

      if page.query_selector(date_from_sel):
        page.fill(date_from_sel, start_date)
      if page.query_selector(date_to_sel):
        page.fill(date_to_sel, end_date)

      # Submit the search form
      submit_button = (
          "input[name='search']"
          if page.query_selector("input[name='search']")
          else "input[type='submit']"
      )
      page.click(submit_button)

      # Wait for results table or no-results message
      page.wait_for_selector(
          "table.searchResultsTable, table[summary*='search results'], body",
          timeout=20000,
      )

      html = page.content()
      soup = BeautifulSoup(html, "html.parser")

      # Parse results table rows
      rows = soup.select("table.searchResultsTable tr, table tr")
      for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 5:
          col_texts = [c.get_text(strip=True) for c in cols]

          # Extract TTB ID, Brand Name, Fanciful Name, Class, Issue Date
          ttb_id = col_texts[0]
          if ttb_id and (ttb_id.isdigit() or len(ttb_id) >= 8):
            brand_name = col_texts[1] if len(col_texts) > 1 else ""
            fanciful_name = col_texts[2] if len(col_texts) > 2 else ""
            class_desc = col_texts[3] if len(col_texts) > 3 else ""
            issue_date = col_texts[4] if len(col_texts) > 4 else ""

            results.append({
                "ttb_id": ttb_id,
                "brand_name": brand_name,
                "fanciful_name": fanciful_name,
                "class_desc": class_desc,
                "issue_date": issue_date,
                "search_term": term,
            })

    except Exception as e:
      logger.warning(f"TTB scraping error for '{term}': {e}")
      continue

  return results