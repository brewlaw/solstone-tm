import logging
import re
import time

logger = logging.getLogger(__name__)


def apply_akamai_stealth(page):
  """Injects JavaScript overrides to pass Akamai Bot Manager (bobcmn) detection."""
  page.add_init_script("""
        // 1. Mask navigator.webdriver
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

        // 2. Mock Chrome runtime object
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };

        // 3. Mock languages and plugins
        Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });

        // 4. Override permissions query
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
        );
    """)


def scrape_ttb(page, ttb_date_from, ttb_date_to, mark_list):
  """Scrapes TTB COLA Registry bypassing Akamai Bot Manager."""
  ttb_results = []
  seen_ttb_ids = set()

  if isinstance(mark_list, str):
    mark_list = [mark_list]

  if not mark_list or not page:
    return ttb_results

  clean_terms = list(
      dict.fromkeys([str(m).strip() for m in mark_list if str(m).strip()])
  )

  # Apply stealth overrides before visiting TTB
  apply_akamai_stealth(page)

  ttb_url = "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do"

  for mark in clean_terms:
    if not mark:
      continue

    logger.info(f"Navigating to TTB for term '{mark}'...")

    try:
      page.goto(ttb_url, timeout=30000, wait_until="networkidle")

      # Give Akamai bobcmn script 2 seconds to complete verification
      page.wait_for_timeout(2000)

      # Handle disclaimer modal if present
      if page.locator("input[value='I Agree']").is_visible():
        page.locator("input[value='I Agree']").evaluate("node => node.click()")
        page.wait_for_timeout(1000)

      # Wait for input field to be ready
      input_sel = "#productname, input[name='searchCriteria.productOrFancifulName'], input[name='searchCriteria.brandName']"
      page.wait_for_selector(input_sel, timeout=15000)

      # Fill form fields
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

      page.locator(input_sel).fill(mark)

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

      # Wait for search results container
      try:
        page.wait_for_selector(
            "a:has-text('Save Search Results To File'), div.box table,"
            " table[width='785']",
            timeout=20000,
        )
      except Exception:
        logger.info(f"No results container loaded for '{mark}'")
        continue

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

          cols = [text.strip() for text in row.locator("td").all_inner_texts()]
          if len(cols) < 2:
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
              c_clean = cell.replace("-", "").strip()
              if c_clean.isdigit() and len(c_clean) >= 8:
                ttb_id = c_clean
                break

          if not ttb_id and len(cols) >= 3:
            ttb_id = f"COLA_{abs(hash(''.join(cols))) % 100000000}"

          if ttb_id and ttb_id not in seen_ttb_ids:
            seen_ttb_ids.add(ttb_id)
            variation_count += 1

            date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", row_text)
            approval_dt = date_match.group(0) if date_match else ttb_date_from

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

        # Next page navigation
        next_btn = page.locator("a:has-text('Next')").first
        if next_btn.is_visible():
          btn_class = next_btn.get_attribute("class") or ""
          if "disabled" in btn_class.lower():
            break
          next_btn.evaluate("node => node.click()")
          page.wait_for_timeout(2000)
        else:
          break

      logger.info(
          f"Successfully scraped {variation_count} NEW records for '{mark}'!"
      )

    except Exception as e:
      logger.warning(f"TTB error for '{mark}': {e}")
      continue

  return ttb_results