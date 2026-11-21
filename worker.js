// Cloudflare Worker: Ping Manager (D1) - URL ping + HF token check/restart
// Sab kuch admin page se: URLs, HF token, password. Dashboard me kuch daalna zaroori nahi.
// D1 binding name : DB   (tables apne aap ban jaate hain)
// Optional        : ADMIN_PASS / HF_TOKEN secrets (backup ke taur par, panel wale ko priority milti hai)
// Cron trigger    : */5 * * * *

const UA =
  "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36";
const MAX_URLS = 15; // free plan: ek run me 50 subrequest; har HF URL = ping + runtime check (+restart)
const RESTART_COOLDOWN = 30 * 60 * 1000; // ek Space ko 30 min me ek hi baar restart
const RESTART_STAGES = ["SLEEPING", "RUNTIME_ERROR", "STOPPED"];
const HF = "https://huggingface.co";
const SESSION_MS = 30 * 24 * 3600 * 1000;
const enc = new TextEncoder();

// ---------- db ----------
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

const metaGet = async (env, k) => (await env.DB.prepare("SELECT v FROM meta WHERE k=?").bind(k).first())?.v ?? null;
const metaSet = (env, k, v) => env.DB.prepare("INSERT OR REPLACE INTO meta(k,v,exp) VALUES(?,?,NULL)").bind(k, v).run();
const metaDel = (env, k) => env.DB.prepare("DELETE FROM meta WHERE k=?").bind(k).run();

async function getRows(env) {
  return (await env.DB.prepare("SELECT * FROM pings ORDER BY added_at").all()).results;
}

// ---------- auth (password + cookie session) ----------
async function hmacHex(key, msg) {
  const k = await crypto.subtle.importKey("raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const s = await crypto.subtle.sign("HMAC", k, enc.encode(msg));
  return [...new Uint8Array(s)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function timingEq(a, b) {
  if (a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return d === 0;
}

async function sessKey(env) {
  let k = await metaGet(env, "sess_key");
  if (!k) {
    k = [...crypto.getRandomValues(new Uint8Array(32))].map((b) => b.toString(16).padStart(2, "0")).join("");
    await metaSet(env, "sess_key", k);
  }
  return k;
}

async function passConfigured(env) {
  return !!(await metaGet(env, "pass_hash")) || !!env.ADMIN_PASS;
}

async function checkPassword(env, pw) {
  pw = String(pw || "");
  const stored = await metaGet(env, "pass_hash");
  if (stored) return timingEq(await hmacHex(await sessKey(env), "pw:" + pw), stored);
  if (env.ADMIN_PASS) return timingEq(pw, env.ADMIN_PASS);
  return false;
}

async function passId(env) {
  return (await metaGet(env, "pass_hash")) || "env:" + (env.ADMIN_PASS || "");
}

async function makeCookie(env) {
  const exp = String(Date.now() + SESSION_MS);
  const sig = await hmacHex(await sessKey(env), "sess|" + exp + "|" + (await passId(env)));
  return "sid=" + exp + "." + sig + "; Path=/; Max-Age=" + SESSION_MS / 1000 + "; HttpOnly; Secure; SameSite=Strict";
}

async function isAuthed(req, env) {
  const c = (req.headers.get("Cookie") || "").split(/;\s*/).find((x) => x.startsWith("sid="));
  if (!c) return false;
  const [exp, sig] = c.slice(4).split(".");
  if (!exp || !sig || Number(exp) < Date.now()) return false;
  const good = await hmacHex(await sessKey(env), "sess|" + exp + "|" + (await passId(env)));
  return timingEq(sig, good);
}

async function setPassword(env, pw) {
  await metaSet(env, "pass_hash", await hmacHex(await sessKey(env), "pw:" + pw));
}

// ---------- HF ----------
async function getToken(env) {
  return (await metaGet(env, "hf_token")) || env.HF_TOKEN || "";
}

const hfFetch = (token, path, init = {}) =>
  fetch(HF + path, {
    ...init,
    headers: { Authorization: "Bearer " + token, "User-Agent": "ping-manager" },
    signal: AbortSignal.timeout(20000),
  });

// "owner-space-name.hf.space" -> "owner/space_name" (token wale account ke Spaces me dhundh kar)
async function resolveSpace(env, token, host) {
  const sub = host.replace(/\.hf\.space$/, "").toLowerCase();
  const norm = (s) => s.toLowerCase().replace(/[/_.]/g, "-");
  const known = await env.DB.prepare("SELECT id FROM spaces WHERE sub=?").bind(sub).first();
  if (known) return known.id;

  const cached = await env.DB.prepare("SELECT v FROM meta WHERE k='owners' AND exp>?").bind(Date.now()).first();
  let owners = cached ? JSON.parse(cached.v) : null;
  if (!owners) {
    const r = await hfFetch(token, "/api/whoami-v2");
    if (!r.ok) throw new Error("token check fail (" + r.status + ")");
    const w = await r.json();
    owners = [w.name, ...(w.orgs || []).map((o) => o.name)].filter(Boolean);
    await env.DB.prepare("INSERT OR REPLACE INTO meta(k,v,exp) VALUES('owners',?,?)")
      .bind(JSON.stringify(owners), Date.now() + 86400000)
      .run();
  }
  for (const o of owners) {
    if (!sub.startsWith(norm(o) + "-")) continue;
    const r = await hfFetch(token, "/api/spaces?author=" + encodeURIComponent(o) + "&limit=500");
    if (!r.ok) continue;
    const hit = (await r.json()).find((s) => norm(s.id) === sub);
    if (hit) {
      await env.DB.prepare("INSERT OR REPLACE INTO spaces(sub,id) VALUES(?,?)").bind(sub, hit.id).run();
      return hit.id;
    }
  }
  throw new Error("Space nahi mila (token usi account ka ho jisme ye Space hai)");
}

async function hfCheck(env, token, u, st) {
  let host = "";
  try { host = new URL(u).hostname; } catch { return; }
  if (!host.endsWith(".hf.space") || !token) return;
  try {
    const id = await resolveSpace(env, token, host);
    st.space = id;
    const r = await hfFetch(token, "/api/spaces/" + id + "/runtime");
    if (!r.ok) { st.note = "runtime check " + r.status; return; }
    st.stage = (await r.json()).stage;
    if (RESTART_STAGES.includes(st.stage)) {
      if (Date.now() - (st.restartedAt || 0) > RESTART_COOLDOWN) {
        const rr = await hfFetch(token, "/api/spaces/" + id + "/restart", { method: "POST" });
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

// ---------- pings ----------
async function runPings(env) {
  const rows = await getRows(env);
  const token = await getToken(env);
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
      await hfCheck(env, token, row.url, st);
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

const json = (o, status = 200, headers = {}) =>
  new Response(JSON.stringify(o), { status, headers: { "Content-Type": "application/json", ...headers } });

async function snap(env, rows) {
  rows = rows || (await getRows(env));
  const status = {};
  for (const r of rows) {
    if (r.at) status[r.url] = { code: r.code, ms: r.ms, at: r.at, err: r.err, stage: r.stage, space: r.space, note: r.note };
  }
  return { urls: rows.map((r) => r.url), status, hasToken: !!(await getToken(env)) };
}

async function settings(env) {
  const t = await metaGet(env, "hf_token");
  const e = env.HF_TOKEN || "";
  const tok = t || e;
  return {
    hasToken: !!tok,
    hint: tok ? "..." + tok.slice(-4) : "",
    tokenFrom: t ? "panel" : e ? "secret" : "",
    passFrom: (await metaGet(env, "pass_hash")) ? "panel" : "secret",
  };
}

// ---------- page ----------
const PAGE = `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Ping Manager</title>
<style>
body{font-family:sans-serif;background:#0f1117;color:#e6e6e6;max-width:640px;margin:auto;padding:16px}
input{width:100%;padding:10px;border-radius:8px;border:1px solid #333;background:#181b24;color:#fff;box-sizing:border-box;margin:4px 0}
button{padding:10px 14px;border:0;border-radius:8px;background:#3b82f6;color:#fff;margin:8px 8px 8px 0}
button.d{background:#b91c1c;padding:6px 10px;margin:0}button.g{background:#374151}
.row{border:1px solid #2a2f3a;border-radius:8px;padding:10px;margin:8px 0;word-break:break-all}
.ok{color:#4ade80}.bad{color:#f87171}.s{font-size:12px;color:#9aa}
.box{border:1px solid #2a2f3a;border-radius:10px;padding:12px;margin:16px 0}
</style></head><body>
<h2>Ping Manager</h2>
<div id="login" style="display:none">
<div class="s" id="lt"></div>
<input id="pw" type="password" placeholder="Password" autocomplete="current-password">
<button id="lb" onclick="go()">Login</button>
</div>
<div id="admin" style="display:none">
<button class="g" onclick="logout()">Logout</button>
<div class="s" id="tk"></div>
<input id="u" placeholder="https://user-space.hf.space/health">
<button onclick="add()">Add</button><button onclick="run()">Ping now</button>
<div id="l"></div>
<div class="box"><b>HF token</b>
<div class="s" id="ts"></div>
<input id="tkn" type="password" placeholder="hf_... (khali chhodke save karo = hata do)" autocomplete="off">
<button onclick="saveTok()">Save token</button></div>
<div class="box"><b>Password badlo</b>
<input id="cur" type="password" placeholder="Purana password" autocomplete="current-password">
<input id="np" type="password" placeholder="Naya password (kam se kam 8 akshar)" autocomplete="new-password">
<button onclick="chPw()">Change password</button></div>
</div>
<script>
const $=id=>document.getElementById(id);
const esc=x=>String(x).replace(/[&<>]/g,'');
let mode='login';
async function api(p,b){const r=await fetch(p,b!==undefined?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:{});let d={};try{d=await r.json()}catch(e){}return d}
function show(w){$('login').style.display=w==='login'?'block':'none';$('admin').style.display=w==='admin'?'block':'none'}
async function boot(){const s=await api('/api/state');
if(s.authed){show('admin');load();loadSet()}
else{show('login');mode=s.configured?'login':'setup';
$('lt').textContent=s.configured?'Login karo':'Pehli baar: naya password set karo (kam se kam 8 akshar)';
$('lb').textContent=s.configured?'Login':'Set password'}}
async function go(){const d=await api(mode==='login'?'/api/login':'/api/setup',{password:$('pw').value});
if(d.error)alert(d.error);else{$('pw').value='';boot()}}
async function logout(){await api('/api/logout',{});boot()}
function draw(d){const l=$('l');l.textContent='';
$('tk').textContent=d.hasToken?'HF token: laga hai (auto-restart ON)':'HF token: nahi laga (sirf ping)';
if(!d.urls||!d.urls.length){l.textContent='Koi URL nahi hai.';return}
for(const u of d.urls){const s=d.status[u];const row=document.createElement('div');row.className='row';
const a=document.createElement('div');a.textContent=u;row.appendChild(a);
const t=document.createElement('div');t.className='s';
if(s){const ok=s.code>=200&&s.code<400;t.innerHTML='<span class="'+(ok?'ok':'bad')+'">'+(s.code||'ERR')+'</span> · '+s.ms+' ms · '+new Date(s.at).toLocaleString()+(s.stage?' · stage: <b>'+esc(s.stage)+'</b>':'')+(s.space?' · '+esc(s.space):'')+(s.err?' · '+esc(s.err):'')+(s.note?' · '+esc(s.note):'')}
else t.textContent='abhi ping nahi hui';
row.appendChild(t);const b=document.createElement('button');b.className='d';b.textContent='Delete';
b.onclick=async()=>draw(await api('/api/del',{url:u}));row.appendChild(b);l.appendChild(row)}}
async function load(){const d=await api('/api/list');if(d.error){boot();return}draw(d)}
async function loadSet(){const s=await api('/api/settings');
$('ts').textContent=s.hasToken?('Laga hai: '+s.hint+' ('+(s.tokenFrom==='panel'?'panel se':'Cloudflare secret se')+')'):'Abhi koi token nahi.'}
async function add(){const i=$('u');const d=await api('/api/add',{url:i.value.trim()});if(d.error)alert(d.error);else{i.value='';draw(d)}}
async function run(){const d=await api('/api/run',{});if(d.error)alert(d.error);else draw(d)}
async function saveTok(){const d=await api('/api/token',{token:$('tkn').value.trim()});
if(d.error)alert(d.error);else{$('tkn').value='';alert(d.removed?'Token hata diya':'Token save ho gaya ('+d.name+')');loadSet();load()}}
async function chPw(){const d=await api('/api/password',{current:$('cur').value,password:$('np').value});
if(d.error)alert(d.error);else{$('cur').value='';$('np').value='';alert('Password badal gaya')}}
boot();
</script></body></html>`;

// ---------- routes ----------
export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(ensure(env).then(() => runPings(env)));
  },

  async fetch(req, env) {
    const p = new URL(req.url).pathname;

    if (p === "/health") return new Response("ok");
    await ensure(env);

    if (p === "/" && req.method === "GET") {
      return new Response(PAGE, { headers: { "Content-Type": "text/html; charset=utf-8" } });
    }
    if (p === "/api/state") {
      return json({ configured: await passConfigured(env), authed: await isAuthed(req, env) });
    }
    if (req.method !== "POST" && p !== "/api/list" && p !== "/api/settings") {
      return new Response("not found", { status: 404 });
    }

    // --- login / setup (public) ---
    if (p === "/api/setup") {
      if (await passConfigured(env)) return json({ error: "Password pehle se set hai" }, 403);
      const { password } = await req.json();
      if (!password || password.length < 8) return json({ error: "Password kam se kam 8 akshar ka rakho" }, 400);
      await setPassword(env, password);
      return json({ ok: true }, 200, { "Set-Cookie": await makeCookie(env) });
    }
    if (p === "/api/login") {
      const L = JSON.parse((await metaGet(env, "lock")) || '{"n":0,"until":0}');
      if (L.until > Date.now()) {
        return json({ error: "Bahut galat try ho gaye. " + Math.ceil((L.until - Date.now()) / 60000) + " minute baad try karo" }, 429);
      }
      const { password } = await req.json();
      if (await checkPassword(env, password)) {
        if (L.n) await metaDel(env, "lock");
        return json({ ok: true }, 200, { "Set-Cookie": await makeCookie(env) });
      }
      L.n += 1;
      if (L.n >= 5) { L.until = Date.now() + 10 * 60000; L.n = 0; }
      await metaSet(env, "lock", JSON.stringify(L));
      return json({ error: "Password galat hai" }, 401);
    }

    // --- baaki sab login ke baad ---
    if (!(await isAuthed(req, env))) return json({ error: "login chahiye" }, 401);

    if (p === "/api/logout") {
      return json({ ok: true }, 200, { "Set-Cookie": "sid=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict" });
    }
    if (p === "/api/list") return json(await snap(env));
    if (p === "/api/settings") return json(await settings(env));

    if (p === "/api/token") {
      const { token } = await req.json();
      if (!token) {
        await metaDel(env, "hf_token");
        await metaDel(env, "owners");
        return json({ ok: true, removed: true });
      }
      let r;
      try { r = await hfFetch(token, "/api/whoami-v2"); } catch { return json({ error: "HF se connect nahi hua" }, 502); }
      if (!r.ok) return json({ error: "Token galat ya expire hai (" + r.status + ")" }, 400);
      const w = await r.json();
      await metaSet(env, "hf_token", token);
      await metaDel(env, "owners");
      return json({ ok: true, name: w.name });
    }

    if (p === "/api/password") {
      const { current, password } = await req.json();
      if (!(await checkPassword(env, current))) return json({ error: "Purana password galat hai" }, 401);
      if (!password || password.length < 8) return json({ error: "Naya password kam se kam 8 akshar ka rakho" }, 400);
      await setPassword(env, password);
      return json({ ok: true }, 200, { "Set-Cookie": await makeCookie(env) });
    }

    if (p === "/api/add") {
      const { url: u } = await req.json();
      if (!/^https?:\/\/[^\s]+$/i.test(u || "")) return json({ error: "URL https:// se shuru hona chahiye" }, 400);
      const rows = await getRows(env);
      if (rows.some((r) => r.url === u)) return json({ error: "Ye URL pehle se hai" }, 400);
      if (rows.length >= MAX_URLS) return json({ error: "Limit " + MAX_URLS + " URL" }, 400);
      await env.DB.prepare("INSERT INTO pings(url, added_at) VALUES(?,?)").bind(u, Date.now()).run();
      return json(await snap(env));
    }

    if (p === "/api/del") {
      const { url: u } = await req.json();
      await env.DB.prepare("DELETE FROM pings WHERE url=?").bind(u).run();
      return json(await snap(env));
    }

    if (p === "/api/run") return json(await snap(env, await runPings(env)));

    return new Response("not found", { status: 404 });
  },
};
