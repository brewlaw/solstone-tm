import os
import json
import io
import streamlit as st
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload
from utils.drive_uploader import get_drive_service

FILE_NAME = "saved_searches.json"

def _find_saved_searches_file_id(service, folder_id):
    query = f"'{folder_id}' in parents and name = '{FILE_NAME}' and trashed = false"
    results = service.files().list(
        q=query,
        pageSize=1,
        fields="files(id)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True
    ).execute()
    files = results.get('files', [])
    return files[0]['id'] if files else None

def get_saved_searches():
    """Fetches all saved search profiles from Google Drive or local backup."""
    try:
        service = get_drive_service()
        folder_id = st.secrets["FOLDER_ID"]
        file_id = _find_saved_searches_file_id(service, folder_id)
        if file_id:
            request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
            file_stream = io.BytesIO()
            downloader = MediaIoBaseDownload(file_stream, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            file_stream.seek(0)
            return json.loads(file_stream.read().decode('utf-8'))
    except Exception:
        pass

    if os.path.exists(FILE_NAME):
        try:
            with open(FILE_NAME, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_search_config(search_name, params):
    """Saves or updates a search profile locally and on Google Drive."""
    searches = get_saved_searches()
    searches[search_name] = params

    with open(FILE_NAME, "w", encoding="utf-8") as f:
        json.dump(searches, f, indent=4)

    try:
        service = get_drive_service()
        folder_id = st.secrets["FOLDER_ID"]
        file_id = _find_saved_searches_file_id(service, folder_id)

        json_bytes = json.dumps(searches, indent=4).encode('utf-8')
        media = MediaInMemoryUpload(json_bytes, mimetype='application/json')

        if file_id:
            service.files().update(
                fileId=file_id,
                media_body=media,
                supportsAllDrives=True
            ).execute()
        else:
            file_metadata = {'name': FILE_NAME, 'parents': [folder_id]}
            service.files().create(
                body=file_metadata,
                media_body=media,
                supportsAllDrives=True
            ).execute()
    except Exception as e:
        st.warning(f"Note: Saved locally, but could not sync configuration to Google Drive: {e}")

def delete_saved_search(search_name):
    """Deletes a search profile from local disk and Google Drive."""
    searches = get_saved_searches()
    if search_name in searches:
        del searches[search_name]
        with open(FILE_NAME, "w", encoding="utf-8") as f:
            json.dump(searches, f, indent=4)
        try:
            service = get_drive_service()
            folder_id = st.secrets["FOLDER_ID"]
            file_id = _find_saved_searches_file_id(service, folder_id)
            if file_id:
                json_bytes = json.dumps(searches, indent=4).encode('utf-8')
                media = MediaInMemoryUpload(json_bytes, mimetype='application/json')
                service.files().update(
                    fileId=file_id,
                    media_body=media,
                    supportsAllDrives=True
                ).execute()
        except Exception:
            pass