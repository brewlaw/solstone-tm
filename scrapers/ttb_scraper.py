import logging
import re
import time

logger = logging.getLogger(__name__)


def scrape_ttb(page, ttb_date_from, ttb_date_to, mark_list):
  """Scrapes TTB COLA Registry targeting exact element IDs and waiting for result table load."""
  ttb_results = []
  seen_ttb_ids = set()

  if isinstance(mark_list, str):
    mark_list = [mark_list]

  if not mark_list or not page:
    return ttb_results

  for mark in mark_list:
    if not mark:
      continue

    logger.info(f"Searching TTB for variation: '{mark}'...")

    for attempt in range(3):
      try:
        page.goto(
            "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do",
            timeout=30000,
            wait_until="domcontentloaded",
        )

        # Handle disclaimer modal if present
        if page.locator("input[value='I Agree']").is_visible():
          page.locator("input[value='I Agree']").evaluate(
              "node => node.click()"
          )
          page.wait_for_timeout(2000)

        # Fill inputs using exact element IDs from DOM inspection
        if page.locator("#datecompletedfrom").is_visible():
          page.locator("#datecompletedfrom").fill(ttb_date_from)
        else:
          page.locator("input[name='searchCriteria.dateCompletedFrom']").fill(
              ttb_date_from
          )

        if page.locator("#datecompletedto").is_visible():
          page.locator("#datecompletedto").fill(ttb_date_to)
        else:
          page.locator("input[name='searchCriteria.dateCompletedTo']").fill(
              ttb_date_to
          )

        if page.locator("#productname").is_visible():
          page.locator("#productname").fill(mark)
        else:
          page.locator(
              "input[name='searchCriteria.productOrFancifulName']"
          ).fill(mark)

        # Select 'Either' radio button
        try:
          page.locator("input[value='E']").evaluate("node => node.click()")
        except Exception:
          try:
            page.locator("text='Either'").last.evaluate("node => node.click()")
          except Exception:
            pass

        page.wait_for_timeout(500)

        # Click Search button
        search_btn = page.locator(
            "input[value='Search'], input[alt*='search'], input[type='submit']"
        ).first
        search_btn.evaluate("node => node.click()")

        # CRITICAL FIX: Wait for the actual results page element, not the search form table
        try:
          page.wait_for_selector(
              "a:has-text('Save Search Results To File'), div.box table,"
              " table[width='785']",
              timeout=20000,
          )
        except Exception:
          logger.info(f"No search results table loaded for '{mark}'.")
          break

        variation_count = 0
        while True:
          # Extract rows specifically from the results table container
          rows = page.locator(
              "div.box table tr, table[width='785'] tr"
          ).all()
          if not rows:
            rows = page.locator("tr").all()

          for row in rows:
            row_text = row.inner_text()
            if "TTB ID" in row_text or "Results" in row_text:
              continue

            cols = row.locator("td").all_inner_texts()
            if len(cols) >= 4:
              first_cell = cols[0].strip()

              # Verify first cell contains numeric TTB ID
              if first_cell and (
                  first_cell.isdigit()
                  or (len(first_cell) >= 8 and first_cell[:4].isdigit())
              ):
                ttb_id = first_cell
                if ttb_id in seen_ttb_ids:
                  continue
                seen_ttb_ids.add(ttb_id)
                variation_count += 1

                brand_nm = cols[1].strip() if len(cols) > 1 else "N/A"
                origin_desc = cols[3].strip() if len(cols) > 3 else "N/A"
                class_desc_val = (
                    cols[5].strip()
                    if len(cols) > 5
                    else (cols[4].strip() if len(cols) > 4 else "N/A")
                )

                # Find date pattern in row text
                date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", row_text)
                issue_dt = date_match.group(0) if date_match else ttb_date_from

                ttb_results.append({
                    "ttb_id": ttb_id,
                    "approval_date": issue_dt,
                    "issue_date": issue_dt,
                    "fanciful_name": brand_nm,
                    "brand_name": brand_nm,
                    "class_desc": class_desc_val,
                    "origin_desc": origin_desc,
                    "search_term": mark,
                })

          # Handle pagination
          next_btn = page.locator(
              "a:has-text('Next'), a:has-text('NEXT')"
          ).last
          if next_btn.is_visible():
            btn_class = next_btn.get_attribute("class") or ""
            if "disabled" in btn_class.lower():
              break
            else:
              next_btn.evaluate("node => node.click()")
              page.wait_for_timeout(3000)
          else:
            break

        logger.info(
            f"Successfully scraped {variation_count} NEW records for '{mark}'!"
        )
        break

      except Exception as e:
        logger.warning(f"TTB Scraper error for '{mark}': {e}")
        if attempt < 2:
          time.sleep(4)

    time.sleep(1)

  return ttb_results