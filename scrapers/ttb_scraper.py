import logging
import re

logger = logging.getLogger(__name__)


def scrape_ttb(page, start_date, end_date, brand_terms):
  """Scrapes TTB Public COLA Registry using the exact element IDs from DOM inspection."""
  results = []
  if not brand_terms or not page:
    return results

  clean_terms = list(
      dict.fromkeys([
          str(t).strip() for t in brand_terms if str(t).strip()
      ])
  )
  if not clean_terms:
    return results

  ttb_url = "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do"

  for term in clean_terms:
    try:
      logger.info(f"Navigating to TTB for term '{term}'...")
      page.goto(ttb_url, timeout=25000, wait_until="domcontentloaded")

      # 1. Fill Product Name input (id="productname")
      input_sel = "#productname, input[name='searchCriteria.productOrFancifulName'], input[name='searchCriteria.brandName']"
      page.wait_for_selector(input_sel, timeout=12000)
      page.fill(input_sel, term)

      # 2. Fill Date Completed From (id="datecompletedfrom")
      from_sel = "#datecompletedfrom, input[name='searchCriteria.dateCompletedFrom']"
      if page.query_selector(from_sel):
        page.fill(from_sel, start_date)

      # 3. Fill Date Completed To (id="datecompletedto")
      to_sel = "#datecompletedto, input[name='searchCriteria.dateCompletedTo']"
      if page.query_selector(to_sel):
        page.fill(to_sel, end_date)

      # 4. Click Submit Button
      submit_sel = "input[value='Search'], input[alt*='search'], input[type='submit']"
      submit_btn = page.query_selector(submit_sel)
      if submit_btn:
        submit_btn.click()
      else:
        page.focus(input_sel)
        page.keyboard.press("Enter")

      # 5. Wait for results container (div.box table or width=785 table)
      try:
        page.wait_for_selector("div.box table, table[width='785'], div.pagination", timeout=15000)
      except Exception:
        logger.info(f"No results table container found for '{term}'")
        continue

      # 6. Extract rows from div.box table
      rows = page.query_selector_all("div.box table tr, table[width='785'] tr")
      for row in rows:
        cols = row.query_selector_all("td")
        if len(cols) >= 4:
          col_texts = [c.inner_text().strip() for c in cols]

          ttb_id = None
          link = row.query_selector("a[href*='ttbid='], a[href*='publicViewCola']")
          if link:
            href = link.get_attribute("href") or ""
            m = re.search(r"ttbid=(\w+)", href)
            if m:
              ttb_id = m.group(1)
            elif link.inner_text().strip().isdigit():
              ttb_id = link.inner_text().strip()

          if not ttb_id and col_texts[0].isdigit():
            ttb_id = col_texts[0]

          if ttb_id or len(col_texts) >= 5:
            row_str = " ".join(col_texts)
            date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", row_str)
            issue_date = date_match.group(0) if date_match else ""

            results.append({
                "ttb_id": ttb_id or f"COLA_{len(results) + 1}",
                "brand_name": col_texts[1] if len(col_texts) > 1 else "",
                "fanciful_name": col_texts[2] if len(col_texts) > 2 else "",
                "class_desc": col_texts[4] if len(col_texts) > 4 else (col_texts[3] if len(col_texts) > 3 else ""),
                "issue_date": issue_date,
                "search_term": term,
            })

    except Exception as e:
      logger.warning(f"Error scraping TTB for '{term}': {e}")
      continue

  return results