// Tiện ích dùng chung: i18n, gọi API, hình học vùng, đường dẫn đối tượng.

export const I18N = { lang: "vi", dict: {}, fallback: {} };

export async function loadLang(lang) {
  const get = async (l) => (await fetch(`/static/i18n/${l}.json`, { cache: "no-cache" })).json();
  I18N.fallback = await get("vi");
  I18N.dict = lang === "vi" ? I18N.fallback : await get(lang).catch(() => I18N.fallback);
  I18N.lang = lang;
  document.documentElement.lang = lang;
}

export function t(key, vars) {
  let s = I18N.dict[key] ?? I18N.fallback[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, v);
  return s;
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : detail?.message || JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

export async function api(method, url, body, opts = {}) {
  const init = { method, headers: {}, signal: opts.signal, credentials: "same-origin" };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const r = await fetch(url, init);
  if (r.status === 401) {
    window.dispatchEvent(new CustomEvent("vvb-session-expired"));
    throw new ApiError(401, t("err.session"));
  }
  if (opts.raw) {
    if (!r.ok) throw new ApiError(r.status, await r.text());
    return r;
  }
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new ApiError(r.status, data?.detail ?? data);
  return data;
}

// ---- Hình học: bản JS của vvb/geometry.py (giữ đồng bộ) ----
const evenFloor = (v) => Math.floor(v / 2) * 2;
const evenRound = (v) => Math.round(v / 2) * 2;

export function clampRect(x, y, w, h, W, H) {
  let xi = evenFloor(x), yi = evenFloor(y), wi = Math.max(2, evenRound(w)), hi = Math.max(2, evenRound(h));
  if (xi < 0) { wi += xi; xi = 0; }
  if (yi < 0) { hi += yi; yi = 0; }
  if (xi + wi > W) wi = W - xi;
  if (yi + hi > H) hi = H - yi;
  wi = Math.max(2, evenFloor(wi)); hi = Math.max(2, evenFloor(hi));
  xi = Math.min(xi, W - wi); yi = Math.min(yi, H - hi);
  return { x: xi, y: yi, w: wi, h: hi };
}

export function regionRect(r, W, H) {
  const p = r.preset, s = r.split ?? 0.5;
  if (!p) return clampRect((r.x ?? 0) * W, (r.y ?? 0) * H, (r.w ?? 1) * W, (r.h ?? 1) * H, W, H);
  if (p === "full") return { x: 0, y: 0, w: W, h: H };
  if (p === "bottom") { const y = evenRound(H * s); return clampRect(0, y, W, H - y, W, H); }
  if (p === "top") return clampRect(0, 0, W, H * s, W, H);
  if (p === "left") return clampRect(0, 0, W * s, H, W, H);
  if (p === "right") { const x = evenRound(W * s); return clampRect(x, 0, W - x, H, W, H); }
  if (p === "center_box") { const w = W * r.size, h = H * r.size; return clampRect((W - w) / 2, (H - h) / 2, w, h, W, H); }
  if (p === "pip_corner") {
    const w = W * r.size, h = (w * H) / W, m = r.margin * W;
    const corner = r.corner || "bottom_right";
    const x = corner.includes("left") ? m : W - m - w;
    const y = corner.includes("top") ? m : H - m - h;
    return clampRect(x, y, w, h, W, H);
  }
  return { x: 0, y: 0, w: W, h: H };
}

export function protectRect(p, W, H) {
  return clampRect(p.x * W, p.y * H, p.w * W, p.h * H, W, H);
}

// ---- Đường dẫn trong object: "timeline.0.region.split" ----
export function getPath(obj, path) {
  return path.split(".").reduce((o, k) => (o == null ? undefined : o[k]), obj);
}

export function setPath(obj, path, value) {
  const ks = path.split(".");
  let o = obj;
  for (let i = 0; i < ks.length - 1; i++) {
    if (o[ks[i]] == null) o[ks[i]] = /^\d+$/.test(ks[i + 1]) ? [] : {};
    o = o[ks[i]];
  }
  o[ks[ks.length - 1]] = value;
}

export const clone = (o) => (o == null ? o : JSON.parse(JSON.stringify(o)));

export function debounce(fn, ms) {
  let h;
  return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); };
}

export function fmtDuration(sec) {
  if (sec == null || !isFinite(sec)) return "—";
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  if (h) return `${h}g ${String(m).padStart(2, "0")}p`;
  if (m) return `${m}p ${String(s).padStart(2, "0")}s`;
  return `${s}s`;
}

export function fmtBytes(b) {
  if (!b) return "0 MB";
  const gb = b / 1024 ** 3;
  return gb >= 1 ? `${gb.toFixed(1)} GB` : `${Math.max(1, Math.round(b / 1024 ** 2))} MB`;
}

export function baseName(p) {
  return (p || "").split(/[\\/]/).filter(Boolean).pop() || p || "";
}

export function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = "sine"; o.frequency.value = 880;
    g.gain.setValueAtTime(0.0001, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.5);
    o.connect(g).connect(ctx.destination);
    o.start(); o.stop(ctx.currentTime + 0.55);
  } catch (_) { /* không có audio */ }
}
