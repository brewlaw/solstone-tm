import os
os.system("playwright install chromium")

import streamlit as st
from reports import status_report, clearance_tool, monitoring_tool, section_2e_tool
from utils.saved_searches import get_saved_searches, delete_saved_search

st.set_page_config(page_title="Solstone IP Suite", layout="wide", page_icon="⚖️")

if os.path.exists("logo.jpg"):
    st.sidebar.image("logo.jpg", use_container_width=True)

st.sidebar.title("Solstone IP Tools")
st.sidebar.caption("Brew Law IP Suite")

tool = st.sidebar.radio(
    "Select Tool:", 
    [
        "Trademark Status Report", 
        "Full Clearance Search",
        "Saved Quarterly Searches",
        "Trademark Monitoring Suite",
        "Section 2(e) Risk Analyzer",
        "Cloud Report Archive"
    ]
)

def show_saved_searches():
    st.header("Saved Quarterly Clearance Searches")
    st.write("Manage client search profiles and trigger re-runs for new quarters.")

    saved_searches = get_saved_searches()

    if not saved_searches:
        st.info("No saved search profiles found. Create one directly within the Full Clearance Search tool.")
        return

    for name, params in saved_searches.items():
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
            with col1:
                st.markdown(f"### 📌 {name}")
                st.caption(f"**Client:** {params.get('client_name', 'N/A')} | **Mark:** {params.get('raw_mark', 'N/A')}")
            with col2:
                st.write(f"🕒 **Last Ran:**")
                st.info(params.get('last_run', 'Never'))
            with col3:
                if st.button("▶️ Load & Run Search", key=f"run_{name}", use_container_width=True):
                    st.session_state['load_profile_key'] = name
                    st.session_state['main_tool_router'] = "Full Clearance Search"
                    st.rerun()
            with col4:
                if st.button("🗑️ Delete Profile", key=f"del_prof_{name}", use_container_width=True):
                    delete_saved_search(name)
                    st.toast(f"Profile '{name}' deleted!")
                    st.rerun()
            st.divider()

def show_drive_archive():
    st.header("Solstone Cloud Report Archive")
    st.write("Access and manage all historically generated reports stored on Google Drive.")
    
    from utils.drive_uploader import list_drive_reports, trash_drive_file
    with st.spinner("Fetching reports from Google Drive..."):
        files = list_drive_reports()
    
    if not files:
        st.info("No reports found in Google Drive yet.")
        return

    for file in files:
        col1, col2, col3 = st.columns([6, 2, 2])
        
        with col1:
            st.write(f"📄 **{file['name']}**")
            st.caption(f"Created: {file['createdTime'][:10]}")
            
        with col2:
            st.markdown(f"[🔗 View in Drive]({file['webViewLink']})")
            
        with col3:
            if st.button("🗑️ Delete", key=f"del_{file['id']}", use_container_width=True):
                with st.spinner("Moving to trash..."):
                    if trash_drive_file(file['id']):
                        st.toast(f"Report moved to trash!")
                        st.rerun()
                        
        st.divider()

# Tool Router
if tool == "Trademark Status Report":
    status_report.run()
elif tool == "Full Clearance Search":
    clearance_tool.run()
elif tool == "Saved Quarterly Searches":
    show_saved_searches()
elif tool == "Trademark Monitoring Suite":
    monitoring_tool.run()
elif tool == "Section 2(e) Risk Analyzer":
    section_2e_tool.run()
elif tool == "Cloud Report Archive":
    show_drive_archive()