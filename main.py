import os
os.system("playwright install chromium")

import streamlit as st
from reports import status_report, clearance_tool, monitoring_tool, section_2e_tool, lop_generator
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
        "Trademark Monitoring Suite",
        "Saved Quarterly Monitoring",
        "Section 2(e) Risk Analyzer",
        "Letter of Protest Generator",
        "Cloud Report Archive"
        "GOODS/SERVICES DESCRIPTION BUILDER"
    ]
)

def show_saved_monitoring():
    st.header("Saved Quarterly Monitoring Profiles")
    st.caption("Manage client monitoring profiles and trigger quarterly sweeps.")

    saved_searches = get_saved_searches()

    if not saved_searches:
        st.info("No saved monitoring profiles found. Create one directly within the Trademark Monitoring Suite.")
        return

    # Compact, professional dashboard styling
    st.markdown(
        """
        <style>
            .monitoring-table-header {
                font-weight: 600;
                font-size: 12px;
                color: #555;
                text-transform: uppercase;
                letter-spacing: 0.5px;
                padding-bottom: 6px;
                border-bottom: 2px solid #e0e0e0;
                margin-bottom: 10px;
            }
            .monitoring-row-title {
                font-weight: 600;
                font-size: 13px;
                color: #1f1f1f;
                padding-top: 4px;
            }
            .monitoring-row-sub {
                font-size: 13px;
                color: #4f4f4f;
                padding-top: 4px;
            }
            .monitoring-badge {
                background-color: #f0f2f6;
                padding: 3px 8px;
                border-radius: 4px;
                font-size: 12px;
                color: #31333f;
                font-weight: 500;
                display: inline-block;
            }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Table Header Row
    h1, h2, h3, h4, h5, h6, h7 = st.columns([3, 2, 2, 1, 1.5, 1.5, 1])
    with h1:
        st.markdown('<div class="monitoring-table-header">Profile Label</div>', unsafe_allow_html=True)
    with h2:
        st.markdown('<div class="monitoring-table-header">Client Name</div>', unsafe_allow_html=True)
    with h3:
        st.markdown('<div class="monitoring-table-header">Trademark</div>', unsafe_allow_html=True)
    with h4:
        st.markdown('<div class="monitoring-table-header">Lookback</div>', unsafe_allow_html=True)
    with h5:
        st.markdown('<div class="monitoring-table-header">Last Ran</div>', unsafe_allow_html=True)
    with h6:
        st.markdown('<div class="monitoring-table-header">Run</div>', unsafe_allow_html=True)
    with h7:
        st.markdown('<div class="monitoring-table-header">Action</div>', unsafe_allow_html=True)

    # Table Body Rows
    for name, params in saved_searches.items():
        col1, col2, col3, col4, col5, col6, col7 = st.columns([3, 2, 2, 1, 1.5, 1.5, 1])
        
        with col1:
            st.markdown(f'<div class="monitoring-row-title">{name}</div>', unsafe_allow_html=True)
        with col2:
            st.markdown(f'<div class="monitoring-row-sub">{params.get("client_name", "N/A")}</div>', unsafe_allow_html=True)
        with col3:
            st.markdown(f'<div class="monitoring-row-sub">{params.get("raw_mark", "N/A")}</div>', unsafe_allow_html=True)
        with col4:
            st.markdown(f'<span class="monitoring-badge">{params.get("lookback_years", "1.0")} yr</span>', unsafe_allow_html=True)
        with col5:
            last_run = params.get('last_run', 'Never')
            st.markdown(f'<div class="monitoring-row-sub">{last_run}</div>', unsafe_allow_html=True)
        with col6:
            if st.button("Run Sweep", key=f"run_{name}", use_container_width=True, type="primary"):
                st.session_state['load_monitoring_key'] = name
                st.session_state['main_tool_router'] = "Trademark Monitoring Suite"
                st.rerun()
        with col7:
            if st.button("Delete", key=f"del_prof_{name}", use_container_width=True):
                delete_saved_search(name)
                st.toast(f"Profile '{name}' deleted!")
                st.rerun()
                
        st.markdown('<hr style="margin: 6px 0 10px 0; border: none; border-bottom: 1px solid #f0f0f0;">', unsafe_allow_html=True)

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
elif tool == "Trademark Monitoring Suite":
    monitoring_tool.run()
elif tool == "Saved Quarterly Monitoring":
    show_saved_monitoring()
elif tool == "Section 2(e) Risk Analyzer":
    section_2e_tool.run()
elif tool == "Letter of Protest Generator":
    lop_generator.run()
elif tool == "Cloud Report Archive":
    show_drive_archive()
