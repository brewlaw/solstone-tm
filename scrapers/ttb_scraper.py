import logging
import os
import time

logger = logging.getLogger(__name__)


def scrape_ttb(page, ttb_date_from, ttb_date_to, mark_list):
  """Submits TTB search and saves a full-page debug screenshot."""
  ttb_results = []
  if not mark_list or not page:
    return ttb_results

  clean_terms = (
      [mark_list]
      if isinstance(mark_list, str)
      else [str(m).strip() for m in mark_list if str(m).strip()]
  )
  target_term = clean_terms[0] if clean_terms else "WINGMAN"

  os.makedirs("outputs", exist_ok=True)
  debug_path = "outputs/ttb_debug.png"

  try:
    logger.info(f"Navigating to TTB for diagnostic run ('{target_term}')...")
    page.goto(
        "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do",
        timeout=30000,
        wait_until="domcontentloaded",
    )

    # Dismiss modal if present
    if page.locator("input[value='I Agree']").is_visible():
      page.locator("input[value='I Agree']").evaluate("node => node.click()")
      page.wait_for_timeout(1000)

    # Fill form
    try:
      page.locator("input[name='searchCriteria.dateCompletedFrom']").fill(
          ttb_date_from
      )
      page.locator("input[name='searchCriteria.dateCompletedTo']").fill(
          ttb_date_to
      )
      page.locator("input[name='searchCriteria.productOrFancifulName']").fill(
          target_term
      )
    except Exception:
      if page.locator("#productname").is_visible():
        page.locator("#datecompletedfrom").fill(ttb_date_from)
        page.locator("#datecompletedto").fill(ttb_date_to)
        page.locator("#productname").fill(target_term)

    # Select 'Either'
    try:
      page.locator("input[value='E']").evaluate("node => node.click()")
    except Exception:
      pass

    page.wait_for_timeout(500)

    # Submit search
    search_btn = page.locator(
        "input[value='Search'], input[alt*='search'], input[type='submit']"
    ).first
    search_btn.evaluate("node => node.click()")

    # Wait for response and capture full-page screenshot
    page.wait_for_timeout(5000)
    page.screenshot(path=debug_path, full_page=True)
    logger.info(f"Successfully saved TTB debug screenshot to {debug_path}")

  except Exception as e:
    logger.warning(f"Error capturing TTB debug screenshot: {e}")
    try:
      page.screenshot(path=debug_path, full_page=True)
    except Exception:
      pass

  return ttb_results