/* ═══════════════════════════════════════════════════════════════
   Pitch Mirror · front-end
   One page, many "views". The URL hash (#/results/abc123) decides which view is drawn.
   ═══════════════════════════════════════════════════════════════ */

// ───────── tiny helpers ─────────
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const view = $("#view");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const fmt = (t) => { t = Math.max(0, Math.round(t || 0)); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`; };
const FILLERS = new Set(["um", "uh", "umm", "uhm", "erm", "er", "ah", "hmm", "like", "so", "actually", "basically"]);
const isFiller = (w) => FILLERS.has(w.toLowerCase().replace(/[^a-z]/g, ""));
const COLORS = { amber: "#f5b13d", rose: "#f2566b", sky: "#4f9dff", pink: "#e98ee6", violet: "#a78bfa" };
const TYPE_COLOR = {
  pace_fast: "amber", pace_slow: "amber", filler: "rose", long_pause: "rose", visual: "sky", low_energy: "sky",
  monotone: "violet", content: "pink", skipped_text: "pink", clarity: "pink",
};
const flawColor = (f) => COLORS[TYPE_COLOR[f.type] || "violet"];
const ICON = {
  up: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg>',
  play: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 4.5v15l13-7.5z"/></svg>',
  pause: '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M6 4h4v16H6zM14 4h4v16h-4z"/></svg>',
  check: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
  chev: "›", trash: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  refresh: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5"/></svg>',
  pencil: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>',
};

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch { /* not JSON */ }
    throw new Error(msg);
  }
  return res.json();
}
const postJSON = (path, body) => api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 2600);
}

function download(name, blob) {
  const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

// ───────── app state (lives as long as the tab is open) ─────────
const state = {
  rubrics: [],
  rubricId: localStorage.getItem("pm.rubric") || "hackathon",
  file: null,          // a File chosen / recorded, waiting to be analysed
  sample: null,        // or the name of a sample in data/
  localUrl: null,      // object URL for the chosen file (used by the Analyzing view)
  autoRecord: false,
  sessions: new Map(), // cache of loaded sessions
  cleanup: [],         // functions to run when we leave a view (stop timers, cameras...)
  crumb: "",           // optional text a view shows next to the Back button, e.g. "Flaw 2 of 4"
};
const custom = () => JSON.parse(localStorage.getItem("pm.customRubrics") || "[]");
const allRubrics = () => [...state.rubrics, ...custom()];
const workspace = () => JSON.parse(localStorage.getItem("pm.workspace") || '{"name":"Example workspace","speaker":"Olivia"}');

// ═══════════════════ 🎓 Checkpoint 4: score-ring maths ═══════════════════
// A ring is an SVG circle whose outline is a dashed line exactly as long as the circle (C = 2πr).
// "stroke-dashoffset" slides that dash backwards. Offset 0 → full ring. Offset C → empty ring.
// Fill the ring `score` percent: slide the dash back by the part that should stay empty.
//    score is 0..100, C is the circumference. Example: score 68, C 100 → returns 32.
function ringOffset(score, C) {
  return C * (1 - clamp(score, 0, 100) / 100);
}

// ═══════════════════ 🎓 Checkpoint 5: Prev / Next flaw ═══════════════════
// i = current flaw index, dir = -1 (Prev) or +1 (Next), n = how many flaws exist.
// 🎓 TODO (Olivia): return the index of the neighbour flaw, but never go below 0 or above n - 1.
//    Example: neighborIndex(0, -1, 4) → 0   neighborIndex(1, +1, 4) → 2   neighborIndex(3, +1, 4) → 3
function neighborIndex(i, dir, n) {
  return clamp(i + dir, 0, n - 1);
}

function ring(score, { size = 92, stroke = 8, color = "url(#ringGrad)", track = "#2a2736", muted = false } = {}) {
  const r = (size - stroke) / 2, C = 2 * Math.PI * r;
  const col = muted ? "#6e6880" : color;
  return `<div class="ring ${size > 100 ? "lg" : ""}" style="width:${size}px;height:${size}px">
    <svg width="${size}" height="${size}" aria-hidden="true">
      <defs><linearGradient id="ringGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#c4a8ff"/><stop offset="1" stop-color="#7c4dff"/></linearGradient></defs>
      <circle cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="${track}" stroke-width="${stroke}" fill="none"/>
      <circle class="arc" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="${col}" stroke-width="${stroke}" fill="none" stroke-linecap="round"
        stroke-dasharray="${C}" stroke-dashoffset="${C}" data-offset="${ringOffset(score, C)}"/>
    </svg><b>${Math.round(score)}</b></div>`;
}
// animate rings and bars from 0 after they are on screen
function animateIn(root = view) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    $$(".arc[data-offset]", root).forEach((c) => c.setAttribute("stroke-dashoffset", c.dataset.offset));
    $$(".bar > i[data-w]", root).forEach((b) => (b.style.width = b.dataset.w));
  }));
}

// ───────── audio waveform peaks (decoded in the browser with Web Audio) ─────────
const peakCache = new Map();
async function peaks(url, n) {
  const key = url + "|" + n;
  if (peakCache.has(key)) return peakCache.get(key);
  const p = (async () => {
    try {
      const buf = await (await fetch(url)).arrayBuffer();
      const ctx = new (window.OfflineAudioContext || window.webkitOfflineAudioContext)(1, 1, 44100);
      const audio = await ctx.decodeAudioData(buf);
      const data = audio.getChannelData(0), step = Math.floor(data.length / n) || 1, out = [];
      for (let i = 0; i < n; i++) {
        let s = 0;
        for (let j = i * step; j < (i + 1) * step && j < data.length; j += 16) s = Math.max(s, Math.abs(data[j]));
        out.push(s);
      }
      const max = Math.max(...out, 1e-6);
      return { bars: out.map((v) => clamp(Math.pow(v / max, 0.8), 0.06, 1)), duration: audio.duration };
    } catch {
      // could not decode (rare codec): fall back to a calm synthetic shape
      return { bars: Array.from({ length: n }, (_, i) => 0.35 + 0.45 * Math.abs(Math.sin(i * 0.37) * Math.cos(i * 0.11))), duration: 0 };
    }
  })();
  peakCache.set(key, p);
  return p;
}
const barsHTML = (bars, cls = "") => bars.map((v) => `<i class="${cls}" style="height:${Math.round(v * 100)}%"></i>`).join("");

// ═══════════════════ router ═══════════════════
const routes = {
  analyze: analyzeView, analyzing: analyzingView, results: resultsView, flaw: flawView,
  progress: progressView, sessions: sessionsView, rubrics: rubricsView, evaluation: evaluationView,
};
const NAV_OF = { analyze: "analyze", analyzing: "analyze", results: "sessions", flaw: "sessions", progress: "sessions", sessions: "sessions", rubrics: "rubrics", evaluation: "evaluation" };

function parseHash() {
  const [name, ...args] = (location.hash.replace(/^#\/?/, "") || "analyze").split("/");
  return { name: routes[name] ? name : "analyze", args };
}

// ───────── Back button: every page returns to the page you came from ─────────
// `trail` mirrors this tab's in-app history. When you opened a page directly (no trail yet),
// Back goes to the page's logical parent instead, e.g. a flaw → its results.
const PAGE_NAME = { analyze: "Analyze", analyzing: "Analysis", results: "Results", flaw: "Flaw", progress: "Progress", sessions: "Sessions", rubrics: "Rubrics", evaluation: "Evaluation" };
const trail = [];
let replacing = false;
function track() {
  const h = location.hash || "#/analyze";
  if (trail.at(-2) === h) trail.pop();                            // browser Back or our Back button
  else if (replacing && trail.length) trail[trail.length - 1] = h; // a redirect, e.g. Analysis → Results
  else if (trail.at(-1) !== h) trail.push(h);
  replacing = false;
}
function parentOf(name, args) {
  if (name === "flaw") return `#/results/${args[0]}`;
  if (name === "results" || name === "progress") return "#/sessions";
  return name === "analyze" ? null : "#/analyze";
}
function paintBack(name, args) {
  const prev = trail.length > 1 ? trail.at(-2) : parentOf(name, args);
  $("#back-row").hidden = !prev;
  if (!prev) return;
  const to = prev.replace(/^#\/?/, "").split("/")[0] || "analyze";
  const label = to === name ? "Back" : `Back to ${PAGE_NAME[to] || "previous page"}`;
  $("#back-btn").innerHTML = `<span class="arrow" aria-hidden="true">←</span>${label}`;
  $("#back-btn").onclick = () => (trail.length > 1 ? history.back() : go(prev));
  $("#back-crumb").textContent = state.crumb;
}

let renderSeq = 0;
async function render() {
  state.cleanup.forEach((fn) => { try { fn(); } catch { /* ignore */ } });
  state.cleanup = [];
  state.crumb = "";
  const { name, args } = parseHash();
  const seq = ++renderSeq;
  $$(".nav a").forEach((a) => a.classList.toggle("active", a.dataset.nav === NAV_OF[name]));
  const draw = async () => {
    paintBack(name, args); // show Back right away, even while the page is still loading
    try { await routes[name](...args); }
    catch (e) { if (seq === renderSeq) view.innerHTML = errorCard(e.message); }
    if (seq !== renderSeq) return; // you already moved on (e.g. left a running analysis): don't touch the new page
    paintBack(name, args); // again, now with the page's crumb
    animateIn();
  };
  // smooth cross-fade between pages when the browser supports View Transitions
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const t = document.startViewTransition(draw);
    t.ready.catch(() => { /* fade skipped (e.g. you clicked again quickly): the page still updates */ });
    t.finished.finally(() => view.focus({ preventScroll: true }));
  } else {
    await draw();
    view.focus({ preventScroll: true });
  }
  window.scrollTo({ top: 0 });
}
// replace: swap the current history entry instead of adding one (used for redirects, so Back skips them)
const go = (hash, { replace = false } = {}) => {
  if (location.hash === hash) return render();
  if (replace) { replacing = true; location.replace(hash); } else location.hash = hash;
};
const errorCard = (msg) => `<div class="card empty" data-anim><p class="card-title" style="justify-content:center">Something went wrong</p>
  <p class="card-sub">${esc(msg)}</p><p><a class="btn" href="#/analyze" style="margin-top:16px">Back to Analyze</a></p></div>`;

async function getSession(sid, fresh = false) {
  if (!fresh && state.sessions.has(sid)) return state.sessions.get(sid);
  const s = await api(`/api/sessions/${sid}`);
  state.sessions.set(sid, s);
  return s;
}

// ═══════════════════ 1 · Analyze (upload) ═══════════════════
async function analyzeView() {
  if (!state.rubrics.length) state.rubrics = await api("/api/rubrics").catch(() => []);
  const samples = await api("/api/samples").catch(() => []);
  view.innerHTML = `
  <section class="hero">
    <span class="badge" data-anim>Multimodal · Speech · Visual · Content</span>
    <h1 data-anim="2">See exactly <em>which second</em><br>your pitch loses the room.</h1>
    <p data-anim="3">Upload a rehearsal. Get timestamped, rubric-scored feedback you can reproduce.</p>
    <div class="card upload-card" data-anim="4">
      <div class="dropzone" id="dropzone"></div>
      <div class="preset-row">
        <div><p class="eyebrow" style="margin:0">Rubric preset</p><div class="chips" id="chips"></div></div>
        <button class="btn btn-primary btn-lg" id="analyze-btn" disabled>Analyze your pitch →</button>
      </div>
    </div>
    <div class="legend" data-anim="5">
      <span><i class="dot" style="background:#a78bfa"></i>Pace, pauses, fillers</span>
      <span><i class="dot" style="background:#4f9dff"></i>Gaze, gesture, posture</span>git 
      <span><i class="dot" style="background:#e98ee6"></i>Hook, structure, clarity</span>
    </div>
  </section>`;

  const dz = $("#dropzone");
  let countdown = 3; /*倒数3秒*/
  let previewStream = null; // 预览时打开的摄像头画面
  const stopPreview = () => { if (previewStream) { previewStream.getTracks().forEach((t) => t.stop()); previewStream = null; } };
  const drawEmpty = () => {
    dz.innerHTML = `<div>
      <div class="dz-icon" id="icon-btn">${ICON.up}</div>
      <p class="dz-title">Drop your pitch video here</p>
      <p class="dz-sub">MP4, MOV or WebM · up to 10 min · stays private to your workspace</p>
      <div class="dz-actions">
        <button class="btn dz-btn" id="browse-btn">Browse files</button>  <!-- dz stand for dropzone -->
        <button class="btn dz-btn" id="record-btn"><span class="rec-dot"></span>Record now</button>
      </div>
      ${samples.length ? `<div class="samples">or try a sample: ${samples.filter((s) => !s.endsWith(".txt")).map((s) => `<button data-sample="${esc(s)}">${esc(s)}</button>`).join("")}</div>` : ""}
    </div>`;
    $("#browse-btn").onclick = () => $("#file-input").click();
    $("#icon-btn").onclick = () => $("#file-input").click();
    $("#record-btn").onclick = drawRecordSetup;
    $$("[data-sample]", dz).forEach((b) => (b.onclick = () => choose(null, b.dataset.sample)));
  };
  // 准备间 + Google Meet 式摄像头预览：先看到自己，选好倒数秒数，再开始录
  async function drawRecordSetup() {
    dz.innerHTML = `<div class="rec-setup">
      <div class="rec-preview">
        <video id="preview" autoplay muted playsinline></video>
        <span class="rec-hint">Camera preview · not recording yet</span>
        <div class="rec-count" id="rec-count" hidden></div>
      </div>
      <div class="rec-controls">
      <h2><span class="rec-dot"></span> Get ready to record </h2>
        <p class="dz-sub">Choose a countdown duration before recording:</p>
        <div class="chips">
          ${[3, 5, 10].map((s) => `<button class="chip ${s === countdown ? "active" : ""}" data-cd="${s}">${s}s</button>`).join("")}
        </div>
        <div class="dz-actions">
          <button class="btn" id="cd-back">Back</button>
          <button class="btn btn-primary" id="cd-start">Record now</button>
        </div>
      </div>
    </div>`;
    // 选秒数：只换高亮，不重画（重画会把摄像头关掉又重开）
    $$("[data-cd]", dz).forEach((b) => (b.onclick = () => {
      countdown = +b.dataset.cd;
      $$("[data-cd]", dz).forEach((x) => x.classList.toggle("active", x === b));
    }));
    $("#cd-back").onclick = () => { stopPreview(); drawEmpty(); };
    $("#cd-start").onclick = () => runCountdown();
    // 打开摄像头，把实时画面放进预览框
    try { previewStream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: true }); }
    catch { toast("Camera / microphone permission was blocked."); drawEmpty(); return; }
    const v = $("#preview", dz);
    if (v) { v.srcObject = previewStream; state.cleanup.push(stopPreview); }
    else stopPreview(); // 用户在授权弹窗期间离开了页面
  }

  // 在预览画面上数 3…2…1，数完用已经开着的摄像头开始录
  function runCountdown() {
    if (!previewStream) return;
    const stream = previewStream;
    const el = $("#rec-count");
    if ($("#cd-start")) $("#cd-start").disabled = true;
    let n = countdown;
    el.hidden = false; el.textContent = n;
    const tick = setInterval(() => {
      n--;
      if (n > 0) el.textContent = n;
      else { clearInterval(tick); startRecording(stream); }
    }, 1000);
    state.cleanup.push(() => clearInterval(tick));
  }
  const drawChosen = () => {
    const name = state.file ? state.file.name : state.sample;
    const url = state.file ? state.localUrl : null;
    dz.innerHTML = `<div class="dz-file">
      ${url && state.file.type.startsWith("video") ? `<video src="${url}" muted playsinline preload="metadata"></video>` : `<div class="dz-icon" style="margin:0">${ICON.check}</div>`}
      <div style="text-align:left">
        <div class="dz-name" id="dz-name"><p class="dz-title">${esc(name)}</p>${state.file ? `<button class="rename-btn" id="rename-btn" type="button" title="Rename" aria-label="Rename file">${ICON.pencil}</button>` : ""}</div>
        <p class="dz-sub" style="margin-bottom:12px">${state.file ? (state.file.size / 1048576).toFixed(1) + " MB · ready" : "sample recording · ready"}</p>
        <button class="btn" id="change-btn">Choose another</button></div></div>`;
    $("#change-btn").onclick = () => { choose(null, null); };
    if (state.file) $("#rename-btn").onclick = startRename; // 示例文件不能改名，只有你自己上传或录的才可以
  };
  // 改文件名：把标题换成输入框。Enter 保存，Esc 取消，点别处也会保存
  function startRename() {
    const f = state.file;
    const dot = f.name.lastIndexOf(".");
    const stem = dot > 0 ? f.name.slice(0, dot) : f.name; // 名字本体，例如 recording_2026-10-15
    const ext = dot > 0 ? f.name.slice(dot) : "";         // 副档名，例如 .webm（保持不变）
    $("#dz-name").innerHTML = `<input class="dz-rename" id="rename-input" value="${esc(stem)}" maxlength="80" aria-label="File name"><span class="dz-ext">${esc(ext)}</span>`;
    const input = $("#rename-input");
    input.focus();
    input.select();
    let finished = false;
    const finish = (save) => {
      if (finished) return; // Enter 之后输入框消失也会触发 blur，避免做两次
      finished = true;
      const clean = input.value.replace(/[\\/:*?"<>|]/g, "").trim();
      if (save && !clean) toast("The name can't be empty");
      else if (save && clean !== stem) {
        state.file = new File([f], clean + ext, { type: f.type, lastModified: f.lastModified });
        toast(`Renamed to “${clean + ext}”`);
      }
      drawChosen();
    };
    input.onkeydown = (e) => {
      if (e.key === "Enter") finish(true);
      if (e.key === "Escape") finish(false);
    };
    input.onblur = () => finish(true);
  }
  function choose(file, sample) {
    if (state.localUrl) URL.revokeObjectURL(state.localUrl);
    state.file = file; state.sample = sample;
    state.localUrl = file ? URL.createObjectURL(file) : null;
    $("#analyze-btn").disabled = !(file || sample);
    (file || sample) ? drawChosen() : drawEmpty();
  }
  state.file || state.sample ? drawChosen() : drawEmpty();
  $("#analyze-btn").disabled = !(state.file || state.sample);

  // drag & drop
  ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) choose(f, null); });
  $("#file-input").onchange = (e) => { const f = e.target.files[0]; if (f) choose(f, null); e.target.value = ""; };

  // rubric chips
  const drawChips = () => {
    $("#chips").innerHTML = allRubrics().map((r) =>
      `<button class="chip ${r.id === state.rubricId ? "active" : ""}" data-rub="${esc(r.id)}">${esc(r.name)}${r.id === state.rubricId ? ` · ${r.minutes} min` : ""}</button>`).join("")
      + `<button class="chip" id="custom-chip">+ Custom</button>`;
    $$("[data-rub]").forEach((b) => (b.onclick = () => { state.rubricId = b.dataset.rub; localStorage.setItem("pm.rubric", state.rubricId); drawChips(); }));
    $("#custom-chip").onclick = () => customRubricDialog(() => drawChips());
  };
  drawChips();

  $("#analyze-btn").onclick = async () => {
    const btn = $("#analyze-btn");
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span>${state.file ? "Uploading…" : "Starting…"}`;
    try {
      const body = { rubric: state.rubricId, speaker: workspace().speaker, name: state.file ? state.file.name : state.sample };
      const cr = custom().find((r) => r.id === state.rubricId);
      if (cr) body.custom = cr;
      if (state.file) {
        const fd = new FormData();
        fd.append("file", state.file, state.file.name);
        body.upload = (await api("/api/upload", { method: "POST", body: fd })).upload;
      } else body.sample = state.sample;
      const { job } = await postJSON("/api/analyze", body);
      go(`#/analyzing/${job}`);
    } catch (e) {
      toast(e.message);
      btn.disabled = false;
      btn.textContent = "Analyze your pitch →";
    }
  };

  // camera recording. `existing` = the camera already opened by the preview (so we don't ask twice)
  async function startRecording(existing) {
    let stream = existing instanceof MediaStream ? existing : null;
    if (!stream) {
      try { stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: true }); }
      catch { toast("Camera / microphone permission was blocked."); return; }
    }
    previewStream = null; // 预览把摄像头交给录制了，别再被 stopPreview 关掉
    const mime = ["video/webm;codecs=vp9,opus", "video/webm"].find((m) => MediaRecorder.isTypeSupported(m)) || "";
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : {});
    const chunks = [];
    const t0 = Date.now();
    dz.innerHTML = `<div class="rec-live"><video autoplay muted playsinline></video>
      <div class="rec-timer"><span class="rec-dot live" style="display:inline-block;margin-right:6px"></span><span id="rec-t">0:00</span> / 10:00</div>
      <button class="btn btn-primary" id="stop-btn">Stop recording</button></div>`;
    $("video", dz).srcObject = stream;
    const tick = setInterval(() => {
      const s = (Date.now() - t0) / 1000;
      const el = $("#rec-t"); if (el) el.textContent = fmt(s);
      if (s >= 600) rec.stop();
    }, 250);
    const stopAll = () => { clearInterval(tick); stream.getTracks().forEach((t) => t.stop()); };
    state.cleanup.push(() => { if (rec.state !== "inactive") rec.stop(); stopAll(); });
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      stopAll();
      if (!document.body.contains(dz)) return;
      const file = new File(chunks, `recording_${new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-")}.webm`, { type: "video/webm" });
      choose(file, null);
      toast("Recording ready. Press Analyze.");
    };
    rec.start(500);
    $("#stop-btn").onclick = () => rec.stop();
  }
  if (state.autoRecord) { state.autoRecord = false; drawRecordSetup(); }
}

function customRubricDialog(done) {
  const d = document.createElement("dialog");
  d.innerHTML = `<form method="dialog" class="stack">
    <p class="card-title">New rubric preset</p>
    <label class="field">Name<input name="name" required placeholder="e.g. Demo day pitch" maxlength="40"></label>
    <label class="field">Time limit (minutes)<input name="minutes" type="number" min="1" max="30" value="3" required></label>
    <label class="field">Focus areas (comma separated)<input name="focus" placeholder="hook, problem, demo, ask"></label>
    <div class="actions" style="justify-content:flex-end"><button class="btn" value="cancel" formnovalidate>Cancel</button><button class="btn btn-primary" value="ok">Save preset</button></div>
  </form>`;
  document.body.append(d);
  d.showModal();
  d.addEventListener("close", () => {
    if (d.returnValue === "ok") {
      const f = new FormData($("form", d));
      const r = { id: "custom-" + Date.now().toString(36), name: f.get("name").trim(), minutes: +f.get("minutes"), focus: String(f.get("focus") || "").split(",").map((s) => s.trim()).filter(Boolean), custom: true };
      localStorage.setItem("pm.customRubrics", JSON.stringify([...custom(), r]));
      state.rubricId = r.id;
      localStorage.setItem("pm.rubric", r.id);
      toast(`Preset “${r.name}” saved`);
      done?.();
    }
    d.remove();
  });
}

// ═══════════════════ 2 · Analyzing ═══════════════════
async function analyzingView(jobId) {
  let job = await api(`/api/jobs/${jobId}`);
  const url = state.localUrl || `/api/jobs/${jobId}/media`;
  const speaker = job.speaker || workspace().speaker;
  view.innerHTML = `
  <div class="page-head" data-anim>
    <div><p class="eyebrow">Session · ${esc(job.name || job.file)} · <span id="dur">–:–</span></p><h1 class="h1">Analyzing ${esc(speaker)}'s pitch</h1></div>
    <div><div class="big-pct mono"><span id="pct">0</span><small>%</small></div><p class="card-sub" id="eta" style="text-align:right">estimating…</p></div>
  </div>
  <div class="grid-3">
    ${lane("speech", "#a78bfa", "Speech", "Transcribing with word-level timestamps", "", 2)}
    ${lane("visual", "#4f9dff", "Visual", job.is_video ? "Sampling 2 fps · gaze &amp; gesture" : "Audio-only file · no frames", "sky", 3)}
    ${lane("content", "#e98ee6", "Content", "Scoring structure against rubric", "pink", 4)}
  </div>
  <div class="card live-tl" data-anim="5"><span class="label">LIVE TIMELINE</span>
    <div class="mini-wave" id="mini"><div class="playhead" id="ph" style="left:0"></div></div>
    <span class="time" id="tl-time" style="text-align:right">0:00 / –:–</span></div>`;

  function lane(id, color, title, sub, barCls, anim) {
    return `<article class="card" data-anim="${anim}">
      <div class="lane-head"><p class="card-title"><i class="dot" style="background:${color}"></i>${title}</p><span class="lane-pct" id="${id}-pct">0%</span></div>
      <p class="card-sub">${sub}</p>
      <div class="inset lane-body" id="${id}-body"></div>
      <div class="bar ${barCls}"><i id="${id}-bar"></i></div>
      <div class="metrics" id="${id}-m"></div></article>`;
  }

  // alive = this page still owns the job. It turns false when the job fails, when we jump to Results,
  // or when you leave with Back / the nav (then a toast says where the analysis will be).
  let alive = true;
  state.cleanup.push(() => {
    if (!alive) return;
    alive = false;
    toast(job.status === "done" ? "Analysis finished · open it from Sessions" : "Analysis keeps running · it will appear in Sessions when done");
  });
  // The page is on screen now: fill it in without making the router wait, so the page
  // (and its Back button) appears at once instead of only when the analysis ends.
  live();

  async function live() {
    // speech lane: the real waveform of the recording
    const pk = await peaks(url, 64);
    const full = await peaks(url, 150);
    if (!alive) return; // you left while the waveform was loading
    const dur = pk.duration || 0;
    $("#dur").textContent = dur ? fmt(dur) : "audio";
    $("#speech-body").innerHTML = `<div class="wave">${pk.bars.map((v, i) => `<i style="height:${Math.round(v * 100)}%;animation-delay:${(i % 9) * 0.08}s"></i>`).join("")}</div>`;
    $("#mini").insertAdjacentHTML("afterbegin", barsHTML(full.bars));

    // visual lane: 4 real frames grabbed from the video
    const vb = $("#visual-body");
    vb.innerHTML = `<div class="frames">${[0, 1, 2, 3].map((i) => `<div class="frame" id="fr${i}"></div>`).join("")}</div>`;
    if (job.is_video) grabFrames(url, 4).then((imgs) => imgs.forEach((src, i) => { const f = $(`#fr${i}`); if (f && src) f.innerHTML = `<img alt="" src="${src}">`; }));

    // content lane: rubric focus + what we are waiting for
    const rub = job.rubric || {};
    $("#content-body").innerHTML = `<div class="quote" id="quote"><div class="skeleton" style="width:90%"></div><div class="skeleton" style="width:75%"></div><div class="skeleton" style="width:55%"></div>
       <p style="margin-top:14px">${(rub.focus || []).map((f) => `<span class="tag pink" style="margin-right:6px">${esc(f)}</span>`).join("")}</p></div>`;

    let frameTick = 0;
    const update = (j) => {
      const p = j.progress || 0;
      const speech = clamp((p - 0.03) / 0.72), visual = j.is_video ? clamp((p - 0.2) / 0.65) : 1, content = clamp((p - 0.7) / 0.3);
      const overall = Math.round(p * 100);
      $("#pct").textContent = overall;
      const eta = p > 0.04 ? Math.max(1, Math.round((j.elapsed / p) * (1 - p))) : null;
      $("#eta").textContent = j.status === "done" ? "done" : eta ? `~${eta}s remaining` : "warming up the models…";
      [["speech", speech], ["visual", visual], ["content", content]].forEach(([id, v]) => {
        $(`#${id}-pct`).textContent = `${Math.round(v * 100)}%`;
        $(`#${id}-bar`).style.width = `${v * 100}%`;
      });
      $("#speech-m").innerHTML = `stage ${esc(j.stage)}<br>elapsed ${j.elapsed.toFixed(1)}s<br>model whisper · word timestamps`;
      $("#visual-m").innerHTML = j.is_video ? `frames ${Math.round(visual * 4)} / 4 preview<br>gaze ${j.gemini === "off" ? "needs Gemini key" : "via Gemini " + j.gemini}<br>sampling ~1 fps for scoring` : "no video track<br>visual score skipped<br>&nbsp;";
      $("#content-m").innerHTML = `${(rub.focus || []).join(" · ") || "rubric"}<br>gemini ${j.gemini}<br>rubric: ${esc(rub.name || "")}`;
      // animate the frame highlight + timeline playhead
      frameTick = (frameTick + 1) % 4;
      $$(".frame").forEach((f, i) => f.classList.toggle("on", job.is_video && i === frameTick));
      const done = Math.round(p * full.bars.length);
      $$("#mini i").forEach((b, i) => b.classList.toggle("done", i < done));
      $("#ph").style.left = `${p * 100}%`;
      $("#tl-time").textContent = `${fmt(dur * p)} / ${dur ? fmt(dur) : "–:–"}`;
    };
    update(job);
    while (alive) {
      await new Promise((r) => setTimeout(r, 700));
      if (!alive) return;
      try { job = await api(`/api/jobs/${jobId}`); } catch (e) { alive = false; view.innerHTML = errorCard(e.message); return; }
      update(job);
      if (job.status === "done") {
        state.file = null; state.sample = null;
        setTimeout(() => { if (alive) { alive = false; go(`#/results/${job.session}`, { replace: true }); } }, 600);
        return;
      }
      if (job.status === "error") {
        alive = false;
        view.innerHTML = errorCard(`Analysis failed: ${job.error}. Tips: make sure the file plays on your computer, or try a shorter clip.`);
        return;
      }
    }
  }
}

function grabFrames(url, n) {
  return new Promise((resolve) => {
    const v = Object.assign(document.createElement("video"), { src: url, muted: true, crossOrigin: "anonymous", preload: "auto" });
    const out = [];
    v.onloadedmetadata = async () => {
      const c = document.createElement("canvas");
      c.width = 112; c.height = 184;
      const ctx = c.getContext("2d");
      for (let i = 0; i < n; i++) {
        v.currentTime = v.duration * (i + 0.5) / n;
        await new Promise((r) => (v.onseeked = r));
        const scale = Math.max(c.width / v.videoWidth, c.height / v.videoHeight);
        const w = v.videoWidth * scale, h = v.videoHeight * scale;
        ctx.drawImage(v, (c.width - w) / 2, (c.height - h) / 2, w, h);
        out.push(c.toDataURL("image/jpeg", 0.7));
      }
      resolve(out);
    };
    v.onerror = () => resolve([]);
  });
}

// ═══════════════════ 3 · Results ═══════════════════
async function resultsView(sid) {
  const s = await getSession(sid, true);
  const flaws = s.flaws;
  const dims = { ...s.scores.dimensions, ...s.scores.ai_dimensions };
  const short = { "Fluency (fillers)": "Fillers", "Vocal variety (pitch)": "Vocal variety", "Energy / projection": "Energy", "Content (AI)": "Content · AI", "Visual (AI)": "Eye contact · AI" };
  view.innerHTML = `
  <div class="page-head" data-anim>
    <div><p class="eyebrow">${esc((s.name || s.file).replace(/\.[^.]+$/, ""))} · ${esc(s.rubric.name)} rubric</p><h1 class="h1">${esc(s.speaker)}'s pitch · Results</h1></div>
    <div class="actions"><button class="btn" id="export-btn">Export</button><button class="btn btn-primary" id="rerecord-btn">Re-record</button></div>
  </div>
  <div class="grid-golden">
    <div class="stack">
      <article class="card player" data-anim="2">
        <div class="stage" id="stage">
          ${s.is_video ? `<video id="media" src="${s.media_url}" preload="metadata" playsinline></video>` : `<div class="silhouette"></div><audio id="media" src="${s.media_url}" preload="metadata"></audio>`}
        </div>
        <div class="scrub">
          <button class="play-btn" id="play" aria-label="Play">${ICON.play}</button>
          <span class="time" id="time">0:00 / ${fmt(s.duration)}</span>
          <div class="track" id="track"><div class="fill" id="fill" style="width:0"></div>
            ${flaws.map((f) => `<button class="marker" data-t="${f.start}" title="${esc(f.label)}" style="left:${(f.start / s.duration) * 100}%;background:${flawColor(f)}"><span style="color:${flawColor(f)}">${fmt(f.start)}</span></button>`).join("")}
          </div>
        </div>
      </article>
      <article class="card" data-anim="3">
        <p class="card-title">Audience attention <span class="card-sub" style="margin:0;font-weight:400">estimated from pace, energy &amp; flaws</span></p>
        <div class="attn" id="attn"></div>
      </article>
    </div>
    <div class="stack">
      <article class="card score-card" data-anim="2">
        ${ring(s.overall)}
        <div class="score-text"><p class="eyebrow" style="margin:0">Overall</p><h3>${esc(s.headline)}</h3><p class="card-sub" style="margin:0">${flaws.length} timestamped flaw${flaws.length === 1 ? "" : "s"}</p></div>
      </article>
      <article class="card" data-anim="3">
        ${Object.entries(dims).map(([k, v]) => `<div class="rubric-row ${k.includes("AI") ? "ai" : ""}"><div class="lbl"><span>${esc(short[k] || k)}</span><span class="mono">${Math.round(v)}/10</span></div><div class="bar"><i data-w="${v * 10}%"></i></div></div>`).join("")}
        ${s.ai_error ? `<p class="card-sub">Gemini error (scores unaffected): ${esc(s.ai_error.slice(0, 90))}</p>` : ""}
      </article>
      <article class="card" data-anim="4">
        <p class="card-title">Flaws</p>
        ${flaws.length ? `<ul class="flaw-list">${flaws.map((f) => `
          <li class="flaw-item ${s.fixed.includes(f.idx) ? "fixed" : ""}" data-idx="${f.idx}" tabindex="0">
            <i class="dot" style="background:${flawColor(f)}"></i><span class="mono" style="color:${flawColor(f)}">${fmt(f.start)}</span>
            <span class="title">${esc(f.label)}</span><span class="chev">${ICON.chev}</span></li>`).join("")}</ul>`
          : `<p class="card-sub">No flaws found. Clean delivery! 🎉</p>`}
      </article>
    </div>
  </div>`;

  // custom media controls
  const m = $("#media");
  const setTime = () => {
    const d = m.duration || s.duration;
    $("#fill").style.width = `${(m.currentTime / d) * 100}%`;
    $("#time").textContent = `${fmt(m.currentTime)} / ${fmt(d)}`;
    const ph = $("#attn-ph"); if (ph) ph.setAttribute("x1", (m.currentTime / d) * 1000), ph.setAttribute("x2", (m.currentTime / d) * 1000);
  };
  let raf;
  const loop = () => { setTime(); raf = requestAnimationFrame(loop); };
  m.onplay = () => { $("#play").innerHTML = ICON.pause; loop(); };
  m.onpause = () => { $("#play").innerHTML = ICON.play; cancelAnimationFrame(raf); setTime(); };
  m.onended = m.onpause;
  $("#play").onclick = () => (m.paused ? m.play() : m.pause());
  $("#stage").onclick = (e) => { if (e.target === m || e.target.id === "stage") m.paused ? m.play() : m.pause(); };
  const seek = (t) => { m.currentTime = clamp(t, 0, m.duration || s.duration); setTime(); };
  $("#track").onclick = (e) => { if (e.target.closest(".marker")) return; const r = e.currentTarget.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * (m.duration || s.duration)); };
  $$(".marker").forEach((b) => (b.onclick = () => { seek(Math.max(0, +b.dataset.t - 1)); m.play(); }));
  const key = (e) => { if (e.code === "Space" && !/INPUT|TEXTAREA|BUTTON/.test(document.activeElement.tagName)) { e.preventDefault(); m.paused ? m.play() : m.pause(); } };
  document.addEventListener("keydown", key);
  state.cleanup.push(() => { document.removeEventListener("keydown", key); cancelAnimationFrame(raf); m.pause(); });

  drawAttention($("#attn"), s.attention, s.flaws, s.duration, seek);
  $$(".flaw-item").forEach((li) => {
    const open = () => go(`#/flaw/${sid}/${li.dataset.idx}`);
    li.onclick = open;
    li.onkeydown = (e) => e.key === "Enter" && open();
  });
  $("#export-btn").onclick = () => {
    download(`${(s.name || s.file).replace(/[\\/:*?"<>|]/g, "_")}_pitch-mirror-report.json`, new Blob([JSON.stringify(s, null, 2)], { type: "application/json" }));
    toast("Report exported");
  };
  $("#rerecord-btn").onclick = () => { state.autoRecord = true; state.rubricId = s.rubric.id || state.rubricId; go("#/analyze"); };
}

function drawAttention(el, vals, flaws, dur, seek) {
  const W = 1000, H = 150, n = vals.length;
  const pts = vals.map((v, i) => [(i / (n - 1)) * W, H - 12 - v * (H - 30)]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Estimated audience attention over time">
    <defs><linearGradient id="ag" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8b5cf6" stop-opacity=".45"/><stop offset="1" stop-color="#8b5cf6" stop-opacity="0"/></linearGradient></defs>
    ${flaws.map((f) => `<rect x="${(f.start / dur) * W}" y="0" width="${Math.max(3, ((f.end - f.start) / dur) * W)}" height="${H}" fill="${flawColor(f)}" opacity=".07"/>`).join("")}
    <path d="${line}L${W},${H}L0,${H}Z" fill="url(#ag)"/>
    <path d="${line}" fill="none" stroke="#b794ff" stroke-width="2" vector-effect="non-scaling-stroke" stroke-linejoin="round"/>
    <line id="attn-ph" x1="0" x2="0" y1="0" y2="${H}" stroke="#fff" stroke-opacity=".5" stroke-width="1" vector-effect="non-scaling-stroke"/>
  </svg>`;
  el.style.cursor = "pointer";
  el.onclick = (e) => { const r = el.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * dur); };
}

// ═══════════════════ 4 · Flaw detail / Re-speak ═══════════════════
async function flawView(sid, idxStr) {
  const s = await getSession(sid);
  const n = s.flaws.length;
  const idx = clamp(parseInt(idxStr, 10) || 0, 0, n - 1);
  const f = s.flaws[idx];
  if (!f) throw new Error("This session has no flaws.");
  const fixed = s.fixed.includes(idx);
  // how much lower is estimated attention inside this flaw vs the whole talk?
  const at = s.attention, i0 = Math.floor((f.start / s.duration) * (at.length - 1)), i1 = Math.ceil((Math.min(s.duration, f.end + 1.5) / s.duration) * (at.length - 1));
  const segAvg = at.slice(i0, i1 + 1).reduce((a, b) => a + b, 0) / Math.max(1, i1 - i0 + 1);
  const avg = at.reduce((a, b) => a + b, 0) / at.length;
  const drop = Math.round(((segAvg - avg) / avg) * 100);

  state.crumb = `Flaw ${idx + 1} of ${n}`;
  view.innerHTML = `
  <div class="page-head" data-anim>
    <div style="display:flex;align-items:center;gap:14px"><span class="pill-time">${fmt(f.start)} – ${fmt(f.end)}</span><h1 class="h1" id="flaw-title" tabindex="-1">${esc(f.label)}${f.count > 1 ? ` in ${Math.max(1, Math.round(f.end - f.start))} seconds` : ""}</h1></div>
    <div class="actions">
      <button class="btn" id="prev-btn" title="Previous flaw (← key)" ${idx === 0 ? "disabled" : ""}>← Prev</button>
      <button class="btn" id="next-btn" title="Next flaw (→ key)" ${idx === n - 1 ? "disabled" : ""}>Next →</button>
    </div>
  </div>
  <div class="grid-2">
    <article class="card" data-anim="2">
      <div class="lane-head"><p class="eyebrow" style="margin:0">Original · You</p><span class="lane-pct" id="o-meta"></span></div>
      <div class="audio-row"><button class="audio-btn" id="o-play" aria-label="Play original">${ICON.play}</button><div class="seg-wave" id="o-wave"></div></div>
      <p class="say" id="o-text"><span class="skeleton" style="display:block;width:92%"></span><span class="skeleton" style="display:block;width:70%"></span></p>
    </article>
    <article class="card glow" data-anim="3">
      <div class="lane-head"><p class="eyebrow" style="margin:0;color:var(--violet-3)">Re-speak · AI rewrite</p><span class="lane-pct" id="r-meta"></span></div>
      <div class="audio-row"><button class="audio-btn violet" id="r-play" aria-label="Play rewrite">${ICON.play}</button><div class="seg-wave violet" id="r-wave"></div></div>
      <p class="say violet" id="r-text"><span class="skeleton" style="display:block;width:88%"></span><span class="skeleton" style="display:block;width:60%"></span></p>
      <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap">
        <span class="chip" id="voice-chip" style="cursor:default">Voice: neutral TTS</span>
        <button class="chip" id="tone-chip">Tone: confident</button>
        <button class="chip active" id="regen-btn">${ICON.refresh} Regenerate</button>
      </div>
    </article>
  </div>
  <div class="grid-3 grid-flaw">
    <article class="card why" data-anim="3"><p class="card-title">Why this matters</p>
      <p>${esc(f.why)} ${drop < -3 ? `Estimated attention dropped <b>${drop}%</b> here.` : ""}</p></article>
    <article class="card why" data-anim="4"><p class="card-title">Practice tip</p><p>${esc(f.suggestion)}</p></article>
    <article class="card stack" data-anim="5" style="align-content:center">
      <button class="btn btn-primary btn-block btn-lg" id="practice-btn">Practice this segment</button>
      <button class="btn btn-block" id="fixed-btn">${fixed ? "✓ Marked as fixed" : "Mark as fixed"}</button>
      <div class="practice-out" id="practice-out"></div>
    </article>
  </div>`;
  $("#flaw-title").focus({ preventScroll: true });

  // Prev / Next (uses your 🎓 neighborIndex)
  const nav = (dir) => { const j = neighborIndex(idx, dir, n); if (j !== idx) go(`#/flaw/${sid}/${j}`); else toast(dir < 0 ? "This is the first flaw" : "This is the last flaw"); };
  $("#prev-btn").onclick = () => nav(-1);
  $("#next-btn").onclick = () => nav(1);
  const keys = (e) => { if (e.target.tagName === "INPUT") return; if (e.key === "ArrowLeft") nav(-1); if (e.key === "ArrowRight") nav(1); };
  document.addEventListener("keydown", keys);
  state.cleanup.push(() => document.removeEventListener("keydown", keys));

  $("#fixed-btn").onclick = async () => {
    const r = await postJSON(`/api/sessions/${sid}/flaws/${idx}/fixed`);
    s.fixed = r.fixed;
    const on = r.fixed.includes(idx);
    $("#fixed-btn").textContent = on ? "✓ Marked as fixed" : "Mark as fixed";
    toast(on ? "Nice! Marked as fixed." : "Unmarked");
  };

  const tones = ["confident", "warm", "energetic", "calm"];
  let tone = "confident";
  $("#tone-chip").onclick = () => { tone = tones[(tones.indexOf(tone) + 1) % tones.length]; $("#tone-chip").textContent = `Tone: ${tone}`; };

  const players = [];
  state.cleanup.push(() => players.forEach((a) => a.pause()));
  const wire = (btnId, waveId, src) => {
    const a = new Audio(src);
    players.push(a);
    const btn = $(btnId), bars = () => $$(`${waveId} i`);
    let raf;
    const paint = () => { const p = a.currentTime / (a.duration || 1); bars().forEach((b, i, all) => b.classList.toggle("dim", i / all.length > p)); raf = requestAnimationFrame(paint); };
    a.onplay = () => { players.forEach((o) => o !== a && o.pause()); btn.innerHTML = ICON.pause; paint(); };
    a.onpause = a.onended = () => { btn.innerHTML = ICON.play; cancelAnimationFrame(raf); bars().forEach((b) => b.classList.remove("dim")); };
    btn.onclick = () => (a.paused ? a.play() : a.play && a.pause());
    btn.onclick = () => (a.paused ? a.play() : a.pause());
    a.onloadedmetadata = () => {
      const meta = waveId === "#o-wave" ? "#o-meta" : "#r-meta";
      $(meta).dataset.d = a.duration.toFixed(1);
      $(meta).textContent = `${a.duration.toFixed(1)}s · ${$(meta).dataset.f} filler${$(meta).dataset.f === "1" ? "" : "s"}`;
    };
    return a;
  };

  const load = async (regenerate = false) => {
    if (regenerate) {
      $("#regen-btn").innerHTML = `<span class="spinner"></span> Regenerating`;
      $("#r-text").innerHTML = `<span class="skeleton" style="display:block;width:88%"></span><span class="skeleton" style="display:block;width:60%"></span>`;
    }
    try {
      const r = await postJSON(`/api/sessions/${sid}/flaws/${idx}/respeak`, { regenerate, tone });
      $("#o-text").innerHTML = `“${r.original_text.split(/\s+/).map((w) => (isFiller(w) ? `<u>${esc(w)}</u>` : esc(w))).join(" ")}”`;
      $("#r-text").textContent = `“${r.rewrite}”`;
      $("#o-meta").dataset.f = r.original_fillers;
      $("#r-meta").dataset.f = r.rewrite_fillers;
      $("#o-meta").textContent = `${r.original_fillers} fillers`;
      $("#r-meta").textContent = `${r.rewrite_fillers} fillers`;
      $("#voice-chip").textContent = `Voice: ${r.engine === "edge-tts" ? "neutral TTS" : r.engine}`;
      const [ow, rw] = await Promise.all([peaks(r.original_url, 56), peaks(r.rewrite_url, 56)]);
      $("#o-wave").innerHTML = barsHTML(ow.bars);
      $("#r-wave").innerHTML = barsHTML(rw.bars);
      players.forEach((a) => a.pause());
      players.length = 0;
      wire("#o-play", "#o-wave", r.original_url);
      wire("#r-play", "#r-wave", r.rewrite_url);
      if (r.gemini === "off") $("#r-text").insertAdjacentHTML("afterend", `<p class="card-sub" id="nokey">No Gemini key: this rewrite only removes fillers. Add GEMINI_API_KEY in .env for real rewrites.</p>`);
    } catch (e) {
      $("#r-text").textContent = `Could not create the re-speak: ${e.message}`;
    } finally {
      $("#regen-btn").innerHTML = `${ICON.refresh} Regenerate`;
    }
  };
  $("#regen-btn").onclick = () => { $("#nokey")?.remove(); load(true); };
  load();

  // practice: record the mic for this segment and compare fillers + pace
  $("#practice-btn").onclick = async () => {
    const btn = $("#practice-btn"), out = $("#practice-out");
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch { toast("Microphone permission was blocked."); return; }
    const rec = new MediaRecorder(stream), chunks = [];
    const limit = Math.ceil(f.end - f.start + 8);
    let left = limit;
    btn.innerHTML = `<span class="rec-dot live"></span> Recording… tap to stop (${left}s)`;
    const tick = setInterval(() => { left--; btn.innerHTML = `<span class="rec-dot live"></span> Recording… tap to stop (${left}s)`; if (left <= 0) rec.stop(); }, 1000);
    state.cleanup.push(() => { clearInterval(tick); if (rec.state !== "inactive") rec.stop(); stream.getTracks().forEach((t) => t.stop()); });
    btn.onclick = () => rec.stop();
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = async () => {
      clearInterval(tick);
      stream.getTracks().forEach((t) => t.stop());
      btn.innerHTML = `<span class="spinner"></span> Scoring your take…`;
      btn.disabled = true;
      try {
        const fd = new FormData();
        fd.append("file", new Blob(chunks, { type: "audio/webm" }), "take.webm");
        const r = await api(`/api/sessions/${sid}/flaws/${idx}/practice`, { method: "POST", body: fd });
        out.innerHTML = `fillers ${r.before.fillers} → <b style="color:var(--green)">${r.after.fillers}</b><br>pace ${r.before.wpm} → ${r.after.wpm} wpm<br><span style="color:var(--tx-3)">“${esc(r.transcript.slice(0, 120))}”</span>`;
        if (r.after.fillers < r.before.fillers) toast("Fewer fillers than before. Great progress!");
      } catch (e) { out.textContent = e.message; }
      btn.disabled = false;
      btn.textContent = "Practice again";
      btn.onclick = $("#practice-btn").onclick;
      flawView.lastPractice = btn.onclick;
    };
    rec.start();
  };
  const practiceHandler = $("#practice-btn").onclick;
  $("#practice-btn").addEventListener("click", () => {}, { once: true });
  flawView.practiceHandler = practiceHandler;
}

// ═══════════════════ 5 · Progress (before / after) ═══════════════════
async function progressView(a, b) {
  if (!a || !b) return pickTwo();
  const c = await api(`/api/compare?a=${a}&b=${b}`);
  const date = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const delta = (r) => {
    const d = r.b - r.a;
    if (Math.abs(d) < 0.05) return `<span class="delta flat">= 0</span>`;
    let good;
    if (r.better === "lower") good = d < 0;
    else if (r.better === "higher") good = d > 0;
    else good = Math.abs(r.b - 150) < Math.abs(r.a - 150);
    const v = Number.isInteger(d) ? Math.abs(d) : Math.abs(d).toFixed(1);
    return `<span class="delta ${good ? "" : "bad"}">${d < 0 ? "▼" : "▲"} ${v}</span>`;
  };
  view.innerHTML = `
  <div class="grid-2 grid-progress">
    <div class="stack">
      <div data-anim><p class="eyebrow">Progress · Attempt 1 → Attempt 2</p>
        <h1 class="big-head">${esc(c.headline.text)} <em>${esc(c.headline.value)}</em>.</h1>
        <p class="card-sub" style="font-size:13.5px">Same rubric, same prompt, same model settings — so the change is you, not the scorer.</p></div>
      <div class="grid-2" data-anim="2">
        <article class="card ba"><p class="eyebrow">Before</p>${ring(c.a.overall, { size: 112, muted: true })}<p class="date">${date(c.a.created)} · ${fmt(c.a.duration)}</p></article>
        <article class="card ba glow"><p class="eyebrow" style="color:var(--violet-3)">After</p>${ring(c.b.overall, { size: 112 })}<p class="date">${date(c.b.created)} · ${fmt(c.b.duration)}</p></article>
      </div>
      <article class="card verified" data-anim="3"><div class="check">${ICON.check}</div>
        <div><p class="card-title">Reproducible score</p><p class="card-sub mono" style="font-size:11px">${c.repro.available
          ? `eval.py · ${c.repro.files} files × ${c.repro.runs} cache-cleared re-runs · max σ = ${c.repro.sigma} pts · rubric v${esc(c.repro.version)}`
          : "Not measured yet · run py -3.12 eval.py --plan --repeats 3 --no-ai"}</p></div>
        <span class="ok">${!c.repro.available ? "NOT RUN" : c.repro.sigma <= 0.5 ? "VERIFIED" : "UNSTABLE"}</span></article>
    </div>
    <article class="card" data-anim="2" style="align-self:start">
      <div class="lane-head"><p class="card-title">Metric breakdown</p><span class="chip" style="cursor:default">${esc(c.b.rubric.name)} · ${c.b.rubric.minutes} min</span></div>
      <table class="mtable"><tbody>${c.rows.map((r) => `<tr><td>${esc(r.name)}</td><td class="num a">${r.a}</td><td class="arrow">→</td><td class="num">${r.b}</td><td style="text-align:right">${delta(r)}</td></tr>`).join("")}</tbody></table>
      <div class="actions" style="margin-top:21px"><button class="btn btn-primary" id="share-btn">Share progress card</button><button class="btn" id="tl-btn">Compare timelines</button></div>
    </article>
  </div>`;
  $("#share-btn").onclick = () => shareCard(c);
  $("#tl-btn").onclick = () => compareTimelines(c);
}

async function pickTwo() {
  const list = await api("/api/sessions");
  view.innerHTML = `<div class="page-head" data-anim><div><p class="eyebrow">Progress</p><h1 class="h1">Pick two attempts to compare</h1></div></div>
    <div class="card" data-anim="2">${list.length < 2 ? `<div class="empty">You need at least two analysed takes. <a class="btn" href="#/analyze" style="margin-left:10px">Analyze a take</a></div>` : sessionRows(list, true)}</div>`;
  wireSessionRows(list);
}

function shareCard(c) {
  const cv = Object.assign(document.createElement("canvas"), { width: 1200, height: 630 });
  const x = cv.getContext("2d");
  const g = x.createRadialGradient(600, -100, 50, 600, -100, 700);
  g.addColorStop(0, "#3b2470"); g.addColorStop(1, "#0b0a10");
  x.fillStyle = g; x.fillRect(0, 0, 1200, 630);
  x.fillStyle = "#a9a6b8"; x.font = "500 22px Inter, sans-serif"; x.fillText("PITCH MIRROR · PROGRESS", 70, 90);
  x.fillStyle = "#ecebf2"; x.font = "600 64px Inter, sans-serif"; x.fillText(`${c.headline.text}`, 70, 190);
  x.fillStyle = "#a78bfa"; x.fillText(c.headline.value, 70, 270);
  const ringAt = (cx, val, col, label) => {
    x.lineWidth = 16; x.strokeStyle = "#2a2736"; x.beginPath(); x.arc(cx, 440, 80, 0, Math.PI * 2); x.stroke();
    x.strokeStyle = col; x.lineCap = "round"; x.beginPath(); x.arc(cx, 440, 80, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * val) / 100); x.stroke();
    x.fillStyle = "#ecebf2"; x.font = "600 48px Inter, sans-serif"; x.textAlign = "center"; x.fillText(Math.round(val), cx, 457);
    x.fillStyle = "#6f6c80"; x.font = "500 18px Inter, sans-serif"; x.fillText(label, cx, 560); x.textAlign = "left";
  };
  ringAt(170, c.a.overall, "#6e6880", "BEFORE");
  ringAt(400, c.b.overall, "#9d6bff", "AFTER");
  x.font = "400 22px Inter, sans-serif";
  c.rows.slice(0, 5).forEach((r, i) => {
    const y = 380 + i * 46;
    x.fillStyle = "#a9a6b8"; x.fillText(r.name, 600, y);
    x.fillStyle = "#ecebf2"; x.fillText(`${r.a}  →  ${r.b}`, 930, y);
  });
  cv.toBlob((blob) => { download("pitch-mirror-progress.png", blob); toast("Progress card downloaded"); });
}

function compareTimelines(c) {
  const W = 660, H = 200;
  const all = [...c.timeline_a, ...c.timeline_b];
  const tMax = Math.max(...all.map((p) => p.t), 1), wMax = Math.max(220, ...all.map((p) => p.wpm));
  const path = (arr) => arr.filter((p) => p.wpm).map((p, i) => `${i ? "L" : "M"}${((p.t / tMax) * W).toFixed(1)},${(H - (p.wpm / wMax) * H).toFixed(1)}`).join("");
  const band = (lo, hi) => `<rect x="0" width="${W}" y="${H - (hi / wMax) * H}" height="${((hi - lo) / wMax) * H}" fill="#4ade80" opacity=".06"/>`;
  const dots = (arr, y) => arr.map((f) => `<circle cx="${(f.s / tMax) * W}" cy="${y}" r="4" fill="${f.sev === "high" ? COLORS.rose : f.sev === "medium" ? COLORS.amber : COLORS.violet}"/>`).join("");
  const d = document.createElement("dialog");
  d.innerHTML = `<div class="lane-head"><p class="card-title">Pace timeline · words per minute</p><button class="btn btn-ghost btn-icon" id="close-d" aria-label="Close">✕</button></div>
    <p class="card-sub"><span style="color:#6e6880">━ Before (${esc(c.a.name || c.a.file)})</span> &nbsp; <span style="color:#a78bfa">━ After (${esc(c.b.name || c.b.file)})</span> &nbsp; green band = comfortable 100–195 wpm</p>
    <svg viewBox="-4 -14 ${W + 8} ${H + 36}" style="width:100%;margin-top:14px">${band(100, 195)}
      <path d="${path(c.timeline_a)}" fill="none" stroke="#6e6880" stroke-width="2"/><path d="${path(c.timeline_b)}" fill="none" stroke="#a78bfa" stroke-width="2.4"/>
      ${dots(c.flaws_a, H + 10)}${dots(c.flaws_b, -6)}</svg>
    <p class="card-sub">Dots = flaws (top: after, bottom: before). Fewer dots = cleaner take.</p>`;
  document.body.append(d);
  d.showModal();
  $("#close-d", d).onclick = () => d.close();
  d.addEventListener("close", () => d.remove());
}

// ═══════════════════ Sessions ═══════════════════
function sessionRows(list, selectable) {
  return `<div class="list-row head"><span>Session</span><span>Rubric</span><span>Length</span><span>Score</span><span></span></div>
  ${list.map((s) => `<div class="list-row" data-sid="${s.id}">
    <span style="display:flex;align-items:center;gap:12px">${selectable ? `<input type="checkbox" data-pick="${s.id}" aria-label="Select ${esc(s.name || s.file)}">` : ""}
      <span><b style="font-weight:500">${esc(s.name || s.file)}</b><br><span class="card-sub" style="margin:0">${new Date(s.created * 1000).toLocaleString()} · ${s.n_flaws} flaws</span></span></span>
    <span class="card-sub" style="margin:0">${esc(s.rubric.name)}</span><span class="mono">${fmt(s.duration)}</span>
    <span class="mono" style="color:var(--violet-2)">${Math.round(s.overall)}</span>
    <span style="text-align:right"><button class="btn btn-ghost btn-icon" data-del="${s.id}" aria-label="Delete session">${ICON.trash}</button></span></div>`).join("")}`;
}

function wireSessionRows(list) {
  const picked = [];
  $$("[data-sid]").forEach((row) => (row.onclick = (e) => {
    if (e.target.closest("[data-pick],[data-del]")) return;
    go(`#/results/${row.dataset.sid}`);
  }));
  $$("[data-pick]").forEach((cb) => (cb.onchange = () => {
    if (cb.checked) picked.push(cb.dataset.pick); else picked.splice(picked.indexOf(cb.dataset.pick), 1);
    if (picked.length > 2) { const old = picked.shift(); $(`[data-pick="${old}"]`).checked = false; }
    const btn = $("#compare-btn");
    if (btn) btn.disabled = picked.length !== 2;
    if (!btn && picked.length === 2) {
      // order by date: older = before
      const [x, y] = picked.map((id) => list.find((s) => s.id === id)).sort((p, q) => p.created - q.created);
      go(`#/progress/${x.id}/${y.id}`);
    }
  }));
  $$("[data-del]").forEach((b) => (b.onclick = async () => {
    if (!confirm("Delete this session? This cannot be undone.")) return;
    await api(`/api/sessions/${b.dataset.del}`, { method: "DELETE" });
    state.sessions.delete(b.dataset.del);
    toast("Session deleted");
    render();
  }));
  const btn = $("#compare-btn");
  if (btn) btn.onclick = () => {
    const [x, y] = picked.map((id) => list.find((s) => s.id === id)).sort((p, q) => p.created - q.created);
    go(`#/progress/${x.id}/${y.id}`);
  };
}

async function sessionsView() {
  const list = await api("/api/sessions");
  view.innerHTML = `<div class="page-head" data-anim><div><p class="eyebrow">Workspace · ${list.length} session${list.length === 1 ? "" : "s"}</p><h1 class="h1">Sessions</h1></div>
    <div class="actions"><button class="btn" id="compare-btn" disabled>Compare selected</button><a class="btn btn-primary" href="#/analyze">New analysis</a></div></div>
    <div class="card" data-anim="2">${list.length ? sessionRows(list, true) : `<div class="empty">No sessions yet. Upload a rehearsal to get started.<br><a class="btn btn-primary" href="#/analyze" style="margin-top:16px">Analyze your pitch →</a></div>`}</div>
    ${list.length ? `<p class="card-sub" data-anim="3" style="margin-top:13px">Tick two takes and press <b>Compare selected</b> to see your progress.</p>` : ""}`;
  wireSessionRows(list);
}

// ═══════════════════ Rubrics ═══════════════════
async function rubricsView() {
  state.rubrics = await api("/api/rubrics").catch(() => []);
  const draw = () => {
    view.innerHTML = `<div class="page-head" data-anim><div><p class="eyebrow">Scoring</p><h1 class="h1">Rubrics</h1></div>
      <div class="actions"><button class="btn btn-primary" id="new-rub">+ New preset</button></div></div>
      <div class="grid-3">${allRubrics().map((r, i) => `<article class="card ${r.id === state.rubricId ? "glow" : ""}" data-anim="${Math.min(5, i + 2)}">
        <div class="lane-head"><p class="card-title">${esc(r.name)}</p><span class="lane-pct">${r.minutes} min</span></div>
        <p class="card-sub">${r.custom ? "Custom preset · saved in this browser" : "Preset · from rubrics.json"}</p>
        <p style="margin:14px 0">${(r.focus || []).map((f) => `<span class="tag pink" style="margin:0 6px 6px 0">${esc(f)}</span>`).join("")}</p>
        <div class="actions"><button class="btn" data-use="${esc(r.id)}">${r.id === state.rubricId ? "✓ In use" : "Use preset"}</button>
        ${r.custom ? `<button class="btn btn-ghost btn-icon" data-rm="${esc(r.id)}" aria-label="Delete preset">${ICON.trash}</button>` : ""}</div></article>`).join("")}</div>
      <article class="card" data-anim="5" style="margin-top:13px"><p class="card-title">How scores are computed</p>
        <p class="card-sub" style="line-height:1.7">The overall score is a fixed weighted mix of six acoustic dimensions — Pace 20%, Fillers 20%, Pausing 15%, Vocal variety 20%, Energy 10%, Clarity 15% — computed with pure maths, so the same file always gets the same score. Gemini content and eye-contact scores are shown next to it but never mixed in.</p></article>`;
    $("#new-rub").onclick = () => customRubricDialog(draw);
    $$("[data-use]").forEach((b) => (b.onclick = () => { state.rubricId = b.dataset.use; localStorage.setItem("pm.rubric", state.rubricId); toast("Preset selected"); draw(); animateIn(); }));
    $$("[data-rm]").forEach((b) => (b.onclick = () => { localStorage.setItem("pm.customRubrics", JSON.stringify(custom().filter((r) => r.id !== b.dataset.rm))); draw(); }));
  };
  draw();
}

// ═══════════════════ Evaluation ═══════════════════
async function evaluationView() {
  const e = await api("/api/evaluation");
  if (!e.available) {
    view.innerHTML = `<div class="page-head" data-anim><div><p class="eyebrow">Proof it works</p><h1 class="h1">Evaluation</h1></div></div>
      <div class="card empty" data-anim="2"><p class="card-title" style="justify-content:center">No evaluation results yet</p>
      <p class="card-sub">In a terminal inside the <code>pitch_mirror</code> folder run:</p><p class="mono" style="color:var(--violet-3)">py -3.12 eval.py</p>
      <p class="card-sub">It scores every good_* and bad_* recording several times and checks the score separates them and never changes between runs.</p></div>`;
    return;
  }
  const s = e.summary;
  const stat = (label, val, sub) => `<article class="card"><p class="eyebrow">${label}</p><p style="font-size:28px;font-weight:600;margin:4px 0;letter-spacing:-.02em">${val}</p><p class="card-sub">${sub}</p></article>`;
  view.innerHTML = `<div class="page-head" data-anim><div><p class="eyebrow">Proof it works</p><h1 class="h1">Evaluation</h1></div></div>
    <div class="grid-3" style="grid-template-columns:repeat(4,1fr)" data-anim="2">
      ${stat("Mean gap", `${(+s.mean_gap).toFixed(1)} pts`, "good − bad average score")}
      ${stat("AUROC", (+s.auroc).toFixed(2), "how often good beats bad (1.0 = always)")}
      ${stat("Rerun σ", `${(+s.rerun_std_max).toFixed(2)} pts`, "0 = perfectly reproducible")}
      ${stat("Files", s.n_files, "recordings evaluated")}</div>
    ${e.has_plot ? `<article class="card" data-anim="3" style="margin-top:13px"><p class="card-title">Score separation</p><img src="/api/evaluation/plot" alt="Score separation between good and bad recordings" style="width:100%;border-radius:10px;margin-top:13px"></article>` : ""}
    ${e.rows ? `<article class="card" data-anim="4" style="margin-top:13px;overflow:auto"><table class="mtable"><tbody>
      <tr>${Object.keys(e.rows[0]).map((k) => `<td class="eyebrow">${esc(k)}</td>`).join("")}</tr>
      ${e.rows.map((r) => `<tr>${Object.values(r).map((v) => `<td class="mono" style="font-size:12px">${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></article>` : ""}`;
}

// ═══════════════════ workspace + boot ═══════════════════
function paintWorkspace() {
  const w = workspace();
  $("#workspace-name").textContent = w.name;
  $("#workspace-avatar").textContent = (w.speaker || w.name || "O").trim()[0].toUpperCase();
}
$("#workspace-btn").onclick = () => {
  const w = workspace();
  const d = document.createElement("dialog");
  d.innerHTML = `<form method="dialog" class="stack"><p class="card-title">Workspace</p>
    <label class="field">Workspace name<input name="name" value="${esc(w.name)}" maxlength="40" required></label>
    <label class="field">Speaker name (shown as “Olivia's pitch”)<input name="speaker" value="${esc(w.speaker)}" maxlength="30" required></label>
    <div class="actions" style="justify-content:flex-end"><button class="btn" value="cancel" formnovalidate>Cancel</button><button class="btn btn-primary" value="ok">Save</button></div></form>`;
  document.body.append(d);
  d.showModal();
  d.addEventListener("close", () => {
    if (d.returnValue === "ok") {
      const f = new FormData($("form", d));
      localStorage.setItem("pm.workspace", JSON.stringify({ name: f.get("name").trim(), speaker: f.get("speaker").trim() }));
      paintWorkspace();
      toast("Workspace updated");
    }
    d.remove();
  });
};

async function checkHealth() {
  const dot = $("#health-dot");
  try {
    const h = await api("/api/health");
    dot.classList.add("ok");
    dot.title = `Server OK · Gemini: ${h.gemini}${h.model ? " (" + h.model + ")" : ""}`;
  } catch {
    dot.title = "Server health endpoint not found yet (🎓 Checkpoint 2 in server.py)";
  }
}

paintWorkspace();
checkHealth();
window.addEventListener("hashchange", () => { track(); render(); });
track();
render();
