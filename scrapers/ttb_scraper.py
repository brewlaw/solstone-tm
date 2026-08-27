import logging
import re
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def scrape_ttb(ttb_date_from, ttb_date_to, mark_list):
  """Scrapes TTB COLA Registry via direct HTTP POST requests (Zero Playwright RAM)."""
  ttb_results = []
  seen_ttb_ids = set()

  if isinstance(mark_list, str):
    mark_list = [mark_list]

  if not mark_list:
    return ttb_results

  clean_terms = list(
      dict.fromkeys([str(m).strip() for m in mark_list if str(m).strip()])
  )

  session = requests.Session()
  session.headers.update({
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
      ),
      "Accept": (
          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
      ),
      "Referer": (
          "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do"
      ),
  })

  # Initialize JSP Session Cookie
  try:
    session.get(
        "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do",
        timeout=10,
    )
  except Exception as e:
    logger.warning(f"TTB session initialization warning: {e}")

  post_url = "https://www.ttbonline.gov/colasonline/publicSearchColasBasicProcess.do?action=search"

  for mark in clean_terms:
    try:
      logger.info(f"Posting HTTP TTB query for '{mark}'...")
      payload = {
          "searchCriteria.dateCompletedFrom": ttb_date_from,
          "searchCriteria.dateCompletedTo": ttb_date_to,
          "searchCriteria.productOrFancifulName": mark,
          "searchCriteria.brandFancifulEq": "E",  # 'E' = Either Brand Name or Fanciful Name
          "action": "search",
      }

      resp = session.post(post_url, data=payload, timeout=15)
      if resp.status_code != 200:
        continue

      soup = BeautifulSoup(resp.text, "html.parser")
      rows = soup.find_all("tr")

      for row in rows:
        row_text = row.get_text(strip=True)
        if (
            "TTB ID" in row_text
            or "Total Matching" in row_text
            or "Brand Name" in row_text
        ):
          continue

        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < 3:
          continue

        # Extract TTB ID from link hrefs or text
        ttb_id = None
        for a in row.find_all("a", href=True):
          href = a["href"]
          link_text = a.get_text(strip=True)

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

        if not ttb_id and len(cols) >= 4:
          ttb_id = f"COLA_{abs(hash(''.join(cols))) % 100000000}"

        if ttb_id and ttb_id not in seen_ttb_ids:
          seen_ttb_ids.add(ttb_id)

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

    except Exception as e:
      logger.warning(f"TTB HTTP scrape error for '{mark}': {e}")
      continue

  return ttb_results