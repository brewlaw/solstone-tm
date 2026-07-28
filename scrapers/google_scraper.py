import requests
import time

# Paste your SerpApi key here
SERPAPI_KEY = "a89a4b348d884eb64ad037309a187ca3872d0073ab0de4dfbcb8cc2501a413ad"

def scrape_google(web_mark_base, raw_mark, date_from, date_to):
    web_results = []
    print("\nFetching Web Search results via SerpApi...")
    
    target_sites = ['untappd.com', 'cellartracker.com', 'distiller.com']
    url = "https://serpapi.com/search.json"
    
    for domain in target_sites:
        print(f" -> Searching {domain} for '{raw_mark}' between {date_from} and {date_to}...")
        site_query = f'{web_mark_base} site:{domain} after:{date_from} before:{date_to}'
        site_result_count = 0
        
        # Paginate up to 3 pages (max 30 results per site) to protect API credits
        for page in range(3):
            payload = {
                "engine": "google",
                "q": site_query,
                "num": 10, # Standard default
                "start": page * 10, # Offsets by 0, 10, 20
                "api_key": SERPAPI_KEY
            }
            
            try:
                response = requests.get(url, params=payload, timeout=15)
                if response.status_code != 200:
                    print(f" 🚨 SerpApi Error: {response.status_code} - {response.text}")
                    break
                    
                data = response.json()
                
                # Check if this page actually has results
                if "organic_results" in data and data["organic_results"]:
                    for item in data["organic_results"]:
                        link = str(item.get("link", ""))
                        
                        # Deduplication: Google sometimes overlaps results between pages
                        if not any(r['link'] == link for r in web_results):
                            web_results.append({
                                "title": item.get("title", "No Title"),
                                "link": link,
                                "domain": domain
                            })
                            site_result_count += 1
                else:
                    # No more results on this page, break the loop early to save credits!
                    break
                    
            except Exception as e:
                print(f"Web Scraper API error for {domain}: {e}")
                break
                
            time.sleep(1) # Courteous rate limiting
            
        print(f"    Found {site_result_count} unique results from {domain}.")
        
    return web_results