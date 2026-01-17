# 📖 退休走讀

> 旅遊願望清單 × 探險圖鑑 二合一系統

結合「想去的地方」願望管理與「景點收集打卡」圖鑑系統，專為退休慢遊設計。

## ✨ 核心功能

### 📋 願望清單
- 新增/編輯/刪除想去的地方
- 優先度、最佳季節、預算設定
- 完成打勾，累積成就感

### 🗺️ 探險圖鑑
- 景點打卡收集系統
- 稀有度分級（普通/稀有/史詩/傳說）
- 收集進度視覺化

### 🏆 成就徽章（16種）
| 徽章 | 名稱 | 條件 |
|:---:|:---|:---|
| 🎯 | 初次打卡 | 打卡 1 個景點 |
| 🧭 | 小小探險家 | 打卡 5 個景點 |
| 🗺️ | 資深探險家 | 打卡 10 個景點 |
| 🏆 | 探險大師 | 打卡 25 個景點 |
| 📷 | 攝影新手 | 上傳 1 張照片 |
| 🎞️ | 攝影達人 | 上傳 10 張照片 |
| 👟 | 健走新手 | 累計 10 公里 |
| 🥾 | 健走達人 | 累計 50 公里 |
| 🦶 | 百里行者 | 累計 100 公里 |
| ⭐ | 夢想實現 | 完成 1 個願望 |
| 🌟 | 圓夢達人 | 完成 10 個願望 |
| 📝 | 旅遊作家 | 寫 5 篇日記 |

### 🚶 走讀路線
- 台灣各地精選路線
- 無障礙程度標示（♿ 1-5 級）
- 沿途設施：廁所、休息區、停車場

### 💬 LINE Bot 互動
| 指令 | 功能 |
|------|------|
| `選單` | 功能選單 |
| `願望` | 查看願望清單 |
| `路線` | 本季推薦 |
| `圖鑑` | 收集進度 |
| `成就` | 已解鎖徽章 |
| `統計` | 總覽數據 |
| `新增 地點` | 加入願望 |
| `完成 地點` | 標記完成 |

---

## 🚀 部署到 Railway

### 1. LINE Bot 設定

1. [LINE Developers](https://developers.line.biz/) 建立 Messaging API Channel
2. 取得 **Channel Secret** 和 **Channel Access Token**

### 2. 部署

```bash
# 推到 GitHub
git init && git add . && git commit -m "init"
gh repo create retire-reading --public --push

# 或使用 Railway CLI
railway login && railway init && railway up
```

### 3. 環境變數

```
LINE_CHANNEL_SECRET=你的secret
LINE_CHANNEL_ACCESS_TOKEN=你的token
```

### 4. LINE Webhook

- URL: `https://你的網址.railway.app/callback`
- 開啟 Use webhook

---

## 🎨 設計特色

- **3D 旋轉冷光 Logo** - 「讀」字 Apple 風格
- **深色主題** - 護眼舒適
- **玻璃擬態** - 現代質感
- **霓虹光暈** - 科技美學

---

## 📁 專案結構

```
retire-reading/
├── app.py              # Flask + LINE Bot
├── requirements.txt
├── Procfile
├── templates/
│   ├── index.html      # 首頁儀表板
│   ├── wishes.html     # 願望清單
│   ├── routes.html     # 走讀路線
│   ├── atlas.html      # 探險圖鑑
│   ├── achievements.html # 成就徽章
│   └── logs.html       # 旅遊紀錄
└── retire_reading.db   # SQLite
```

---

## 🛠️ 本地開發

```bash
pip install -r requirements.txt
python app.py
# 開啟 http://localhost:5000
```

---

🌿 退休生活，慢慢走，好好讀！
