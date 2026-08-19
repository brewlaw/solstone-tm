import os
os.system("playwright install chromium")

import streamlit as st
from reports import status_report, clearance_monitoring

st.set_page_config(page_title="Solstone IP Suite", layout="wide", page_icon="⚖️")

# --- Add Logo to Sidebar ---
if os.path.exists("logo.jpg"):
    st.sidebar.image("logo.jpg", use_container_width=True)
# ---------------------------

st.sidebar.title("Solstone IP Tools")
st.sidebar.caption("Brew Law IP Suite")

tool = st.sidebar.radio(
    "Select Tool:", 
    ["Trademark Status Report", "Clearance & Monitoring Suite"]
)
# ... [rest of file remains the same]

if tool == "Trademark Status Report":
    status_report.run()
elif tool == "Clearance & Monitoring Suite":
    clearance_monitoring.run()