import requests
import streamlit as st

resp = requests.get(
    "https://www.ttbonline.gov/colasonline/publicSearchColasBasic.do",
    headers={"User-Agent": "Mozilla/5.0"},
)
st.write(f"TTB HTTP Status: {resp.status_code}")
st.write(f"Page Sample: {resp.text[:300]}")