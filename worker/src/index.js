// Tsayad HaDilim edge worker (Cloudflare Workers Free plan):
//  1) /go/<productId>?...  – signed redirect to the affiliate link + anonymous click count in D1
//  2) /stats               – signed endpoint the pipeline pulls click stats from
//  3) cron trigger         – reliably dispatches the GitHub Actions autopilot (GitHub's own cron can be late)
// No personal data is stored: only day, product, post, source, variant and a counter.

const enc = new TextEncoder();

async function hmacHex(secret, msg) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(msg));
  return [...new Uint8Array(sig)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function b64urlDecode(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  while (s.length % 4) s += "=";
  const bin = atob(s);
  return new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
}

const ALLOWED = /^https:\/\/(s\.click\.aliexpress\.com|[a-z]+\.aliexpress\.com)\//;

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const parts = url.pathname.split("/").filter(Boolean);

    if (parts[0] === "go" && parts[1]) {
      const pid = parts[1];
      const s = url.searchParams.get("s") || "";
      const p = url.searchParams.get("p") || "0";
      const v = url.searchParams.get("v") || "";
      const u = url.searchParams.get("u") || "";
      const k = url.searchParams.get("k") || "";
      const expected = (await hmacHex(env.TRACKER_SECRET, `${pid}|${s}|${p}|${v}|${u}`)).slice(0, 20);
      let target;
      try { target = b64urlDecode(u); } catch { target = ""; }
      if (k !== expected || !ALLOWED.test(target)) {
        return Response.redirect(env.SITE_URL || "https://aliexpress.com", 302);
      }
      const day = new Date().toISOString().slice(0, 10);
      const bot = /bot|crawl|spider|preview|facebookexternalhit|telegrambot|whatsapp/i.test(req.headers.get("user-agent") || "");
      if (!bot) {
        ctx.waitUntil(env.DB.prepare(
          "INSERT INTO clicks(day,post_id,product_id,source,variant,n) VALUES(?1,?2,?3,?4,?5,1) " +
          "ON CONFLICT(day,post_id,source) DO UPDATE SET n=n+1").bind(day, Number(p) || 0, pid, s, v).run());
      }
      return new Response(null, { status: 302, headers: { Location: target, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer-when-downgrade" } });
    }

    if (parts[0] === "stats") {
      const since = url.searchParams.get("since") || "1970-01-01";
      const t = url.searchParams.get("t") || "0";
      const k = url.searchParams.get("k") || "";
      const fresh = Math.abs(Date.now() / 1000 - Number(t)) < 600;
      const expected = (await hmacHex(env.TRACKER_SECRET, `stats|${since}|${t}`)).slice(0, 20);
      if (!fresh || k !== expected) return new Response("forbidden", { status: 403 });
      const { results } = await env.DB.prepare(
        "SELECT day, post_id, product_id, source, variant, n FROM clicks WHERE day >= ?1 ORDER BY day").bind(since).all();
      return Response.json({ rows: results });
    }

    if (parts[0] === "health") return new Response("ok");
    return Response.redirect(env.SITE_URL || "https://aliexpress.com", 302);
  },

  // Cron Trigger → GitHub workflow_dispatch (fine-grained token: this repo only, Actions: read & write)
  async scheduled(event, env, ctx) {
    if (!env.GH_TOKEN || !env.GH_REPO) return;
    ctx.waitUntil(fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/autopilot.yml/dispatches`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "tsayad-worker",
                 "X-GitHub-Api-Version": "2022-11-28" },
      body: JSON.stringify({ ref: env.GH_REF || "main" }),
    }));
  },
};
