import os
import re
import csv

class Section2EAnalyzer:
    def __init__(self, data_dir="data"):
        """Loads the CSV dictionaries into memory to retain RAG metadata."""
        self.geo_terms = self._load_csv_to_dict(
            os.path.join(data_dir, "Geo_Descriptors_Master.csv"), "Geographic 2(e)(2)"
        )
        self.desc_terms = self._load_csv_to_dict(
            os.path.join(data_dir, "Descriptive_Terms_Master.csv"), "Descriptive 2(e)(1)"
        )
        self.laud_terms = self._load_csv_to_dict(
            os.path.join(data_dir, "Laudatory_Terms_Master.csv"), "Laudatory 2(e)(1)"
        )
        self.surname_terms = self._load_surname_csv(
            os.path.join(data_dir, "Surnames_Master.csv")
        )

    def _load_csv_to_dict(self, filepath, default_category):
        term_dict = {}
        try:
            with open(filepath, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames or len(reader.fieldnames) == 1:
                    f.seek(0)
                    for line in f.readlines()[1:]:
                        clean_term = line.strip().upper()
                        if clean_term:
                            term_dict[clean_term] = {
                                "Category": default_category,
                                "Risk_Level": "Moderate/High", 
                                "Legal_Basis": f"Flagged under {default_category} rules."
                            }
                else:
                    term_column = reader.fieldnames[0]
                    for row in reader:
                        clean_term = str(row[term_column]).strip().upper()
                        if clean_term:
                            term_dict[clean_term] = row
        except Exception as e:
            print(f"🚨 Warning: Could not load {filepath}. Error: {e}")
        return term_dict

    def _load_surname_csv(self, filepath):
        """Specifically handles the US Census dataset headers and applies a rarity threshold."""
        term_dict = {}
        threshold = 1000  # Ignore any surname with fewer than 1,000 people
        
        try:
            with open(filepath, mode='r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get('name', '').strip().upper()
                    if name:
                        count = row.get('count', '0')
                        try:
                            count_int = int(count)
                            
                            # Skip if the name doesn't meet our threshold
                            if count_int < threshold:
                                continue
                                
                            if count_int <= 5000:
                                rarity = "somewhat rare"
                            elif count_int <= 25000:
                                rarity = "relatively common"
                            else:
                                rarity = "very common"
                        except ValueError:
                            count_int = 0
                            rarity = "known"
                            continue # Skip invalid rows

                        term_dict[name] = {
                            "Category": "Surname 2(e)(4)",
                            "Count": f"{count_int:,}", # Formats with commas (e.g., 1,500)
                            "Rarity": rarity
                        }
        except Exception as e:
            print(f"🚨 Warning: Could not load {filepath}. Error: {e}")
        return term_dict

    def analyze_mark(self, raw_mark, report_type="Clearance"):
        """Scans the proposed mark and generates conversational feedback."""
        words_in_mark = raw_mark.upper().split()
        
        def find_matches(term_dictionary):
            found_data = []
            for word in words_in_mark:
                if word in term_dictionary:
                    match_info = {"Matched_Term": word}
                    match_info.update(term_dictionary[word])
                    found_data.append(match_info)
            return found_data

        results = {
            "geographic_2e2": find_matches(self.geo_terms),
            "descriptive_2e1": find_matches(self.desc_terms),
            "laudatory_2e1": find_matches(self.laud_terms),
            "surname_2e4": find_matches(self.surname_terms)
        }
        
        feedback = []
        
        if report_type == "Clearance":
            for match in results["geographic_2e2"]:
                feedback.append(f"The term '{match['Matched_Term']}' appears to be a geographic term, and may be relatively weak by itself or require a disclaimer (Section 2(e)(2)).")
            for match in results["descriptive_2e1"]:
                feedback.append(f"The term '{match['Matched_Term']}' appears to be descriptive. This may trigger a Section 2(e)(1) refusal or require proof of acquired distinctiveness.")
            for match in results["laudatory_2e1"]:
                feedback.append(f"The term '{match['Matched_Term']}' appears to be laudatory, and may be relatively weak by itself (Section 2(e)(1)).")
            for match in results["surname_2e4"]:
                feedback.append(f"The term '{match['Matched_Term']}' has surname significance. Current census data indicates {match.get('Count', 'a low number of')} people in the country have that name (making it a {match.get('Rarity', 'known')} surname). If the count is very low, this refusal risk decreases significantly (Section 2(e)(4)).")
        
        elif report_type == "Monitoring":
            for category, matches in results.items():
                for match in matches:
                    friendly_cat = category.split('_')[0].capitalize()
                    
                    if category == "surname_2e4":
                        feedback.append(f"Monitoring Context: '{match['Matched_Term']}' is a registered Surname ({match.get('Count')} people). It may exist in a 'crowded field', so enforcement should focus on identical goods/services.")
                    else:
                        feedback.append(f"Monitoring Context: Because '{match['Matched_Term']}' is a {friendly_cat} term, it may exist in a 'crowded field'. Enforcement should focus strictly on identical goods/services.")
                    
        if not feedback:
            feedback.append("No immediate Section 2(e) issues detected in dictionaries.")
            
        return results, feedback