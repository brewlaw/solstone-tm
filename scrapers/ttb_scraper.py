from html.parser import HTMLParser
import http.cookiejar
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


class TTBTableParser(HTMLParser):

  def __init__(self):
    super().__init__()
    self.in_tr = False
    self.in_td = False
    self.current_row = []
    self.rows = []
    self.current_text = ""

  def handle_starttag(self, tag, attrs):
    if tag == "tr":
      self.in_tr = True
      self.current_row = []
    elif tag == "td" and self.in_tr:
      self.in_td = True
      self.current_text = ""

  def handle_endtag(self, tag):
    if tag == "td" and self.in_td:
      self.in_td = False
      self.current_row.append(" ".join(self.current_text.split()))
    elif tag == "tr" and self.in_tr:
      self.in_tr = False
      if len(self.current_row) >= 5:
        # Verify column 0 contains a valid TTB ID
        first_cell = self.current_row[0].strip()
        if first_cell and (first_cell.isdigit() or len(first_cell) >= 8):
          self.rows.append(self.current_row)

  def handle_data(self, data):
    if self.in_td:
      self.current_text += data


def scrape_ttb(page_or_dummy, start_date, end_date, brand_terms):
  """Scrapes TTB COLA Registry using two-step HTTP Session requests (GET -> POST).

  Accepts `page_or_dummy` to maintain compatibility with clearance_tool call
  signatures.
  """
  results = []
  if not brand_terms:
    return results

  clean_terms = list(
      set([
          str(t).replace("%", "").strip()
          for t in brand_terms
          if str(t).replace("%", "").strip()
      ])
  )
  if not clean_terms:
    return results

  # CookieJar retains JSESSIONID cookie across GET and POST steps
  cj = http.cookiejar.CookieJar()
  opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
      ),
      "Accept": (
          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
      ),
      "Accept-Language": "en-US,en;q=0.9",
  }

  base_url = "https://www.ttbonline.gov/colasonline/publicSearchColasAdvanced.do"

  for term in clean_terms:
    try:
      # Step 1: GET request to initialize session cookie
      get_req = urllib.request.Request(base_url, headers=headers)
      with opener.open(get_req, timeout=10) as resp:
        _ = resp.read()

      # Step 2: POST form payload
      post_data = urllib.parse.urlencode({
          "action": "search",
          "searchCriteria.brandName": term,
          "searchCriteria.issueDateFrom": start_date,
          "searchCriteria.issueDateTo": end_date,
          "search": "Search",
      }).encode("utf-8")

      post_headers = headers.copy()
      post_headers["Content-Type"] = "application/x-www-form-urlencoded"
      post_req = urllib.request.Request(
          base_url, data=post_data, headers=post_headers, method="POST"
      )

      with opener.open(post_req, timeout=15) as resp:
        html_content = resp.read().decode("utf-8", errors="ignore")

      # Step 3: Parse response rows
      parser = TTBTableParser()
      parser.feed(html_content)

      for col_texts in parser.rows:
        ttb_id = col_texts[0].strip()
        brand_name = col_texts[1].strip() if len(col_texts) > 1 else ""
        fanciful_name = col_texts[2].strip() if len(col_texts) > 2 else ""
        class_desc = col_texts[3].strip() if len(col_texts) > 3 else ""
        issue_date = col_texts[4].strip() if len(col_texts) > 4 else ""

        results.append({
            "ttb_id": ttb_id,
            "brand_name": brand_name,
            "fanciful_name": fanciful_name,
            "class_desc": class_desc,
            "issue_date": issue_date,
            "search_term": term,
        })

    except Exception as e:
      logger.warning(f"TTB HTTP scraping error for term '{term}': {e}")
      continue

  return results