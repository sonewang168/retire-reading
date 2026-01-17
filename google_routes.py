"""
Google OAuth 路由
處理授權、回調、API 操作
"""

from flask import Blueprint, request, redirect, session, jsonify, url_for, render_template
import os
import base64
from datetime import datetime
from google_integration import (
    get_auth_url, exchange_code_for_tokens, refresh_access_token,
    get_user_info, get_or_create_album, upload_photo_to_album,
    list_album_photos, get_or_create_travel_doc, create_formatted_travel_entry,
    save_checkin_with_photo
)

google_bp = Blueprint('google', __name__, url_prefix='/google')

# ==================== OAuth 流程 ====================

@google_bp.route('/auth')
def google_auth():
    """開始 Google OAuth 授權"""
    auth_url = get_auth_url()
    return redirect(auth_url)


@google_bp.route('/callback')
def google_callback():
    """Google OAuth 回調"""
    code = request.args.get('code')
    error = request.args.get('error')
    
    if error:
        return render_template('google_result.html', 
                             success=False, 
                             message=f'授權失敗：{error}')
    
    if not code:
        return render_template('google_result.html', 
                             success=False, 
                             message='未收到授權碼')
    
    # 換取 tokens
    tokens = exchange_code_for_tokens(code)
    
    if 'error' in tokens:
        return render_template('google_result.html', 
                             success=False, 
                             message=f'換取 Token 失敗：{tokens.get("error_description", tokens["error"])}')
    
    # 儲存到 session
    session['google_access_token'] = tokens.get('access_token')
    session['google_refresh_token'] = tokens.get('refresh_token')
    session['google_token_expiry'] = tokens.get('expires_in')
    
    # 取得使用者資訊
    user_info = get_user_info(tokens['access_token'])
    session['google_user'] = {
        'email': user_info.get('email'),
        'name': user_info.get('name'),
        'picture': user_info.get('picture')
    }
    
    return render_template('google_result.html', 
                         success=True, 
                         message='Google 帳號連動成功！',
                         user=session['google_user'])


@google_bp.route('/status')
def google_status():
    """檢查 Google 連動狀態"""
    if 'google_access_token' in session:
        return jsonify({
            'connected': True,
            'user': session.get('google_user', {})
        })
    return jsonify({'connected': False})


@google_bp.route('/disconnect')
def google_disconnect():
    """解除 Google 連動"""
    session.pop('google_access_token', None)
    session.pop('google_refresh_token', None)
    session.pop('google_user', None)
    return jsonify({'success': True, 'message': '已解除 Google 連動'})


# ==================== 相簿功能 ====================

@google_bp.route('/album')
def get_album():
    """取得走讀圖鑑相簿"""
    access_token = session.get('google_access_token')
    if not access_token:
        return jsonify({'error': '請先連動 Google 帳號'}), 401
    
    album = get_or_create_album(access_token)
    return jsonify(album)


@google_bp.route('/album/photos')
def get_album_photos():
    """取得相簿中的照片"""
    access_token = session.get('google_access_token')
    if not access_token:
        return jsonify({'error': '請先連動 Google 帳號'}), 401
    
    album = get_or_create_album(access_token)
    album_id = album.get('id')
    
    if not album_id:
        return jsonify({'error': '無法取得相簿'}), 500
    
    photos = list_album_photos(access_token, album_id)
    return jsonify(photos)


@google_bp.route('/upload', methods=['POST'])
def upload_photo():
    """上傳照片到走讀圖鑑相簿"""
    access_token = session.get('google_access_token')
    if not access_token:
        return jsonify({'error': '請先連動 Google 帳號'}), 401
    
    # 取得照片資料
    if 'photo' not in request.files:
        return jsonify({'error': '請選擇照片'}), 400
    
    photo = request.files['photo']
    if photo.filename == '':
        return jsonify({'error': '請選擇照片'}), 400
    
    spot_name = request.form.get('spot_name', '未知景點')
    description = request.form.get('description', '')
    
    # 取得相簿
    album = get_or_create_album(access_token)
    album_id = album.get('id')
    
    if not album_id:
        return jsonify({'error': '無法取得相簿'}), 500
    
    # 上傳照片
    image_data = photo.read()
    filename = f"{spot_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    full_description = f"{spot_name}\n{description}" if description else spot_name
    
    result = upload_photo_to_album(access_token, album_id, image_data, filename, full_description)
    
    return jsonify(result)


# ==================== 文件功能 ====================

@google_bp.route('/doc')
def get_travel_doc():
    """取得旅遊日誌文件"""
    access_token = session.get('google_access_token')
    if not access_token:
        return jsonify({'error': '請先連動 Google 帳號'}), 401
    
    doc = get_or_create_travel_doc(access_token)
    
    # 加入文件連結
    if 'documentId' in doc:
        doc['url'] = f"https://docs.google.com/document/d/{doc['documentId']}/edit"
    
    return jsonify(doc)


@google_bp.route('/doc/entry', methods=['POST'])
def add_doc_entry():
    """新增旅遊記錄到文件"""
    access_token = session.get('google_access_token')
    if not access_token:
        return jsonify({'error': '請先連動 Google 帳號'}), 401
    
    data = request.get_json()
    if not data:
        return jsonify({'error': '請提供記錄內容'}), 400
    
    spot_name = data.get('spot_name', '未知景點')
    location = data.get('location', '')
    notes = data.get('notes', '')
    photo_url = data.get('photo_url')
    
    # 取得文件
    doc = get_or_create_travel_doc(access_token)
    doc_id = doc.get('documentId')
    
    if not doc_id:
        return jsonify({'error': '無法取得文件'}), 500
    
    # 新增記錄
    date_str = datetime.now().strftime('%Y/%m/%d %H:%M')
    result = create_formatted_travel_entry(
        access_token, doc_id, spot_name, location, date_str, notes, photo_url
    )
    
    result['doc_url'] = f"https://docs.google.com/document/d/{doc_id}/edit"
    
    return jsonify(result)


# ==================== 整合打卡功能 ====================

@google_bp.route('/checkin', methods=['POST'])
def checkin_with_google():
    """
    打卡並同步到 Google 相簿 + 文件
    """
    access_token = session.get('google_access_token')
    if not access_token:
        return jsonify({'error': '請先連動 Google 帳號'}), 401
    
    spot_name = request.form.get('spot_name', '未知景點')
    location = request.form.get('location', '')
    notes = request.form.get('notes', '')
    
    # 處理照片
    image_data = None
    filename = None
    
    if 'photo' in request.files:
        photo = request.files['photo']
        if photo.filename:
            image_data = photo.read()
            filename = f"{spot_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
    
    # 同步到 Google
    result = save_checkin_with_photo(
        access_token, spot_name, location, notes, image_data, filename
    )
    
    # 加入文件連結
    if result.get('doc', {}).get('documentId'):
        result['doc_url'] = f"https://docs.google.com/document/d/{result['doc']['documentId']}/edit"
    
    # 加入相簿連結
    if result.get('album', {}).get('productUrl'):
        result['album_url'] = result['album']['productUrl']
    
    return jsonify(result)
