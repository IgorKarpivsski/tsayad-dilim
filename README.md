# צייד הדילים (Tsayad HaDilim) – עסק Affiliate אוטונומי של AliExpress לקהל הישראלי

מערכת שמאתרת מוצרים איכותיים ב-AliExpress, מייצרת קישורי שותפים עם ה-Tracking ID שלך, כותבת פוסטים בעברית, מעצבת תמונות וסרטונים, מפרסמת לטלגרם כל ~שעתיים, מפיצה לפייסבוק/אינסטגרם/TikTok לפי ההרשאות, מעדכנת אתר, מודדת, לומדת ושולחת לך דוחות – ב-₪0 לחודש.

## מה צריך ממך (פעם אחת, ~60–90 דקות)
| # | פעולה | מדריך | חובה? |
|---|---|---|---|
| 1 | GitHub: ריפו **ציבורי** + העלאת הקוד | `docs/SETUP_DEPLOY.md` | חובה |
| 2 | AliExpress: App Key, App Secret, Tracking ID | `docs/SETUP_ALIEXPRESS.md` | חובה |
| 3 | Telegram: ערוץ `@tsayad_dilim` + בוט כאדמין | `docs/SETUP_TELEGRAM.md` | חובה |
| 4 | Cloudflare: Pages (אתר+דשבורד) + Worker (קליקים) | `docs/SETUP_DEPLOY.md` | מומלץ מאוד |
| 5 | Facebook / Instagram / TikTok | `docs/SETUP_SOCIAL.md` | אופציונלי |
| 6 | Gemini (כתיבה עם AI) | `.env.example` | אופציונלי |

אחרי זה הכול רץ לבד. כל רכיב שלא חובר מסומן **Pending** בדשבורד ולא מוצג כפעיל.

## פקודות
```bash
python -m tsayad check      # בדיקה חיה: הרשאות AliExpress, האם הבוט אדמין, התראות
python -m tsayad tick       # ריצת אוטופיילוט אחת (זה מה ש-GitHub Actions מריץ כל שעה)
python -m tsayad scan       # סריקת מוצרים עכשיו
python -m tsayad publish    # פרסום מוצר אחד עכשיו
python -m tsayad status     # מצב חיבורים ו-KPI
python -m tsayad report daily|weekly
python -m tsayad keygen     # מפתחות הצפנה וסיסמה
python -m pytest -q          # 16 בדיקות מקצה לקצה
```

## מבנה
```
tsayad/        aliexpress · discovery · scoring · content · media · telegram · social · publisher
                tracking · analytics · manager (AI Business Manager) · reports · site · dashboard
                storage (DB מוצפן) · crypto · config · db · http · log · __main__ (CLI)
config/settings.json   קטגוריות, מילות חיפוש, ספים, תדירות, מיתוג
worker/                Cloudflare Worker – מעקב קליקים + cron אמין
.github/workflows/     autopilot (כל שעה) + tests
docs/                  מדריכי הקמה, מיתוג, צמיחה, גיבוי
assets/                פונט Heebo (OFL) ונכסי מותג
```

## עקרונות שקודדו במערכת
- לא ממציאים מחיר/הנחה/יתרונות. מחיר נבדק מחדש רגע לפני פרסום.
- עמלה היא לכל היותר 10% מהציון – לא בוחרים מוצר רק בגלל עמלה.
- אין מוצר איכותי → לא מפרסמים (ומקבלים התראה).
- אותו מוצר לא חוזר לפני 45 יום. נעילה + concurrency → אין כפילויות.
- גילוי נאות בכל פוסט ובכל עמוד באתר. קישורי האתר מסומנים `rel="sponsored"`.
- סודות רק ב-GitHub Secrets. DB מוצפן AES-256-GCM. הדשבורד מוצפן בסיסמה.
- ללא ספאם, ללא קבוצות ללא רשות, ללא בוטים מזויפים, ללא עקיפת מגבלות API.

מסמכים נוספים: `TECHNICAL_RESEARCH.md`, `docs/BRAND.md`, `docs/GROWTH.md`, `docs/BACKUP_RESTORE.md`.
