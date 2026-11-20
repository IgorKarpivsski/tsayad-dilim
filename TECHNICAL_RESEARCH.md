# TECHNICAL_RESEARCH.md – מחקר טכני וארכיטקטורה (נבדק: 20/11/2026)

> עיקרון מנחה: לא להציג כפעיל משהו שלא עובד, לא להציג 24/7 משהו שתלוי במחשב הביתי, ולא לחרוג ממכסות חינמיות.

## 1. ממצאים לפי שירות

| שירות | חינמי? | חשבון/הרשאה | מגבלות עיקריות | פרסום אוטומטי | הערות |
|---|---|---|---|---|---|
| **AliExpress Affiliate API** (Open Platform, gateway `api-sg.aliexpress.com/sync`) | כן | חשבון Portals + אפליקציה מאושרת ב-Open Platform (אישור יכול לקחת ימים) | חתימת HMAC-SHA256 לכל קריאה; הרשאות משתנות בין חשבונות | — | `product.query`, `productdetail.get`, `link.generate`, `category.get` – בסיס. `hotproduct.query` ו-`order.list` **לא מובטחים לכל חשבון** → המערכת בודקת בפועל (`python -m tsayad check`) ומסמנת Pending אם אין גישה. אין ב-API: עלות משלוח מדויקת ומספר ביקורות → לא מוצגים כעובדה. |
| **Telegram Bot API** | כן | בוט מ-BotFather, אדמין בערוץ עם "פרסום הודעות" | ~20 הודעות לדקה לקבוצה/ערוץ; כיתוב לתמונה עד 1024 תווים | כן, מלא | הערוץ הוא ערוץ ההפצה הראשי – אין בו מגבלה על קישורי Affiliate. |
| **Meta – Facebook Pages API** | כן | עמוד עסקי, אפליקציית Meta (מצב פיתוח מספיק לעמוד שלך), Page Token | Rate limits של Graph | כן | `/{page-id}/photos` עם קובץ. פרסום **בקבוצות** אינו אפשרי דרך API → לא מבוצע. |
| **Instagram Content Publishing API** | כן | חשבון מקצועי (Business/Creator) מקושר לעמוד | התיעוד מציין גם 100 וגם 50 פוסטים ל-24 שעות – המערכת מגבילה ל-20 ביום | כן (תמונות, Reels) | המדיה חייבת להיות ב-URL ציבורי → האתר שלנו מארח אותה. קישורים בכיתוב לא לחיצים → "קישור בביו". |
| **TikTok Content Posting API** | כן | אפליקציית מפתחים + OAuth | **אפליקציה שלא עברה Audit יכולה לפרסם רק כפרטי (SELF_ONLY)**, עד 5 משתמשים ביום | חלקי | הפתרון החוקי: העלאה כ**טיוטה** לתיבת היוצר (Upload API). אתה פותח TikTok, מוסיף סאונד טרנדי ולוחץ פרסם (~20 שניות). אחרי Audit אפשר לעבור ל-Direct Post. |
| **GitHub Actions** | כן (ריפו ציבורי: דקות ללא הגבלה) | חשבון GitHub | cron "best effort" – יכול להתעכב; בריפו ציבורי workflow מתוזמן נכבה אחרי 60 יום ללא פעילות | — | המערכת שומרת state בכל ריצה (פעילות), ו-Cloudflare Worker cron מפעיל את ה-workflow כגיבוי מדויק. דיווחים בקהילה שבריפו **פרטי** בחשבון חינמי cron לא רץ – לא אומת רשמית, ולכן בחרנו ריפו ציבורי + הצפנה. |
| **Cloudflare Pages** | כן, ללא כרטיס אשראי | חשבון Cloudflare + API Token | 500 builds/חודש (אנחנו משתמשים ב-direct upload) | — | אירוח האתר + הדשבורד + המדיה; תת-דומיין חינמי `*.pages.dev`. |
| **Cloudflare Workers + D1** | כן | אותו חשבון | 100K בקשות/יום; D1: 5M שורות קריאה, 100K כתיבה ביום (נאכף מ-1/9/2026) | — | מעקב קליקים + cron אמין. |
| **Gemini API (Google AI Studio)** | יש מכסה חינמית, ללא כרטיס | מפתח API | המכסות קוצצו ב-2025–2026 והן משתנות לפי פרויקט; נתוני שכבה חינמית עשויים לשמש את Google | — | אופציונלי. מוגבל אצלנו ל-15 קריאות ביום. בלי מפתח – מנוע כתיבה מובנה. |
| **FFmpeg + Pillow (+libraqm)** | Open Source | — | זמן מעבד של ה-runner | — | כרטיסי מוצר בעברית RTL וסרטוני 9:16 אוטומטיים. |

## 2. הארכיטקטורה שנבחרה (₪0 לחודש)

```
 Cloudflare Worker cron ──► GitHub Actions (כל שעה, ריפו ציבורי)
                               │  python -m tsayad tick
                               ├─ שחזור DB מוצפן (ענף data)
                               ├─ סריקה יומית → סינון → ניקוד → קישורי Affiliate → תור
                               ├─ אימות מחיר → כרטיס+וידאו → פרסום לטלגרם (כל ~2 שעות)
                               ├─ אנליטיקה (קליקים/הזמנות/קהל) → למידה → המלצות → דוחות
                               ├─ בניית אתר + דשבורד מוצפן → Cloudflare Pages
                               ├─ פייסבוק / אינסטגרם / טיוטת TikTok
                               └─ שמירת DB מוצפן (force-push, היסטוריה לא גדלה)
 משתמשים ──► /go/... (Worker) ──► AliExpress   (ספירת קליק אנונימית ב-D1)
```

**למה לא שרת?** אין שרת חינמי אמין 24/7 בלי כרטיס אשראי. ריצות קצרות כל שעה מספיקות לפרסום כל שעתיים.
**למה SQLite?** קובץ אחד, ללא שירות חיצוני, קל לגבות. מוצפן AES-256-GCM לפני שמירה בריפו הציבורי.
**החלפה עתידית בתשלום:** כל רכיב הוא מודול נפרד – אפשר להחליף את `storage.py` ב-Postgres, את GitHub Actions בשרת, או את Gemini במודל אחר, בלי לגעת בשאר.

## 3. מה **לא** 24/7 באמת – בשקיפות
- GitHub cron עלול להתעכב בדקות ספורות ובעומסים גם יותר. ה-Worker cron מצמצם זאת.
- TikTok: טיוטות בלבד עד Audit.
- נתוני מכירות: רק אם `order.list` פתוח לחשבון שלך; אחרת – רק בפורטל.
- מעקב קליקים ולמידה: רק אחרי הקמת ה-Worker.

## 4. עלויות נסתרות אפשריות (וכיצד נמנעו)
| סיכון | מניעה |
|---|---|
| חריגה מדקות Actions | ריפו ציבורי = ללא הגבלה. |
| חיוב Gemini | מפתח מפרויקט **ללא Billing**; תקרה פנימית 15/יום. |
| Cloudflare | תוכנית Free בלבד, ללא כרטיס – בחריגה השירות נעצר, לא מחייב. |
| דומיין | לא נרכש – `pages.dev`. |

## 5. מקורות עיקריים
- AliExpress Open Platform – openservice.aliexpress.com (תיעוד API ו-SDK רשמיים)
- Telegram Bot API – core.telegram.org/bots/api
- Instagram Content Publishing – developers.facebook.com/docs/instagram-platform/content-publishing
- TikTok Direct Post / Content Sharing Guidelines – developers.tiktok.com
- GitHub Actions billing & limits – docs.github.com
- Cloudflare Workers/D1 pricing & changelog – developers.cloudflare.com
- Gemini API rate limits – ai.google.dev/gemini-api/docs/rate-limits
