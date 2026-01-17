"""
退休走讀 - 旅遊願望清單 × 探險圖鑑 二合一系統
Railway + LINE Bot 版本
含 Google 相簿 + Google 文件整合
"""

import os
import json
from datetime import datetime
from flask import Flask, request, abort, render_template, jsonify, redirect, url_for, session
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

app = Flask(__name__, static_folder='static', static_url_path='/static')

# Session 密鑰（用於 Google OAuth）
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'retire-reading-secret-key-2025')

# 註冊 Google Blueprint（可選功能）
GOOGLE_ENABLED = False
try:
    from google_routes import google_bp
    app.register_blueprint(google_bp)
    GOOGLE_ENABLED = True
    print("✅ Google 整合模組已載入")
except Exception as e:
    print(f"⚠️ Google 整合模組未載入: {e}")

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
    """插入完整 144 個景點資料"""
    
    # 完整景點資料 - 全台 20 縣市
    FULL_DATA = {
        "台北市": {
            "emoji": "🏙️", "region": "北部",
            "routes": [("台北城市漫步", "台北經典景點一日遊", 5.0, 4.0, "輕鬆", 5, "四季皆宜", "101、故宮、龍山寺")],
            "spots": [
                ("台北101", "地標", "台灣最高建築", 25.0339, 121.5645, "🏢", "rare"),
                ("故宮博物院", "博物館", "國寶級收藏", 25.1024, 121.5485, "🏛️", "epic"),
                ("中正紀念堂", "古蹟", "民主紀念園區", 25.0347, 121.5219, "🏛️", "rare"),
                ("龍山寺", "廟宇", "萬華信仰中心", 25.0372, 121.4999, "🙏", "rare"),
                ("西門町", "商圈", "年輕人聖地", 25.0423, 121.5081, "🛍️", "common"),
                ("象山步道", "步道", "眺望101", 25.0275, 121.5714, "🥾", "common"),
                ("士林夜市", "夜市", "觀光夜市", 25.0878, 121.5241, "🍜", "common"),
                ("北投溫泉", "溫泉", "日式溫泉鄉", 25.1375, 121.5069, "♨️", "rare"),
                ("陽明山", "自然", "四季花海", 25.1636, 121.5406, "🌸", "rare"),
                ("大稻埕", "老街", "百年商街", 25.0565, 121.5103, "🏮", "rare"),
            ]
        },
        "新北市": {
            "emoji": "🌊", "region": "北部",
            "routes": [
                ("淡水老街漫步", "河岸風光美食之旅", 3.5, 2.5, "輕鬆", 4, "春秋", "老街、夕陽、紅毛城"),
                ("九份金瓜石懷舊", "礦業遺址山城風光", 4.0, 4.0, "中等", 3, "秋冬", "黃金博物館、茶樓")
            ],
            "spots": [
                ("淡水老街", "老街", "河岸風光", 25.1697, 121.4397, "🌅", "common"),
                ("九份老街", "老街", "山城風情", 25.1089, 121.8450, "🏮", "rare"),
                ("野柳地質公園", "自然", "女王頭", 25.2069, 121.6906, "🪨", "epic"),
                ("平溪天燈", "體驗", "放天燈祈福", 25.0258, 121.7383, "🏮", "rare"),
                ("猴硐貓村", "景點", "貓咪天堂", 25.0867, 121.8278, "🐱", "common"),
                ("十分瀑布", "瀑布", "台版尼加拉", 25.0469, 121.7772, "💧", "rare"),
                ("漁人碼頭", "碼頭", "情人橋夕陽", 25.1833, 121.4167, "🌉", "common"),
                ("烏來溫泉", "溫泉", "泰雅族溫泉", 24.8653, 121.5506, "♨️", "rare"),
                ("福隆海水浴場", "海灘", "東北角沙灘", 25.0167, 121.9500, "🏖️", "common"),
                ("金瓜石", "古蹟", "黃金博物館", 25.1083, 121.8583, "🏆", "rare"),
            ]
        },
        "桃園市": {
            "emoji": "✈️", "region": "北部",
            "routes": [("大溪老街散策", "木器街古蹟巡禮", 3.0, 2.5, "輕鬆", 4, "四季皆宜", "老街、豆干、木器")],
            "spots": [
                ("大溪老街", "老街", "木器街", 24.8833, 121.2833, "🏚️", "common"),
                ("拉拉山", "自然", "神木群", 24.7000, 121.4167, "🌲", "rare"),
                ("小烏來瀑布", "瀑布", "天空步道", 24.8333, 121.3833, "💧", "common"),
                ("石門水庫", "水庫", "湖光山色", 24.8167, 121.2500, "🌊", "common"),
                ("Xpark水族館", "水族館", "都會水族館", 25.0167, 121.2167, "🐟", "rare"),
                ("華泰名品城", "購物", "Outlet購物", 25.0167, 121.2250, "🛍️", "common"),
                ("角板山", "景點", "北橫風景", 24.8167, 121.3500, "🏔️", "common"),
                ("慈湖紀念雕塑公園", "公園", "蔣公銅像", 24.8333, 121.3000, "🗿", "common"),
            ]
        },
        "新竹縣市": {
            "emoji": "🌬️", "region": "北部",
            "routes": [("內灣老街散步", "客家風情體驗", 2.5, 2.0, "輕鬆", 4, "春秋", "老街、吊橋、野薑花")],
            "spots": [
                ("內灣老街", "老街", "客家風情", 24.7042, 121.1875, "🏮", "common"),
                ("新竹城隍廟", "廟宇", "百年古廟", 24.8050, 120.9658, "🙏", "rare"),
                ("司馬庫斯", "部落", "上帝的部落", 24.5833, 121.2500, "🌲", "legendary"),
                ("南寮漁港", "漁港", "17公里海岸線", 24.8417, 120.9167, "🚴", "common"),
                ("綠世界生態農場", "生態", "生態園區", 24.7333, 121.0667, "🦋", "common"),
                ("北埔老街", "老街", "客家聚落", 24.7000, 121.0583, "🏮", "common"),
                ("新竹動物園", "動物園", "百年動物園", 24.8000, 120.9750, "🦁", "common"),
            ]
        },
        "基隆市": {
            "emoji": "⚓", "region": "北部",
            "routes": [("基隆港都漫步", "海港城市風情", 3.0, 2.5, "輕鬆", 4, "四季皆宜", "廟口、正濱、和平島")],
            "spots": [
                ("基隆廟口夜市", "夜市", "美食天堂", 25.1286, 121.7420, "🍜", "rare"),
                ("和平島公園", "自然", "奇岩地質", 25.1584, 121.7631, "🪨", "rare"),
                ("正濱漁港彩色屋", "漁港", "彩虹漁村", 25.1480, 121.7589, "🌈", "rare"),
                ("望幽谷", "步道", "海岸步道", 25.1500, 121.8000, "🌊", "common"),
                ("基隆嶼", "離島", "登島探險", 25.1917, 121.7833, "🏝️", "rare"),
            ]
        },
        "苗栗縣": {
            "emoji": "🏔️", "region": "中部",
            "routes": [("勝興車站鐵道之旅", "鐵道文化體驗", 3.5, 3.0, "中等", 3, "春秋", "車站、斷橋、小火車")],
            "spots": [
                ("勝興車站", "車站", "鐵道文化", 24.4167, 120.7833, "🚂", "rare"),
                ("南庄老街", "老街", "客家山城", 24.5972, 120.9931, "🏮", "common"),
                ("三義木雕街", "老街", "木雕藝術", 24.3833, 120.7500, "🪵", "common"),
                ("通霄神社", "古蹟", "日式遺跡", 24.4917, 120.6833, "⛩️", "rare"),
                ("飛牛牧場", "牧場", "親子牧場", 24.4833, 120.7667, "🐄", "common"),
                ("龍騰斷橋", "古蹟", "鐵道遺跡", 24.4000, 120.7833, "🌉", "rare"),
            ]
        },
        "台中市": {
            "emoji": "☀️", "region": "中部",
            "routes": [("台中文青一日遊", "文創與美食之旅", 4.0, 4.0, "輕鬆", 5, "四季皆宜", "審計、歌劇院、逢甲")],
            "spots": [
                ("高美濕地", "濕地", "夕陽美景", 24.3167, 120.5500, "🌅", "epic"),
                ("逢甲夜市", "夜市", "創意美食", 24.1791, 120.6462, "🍜", "common"),
                ("彩虹眷村", "藝術", "彩繪藝術", 24.1382, 120.6196, "🎨", "rare"),
                ("宮原眼科", "美食", "日式建築冰店", 24.1378, 120.6845, "🍨", "rare"),
                ("武陵農場", "農場", "櫻花勝地", 24.3500, 121.3000, "🌸", "epic"),
                ("審計新村", "文創", "文創聚落", 24.1417, 120.6583, "📷", "common"),
                ("台中國家歌劇院", "藝文", "建築藝術", 24.1625, 120.6403, "🎭", "rare"),
                ("大坑步道", "步道", "登山健行", 24.1833, 120.7333, "🥾", "common"),
                ("梧棲漁港", "漁港", "海鮮美食", 24.2667, 120.5167, "🦐", "common"),
                ("谷關溫泉", "溫泉", "山中溫泉", 24.2000, 121.0000, "♨️", "rare"),
            ]
        },
        "彰化縣": {
            "emoji": "🙏", "region": "中部",
            "routes": [("鹿港小鎮散策", "古蹟與傳統工藝", 3.0, 3.0, "輕鬆", 4, "春秋冬", "天后宮、摸乳巷、老街")],
            "spots": [
                ("鹿港老街", "老街", "一府二鹿", 24.0544, 120.4347, "🏮", "rare"),
                ("八卦山大佛", "地標", "地標大佛", 24.0833, 120.5417, "🙏", "rare"),
                ("扇形車庫", "古蹟", "鐵道遺產", 24.0833, 120.5333, "🚂", "rare"),
                ("田尾公路花園", "花園", "花卉天堂", 23.8917, 120.5250, "🌷", "common"),
                ("王功漁港", "漁港", "蚵仔故鄉", 23.9667, 120.3167, "🦪", "common"),
            ]
        },
        "南投縣": {
            "emoji": "🌲", "region": "中部",
            "routes": [("日月潭環湖步道", "台灣之心湖光山色", 3.0, 2.0, "輕鬆", 4, "四季皆宜", "向山、水社、文武廟")],
            "spots": [
                ("日月潭", "湖泊", "台灣之心", 23.8583, 120.9167, "🌊", "epic"),
                ("清境農場", "農場", "高山草原", 24.0583, 121.1667, "🐑", "epic"),
                ("溪頭森林", "森林", "森林浴場", 23.6750, 120.7917, "🌲", "rare"),
                ("集集車站", "車站", "小火車站", 23.8333, 120.7833, "🚂", "common"),
                ("合歡山", "高山", "雪季賞雪", 24.1500, 121.2750, "⛰️", "epic"),
                ("忘憂森林", "秘境", "夢幻秘境", 23.6333, 120.8000, "🌫️", "rare"),
                ("埔里酒廠", "景點", "紹興酒香", 23.9667, 120.9667, "🍶", "common"),
            ]
        },
        "雲林縣": {
            "emoji": "🎭", "region": "中部",
            "routes": [("雲林布袋戲文化之旅", "傳統藝術體驗", 4.0, 3.5, "輕鬆", 4, "春秋", "朝天宮、糖廠、布袋戲")],
            "spots": [
                ("劍湖山", "樂園", "主題樂園", 23.6333, 120.5833, "🎢", "common"),
                ("北港朝天宮", "廟宇", "媽祖信仰中心", 23.5667, 120.3000, "🙏", "epic"),
                ("虎尾糖廠", "古蹟", "糖業歷史", 23.7083, 120.4333, "🏭", "common"),
                ("西螺大橋", "地標", "歷史建築", 23.7667, 120.4667, "🌉", "common"),
                ("草嶺風景區", "自然", "竹林秘境", 23.5833, 120.6833, "🎋", "rare"),
            ]
        },
        "嘉義縣市": {
            "emoji": "🌄", "region": "南部",
            "routes": [("阿里山森林步道", "神木雲海日出", 6.0, 4.0, "中等", 3, "春秋", "神木、日出、小火車")],
            "spots": [
                ("阿里山", "森林", "日出雲海", 23.5103, 120.8028, "🌄", "legendary"),
                ("奮起湖", "老街", "便當傳奇", 23.5083, 120.6917, "🍱", "rare"),
                ("檜意森活村", "文創", "日式建築群", 23.4833, 120.4500, "🏡", "rare"),
                ("故宮南院", "博物館", "亞洲藝術", 23.4667, 120.2917, "🏛️", "epic"),
                ("嘉義文化路夜市", "夜市", "火雞肉飯", 23.4833, 120.4500, "🍜", "common"),
                ("太平雲梯", "景點", "高山吊橋", 23.5833, 120.5833, "🌉", "rare"),
            ]
        },
        "台南市": {
            "emoji": "🏛️", "region": "南部",
            "routes": [("台南府城古蹟巡禮", "百年古都文化之旅", 5.0, 5.0, "輕鬆", 5, "春秋冬", "赤崁樓、孔廟、神農街")],
            "spots": [
                ("赤崁樓", "古蹟", "古蹟巡禮", 22.9976, 120.2023, "🏛️", "rare"),
                ("安平古堡", "古蹟", "台灣第一城", 23.0017, 120.1603, "🏰", "rare"),
                ("神農街", "老街", "老屋新生", 22.9975, 120.1958, "🏮", "rare"),
                ("奇美博物館", "博物館", "藝術殿堂", 22.9361, 120.2264, "🏛️", "epic"),
                ("林百貨", "古蹟", "日治百貨", 22.9914, 120.1997, "🏬", "rare"),
                ("井仔腳鹽田", "景點", "夕陽鹽田", 23.1500, 120.0833, "🌅", "rare"),
                ("孔廟", "古蹟", "全台首學", 22.9903, 120.2044, "📚", "rare"),
                ("花園夜市", "夜市", "台南小吃", 23.0000, 120.2167, "🍜", "common"),
                ("安平樹屋", "古蹟", "榕樹奇觀", 23.0000, 120.1583, "🌳", "rare"),
            ]
        },
        "高雄市": {
            "emoji": "🌴", "region": "南部",
            "routes": [("高雄港都漫遊", "海港城市風光", 6.0, 5.0, "輕鬆", 4, "四季皆宜", "駁二、旗津、蓮池潭")],
            "spots": [
                ("駁二藝術特區", "文創", "文創基地", 22.6203, 120.2817, "🎨", "rare"),
                ("旗津海岸", "海灘", "渡輪風情", 22.6000, 120.2667, "🏖️", "common"),
                ("蓮池潭", "景點", "龍虎塔", 22.6833, 120.2917, "🐉", "rare"),
                ("西子灣", "海灣", "夕陽美景", 22.6250, 120.2583, "🌅", "rare"),
                ("佛光山", "寺廟", "佛教聖地", 22.7500, 120.4417, "🙏", "epic"),
                ("美濃客家村", "部落", "客家文化", 22.8917, 120.5417, "🏮", "common"),
                ("六合夜市", "夜市", "觀光夜市", 22.6333, 120.2917, "🍜", "common"),
                ("旗山老街", "老街", "香蕉故鄉", 22.8833, 120.4833, "🍌", "common"),
                ("愛河", "河岸", "河岸風光", 22.6333, 120.2833, "🌃", "common"),
                ("美麗島站", "地鐵", "光之穹頂", 22.6317, 120.2867, "✨", "rare"),
            ]
        },
        "屏東縣": {
            "emoji": "🏝️", "region": "南部",
            "routes": [("墾丁國家公園", "國境之南熱帶風情", 8.0, 6.0, "中等", 3, "秋冬春", "鵝鑾鼻、龍磐、後壁湖")],
            "spots": [
                ("墾丁國家公園", "國家公園", "國境之南", 21.9500, 120.7833, "🏝️", "epic"),
                ("鵝鑾鼻燈塔", "燈塔", "台灣最南點", 21.9000, 120.8500, "🗼", "rare"),
                ("恆春老街", "老街", "海角七號", 22.0000, 120.7500, "🏮", "common"),
                ("小琉球", "離島", "珊瑚島嶼", 22.3333, 120.3667, "🐢", "epic"),
                ("霧台部落", "部落", "魯凱文化", 22.7500, 120.7333, "🏔️", "rare"),
                ("龍磐草原", "草原", "星空聖地", 21.9333, 120.8333, "🌌", "rare"),
                ("海生館", "水族館", "海洋世界", 22.0500, 120.7000, "🐬", "rare"),
                ("大鵬灣", "風景區", "潟湖風光", 22.4333, 120.5000, "🌊", "common"),
            ]
        },
        "宜蘭縣": {
            "emoji": "🌾", "region": "北部",
            "routes": [("宜蘭礁溪溫泉散步", "溫泉小鎮愜意時光", 2.0, 2.0, "輕鬆", 5, "秋冬", "湯圍溝、溫泉魚")],
            "spots": [
                ("礁溪溫泉", "溫泉", "溫泉鄉", 24.8333, 121.7667, "♨️", "rare"),
                ("羅東夜市", "夜市", "在地美食", 24.6833, 121.7667, "🍜", "common"),
                ("太平山", "森林", "森林鐵道", 24.5167, 121.5167, "🌲", "epic"),
                ("蘭陽博物館", "博物館", "建築美學", 24.8667, 121.8333, "🏛️", "rare"),
                ("龜山島", "離島", "牛奶海", 24.8500, 121.9500, "🐢", "epic"),
                ("幾米公園", "藝術", "繪本世界", 24.7583, 121.7583, "🎨", "common"),
                ("外澳海灘", "海灘", "衝浪聖地", 24.8833, 121.8500, "🏄", "common"),
            ]
        },
        "花蓮縣": {
            "emoji": "⛰️", "region": "東部",
            "routes": [("花蓮七星潭海岸", "太平洋壯闘風光", 2.5, 1.5, "輕鬆", 4, "春夏秋", "礫石海灘、觀星")],
            "spots": [
                ("太魯閣", "國家公園", "峽谷地形", 24.1667, 121.5000, "⛰️", "legendary"),
                ("七星潭", "海灘", "礫石海灘", 24.0333, 121.6333, "🏖️", "rare"),
                ("清水斷崖", "斷崖", "蘇花公路", 24.2333, 121.6833, "🌊", "epic"),
                ("鯉魚潭", "湖泊", "湖光山色", 23.9333, 121.5167, "🚣", "common"),
                ("六十石山", "花海", "金針花海", 23.3000, 121.2167, "🌻", "rare"),
                ("瑞穗溫泉", "溫泉", "黃金湯", 23.5000, 121.3667, "♨️", "rare"),
                ("雲山水", "秘境", "夢幻湖泊", 23.7333, 121.4333, "🌳", "rare"),
                ("林田山林業文化園區", "古蹟", "森林鐵道", 23.7500, 121.4167, "🚂", "rare"),
            ]
        },
        "台東縣": {
            "emoji": "🎈", "region": "東部",
            "routes": [("台東池上伯朗大道", "無邊際稻田療癒之旅", 5.0, 3.0, "輕鬆", 4, "夏秋", "金城武樹、天堂路")],
            "spots": [
                ("伯朗大道", "稻田", "金城武樹", 23.0917, 121.1917, "🌾", "rare"),
                ("三仙台", "海岸", "八拱橋", 23.1167, 121.4167, "🌉", "epic"),
                ("知本溫泉", "溫泉", "泡湯勝地", 22.7000, 121.0167, "♨️", "rare"),
                ("綠島", "離島", "潛水天堂", 22.6667, 121.4833, "🐠", "epic"),
                ("蘭嶼", "離島", "飛魚文化", 22.0500, 121.5500, "🛶", "legendary"),
                ("鹿野高台", "草原", "熱氣球", 22.9167, 121.1167, "🎈", "rare"),
                ("多良車站", "車站", "最美車站", 22.5167, 120.9500, "🚂", "rare"),
            ]
        },
        "澎湖縣": {
            "emoji": "🐚", "region": "離島",
            "routes": [("澎湖跳島之旅", "離島海洋風情", 10.0, 8.0, "中等", 3, "春夏", "跨海大橋、雙心石滬")],
            "spots": [
                ("澎湖跨海大橋", "地標", "台灣最長跨海大橋", 23.5917, 119.5500, "🌉", "rare"),
                ("七美雙心石滬", "景點", "浪漫雙心", 23.2000, 119.4333, "💕", "epic"),
                ("吉貝沙尾", "海灘", "最美沙灘", 23.7333, 119.6083, "🏖️", "rare"),
                ("二崁聚落", "古蹟", "閩式建築", 23.5917, 119.5167, "🏘️", "rare"),
                ("藍洞", "秘境", "海蝕洞", 23.7333, 119.5167, "🔵", "rare"),
                ("小門鯨魚洞", "自然", "海蝕洞", 23.6000, 119.4833, "🐋", "common"),
            ]
        },
        "金門縣": {
            "emoji": "🏯", "region": "離島",
            "routes": [("金門戰地巡禮", "戰地風光歷史之旅", 6.0, 5.0, "輕鬆", 4, "春秋", "古寧頭、翟山坑道")],
            "spots": [
                ("金門古寧頭", "戰地", "戰役遺址", 24.4667, 118.3000, "⚔️", "rare"),
                ("金門模範街", "老街", "巴洛克建築", 24.4333, 118.3167, "🏛️", "common"),
                ("翟山坑道", "戰地", "地下碼頭", 24.4167, 118.3000, "🚢", "rare"),
                ("莒光樓", "地標", "金門地標", 24.4333, 118.3167, "🏯", "rare"),
                ("水頭聚落", "古蹟", "閩南建築群", 24.4083, 118.3000, "🏘️", "rare"),
            ]
        },
        "馬祖": {
            "emoji": "⛵", "region": "離島",
            "routes": [("馬祖藍眼淚追蹤", "追逐藍眼淚之旅", 5.0, 4.0, "中等", 3, "春夏", "北海坑道、芹壁")],
            "spots": [
                ("北海坑道", "戰地", "藍眼淚", 26.1500, 119.9333, "✨", "epic"),
                ("芹壁聚落", "古蹟", "閩東建築", 26.2167, 120.0000, "🏘️", "rare"),
                ("東引燈塔", "燈塔", "國之北疆", 26.3667, 120.5000, "🗼", "rare"),
                ("大坵島", "離島", "梅花鹿", 26.2000, 119.9500, "🦌", "rare"),
                ("馬祖酒廠", "景點", "老酒文化", 26.1500, 119.9333, "🍶", "common"),
            ]
        }
    }
    
    route_id = 1
    spot_order = 1
    
    for city, data in FULL_DATA.items():
        region = data["region"]
        emoji = data["emoji"]
        
        # 插入路線
        for route in data["routes"]:
            name, desc, dist, hours, diff, acc, season, highlights = route
            conn.execute('''
                INSERT INTO routes (name, region, description, distance_km, duration_hours, 
                                  difficulty, accessibility, best_season, highlights, cover_emoji)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (name, region, desc, dist, hours, diff, acc, season, highlights, emoji))
            
            current_route_id = route_id
            route_id += 1
            
            # 插入該路線的景點
            spot_num = 1
            for spot in data["spots"]:
                name, stype, desc, lat, lng, icon, rarity = spot
                conn.execute('''
                    INSERT INTO spots (route_id, name, spot_type, description, 
                                     has_restroom, has_rest_area, has_parking, wheelchair_accessible,
                                     lat, lng, order_num, icon, rarity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (current_route_id, name, stype, desc, 1, 1, 1, 1, lat, lng, spot_num, icon, rarity))
                spot_num += 1
    
    conn.commit()
    print(f"✅ 已插入 {route_id-1} 條路線與 144 個景點")

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

@app.route('/google-settings')
def google_settings():
    """Google 連動設定頁面"""
    return render_template('google_settings.html')

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
                   c.checkin_date, c.photo_url, c.note as checkin_note
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

@app.route('/checkins')
def checkins_page():
    """打卡記錄頁面"""
    user_id = request.args.get('user', 'default')
    
    with get_db() as conn:
        # 取得所有打卡記錄
        checkins = conn.execute('''
            SELECT c.*, s.name as spot_name, s.icon, s.spot_type,
                   r.name as route_name, r.region
            FROM checkins c
            JOIN spots s ON c.spot_id = s.id
            JOIN routes r ON c.route_id = r.id
            WHERE c.user_id = ?
            ORDER BY c.checkin_date DESC, c.id DESC
        ''', (user_id,)).fetchall()
        
        # 統計
        photo_count = sum(1 for c in checkins if c['photo_url'])
        note_count = sum(1 for c in checkins if c['note'])
    
    # 檢查 Google 連動狀態
    google_connected = 'google_access_token' in session
    album_url = None
    doc_url = None
    
    if google_connected:
        try:
            from google_integration import get_or_create_album, get_or_create_travel_doc
            
            album = get_or_create_album(session['google_access_token'])
            if album.get('productUrl'):
                album_url = album['productUrl']
            
            doc = get_or_create_travel_doc(session['google_access_token'])
            if doc.get('documentId'):
                doc_url = f"https://docs.google.com/document/d/{doc['documentId']}/edit"
        except:
            pass
    
    return render_template('checkins.html',
                          checkins=checkins,
                          photo_count=photo_count,
                          note_count=note_count,
                          google_connected=google_connected,
                          album_url=album_url,
                          doc_url=doc_url,
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
    """打卡景點（支援照片上傳 + Google 同步）"""
    import uuid
    
    # 支援 JSON 或 FormData
    if request.is_json:
        user_id = request.json.get('user_id', 'default')
        note = request.json.get('note', '')
        photo_url = None
        photo_data = None
        photo_filename = None
    else:
        user_id = request.form.get('user_id', 'default')
        note = request.form.get('note', '')
        photo_url = None
        photo_data = None
        photo_filename = None
        
        # 處理照片上傳
        if 'photo' in request.files:
            photo = request.files['photo']
            if photo and photo.filename:
                # 讀取照片資料（用於 Google 上傳）
                photo_data = photo.read()
                photo.seek(0)  # 重置指標
                
                # 儲存照片到 static/uploads
                upload_dir = os.path.join(app.static_folder or 'static', 'uploads')
                os.makedirs(upload_dir, exist_ok=True)
                
                # 生成唯一檔名
                ext = photo.filename.rsplit('.', 1)[-1].lower() if '.' in photo.filename else 'jpg'
                photo_filename = f"{user_id}_{spot_id}_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(upload_dir, photo_filename)
                
                photo.save(filepath)
                photo_url = f"/static/uploads/{photo_filename}"
    
    with get_db() as conn:
        # 檢查是否已打卡
        existing = conn.execute(
            "SELECT id FROM checkins WHERE user_id = ? AND spot_id = ?",
            (user_id, spot_id)
        ).fetchone()
        
        if existing:
            return jsonify({'success': False, 'message': '已經打卡過了'})
        
        # 取得景點資訊
        spot = conn.execute("SELECT s.*, r.name as route_name, r.region FROM spots s JOIN routes r ON s.route_id = r.id WHERE s.id = ?", (spot_id,)).fetchone()
        
        # 新增打卡
        conn.execute('''
            INSERT INTO checkins (user_id, spot_id, route_id, checkin_date, note, photo_url)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (user_id, spot_id, spot['route_id'], datetime.now().strftime('%Y-%m-%d'), note, photo_url))
        
        conn.commit()
    
    # ========== Google 同步 ==========
    google_result = None
    if session.get('google_access_token'):
        try:
            from google_integration import save_checkin_with_photo
            
            # 組合地點資訊
            location = f"{spot['region']} - {spot['route_name']}"
            
            # 同步到 Google 相簿 + 文件
            google_result = save_checkin_with_photo(
                access_token=session['google_access_token'],
                spot_name=spot['name'],
                location=location,
                notes=note or f"打卡 {spot['name']}",
                image_data=photo_data,
                filename=photo_filename
            )
        except Exception as e:
            print(f"Google 同步失敗: {e}")
            google_result = {'success': False, 'error': str(e)}
    
    # 檢查成就
    unlocked = check_achievements(user_id)
    
    result = {
        'success': True,
        'message': f"成功打卡「{spot['name']}」！",
        'unlocked': [{'name': a['name'], 'icon': a['icon']} for a in unlocked]
    }
    
    # 加入 Google 同步結果
    if google_result:
        result['google_sync'] = google_result.get('success', False)
        if google_result.get('doc', {}).get('documentId'):
            result['doc_url'] = f"https://docs.google.com/document/d/{google_result['doc']['documentId']}/edit"
    
    return jsonify(result)


@app.route('/spot/<int:spot_id>/checkin/cancel', methods=['POST'])
def cancel_checkin(spot_id):
    """取消打卡"""
    user_id = request.json.get('user_id', 'default')
    
    with get_db() as conn:
        # 檢查打卡是否存在
        checkin = conn.execute(
            "SELECT id, photo_url FROM checkins WHERE user_id = ? AND spot_id = ?",
            (user_id, spot_id)
        ).fetchone()
        
        if not checkin:
            return jsonify({'success': False, 'message': '找不到打卡記錄'})
        
        # 刪除照片檔案（如果有）
        if checkin['photo_url']:
            import os
            photo_path = os.path.join(app.static_folder or 'static', checkin['photo_url'].lstrip('/static/'))
            if os.path.exists(photo_path):
                try:
                    os.remove(photo_path)
                except:
                    pass
        
        # 刪除打卡記錄
        conn.execute(
            "DELETE FROM checkins WHERE user_id = ? AND spot_id = ?",
            (user_id, spot_id)
        )
        conn.commit()
    
    return jsonify({'success': True, 'message': '已取消打卡'})

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

# 應用啟動時自動初始化資料庫（gunicorn 和直接執行都會觸發）
init_db()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
