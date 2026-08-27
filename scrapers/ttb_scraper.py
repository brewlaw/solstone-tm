import logging
import re
import requests
from bs4 import BeautifulSoup
import urllib3
import urllib.parse

# Suppress insecure request warnings for .gov legacy SSL certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


def scrape_ttb(ttb_date_from, ttb_date_to, mark_list):
  """Scrapes TTB COLA Registry via direct HTTP POST requests with relaxed SSL."""
  ttb_results = []
  seen_ttb_ids = set()

  if isinstance(mark_list, str):
    mark_list = [mark_list]

  if not mark_list:
    return ttb_results

  clean_terms = list(
      dict.fromkeys([str(m).strip() for m in mark_list if str(m).strip()])
  )

  # Create a session to persist cookies across requests (JSESSIONID)
  session = requests.Session()
  session.verify = False  # Critical for bypassing .gov SSL errors
  session.headers.update({
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
      ),
      "Accept": (
          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
      ),
      "Accept-Language": "en-US,en;q=0.9",
      "Content-Type": "application/x-www-form-urlencoded",
      "Origin": "https://www.ttbonline.gov",
      "Referer": (
          "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do"
      ),
  })

  # Step 1: Establish Session & retrieve JSESSIONID cookie
  try:
    session.get(
        "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do",
        timeout=15,
    )
  except Exception as e:
    logger.warning(f"TTB session initialization warning: {e}")

  post_url = "https://www.ttbonline.gov/colasonline/publicSearchColasBasicProcess.do?action=search"

  for mark in clean_terms:
    try:
      logger.info(f"Posting HTTP TTB query for '{mark}'...")
      
      # Step 2: Build the form payload exactly as a browser would
      payload = {
          "searchCriteria.dateCompletedFrom": ttb_date_from,
          "searchCriteria.dateCompletedTo": ttb_date_to,
          "searchCriteria.productOrFancifulName": mark,
          "searchCriteria.brandFancifulEq": "E",  # 'E' = Either Brand or Fanciful Name
          "action": "search",
      }
      
      # URL-encode the payload data for the application/x-www-form-urlencoded content type
      encoded_payload = urllib.parse.urlencode(payload)

      # Step 3: Execute the POST request
      resp = session.post(post_url, data=encoded_payload, timeout=20)
      
      if resp.status_code != 200:
        logger.warning(f"TTB returned status code {resp.status_code} for '{mark}'")
        continue

      # Step 4: Parse the returned HTML using BeautifulSoup
      soup = BeautifulSoup(resp.text, "html.parser")
      
      # Locate the results table rows
      rows = soup.find_all("tr")

      variation_count = 0
      for row in rows:
        row_text = row.get_text(strip=True)
        # Skip header rows and summary rows
        if (
            "TTB ID" in row_text
            or "Total Matching" in row_text
            or "Brand Name" in row_text
        ):
          continue

        cols = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cols) < 3:
          continue

        # Extract TTB ID from link hrefs (e.g., ttbid=XXXX)
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

        # Fallback: Check cell text for IDs
        if not ttb_id:
          for cell in cols:
            c_clean = cell.replace("-", "").strip()
            if c_clean.isdigit() and len(c_clean) >= 8:
              ttb_id = c_clean
              break

        # Fallback: Hash generation if row is valid but ID is hidden
        if not ttb_id and len(cols) >= 4:
          ttb_id = f"COLA_{abs(hash(''.join(cols))) % 100000000}"

        if ttb_id and ttb_id not in seen_ttb_ids:
          seen_ttb_ids.add(ttb_id)
          variation_count += 1

          # Extract issue date from row text
          date_match = re.search(r"\b\d{2}/\d{2}/\d{4}\b", row_text)
          approval_dt = date_match.group(0) if date_match else ttb_date_from

          # Extract text columns based on standard TTB HTML layout
          fanciful_nm = cols[0] if len(cols) > 0 else "N/A"
          brand_nm = cols[1] if len(cols) > 1 else fanciful_nm
          origin_desc = cols[3] if len(cols) > 3 else "N/A"
          
          # Combine Class and Type columns for cleaner display
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
          
      logger.info(f"Successfully scraped {variation_count} records for '{mark}' via HTTP POST.")

    except Exception as e:
      logger.warning(f"TTB HTTP scrape error for '{mark}': {e}")
      continue

  return ttb_results