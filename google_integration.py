"""
Google API 整合模組
- Google 相簿：走讀圖鑑照片
- Google 文件：旅遊點滴記錄（圖文並茂）
- ImgBB：圖片託管（用於 Google 文件插入圖片）
"""

import os
import json
import base64
import requests
from datetime import datetime
from urllib.parse import quote

# Google OAuth 設定
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
GOOGLE_REDIRECT_URI = os.environ.get('GOOGLE_REDIRECT_URI', '')

# ImgBB API Key（用於圖片託管）
IMGBB_API_KEY = os.environ.get('IMGBB_API_KEY', '')

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
    query = '&'.join([f'{k}={quote(str(v))}' for k, v in params.items()])
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


# ==================== ImgBB 圖片託管 ====================

def upload_to_imgbb(image_data, filename=None):
    """
    上傳圖片到 ImgBB
    
    Args:
        image_data: 圖片的二進制資料
        filename: 檔名（選填）
    
    Returns:
        dict: {
            'success': bool,
            'url': 圖片 URL（用於 Google 文件）,
            'display_url': 顯示用 URL,
            'delete_url': 刪除用 URL
        }
    """
    if not IMGBB_API_KEY:
        return {'success': False, 'error': 'ImgBB API Key 未設定'}
    
    try:
        # 轉換為 base64
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        
        # 上傳到 ImgBB
        response = requests.post(
            'https://api.imgbb.com/1/upload',
            data={
                'key': IMGBB_API_KEY,
                'image': image_base64,
                'name': filename or 'travel_photo'
            }
        )
        
        result = response.json()
        
        if result.get('success'):
            data = result.get('data', {})
            return {
                'success': True,
                'url': data.get('url'),  # 直接圖片 URL
                'display_url': data.get('display_url'),
                'thumb_url': data.get('thumb', {}).get('url'),
                'delete_url': data.get('delete_url')
            }
        else:
            return {'success': False, 'error': result.get('error', {}).get('message', '上傳失敗')}
            
    except Exception as e:
        return {'success': False, 'error': str(e)}


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


def create_formatted_travel_entry(access_token, doc_id, spot_name, location, date, notes, photo_url=None, imgbb_url=None):
    """
    建立圖文並茂的旅遊記錄
    
    Args:
        access_token: Google access token
        doc_id: 文件 ID
        spot_name: 景點名稱
        location: 地點
        date: 日期
        notes: 心得
        photo_url: Google 相簿照片連結（僅文字顯示）
        imgbb_url: ImgBB 圖片 URL（用於插入實際圖片）
    """
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
    
    # 建立內容文字
    divider = "═" * 40 + "\n"
    title_text = f"📍 {spot_name}\n"
    meta_text = f"📅 {date}  |  📌 {location}\n\n"
    notes_text = f"💭 {notes}\n\n" if notes else ""
    
    # 組合文字
    full_text = divider + title_text + meta_text + notes_text
    
    # 構建請求
    requests_list = [
        # 1. 插入文字
        {
            'insertText': {
                'location': {'index': insert_index},
                'text': full_text
            }
        },
        # 2. 分隔線樣式（綠色）
        {
            'updateTextStyle': {
                'range': {
                    'startIndex': insert_index,
                    'endIndex': insert_index + len(divider)
                },
                'textStyle': {
                    'foregroundColor': {
                        'color': {'rgbColor': {'red': 0.0, 'green': 0.6, 'blue': 0.4}}
                    }
                },
                'fields': 'foregroundColor'
            }
        },
        # 3. 標題樣式（粗體、大字、深綠色）
        {
            'updateTextStyle': {
                'range': {
                    'startIndex': insert_index + len(divider),
                    'endIndex': insert_index + len(divider) + len(title_text)
                },
                'textStyle': {
                    'bold': True,
                    'fontSize': {'magnitude': 16, 'unit': 'PT'},
                    'foregroundColor': {
                        'color': {'rgbColor': {'red': 0.1, 'green': 0.4, 'blue': 0.2}}
                    }
                },
                'fields': 'bold,fontSize,foregroundColor'
            }
        },
        # 4. 日期地點樣式（灰色、小字）
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
    
    # 先執行文字插入
    response = requests.post(
        f'https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate',
        headers=headers,
        json={'requests': requests_list}
    )
    
    text_result = response.json()
    
    # 如果有 ImgBB 圖片 URL，插入實際圖片
    if imgbb_url:
        # 重新取得文件長度
        doc_response = requests.get(
            f'https://docs.googleapis.com/v1/documents/{doc_id}',
            headers=headers
        )
        doc = doc_response.json()
        new_end_index = doc.get('body', {}).get('content', [{}])[-1].get('endIndex', 1) - 1
        
        # 插入圖片
        image_requests = [
            {
                'insertInlineImage': {
                    'location': {'index': new_end_index},
                    'uri': imgbb_url,
                    'objectSize': {
                        'width': {'magnitude': 350, 'unit': 'PT'},
                        'height': {'magnitude': 262, 'unit': 'PT'}
                    }
                }
            }
        ]
        
        img_response = requests.post(
            f'https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate',
            headers=headers,
            json={'requests': image_requests}
        )
        
        img_result = img_response.json()
        
        # 插入圖片後換行
        doc_response = requests.get(
            f'https://docs.googleapis.com/v1/documents/{doc_id}',
            headers=headers
        )
        doc = doc_response.json()
        final_end_index = doc.get('body', {}).get('content', [{}])[-1].get('endIndex', 1) - 1
        
        requests.post(
            f'https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate',
            headers=headers,
            json={'requests': [{'insertText': {'location': {'index': final_end_index}, 'text': '\n\n'}}]}
        )
        
        return {'text_result': text_result, 'image_result': img_result, 'has_image': True}
    
    return text_result
    
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
    打卡並儲存到 Google 相簿 + 文件（圖文並茂）
    
    流程：
    1. 上傳照片到 Google 相簿
    2. 上傳照片到 ImgBB（取得公開 URL）
    3. 建立/更新 Google 文件，插入圖文並茂的記錄
    
    Returns:
        dict: {
            'success': bool,
            'album': album_info,
            'photo': photo_info,
            'imgbb': imgbb_info,
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
        imgbb_url = None
        
        # 2. 處理照片（如果有）
        if image_data and filename and album_id:
            description = f"{spot_name} - {date_str}"
            
            # 2a. 上傳到 Google 相簿
            photo_result = upload_photo_to_album(
                access_token, album_id, image_data, filename, description
            )
            result['photo'] = photo_result
            
            # 取得 Google 相簿照片 URL
            if 'newMediaItemResults' in photo_result:
                media_item = photo_result['newMediaItemResults'][0].get('mediaItem', {})
                photo_url = media_item.get('productUrl')
            
            # 2b. 上傳到 ImgBB（用於 Google 文件插入圖片）
            imgbb_result = upload_to_imgbb(image_data, filename)
            result['imgbb'] = imgbb_result
            
            if imgbb_result.get('success'):
                imgbb_url = imgbb_result.get('url')
                print(f"✅ ImgBB 上傳成功: {imgbb_url}")
            else:
                print(f"⚠️ ImgBB 上傳失敗: {imgbb_result.get('error')}")
        
        # 3. 取得或建立文件
        doc = get_or_create_travel_doc(access_token)
        result['doc'] = doc
        doc_id = doc.get('documentId')
        
        # 4. 加入圖文並茂的旅遊記錄
        if doc_id:
            entry_result = create_formatted_travel_entry(
                access_token, doc_id, spot_name, location, date_str, notes,
                photo_url=photo_url,
                imgbb_url=imgbb_url  # 傳入 ImgBB URL 用於插入圖片
            )
            result['entry'] = entry_result
        
        result['success'] = True
        
    except Exception as e:
        result['error'] = str(e)
        print(f"❌ save_checkin_with_photo 錯誤: {e}")
    
    return result
