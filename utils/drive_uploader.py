import os
import streamlit as st
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ['https://www.googleapis.com/auth/drive']

def get_drive_service():
    """Authenticates using Streamlit secrets and returns the Google Drive API client."""
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = service_account.Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def upload_to_drive(file_path):
    """Uploads a local file to the shared Google Drive folder and returns its web link."""
    try:
        service = get_drive_service()
        folder_id = st.secrets["FOLDER_ID"]
        file_name = os.path.basename(file_path)

        file_metadata = {
            'name': file_name,
            'parents': [folder_id]
        }
        
        media = MediaFileUpload(file_path, resumable=True)
        uploaded_file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        return uploaded_file.get('webViewLink')
    except Exception as e:
        st.warning(f"Note: Could not archive {os.path.basename(file_path)} to Google Drive: {e}")
        return None

def list_drive_reports():
    """Fetches all uploaded reports from the Google Drive folder for display."""
    try:
        service = get_drive_service()
        folder_id = st.secrets["FOLDER_ID"]
        
        query = f"'{folder_id}' in parents and trashed = false"
        results = service.files().list(
            q=query,
            pageSize=50,
            fields="files(id, name, mimeType, createdTime, webViewLink)",
            orderBy="createdTime desc"
        ).execute()

        return results.get('files', [])
    except Exception as e:
        st.error(f"Error fetching files from Google Drive: {e}")
        return []