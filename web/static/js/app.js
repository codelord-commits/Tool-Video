// Video Variant Builder — Alpine component chính.
import { api, baseName, beep, clone, debounce, fmtBytes, fmtDuration, getPath, loadLang, protectRect,
         regionRect, setPath, t as tr } from "./lib.js";
import { buildFields } from "./schema.js";

const LOG_ROW = 22;
const SEG_KEYS = {
  region: null,
  duration: ["duration_mode", "clip_start", "min_speed", "max_speed", "speed", "trim", "optional", "transition_in"],
  audio: ["audio", "voice_slot"],
};
const SLOT_ICON = { per_group: "film", shared: "file-video", pool: "layers" };

function app() {
  return {
    // ------------------------------------------------------------ trạng thái
    ready: false, sys: null, settings: {}, theme: "system", lang: "vi", schema: null,
    presets: [], presetId: "", preset: null, savedJson: "", builtin: true, presetErrors: [],
    project: "", paths: {}, outDir: "",
    plan: null, planLoading: false, planError: "", full: null, checking: false, showIssues: false,
    groupSel: {}, clipSel: {}, manual: {},
    pv: { group: "", clip: "", seg: 0, t: 1, dur: 0, W: 1080, H: 1920, url: "", beforeUrl: "", loading: false,
          error: "", warnings: [], grid: false, safe: false, compare: false, cmp: 50, videoUrl: "", videoLoading: false },
    sel: "region", drag: null,
    optTab: "region", optionsOpen: false, mtab: "preview", jsonDraft: { slots: "", timeline: "" }, jsonErr: "",
    job: { state: "idle", summary: {}, tasks: {}, percent: 0, eta: null, workers: 0, out_dir: "" },
    logs: [], logFilter: "all", logTop: 0, logH: 200, logStick: true,
    modal: null, fb: { kind: "dir", target: "", path: "", data: null, roots: [], error: "", typed: "" },
    dialog: { title: "", text: "", input: null, ok: "", danger: false, resolve: null },
    filesSlot: null, issueDetail: null, toasts: [], unfinished: null, menu: "", expired: false,
    _pvAbort: null, _ws: null, _fieldCache: {}, _toastId: 0,

    i18nRev: 0,
    // this.t() phụ thuộc i18nRev để Alpine vẽ lại khi đổi ngôn ngữ
    t(key, vars) { return this.i18nRev >= 0 ? tr(key, vars) : key; },
    fmtDuration, fmtBytes, baseName,

    // ------------------------------------------------------------ khởi động
    async init() {
      this.sys = await api("GET", "/api/system").catch(() => null);
      this.settings = this.sys?.settings || {};
      this.lang = this.settings.lang || "vi";
      await loadLang(this.lang);
      this.i18nRev++;
      this.applyTheme(this.settings.theme || "system");
      this.schema = await api("GET", "/api/schema");
      this.presets = await api("GET", "/api/presets");
      const last = this.settings.last_job || {};
      const pid = last.preset_name && this.presets.some((p) => p.id === last.preset_name) ? last.preset_name
        : (this.presets.find((p) => p.id === "palm_bottom") || this.presets[0])?.id;
      if (pid) await this.loadPreset(pid);
      if (last.paths) { this.paths = { ...last.paths }; this.project = last.project || ""; this.outDir = last.out_dir || ""; }
      this.ready = true;

      const refresh = debounce(() => this.refreshPlan(), 400);
      this.$watch(() => JSON.stringify([this.paths, this.preset?.slots, this.preset?.groups, this.preset?.combine,
        this.manual, this.outDir, this.preset?.output?.folder_template, this.preset?.output?.name_template,
        this.groupFilter(), this.clipFilter()]), refresh);
      const pv = debounce(() => this.loadPreview(), 300);
      this.$watch(() => JSON.stringify([this.preset?.timeline, this.preset?.output?.resolution, this.paths,
        this.manual, this.pv.group, this.pv.clip, this.pv.seg, Math.round(this.pv.t * 30)]), pv);
      this.$watch(() => this.pv.compare, (v) => v && this.loadPreview());
      this.$watch(() => this.optTab + "|" + this.pv.seg, () => this.syncJsonDraft());
      this.connectWs();
      window.addEventListener("vvb-session-expired", () => { this.expired = true; });
      window.addEventListener("beforeunload", (e) => {
        if (this.dirty || this.isRunning) { e.preventDefault(); e.returnValue = ""; }
      });
      matchMedia("(prefers-color-scheme: light)").addEventListener("change", () => this.applyTheme(this.theme));
      this.syncJsonDraft();
      if (Object.keys(this.paths).length) this.refreshPlan();
    },

    // ------------------------------------------------------------ giao diện chung
    applyTheme(th) {
      this.theme = th;
      if (th === "system") document.documentElement.removeAttribute("data-theme");
      else document.documentElement.setAttribute("data-theme", th);
    },
    setTheme(th) { this.applyTheme(th); this.menu = ""; this.saveSettings({ theme: th }); },
    get themeIcon() { return this.theme === "light" ? "sun" : this.theme === "dark" ? "moon" : "monitor"; },
    async setLang(l) { await loadLang(l); this.lang = l; this.i18nRev++; this._fieldCache = {}; this.menu = ""; this.saveSettings({ lang: l }); },
    saveSettings(d) { api("PUT", "/api/settings", d).then((s) => (this.settings = s)).catch(() => {}); },
    icon(name) { return `/static/vendor/icons.svg#i-${name}`; },
    toast(kind, msg, ms = 4000) {
      const id = ++this._toastId;
      this.toasts.push({ id, kind, msg });
      setTimeout(() => (this.toasts = this.toasts.filter((x) => x.id !== id)), ms);
    },
    ask({ title, text = "", input = null, ok = this.t("common.ok"), danger = false }) {
      return new Promise((resolve) => {
        this.dialog = { title, text, input, ok, danger, resolve };
        this.modal = "dialog";
        this.$nextTick(() => document.querySelector("#dialog-input, #dialog-ok")?.focus());
      });
    },
    closeDialog(val) {
      const r = this.dialog.resolve;
      this.modal = null;
      r && r(val);
    },
    onKey(e) {
      const tag = (e.target.tagName || "").toLowerCase();
      const typing = ["input", "textarea", "select"].includes(tag);
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); this.savePreset(); }
      else if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); this.start(); }
      else if (e.key === "Escape") {
        if (this.modal === "dialog") this.closeDialog(null);
        else if (this.modal) this.modal = null;
        this.menu = "";
      } else if (e.key === " " && !typing && this.pv.videoUrl) {
        const v = document.querySelector("#pv-video");
        if (v) { e.preventDefault(); v.paused ? v.play() : v.pause(); }
      }
    },

    // ------------------------------------------------------------ preset
    get dirty() { return !!this.preset && JSON.stringify(this.preset) !== this.savedJson; },
    get presetName() { return this.preset?.name || "—"; },
    async loadPreset(id) {
      const d = await api("GET", `/api/presets/${encodeURIComponent(id)}`);
      this.presetId = d.id; this.builtin = d.builtin;
      this.preset = d.preset; this.savedJson = JSON.stringify(d.preset);
      this._fieldCache = {}; this.sel = "region";
      this.pv.seg = Math.max(0, this.preset.timeline.findIndex((s) => s.kind === "composite"));
      this.syncJsonDraft();
    },
    async selectPreset(id) {
      this.menu = "";
      if (id === this.presetId) return;
      if (this.dirty && !(await this.ask({ title: this.t("preset.confirmDiscard"), danger: true }))) return;
      await this.loadPreset(id);
      this.saveSettings({ last_job: { ...(this.settings.last_job || {}), preset_name: id } });
    },
    async savePreset() {
      this.menu = "";
      if (!this.preset) return;
      if (this.builtin) return this.saveAs();
      await this._put(this.presetId);
      this.toast("ok", this.t("preset.saved"));
    },
    async _put(id) {
      try {
        const r = await api("PUT", `/api/presets/${encodeURIComponent(id)}`, { preset: this.preset });
        this.presetId = r.id; this.builtin = false; this.savedJson = JSON.stringify(this.preset);
        this.presets = await api("GET", "/api/presets");
        return true;
      } catch (e) { this.showPresetError(e); return false; }
    },
    showPresetError(e) {
      const errs = e.detail?.errors;
      this.presetErrors = errs || [];
      this.toast("err", errs ? `${this.t("preset.invalid")}: ${errs.map((x) => `${x.loc}: ${x.msg}`).join("; ")}` : e.message, 8000);
    },
    async saveAs(base) {
      this.menu = "";
      const name = await this.ask({ title: this.t("preset.saveAs"), text: this.builtin ? this.t("preset.builtinReadonly") : "",
                                    input: base || `${this.preset.name} (bản của tôi)`, ok: this.t("common.save") });
      if (!name) return;
      const { id } = await api("POST", "/api/presets/slug", { name });
      this.preset.name = name;
      if (await this._put(id)) this.toast("ok", this.t("preset.saved"));
    },
    duplicate() { this.saveAs(`${this.preset.name} (bản sao)`); },
    async renamePreset() {
      this.menu = "";
      if (this.builtin) return this.saveAs();
      const name = await this.ask({ title: this.t("preset.rename"), input: this.preset.name, ok: this.t("common.save") });
      if (!name || name === this.preset.name) return;
      const old = this.presetId;
      const { id } = await api("POST", "/api/presets/slug", { name });
      this.preset.name = name;
      if (await this._put(id)) { await api("DELETE", `/api/presets/${old}`).catch(() => {}); this.presets = await api("GET", "/api/presets"); }
    },
    async deletePreset() {
      this.menu = "";
      if (this.builtin) return;
      if (!(await this.ask({ title: this.t("preset.confirmDelete", { name: this.preset.name }), danger: true, ok: this.t("preset.delete") }))) return;
      await api("DELETE", `/api/presets/${this.presetId}`);
      this.presets = await api("GET", "/api/presets");
      this.toast("ok", this.t("preset.deleted"));
      await this.loadPreset((this.presets.find((p) => p.builtin) || this.presets[0]).id);
    },
    exportPreset() {
      this.menu = "";
      const blob = new Blob([JSON.stringify(this.preset, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${this.presetId || "preset"}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    },
    async importPreset(ev) {
      const file = ev.target.files?.[0];
      ev.target.value = "";
      if (!file) return;
      try {
        const data = JSON.parse(await file.text());
        const v = await api("POST", "/api/presets/validate", { preset: data });
        if (!v.ok) throw { detail: { errors: v.errors } };
        const { id } = await api("POST", "/api/presets/slug", { name: data.name || file.name.replace(/\.json$/i, "") });
        await api("PUT", `/api/presets/${id}`, { preset: data });
        this.presets = await api("GET", "/api/presets");
        await this.loadPreset(id);
        this.toast("ok", this.t("preset.imported"));
      } catch (e) {
        if (e instanceof SyntaxError) this.toast("err", `${this.t("opt.jsonError")}: ${e.message}`);
        else this.showPresetError(e);
      }
    },

    // ------------------------------------------------------------ nguồn
    get slotList() {
      if (!this.preset) return [];
      return Object.entries(this.preset.slots)
        .filter(([, s]) => !(s.type === "pool" && this.preset.combine.mode === "no_pool"))
        .map(([name, s]) => ({ name, ...s, icon: SLOT_ICON[s.type], label: s.label || name }));
    },
    slotScan(name) { return this.plan?.scans?.[name]; },
    slotState(sl) {
      const sc = this.slotScan(sl.name);
      if (!this.paths[sl.name]) return sl.required ? "missing" : "empty";
      if (!sc) return "pending";
      if (sc.error) return "error";
      return sc.warnings?.length ? "warn" : "ok";
    },
    slotTotal(name) {
      const sc = this.slotScan(name);
      const media = this.full?.media;
      if (!sc || !media) return null;
      return sc.files.reduce((s, f) => s + (media[f]?.video_duration || 0), 0);
    },
    async openBrowser(target, kind = "dir") {
      this.fb = { ...this.fb, kind, target, error: "", typed: "" };
      this.modal = "fb";
      if (!this.fb.roots.length) this.fb.roots = await api("GET", "/api/fs/roots").catch(() => []);
      const cur = target === "project" ? this.project : target === "out" ? this.outDir : this.paths[target];
      const start = cur || this.project || this.settings.recent_projects?.[0] || this.fb.roots[0]?.path;
      await this.fbLoad(start);
      this.$nextTick(() => document.querySelector(".fb-list button")?.focus());
    },
    async fbLoad(path) {
      if (!path) return;
      try {
        this.fb.data = await api("GET", `/api/fs/list?path=${encodeURIComponent(path)}`);
        this.fb.path = this.fb.data.path; this.fb.typed = this.fb.data.path; this.fb.error = "";
      } catch (e) { this.fb.error = e.message; }
    },
    fbChoose(path) {
      const target = this.fb.target;
      // Người dùng dán đường dẫn rồi bấm "Chọn" ngay (chưa bấm Mở) → dùng đường dẫn đã gõ, không lấy thư mục cũ
      const typed = (this.fb.typed || "").trim();
      const chosen = path || (typed && typed !== this.fb.path ? typed : this.fb.path);
      this.modal = null;
      this.applyPath(target, chosen);
    },
    async nativePick() {
      const target = this.fb.target;
      this.modal = null;
      const r = await api("POST", "/api/fs/dialog", { kind: this.fb.kind, initial: this.fb.path }).catch(() => ({}));
      if (r.path) this.applyPath(target, r.path);
    },
    async applyPath(target, path) {
      if (target === "project") return this.setProject(path);
      if (target === "out") { this.outDir = path; return; }
      this.paths = { ...this.paths, [target]: path };
      this.saveLastJob();
    },
    async setProject(path) {
      this.project = path;
      try {
        const r = await api("POST", "/api/project/resolve", { preset: this.preset, project: path });
        this.paths = r.paths; this.outDir = r.out_dir; this.manual = {};
        this.groupSel = {}; this.clipSel = {};
        if (r.missing.length) this.toast("warn", `Chưa tự nhận được: ${r.missing.map((m) => this.preset.slots[m].label || m).join(", ")}`);
        this.saveLastJob();
        this.settings = await api("GET", "/api/settings");
      } catch (e) { this.toast("err", e.message); }
    },
    saveLastJob() {
      this.saveSettings({ last_job: { preset_name: this.presetId, paths: this.paths, out_dir: this.outDir, project: this.project } });
    },
    jobBody(extra = {}) {
      return { preset: this.preset, preset_name: this.presetId, paths: this.paths, out_dir: this.outDir || null,
               groups: this.groupFilter(), clips: this.clipFilter(), manual: this.manual, ...extra };
    },
    groupFilter() {
      const rows = this.plan?.match?.rows?.filter((r) => r.valid) || [];
      const off = rows.filter((r) => this.groupSel[r.key] === false);
      return off.length ? rows.filter((r) => this.groupSel[r.key] !== false).map((r) => r.key) : null;
    },
    clipFilter() {
      const pool = this.plan?.match?.pool || [];
      const off = pool.filter((p) => this.clipSel[p] === false);
      return off.length ? pool.filter((p) => this.clipSel[p] !== false).map((p) => baseName(p).replace(/\.[^.]+$/, "")) : null;
    },
    async refreshPlan() {
      if (!this.preset || !Object.keys(this.paths).length) { this.plan = null; return; }
      this.planLoading = true;
      try {
        // bảng ghép dựng trên toàn bộ nhóm/clip (không áp bộ lọc) để còn tick lại
        this.plan = await api("POST", "/api/plan", this.jobBody({ groups: null, clips: null, probe: false }));
        this.planError = "";
        const rows = this.plan.match?.rows || [];
        if (!rows.some((r) => r.key === this.pv.group || r.display === this.pv.group)) this.pv.group = rows.find((r) => r.valid)?.display || rows[0]?.display || "";
        const pool = this.plan.match?.pool || [];
        if (!pool.some((p) => baseName(p).startsWith(this.pv.clip + ".") )) this.pv.clip = pool[0] ? baseName(pool[0]).replace(/\.[^.]+$/, "") : "";
        this.runCheck(false);
      } catch (e) { this.planError = e.message; this.plan = null; }
      finally { this.planLoading = false; }
    },
    get matchRows() { return this.plan?.match?.rows || []; },
    get perGroupSlots() { return this.slotList.filter((s) => s.type === "per_group"); },
    get poolFiles() { return this.plan?.match?.pool || []; },
    toggleGroup(key) { this.groupSel = { ...this.groupSel, [key]: this.groupSel[key] === false }; },
    toggleClip(p) { this.clipSel = { ...this.clipSel, [p]: this.clipSel[p] === false }; },
    setAllClips(on) { const o = {}; for (const p of this.poolFiles) o[p] = on; this.clipSel = o; },
    setManual(group, slot, file) {
      const m = clone(this.manual);
      m[group] = { ...(m[group] || {}), [slot]: file };
      this.manual = m;
    },
    cellCandidates(row, slot) {
      const c = row.cells[slot];
      if (c.status === "duplicate") return c.candidates;
      return this.plan?.scans?.[slot]?.files || [];
    },
    showFiles(slot) { this.filesSlot = slot; this.modal = "files"; },
    media(path) { return this.full?.media?.[path]; },

    // ------------------------------------------------------------ preview
    get seg() { return this.preset?.timeline?.[this.pv.seg]; },
    get isComposite() { return this.seg?.kind === "composite"; },
    segLabel(s, i) {
      const k = { composite: "Ghép vùng", asset: "File", pool: "Clip pool", blank: "Màn trống" }[s.kind] || s.kind;
      const slot = s.base || s.slot || "";
      const lab = slot && this.preset.slots[slot] ? (this.preset.slots[slot].label || slot) : slot;
      return `${i + 1}. ${k}${lab ? " · " + lab : ""}`;
    },
    get canPreview() { return !!(this.plan?.match?.rows?.length); },
    async loadPreview() {
      if (!this.canPreview || !this.preset) return;
      this._pvAbort?.abort();
      const ctl = new AbortController();
      this._pvAbort = ctl;
      this.pv.loading = true;
      try {
        const body = this.jobBody({ group: this.pv.group, clip: this.pv.clip, segment: this.pv.seg, t: this.pv.t });
        const r = await api("POST", "/api/preview/frame", body, { raw: true, signal: ctl.signal });
        if (r.status === 204) return;
        const blob = await r.blob();
        if (this.pv.url) URL.revokeObjectURL(this.pv.url);
        this.pv.url = URL.createObjectURL(blob);
        this.pv.dur = parseFloat(r.headers.get("x-duration")) || 0;
        this.pv.W = parseInt(r.headers.get("x-w")) || 1080;
        this.pv.H = parseInt(r.headers.get("x-h")) || 1920;
        const w = decodeURIComponent(r.headers.get("x-warnings") || "");
        this.pv.warnings = w ? w.split("|") : [];
        this.pv.error = "";
        if (this.pv.t > this.pv.dur) this.pv.t = Math.max(0, this.pv.dur - 0.05);
        if (this.pv.compare) {
          const b = await api("POST", "/api/preview/frame", { ...body, before: true }, { raw: true, signal: ctl.signal });
          if (b.status !== 204) {
            if (this.pv.beforeUrl) URL.revokeObjectURL(this.pv.beforeUrl);
            this.pv.beforeUrl = URL.createObjectURL(await b.blob());
          }
        }
      } catch (e) {
        if (e.name !== "AbortError") this.pv.error = e.message;
      } finally {
        if (this._pvAbort === ctl) this.pv.loading = false;
      }
    },
    async play5() {
      this.pv.videoLoading = true;
      try {
        const r = await api("POST", "/api/preview/clip", this.jobBody({ group: this.pv.group, clip: this.pv.clip, seconds: 5 }));
        this.pv.videoUrl = r.url + "?v=" + Date.now();
      } catch (e) { this.toast("err", e.message); }
      finally { this.pv.videoLoading = false; }
    },

    // ------------------------------------------------------------ chỉnh vùng (SVG)
    get rects() {
      if (!this.isComposite) return [];
      const { W, H } = this.pv, s = this.seg;
      const out = [{ id: "region", kind: "region", label: this.t("preview.region"), ...regionRect(s.region, W, H) }];
      (s.protect || []).forEach((p, i) => out.push({ id: `p${i}`, kind: "protect", idx: i,
        label: p.label || `${this.t("preview.protect")} ${i + 1}`, ...protectRect(p, W, H) }));
      return out;
    },
    get selRect() { return this.rects.find((r) => r.id === this.sel) || null; },
    handles(r) {
      const hs = [["nw", r.x, r.y], ["n", r.x + r.w / 2, r.y], ["ne", r.x + r.w, r.y], ["e", r.x + r.w, r.y + r.h / 2],
                  ["se", r.x + r.w, r.y + r.h], ["s", r.x + r.w / 2, r.y + r.h], ["sw", r.x, r.y + r.h], ["w", r.x, r.y + r.h / 2]];
      return hs.map(([h, x, y]) => ({ h, x, y }));
    },
    boxStyle(r) {
      const { W, H } = this.pv;
      return `left:${(r.x / W) * 100}%;top:${(r.y / H) * 100}%;width:${(r.w / W) * 100}%;height:${(r.h / H) * 100}%`;
    },
    framePoint(e) {
      const b = this.$refs.editor.getBoundingClientRect();
      return { x: ((e.clientX - b.left) / b.width) * this.pv.W, y: ((e.clientY - b.top) / b.height) * this.pv.H };
    },
    startDrag(e, id, handle) {
      const r = this.rects.find((x) => x.id === id);
      if (!r || e.button > 0) return;
      e.preventDefault();
      this.$refs.editor.setPointerCapture(e.pointerId);
      e.currentTarget.focus?.({ preventScroll: true });
      this.sel = id;
      this.drag = { id, handle, p0: this.framePoint(e), r0: { x: r.x, y: r.y, w: r.w, h: r.h } };
    },
    onDrag(e) {
      const d = this.drag;
      if (!d) return;
      const p = this.framePoint(e);
      const dx = p.x - d.p0.x, dy = p.y - d.p0.y;
      this.applyRect(d.id, this.moveRect(d.r0, d.handle, dx, dy), d.handle);
    },
    endDrag() { this.drag = null; },
    moveRect(r0, h, dx, dy) {
      const { W, H } = this.pv, MIN = 20;
      let { x, y, w, h: hh } = r0;
      if (h === "move") {
        x = Math.min(Math.max(0, x + dx), W - w);
        y = Math.min(Math.max(0, y + dy), H - hh);
      } else {
        if (h.includes("w")) { const nx = Math.min(Math.max(0, x + dx), x + w - MIN); w += x - nx; x = nx; }
        if (h.includes("e")) w = Math.min(Math.max(MIN, w + dx), W - x);
        if (h.includes("n")) { const ny = Math.min(Math.max(0, y + dy), y + hh - MIN); hh += y - ny; y = ny; }
        if (h.includes("s")) hh = Math.min(Math.max(MIN, hh + dy), H - y);
      }
      return { x, y, w, h: hh };
    },
    applyRect(id, r, handle = "move") {
      const { W, H } = this.pv, q = (v) => Math.round(v * 10000) / 10000;
      if (id === "region") {
        const reg = this.seg.region, p = reg.preset;
        const splitEdge = { bottom: "n", top: "s", left: "e", right: "w" }[p];
        if (splitEdge && handle === splitEdge) {
          const clampS = (v) => Math.min(0.95, Math.max(0.05, q(v)));
          if (p === "bottom") reg.split = clampS(r.y / H);
          if (p === "top") reg.split = clampS((r.y + r.h) / H);
          if (p === "left") reg.split = clampS((r.x + r.w) / W);
          if (p === "right") reg.split = clampS(r.x / W);
        } else {
          Object.assign(reg, { preset: null, x: q(r.x / W), y: q(r.y / H), w: q(r.w / W), h: q(r.h / H) });
        }
      } else {
        const pr = this.seg.protect[parseInt(id.slice(1))];
        Object.assign(pr, { x: q(r.x / W), y: q(r.y / H), w: q(r.w / W), h: q(r.h / H) });
      }
    },
    keyRect(e, id) {
      const r = this.rects.find((x) => x.id === id);
      if (!r || !e.key.startsWith("Arrow")) return;
      e.preventDefault();
      const step = e.shiftKey ? 20 : 2;
      const dx = e.key === "ArrowLeft" ? -step : e.key === "ArrowRight" ? step : 0;
      const dy = e.key === "ArrowUp" ? -step : e.key === "ArrowDown" ? step : 0;
      const h = e.altKey ? (dx ? "e" : "s") : "move";
      this.sel = id;
      this.applyRect(id, this.moveRect(r, h, dx, dy), h);
    },
    setRectField(field, val) {
      const r = this.selRect;
      if (!r) return;
      const v = parseInt(val);
      if (isNaN(v)) return;
      const nr = { x: r.x, y: r.y, w: r.w, h: r.h, [field]: v };
      const { W, H } = this.pv;
      nr.w = Math.min(Math.max(20, nr.w), W); nr.h = Math.min(Math.max(20, nr.h), H);
      nr.x = Math.min(Math.max(0, nr.x), W - nr.w); nr.y = Math.min(Math.max(0, nr.y), H - nr.h);
      this.applyRect(r.id, nr, "numeric");
    },
    addProtect() {
      this.seg.protect.push({ from: "base", x: 0, y: 0.45, w: 1, h: 0.06, label: `${this.t("preview.protect")} ${this.seg.protect.length + 1}` });
      this.sel = `p${this.seg.protect.length - 1}`;
    },
    removeProtect(i) { this.seg.protect.splice(i, 1); this.sel = "region"; },
    get safeZones() {
      const { W, H } = this.pv;
      return [{ x: 0, y: 0, w: W, h: H * 0.08 }, { x: 0, y: H * 0.8, w: W, h: H * 0.2 },
              { x: W * 0.86, y: H * 0.35, w: W * 0.14, h: H * 0.45 }];
    },

    // ------------------------------------------------------------ tuỳ chọn (form từ schema)
    get tabs() {
      return ["region", "duration", "audio", "output", "run", "advanced"].map((id) => ({ id, label: this.t(`opt.tab.${id}`) }));
    },
    get tabFields() {
      if (!this.schema || !this.preset) return [];
      const i = this.pv.seg, s = this.seg, key = `${this.optTab}|${i}|${s?.kind}|${this.lang}`;
      if (this._fieldCache[key]) return this._fieldCache[key];
      const S = this.schema, out = [];
      const sec = (label) => out.push({ key: `sec-${label}`, type: "section", label, depth: 0 });
      if (this.optTab === "region" && s) {
        sec(this.t("opt.segmentOpts"));
        const ex = s.kind === "composite" ? ["x", "y", "w", "h"]
          : ["x", "y", "w", "h", "preset", "split", "corner", "size", "margin", "border", "feather", "opacity", "offset"];
        out.push(...buildFields(S, "Region", `timeline.${i}.region`, { exclude: ex }));
        if (s.kind === "composite") out.push(...buildFields(S, "Segment", `timeline.${i}`, { only: ["active_time"] }));
      } else if (this.optTab === "duration" && s) {
        sec(this.t("opt.segmentOpts"));
        const only = s.kind === "composite" ? SEG_KEYS.duration : ["speed", "trim", "optional", "transition_in", "duration"];
        out.push(...buildFields(S, "Segment", `timeline.${i}`, { only }));
        sec(this.t("opt.combine"));
        out.push(...buildFields(S, "CombineCfg", "combine"));
      } else if (this.optTab === "audio") {
        if (s) { sec(this.t("opt.segmentOpts")); out.push(...buildFields(S, "Segment", `timeline.${i}`, { only: SEG_KEYS.audio })); }
        sec(this.t("opt.jobAudio"));
        out.push(...buildFields(S, "AudioCfg", "audio"));
      } else if (this.optTab === "output") {
        out.push(...buildFields(S, "OutputCfg", "output"));
      } else if (this.optTab === "run") {
        out.push(...buildFields(S, "RunCfg", "run"));
      } else if (this.optTab === "advanced") {
        sec(this.t("opt.groups"));
        out.push(...buildFields(S, "GroupsCfg", "groups"));
      }
      this._fieldCache[key] = out;
      return out;
    },
    // Chỉ hiện ô có nghĩa trong ngữ cảnh hiện tại (progressive disclosure)
    fieldVisible(f) {
      if (f.showIf && getPath(this.preset, f.showIf) == null) return false;
      if (!f.path) return true;
      const P = this.preset, p = f.path, parent = (n) => getPath(P, p.split(".").slice(0, -n).join("."));
      let m = p.match(/^timeline\.(\d+)\.region\.(split|corner|size|margin|background)$/);
      if (m) {
        const reg = P.timeline[m[1]].region;
        if (m[2] === "split") return ["bottom", "top", "left", "right"].includes(reg.preset);
        if (m[2] === "size") return ["pip_corner", "center_box"].includes(reg.preset);
        if (m[2] === "background") return reg.fit === "contain";
        return reg.preset === "pip_corner";
      }
      if (/^timeline\.\d+\.(min_speed|max_speed)$/.test(p)) return parent(1).duration_mode === "match_base_speed";
      if (/\.audio\.base_volume$/.test(p)) return ["base", "mix"].includes(parent(1).mode);
      if (/\.audio\.overlay_volume$/.test(p)) return ["overlay", "mix"].includes(parent(1).mode);
      if (/\.transition_in\.duration$/.test(p)) return parent(1).type !== "cut";
      if (p === "output.bitrate_mbps") return P.output.quality === "bitrate";
      if (p === "output.thumbnail_at") return P.output.thumbnails;
      if (p === "combine.subset_k" || p === "combine.subset_strategy") return P.combine.mode === "per_group_subset";
      if (p === "groups.regex") return P.groups.key_mode === "regex";
      if (p === "groups.separator") return ["prefix", "suffix"].includes(P.groups.key_mode);
      return true;
    },
    nullLabel(f) { return f.name === "preset" ? this.t("enum.custom") : this.t("common.none"); },
    val(f) { return getPath(this.preset, f.path); },
    setVal(f, v) { setPath(this.preset, f.path, v); },
    optLabel(o) { const k = `enum.${o}`, s = this.t(k); return s === k ? String(o) : s; },
    api_open(path) { api("POST", "/api/system/open", { path }).catch((e) => this.toast("err", e.message)); },
    fv(f) {
      const v = getPath(this.preset, f.path);
      if (f.type === "csv") return Array.isArray(v) ? v.join(", ") : "";
      if (f.type === "json") return v == null ? "" : JSON.stringify(v, null, 1);
      if (f.type === "enum") return v == null ? "" : String(typeof v === "object" ? "__obj" : v);
      return v ?? "";
    },
    setFv(f, raw) {
      let v = raw;
      if (f.type === "number") {
        if (raw === "" || raw == null) v = f.nullable ? null : f.default ?? 0;
        else { v = f.int ? parseInt(raw) : parseFloat(raw); if (isNaN(v)) return; }
        if (v != null && f.min !== undefined) v = Math.max(f.min, v);
        if (v != null && f.max !== undefined) v = Math.min(f.max, v);
      } else if (f.type === "enum") {
        v = raw === "" ? null : f.options.find((o) => String(o) === String(raw));
      } else if (f.type === "text") {
        if (raw === "" && f.nullable) v = null;
        else if (f.mixed && raw !== "" && !isNaN(Number(raw))) v = Number(raw);
      } else if (f.type === "csv") {
        const arr = String(raw).split(",").map((x) => x.trim()).filter(Boolean);
        v = arr.length ? arr : (f.nullable ? null : []);
      } else if (f.type === "json") {
        try { v = raw.trim() ? JSON.parse(raw) : (f.nullable ? null : {}); } catch (_) { this.toast("err", this.t("opt.jsonError")); return; }
      }
      setPath(this.preset, f.path, v);
    },
    toggleOpt(f, on) { setPath(this.preset, f.path, on ? clone(f.defaults) : null); },
    resetTab() {
      const saved = JSON.parse(this.savedJson), i = this.pv.seg;
      const segSaved = saved.timeline?.[i];
      const copy = (keys) => keys.forEach((k) => { if (segSaved && k in segSaved) this.preset.timeline[i][k] = clone(segSaved[k]); });
      if (this.optTab === "region") copy(["region", "protect", "active_time"]);
      if (this.optTab === "duration") { copy(SEG_KEYS.duration); this.preset.combine = clone(saved.combine); }
      if (this.optTab === "audio") { copy(SEG_KEYS.audio); this.preset.audio = clone(saved.audio); }
      if (["output", "run"].includes(this.optTab)) this.preset[this.optTab] = clone(saved[this.optTab]);
      if (this.optTab === "advanced") { this.preset.groups = clone(saved.groups); this.preset.slots = clone(saved.slots); this.preset.timeline = clone(saved.timeline); }
      this.syncJsonDraft();
    },
    syncJsonDraft() {
      if (!this.preset) return;
      this.jsonDraft = { slots: JSON.stringify(this.preset.slots, null, 2), timeline: JSON.stringify(this.preset.timeline, null, 2) };
      this.jsonErr = "";
    },
    async applyJson(which) {
      try {
        const v = JSON.parse(this.jsonDraft[which]);
        const test = { ...clone(this.preset), [which]: v };
        const r = await api("POST", "/api/presets/validate", { preset: test });
        if (!r.ok) { this.jsonErr = r.errors.map((e) => `${e.loc}: ${e.msg}`).join("\n"); return; }
        this.preset[which] = v; this.jsonErr = ""; this._fieldCache = {};
        if (this.pv.seg >= this.preset.timeline.length) this.pv.seg = 0;
      } catch (e) { this.jsonErr = `${this.t("opt.jsonError")}: ${e.message}`; }
    },

    // ------------------------------------------------------------ chạy
    get isRunning() { return ["running", "paused"].includes(this.job.state); },
    get startReason() {
      if (!this.sys?.ffmpeg_ok) return this.t("run.reason.ffmpeg");
      if (this.isRunning) return this.t("run.reason.running");
      if (!Object.keys(this.paths).length) return this.t("run.reason.noSource");
      const b = this.full?.blockers || [];
      if (this.full && b.length) return b[0];
      if (this.planError) return this.planError;
      if (this.plan && !this.plan.count) return (this.plan.blockers || [])[0] || this.t("run.reason.noTasks");
      return "";
    },
    get canStart() { return !this.startReason && !!this.full?.ok && !this.checking; },
    get summary() {
      const p = this.full || this.plan;
      if (!p || !p.count) return "";
      const vars = { groups: p.groups, clips: p.clips, count: p.count };
      return this.preset.combine.mode === "no_pool" || !p.clips ? this.t("run.summaryNoPool", vars) : this.t("run.summary", vars);
    },
    get estimate() {
      const f = this.full;
      if (!f || !f.total_duration) return "";
      const todo = f.total_duration * (f.count ? (f.count - (this.preset.run.existing === "skip" ? f.existing : 0)) / f.count : 1);
      const secs = this.job.eta ?? (todo * 0.5) / Math.max(1, f.workers);  // ước lượng thô, sẽ tính lại sau video đầu
      return [this.t("run.estimate", { time: fmtDuration(secs) }), this.t("run.size", { size: fmtBytes(f.est_bytes) }),
              f.existing ? this.t("run.existing", { n: f.existing }) : ""].filter(Boolean).join(" · ");
    },
    async runCheck(show = true) {
      if (!this.preset || !Object.keys(this.paths).length) return;
      this.checking = true;
      try {
        this.full = await api("POST", "/api/plan", this.jobBody({ probe: true }));
        this.unfinished = this.full.unfinished || null;
        if (show) this.showIssues = true;
      } catch (e) { if (show) this.toast("err", e.message); }
      finally { this.checking = false; }
    },
    get issues() { return this.full?.issues || []; },
    issueClick(i) {
      if (i.slot) {
        this.mtab = "source";
        const el = document.querySelector(`[data-slot="${i.slot}"]`);
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
        el?.classList.add("flash"); setTimeout(() => el?.classList.remove("flash"), 1600);
      } else if (i.file) { this.issueDetail = { title: baseName(i.file), text: i.msg, file: i.file, media: this.media(i.file) }; this.modal = "issue"; }
      else { this.issueDetail = { title: this.t("run.issues"), text: i.msg }; this.modal = "issue"; }
    },
    async start() {
      if (!this.canStart) { if (!this.full) await this.runCheck(true); if (!this.canStart) return; }
      const f = this.full;
      if (f.count >= 500 && !(await this.ask({ title: this.t("run.confirmLarge", { count: f.count, time: this.estimate, size: fmtBytes(f.est_bytes) }) }))) return;
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
      try {
        this.logs = [];
        await api("POST", "/api/jobs/start", this.jobBody());
        this.saveLastJob();
      } catch (e) { this.toast("err", e.detail?.blockers?.join("; ") || e.message, 8000); }
    },
    pause() { api("POST", "/api/jobs/pause"); },
    resume() { api("POST", "/api/jobs/resume"); },
    async stop() {
      if (await this.ask({ title: this.t("run.confirmStop"), danger: true, ok: this.t("run.stop") })) api("POST", "/api/jobs/cancel");
    },
    async retry() { this.modal = null; try { await api("POST", "/api/jobs/retry"); } catch (e) { this.toast("err", e.message); } },
    async resumeUnfinished() {
      try { await api("POST", "/api/jobs/resume-unfinished", { out_dir: this.unfinished.out_dir }); this.unfinished = null; }
      catch (e) { this.toast("err", e.message); }
    },
    openOutput() { api("POST", "/api/system/open", { path: this.job.out_dir || this.full?.out_dir || this.outDir }).catch((e) => this.toast("err", e.message)); },
    get runningTasks() { return Object.values(this.job.tasks).filter((x) => x.status === "running"); },
    get jobPercent() { return this.job.percent || 0; },

    // ------------------------------------------------------------ websocket
    connectWs() {
      const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
      this._ws = ws;
      ws.onmessage = (m) => this.onEvent(JSON.parse(m.data));
      ws.onclose = (e) => { if (e.code === 4401) this.expired = true; else setTimeout(() => this.connectWs(), 1500); };
    },
    onEvent(ev) {
      if (ev.type === "snapshot") {
        this.job.state = ev.state || "idle";
        if (ev.tasks) { const m = {}; ev.tasks.forEach((x) => (m[x.index] = x)); this.job.tasks = m; }
        if (ev.summary) this.job.summary = ev.summary;
        this.job.out_dir = ev.out_dir || "";
        this.job.eta = ev.eta_s ?? null;
        if (this.isRunning) api("GET", "/api/jobs/current").then((c) => { this.logs = (c.logs || []).map(this.logItem); });
      } else if (ev.type === "job") {
        const prev = this.job.state;
        this.job.state = ev.state; this.job.summary = ev.summary || this.job.summary;
        if (ev.state === "running" && prev !== "paused" && prev !== "running") { this.job.tasks = {}; this.job.percent = 0; this.job.eta = null; }
        if (["done", "cancelled", "error"].includes(ev.state) && prev !== ev.state) this.onJobEnd(ev.state);
      } else if (ev.type === "task") {
        this.job.tasks = { ...this.job.tasks, [ev.index]: ev };
      } else if (ev.type === "task_progress") {
        const x = this.job.tasks[ev.index];
        if (x) x.progress = ev.progress;
      } else if (ev.type === "progress") {
        this.job.percent = ev.percent; this.job.eta = ev.eta_s ?? null;
        this.job.summary = { ...this.job.summary, done: ev.done, failed: ev.failed, skipped: ev.skipped, total: ev.total };
      } else if (ev.type === "log") {
        if (ev.level === "debug" && this.preset?.run?.log_level !== "debug") return;
        this.logs.push(this.logItem(ev));
        if (this.logs.length > 20000) this.logs.splice(0, 5000);
        if (this.logStick) this.$nextTick(() => { const el = this.$refs.log; if (el) el.scrollTop = el.scrollHeight; });
      }
    },
    logItem(ev) {
      const lv = ev.level === "warning" ? "warn" : ev.level;
      const time = new Date((ev.ts || Date.now() / 1000) * 1000).toLocaleTimeString();
      return { lv, msg: ev.msg, time, index: ev.index };
    },
    onJobEnd(state) {
      this.job.out_dir = this.job.out_dir || this.full?.out_dir || this.outDir;
      api("GET", "/api/jobs/current").then((c) => { this.job.out_dir = c.out_dir; this.job.summary = c.summary; });
      if (state === "done") {
        this.modal = "done";
        beep();
        const s = this.job.summary || {};
        if ("Notification" in window && Notification.permission === "granted" && document.hidden)
          new Notification(this.t("run.doneTitle"), { body: `${s.done || 0} ${this.t("run.ok")} · ${s.failed || 0} ${this.t("run.failed")}` });
      }
      this.runCheck(false);
    },

    // log ảo hoá: chỉ render các dòng đang thấy
    get filteredLogs() {
      if (this.logFilter === "err") return this.logs.filter((l) => l.lv === "error");
      if (this.logFilter === "warn") return this.logs.filter((l) => l.lv === "warn" || l.lv === "error");
      return this.logs;
    },
    get visibleLogs() {
      const all = this.filteredLogs;
      const start = Math.max(0, Math.floor(this.logTop / LOG_ROW) - 10);
      const end = Math.min(all.length, start + Math.ceil(this.logH / LOG_ROW) + 20);
      const out = [];
      for (let i = start; i < end; i++) out.push({ ...all[i], i, top: i * LOG_ROW });
      return out;
    },
    onLogScroll(el) {
      this.logTop = el.scrollTop; this.logH = el.clientHeight;
      this.logStick = el.scrollTop + el.clientHeight >= el.scrollHeight - LOG_ROW * 2;
    },
    logClick(l) {
      if (l.lv !== "error") return;
      const task = l.index != null ? this.job.tasks[l.index] : null;
      this.issueDetail = { title: this.t("common.error"), text: task?.error || l.msg, file: task?.out, log: true };
      this.modal = "issue";
    },

    async quit() {
      const running = this.isRunning;
      if (!(await this.ask({ title: this.t("top.quit"), text: running ? this.t("run.confirmStop") : "", danger: running }))) return;
      await api("POST", "/api/system/quit", { force: true }).catch(() => {});
      document.body.innerHTML = `<main style="display:grid;place-items:center;height:100vh;font-family:sans-serif">${this.t("app.title")} — đã thoát.</main>`;
    },
  };
}

document.addEventListener("alpine:init", () => window.Alpine.data("app", app));
