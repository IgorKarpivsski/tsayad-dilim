# גיבוי ושחזור

## איפה הנתונים
- `data` branch בריפו: `state.db.enc` (המצב הנוכחי) + `backups/` – 14 גיבויים יומיים אחרונים. הכול מוצפן AES-256-GCM עם `DATA_KEY`.
- בלי `DATA_KEY` אין דרך לפענח. **שמור אותו גם במנהל סיסמאות.**

## שחזור לגיבוי יומי
```
git fetch origin data
git show origin/data:backups/2026-11-20.db.enc > restore.enc
python -m tsayad restore restore.enc
python -m tsayad save
```
(`save` דוחף את המצב המשוחזר חזרה ל-data.)

## גיבוי ידני
```
python -m tsayad backup my-backup.enc
```

## התאוששות מקריסה
- כל ריצה מתחילה משחזור ה-DB האחרון ומסתיימת בשמירה גם כשמשהו נכשל (`if: always()`).
- נעילת פרסום (20 דק') + `concurrency` ב-Actions מונעות פרסום כפול.
- פרסום שנכשל נשמר כ-failed, נשלחת התראה, ומנסים שוב בריצה הבאה; אחרי 3 כשלים המוצר נפסל.

## החלפת מפתח הצפנה
1. `python -m tsayad restore` עם המפתח הישן (גיבוי מקומי) → 2. עדכן `DATA_KEY` ב-Secrets → 3. `python -m tsayad save`.
