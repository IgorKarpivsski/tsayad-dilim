# רשתות חברתיות – מה אפשרי בפועל ואיך מחברים

| פלטפורמה | אוטומטי? | מה המערכת עושה |
|---|---|---|
| Facebook (עמוד עסקי) | ✅ מלא | פוסט תמונה + קישור Affiliate + הפניה לטלגרם |
| Instagram (חשבון מקצועי) | ✅ מלא | Reel (או תמונה) + כיתוב + "קישור בביו" (קישורים בכיתוב לא לחיצים) |
| TikTok | ⚠️ טיוטה | הסרטון נשלח ל-Inbox שלך ב-TikTok; אתה מוסיף סאונד ולוחץ Post. פרסום ציבורי אוטומטי מחייב Audit של TikTok |
| קבוצות פייסבוק | ❌ | אין API לפרסום בקבוצות – לא מבוצע (ראה docs/GROWTH.md) |

## Facebook + Instagram (≈25 דקות)
1. צור **עמוד** פייסבוק בשם `צייד הדילים` (קטגוריה: Shopping & Retail). תמונה: `assets/brand/profile.png`, קאבר: `assets/brand/banner.png`.
2. אינסטגרם: צור חשבון חדש (מומלץ `tsayad.dilim` – בדוק זמינות באפליקציה) → Settings → Account type → **Professional (Business)** → קשר לעמוד הפייסבוק.
3. כנס ל:
```
https://developers.facebook.com/apps
```
Create App → Use case: **Manage everything on your Page** + Instagram API. המצב Development מספיק לעמוד שלך (אתה אדמין של האפליקציה).
4. Graph API Explorer → בחר את האפליקציה → הרשאות:
```
pages_show_list,pages_read_engagement,pages_manage_posts,instagram_basic,instagram_content_publish,business_management
```
Generate Access Token → המר ל-Long-Lived (Access Token Debugger → Extend) → קרא:
```
me/accounts
```
העתק את `access_token` של העמוד (Page Token ללא תפוגה) ואת `id` של העמוד.
5. מזהה אינסטגרם: ב-Explorer קרא (החלף PAGE_ID):
```
PAGE_ID?fields=instagram_business_account
```
6. GitHub Secrets:
```
FB_PAGE_ID
```
```
FB_PAGE_TOKEN
```
```
IG_USER_ID
```

## TikTok (טיוטות) (≈20 דקות + אישור)
1. ב-TikTok: צור חשבון `tsayad.dilim` (אם פנוי). שם תצוגה: צייד הדילים.
2. כנס ל:
```
https://developers.tiktok.com
```
צור App → הוסף מוצר **Content Posting API** → scope:
```
video.upload
```
3. השלם OAuth פעם אחת (אני אכין לך דף התחברות קטן כשתגיע לשלב הזה) כדי לקבל refresh token.
4. GitHub Secrets:
```
TIKTOK_CLIENT_KEY
```
```
TIKTOK_CLIENT_SECRET
```
```
TIKTOK_REFRESH_TOKEN
```
5. כל סרטון מגיע כהתראה באפליקציה; הכיתוב המוצע נשלח אליך בטלגרם. ב-TikTok יש לסמן "AI-generated" רק אם התוכן נוצר ב-AI (הכרטיסים שלנו משתמשים בתמונת המוכר האמיתית).
