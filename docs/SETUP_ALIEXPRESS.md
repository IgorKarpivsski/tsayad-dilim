# חיבור AliExpress Affiliate API

> שמות תפריטים אומתו מול מקורות עדכניים, אבל AliExpress משנה ממשקים מדי פעם. אם משהו לא תואם – פתח את הדף בחלון הדפדפן של Claude ואני אנווט איתך בזמן אמת.

## שלב 1 – Tracking ID (בפורטל השותפים)
1. היכנס ל:
```
https://portals.aliexpress.com
```
2. התחבר עם חשבון ה-Affiliate הקיים שלך.
3. עבור ל-**Settings → Tracking ID** (בחלק מהממשקים: Tools → Link Generator → Tracking ID).
4. צור Tracking ID חדש ייעודי למערכת (מומלץ, כדי להפריד נתונים) – למשל:
```
tsayad
```
5. העתק אותו – זה `AE_TRACKING_ID`.

## שלב 2 – אפליקציה ב-Open Platform (App Key + App Secret)
1. היכנס ל:
```
https://openservice.aliexpress.com
```
2. התחבר עם **אותו** חשבון AliExpress. אם זו הפעם הראשונה – השלם את פרופיל המפתח (Developer). בחר סוג מפתח מתאים ל-Affiliate (אדם פרטי/Individual אם אין לך חברה).
3. **בדיקת זכאות:** אם אין לך אפשרות ליצור אפליקציה מסוג Affiliate – החשבון עוד לא מאושר. אישור יכול לקחת כמה ימי עסקים.
4. ב-**App Management / Create App** בחר קטגוריית **Affiliates API**, תן שם (למשל `Tsayad HaDilim`) ותיאור קצר ("Telegram & website deals channel for Israel").
5. אחרי האישור: **APP Overview → Manage** ליד האפליקציה:
   - **App Key** → `AE_APP_KEY`
   - **App Secret** (בדרך כלל דרך כפתור View) → `AE_APP_SECRET`
6. **הרשאות:** ודא שבאפליקציה מופיעים ה-APIs: `aliexpress.affiliate.product.query`, `productdetail.get`, `link.generate`, `category.get`. `hotproduct.query` ו-`order.list` – אם קיימים, מצוין; אם לא – המערכת תעבוד בלעדיהם ותסמן אותם Pending.

## שלב 3 – חיבור למערכת
הוסף ב-GitHub: Settings → Secrets and variables → Actions → **New repository secret** – שלושה סודות:
```
AE_APP_KEY
```
```
AE_APP_SECRET
```
```
AE_TRACKING_ID
```

## שלב 4 – בדיקה אמיתית
ב-GitHub: Actions → autopilot → **Run workflow**. או מקומית:
```
python -m tsayad check
```
הפלט מציג לכל API: `ok: true/false` + השגיאה המדויקת מ-AliExpress. כך יודעים בפועל מה פתוח לחשבון שלך.

## חשוב
- המערכת משתמשת **רק** ב-Tracking ID שלך ולא משנה פרמטרים בקישורים.
- ה-App Secret לעולם לא נכנס לקוד או לריפו – רק ל-Secrets.
