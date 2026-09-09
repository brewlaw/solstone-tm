def calculate_deadline(reg_date_str, status_str=""):
    if not reg_date_str or str(reg_date_str) in ["N/A", "nan", "None"] or pd.isna(reg_date_str): 
        return "Not Registered"
    try:
        reg_date = pd.to_datetime(reg_date_str)
        current_date = datetime.now()
        status_upper = str(status_str).upper() if status_str else ""
        
        # USPTO status strings indicating completed filings
        renewed_keywords = ["RENEWED", "ACCEPTED", "COMBINED SECTION 8 & 9", "SECTION 8 & 15", "REGISTERED AND RENEWED"]
        is_explicitly_renewed = any(kw in status_upper for kw in renewed_keywords)

        # 1. First Maintenance Window: Section 8 (5th to 6th year)
        sec8_start = reg_date + relativedelta(years=5)
        sec8_end = reg_date + relativedelta(years=6)

        if current_date < sec8_end:
            if sec8_start <= current_date < sec8_end:
                if is_explicitly_renewed:
                    pass  # Advanced early -> move to Section 8 & 9 cycle
                else:
                    return f"Sec 8: {sec8_start.strftime('%Y-%m-%d')} to {sec8_end.strftime('%Y-%m-%d')}"
            else:
                return f"Sec 8: {sec8_start.strftime('%Y-%m-%d')} to {sec8_end.strftime('%Y-%m-%d')}"

        # 2. Recurring 10-Year Renewal Windows: Section 8 & 9 (Years 9-10, 19-20, 29-30...)
        k = 1
        while True:
            sec89_start = reg_date + relativedelta(years=(10 * k - 1))
            sec89_end = reg_date + relativedelta(years=(10 * k))

            # If current date has passed this window, live mark has completed renewal
            if current_date >= sec89_end:
                k += 1
                continue

            # Upcoming renewal window
            if current_date < sec89_start:
                return f"Sec 8 & 9: {sec89_start.strftime('%Y-%m-%d')} to {sec89_end.strftime('%Y-%m-%d')}"

            # Inside active renewal window
            if sec89_start <= current_date < sec89_end:
                if is_explicitly_renewed:
                    k += 1
                    continue
                else:
                    return f"Sec 8 & 9: {sec89_start.strftime('%Y-%m-%d')} to {sec89_end.strftime('%Y-%m-%d')}"

    except Exception:
        return "Unknown"
