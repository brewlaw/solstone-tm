import logging
import time

logger = logging.getLogger(__name__)


def scrape_ttb(page, start_date, end_date, brand_terms):
  """Scrapes TTB COLA Registry using JavaScript DOM clicks and pagination."""
  ttb_results = []
  seen_ttb_ids = set()

  if isinstance(brand_terms, str):
    brand_terms = [brand_terms]

  if not brand_terms or not page:
    return ttb_results

  for mark in brand_terms:
    if not mark:
      continue

    logger.info(f"Searching TTB for variation: '{mark}'...")

    for attempt in range(3):
      try:
        if attempt > 0:
          logger.info(f"TTB Connection Retry {attempt + 1}/3...")

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
          page.wait_for_timeout(3000)

        # Robust form filling with index fallback
        try:
          page.locator("input[name='dateFrom']").fill(start_date)
          page.locator("input[name='dateTo']").fill(end_date)
          page.locator("input[name='brandName']").fill(mark)
        except Exception:
          try:
            page.locator("#datecompletedfrom").fill(start_date)
            page.locator("#datecompletedto").fill(end_date)
            page.locator("#productname").fill(mark)
          except Exception:
            text_boxes = page.locator("input[type='text']")
            if text_boxes.count() >= 3:
              text_boxes.nth(0).fill(start_date)
              text_boxes.nth(1).fill(end_date)
              text_boxes.nth(2).fill(mark)

        # Select 'Either' radio button
        try:
          page.locator("input[value='E']").evaluate("node => node.click()")
        except Exception:
          try:
            page.locator("text='Either'").last.evaluate("node => node.click()")
          except Exception:
            pass

        page.wait_for_timeout(500)

        # JS Click on Search button
        page.locator("input[value='Search']").evaluate("node => node.click()")
        page.wait_for_timeout(5000)

        # Parse result table and handle pagination
        if (
            page.locator("text='Save Search Results To File'").is_visible()
            or page.locator("table").first.is_visible()
        ):
          variation_count = 0

          while True:
            if not page.locator("table").first.is_visible():
              break

            rows = page.locator("tr").all()
            for row in rows:
              row_text = row.inner_text()
              if "TTB ID" in row_text or "Results" in row_text:
                continue

              cols = row.locator("td").all_inner_texts()
              if len(cols) >= 6 and cols[0].strip().isdigit():
                ttb_id = cols[0].strip()

                if ttb_id in seen_ttb_ids:
                  continue
                seen_ttb_ids.add(ttb_id)
                variation_count += 1

                approval_dt = cols[3].strip() if len(cols) > 3 else "N/A"
                fanciful_nm = cols[4].strip() if len(cols) > 4 else "N/A"
                brand_nm = cols[5].strip() if len(cols) > 5 else "N/A"
                class_desc_val = (
                    cols[9].strip()
                    if len(cols) > 9
                    else (cols[6].strip() if len(cols) > 6 else "N/A")
                )

                ttb_results.append({
                    "ttb_id": ttb_id,
                    "approval_date": approval_dt,
                    "issue_date": approval_dt,
                    "fanciful_name": fanciful_nm,
                    "brand_name": brand_nm,
                    "class_desc": class_desc_val,
                    "search_term": mark,
                })

            # Check for next page link
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
              f"Successfully scraped {variation_count} NEW records for"
              f" '{mark}'!"
          )
          break

        else:
          logger.info(f"No TTB records found for '{mark}'.")
          break

      except Exception as e:
        logger.warning(f"TTB Scraper error for '{mark}': {e}")
        if attempt < 2:
          time.sleep(5)
        else:
          logger.error(f"TTB Scraper failed for '{mark}' after 3 attempts.")

    time.sleep(1)

  return ttb_results