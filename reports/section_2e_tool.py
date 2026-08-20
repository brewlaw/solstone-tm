import streamlit as st
from analyzers.section_2e_analyzer import Section2EAnalyzer

def run():
    st.header("Section 2(e) Risk Analyzer")
    st.write("Evaluate a trademark for descriptiveness, geographic, surname, or other Section 2(e) refusal risks.")

    raw_mark = st.text_input("Full Trademark Name:", placeholder="e.g. COLORADO CRAFT BEER")

    if st.button("Analyze Mark", type="primary"):
        if not raw_mark.strip():
            st.warning("Please enter a trademark name.")
            return
            
        with st.spinner("Analyzing against USPTO Section 2(e) criteria..."):
            analyzer = Section2EAnalyzer(data_dir="data")
            raw_risk_data, feedback_summary = analyzer.analyze_mark(raw_mark, "Clearance")
            
            if feedback_summary:
                st.subheader("⚠️ Risk Feedback")
                for statement in feedback_summary:
                    st.warning(f"- {statement}")
            else:
                st.success("✅ No immediate Section 2(e) risks detected for this mark based on the datasets.")