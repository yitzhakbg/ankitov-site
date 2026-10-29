/**
 * ankitov-preview — password-gated static preview of the full site.
 * Serves the ../site directory (all 13 locales) ONLY to visitors with the
 * preview cookie. No DNS involved: lives at https://ankitov-preview.<subdomain>.workers.dev
 *
 * PREVIEW_PW is passed at deploy time via `wrangler deploy --var PREVIEW_PW:...`
 * (never committed to the repo).
 */
const FORM = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AnkiTov — private preview</title><style>
body{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;background:#0e1f17;color:#e8f5ee}
form{background:#132b20;padding:2rem 2.5rem;border-radius:14px;border:1px solid #2c4a3a}
h1{font-size:1.2rem;margin:0 0 1rem}input{font:inherit;padding:.5rem .75rem;border-radius:8px;border:1px solid #2c4a3a;background:#0e1f17;color:#e8f5ee;width:100%;box-sizing:border-box}
button{font:inherit;margin-top:.75rem;padding:.5rem 1.25rem;border-radius:8px;border:0;background:#3ddc84;color:#0e1f17;font-weight:600;cursor:pointer}
p{color:#9fbfae;font-size:.85rem}.err{color:#ff6b5e}</style></head>
<body><form method="POST" action="/__gate"><h1>AnkiTov — private preview</h1>
<p>Enter the preview password.</p>
<input type="password" name="pw" autofocus><button>Enter</button></form></body></html>`;

const html = (body, status) => new Response(body, { status, headers: { "content-type": "text/html; charset=utf-8" } });

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const pw = env.PREVIEW_PW || "";
    if (!pw) return html("Preview not configured (PREVIEW_PW missing).", 503);
    if (url.pathname === "/__gate" && req.method === "POST") {
      const f = await req.formData();
      if (f.get("pw") === pw) {
        return new Response(null, { status: 302, headers: {
          "Set-Cookie": `pv=${pw}; HttpOnly; Secure; Path=/; Max-Age=604800; SameSite=Lax`,
          Location: "/" } });
      }
      return html(FORM.replace("</p>", '</p><p class="err">Wrong password.</p>'), 401);
    }
    const cookie = req.headers.get("cookie") || "";
    if (cookie.includes(`pv=${pw}`)) return env.ASSETS.fetch(req);
    return html(FORM, 401);
  }
}
