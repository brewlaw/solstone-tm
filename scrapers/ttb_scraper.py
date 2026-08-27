import logging
import re
import time

logger = logging.getLogger(__name__)


def scrape_ttb(page, ttb_date_from, ttb_date_to, mark_list):
  """Scrapes TTB COLA Registry extracting TTB IDs from link URLs and text cells."""
  ttb_results = []
  seen_ttb_ids = set()

  if isinstance(mark_list, str):
    mark_list = [mark_list]

  if not mark_list or not page:
    return ttb_results

  clean_terms = []
  for m in mark_list:
    t = str(m).strip()
    if t and t not in clean_terms:
      clean_terms.append(t)

  for mark in clean_terms:
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
          page.wait_for_timeout(1500)

        # Fill Basic Search inputs
        try:
          page.locator("input[name='searchCriteria.dateCompletedFrom']").fill(
              ttb_date_from
          )
          page.locator("input[name='searchCriteria.dateCompletedTo']").fill(
              ttb_date_to
          )
          page.locator(
              "input[name='searchCriteria.productOrFancifulName']"
          ).fill(mark)
        except Exception:
          text_boxes = page.locator("input[type='text']")
          if text_boxes.count() >= 3:
            text_boxes.nth(0).fill(ttb_date_from)
            text_boxes.nth(1).fill(ttb_date_to)
            text_boxes.nth(2).fill(mark)

        # Select 'Either' radio button
        try:
          page.locator("input[value='E']").evaluate("node => node.click()")
        except Exception:
          pass

        page.wait_for_timeout(500)

        # Click Search button
        search_btn = page.locator(
            "input[value='Search'], input[alt*='search'], input[type='submit']"
        ).first
        search_btn.evaluate("node => node.click()")
        page.wait_for_timeout(4000)

        # Parse results table
        if (
            page.locator("text='Save Search Results To File'").is_visible()
            or page.locator("table").first.is_visible()
        ):
          variation_count = 0
          page_count = 0

          while page_count < 4:  # Cap at 4 pages per term for memory speed
            page_count += 1
            if not page.locator("table").first.is_visible():
              break

            rows = page.locator("tr").all()
            for row in rows:
              row_text = row.inner_text().strip()
              if (
                  "TTB ID" in row_text
                  or "Total Matching" in row_text
                  or "Brand Name" in row_text
                  or "Fanciful Name" in row_text
              ):
                continue

              cols = [
                  text.strip() for text in row.locator("td").all_inner_texts()
              ]
              if len(cols) < 2:
                continue

              # --- EXTRACT TTB ID ---
              ttb_id = None

              # Check 1: Numeric ID in Col 0 (Advanced search layout)
              c0_clean = cols[0].replace("-", "").strip()
              if c0_clean.isdigit() and len(c0_clean) >= 8:
                ttb_id = cols[0].strip()

              # Check 2: Parse ttbid parameter from link hrefs (Basic search layout)
              if not ttb_id:
                links = row.locator("a").all()
                for link in links:
                  href = link.get_attribute("href") or ""
                  m = re.search(r"ttbid=(\d+)", href, re.IGNORECASE)
                  if m:
                    ttb_id = m.group(1)
                    break
                  link_text = link.inner_text().strip()
                  if link_text.isdigit() and len(link_text) >= 8:
                    ttb_id = link_text
                    break

              # Check 3: Search all cell texts for numeric string
              if not ttb_id:
                for cell in cols:
                  c_clean = cell.replace("-", "").strip()
                  if c_clean.isdigit() and len(c_clean) >= 8:
                    ttb_id = c_clean
                    break

              # Check 4: Fallback unique ID generation if valid row content
              if not ttb_id and len(cols) >= 3:
                row_hash = abs(hash("".join(cols))) % 100000000
                ttb_id = f"COLA_{row_hash}"

              if ttb_id and ttb_id not in seen_ttb_ids:
                seen_ttb_ids.add(ttb_id)
                variation_count += 1

                # Extract date MM/DD/YYYY from row text
                date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", row_text)
                approval_dt = (
                    date_match.group(0) if date_match else ttb_date_from
                )

                fanciful_nm = cols[0] if len(cols) > 0 else "N/A"
                brand_nm = cols[1] if len(cols) > 1 else fanciful_nm
                origin_desc = cols[3] if len(cols) > 3 else "N/A"
                class_desc_val = (
                    f"{cols[4]} - {cols[5]}"
                    if len(cols) > 5
                    else (cols[4] if len(cols) > 4 else "N/A")
                )

                ttb_results.append({
                    "ttb_id": ttb_id,
                    "approval_date": approval_dt,
                    "issue_date": approval_dt,
                    "fanciful_name": fanciful_nm,
                    "brand_name": brand_nm,
                    "origin_desc": origin_desc,
                    "class_desc": class_desc_val,
                    "search_term": mark,
                })

            # Pagination handling
            next_btn = page.locator(
                "a:has-text('Next'), a:has-text('NEXT')"
            ).last
            if next_btn.is_visible():
              btn_class = next_btn.get_attribute("class") or ""
              if "disabled" in btn_class.lower():
                break
              next_btn.evaluate("node => node.click()")
              page.wait_for_timeout(2000)
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
          time.sleep(3)

    time.sleep(1)

  return ttb_results