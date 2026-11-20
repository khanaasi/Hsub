// Cloudflare Worker: Ping Manager (D1) - URL ping + HF token check/restart
// D1 binding name : DB        (tables apne aap ban jaate hain)
// Secrets         : ADMIN_PASS (zaroori), HF_TOKEN (optional, auto-restart ke liye)
// Cron trigger    : */5 * * * *
// Admin page      : https://<worker>.workers.dev/  (browser password box: user = kuch bhi, password = ADMIN_PASS)

const UA =
  "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36";
const MAX_URLS = 15; // free plan: ek run me 50 subrequest; har HF URL = ping + runtime check (+restart)
const RESTART_COOLDOWN = 30 * 60 * 1000; // ek Space ko 30 min me ek hi baar restart
const RESTART_STAGES = ["SLEEPING", "RUNTIME_ERROR", "STOPPED"];
const HF = "https://huggingface.co";

let ready = false;
async function ensure(env) {
  if (ready) return;
  await env.DB.batch([
    env.DB.prepare(
      "CREATE TABLE IF NOT EXISTS pings (url TEXT PRIMARY KEY, code INTEGER, ms INTEGER, at TEXT, err TEXT, stage TEXT, space TEXT, note TEXT, restarted_at INTEGER DEFAULT 0, added_at INTEGER)"
    ),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS spaces (sub TEXT PRIMARY KEY, id TEXT)"),
    env.DB.prepare("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT, exp INTEGER)"),
  ]);
  ready = true;
}

async function getRows(env) {
  return (await env.DB.prepare("SELECT * FROM pings ORDER BY added_at").all()).results;
}

const hfFetch = (env, path, init = {}) =>
  fetch(HF + path, {
    ...init,
    headers: { Authorization: "Bearer " + env.HF_TOKEN, "User-Agent": "ping-manager" },
    signal: AbortSignal.timeout(20000),
  });

// "owner-space-name.hf.space" -> "owner/space_name" (token wale account ke Spaces me dhundh kar)
async function resolveSpace(env, host) {
  const sub = host.replace(/\.hf\.space$/, "").toLowerCase();
  const norm = (s) => s.toLowerCase().replace(/[/_.]/g, "-");
  const known = await env.DB.prepare("SELECT id FROM spaces WHERE sub=?").bind(sub).first();
  if (known) return known.id;

  const cached = await env.DB.prepare("SELECT v FROM meta WHERE k='owners' AND exp>?").bind(Date.now()).first();
  let owners = cached ? JSON.parse(cached.v) : null;
  if (!owners) {
    const r = await hfFetch(env, "/api/whoami-v2");
    if (!r.ok) throw new Error("token check fail (" + r.status + ")");
    const w = await r.json();
    owners = [w.name, ...(w.orgs || []).map((o) => o.name)].filter(Boolean);
    await env.DB.prepare("INSERT OR REPLACE INTO meta(k,v,exp) VALUES('owners',?,?)")
      .bind(JSON.stringify(owners), Date.now() + 86400000)
      .run();
  }
  for (const o of owners) {
    if (!sub.startsWith(norm(o) + "-")) continue;
    const r = await hfFetch(env, "/api/spaces?author=" + encodeURIComponent(o) + "&limit=500");
    if (!r.ok) continue;
    const hit = (await r.json()).find((s) => norm(s.id) === sub);
    if (hit) {
      await env.DB.prepare("INSERT OR REPLACE INTO spaces(sub,id) VALUES(?,?)").bind(sub, hit.id).run();
      return hit.id;
    }
  }
  throw new Error("Space nahi mila (token usi account ka ho jisme ye Space hai)");
}

async function hfCheck(env, u, st) {
  let host = "";
  try { host = new URL(u).hostname; } catch { return; }
  if (!host.endsWith(".hf.space") || !env.HF_TOKEN) return;
  try {
    const id = await resolveSpace(env, host);
    st.space = id;
    const r = await hfFetch(env, "/api/spaces/" + id + "/runtime");
    if (!r.ok) { st.note = "runtime check " + r.status; return; }
    st.stage = (await r.json()).stage;
    if (RESTART_STAGES.includes(st.stage)) {
      if (Date.now() - (st.restartedAt || 0) > RESTART_COOLDOWN) {
        const rr = await hfFetch(env, "/api/spaces/" + id + "/restart", { method: "POST" });
        st.restartedAt = Date.now();
        st.note = rr.ok ? "restart bheja" : "restart fail " + rr.status;
      } else {
        st.note = "restart ho chuka (cooldown)";
      }
    }
  } catch (e) {
    st.note = String(e.message || e).slice(0, 90);
  }
}

async function runPings(env) {
  const rows = await getRows(env);
  const results = await Promise.all(
    rows.map(async (row) => {
      const t0 = Date.now();
      const st = { url: row.url, restartedAt: row.restarted_at || 0 };
      try {
        const r = await fetch(row.url + (row.url.includes("?") ? "&" : "?") + "t=" + t0, {
          headers: { "User-Agent": UA, "Cache-Control": "no-cache" },
          redirect: "follow",
          signal: AbortSignal.timeout(25000),
        });
        r.body?.cancel();
        st.code = r.status;
      } catch (e) {
        st.code = 0;
        st.err = String(e).slice(0, 80);
      }
      st.ms = Date.now() - t0;
      st.at = new Date().toISOString();
      await hfCheck(env, row.url, st);
      return st;
    })
  );
  if (results.length) {
    await env.DB.batch(
      results.map((s) =>
        env.DB.prepare(
          "UPDATE pings SET code=?, ms=?, at=?, err=?, stage=?, space=?, note=?, restarted_at=? WHERE url=?"
        ).bind(s.code, s.ms, s.at, s.err ?? null, s.stage ?? null, s.space ?? null, s.note ?? null, s.restartedAt || 0, s.url)
      )
    );
  }
  return getRows(env);
}

function authed(req, env) {
  const h = req.headers.get("Authorization") || "";
  if (!h.startsWith("Basic ") || !env.ADMIN_PASS) return false;
  let s = "";
  try { s = atob(h.slice(6)); } catch { return false; }
  return s.slice(s.indexOf(":") + 1) === env.ADMIN_PASS;
}

const json = (o, status = 200) =>
  new Response(JSON.stringify(o), { status, headers: { "Content-Type": "application/json" } });

async function snap(env, rows) {
  rows = rows || (await getRows(env));
  const status = {};
  for (const r of rows) {
    if (r.at) status[r.url] = { code: r.code, ms: r.ms, at: r.at, err: r.err, stage: r.stage, space: r.space, note: r.note };
  }
  return { urls: rows.map((r) => r.url), status, hasToken: !!env.HF_TOKEN };
}

const PAGE = `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ping Manager</title>
<style>
body{font-family:sans-serif;background:#0f1117;color:#e6e6e6;max-width:640px;margin:auto;padding:16px}
input{width:100%;padding:10px;border-radius:8px;border:1px solid #333;background:#181b24;color:#fff;box-sizing:border-box}
button{padding:10px 14px;border:0;border-radius:8px;background:#3b82f6;color:#fff;margin:8px 8px 8px 0}
button.d{background:#b91c1c;padding:6px 10px;margin:0}
.row{border:1px solid #2a2f3a;border-radius:8px;padding:10px;margin:8px 0;word-break:break-all}
.ok{color:#4ade80}.bad{color:#f87171}.s{font-size:12px;color:#9aa}
</style></head><body>
<h2>Ping Manager</h2>
<div class="s" id="tk"></div>
<input id="u" placeholder="https://user-space.hf.space/health">
<button onclick="add()">Add</button><button onclick="run()">Ping now</button>
<div id="l"></div>
<script>
const esc=x=>String(x).replace(/[&<>]/g,'');
async function api(p,b){const r=await fetch(p,b?{method:'POST',body:JSON.stringify(b)}:{});return r.json()}
function draw(d){const l=document.getElementById('l');l.textContent='';
document.getElementById('tk').textContent=d.hasToken?'HF token: laga hai (auto-restart ON)':'HF token: nahi laga (sirf ping)';
if(!d.urls.length){l.textContent='Koi URL nahi hai.';return}
for(const u of d.urls){const s=d.status[u];const row=document.createElement('div');row.className='row';
const a=document.createElement('div');a.textContent=u;row.appendChild(a);
const t=document.createElement('div');t.className='s';
if(s){const ok=s.code>=200&&s.code<400;t.innerHTML='<span class="'+(ok?'ok':'bad')+'">'+(s.code||'ERR')+'</span> · '+s.ms+' ms · '+new Date(s.at).toLocaleString()+(s.stage?' · stage: <b>'+esc(s.stage)+'</b>':'')+(s.space?' · '+esc(s.space):'')+(s.err?' · '+esc(s.err):'')+(s.note?' · '+esc(s.note):'')}
else t.textContent='abhi ping nahi hui';
row.appendChild(t);const b=document.createElement('button');b.className='d';b.textContent='Delete';
b.onclick=async()=>draw(await api('/api/del',{url:u}));row.appendChild(b);l.appendChild(row)}}
async function load(){draw(await api('/api/list'))}
async function add(){const i=document.getElementById('u');const d=await api('/api/add',{url:i.value.trim()});if(d.error)alert(d.error);else{i.value='';draw(d)}}
async function run(){draw(await api('/api/run',{}))}
load();
</script></body></html>`;

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(ensure(env).then(() => runPings(env)));
  },

  async fetch(req, env) {
    const url = new URL(req.url);

    if (url.pathname === "/health") return new Response("ok");

    if (!authed(req, env)) {
      return new Response("Login required", {
        status: 401,
        headers: { "WWW-Authenticate": 'Basic realm="Ping Manager"' },
      });
    }
    await ensure(env);

    if (url.pathname === "/" && req.method === "GET") {
      return new Response(PAGE, { headers: { "Content-Type": "text/html; charset=utf-8" } });
    }

    if (url.pathname === "/api/list") return json(await snap(env));

    if (req.method !== "POST") return new Response("not found", { status: 404 });

    if (url.pathname === "/api/add") {
      const { url: u } = await req.json();
      if (!/^https?:\/\/[^\s]+$/i.test(u || "")) return json({ error: "URL https:// se shuru hona chahiye" }, 400);
      const rows = await getRows(env);
      if (rows.some((r) => r.url === u)) return json({ error: "Ye URL pehle se hai" }, 400);
      if (rows.length >= MAX_URLS) return json({ error: "Limit " + MAX_URLS + " URL" }, 400);
      await env.DB.prepare("INSERT INTO pings(url, added_at) VALUES(?,?)").bind(u, Date.now()).run();
      return json(await snap(env));
    }

    if (url.pathname === "/api/del") {
      const { url: u } = await req.json();
      await env.DB.prepare("DELETE FROM pings WHERE url=?").bind(u).run();
      return json(await snap(env));
    }

    if (url.pathname === "/api/run") {
      return json(await snap(env, await runPings(env)));
    }

    return new Response("not found", { status: 404 });
  },
};
