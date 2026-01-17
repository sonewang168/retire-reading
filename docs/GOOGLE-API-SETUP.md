# 🔗 Google API 設定指南

## 📋 功能說明

整合後可實現：
- **📷 Google 相簿**：打卡照片自動上傳到「退休走讀圖鑑」相簿
- **📝 Google 文件**：旅遊心得自動整理到「退休走讀旅遊日誌」文件

---

## 🛠️ 設定步驟

### Step 1: 建立 Google Cloud 專案

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 點擊上方「選取專案」→「新增專案」
3. 專案名稱：`retire-reading`
4. 點擊「建立」

---

### Step 2: 啟用 API

1. 在專案中，前往「API 和服務」→「資料庫」
2. 搜尋並啟用以下 API：
   - ✅ **Google Photos Library API**
   - ✅ **Google Docs API**
   - ✅ **Google Drive API**

---

### Step 3: 設定 OAuth 同意畫面

1. 前往「API 和服務」→「OAuth 同意畫面」
2. 選擇「外部」→「建立」
3. 填寫：
   - 應用程式名稱：`退休走讀`
   - 使用者支援電子郵件：你的 Email
   - 開發人員聯絡資訊：你的 Email
4. 點擊「儲存並繼續」
5. 新增範圍（Scopes）：
   ```
   https://www.googleapis.com/auth/photoslibrary
   https://www.googleapis.com/auth/photoslibrary.appendonly
   https://www.googleapis.com/auth/documents
   https://www.googleapis.com/auth/drive.file
   openid
   email
   profile
   ```
6. 測試使用者：新增你自己的 Email
7. 儲存

---

### Step 4: 建立 OAuth 用戶端 ID

1. 前往「API 和服務」→「憑證」
2. 點擊「建立憑證」→「OAuth 用戶端 ID」
3. 應用程式類型：**網頁應用程式**
4. 名稱：`退休走讀 Web`
5. **授權重新導向 URI**：
   ```
   https://你的網域.up.railway.app/google/callback
   ```
   
   例如：
   ```
   https://retire-reading-643a9.up.railway.app/google/callback
   ```

6. 點擊「建立」
7. 記下：
   - **用戶端 ID**：`xxxxxx.apps.googleusercontent.com`
   - **用戶端密碼**：`GOCSPX-xxxxxx`

---

### Step 5: 設定 Railway 環境變數

在 Railway 專案中新增以下環境變數：

| 變數名稱 | 值 |
|---------|-----|
| `GOOGLE_CLIENT_ID` | 用戶端 ID |
| `GOOGLE_CLIENT_SECRET` | 用戶端密碼 |
| `GOOGLE_REDIRECT_URI` | `https://你的網域.up.railway.app/google/callback` |
| `FLASK_SECRET_KEY` | 隨機字串（用於 session 加密） |

---

## 🧪 測試連動

1. 開啟網站首頁
2. 點擊「📷 Google 連動」
3. 點擊「使用 Google 帳號連動」
4. 授權存取權限
5. 看到「連動成功」畫面

---

## 📱 功能使用

### 上傳照片到相簿

```python
# API 端點
POST /google/upload

# 表單參數
- photo: 照片檔案
- spot_name: 景點名稱
- description: 描述（選填）
```

### 新增旅遊記錄到文件

```python
# API 端點
POST /google/doc/entry

# JSON 參數
{
    "spot_name": "景點名稱",
    "location": "地點",
    "notes": "心得筆記",
    "photo_url": "照片連結（選填）"
}
```

### 打卡同步（照片+文件）

```python
# API 端點
POST /google/checkin

# 表單參數
- photo: 照片檔案（選填）
- spot_name: 景點名稱
- location: 地點
- notes: 心得筆記
```

---

## ⚠️ 注意事項

1. **測試模式**：OAuth 同意畫面在測試模式時，只有加入測試使用者的帳號可以授權
2. **發布應用程式**：正式上線前需要提交 Google 審核
3. **Token 過期**：Access Token 約 1 小時過期，系統會自動使用 Refresh Token 更新
4. **相簿限制**：Google Photos API 只能上傳到自己建立的相簿
5. **資料歸屬**：所有資料都儲存在使用者自己的 Google 帳號中

---

## 🐛 常見問題

### Q: 授權時出現「未經驗證的應用程式」警告？
A: 這是正常的測試模式警告，點擊「進階」→「前往（應用程式名稱）」即可繼續

### Q: 授權後出現 400 錯誤？
A: 檢查 `GOOGLE_REDIRECT_URI` 是否與 OAuth 憑證中的「授權重新導向 URI」完全一致

### Q: 上傳照片失敗？
A: 確認已啟用 Google Photos Library API，並且 OAuth 範圍包含 `photoslibrary`

---

## 📚 參考文件

- [Google Photos Library API](https://developers.google.com/photos/library/guides/get-started)
- [Google Docs API](https://developers.google.com/docs/api/quickstart/python)
- [Google OAuth 2.0](https://developers.google.com/identity/protocols/oauth2/web-server)
