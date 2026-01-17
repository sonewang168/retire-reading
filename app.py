"""
退休走讀 - 旅遊願望清單 × 探險圖鑑 二合一系統
Railway + LINE Bot 版本
"""

import os
import json
from datetime import datetime
from flask import Flask, request, abort, render_template, jsonify, redirect, url_for
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, PushMessageRequest,
    TextMessage, FlexMessage, FlexContainer,
    QuickReply, QuickReplyItem, MessageAction, URIAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent, LocationMessageContent
from linebot.v3.exceptions import InvalidSignatureError
import sqlite3
from contextlib import contextmanager

app = Flask(__name__)

# LINE Bot 設定
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '')

if LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN:
    configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
    handler = WebhookHandler(LINE_CHANNEL_SECRET)
else:
    configuration = None
    handler = None

DATABASE = os.environ.get('DATABASE_PATH', 'retire_reading.db')

@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """初始化資料庫"""
    with get_db() as conn:
        conn.executescript('''
            -- 願望清單
            CREATE TABLE IF NOT EXISTS wishes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                region TEXT,
                description TEXT,
                best_season TEXT,
                budget INTEGER DEFAULT 0,
                priority INTEGER DEFAULT 3,
                completed INTEGER DEFAULT 0,
                completed_date TEXT,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT DEFAULT 'default'
            );
            
            -- 走讀路線
            CREATE TABLE IF NOT EXISTS routes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                region TEXT,
                description TEXT,
                distance_km REAL,
                duration_hours REAL,
                difficulty TEXT DEFAULT '輕鬆',
                accessibility INTEGER DEFAULT 3,
                best_season TEXT,
                highlights TEXT,
                cover_emoji TEXT DEFAULT '🚶',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            
            -- 路線景點（圖鑑收集點）
            CREATE TABLE IF NOT EXISTS spots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                route_id INTEGER,
                name TEXT NOT NULL,
                spot_type TEXT,
                description TEXT,
                has_restroom INTEGER DEFAULT 0,
                has_rest_area INTEGER DEFAULT 0,
                has_parking INTEGER DEFAULT 0,
                wheelchair_accessible INTEGER DEFAULT 0,
                lat REAL,
                lng REAL,
                order_num INTEGER DEFAULT 0,
                icon TEXT DEFAULT '📍',
                rarity TEXT DEFAULT 'common',
                FOREIGN KEY (route_id) REFERENCES routes(id)
            );
            
            -- 打卡紀錄（圖鑑收集）
            CREATE TABLE IF NOT EXISTS checkins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                spot_id INTEGER,
                route_id INTEGER,
                checkin_date TEXT,
                photo_url TEXT,
                note TEXT,
                rating INTEGER DEFAULT 5,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (spot_id) REFERENCES spots(id),
                FOREIGN KEY (route_id) REFERENCES routes(id)
            );
            
            -- 成就徽章
            CREATE TABLE IF NOT EXISTS achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                icon TEXT,
                condition_type TEXT,
                condition_value INTEGER,
                rarity TEXT DEFAULT 'common'
            );
            
            -- 用戶成就
            CREATE TABLE IF NOT EXISTS user_achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                achievement_id INTEGER,
                unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (achievement_id) REFERENCES achievements(id),
                UNIQUE(user_id, achievement_id)
            );
            
            -- 旅遊紀錄
            CREATE TABLE IF NOT EXISTS travel_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wish_id INTEGER,
                route_id INTEGER,
                travel_date TEXT,
                actual_budget INTEGER,
                rating INTEGER DEFAULT 5,
                photos TEXT,
                diary TEXT,
                weather TEXT,
                companions TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                user_id TEXT DEFAULT 'default',
                FOREIGN KEY (wish_id) REFERENCES wishes(id),
                FOREIGN KEY (route_id) REFERENCES routes(id)
            );
            
            -- 用戶設定
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                display_name TEXT,
                total_distance REAL DEFAULT 0,
                total_spots INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        conn.commit()
        
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM routes")
        if cursor.fetchone()[0] == 0:
            insert_sample_data(conn)
        
        cursor.execute("SELECT COUNT(*) FROM achievements")
        if cursor.fetchone()[0] == 0:
            insert_achievements(conn)

def insert_achievements(conn):
    """插入成就資料"""
    achievements = [
        ('first_checkin', '初次打卡', '完成第一次打卡', '🎯', 'checkin_count', 1, 'common'),
        ('explorer_5', '小小探險家', '打卡 5 個景點', '🧭', 'checkin_count', 5, 'common'),
        ('explorer_10', '資深探險家', '打卡 10 個景點', '🗺️', 'checkin_count', 10, 'rare'),
        ('explorer_25', '探險大師', '打卡 25 個景點', '🏆', 'checkin_count', 25, 'epic'),
        ('first_photo', '攝影新手', '上傳第一張照片', '📷', 'photo_count', 1, 'common'),
        ('photographer', '攝影達人', '上傳 10 張照片', '🎞️', 'photo_count', 10, 'rare'),
        ('walker_10km', '健走新手', '累計走過 10 公里', '👟', 'total_distance', 10, 'common'),
        ('walker_50km', '健走達人', '累計走過 50 公里', '🥾', 'total_distance', 50, 'rare'),
        ('walker_100km', '百里行者', '累計走過 100 公里', '🦶', 'total_distance', 100, 'epic'),
        ('route_complete', '路線達人', '完成一條完整路線', '🛤️', 'route_complete', 1, 'rare'),
        ('north_explorer', '北台灣通', '打卡 5 個北部景點', '🌆', 'region_north', 5, 'rare'),
        ('south_explorer', '南台灣通', '打卡 5 個南部景點', '🌴', 'region_south', 5, 'rare'),
        ('wish_complete', '夢想實現', '完成願望清單項目', '⭐', 'wish_complete', 1, 'common'),
        ('wish_master', '圓夢達人', '完成 10 個願望', '🌟', 'wish_complete', 10, 'epic'),
        ('diary_writer', '旅遊作家', '寫下 5 篇旅遊日記', '📝', 'diary_count', 5, 'rare'),
        ('all_seasons', '四季旅人', '在四個季節都有打卡', '🍂', 'all_seasons', 4, 'legendary'),
    ]
    
    for a in achievements:
        conn.execute('''
            INSERT INTO achievements (code, name, description, icon, condition_type, condition_value, rarity)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', a)
    conn.commit()

def insert_sample_data(conn):
    """插入範例走讀路線與景點"""
    routes = [
        ('淡水老街漫步', '北部', '從捷運淡水站出發，沿河岸步道漫步至漁人碼頭，品嚐在地小吃', 3.5, 2.5, '輕鬆', 4, '春秋', '老街美食、夕陽美景、紅毛城', '🌅'),
        ('九份金瓜石懷舊之旅', '北部', '礦業遺址與山城風光的完美結合，重溫黃金歲月', 4.0, 4.0, '中等', 3, '秋冬', '黃金博物館、祈堂老街、茶樓', '🏮'),
        ('台南府城古蹟巡禮', '南部', '走訪台灣歷史最悠久的城市核心，感受百年風華', 5.0, 5.0, '輕鬆', 5, '春秋冬', '赤崁樓、孔廟、神農街', '🏛️'),
        ('日月潭環湖步道', '中部', '台灣最美高山湖泊的悠閒散步，湖光山色盡收眼底', 3.0, 2.0, '輕鬆', 4, '四季皆宜', '向山遊客中心、水社碼頭', '🌊'),
        ('花蓮七星潭海岸', '東部', '太平洋海岸線的壯闘風光，聆聽浪濤拍岸', 2.5, 1.5, '輕鬆', 4, '春夏秋', '礫石海灘、觀星、四八高地', '🏖️'),
        ('阿里山森林步道', '中部', '神木群與雲海的夢幻組合，森林芬多精洗禮', 6.0, 4.0, '中等', 3, '春秋', '神木車站、姊妹潭、日出', '🌲'),
        ('鹿港小鎮散策', '中部', '傳統工藝與古蹟的深度體驗，巷弄間的時光旅行', 3.0, 3.0, '輕鬆', 4, '春秋冬', '天后宮、摸乳巷、老街', '🎭'),
        ('墾丁國家公園', '南部', '台灣最南端的熱帶風情，陽光沙灘椰影', 8.0, 6.0, '中等', 3, '秋冬春', '鵝鑾鼻、龍磐草原、後壁湖', '🌺'),
        ('宜蘭礁溪溫泉散步', '北部', '溫泉小鎮的愜意時光，泡湯賞景兩相宜', 2.0, 2.0, '輕鬆', 5, '秋冬', '湯圍溝、跑馬古道、溫泉魚', '♨️'),
        ('台東池上伯朗大道', '東部', '無邊際稻田的療癒風景，騎車漫遊田園', 5.0, 3.0, '輕鬆', 4, '夏秋', '金城武樹、天堂路、稻米原鄉館', '🌾'),
    ]
    
    for route in routes:
        conn.execute('''
            INSERT INTO routes (name, region, description, distance_km, duration_hours, 
                              difficulty, accessibility, best_season, highlights, cover_emoji)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', route)
    
    # 淡水景點
    spots_tamsui = [
        (1, '淡水捷運站', '起點', '交通便利的起點，週邊有便利商店', 1, 1, 1, 1, 25.1677, 121.4453, 1, '🚇', 'common'),
        (1, '淡水老街', '商圈', '各式小吃與紀念品，阿給、魚酥必吃', 1, 1, 0, 1, 25.1697, 121.4397, 2, '🛍️', 'common'),
        (1, '紅毛城', '古蹟', '荷蘭時期建築，眺望淡水河口', 1, 1, 1, 1, 25.1753, 121.4328, 3, '🏰', 'rare'),
        (1, '真理大學', '景點', '馬偕故居與牛津學堂', 0, 1, 0, 1, 25.1761, 121.4311, 4, '🎓', 'common'),
        (1, '漁人碼頭', '景點', '看夕陽的最佳地點，情人橋', 1, 1, 1, 1, 25.1833, 121.4167, 5, '🌉', 'rare'),
    ]
    
    # 台南景點
    spots_tainan = [
        (3, '赤崁樓', '古蹟', '荷蘭時期普羅民遮城遺址', 1, 1, 1, 1, 22.9971, 120.2023, 1, '🏛️', 'rare'),
        (3, '祀典武廟', '廟宇', '台灣最早的關帝廟', 0, 1, 0, 1, 22.9969, 120.2031, 2, '⛩️', 'common'),
        (3, '大天后宮', '廟宇', '台灣第一座官建媽祖廟', 0, 1, 0, 1, 22.9964, 120.2036, 3, '🙏', 'common'),
        (3, '孔廟', '古蹟', '全台首學，紅牆綠蔭', 1, 1, 1, 1, 22.9903, 120.2044, 4, '📚', 'rare'),
        (3, '神農街', '老街', '保存完整的清代街屋', 0, 1, 0, 0, 22.9978, 120.1967, 5, '🏮', 'rare'),
        (3, '國華街', '美食', '小吃聚集地，富盛號、邱家', 1, 0, 0, 1, 22.9942, 120.1986, 6, '🍜', 'common'),
    ]
    
    # 日月潭景點
    spots_sunmoon = [
        (4, '向山遊客中心', '景點', '清水模建築，眺望湖景', 1, 1, 1, 1, 23.8472, 120.9011, 1, '🏢', 'rare'),
        (4, '水社碼頭', '碼頭', '搭船遊湖的起點', 1, 1, 1, 1, 23.8658, 120.9108, 2, '⛴️', 'common'),
        (4, '文武廟', '廟宇', '氣勢磅礡的湖畔廟宇', 1, 1, 1, 0, 23.8711, 120.9317, 3, '🏯', 'rare'),
        (4, '伊達邵', '部落', '邵族文化與美食', 1, 1, 0, 1, 23.8528, 120.9356, 4, '🎪', 'common'),
    ]
    
    for spot in spots_tamsui + spots_tainan + spots_sunmoon:
        conn.execute('''
            INSERT INTO spots (route_id, name, spot_type, description, 
                             has_restroom, has_rest_area, has_parking, wheelchair_accessible,
                             lat, lng, order_num, icon, rarity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', spot)
    
    conn.commit()

# ============ 成就檢查 ============

def check_achievements(user_id):
    """檢查並解鎖成就"""
    unlocked = []
    
    with get_db() as conn:
        # 取得用戶統計
        stats = get_user_stats(user_id)
        
        # 取得所有成就
        achievements = conn.execute("SELECT * FROM achievements").fetchall()
        
        # 已解鎖的成就
        unlocked_ids = [r['achievement_id'] for r in conn.execute(
            "SELECT achievement_id FROM user_achievements WHERE user_id = ?", (user_id,)
        ).fetchall()]
        
        for ach in achievements:
            if ach['id'] in unlocked_ids:
                continue
            
            # 檢查條件
            should_unlock = False
            ct = ach['condition_type']
            cv = ach['condition_value']
            
            if ct == 'checkin_count' and stats['checkin_count'] >= cv:
                should_unlock = True
            elif ct == 'photo_count' and stats['photo_count'] >= cv:
                should_unlock = True
            elif ct == 'total_distance' and stats['total_distance'] >= cv:
                should_unlock = True
            elif ct == 'wish_complete' and stats['wish_complete'] >= cv:
                should_unlock = True
            elif ct == 'diary_count' and stats['diary_count'] >= cv:
                should_unlock = True
            
            if should_unlock:
                conn.execute('''
                    INSERT OR IGNORE INTO user_achievements (user_id, achievement_id)
                    VALUES (?, ?)
                ''', (user_id, ach['id']))
                unlocked.append(ach)
        
        conn.commit()
    
    return unlocked

def get_user_stats(user_id):
    """取得用戶統計"""
    with get_db() as conn:
        checkin_count = conn.execute(
            "SELECT COUNT(*) FROM checkins WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        
        photo_count = conn.execute(
            "SELECT COUNT(*) FROM checkins WHERE user_id = ? AND photo_url IS NOT NULL", (user_id,)
        ).fetchone()[0]
        
        wish_complete = conn.execute(
            "SELECT COUNT(*) FROM wishes WHERE user_id = ? AND completed = 1", (user_id,)
        ).fetchone()[0]
        
        diary_count = conn.execute(
            "SELECT COUNT(*) FROM travel_logs WHERE user_id = ? AND diary IS NOT NULL AND diary != ''", (user_id,)
        ).fetchone()[0]
        
        # 取得總距離
        settings = conn.execute(
            "SELECT total_distance FROM user_settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        total_distance = settings['total_distance'] if settings else 0
        
        # 取得成就數
        achievement_count = conn.execute(
            "SELECT COUNT(*) FROM user_achievements WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
    
    return {
        'checkin_count': checkin_count,
        'photo_count': photo_count,
        'wish_complete': wish_complete,
        'diary_count': diary_count,
        'total_distance': total_distance,
        'achievement_count': achievement_count
    }

# ============ 網頁路由 ============

@app.route('/')
def index():
    user_id = request.args.get('user', 'default')
    
    with get_db() as conn:
        wishes_total = conn.execute("SELECT COUNT(*) FROM wishes WHERE user_id = ?", (user_id,)).fetchone()[0]
        wishes_done = conn.execute("SELECT COUNT(*) FROM wishes WHERE user_id = ? AND completed = 1", (user_id,)).fetchone()[0]
        routes_total = conn.execute("SELECT COUNT(*) FROM routes").fetchone()[0]
        spots_total = conn.execute("SELECT COUNT(*) FROM spots").fetchone()[0]
        
        checkin_count = conn.execute("SELECT COUNT(*) FROM checkins WHERE user_id = ?", (user_id,)).fetchone()[0]
        achievement_count = conn.execute("SELECT COUNT(*) FROM user_achievements WHERE user_id = ?", (user_id,)).fetchone()[0]
        
        # 本季推薦
        month = datetime.now().month
        season = '春' if month in [3,4,5] else '夏' if month in [6,7,8] else '秋' if month in [9,10,11] else '冬'
        
        seasonal_routes = conn.execute('''
            SELECT * FROM routes 
            WHERE best_season LIKE ? OR best_season LIKE '%四季%'
            ORDER BY accessibility DESC LIMIT 6
        ''', (f'%{season}%',)).fetchall()
        
        recent_checkins = conn.execute('''
            SELECT c.*, s.name as spot_name, s.icon, r.name as route_name
            FROM checkins c
            JOIN spots s ON c.spot_id = s.id
            JOIN routes r ON c.route_id = r.id
            WHERE c.user_id = ?
            ORDER BY c.created_at DESC LIMIT 5
        ''', (user_id,)).fetchall()
        
    return render_template('index.html',
                          wishes_total=wishes_total,
                          wishes_done=wishes_done,
                          routes_total=routes_total,
                          spots_total=spots_total,
                          checkin_count=checkin_count,
                          achievement_count=achievement_count,
                          seasonal_routes=seasonal_routes,
                          recent_checkins=recent_checkins,
                          current_season=season,
                          user_id=user_id)

@app.route('/atlas')
def atlas():
    """探險圖鑑頁面"""
    user_id = request.args.get('user', 'default')
    
    with get_db() as conn:
        # 所有景點與收集狀態
        spots = conn.execute('''
            SELECT s.*, r.name as route_name, r.region,
                   CASE WHEN c.id IS NOT NULL THEN 1 ELSE 0 END as collected,
                   c.checkin_date, c.photo_url
            FROM spots s
            JOIN routes r ON s.route_id = r.id
            LEFT JOIN checkins c ON s.id = c.spot_id AND c.user_id = ?
            ORDER BY r.region, r.name, s.order_num
        ''', (user_id,)).fetchall()
        
        # 統計
        total = len(spots)
        collected = sum(1 for s in spots if s['collected'])
        
        # 依路線分組
        routes_map = {}
        for s in spots:
            route_name = s['route_name']
            if route_name not in routes_map:
                routes_map[route_name] = {'region': s['region'], 'spots': [], 'collected': 0}
            routes_map[route_name]['spots'].append(s)
            if s['collected']:
                routes_map[route_name]['collected'] += 1
        
    return render_template('atlas.html',
                          routes_map=routes_map,
                          total=total,
                          collected=collected,
                          user_id=user_id)

@app.route('/achievements')
def achievements_page():
    """成就頁面"""
    user_id = request.args.get('user', 'default')
    
    with get_db() as conn:
        achievements = conn.execute('''
            SELECT a.*, 
                   CASE WHEN ua.id IS NOT NULL THEN 1 ELSE 0 END as unlocked,
                   ua.unlocked_at
            FROM achievements a
            LEFT JOIN user_achievements ua ON a.id = ua.achievement_id AND ua.user_id = ?
            ORDER BY a.rarity DESC, a.condition_value
        ''', (user_id,)).fetchall()
        
        total = len(achievements)
        unlocked = sum(1 for a in achievements if a['unlocked'])
        
    return render_template('achievements.html',
                          achievements=achievements,
                          total=total,
                          unlocked=unlocked,
                          user_id=user_id)

@app.route('/wishes')
def wishes_list():
    user_id = request.args.get('user', 'default')
    filter_status = request.args.get('status', 'all')
    filter_region = request.args.get('region', 'all')
    
    with get_db() as conn:
        query = "SELECT * FROM wishes WHERE user_id = ?"
        params = [user_id]
        
        if filter_status == 'pending':
            query += " AND completed = 0"
        elif filter_status == 'done':
            query += " AND completed = 1"
            
        if filter_region != 'all':
            query += " AND region = ?"
            params.append(filter_region)
            
        query += " ORDER BY priority ASC, created_at DESC"
        
        wishes = conn.execute(query, params).fetchall()
        regions = conn.execute("SELECT DISTINCT region FROM wishes WHERE region IS NOT NULL AND user_id = ?", (user_id,)).fetchall()
        
    return render_template('wishes.html', wishes=wishes, regions=regions,
                          filter_status=filter_status, filter_region=filter_region, user_id=user_id)

@app.route('/wishes/add', methods=['GET', 'POST'])
def add_wish():
    user_id = request.args.get('user', 'default')
    
    if request.method == 'POST':
        with get_db() as conn:
            conn.execute('''
                INSERT INTO wishes (name, region, description, best_season, budget, priority, notes, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                request.form['name'],
                request.form['region'],
                request.form['description'],
                request.form['best_season'],
                int(request.form.get('budget', 0) or 0),
                int(request.form.get('priority', 3)),
                request.form.get('notes', ''),
                user_id
            ))
            conn.commit()
        return redirect(url_for('wishes_list', user=user_id))
    return render_template('wish_form.html', wish=None, user_id=user_id)

@app.route('/wishes/<int:wish_id>/edit', methods=['GET', 'POST'])
def edit_wish(wish_id):
    user_id = request.args.get('user', 'default')
    
    with get_db() as conn:
        if request.method == 'POST':
            conn.execute('''
                UPDATE wishes SET name=?, region=?, description=?, best_season=?, 
                                 budget=?, priority=?, notes=?
                WHERE id=? AND user_id=?
            ''', (
                request.form['name'],
                request.form['region'],
                request.form['description'],
                request.form['best_season'],
                int(request.form.get('budget', 0) or 0),
                int(request.form.get('priority', 3)),
                request.form.get('notes', ''),
                wish_id,
                user_id
            ))
            conn.commit()
            return redirect(url_for('wishes_list', user=user_id))
        
        wish = conn.execute("SELECT * FROM wishes WHERE id=? AND user_id=?", (wish_id, user_id)).fetchone()
    return render_template('wish_form.html', wish=wish, user_id=user_id)

@app.route('/wishes/<int:wish_id>/complete', methods=['POST'])
def complete_wish(wish_id):
    user_id = request.json.get('user_id', 'default')
    
    with get_db() as conn:
        conn.execute('''
            UPDATE wishes SET completed = 1, completed_date = ? WHERE id = ? AND user_id = ?
        ''', (datetime.now().strftime('%Y-%m-%d'), wish_id, user_id))
        conn.commit()
    
    # 檢查成就
    unlocked = check_achievements(user_id)
    
    return jsonify({'success': True, 'unlocked': [{'name': a['name'], 'icon': a['icon']} for a in unlocked]})

@app.route('/wishes/<int:wish_id>/delete', methods=['POST'])
def delete_wish(wish_id):
    user_id = request.json.get('user_id', 'default')
    
    with get_db() as conn:
        conn.execute("DELETE FROM wishes WHERE id=? AND user_id=?", (wish_id, user_id))
        conn.commit()
    return jsonify({'success': True})

@app.route('/routes')
def routes_list():
    filter_region = request.args.get('region', 'all')
    filter_difficulty = request.args.get('difficulty', 'all')
    user_id = request.args.get('user', 'default')
    
    with get_db() as conn:
        query = "SELECT * FROM routes WHERE 1=1"
        params = []
        
        if filter_region != 'all':
            query += " AND region = ?"
            params.append(filter_region)
            
        if filter_difficulty != 'all':
            query += " AND difficulty = ?"
            params.append(filter_difficulty)
            
        query += " ORDER BY accessibility DESC, name"
        
        routes = conn.execute(query, params).fetchall()
        regions = conn.execute("SELECT DISTINCT region FROM routes").fetchall()
        
        # 加入收集進度
        routes_with_progress = []
        for r in routes:
            total = conn.execute("SELECT COUNT(*) FROM spots WHERE route_id=?", (r['id'],)).fetchone()[0]
            collected = conn.execute('''
                SELECT COUNT(*) FROM checkins c
                JOIN spots s ON c.spot_id = s.id
                WHERE s.route_id = ? AND c.user_id = ?
            ''', (r['id'], user_id)).fetchone()[0]
            routes_with_progress.append({**dict(r), 'total_spots': total, 'collected_spots': collected})
        
    return render_template('routes.html', routes=routes_with_progress, regions=regions,
                          filter_region=filter_region, filter_difficulty=filter_difficulty, user_id=user_id)

@app.route('/routes/<int:route_id>')
def route_detail(route_id):
    user_id = request.args.get('user', 'default')
    
    with get_db() as conn:
        route = conn.execute("SELECT * FROM routes WHERE id=?", (route_id,)).fetchone()
        spots = conn.execute('''
            SELECT s.*, 
                   CASE WHEN c.id IS NOT NULL THEN 1 ELSE 0 END as collected,
                   c.checkin_date, c.photo_url, c.note as checkin_note
            FROM spots s
            LEFT JOIN checkins c ON s.id = c.spot_id AND c.user_id = ?
            WHERE s.route_id = ?
            ORDER BY s.order_num
        ''', (user_id, route_id)).fetchall()
        
        total = len(spots)
        collected = sum(1 for s in spots if s['collected'])
        
    return render_template('route_detail.html', route=route, spots=spots,
                          total=total, collected=collected, user_id=user_id)

@app.route('/spot/<int:spot_id>/checkin', methods=['POST'])
def checkin_spot(spot_id):
    """打卡景點"""
    user_id = request.json.get('user_id', 'default')
    note = request.json.get('note', '')
    
    with get_db() as conn:
        # 檢查是否已打卡
        existing = conn.execute(
            "SELECT id FROM checkins WHERE user_id = ? AND spot_id = ?",
            (user_id, spot_id)
        ).fetchone()
        
        if existing:
            return jsonify({'success': False, 'message': '已經打卡過了'})
        
        # 取得景點資訊
        spot = conn.execute("SELECT * FROM spots WHERE id = ?", (spot_id,)).fetchone()
        
        # 新增打卡
        conn.execute('''
            INSERT INTO checkins (user_id, spot_id, route_id, checkin_date, note)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, spot_id, spot['route_id'], datetime.now().strftime('%Y-%m-%d'), note))
        
        conn.commit()
    
    # 檢查成就
    unlocked = check_achievements(user_id)
    
    return jsonify({
        'success': True,
        'message': f"成功打卡「{spot['name']}」！",
        'unlocked': [{'name': a['name'], 'icon': a['icon']} for a in unlocked]
    })

@app.route('/logs')
def travel_logs():
    user_id = request.args.get('user', 'default')
    
    with get_db() as conn:
        logs = conn.execute('''
            SELECT l.*, w.name as wish_name, r.name as route_name
            FROM travel_logs l
            LEFT JOIN wishes w ON l.wish_id = w.id
            LEFT JOIN routes r ON l.route_id = r.id
            WHERE l.user_id = ?
            ORDER BY l.travel_date DESC
        ''', (user_id,)).fetchall()
    return render_template('logs.html', logs=logs, user_id=user_id)

@app.route('/logs/add', methods=['GET', 'POST'])
def add_log():
    user_id = request.args.get('user', 'default')
    
    with get_db() as conn:
        if request.method == 'POST':
            conn.execute('''
                INSERT INTO travel_logs (wish_id, route_id, travel_date, actual_budget, rating, diary, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                request.form.get('wish_id') or None,
                request.form.get('route_id') or None,
                request.form['travel_date'],
                int(request.form.get('actual_budget', 0) or 0),
                int(request.form.get('rating', 5)),
                request.form.get('diary', ''),
                user_id
            ))
            conn.commit()
            
            # 檢查成就
            check_achievements(user_id)
            
            return redirect(url_for('travel_logs', user=user_id))
        
        wishes = conn.execute("SELECT id, name FROM wishes WHERE user_id = ? ORDER BY name", (user_id,)).fetchall()
        routes = conn.execute("SELECT id, name FROM routes ORDER BY name").fetchall()
    return render_template('log_form.html', wishes=wishes, routes=routes, user_id=user_id)

# ============ API ============

@app.route('/api/stats/<user_id>')
def api_user_stats(user_id):
    stats = get_user_stats(user_id)
    return jsonify(stats)

@app.route('/api/achievements/<user_id>')
def api_user_achievements(user_id):
    with get_db() as conn:
        achievements = conn.execute('''
            SELECT a.*, ua.unlocked_at
            FROM achievements a
            JOIN user_achievements ua ON a.id = ua.achievement_id
            WHERE ua.user_id = ?
            ORDER BY ua.unlocked_at DESC
        ''', (user_id,)).fetchall()
    return jsonify([dict(a) for a in achievements])

# ============ LINE Bot ============

@app.route('/callback', methods=['POST'])
def callback():
    if not handler:
        return 'LINE Bot not configured', 400
        
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

if handler:
    @handler.add(MessageEvent, message=TextMessageContent)
    def handle_message(event):
        text = event.message.text.strip()
        user_id = event.source.user_id
        
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            
            if text in ['選單', '功能', 'menu', '?', '？']:
                reply = create_menu_flex()
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text='功能選單', contents=FlexContainer.from_dict(reply))]
                    )
                )
            elif text in ['願望', '清單', '想去']:
                reply = get_wishes_flex(user_id)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text='願望清單', contents=FlexContainer.from_dict(reply))]
                    )
                )
            elif text in ['路線', '走讀', '推薦']:
                reply = get_routes_flex()
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text='推薦路線', contents=FlexContainer.from_dict(reply))]
                    )
                )
            elif text in ['圖鑑', '收集', '打卡']:
                reply = get_atlas_flex(user_id)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text='探險圖鑑', contents=FlexContainer.from_dict(reply))]
                    )
                )
            elif text in ['成就', '徽章', '獎章']:
                reply = get_achievements_flex(user_id)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text='成就徽章', contents=FlexContainer.from_dict(reply))]
                    )
                )
            elif text in ['統計', '進度', '紀錄']:
                reply = get_stats_message(user_id)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply)]
                    )
                )
            elif text.startswith('新增 ') or text.startswith('加入 '):
                place_name = text.split(' ', 1)[1] if ' ' in text else ''
                if place_name:
                    add_wish_from_line(place_name, user_id)
                    reply = f'✨ 已將「{place_name}」加入願望清單！'
                else:
                    reply = '請輸入地點名稱，例如：新增 阿里山'
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply)]
                    )
                )
            elif text.startswith('完成 '):
                place_name = text.split(' ', 1)[1] if ' ' in text else ''
                result = mark_wish_complete_line(place_name, user_id)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=result)]
                    )
                )
            elif text in ['北部', '中部', '南部', '東部']:
                reply = get_region_routes_flex(text)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[FlexMessage(alt_text=f'{text}路線', contents=FlexContainer.from_dict(reply))]
                    )
                )
            else:
                reply = search_content(text, user_id)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply)]
                    )
                )

def create_menu_flex():
    return {
        "type": "bubble",
        "hero": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📖", "size": "4xl", "align": "center"},
                {"type": "text", "text": "退休走讀", "weight": "bold", "size": "xl", "color": "#1a5f2a", "align": "center", "margin": "md"}
            ],
            "paddingAll": "20px",
            "backgroundColor": "#f0f7f2"
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "📋 輸入「願望」查看清單", "margin": "md", "size": "sm"},
                {"type": "text", "text": "🚶 輸入「路線」看推薦", "margin": "sm", "size": "sm"},
                {"type": "text", "text": "🗺️ 輸入「圖鑑」看收集進度", "margin": "sm", "size": "sm"},
                {"type": "text", "text": "🏆 輸入「成就」看徽章", "margin": "sm", "size": "sm"},
                {"type": "text", "text": "📊 輸入「統計」看總覽", "margin": "sm", "size": "sm"},
                {"type": "separator", "margin": "lg"},
                {"type": "text", "text": "➕「新增 地點」加入願望", "margin": "md", "size": "sm"},
                {"type": "text", "text": "✅「完成 地點」標記完成", "margin": "sm", "size": "sm"},
                {"type": "text", "text": "🧭「北部/中部/南部/東部」", "margin": "sm", "size": "sm"}
            ]
        }
    }

def get_wishes_flex(user_id):
    with get_db() as conn:
        wishes = conn.execute(
            "SELECT * FROM wishes WHERE completed = 0 AND user_id = ? ORDER BY priority LIMIT 8",
            (user_id,)
        ).fetchall()
    
    if not wishes:
        return {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "📋 願望清單是空的", "weight": "bold"},
            {"type": "text", "text": "輸入「新增 地點」來加入", "color": "#888888", "margin": "md", "size": "sm"}
        ]}}
    
    contents = []
    for w in wishes:
        emoji = ['🔴', '🟠', '🟡', '🟢', '⚪'][min(w['priority']-1, 4)]
        contents.append({
            "type": "box", "layout": "horizontal", "margin": "md",
            "contents": [
                {"type": "text", "text": emoji, "flex": 0},
                {"type": "text", "text": w['name'], "flex": 3, "margin": "sm"},
                {"type": "text", "text": w['best_season'] or '', "flex": 1, "size": "xs", "color": "#888888"}
            ]
        })
    
    return {"type": "bubble",
            "header": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "📋 我的願望清單", "weight": "bold"}]},
            "body": {"type": "box", "layout": "vertical", "contents": contents}}

def get_routes_flex():
    month = datetime.now().month
    season = '春' if month in [3,4,5] else '夏' if month in [6,7,8] else '秋' if month in [9,10,11] else '冬'
    
    with get_db() as conn:
        routes = conn.execute('''
            SELECT * FROM routes 
            WHERE best_season LIKE ? OR best_season LIKE '%四季%'
            ORDER BY accessibility DESC LIMIT 5
        ''', (f'%{season}%',)).fetchall()
    
    contents = []
    for r in routes:
        contents.append({
            "type": "box", "layout": "vertical", "margin": "lg", "paddingAll": "sm",
            "backgroundColor": "#f8f8f8", "cornerRadius": "md",
            "contents": [
                {"type": "text", "text": f"{r['cover_emoji']} {r['name']}", "weight": "bold"},
                {"type": "text", "text": f"{r['region']} | {r['distance_km']}km | {r['difficulty']}", "size": "xs", "color": "#888888"},
                {"type": "text", "text": f"♿{'♿'*r['accessibility']}", "size": "xs", "color": "#1a5f2a"}
            ]
        })
    
    return {"type": "bubble",
            "header": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": f"🚶 {season}季推薦路線", "weight": "bold"}]},
            "body": {"type": "box", "layout": "vertical", "contents": contents}}

def get_atlas_flex(user_id):
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM spots").fetchone()[0]
        collected = conn.execute("SELECT COUNT(*) FROM checkins WHERE user_id = ?", (user_id,)).fetchone()[0]
        
        recent = conn.execute('''
            SELECT s.name, s.icon FROM checkins c
            JOIN spots s ON c.spot_id = s.id
            WHERE c.user_id = ?
            ORDER BY c.created_at DESC LIMIT 5
        ''', (user_id,)).fetchall()
    
    progress = (collected / total * 100) if total > 0 else 0
    bar = '█' * int(progress / 10) + '░' * (10 - int(progress / 10))
    
    contents = [
        {"type": "text", "text": f"收集進度: {collected}/{total}", "weight": "bold"},
        {"type": "text", "text": f"[{bar}] {progress:.0f}%", "size": "sm", "margin": "sm"}
    ]
    
    if recent:
        contents.append({"type": "separator", "margin": "lg"})
        contents.append({"type": "text", "text": "最近收集:", "size": "sm", "margin": "md", "color": "#888888"})
        for r in recent:
            contents.append({"type": "text", "text": f"{r['icon']} {r['name']}", "size": "sm", "margin": "sm"})
    
    return {"type": "bubble",
            "header": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "🗺️ 探險圖鑑", "weight": "bold"}]},
            "body": {"type": "box", "layout": "vertical", "contents": contents}}

def get_achievements_flex(user_id):
    with get_db() as conn:
        unlocked = conn.execute('''
            SELECT a.* FROM achievements a
            JOIN user_achievements ua ON a.id = ua.achievement_id
            WHERE ua.user_id = ?
            ORDER BY ua.unlocked_at DESC LIMIT 6
        ''', (user_id,)).fetchall()
        
        total = conn.execute("SELECT COUNT(*) FROM achievements").fetchone()[0]
        unlocked_count = len(unlocked)
    
    if not unlocked:
        return {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "🏆 還沒有成就", "weight": "bold"},
            {"type": "text", "text": "開始打卡收集來解鎖！", "color": "#888888", "margin": "md", "size": "sm"}
        ]}}
    
    contents = [{"type": "text", "text": f"已解鎖: {unlocked_count}/{total}", "size": "sm", "color": "#888888"}]
    
    for a in unlocked:
        contents.append({
            "type": "box", "layout": "horizontal", "margin": "md",
            "contents": [
                {"type": "text", "text": a['icon'], "flex": 0},
                {"type": "text", "text": a['name'], "margin": "sm"}
            ]
        })
    
    return {"type": "bubble",
            "header": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": "🏆 我的成就", "weight": "bold"}]},
            "body": {"type": "box", "layout": "vertical", "contents": contents}}

def get_stats_message(user_id):
    stats = get_user_stats(user_id)
    
    with get_db() as conn:
        total_spots = conn.execute("SELECT COUNT(*) FROM spots").fetchone()[0]
        total_achievements = conn.execute("SELECT COUNT(*) FROM achievements").fetchone()[0]
    
    progress = (stats['checkin_count'] / total_spots * 100) if total_spots > 0 else 0
    bar = '█' * int(progress / 10) + '░' * (10 - int(progress / 10))
    
    return f"""📊 我的退休走讀統計

🗺️ 圖鑑收集: {stats['checkin_count']}/{total_spots}
[{bar}] {progress:.0f}%

🏆 成就徽章: {stats['achievement_count']}/{total_achievements}
⭐ 願望完成: {stats['wish_complete']} 個
📝 旅遊日記: {stats['diary_count']} 篇
📷 收藏照片: {stats['photo_count']} 張

{'🎉 持續探索，收集更多回憶！' if stats['checkin_count'] > 0 else '🚀 開始你的第一次打卡吧！'}"""

def get_region_routes_flex(region):
    with get_db() as conn:
        routes = conn.execute("SELECT * FROM routes WHERE region = ? ORDER BY accessibility DESC", (region,)).fetchall()
    
    if not routes:
        return {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": f"尚無{region}路線資料"}
        ]}}
    
    contents = []
    for r in routes:
        contents.append({
            "type": "box", "layout": "vertical", "margin": "lg",
            "contents": [
                {"type": "text", "text": f"{r['cover_emoji']} {r['name']}", "weight": "bold"},
                {"type": "text", "text": f"{r['distance_km']}km | {r['duration_hours']}h | {r['difficulty']}", "size": "xs", "color": "#888888"},
                {"type": "text", "text": r['highlights'] or '', "size": "xs", "color": "#666666", "wrap": True}
            ]
        })
    
    return {"type": "bubble",
            "header": {"type": "box", "layout": "vertical", "contents": [{"type": "text", "text": f"🗺️ {region}走讀路線", "weight": "bold"}]},
            "body": {"type": "box", "layout": "vertical", "contents": contents}}

def add_wish_from_line(place_name, user_id):
    with get_db() as conn:
        conn.execute("INSERT INTO wishes (name, user_id) VALUES (?, ?)", (place_name, user_id))
        conn.commit()

def mark_wish_complete_line(place_name, user_id):
    with get_db() as conn:
        cursor = conn.execute('''
            UPDATE wishes SET completed = 1, completed_date = ?
            WHERE name LIKE ? AND completed = 0 AND user_id = ?
        ''', (datetime.now().strftime('%Y-%m-%d'), f'%{place_name}%', user_id))
        conn.commit()
        
        if cursor.rowcount > 0:
            unlocked = check_achievements(user_id)
            msg = f'🎉 恭喜完成「{place_name}」！'
            if unlocked:
                msg += f"\n🏆 解鎖成就: {', '.join([a['icon'] + a['name'] for a in unlocked])}"
            return msg
        else:
            return f'❌ 找不到「{place_name}」在願望清單中'

def search_content(keyword, user_id):
    with get_db() as conn:
        routes = conn.execute('''
            SELECT * FROM routes 
            WHERE name LIKE ? OR region LIKE ? OR highlights LIKE ?
            LIMIT 3
        ''', (f'%{keyword}%', f'%{keyword}%', f'%{keyword}%')).fetchall()
        
        spots = conn.execute('''
            SELECT s.*, r.name as route_name FROM spots s
            JOIN routes r ON s.route_id = r.id
            WHERE s.name LIKE ?
            LIMIT 3
        ''', (f'%{keyword}%',)).fetchall()
        
        wishes = conn.execute(
            "SELECT * FROM wishes WHERE name LIKE ? AND user_id = ? LIMIT 3",
            (f'%{keyword}%', user_id)
        ).fetchall()
    
    result = []
    
    if routes:
        result.append('🗺️ 相關路線:')
        for r in routes:
            result.append(f"  {r['cover_emoji']} {r['name']} ({r['region']})")
    
    if spots:
        result.append('\n📍 相關景點:')
        for s in spots:
            result.append(f"  {s['icon']} {s['name']}")
    
    if wishes:
        result.append('\n📋 願望清單:')
        for w in wishes:
            status = '✅' if w['completed'] else '⬜'
            result.append(f"  {status} {w['name']}")
    
    if not result:
        result.append(f'找不到「{keyword}」相關內容')
        result.append('\n💡 試試: 路線、圖鑑、成就')
    
    return '\n'.join(result)

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
