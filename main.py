import os
os.system("playwright install chromium")

import streamlit as st
from reports import status_report, clearance_tool, monitoring_tool, section_2e_tool

st.set_page_config(page_title="Solstone IP Suite", layout="wide", page_icon="⚖️")

# --- Add Logo to Sidebar ---
if os.path.exists("logo.jpg"):
    st.sidebar.image("logo.jpg", use_container_width=True)
# ---------------------------

st.sidebar.title("Solstone IP Tools")
st.sidebar.caption("Brew Law IP Suite")

# Updated Radio Buttons
tool = st.sidebar.radio(
    "Select Tool:", 
    [
        "Trademark Status Report", 
        "Full Clearance Search",
        "Trademark Monitoring Suite",
        "Section 2(e) Risk Analyzer",
        "Cloud Report Archive"
    ]
)

def show_drive_archive():
    st.header("Solstone Cloud Report Archive")
    st.write("Access all historically generated clearance, status, and monitoring reports stored on Google Drive.")
    
    from utils.drive_uploader import list_drive_reports
    with st.spinner("Fetching reports from Google Drive..."):
        files = list_drive_reports()
    
    if not files:
        st.info("No reports found in Google Drive yet.")
        return

    for file in files:
        col1, col2 = st.columns([3, 1])
        with col1:
            st.write(f"📄 **{file['name']}**")
            st.caption(f"Created: {file['createdTime'][:10]}")
        with col2:
            st.markdown(f"[🔗 View in Drive]({file['webViewLink']})")
        st.divider()

# Tool Router
if tool == "Trademark Status Report":
    status_report.run()
elif tool == "Full Clearance Search":
    clearance_tool.run()
elif tool == "Trademark Monitoring Suite":
    monitoring_tool.run()
elif tool == "Section 2(e) Risk Analyzer":
    section_2e_tool.run()
elif tool == "Cloud Report Archive":
    show_drive_archive()