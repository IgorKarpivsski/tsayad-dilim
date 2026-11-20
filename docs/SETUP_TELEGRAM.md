# הקמת ערוץ Telegram + בוט (≈10 דקות, מהטלפון)

## 1. ערוץ
1. Telegram → ✏️ → **New Channel**.
2. שם הערוץ:
```
צייד הדילים | דילים מאליאקספרס 🔥
```
3. תיאור:
```
מוצרים מ-AliExpress שעברו סינון: משוב חיובי גבוה, ביקוש מוכח ומחיר מאומת בשקלים. דיל חדש בערך כל שעתיים 🛒
גילוי נאות: הקישורים הם קישורי שותפים.
🌐 tsayad-dilim.pages.dev
```
4. סוג: **Public**. Username (נבדק – נראה פנוי ב-20/11/2026; טלגרם יאשר סופית):
```
tsayad_dilim
```
5. תמונת פרופיל: הקובץ `assets/brand/profile.png`.

## 2. בוט
1. פתח את **@BotFather** → שלח:
```
/newbot
```
2. שם:
```
Tsayad HaDilim Bot
```
3. Username (נראה פנוי):
```
tsayad_dilim_bot
```
4. BotFather ישלח **Token** → זה `TELEGRAM_BOT_TOKEN` (אל תשתף אותו עם אף אחד).

## 3. הבוט כמנהל
ערוץ → ⚙️ → **Administrators → Add Admin** → חפש `tsayad_dilim_bot` → השאר מסומן רק **Post Messages** (ו-Edit Messages) → שמור.

## 4. מזהים ל-GitHub Secrets
```
TELEGRAM_CHANNEL_ID
```
ערך:
```
@tsayad_dilim
```
```
TELEGRAM_ADMIN_CHAT_ID
```
ערך: המזהה המספרי שלך. כדי לקבל אותו: שלח הודעה כלשהי לבוט שלך, ואז פתח בדפדפן (החלף TOKEN):
```
https://api.telegram.org/botTOKEN/getUpdates
```
חפש `"chat":{"id":123456789` – המספר הוא ה-ID שלך.

## 5. בדיקה
הרץ את ה-workflow ידנית. תקבל בצ'אט הפרטי: "✅ צייד הדילים: חיבור ההתראות עובד", והבדיקה תאשר `can_post: true`.
