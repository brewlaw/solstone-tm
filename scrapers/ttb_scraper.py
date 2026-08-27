from html.parser import HTMLParser
import logging
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


class TTBTableParser(HTMLParser):

  def __init__(self):
    super().__init__()
    self.in_td = False
    self.in_tr = False
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
      self.current_row.append(self.current_text.strip())
    elif tag == "tr" and self.in_tr:
      self.in_tr = False
      if self.current_row:
        self.rows.append(self.current_row)

  def handle_data(self, data):
    if self.in_td:
      self.current_text += data


def scrape_ttb(page_or_dummy, start_date, end_date, brand_terms):
  """Scrapes TTB COLA Registry via fast, lightweight HTTP POST requests.

  Accepts `page_or_dummy` for backwards compatibility with call signatures.
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
  url = "https://www.ttbonline.gov/colasonline/publicSearchColasAdvanced.do"

  headers = {
      "User-Agent": (
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
          " (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
      ),
      "Content-Type": "application/x-www-form-urlencoded",
  }

  for term in clean_terms:
    try:
      data = {
          "action": "search",
          "searchCriteria.brandName": term,
          "searchCriteria.issueDateFrom": start_date,
          "searchCriteria.issueDateTo": end_date,
      }
      encoded_data = urllib.parse.urlencode(data).encode("utf-8")
      req = urllib.request.Request(
          url, data=encoded_data, headers=headers, method="POST"
      )

      with urllib.request.urlopen(req, timeout=12) as response:
        html_content = response.read().decode("utf-8", errors="ignore")

      parser = TTBTableParser()
      parser.feed(html_content)

      for col_texts in parser.rows:
        if len(col_texts) >= 5:
          ttb_id = col_texts[0]
          if ttb_id and (ttb_id.isdigit() or len(ttb_id) >= 8):
            results.append({
                "ttb_id": ttb_id,
                "brand_name": col_texts[1] if len(col_texts) > 1 else "",
                "fanciful_name": col_texts[2] if len(col_texts) > 2 else "",
                "class_desc": col_texts[3] if len(col_texts) > 3 else "",
                "issue_date": col_texts[4] if len(col_texts) > 4 else "",
                "search_term": term,
            })
    except Exception as e:
      logger.warning(f"TTB HTTP request error for '{term}': {e}")

  return results