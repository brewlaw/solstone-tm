import logging
import re
import time

logger = logging.getLogger(__name__)


def scrape_ttb(page, ttb_date_from, ttb_date_to, mark_list):
  """Scrapes TTB COLA Registry with DOM inspection fixes."""
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

    for attempt in range(2):
      try:
        page.goto(
            "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do",
            timeout=25000,
            wait_until="domcontentloaded",
        )

        if page.locator("input[value='I Agree']").is_visible():
          page.locator("input[value='I Agree']").evaluate(
              "node => node.click()"
          )
          page.wait_for_timeout(1000)

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

        try:
          page.locator("input[value='E']").evaluate("node => node.click()")
        except Exception:
          pass

        page.wait_for_timeout(300)

        search_btn = page.locator(
            "input[value='Search'], input[alt*='search'], input[type='submit']"
        ).first
        search_btn.evaluate("node => node.click()")

        try:
          page.wait_for_selector(
              "a:has-text('Save Search Results To File'), div.box table,"
              " table[width='785']",
              timeout=15000,
          )
        except Exception:
          logger.info(f"No results container loaded for '{mark}'")
          break

        variation_count = 0
        page_count = 0

        while page_count < 3:
          page_count += 1
          rows = page.locator("tr").all()

          for row in rows:
            row_text = row.inner_text().strip()
            if (
                "Brand Name" in row_text
                or "TTB ID" in row_text
                or "Total Matching" in row_text
            ):
              continue

            cols = [
                text.strip() for text in row.locator("td").all_inner_texts()
            ]
            if len(cols) < 3:
              continue

            ttb_id = None
            links = row.locator("a").all()
            for link in links:
              href = link.get_attribute("href") or ""
              link_text = link.inner_text().strip()

              m = re.search(r"ttbid=(\d+)", href, re.IGNORECASE)
              if m:
                ttb_id = m.group(1)
                break
              if link_text.isdigit() and len(link_text) >= 8:
                ttb_id = link_text
                break

            if not ttb_id:
              for cell in cols:
                cell_clean = cell.replace("-", "").strip()
                if cell_clean.isdigit() and len(cell_clean) >= 8:
                  ttb_id = cell_clean
                  break

            if not ttb_id and len(cols) >= 4:
              row_hash = abs(hash("".join(cols))) % 100000000
              ttb_id = f"COLA_{row_hash}"

            if ttb_id and ttb_id not in seen_ttb_ids:
              seen_ttb_ids.add(ttb_id)
              variation_count += 1

              date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", row_text)
              approval_dt = date_match.group(0) if date_match else ttb_date_from

              fanciful_nm = cols[0] if len(cols) > 0 else "N/A"
              brand_nm = cols[1] if len(cols) > 1 else "N/A"
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

          next_btn = page.locator("a:has-text('Next')").first
          if next_btn.is_visible():
            btn_class = next_btn.get_attribute("class") or ""
            if "disabled" in btn_class.lower():
              break
            next_btn.evaluate("node => node.click()")
            page.wait_for_timeout(1500)
          else:
            break

        logger.info(
            f"Successfully scraped {variation_count} NEW records for '{mark}'!"
        )
        break

      except Exception as e:
        logger.warning(f"TTB error for '{mark}': {e}")
        if attempt < 1:
          time.sleep(2)

  return ttb_results