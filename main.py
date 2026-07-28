import os
import re
import datetime
from datetime import timedelta
from playwright.sync_api import sync_playwright

# --- Verify these imports match your exact folder structure! ---
from scrapers.uspto_scraper import scrape_uspto
from scrapers.ttb_scraper import scrape_ttb
from scrapers.google_scraper import scrape_google
from reports.pdf_generator import generate_pdf
from reports.docx_generator import generate_docx


def get_dynamic_names(timeframe, raw_mark):
    today = datetime.date.today()
    current_year = today.year
    
    clean_mark = re.sub(r'[\/*?:"<>|]', '', raw_mark).strip().upper()
    
    base_filename = f"{clean_mark}_Monitoring_Report_Raw_Results"
    report_title = f"Trademark Monitoring Report Raw Results - {clean_mark}"
    
    if 0.2 <= timeframe <= 0.4:
        q_ends = {
            1: datetime.date(current_year, 3, 31),
            2: datetime.date(current_year, 6, 30),
            3: datetime.date(current_year, 9, 30),
            4: datetime.date(current_year, 12, 31)
        }
        
        closest_q = None
        target_year = current_year
        min_delta = float('inf')
        
        for q, end_date in q_ends.items():
            delta = abs((today - end_date).days)
            if delta < min_delta:
                min_delta = delta
                closest_q = q
                
        prev_year_q4 = datetime.date(current_year - 1, 12, 31)
        if abs((today - prev_year_q4).days) < min_delta:
            min_delta = abs((today - prev_year_q4).days)
            closest_q = 4
            target_year = current_year - 1
            
        if min_delta <= 31:
            base_filename = f"Q{closest_q} {target_year} Monitoring Report Raw Results - {clean_mark}"
            report_title = f"Q{closest_q} {target_year} Trademark Monitoring Report Raw Results - {clean_mark}"
        else:
            base_filename = f"Mid-Quarter Monitoring Report Raw Results - {clean_mark}"
            report_title = f"Mid-Quarter Trademark Monitoring Report Raw Results - {clean_mark}"
            
    elif timeframe == 0.5:
        if today.month <= 6:
            base_filename = f"Q1-Q2 {current_year} Monitoring Report Raw Results - {clean_mark}"
            report_title = f"Q1-Q2 {current_year} Trademark Monitoring Report Raw Results - {clean_mark}"
        else:
            base_filename = f"Q3-Q4 {current_year} Monitoring Report Raw Results - {clean_mark}"
            report_title = f"Q3-Q4 {current_year} Trademark Monitoring Report Raw Results - {clean_mark}"
            
    elif timeframe == 1.0:
        base_filename = f"{current_year} Monitoring Report Raw Results - {clean_mark}"
        report_title = f"{current_year} Trademark Monitoring Report Raw Results - {clean_mark}"
        
    return base_filename, report_title

# ==========================================
# 1. USER INPUT & CONFIGURATION
# ==========================================
print("\nPRO TIP: If your mark can be one word or two, enter it WITH spaces (e.g., 'SUN SHINE').")
raw_mark = input("Enter the full mark you want to search for: ").strip()
squished_mark = raw_mark.replace(" ", "")

# --- CLIENT INFO INPUT ---
client_name = input("Enter the Client Name: ").strip()
attention_name = input("Enter the Attention Name (e.g., Adeline Druart): ").strip()
client_email = input("Enter the Email Address(es): ").strip()

print("\nPRO TIP: Filtering by a dominant term catches variations like 'BLACK BEAR' if you search 'RED BEAR'.")
dominant_term = input("Is there a dominant/core word in this mark? (Leave blank if none): ").strip().upper()

print("\nPRO TIP: Adding a phonetic equivalent catches sound-alikes (e.g., typing 'BEER' if the mark is 'BEAR').")
phonetic_term = input("Enter a phonetic equivalent or alternate spelling (Leave blank if none): ").strip().upper()

print("\nPRO TIP: Adding a conceptual equivalent catches meaning-alikes (e.g., 'GRIZZLY' for 'BEAR' or 'LOBO' for 'WOLF').")
conceptual_term = input("Enter a conceptually identical term or translation (Leave blank if none): ").strip().upper()

print("\nPRO TIP: Adding a substring root catches puns and embedded words (e.g., typing 'CELOT' catches 'HOPCELOT').")
substring_term = input("Enter a root substring (Leave blank if none): ").strip().upper()

today = datetime.datetime.now()
lookback_input = input("How many years back do you want to search? (Leave blank for max/all-time): ").strip()

# Calculate the TTB 15-year max date
try:
    max_start_date = today.replace(year=today.year - 15) + timedelta(days=1)
except ValueError:
    max_start_date = today.replace(year=today.year - 15, day=28) + timedelta(days=1)

# --- NEW DATE LOGIC ---
if not lookback_input:
    use_all_time = True
    timeframe = 15.0  # Used for file naming conventions
    ttb_start_date = max_start_date # TTB is still capped at 15 years
    google_date_from = "1900-01-01" # Simulates all-time for Google
else:
    use_all_time = False
    try:
        timeframe = float(lookback_input)
        if timeframe >= 15.0:
            ttb_start_date = max_start_date
        else:
            ttb_start_date = today - timedelta(days=(timeframe * 365.25))
            
        uspto_date_from = ttb_start_date.strftime("%Y%m%d")
        google_date_from = ttb_start_date.strftime("%Y-%m-%d")
    except ValueError:
        use_all_time = True
        timeframe = 15.0
        ttb_start_date = max_start_date
        google_date_from = "1900-01-01"

# Formatting the end dates (Always today)
ttb_date_to = today.strftime("%m/%d/%Y")
uspto_date_to = today.strftime("%Y%m%d")
google_date_to = today.strftime("%Y-%m-%d")

# Formatting the TTB start date
ttb_date_from = ttb_start_date.strftime("%m/%d/%Y")

current_date_file = today.strftime("%Y-%m-%d")
timestamp = today.strftime("%H%M%S") 

# Query Formatting
words = raw_mark.split()
web_mark_base = f'("{raw_mark}" OR "{squished_mark}")' if raw_mark != squished_mark else f'"{raw_mark}"'

uspto_spaced = " AND ".join([f"CM2:{w}*" for w in words])
uspto_mark = f"({uspto_spaced}) OR (CM2:{squished_mark}*)" if raw_mark != squished_mark else uspto_spaced

# Initialize the TTB List with the exact mark
ttb_marks_list = ["%" + "%".join(words) + "%"]

# --- DOMINANT TERM EXPANSION ---
if dominant_term:
    web_mark_base = f'{web_mark_base} OR "{dominant_term}"'
    uspto_mark = f"({uspto_mark}) OR (CM2:{dominant_term}*)"
    ttb_marks_list.append(f"%{dominant_term}%")

# --- PHONETIC EQUIVALENT EXPANSION ---
if phonetic_term:
    web_mark_base = f'{web_mark_base} OR "{phonetic_term}"'
    uspto_mark = f"({uspto_mark}) OR (CM2:{phonetic_term}*)"
    ttb_marks_list.append(f"%{phonetic_term}%")

# --- CONCEPTUAL EQUIVALENT EXPANSION ---
if conceptual_term:
    web_mark_base = f'{web_mark_base} OR "{conceptual_term}"'
    uspto_mark = f"({uspto_mark}) OR (CM2:{conceptual_term}*)"
    ttb_marks_list.append(f"%{conceptual_term}%")

# --- SUBSTRING / PUN EXPANSION ---
if substring_term:
    web_mark_base = f'{web_mark_base} OR "{substring_term}"'
    uspto_mark = f"({uspto_mark}) OR (CM2:*{substring_term}*)"
    ttb_marks_list.append(f"%{substring_term}%")

# Remove any duplicate terms from the TTB list
ttb_marks_list = list(set(ttb_marks_list))

# Build USPTO query based on all-time flag
if use_all_time:
    uspto_query = f"({uspto_mark}) AND IC:(\"030\" OR \"032\" OR \"033\" OR \"043\")"
else:
    uspto_query = f"({uspto_mark}) AND IC:(\"030\" OR \"032\" OR \"033\" OR \"043\") AND FD:[{uspto_date_from} TO {uspto_date_to}]"

# Generate Excel filename
safe_mark = re.sub(r'[^A-Z0-9]', '_', squished_mark.upper())
excel_filename = f"{safe_mark}-USPTO-EXPORT-{current_date_file}_{timestamp}.xlsx"

print(f"\nStarting Modular Clearance for '{raw_mark}'...")

# ==========================================
# 2. RUN PLAYWRIGHT SCRAPERS (USPTO & TTB)
# ==========================================
with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True, 
        args=[
            '--disable-popup-blocking', 
            '--disable-notifications', 
            '--disable-infobars',
            '--disable-custom-protocol-handlers' 
        ]
    )
    
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        accept_downloads=True,
        permissions=[] 
    )
    page = context.new_page()

    uspto_data = scrape_uspto(page, uspto_query, excel_filename)
    ttb_data = scrape_ttb(page, ttb_date_from, ttb_date_to, ttb_marks_list)
    
    browser.close()

# ==========================================
# 3. RUN WEB SCRAPER (Google via SerpApi)
# ==========================================
google_data = scrape_google(web_mark_base, raw_mark, google_date_from, google_date_to)

# ==========================================
# 4. GENERATE REPORTS
# ==========================================
base_filename, report_title = get_dynamic_names(timeframe, raw_mark)

pdf_filename = f"{base_filename}.pdf"
docx_filename = f"{base_filename}.docx"

# Format a pretty date for the Word document's metadata table
report_date = today.strftime("%B %d, %Y")

print("\nGenerating Reports...")

# 1. Generate the PDF and capture the page numbers!
try:
    page_data = generate_pdf(
        raw_mark, 
        squished_mark, 
        ttb_date_from, 
        ttb_date_to, 
        uspto_data, 
        ttb_data, 
        google_data, 
        pdf_filename, 
        report_title
    )
    print(f"✅ Successfully generated PDF: {pdf_filename}")
except Exception as e:
    print(f"🚨 Error generating PDF: {e}")
    # Fallback just in case the PDF crashes so the Word Doc can still generate
    page_data = {'uspto_start': 0, 'uspto_end': 0, 'ttb_start': 0, 'ttb_end': 0, 'web_start': 0, 'web_end': 0} 

# 2. Generate the Word Document using those page numbers!
try:
    generate_docx(
        client_name, 
        attention_name, 
        client_email, 
        report_date, 
        raw_mark, 
        report_title, 
        page_data, 
        docx_filename
    )
    print(f"✅ Successfully generated Word Doc: {docx_filename}")
except Exception as e:
    print(f"🚨 Error generating Word Doc: {e}")

# Uncomment and adjust this block when you are ready to plug your Word generator back in
# 2. Generate the Word Document using those page numbers!
try:
    generate_docx(
        client_name, 
        attention_name, 
        client_email, 
        report_date, 
        raw_mark, 
        report_title, 
        page_data, 
        docx_filename
    )
    print(f"✅ Successfully generated Word Doc: {docx_filename}")
except Exception as e:
    print(f"🚨 Error generating Word Doc: {e}")
