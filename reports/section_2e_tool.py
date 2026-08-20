import os
import datetime
import streamlit as st
from analyzers.section_2e_analyzer import Section2EAnalyzer

OUTPUT_DIR = "outputs"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

def run():
    st.header("Section 2(e) Risk Analyzer")
    st.write("Evaluate a trademark for descriptiveness, geographic, surname, or other Section 2(e) refusal risks.")

    if 'section_2e_data' not in st.session_state:
        st.session_state['section_2e_data'] = None

    raw_mark = st.text_input("Full Trademark Name:", placeholder="e.g. COLORADO CRAFT BEER")

    if st.button("Analyze Mark", type="primary"):
        if not raw_mark.strip():
            st.warning("Please enter a trademark name.")
            return
            
        with st.spinner("Analyzing against USPTO Section 2(e) criteria..."):
            analyzer = Section2EAnalyzer(data_dir="data")
            raw_risk_data, feedback_summary = analyzer.analyze_mark(raw_mark, "Clearance")
            
            today = datetime.datetime.now()
            clean_mark = raw_mark.strip().upper()
            report_filename = os.path.join(OUTPUT_DIR, f"Section_2e_Analysis_{clean_mark.replace(' ', '_')}.txt")
            
            # Generate text summary report
            report_content = f"SECTION 2(e) RISK ANALYSIS REPORT\n"
            report_content += f"Mark Analyzed: {clean_mark}\n"
            report_content += f"Date: {today.strftime('%B %d, %Y %H:%M:%S')}\n"
            report_content += "=" * 50 + "\n\n"
            
            if feedback_summary:
                report_content += "RISK FEEDBACK / POTENTIAL REFUSALS DETECTED:\n"
                for stmt in feedback_summary:
                    report_content += f"- {stmt}\n"
            else:
                report_content += "No immediate Section 2(e) risks detected based on standard datasets.\n"

            with open(report_filename, "w", encoding="utf-8") as f:
                f.write(report_content)

            st.session_state['section_2e_data'] = {
                'raw_mark': clean_mark,
                'feedback_summary': feedback_summary,
                'report_filename': report_filename,
                'report_content': report_content
            }

    # --- DISPLAY ANALYSIS RESULTS & ARCHIVE BUTTON IF GENERATED ---
    if st.session_state.get('section_2e_data'):
        data = st.session_state['section_2e_data']
        
        st.subheader(f"Analysis Results for: {data['raw_mark']}")
        if data['feedback_summary']:
            for statement in data['feedback_summary']:
                st.warning(f"- {statement}")
        else:
            st.success("✅ No immediate Section 2(e) risks detected for this mark based on the datasets.")

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                label="📄 Download Analysis Summary (.txt)",
                data=data['report_content'],
                file_name=os.path.basename(data['report_filename']),
                mime="text/plain",
                use_container_width=True
            )
        with col2:
            if st.button("☁️ Archive to Google Drive", use_container_width=True, key="archive_2e"):
                from utils.drive_uploader import upload_to_drive
                with st.spinner("Archiving analysis to Google Drive..."):
                    drive_link = upload_to_drive(data['report_filename'])
                if drive_link:
                    st.success("☁️ Section 2(e) Analysis successfully archived to Google Drive!")