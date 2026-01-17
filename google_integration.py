"""
Google API 整合模組
- Google 相簿：走讀圖鑑照片
- Google 文件：旅遊點滴記錄
"""

import os
import json
import requests
from datetime import datetime
from flask import session, url_for

# Google OAuth 設定
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', '')

# API Scopes
SCOPES = [
    'https://www.googleapis.com/auth/photoslibrary',
    'https://www.googleapis.com/auth/photoslibrary.appendonly',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive.file',
    'openid',
    'email',
    'profile'
]

def get_auth_url():
    """取得 Google OAuth 授權 URL"""
    params = {
        'client_id': GOOGLE_CLIENT_ID,
        'redirect_uri': GOOGLE_REDIRECT_URI,
        'response_type': 'code',
        'scope': ' '.join(SCOPES),
        'access_type': 'offline',
        'prompt': 'consent'
    }
    query = '&'.join([f'{k}={requests.utils.quote(str(v))}' for k, v in params.items()])
    return f'https://accounts.google.com/o/oauth2/v2/auth?{query}'


def exchange_code_for_tokens(code):
    """用授權碼換取 tokens"""
    response = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': GOOGLE_REDIRECT_URI
    })
    return response.json()


def refresh_access_token(refresh_token):
    """刷新 access token"""
    response = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': GOOGLE_CLIENT_ID,
        'client_secret': GOOGLE_CLIENT_SECRET,
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token'
    })
    return response.json()


def get_user_info(access_token):
    """取得使用者資訊"""
    headers = {'Authorization': f'Bearer {access_token}'}
    response = requests.get('https://www.googleapis.com/oauth2/v2/userinfo', headers=headers)
    return response.json()


# ==================== Google 相簿 API ====================

def create_album(access_token, album_title):
    """建立相簿"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    data = {
        'album': {'title': album_title}
    }
    response = requests.post(
        'https://photoslibrary.googleapis.com/v1/albums',
        headers=headers,
        json=data
    )
    return response.json()


def get_or_create_album(access_token, album_title="退休走讀圖鑑"):
    """取得或建立相簿"""
    headers = {'Authorization': f'Bearer {access_token}'}
    
    # 搜尋現有相簿
    response = requests.get(
        'https://photoslibrary.googleapis.com/v1/albums',
        headers=headers,
        params={'pageSize': 50}
    )
    
    if response.status_code == 200:
        albums = response.json().get('albums', [])
        for album in albums:
            if album.get('title') == album_title:
                return album
    
    # 建立新相簿
    return create_album(access_token, album_title)


def upload_photo_to_album(access_token, album_id, image_data, filename, description=""):
    """上傳照片到相簿"""
    # Step 1: 上傳 bytes
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/octet-stream',
        'X-Goog-Upload-Content-Type': 'image/jpeg',
        'X-Goog-Upload-Protocol': 'raw'
    }
    
    upload_response = requests.post(
        'https://photoslibrary.googleapis.com/v1/uploads',
        headers=headers,
        data=image_data
    )
    
    if upload_response.status_code != 200:
        return {'error': 'Upload failed', 'details': upload_response.text}
    
    upload_token = upload_response.text
    
    # Step 2: 建立媒體項目
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    data = {
        'albumId': album_id,
        'newMediaItems': [{
            'description': description,
            'simpleMediaItem': {
                'fileName': filename,
                'uploadToken': upload_token
            }
        }]
    }
    
    response = requests.post(
        'https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate',
        headers=headers,
        json=data
    )
    
    return response.json()


def list_album_photos(access_token, album_id, page_size=25):
    """列出相簿中的照片"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    data = {
        'albumId': album_id,
        'pageSize': page_size
    }
    
    response = requests.post(
        'https://photoslibrary.googleapis.com/v1/mediaItems:search',
        headers=headers,
        json=data
    )
    
    return response.json()


# ==================== Google 文件 API ====================

def create_travel_doc(access_token, title):
    """建立旅遊文件"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    data = {'title': title}
    
    response = requests.post(
        'https://docs.googleapis.com/v1/documents',
        headers=headers,
        json=data
    )
    
    return response.json()


def get_or_create_travel_doc(access_token, title="退休走讀旅遊日誌"):
    """取得或建立旅遊文件（搜尋 Drive）"""
    headers = {'Authorization': f'Bearer {access_token}'}
    
    # 搜尋現有文件
    query = f"name='{title}' and mimeType='application/vnd.google-apps.document' and trashed=false"
    response = requests.get(
        'https://www.googleapis.com/drive/v3/files',
        headers=headers,
        params={'q': query, 'fields': 'files(id,name)'}
    )
    
    if response.status_code == 200:
        files = response.json().get('files', [])
        if files:
            return {'documentId': files[0]['id'], 'title': files[0]['name']}
    
    # 建立新文件
    return create_travel_doc(access_token, title)


def append_to_doc(access_token, doc_id, content):
    """在文件末端加入內容"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    # 先取得文件長度
    doc_response = requests.get(
        f'https://docs.googleapis.com/v1/documents/{doc_id}',
        headers=headers
    )
    
    if doc_response.status_code != 200:
        return {'error': 'Failed to get document'}
    
    doc = doc_response.json()
    end_index = doc.get('body', {}).get('content', [{}])[-1].get('endIndex', 1)
    
    # 建立插入請求
    requests_data = {
        'requests': [{
            'insertText': {
                'location': {'index': end_index - 1},
                'text': content
            }
        }]
    }
    
    response = requests.post(
        f'https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate',
        headers=headers,
        json=requests_data
    )
    
    return response.json()


def add_travel_entry(access_token, doc_id, spot_name, location, date, notes, photo_url=None):
    """加入一筆旅遊記錄到文件"""
    
    # 格式化內容
    entry = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📍 {spot_name}
📅 {date}
📌 {location}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{notes}

"""
    
    if photo_url:
        entry += f"🖼️ 照片連結：{photo_url}\n\n"
    
    entry += "\n"
    
    return append_to_doc(access_token, doc_id, entry)


def create_formatted_travel_entry(access_token, doc_id, spot_name, location, date, notes, photo_url=None):
    """建立格式化的旅遊記錄（含樣式）"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    # 先取得文件長度
    doc_response = requests.get(
        f'https://docs.googleapis.com/v1/documents/{doc_id}',
        headers=headers
    )
    
    if doc_response.status_code != 200:
        return {'error': 'Failed to get document'}
    
    doc = doc_response.json()
    end_index = doc.get('body', {}).get('content', [{}])[-1].get('endIndex', 1)
    insert_index = end_index - 1
    
    # 建立內容
    title_text = f"📍 {spot_name}\n"
    meta_text = f"📅 {date}  |  📌 {location}\n"
    divider = "─" * 40 + "\n"
    notes_text = f"{notes}\n\n"
    
    if photo_url:
        notes_text += f"🖼️ 照片：{photo_url}\n"
    
    notes_text += "\n\n"
    
    full_text = divider + title_text + meta_text + divider + notes_text
    
    requests_data = {
        'requests': [
            # 插入文字
            {
                'insertText': {
                    'location': {'index': insert_index},
                    'text': full_text
                }
            },
            # 標題樣式（粗體、大字）
            {
                'updateTextStyle': {
                    'range': {
                        'startIndex': insert_index + len(divider),
                        'endIndex': insert_index + len(divider) + len(title_text)
                    },
                    'textStyle': {
                        'bold': True,
                        'fontSize': {'magnitude': 16, 'unit': 'PT'}
                    },
                    'fields': 'bold,fontSize'
                }
            },
            # 日期樣式（灰色、小字）
            {
                'updateTextStyle': {
                    'range': {
                        'startIndex': insert_index + len(divider) + len(title_text),
                        'endIndex': insert_index + len(divider) + len(title_text) + len(meta_text)
                    },
                    'textStyle': {
                        'fontSize': {'magnitude': 10, 'unit': 'PT'},
                        'foregroundColor': {
                            'color': {'rgbColor': {'red': 0.5, 'green': 0.5, 'blue': 0.5}}
                        }
                    },
                    'fields': 'fontSize,foregroundColor'
                }
            }
        ]
    }
    
    response = requests.post(
        f'https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate',
        headers=headers,
        json=requests_data
    )
    
    return response.json()


def insert_image_to_doc(access_token, doc_id, image_url):
    """插入圖片到文件（需要公開 URL）"""
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    
    # 取得文件長度
    doc_response = requests.get(
        f'https://docs.googleapis.com/v1/documents/{doc_id}',
        headers=headers
    )
    
    if doc_response.status_code != 200:
        return {'error': 'Failed to get document'}
    
    doc = doc_response.json()
    end_index = doc.get('body', {}).get('content', [{}])[-1].get('endIndex', 1)
    
    requests_data = {
        'requests': [{
            'insertInlineImage': {
                'location': {'index': end_index - 1},
                'uri': image_url,
                'objectSize': {
                    'width': {'magnitude': 400, 'unit': 'PT'},
                    'height': {'magnitude': 300, 'unit': 'PT'}
                }
            }
        }]
    }
    
    response = requests.post(
        f'https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate',
        headers=headers,
        json=requests_data
    )
    
    return response.json()


# ==================== 整合功能 ====================

def save_checkin_with_photo(access_token, spot_name, location, notes, image_data=None, filename=None):
    """
    打卡並儲存到 Google 相簿 + 文件
    
    Returns:
        dict: {
            'success': bool,
            'album': album_info,
            'photo': photo_info (if image provided),
            'doc': doc_info,
            'entry': entry_info
        }
    """
    result = {'success': False}
    date_str = datetime.now().strftime('%Y/%m/%d %H:%M')
    
    try:
        # 1. 取得或建立相簿
        album = get_or_create_album(access_token)
        result['album'] = album
        album_id = album.get('id')
        
        photo_url = None
        
        # 2. 上傳照片（如果有）
        if image_data and filename and album_id:
            description = f"{spot_name} - {date_str}"
            photo_result = upload_photo_to_album(
                access_token, album_id, image_data, filename, description
            )
            result['photo'] = photo_result
            
            # 取得照片 URL
            if 'newMediaItemResults' in photo_result:
                media_item = photo_result['newMediaItemResults'][0].get('mediaItem', {})
                photo_url = media_item.get('productUrl')
        
        # 3. 取得或建立文件
        doc = get_or_create_travel_doc(access_token)
        result['doc'] = doc
        doc_id = doc.get('documentId')
        
        # 4. 加入旅遊記錄
        if doc_id:
            entry_result = create_formatted_travel_entry(
                access_token, doc_id, spot_name, location, date_str, notes, photo_url
            )
            result['entry'] = entry_result
        
        result['success'] = True
        
    except Exception as e:
        result['error'] = str(e)
    
    return result
