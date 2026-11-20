# פריסה חינמית: GitHub + Cloudflare (≈30 דקות)

## א. GitHub (חובה)
1. צור ריפו **Public** בשם `tsayad` (ציבורי = דקות Actions ללא הגבלה; הנתונים הרגישים מוצפנים).
2. העלה את כל קבצי הפרויקט (Add file → Upload files, או `git push`).
3. הפק מפתחות (מקומית או ב-Codespaces):
```
python -m tsayad keygen
```
4. Settings → Secrets and variables → Actions → **Secrets** – הוסף:
```
DATA_KEY
```
```
DASHBOARD_PASSWORD
```
(+ סודות AliExpress וטלגרם מהמדריכים האחרים). **שמור עותק של DATA_KEY במקום בטוח** – בלעדיו אי אפשר לשחזר את הנתונים.
5. Actions → אפשר workflows → autopilot → **Run workflow**.

## ב. Cloudflare Pages – אתר + דשבורד (ללא כרטיס אשראי)
1. הירשם ב:
```
https://dash.cloudflare.com/sign-up
```
2. Account ID: מופיע בדף Workers & Pages (צד ימין) → Secret:
```
CLOUDFLARE_ACCOUNT_ID
```
3. My Profile → API Tokens → Create Token → תבנית **Edit Cloudflare Workers** (כוללת Pages) → Secret:
```
CLOUDFLARE_API_TOKEN
```
4. צור פרויקט Pages ריק פעם אחת (Workers & Pages → Create → Pages → **Direct Upload**) בשם:
```
tsayad-dilim
```
אם השם תפוס, Cloudflare ייתן כתובת אחרת – עדכן אותה ב-GitHub → Variables:
```
SITE_URL
```
```
CF_PAGES_PROJECT
```
5. האתר: `https://tsayad-dilim.pages.dev` · הדשבורד: `https://tsayad-dilim.pages.dev/admin/` (נעול בסיסמה).

## ג. Cloudflare Worker – מעקב קליקים + תזמון מדויק (מומלץ)
מהמחשב (צריך Node.js):
```
cd worker
npx wrangler login
npx wrangler d1 create tsayad-clicks
```
הדבק את ה-`database_id` ב-`worker/wrangler.toml`, ועדכן שם `GH_REPO` (המשתמש/tsayad). ואז:
```
npx wrangler d1 execute tsayad-clicks --remote --file=schema.sql
npx wrangler secret put TRACKER_SECRET
npx wrangler secret put GH_TOKEN
npx wrangler deploy
```
- `TRACKER_SECRET` – אותו ערך מ-keygen, וגם כ-GitHub Secret.
- `GH_TOKEN` – GitHub → Settings → Developer settings → Fine-grained token → רק הריפו `tsayad` → Actions: Read and write.
- הכתובת שתתקבל (למשל `https://tsayad-go.<שם>.workers.dev`) → GitHub Secret:
```
TRACKER_URL
```

## עלות
₪0. כל השירותים בתוכניות חינמיות שלא דורשות כרטיס אשראי; בחריגה – השירות נעצר, לא מחייב.
