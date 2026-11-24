// 3d-print-tools web UI. Plain ES module, no build step.
// The server (web/app.py) does all converting and slicing; this file only drives the page.

const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => [...el.querySelectorAll(sel)];
const enc = encodeURIComponent;
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const icon = (id, cls = "") => `<svg class="ico ${cls}" aria-hidden="true"><use href="#i-${id}"/></svg>`;
const fmtBytes = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);
const fmtTime = (s) => {
  if (s == null) return "–";
  s = Math.round(s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h} h ${m} m` : `${m} m ${String(r).padStart(2, "0")} s`;
};
const num = (v) => (v === "" || v == null ? NaN : Number(v));
const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

async function api(url, opts = {}) {
  const r = await fetch(url, opts);
  let data = null;
  try { data = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) {
    const d = data && data.detail;
    const err = new Error((d && (d.message || d)) || (data && data.conflict ? "name conflict" : r.statusText));
    err.status = r.status; err.data = data; err.code = d && d.code;
    throw err;
  }
  return data;
}
const postJSON = (url, body) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ------------------------------------------------------------------ state --
const FIELDS = ["nozzle_first", "nozzle_other", "bed", "layer_height", "support_threshold", "brim_width"];
const DEFAULT_KEY = { nozzle_first: "nozzle_first", nozzle_other: "nozzle_other", bed: "bed", layer_height: "layer_height",
                      support_threshold: "support_threshold_angle", brim_width: "brim_width" };
// keys the form sets itself; typing them in "Advanced" would fight the form
const RESERVED = new Set(["enable_support", "support_type", "support_threshold_angle", "brim_type", "brim_width", "layer_height",
  "nozzle_temperature", "nozzle_temperature_initial_layer", "hot_plate_temp", "hot_plate_temp_initial_layer"]);

const S = {
  options: null, files: [], sel: -1, lib: [], libTotals: null,
  material: "pla", profile: "quality", values: {}, changed: new Set(), touched: new Set(),
  support: false, supportType: "tree(auto)", brim: false, kv: [], hiddenTypes: new Set(),
  project: null, job: null, results: null, view: "edit", lastConvertKey: null, busy: false, slicer: null,
};
let uid = 0;

// ----------------------------------------------------------- feedback UI --
function announce(text) { const el = $("#sr"); el.textContent = ""; setTimeout(() => (el.textContent = text), 30); }

function toast(text, kind = "ok", { action, onAction, persist } = {}) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.setAttribute("role", kind === "bad" ? "alert" : "status");
  el.innerHTML = `${icon(kind === "bad" ? "error" : kind === "ok" ? "check" : "info")}<div class="grow">${esc(text)}${action ? ` <button type="button" class="linkbtn">${esc(action)}</button>` : ""}</div><button type="button" class="iconbtn small" aria-label="Dismiss">${icon("x")}</button>`;
  const close = () => el.remove();
  el.querySelector(".iconbtn").onclick = close;
  if (action) el.querySelector(".linkbtn").onclick = () => { onAction(); close(); };
  $("#toasts").append(el);
  if (!(persist || kind === "bad")) setTimeout(close, action ? 5000 : 4000);
  return el;
}

function setBusy(btn, busy, label) {
  if (busy) {
    btn.dataset.html = btn.innerHTML;
    btn.setAttribute("aria-busy", "true");
    btn.innerHTML = `<span class="spin" aria-hidden="true"></span>${esc(label)}`;
  } else if (btn.dataset.html) {
    btn.innerHTML = btn.dataset.html;
    btn.removeAttribute("aria-busy");
    delete btn.dataset.html;
  }
}

const dlgConflict = $("#dlgConflict");
function askConflict(info, what) {
  const when = new Date(info.existing.mtime * 1000).toLocaleString();
  $("#conflictText").innerHTML = `<b>${esc(info.path)} already exists with different contents</b>Saved ${esc(when)} · ${fmtBytes(info.existing.size)}. The new ${esc(what)} is ${fmtBytes(info.new.size)}.`;
  dlgConflict.returnValue = "";
  dlgConflict.showModal();
  return new Promise((resolve) => dlgConflict.addEventListener("close", () => resolve(dlgConflict.returnValue || "skip"), { once: true }));
}

// --------------------------------------------------------------- settings --
function profileDefaults() {
  const p = S.options.profiles.find((x) => x.name === S.profile);
  return p.defaults[S.material];
}
function limits() { return S.options.limits.per_material[S.material]; }

function buildSettingsControls() {
  const o = S.options;
  $("#materialSeg").innerHTML = o.materials.map((m) =>
    `<label><input type="radio" name="material" value="${m.name}" ${m.name === S.material ? "checked" : ""}>${m.name.toUpperCase()}</label>`).join("");
  $("#profileList").innerHTML = o.profiles.map((p) =>
    `<label><input type="radio" name="profile" value="${p.name}" ${p.name === S.profile ? "checked" : ""}><span class="r" aria-hidden="true"></span><b>${esc(p.name)}</b><small>${esc(p.description)}</small></label>`).join("");
  $("#settingKeys").innerHTML = o.setting_keys.filter((k) => !RESERVED.has(k)).map((k) => `<option value="${k}">`).join("");
  $$("input[name=material]").forEach((r) => r.addEventListener("change", () => { S.material = r.value; applyDefaults(); onSettingsChanged(); viewer.setColour(); }));
  $$("input[name=profile]").forEach((r) => r.addEventListener("change", () => { S.profile = r.value; applyDefaults(); onSettingsChanged(); }));
}

function applyDefaults() {
  const d = profileDefaults();
  for (const f of FIELDS) {
    if (!S.changed.has(f)) S.values[f] = String(d[DEFAULT_KEY[f]]);
    $("#" + f).value = S.values[f];
  }
  const lim = limits();
  const [lo, hi] = lim.nozzle_range;
  $("#tempHint").textContent = `${S.material.toUpperCase()} preset range ${lo}–${Math.min(hi, S.options.limits.hotend_max)} °C. Printer limits ${S.options.limits.hotend_max} / ${S.options.limits.bed_max} °C.`;
  $("#layer_height_hint").textContent = `Profile ${d.layer_height} mm · nozzle preset allows ${lim.layer_height[0]}–${lim.layer_height[1]} mm`;
  FIELDS.forEach(markChanged);
  FIELDS.forEach((f) => S.touched.has(f) && showFieldError(f));
}

function markChanged(f) {
  const d = profileDefaults();
  const changed = S.changed.has(f) && num(S.values[f]) !== Number(d[DEFAULT_KEY[f]]);
  const fld = $(`[data-field="${f}"]`);
  if (fld) fld.classList.toggle("changed", changed);
  const reset = $(`[data-reset="${f}"]`);
  if (reset) reset.hidden = !changed;
  if (!changed) S.changed.delete(f);
}

function fieldError(f) {
  const v = S.values[f], n = num(v), L = S.options.limits, lim = limits();
  const whole = (lo, hi, what) => {
    if (v === "" || Number.isNaN(n)) return `Enter ${what}.`;
    if (!Number.isInteger(n)) return "Enter a whole number.";
    if (n < lo || n > hi) return null;
    return "";
  };
  switch (f) {
    case "nozzle_first": case "nozzle_other": {
      const e = whole(L.nozzle_min, L.hotend_max, "a temperature");
      return e === null ? `The hotend reaches ${L.hotend_max} °C at most. Enter ${L.nozzle_min}–${L.hotend_max}.` : e;
    }
    case "bed": {
      const e = whole(0, L.bed_max, "a temperature");
      return e === null ? `The bed reaches ${L.bed_max} °C at most. Enter 0–${L.bed_max}.` : e;
    }
    case "layer_height": {
      if (v === "" || Number.isNaN(n)) return "Enter a layer height.";
      const [lo, hi] = lim.layer_height;
      return n < lo || n > hi ? `The 0.4 mm nozzle preset allows ${lo}–${hi} mm.` : "";
    }
    case "support_threshold": {
      if (!S.support) return "";
      const e = whole(0, 90, "an angle");
      return e === null ? "Enter 0–90°." : e;
    }
    case "brim_width": {
      if (!S.brim) return "";
      if (v === "" || Number.isNaN(n)) return "Enter a width.";
      return n < 0.5 || n > 20 ? "Enter 0.5–20 mm." : "";
    }
  }
  return "";
}

function showFieldError(f) {
  const msg = fieldError(f);
  const input = $("#" + f);
  $("#" + f + "_err").textContent = msg;
  input.setAttribute("aria-invalid", msg ? "true" : "false");
  if (f.startsWith("nozzle") && !msg) {
    const [lo, hi] = limits().nozzle_range, n = num(S.values[f]);
    if (n < lo || n > hi) $("#" + f + "_err").innerHTML = `<span class="warntxt">Outside the ${lo}–${hi} °C the filament preset recommends.</span>`;
  }
  return msg;
}

function kvErrors() {
  const keys = new Set(S.options.setting_keys);
  const seen = new Set();
  return S.kv.map((row) => {
    const k = row.key.trim();
    if (!k && !row.value.trim()) return "";
    if (!k) return "Enter a setting key.";
    if (RESERVED.has(k)) return `${k} is set by the form above; use that field.`;
    if (!keys.has(k)) return `${k} is not a setting of the stock presets.`;
    if (seen.has(k)) return `${k} is listed twice.`;
    seen.add(k);
    if (!row.value.trim()) return "Enter a value.";
    return "";
  });
}

function renderKv() {
  const errs = kvErrors();
  $("#kvRows").innerHTML = S.kv.map((row, i) => `
    <div class="kv" data-i="${i}">
      <label class="sr-only" for="kvk${row.id}">Setting key</label>
      <input class="input mono small" id="kvk${row.id}" list="settingKeys" value="${esc(row.key)}" placeholder="support_threshold_angle" data-kv="key" autocomplete="off" aria-invalid="${errs[i] && row.touched ? "true" : "false"}" aria-describedby="kve${row.id}">
      <label class="sr-only" for="kvv${row.id}">Value</label>
      <input class="input mono small" id="kvv${row.id}" value="${esc(row.value)}" placeholder="value" data-kv="value" autocomplete="off">
      <button type="button" class="iconbtn" data-kv="remove" aria-label="Remove ${esc(row.key || "setting")}">${icon("x")}</button>
      <div class="errtxt" id="kve${row.id}">${row.touched ? esc(errs[i]) : ""}</div>
    </div>`).join("");
  const n = S.kv.filter((r) => r.key.trim()).length;
  $("#advCount").hidden = !n;
  $("#advCount").textContent = `${n} set`;
}

function validateAll() {
  const errs = [];
  const okFiles = S.files.filter((f) => f.path && !f.error);
  if (!okFiles.length) errs.push({ id: "dropSmall", msg: "Add at least one STL file." });
  if (okFiles.length > S.options.limits.max_plates) errs.push({ id: "fileList", msg: `${okFiles.length} files, but a project holds at most ${S.options.limits.max_plates} plates. Remove some.` });
  if (S.files.some((f) => f.uploading)) errs.push({ id: "fileList", msg: "Wait until all uploads have finished." });
  for (const f of FIELDS) {
    S.touched.add(f);
    const msg = showFieldError(f);
    if (msg) errs.push({ id: f, msg: `${$(`label[for=${f}]`).textContent}: ${msg}` });
  }
  S.kv.forEach((r) => (r.touched = true));
  renderKv();
  kvErrors().forEach((msg, i) => msg && errs.push({ id: `kvk${S.kv[i].id}`, msg, open: true }));
  const box = $("#errSummary");
  if (errs.length) {
    box.innerHTML = `<b>Fix ${errs.length === 1 ? "this" : `these ${errs.length} things`} first</b><ul>${errs.map((e) => `<li><a href="#${e.id}" data-focus="${e.id}" ${e.open ? 'data-open="1"' : ""}>${esc(e.msg)}</a></li>`).join("")}</ul>`;
    box.hidden = false;
    if (S.view !== "edit") showView("edit");
    box.focus();
  } else {
    box.hidden = true;
  }
  return errs.length === 0;
}

function buildRequest() {
  const d = profileDefaults(), v = S.values;
  const req = { files: S.files.filter((f) => f.path && !f.error).map((f) => f.path), material: S.material, profile: S.profile,
                support: S.support, extra: {} };
  if (num(v.nozzle_first) !== d.nozzle_first) req.nozzle_first = num(v.nozzle_first);
  if (num(v.nozzle_other) !== d.nozzle_other) req.nozzle_other = num(v.nozzle_other);
  if (num(v.bed) !== d.bed) req.bed = num(v.bed);
  if (num(v.layer_height) !== d.layer_height) req.layer_height = num(v.layer_height);
  if (S.support) {
    if (S.supportType !== "normal(auto)") req.extra.support_type = S.supportType;
    if (num(v.support_threshold) !== d.support_threshold_angle) req.extra.support_threshold_angle = String(num(v.support_threshold));
  }
  if (S.brim) {
    req.extra.brim_type = "outer_only";
    if (num(v.brim_width) !== d.brim_width) req.extra.brim_width = String(num(v.brim_width));
  }
  for (const row of S.kv) if (row.key.trim()) req.extra[row.key.trim()] = row.value.trim();
  return req;
}
const requestKey = () => JSON.stringify(buildRequest());

function renderSummary() {
  const ok = S.files.filter((f) => f.path && !f.error).length;
  if (!ok) { $("#summary").textContent = "Add STL files to start"; return; }
  const v = S.values, parts = [`${ok} plate${ok > 1 ? "s" : ""}`, S.material.toUpperCase(), S.profile, `${v.layer_height} mm`,
    `${v.nozzle_first}/${v.nozzle_other}/${v.bed} °C`];
  if (S.support) parts.push(`supports (${S.supportType.startsWith("tree") ? "tree" : "normal"}, ${v.support_threshold}°)`);
  if (S.brim) parts.push(`brim ${v.brim_width} mm`);
  const n = S.kv.filter((r) => r.key.trim()).length;
  if (n) parts.push(`${n} custom`);
  $("#summary").textContent = parts.join(" · ");
}

function onSettingsChanged() {
  renderSummary();
  $("#supportSub").textContent = S.support ? `${S.supportType.startsWith("tree") ? "Tree" : "Normal"} · ${S.values.support_threshold}° overhang angle` : "Off";
  $("#brimSub").textContent = S.brim ? `Outer only · ${S.values.brim_width} mm` : "Off";
  renderStepper();
}

function bindSettings() {
  for (const f of FIELDS) {
    const input = $("#" + f);
    input.addEventListener("input", () => {
      S.values[f] = input.value;
      S.changed.add(f);
      markChanged(f);
      if (S.touched.has(f)) showFieldError(f);
      onSettingsChanged();
    });
    input.addEventListener("blur", () => { S.touched.add(f); showFieldError(f); });
  }
  $$("[data-reset]").forEach((b) => b.addEventListener("click", () => {
    const f = b.dataset.reset;
    S.changed.delete(f);
    applyDefaults();
    onSettingsChanged();
    $("#" + f).focus();
  }));
  const toggle = (btn, key, opts) => btn.addEventListener("click", () => {
    S[key] = !S[key];
    btn.setAttribute("aria-checked", String(S[key]));
    $(opts).hidden = !S[key];
    onSettingsChanged();
  });
  toggle($("#support"), "support", "#supportOpts");
  toggle($("#brim"), "brim", "#brimOpts");
  $("#support_type").addEventListener("change", (e) => { S.supportType = e.target.value; onSettingsChanged(); });
  $("#btnAddKv").addEventListener("click", () => {
    S.kv.push({ id: ++uid, key: "", value: "", touched: false });
    renderKv();
    $(`#kvk${S.kv[S.kv.length - 1].id}`).focus();
  });
  $("#kvRows").addEventListener("input", (e) => {
    const rowEl = e.target.closest(".kv");
    if (!rowEl) return;
    const row = S.kv[+rowEl.dataset.i];
    row[e.target.dataset.kv] = e.target.value;
    if (row.touched) {
      const msg = kvErrors()[+rowEl.dataset.i];
      $(`#kve${row.id}`).textContent = msg;
      $(`#kvk${row.id}`).setAttribute("aria-invalid", msg ? "true" : "false");
    }
    onSettingsChanged();
  });
  $("#kvRows").addEventListener("focusout", (e) => {
    const rowEl = e.target.closest(".kv");
    if (!rowEl || rowEl.contains(e.relatedTarget)) return;
    const row = S.kv[+rowEl.dataset.i];
    if (!row) return;
    row.touched = true;
    const msg = kvErrors()[+rowEl.dataset.i];
    $(`#kve${row.id}`).textContent = msg;
    $(`#kvk${row.id}`).setAttribute("aria-invalid", msg ? "true" : "false");
  });
  $("#kvRows").addEventListener("click", (e) => {
    const b = e.target.closest('[data-kv="remove"]');
    if (!b) return;
    S.kv.splice(+b.closest(".kv").dataset.i, 1);
    renderKv();
    onSettingsChanged();
    $("#btnAddKv").focus();
  });
  $("#errSummary").addEventListener("click", (e) => {
    const a = e.target.closest("[data-focus]");
    if (!a) return;
    e.preventDefault();
    if (a.dataset.open) $("#advanced").open = true;
    const el = document.getElementById(a.dataset.focus);
    if (el) { el.scrollIntoView({ block: "center", behavior: reducedMotion ? "auto" : "smooth" }); (el.matches("input,button,select") ? el : el.querySelector("button,input") || el).focus(); }
  });
  $("#btnReset").addEventListener("click", () => {
    S.changed.clear(); S.touched.clear(); S.kv = [];
    S.support = false; S.brim = false; S.supportType = "tree(auto)";
    $("#support").setAttribute("aria-checked", "false"); $("#supportOpts").hidden = true;
    $("#brim").setAttribute("aria-checked", "false"); $("#brimOpts").hidden = true;
    $("#support_type").value = S.supportType;
    $("#errSummary").hidden = true;
    renderKv(); applyDefaults(); onSettingsChanged();
    toast("Settings reset to the profile", "info");
  });
}

// ------------------------------------------------------------------ files --
function okFiles() { return S.files.filter((f) => f.path && !f.error); }

function fileBadges(f) {
  if (f.uploading) return `<span class="b"><span class="spin" aria-hidden="true"></span>uploading…</span>`;
  if (f.error) return `<span class="b bad">${icon("error")}${esc(f.error)}</span>`;
  const c = f.check, out = [];
  if (!c) return "";
  out.push(c.watertight ? `<span class="b ok">${icon("check")}watertight</span>` : `<span class="b warn">${icon("warn")}${c.open_edges + c.flipped_edges} open edges</span>`);
  out.push(c.fits ? `<span class="b ok">${icon("check")}fits bed</span>` : `<span class="b bad">${icon("error")}larger than the bed</span>`);
  if (c.tilted) out.push(`<span class="b warn">${icon("warn")}tilted ${Math.round(c.tilt_deg)}°</span>`);
  return out.join("");
}

function renderFiles() {
  const list = $("#fileList");
  const plates = okFiles();
  list.innerHTML = S.files.map((f, i) => {
    const plateNo = plates.indexOf(f) + 1;
    const sub = f.check ? `${f.check.size_mm.map((x) => x.toFixed(1)).join(" × ")} mm · ${f.check.volume_cm3} cm³` : f.path ? fmtBytes(f.size) : "";
    return `<li class="file ${i === S.sel ? "sel" : ""} ${f.error ? "err" : ""}" data-i="${i}" draggable="${f.path && !f.error ? "true" : "false"}">
      <button type="button" class="pick" data-act="select" aria-pressed="${i === S.sel}" aria-label="${esc(f.name)}${plateNo ? `, plate ${plateNo}` : ""}">
        <span class="name">${esc(f.name)}</span>
        ${plateNo && plates.length > 1 ? `<span class="plate">plate ${plateNo}</span>` : ""}
        <span class="sub">${esc(sub)}</span>
        <span class="badges">${fileBadges(f)}</span>
      </button>
      <span class="tools">
        ${plates.length > 1 && plateNo ? `<button type="button" class="iconbtn small" data-act="up" aria-label="Move ${esc(f.name)} up" ${plateNo === 1 ? "disabled" : ""}>${icon("up")}</button>
        <button type="button" class="iconbtn small" data-act="down" aria-label="Move ${esc(f.name)} down" ${plateNo === plates.length ? "disabled" : ""}>${icon("down")}</button>` : ""}
        <button type="button" class="iconbtn small" data-act="remove" aria-label="Remove ${esc(f.name)}">${icon("x")}</button>
      </span>
    </li>`;
  }).join("");
  $("#fileCount").textContent = String(S.files.length);
  const n = plates.length, max = S.options ? S.options.limits.max_plates : 36;
  $("#plateHint").textContent = n > max ? `${n} files: a project holds at most ${max} plates. Remove ${n - max}.`
    : n > 1 ? `${n} files → ${n} plates in one project. Drag or use the arrows to reorder.` : "";
  $("#plateHint").style.color = n > max ? "var(--bad)" : "";
  const empty = S.files.length === 0;
  $("#emptyState").hidden = !empty;
  $("#dropSmall").hidden = empty;
  renderPreview();
  renderSummary();
  renderStepper();
  renderLibrary();
}

function selectFile(i) {
  S.sel = i;
  renderFiles();
}

function removeFile(i) {
  const [f] = S.files.splice(i, 1);
  if (S.sel >= S.files.length) S.sel = S.files.length - 1;
  renderFiles();
  toast(`Removed ${f.name}`, "info", { action: "Undo", onAction: () => { S.files.splice(i, 0, f); S.sel = i; renderFiles(); } });
}

function moveFile(i, dir) {
  const plates = okFiles();
  const f = S.files[i], pos = plates.indexOf(f), other = plates[pos + dir];
  if (!other) return;
  const j = S.files.indexOf(other);
  [S.files[i], S.files[j]] = [S.files[j], S.files[i]];
  S.sel = j;
  renderFiles();
  announce(`${f.name} is now plate ${pos + dir + 1}`);
  $(`.file[data-i="${j}"] [data-act="${dir < 0 ? "up" : "down"}"]`)?.focus();
}

async function uploadOne(file, relpath, action = "ask") {
  const fd = new FormData();
  fd.append("file", file, file.name);
  if (relpath) fd.append("relpath", relpath);
  fd.append("on_conflict", action);
  return api("/api/files", { method: "POST", body: fd });
}

async function addFiles(items) {
  if (!items.length) return;
  const max = S.options.limits.max_upload_mb;
  const entries = items.map(({ file, relpath }) => ({ key: ++uid, name: relpath || file.name, uploading: true, file, relpath }));
  S.files.push(...entries);
  if (S.sel < 0) S.sel = S.files.indexOf(entries[0]);
  renderFiles();
  if (S.view === "result") showView("edit");
  let added = 0;
  for (const e of entries) {
    if (e.file.size > max * 1e6 * 1.048576) { Object.assign(e, { uploading: false, error: `larger than ${max} MB` }); renderFiles(); continue; }
    let action = "ask";
    for (;;) {
      try {
        const item = await uploadOne(e.file, e.relpath, action);
        const dup = S.files.find((f) => f !== e && f.path === item.path);
        if (dup) {
          S.files.splice(S.files.indexOf(e), 1);
          toast(`${item.name} is already in the project`, "info");
        } else {
          Object.assign(e, item, { uploading: false, file: null });
          added++;
        }
        break;
      } catch (err) {
        if (err.status === 409 && err.data && err.data.conflict) {
          action = await askConflict(err.data.conflict, "upload");
          if (action === "skip") { S.files.splice(S.files.indexOf(e), 1); break; }
          continue;
        }
        Object.assign(e, { uploading: false, error: err.message, file: null });
        break;
      }
    }
    if (S.sel >= S.files.length || S.sel < 0) S.sel = S.files.length - 1;
    renderFiles();
  }
  if (added) { announce(`${added} file${added > 1 ? "s" : ""} added`); refreshLibrary(); }
}

async function addFromLibrary(path) {
  const existing = S.files.findIndex((f) => f.path === path);
  if (existing >= 0) { selectFile(existing); return; }
  const e = { key: ++uid, name: path.slice(4), uploading: true };
  S.files.push(e); S.sel = S.files.length - 1; renderFiles();
  if (S.view === "result") showView("edit");
  try { Object.assign(e, await postJSON("/api/inspect", { path }), { uploading: false }); }
  catch (err) { Object.assign(e, { uploading: false, error: err.message }); }
  renderFiles();
}

// drag & drop: files, or folders (only the .stl files inside a folder are taken)
async function itemsFromDrop(dt) {
  const out = [];
  const walk = async (entry, path) => {
    if (entry.isFile) {
      const file = await new Promise((res, rej) => entry.file(res, rej));
      if (!path || /\.stl$/i.test(file.name)) out.push({ file, relpath: path ? path + file.name : null });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      let batch;
      do {
        batch = await new Promise((res, rej) => reader.readEntries(res, rej));
        for (const child of batch) await walk(child, (path || "") + entry.name + "/");
      } while (batch.length);
    }
  };
  const entries = [...dt.items].map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null));
  if (entries.some(Boolean)) {
    for (const entry of entries) if (entry) await walk(entry, "");
  } else {
    for (const file of dt.files) out.push({ file, relpath: null });
  }
  return out;
}

function bindFiles() {
  const fileInput = $("#fileInput"), folderInput = $("#folderInput");
  $$("[data-browse]").forEach((b) => b.addEventListener("click", () => (b.dataset.browse === "folder" ? folderInput : fileInput).click()));
  fileInput.addEventListener("change", () => { addFiles([...fileInput.files].map((file) => ({ file, relpath: null }))); fileInput.value = ""; });
  folderInput.addEventListener("change", () => {
    addFiles([...folderInput.files].filter((f) => /\.stl$/i.test(f.name)).map((file) => ({ file, relpath: file.webkitRelativePath })));
    folderInput.value = "";
  });
  let depth = 0;
  const veil = $("#dropVeil");
  const hasFiles = (e) => e.dataTransfer && [...e.dataTransfer.types].includes("Files");
  window.addEventListener("dragenter", (e) => { if (hasFiles(e)) { depth++; veil.hidden = false; } });
  window.addEventListener("dragleave", (e) => { if (hasFiles(e) && --depth <= 0) { depth = 0; veil.hidden = true; } });
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("drop", async (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault(); depth = 0; veil.hidden = true;
    addFiles(await itemsFromDrop(e.dataTransfer));
  });
  $("#fileList").addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    const i = +b.closest(".file").dataset.i;
    ({ select: () => selectFile(i), remove: () => removeFile(i), up: () => moveFile(i, -1), down: () => moveFile(i, 1) })[b.dataset.act]();
  });
  // reorder by dragging (the arrow buttons do the same from the keyboard)
  let dragFrom = -1;
  $("#fileList").addEventListener("dragstart", (e) => { const li = e.target.closest(".file"); dragFrom = li ? +li.dataset.i : -1; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", "reorder"); });
  $("#fileList").addEventListener("dragover", (e) => { if (dragFrom < 0) return; e.preventDefault(); e.stopPropagation(); $$(".file").forEach((x) => x.classList.toggle("drag-over", x === e.target.closest(".file"))); });
  $("#fileList").addEventListener("drop", (e) => {
    if (dragFrom < 0) return;
    e.preventDefault(); e.stopPropagation();
    const li = e.target.closest(".file");
    if (li) { const to = +li.dataset.i; const [f] = S.files.splice(dragFrom, 1); S.files.splice(to, 0, f); S.sel = to; }
    dragFrom = -1; renderFiles();
  });
  $("#fileList").addEventListener("dragend", () => { dragFrom = -1; $$(".file").forEach((x) => x.classList.remove("drag-over")); });
  $("#btnSample").addEventListener("click", async () => {
    const e = { key: ++uid, name: "3DBenchy.stl", uploading: true };
    S.files.push(e); S.sel = S.files.length - 1; renderFiles();
    try { Object.assign(e, await postJSON("/api/sample", {}), { uploading: false }); } catch (err) { Object.assign(e, { uploading: false, error: err.message }); }
    renderFiles(); refreshLibrary();
  });
  $("#libFilter").addEventListener("input", renderLibrary);
  $("#libList").addEventListener("click", (e) => { const b = e.target.closest("[data-path]"); if (b) addFromLibrary(b.dataset.path); });
}

async function refreshLibrary() {
  try {
    const lib = await api("/api/library");
    S.lib = lib.stl.files; S.libTotals = lib;
    renderLibrary();
  } catch { /* library is optional */ }
}

function renderLibrary() {
  const q = $("#libFilter").value.trim().toLowerCase();
  const inProject = new Set(S.files.map((f) => f.path));
  const items = S.lib.filter((f) => !q || f.path.toLowerCase().includes(q));
  $("#libCount").textContent = String(S.lib.length);
  $("#libList").innerHTML = items.length ? items.slice(0, 300).map((f) =>
    `<li><button type="button" data-path="${esc(f.path)}" title="Add ${esc(f.path)} to the project">${inProject.has(f.path) ? icon("check") : icon("plus")}<span class="nm">${esc(f.path.slice(4))}</span><span class="sz">${fmtBytes(f.size)}</span></button></li>`).join("")
    : `<li class="none">${S.lib.length ? "No match" : "Nothing saved yet"}</li>`;
  if (S.libTotals) {
    const t = S.libTotals;
    $("#libTotals").textContent = `On disk: stl/ ${fmtBytes(t.stl.total_bytes)} · 3mf/ ${fmtBytes(t["3mf"].total_bytes)} · gcode/ ${fmtBytes(t.gcode.total_bytes)}`;
  }
}

// ---------------------------------------------------------------- preview --
function renderPreview() {
  const f = S.files[S.sel];
  const show = f && f.path && !f.error;
  $("#stage").hidden = !show;
  $("#previewTitle").textContent = show ? (okFiles().length > 1 ? `Plate ${okFiles().indexOf(f) + 1} of ${okFiles().length}` : "Preview") : "Preview";
  const notices = [], stats = [];
  if (f && f.error) notices.push(["bad", "error", `${f.name} cannot be used`, f.error]);
  if (show && f.check) {
    const c = f.check;
    if (!c.fits) notices.push(["bad", "error", `${c.size_mm.map((x) => x.toFixed(0)).join(" × ")} mm is larger than the ${c.bed_mm[0]} × ${c.bed_mm[1]} × ${c.bed_mm[2]} mm build volume`, "The converter never scales a model. Scale it in your CAD tool or in Creality Print."]);
    if (!c.watertight) notices.push(["warn", "warn", `${c.open_edges + c.flipped_edges} open or inconsistent edges`, "The mesh is not watertight. Creality Print can usually repair it when slicing."]);
    if (c.tilted) notices.push(["warn", "warn", `The part stands at ${Math.round(c.tilt_deg)}° and touches the bed on about ${Math.round(c.bed_contact_mm2)} mm²`,
      "The converter keeps the STL orientation. Enable supports and a brim, or lay the part flat in Creality Print (“Lay on face”) before slicing.", true]);
    else if (c.bed_contact_mm2 < 100) notices.push(["info", "info", `Small contact with the bed (${Math.round(c.bed_contact_mm2)} mm²)`, "A brim helps it stay down."]);
    stats.push(["Size (mm)", c.size_mm.map((x) => x.toFixed(0)).join("×")], ["Volume", `${c.volume_cm3} cm³`],
      ["Bed contact", `${Math.round(c.bed_contact_mm2)} mm²`, c.bed_contact_mm2 < 100 ? "warn" : ""], ["Triangles", c.triangles.toLocaleString()]);
  }
  $("#notices").innerHTML = notices.map(([k, ic, title, body, fix]) =>
    `<div class="notice ${k}">${icon(ic)}<div><b>${esc(title)}</b>${esc(body)}${fix && !(S.support && S.brim) ? `<div><button type="button" class="btn small" data-fix="tilt">Turn on supports and a brim</button></div>` : ""}</div></div>`).join("");
  $("#stats").innerHTML = stats.map(([k, v, cls]) => `<div class="stat"><small>${k}</small><b class="${cls || ""}">${esc(v)}</b></div>`).join("");
  if (show) viewer.show(f); else viewer.clear();
}

// The printer bed (plane, 10 mm grid, outline) for both three.js views; Z is up.
function makeBed(THREE, w, d) {
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const group = new THREE.Group();
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(w, d), new THREE.MeshBasicMaterial({ color: css("--bed") }));
  plane.position.set(w / 2, d / 2, -0.05);
  group.add(plane);
  const pts = [];
  for (let x = 0; x <= w; x += 10) pts.push(x, 0, 0, x, d, 0);
  for (let y = 0; y <= d; y += 10) pts.push(0, y, 0, w, y, 0);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  group.add(new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: css("--grid") })));
  const edge = new THREE.BufferGeometry();
  edge.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, w, 0, 0, w, 0, 0, w, d, 0, w, d, 0, 0, d, 0, 0, d, 0, 0, 0, 0], 3));
  group.add(new THREE.LineSegments(edge, new THREE.LineBasicMaterial({ color: css("--muted") })));
  return group;
}

// three.js view, loaded lazily so the page works without WebGL
const viewer = (() => {
  let THREE, renderer, scene, camera, controls, loader, bedGroup, mesh, failed = false, ready = null, current = null, mode = "iso", token = 0;
  const canvas = $("#viewer"), msg = $("#stageMsg");
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const render = () => renderer && renderer.render(scene, camera);

  async function init() {
    try {
      THREE = await import("three");
      const { OrbitControls } = await import("three/OrbitControls");
      const { STLLoader } = await import("three/STLLoader");
      THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(2, devicePixelRatio));
      scene = new THREE.Scene();
      camera = new THREE.PerspectiveCamera(35, 1, 1, 5000);
      controls = new OrbitControls(camera, canvas);
      controls.enableDamping = false;
      controls.addEventListener("change", render);
      loader = new STLLoader();
      scene.add(new THREE.HemisphereLight(0xffffff, 0x404858, 1.6));
      const sun = new THREE.DirectionalLight(0xffffff, 1.6);
      sun.position.set(-120, -200, 320);
      scene.add(sun);
      buildBed();
      new ResizeObserver(resize).observe($("#stage"));
      resize();
    } catch (e) {
      failed = true;
      msg.hidden = false;
      msg.textContent = "The 3D view is not available in this browser (WebGL is off). The checks and the conversion still work.";
    }
  }

  function buildBed() {
    if (bedGroup) scene.remove(bedGroup);
    const [w, d] = S.options ? S.options.bed_mm : [220, 220];
    bedGroup = makeBed(THREE, w, d);
    scene.add(bedGroup);
  }

  function resize() {
    if (!renderer) return;
    const r = $("#stage").getBoundingClientRect();
    if (!r.width || !r.height) return;
    renderer.setSize(r.width, r.height, false);
    camera.aspect = r.width / r.height;
    camera.updateProjectionMatrix();
    render();
  }

  function frame() {
    const [w, d] = S.options ? S.options.bed_mm : [220, 220];
    const h = mesh ? mesh.userData.height : 20;
    const target = new THREE.Vector3(w / 2, d / 2, h / 3);
    const dist = Math.max(w, d) * 1.55;
    controls.target.copy(target);
    if (mode === "top") camera.position.set(w / 2, d / 2 - 0.01, dist * 1.25);
    else camera.position.set(w / 2 - dist * 0.45, d / 2 - dist * 0.75, dist * 0.62);
    camera.lookAt(target);
    controls.update();
    render();
  }

  async function show(f) {
    if (!ready) ready = init();
    await ready;
    if (failed) return;
    if (current === f.path && mesh) { setColour(); resize(); return; }
    const my = ++token;
    current = f.path;
    msg.hidden = false; msg.textContent = "Loading 3D view…";
    try {
      const buf = await (await fetch(`/api/file?path=${enc(f.path)}`)).arrayBuffer();
      if (my !== token) return;
      const geo = loader.parse(buf);
      geo.computeBoundingBox();
      const b = geo.boundingBox;
      const [w, d] = S.options.bed_mm;
      geo.translate(w / 2 - (b.min.x + b.max.x) / 2, d / 2 - (b.min.y + b.max.y) / 2, -b.min.z);
      if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); }
      mesh = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ color: partColour(), roughness: 0.6, metalness: 0 }));
      mesh.userData.height = b.max.z - b.min.z;
      scene.add(mesh);
      msg.hidden = true;
      resize(); frame();
    } catch (e) {
      msg.textContent = `Cannot show this model: ${e.message}`;
    }
  }

  function clear() { if (mesh && scene) { scene.remove(mesh); mesh = null; current = null; render(); } }
  function partColour() { return (S.options.materials.find((m) => m.name === S.material) || {}).colour || "#F2754E"; }
  function setColour() { if (mesh) { mesh.material.color.set(partColour()); render(); } }
  function setMode(m) { mode = m; if (renderer) frame(); }
  function themeChanged() { if (scene) { buildBed(); render(); } }
  return { show, clear, setColour, setMode, themeChanged };
})();

function bindTabs() {
  const tabs = $$('#previewPane [role="tab"]');
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => {
      tabs.forEach((x) => x.setAttribute("aria-selected", String(x === t)));
      viewer.setMode(t.dataset.view);
    });
    t.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const n = tabs[(i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
      n.focus(); n.click();
    });
  });
  $("#notices").addEventListener("click", (e) => {
    if (!e.target.closest('[data-fix="tilt"]')) return;
    if (!S.support) $("#support").click();
    if (!S.brim) $("#brim").click();
    toast("Supports and a brim are on", "ok");
    renderPreview();
  });
}

// ----------------------------------------------------------- convert/slice --
function showView(v) {
  S.view = v;
  const result = v === "result";
  $("#main").classList.toggle("show-result", result);
  $("#resultPane").hidden = !result;
  $("#previewPane").hidden = result;
  $("#settingsPane").hidden = result;
  renderStepper();
  if (!result) setTimeout(() => window.dispatchEvent(new Event("resize")), 0);
}

function renderStepper() {
  const hasFiles = okFiles().length > 0;
  const steps = { 1: $('[data-step="1"]'), 2: $('[data-step="2"]'), 3: $('[data-step="3"]') };
  Object.values(steps).forEach((s) => { s.classList.remove("cur", "done"); s.removeAttribute("aria-current"); });
  const set = (n, cls) => { steps[n].classList.add(cls); if (cls === "cur") steps[n].setAttribute("aria-current", "step"); };
  if (!hasFiles) set(1, "cur");
  else if (S.view === "result") { set(1, "done"); set(2, "done"); set(3, "cur"); }
  else { set(1, "done"); set(2, "cur"); if (S.project) set(3, "done"); }
  steps[1].querySelector("i").textContent = steps[1].classList.contains("done") ? "✓" : "1";
  steps[2].querySelector("i").textContent = steps[2].classList.contains("done") ? "✓" : "2";
  steps[3].querySelector("i").textContent = steps[3].classList.contains("done") ? "✓" : "3";
  steps[3].disabled = !S.project;
}

async function doConvert(andSlice) {
  if (S.busy) return;
  if (!validateAll()) return;
  const btn = andSlice ? $("#btnSlice") : $("#btnConvert");
  S.busy = true;
  setBusy(btn, true, "Converting…");
  announce("Converting");
  const req = buildRequest();
  let res = null;
  try {
    try {
      res = await postJSON("/api/convert", { ...req, on_conflict: "ask" });
    } catch (err) {
      if (err.status !== 409 || !err.data || !err.data.conflict) throw err;
      const action = await askConflict(err.data.conflict, "project");
      if (action === "skip") { toast("Nothing was saved", "info"); return; }
      res = await postJSON("/api/convert/resolve", { token: err.data.token, action });
    }
  } catch (err) {
    toast(`Conversion failed: ${err.message}`, "bad");
    return;
  } finally {
    S.busy = false;
    setBusy(btn, false);
  }
  S.project = res; S.job = null; S.results = null; S.lastConvertKey = JSON.stringify(req);
  showView("result");
  renderResult();
  $("#resultTitle").focus?.();
  toast(res.reused_existing ? `Up to date: ${res.path}` : `Saved ${res.path}`, "ok");
  refreshLibrary();
  if (andSlice) startSlice();
}

let pollTimer = null;
async function startSlice(action = "ask") {
  if (!S.project) return;
  clearTimeout(pollTimer);
  S.results = null;
  S.job = { state: "starting", plate: 0, plates: S.project.plates };
  renderResult();
  refreshSlicer();
  try {
    const starting = S.job;   // a Cancel click during this request marks this object
    const job = await postJSON("/api/slice", { project: S.project.path, on_conflict: action });
    S.job = starting.cancelRequested ? await postJSON(`/api/jobs/${job.id}/cancel`, {}) : job;
  } catch (err) {
    S.job = { state: "error", error: err.message, code: err.code };
    renderResult();
    refreshSlicer();
    return;
  }
  renderResult();
  poll();
}

async function poll() {
  try {
    S.job = await api(`/api/jobs/${S.job.id}`);
  } catch (err) {
    S.job = { state: "error", error: err.message };
  }
  if (S.job.state === "conflict") {
    const action = await askConflict(S.job.conflicts[0], "G-code");
    if (action === "skip") S.job = await postJSON(`/api/jobs/${S.job.id}/cancel`, {});
    else S.job = await postJSON(`/api/jobs/${S.job.id}/resolve`, { action });
  }
  if (S.job.state === "done") {
    S.results = S.job.results;
    layers.invalidate();   // a re-slice may have replaced the same G-code file
    refreshSlicer();
    toast(`Sliced: ${fmtTime(S.results.reduce((a, r) => a + (r.time_s || 0), 0))} print time`, "ok");
    refreshLibrary();
  }
  renderResult();
  if (["queued", "running", "starting"].includes(S.job.state)) pollTimer = setTimeout(poll, 700);
}

function renderResult() {
  const p = S.project;
  if (!p) return;
  const slicerOk = S.slicer && S.slicer.available;
  // slicing card
  let html = "";
  const j = S.job;
  if (S.results) {
    const r = S.results, total = r.reduce((a, x) => a + (x.time_s || 0), 0), fil = r.reduce((a, x) => a + (x.filament_m || 0), 0);
    const checks = r.flatMap((x) => x.checks.map((c) => ({ ...c, text: (r.length > 1 ? `Plate ${x.plate}: ` : "") + c.text })));
    const warns = (p.warnings || []).map((w) => ({ ok: false, text: w }));
    html = `<h3 class="rtitle">${icon("check", "ok")}Sliced by ${esc((r[0].generator || "Creality Print").replace("_", " "))}</h3>
      <div class="stats">
        <div class="stat"><small>Print time</small><b>${fmtTime(total)}</b></div>
        <div class="stat"><small>Filament</small><b>${fil.toFixed(2)} m</b></div>
        <div class="stat"><small>Layers</small><b>${r.map((x) => x.layers).join(" + ")}</b></div>
        <div class="stat"><small>Height</small><b>${Math.max(...r.map((x) => x.max_z_mm || 0)).toFixed(1)} mm</b></div>
      </div>
      <ul class="checks" aria-label="Settings check">${[...checks, ...warns].map((c) => `<li class="${c.ok ? "ok" : "warn"}">${icon(c.ok ? "check" : "warn")}<span>${esc(c.text)}</span></li>`).join("")}</ul>
      ${r.length > 1 ? `<dl class="kvlist" style="margin-top:12px">${r.map((x) => `<dt>Plate ${x.plate}</dt><dd>${fmtTime(x.time_s)} · ${x.filament_m.toFixed(2)} m · ${x.layers} layers</dd>`).join("")}</dl>` : ""}
      <div class="btnrow" style="margin-top:12px"><button type="button" class="btn small" data-act="reslice">Slice again</button></div>`;
  } else if (j && ["starting", "queued", "running"].includes(j.state)) {
    const pct = j.plates ? Math.max(5, ((Math.max(1, j.plate) - 1) / j.plates) * 100) : 5;
    html = `<h3 class="rtitle"><span class="spin" aria-hidden="true"></span>Slicing${j.plates > 1 ? ` plate ${Math.max(1, j.plate)} of ${j.plates}` : ""}…</h3>
      <div class="prog ${j.plates > 1 ? "" : "indet"}" role="progressbar" aria-label="Slicing progress" aria-valuemin="0" aria-valuemax="${j.plates || 1}" aria-valuenow="${Math.max(0, (j.plate || 1) - 1)}"><i style="width:${pct}%"></i></div>
      <p class="hint">Creality Print command line · usually 2–10 s per plate</p>
      <div class="btnrow" style="margin-top:8px"><button type="button" class="btn small ghost" data-act="cancel" ${j.cancelRequested ? "disabled" : ""}>${j.cancelRequested ? "Cancelling…" : "Cancel"}</button></div>
      <div class="notice info" style="margin-top:12px">${icon("info")}<div><b>The 3MF is saved already</b>You can download it while slicing runs.</div></div>`;
  } else if (j && ["error", "cancelled"].includes(j.state)) {
    const open = j.code === "slicer_open";
    html = `<h3 class="rtitle">${icon(j.state === "cancelled" ? "info" : "error", j.state === "cancelled" ? "acc" : "bad")}${j.state === "cancelled" ? "Slicing cancelled" : open ? "Creality Print is open" : "Slicing failed"}</h3>
      <div class="notice ${j.state === "cancelled" ? "info" : "bad"}">${icon(j.state === "cancelled" ? "info" : "error")}<div>${esc(j.error || "")}</div></div>
      <div class="btnrow" style="margin-top:12px"><button type="button" class="btn small" data-act="reslice">${open ? "Retry" : "Slice again"}</button></div>`;
  } else {
    html = `<h3 class="rtitle">${icon("layers", "acc")}Not sliced yet</h3>
      <p class="hint" style="margin-bottom:12px">Slicing with the Creality Print command line gives the real print time, a settings check and a layer preview.</p>
      ${slicerOk ? `<button type="button" class="btn primary" data-act="reslice">${icon("layers")}Slice with Creality Print</button>`
        : `<div class="notice warn">${icon("warn")}<div><b>Creality Print not found</b>Install it, or set CREALITY_PRINT to its executable and restart the server.</div></div>`}
      ${(p.warnings || []).length ? `<ul class="checks">${p.warnings.map((w) => `<li class="warn">${icon("warn")}<span>${esc(w)}</span></li>`).join("")}</ul>` : ""}`;
  }
  $("#sliceCard").innerHTML = html;

  // saved files card
  const stls = S.files.filter((f) => f.path && !f.error);
  const g = S.results || [];
  $("#savedCard").innerHTML = `<h3 class="rtitle">${icon("download", "acc")}Saved in the project folder</h3>
    <dl class="kvlist">
      <dt>STL</dt><dd>${stls.slice(0, 3).map((f) => esc(f.path)).join("<br>")}${stls.length > 3 ? `<br>+ ${stls.length - 3} more` : ""}</dd>
      <dt>Project</dt><dd>${esc(p.path)} · ${fmtBytes(p.size)}</dd>
      ${g.map((x) => `<dt>G-code</dt><dd>${esc(x.gcode)} · ${fmtBytes(x.size)}</dd>`).join("")}
    </dl>
    <div class="btnrow">
      ${g.map((x, i) => `<a class="btn ${i === 0 ? "primary" : ""}" href="/api/file?path=${enc(x.gcode)}&download=1" download>${icon("download")}G-code${g.length > 1 ? ` plate ${x.plate}` : ""}${i === 0 ? ` <kbd class="kbd">${isMac ? "⌘" : "Ctrl "}S</kbd>` : ""}</a>`).join("")}
      <a class="btn ${g.length ? "" : "primary"}" href="/api/file?path=${enc(p.path)}&download=1" download>${g.length ? "" : icon("download")}3MF project${g.length ? "" : ` <kbd class="kbd">${isMac ? "⌘" : "Ctrl "}S</kbd>`}</a>
      <button type="button" class="btn ghost" data-open="3mf">Open 3mf/</button>
      ${g.length ? `<button type="button" class="btn ghost" data-open="gcode">Open gcode/</button>` : ""}
    </div>`;

  // plate thumbnails
  const names = p.plate_info ? p.plate_info.map((x) => x.name) : [];
  $("#platesCard").innerHTML = `<h3 class="rtitle">${p.plates > 1 ? `${p.plates} plates` : "Plate"}</h3>
    <div class="thumbs">${p.thumbs.map((t, i) => `<figure><img src="${t}&v=${Math.round(p.mtime)}" alt="Plate ${i + 1}${names[i] ? `: ${esc(names[i])}` : ""}" loading="lazy"><figcaption>${i + 1}. ${esc(names[i] || "")}</figcaption></figure>`).join("")}</div>`;

  // layer preview
  const lc = $("#layerCard");
  lc.hidden = !g.length;
  if (g.length) {
    const sel = $("#layerPlate");
    sel.hidden = g.length < 2;
    sel.innerHTML = g.map((x) => `<option value="${esc(x.gcode)}">Plate ${x.plate}</option>`).join("");
    if (layers.path !== g[0].gcode && !g.some((x) => x.gcode === layers.path)) layers.load(g[0].gcode);
    else sel.value = layers.path;
  }
  renderStepper();
}

function bindResult() {
  $("#btnBack").addEventListener("click", () => { showView("edit"); $("#settingsTitle").scrollIntoView({ block: "nearest" }); });
  $("#resultPane").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-act],[data-open]");
    if (!b) return;
    if (b.dataset.open) { try { await postJSON("/api/open", { folder: b.dataset.open }); } catch (err) { toast(err.message, "bad"); } return; }
    if (b.dataset.act === "reslice") startSlice();
    if (b.dataset.act === "cancel" && S.job) {
      S.job.cancelRequested = true;          // also honoured if the job id has not arrived yet
      renderResult();
      if (S.job.id) { S.job = await postJSON(`/api/jobs/${S.job.id}/cancel`, {}); renderResult(); }
    }
  });
  $("#btnConvert").addEventListener("click", () => doConvert(false));
  $("#btnSlice").addEventListener("click", () => doConvert(true));
  $$(".step").forEach((s) => s.addEventListener("click", () => {
    const n = s.dataset.step;
    if (n === "1") { showView("edit"); ($("#dropSmall").hidden ? $("#dropBig") : $("#dropSmall")).querySelector("button").focus(); }
    if (n === "2") { showView("edit"); $("#materialSeg input:checked")?.focus(); }
    if (n === "3" && S.project) showView("result");
  }));
}

// ------------------------------------------------------------- layer view --
const COLOURS = {
  "Outer wall": "#E7782A", "Inner wall": "#F0C43C", "Overhang wall": "#4FD1C5", "Sparse infill": "#B04848",
  "Internal solid infill": "#B85AC8", "Top surface": "#F05A5A", "Bottom surface": "#C8A078", "Bridge": "#5AD2E6",
  "Gap infill": "#D0D0D0", "Support": "#3CC86A", "Support interface": "#3C78FF", "Support transition": "#2E9E58",
  "Brim": "#8C8C8C", "Skirt": "#8C8C8C",
};
// 3D toolpaths: every extrusion segment up to the selected layer, current layer at full colour.
const tool3d = (() => {
  let THREE, renderer, scene, camera, controls, bed, ready = null, failed = false, data = null, loaded = null, layer = 0;
  let objs = {};
  const canvas = $("#toolCanvas"), msg = $("#toolMsg");
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const render = () => renderer && renderer.render(scene, camera);

  async function init() {
    try {
      THREE = await import("three");
      const { OrbitControls } = await import("three/OrbitControls");
      THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
      renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(2, devicePixelRatio));
      scene = new THREE.Scene();
      camera = new THREE.PerspectiveCamera(35, 1, 0.5, 5000);
      controls = new OrbitControls(camera, canvas);
      controls.enableDamping = false;
      controls.addEventListener("change", render);
      buildBed();
      new ResizeObserver(resize).observe(canvas.parentElement);
    } catch (e) {
      failed = true;
      msg.hidden = false;
      msg.textContent = "The 3D view is not available in this browser (WebGL is off). Use the Layer view.";
    }
  }

  function buildBed() {
    if (bed) scene.remove(bed);
    const [w, d] = S.options ? S.options.bed_mm : [220, 220];
    bed = makeBed(THREE, w, d);
    scene.add(bed);
  }

  function resize() {
    if (!renderer || canvas.hidden) return;
    const r = canvas.parentElement.getBoundingClientRect();
    if (!r.width || !r.height) return;
    renderer.setSize(r.width, r.height, false);
    camera.aspect = r.width / r.height;
    camera.updateProjectionMatrix();
    render();
  }

  function clearObjects() {
    for (const o of Object.values(objs)) {
      scene.remove(o.below, o.cur);
      o.below.geometry.dispose(); o.cur.geometry.dispose();
      o.below.material.dispose(); o.cur.material.dispose();
    }
    objs = {};
  }

  function build(d) {
    clearObjects();
    for (const [type, e] of Object.entries(d.types)) {
      if (!e.pos.length) continue;
      const attr = new THREE.BufferAttribute(new Float32Array(e.pos), 3);
      const g1 = new THREE.BufferGeometry(), g2 = new THREE.BufferGeometry();   // same vertices, own draw ranges
      g1.setAttribute("position", attr); g2.setAttribute("position", attr);
      const colour = new THREE.Color(COLOURS[type] || css("--muted"));
      const below = new THREE.LineSegments(g1, new THREE.LineBasicMaterial({ color: colour.clone().multiplyScalar(0.5) }));
      const cur = new THREE.LineSegments(g2, new THREE.LineBasicMaterial({ color: colour }));
      objs[type] = { below, cur, ends: e.ends };
      scene.add(below, cur);
    }
    data = d;
  }

  function frame() {
    const [x0, y0, x1, y1] = data.bbox, h = data.max_z || 10;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const span = Math.max(x1 - x0, y1 - y0, h, 20);
    const dist = span * 1.45 + 20;
    controls.target.set(cx, cy, h / 3);
    camera.position.set(cx - dist * 0.5, cy - dist * 0.8, h / 3 + dist * 0.55);
    camera.lookAt(controls.target);
    controls.update();
  }

  function apply() {
    if (!data) return;
    for (const [type, o] of Object.entries(objs)) {
      const end = o.ends[layer] || 0, prev = layer > 0 ? o.ends[layer - 1] || 0 : 0;
      o.below.geometry.setDrawRange(0, prev);
      o.cur.geometry.setDrawRange(prev, end - prev);
      o.below.visible = o.cur.visible = !S.hiddenTypes.has(type);
    }
    render();
  }

  async function load(path) {
    if (!ready) ready = init();
    await ready;
    if (failed) return;
    resize();
    if (loaded === path && data) { apply(); return; }
    msg.hidden = false; msg.textContent = "Loading toolpaths…";
    let d;
    try { d = await api(`/api/gcode/toolpaths?path=${enc(path)}`); }
    catch (err) { msg.textContent = `Cannot load the toolpaths: ${err.message}`; return; }
    if (layers.path !== path) return;   // the plate changed meanwhile
    build(d);
    loaded = path;
    msg.hidden = true;
    frame(); apply();
  }

  function setLayer(i) { layer = i; apply(); }
  function show(on) { canvas.hidden = !on; if (!on) msg.hidden = true; else resize(); }
  function themeChanged() { if (scene) { buildBed(); render(); } }
  function forget() { loaded = null; data = null; if (scene) { clearObjects(); render(); } }
  return { load, setLayer, show, themeChanged, forget, refresh: apply };
})();

// Layer preview controller: one slider for the 2D layer view and the 3D toolpath view.
const layers = (() => {
  const canvas = $("#layerCanvas"), slider = $("#layerSlider");
  let meta = null, cache = new Map(), path = null, drawing = 0, mode = "2d", shown3d = null;
  const get = (i) => { if (!cache.has(i)) cache.set(i, api(`/api/gcode/layer?path=${enc(path)}&i=${i}`)); return cache.get(i); };

  function renderLegend() {
    $("#legend").innerHTML = meta.types.filter((t) => COLOURS[t]).map((t) =>
      `<button type="button" data-type="${esc(t)}" aria-pressed="${!S.hiddenTypes.has(t)}" style="--c:${COLOURS[t]}">${esc(t)}</button>`).join("")
      + `<span style="--c:var(--muted)">${mode === "3d" ? "Earlier layers are darker" : "Layers below"}</span>`;
  }

  function info() {
    const i = +slider.value, z = meta.z[i];
    $("#layerInfo").textContent = `layer ${i + 1} / ${meta.count} · z ${z != null ? z.toFixed(2) : "?"}`;
    slider.setAttribute("aria-valuetext", `Layer ${i + 1} of ${meta.count}, height ${z} millimetres`);
  }

  async function load(p) {
    path = p; cache = new Map();
    try { meta = await api(`/api/gcode/meta?path=${enc(p)}`); } catch (err) { $("#layerInfo").textContent = err.message; return; }
    slider.max = String(meta.count - 1);
    slider.value = String(mode === "3d" ? meta.count - 1 : Math.round((meta.count - 1) * 0.35));
    if (mode === "3d") shown3d = p;
    renderLegend();
    update();
  }

  function update() {
    if (!meta) return;
    info();
    if (mode === "3d") tool3d.load(path).then(() => tool3d.setLayer(+slider.value));
    else draw();
  }

  async function draw() {
    if (!meta || mode !== "2d") return;
    const i = +slider.value, my = ++drawing;
    const want = [i - 3, i - 2, i - 1, i].filter((x) => x >= 0);
    const data = await Promise.all(want.map(get));
    if (my !== drawing) return;
    const dpr = Math.min(2, devicePixelRatio), r = canvas.getBoundingClientRect();
    canvas.width = Math.max(1, Math.round(r.width * dpr)); canvas.height = Math.max(1, Math.round(r.height * dpr));
    const ctx = canvas.getContext("2d");
    const [x0, y0, x1, y1] = meta.bbox, pad = 16 * dpr;
    const sc = Math.min((canvas.width - 2 * pad) / Math.max(1, x1 - x0), (canvas.height - 2 * pad) / Math.max(1, y1 - y0));
    const ox = (canvas.width - (x1 - x0) * sc) / 2, oy = (canvas.height - (y1 - y0) * sc) / 2;
    const tx = (x) => ox + (x - x0) * sc, ty = (y) => canvas.height - (oy + (y - y0) * sc);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    const muted = getComputedStyle(document.documentElement).getPropertyValue("--muted").trim();
    data.forEach((layer, k) => {
      const current = k === data.length - 1;
      ctx.globalAlpha = current ? 1 : 0.18;
      ctx.lineWidth = Math.max(1, (current ? 0.42 : 0.3) * sc);
      for (const [type, polys] of Object.entries(layer.paths)) {
        if (S.hiddenTypes.has(type)) continue;
        ctx.strokeStyle = current ? COLOURS[type] || muted : muted;
        ctx.beginPath();
        for (const p of polys) {
          ctx.moveTo(tx(p[0]), ty(p[1]));
          for (let n = 2; n < p.length; n += 2) ctx.lineTo(tx(p[n]), ty(p[n + 1]));
        }
        ctx.stroke();
      }
    });
    ctx.globalAlpha = 1;
  }

  function setMode(m) {
    mode = m;
    $$('#layerCard [role="tab"]').forEach((t) => t.setAttribute("aria-selected", String(t.dataset.lv === m)));
    $("#layerView").classList.toggle("is3d", m === "3d");
    canvas.hidden = m === "3d";
    tool3d.show(m === "3d");
    $("#layerHint").textContent = m === "3d"
      ? "Drag to rotate, scroll to zoom, right-drag (or Shift-drag) to pan. The slider sets the top layer. Click a legend entry to hide that path type."
      : "Arrow keys move one layer, Page Up / Page Down jump further. Click a legend entry to hide that path type. Drawn from the G-code.";
    if (meta && m === "3d" && shown3d !== path) {   // first time in 3D for this G-code: show the whole print
      slider.value = slider.max;
      shown3d = path;
    }
    if (meta) { renderLegend(); update(); }
  }

  slider.addEventListener("input", () => { if (!meta) return; info(); mode === "3d" ? tool3d.setLayer(+slider.value) : draw(); });
  $("#layerPlate").addEventListener("change", (e) => load(e.target.value));
  $$('#layerCard [role="tab"]').forEach((t, i, all) => {
    t.addEventListener("click", () => setMode(t.dataset.lv));
    t.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const n = all[(i + 1) % all.length]; n.focus(); n.click();
    });
  });
  $("#legend").addEventListener("click", (e) => {
    const b = e.target.closest("[data-type]");
    if (!b) return;
    const t = b.dataset.type;
    S.hiddenTypes.has(t) ? S.hiddenTypes.delete(t) : S.hiddenTypes.add(t);
    b.setAttribute("aria-pressed", String(!S.hiddenTypes.has(t)));
    mode === "3d" ? tool3d.refresh() : draw();
  });
  new ResizeObserver(() => meta && mode === "2d" && draw()).observe(canvas);
  return { load, draw, invalidate() { path = null; meta = null; cache = new Map(); tool3d.forget(); }, get path() { return path; } };
})();

// ------------------------------------------------------------ app chrome --
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("theme", t); } catch { /* private mode */ }
  const next = t === "dark" ? "light" : "dark";
  $("#btnTheme").setAttribute("aria-label", `Switch to ${next} theme`);
  $("#btnTheme use").setAttribute("href", t === "dark" ? "#i-sun" : "#i-moon");
  viewer.themeChanged();
  tool3d.themeChanged();
  layers.draw();
}

async function refreshSlicer() {
  try { S.slicer = { ...S.slicer, ...(await api("/api/slicer")) }; } catch { return; }
  const chip = $("#slicerChip"), s = S.slicer;
  chip.className = "chip " + (!s.available ? "bad" : s.gui_running ? "warn" : "ok");
  chip.innerHTML = `<span class="dot" aria-hidden="true"></span>${!s.available ? "Creality Print not found" : s.gui_running ? "Creality Print is open: close it to slice" : `Creality Print ${esc(s.version || "")} ready`}`;
  $("#btnSlice").hidden = !s.available;
}

function bindKeys() {
  document.addEventListener("keydown", (e) => {
    const mod = isMac ? e.metaKey : e.ctrlKey;
    const typing = e.target.matches("input, select, textarea") && e.target.type !== "range";
    if (document.querySelector("dialog[open]")) return;
    if (mod && e.key.toLowerCase() === "o") { e.preventDefault(); $("#fileInput").click(); return; }
    if (mod && e.key === "Enter") { e.preventDefault(); doConvert(e.shiftKey && S.slicer && S.slicer.available); return; }
    if (mod && e.key.toLowerCase() === "s") {
      e.preventDefault();
      const href = S.results && S.results.length ? `/api/file?path=${enc(S.results[0].gcode)}&download=1` : S.project ? `/api/file?path=${enc(S.project.path)}&download=1` : null;
      if (href) { const a = document.createElement("a"); a.href = href; a.download = ""; document.body.append(a); a.click(); a.remove(); }
      else toast("Nothing to download yet: convert first", "info");
      return;
    }
    if (typing) return;
    if (e.key === "?") { e.preventDefault(); $("#dlgShortcuts").showModal(); return; }
    if (e.key === "Delete" && S.view === "edit" && S.sel >= 0 && S.files[S.sel] && !e.target.closest("#settingsPane")) {
      e.preventDefault(); removeFile(S.sel);
    }
  });
  window.addEventListener("beforeunload", (e) => {
    if (okFiles().length && requestKey() !== S.lastConvertKey) { e.preventDefault(); e.returnValue = ""; }
  });
  window.addEventListener("focus", refreshSlicer);
}

async function main() {
  $("#btnTheme").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));
  $("#btnShortcuts").addEventListener("click", () => $("#dlgShortcuts").showModal());
  $$("kbd.kbd").forEach((k) => { if (!isMac) k.textContent = k.textContent.replace("⌘", "Ctrl "); });
  setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");
  try {
    S.options = await api("/api/options");
  } catch (err) {
    toast(`Cannot reach the server: ${err.message}`, "bad");
    return;
  }
  S.slicer = S.options.slicer;
  $("#printerChip").textContent = S.options.printer.replace("Creality ", "");
  buildSettingsControls();
  bindSettings(); bindFiles(); bindTabs(); bindResult(); bindKeys();
  applyDefaults(); renderKv(); onSettingsChanged(); renderFiles();
  refreshSlicer(); refreshLibrary();
}

main();
