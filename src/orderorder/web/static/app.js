const $ = (id) => document.getElementById(id);
let job = null, verdicts = [], chosen = null;

// ---------- status ----------
fetch("/api/health").then(r => r.json()).then(h => {
  const bits = [`${h.judgments_with_text.toLocaleString()} judgments`];
  // "configured", not "reachable": the health route reads a key, it does not make a call, and a
  // key for a provider that is down reads exactly the same as one that works.
  bits.push(h.model_configured ? "model configured" : "no model configured");
  $("status").textContent = bits.join(" · ");
  if (!h.model_configured) $("usemodel").checked = false;
}).catch(() => $("status").textContent = "the server is not answering");

// A judgment's date, in the reader's locale rather than the server's format.
function decided(iso) {
  if (!iso) return "";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return iso;
  return new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" })
    .format(when);
}

// Each surface's object -- the bundle, the shelf, the tome -- leans a few degrees toward the pointer.
// Two custom properties set through the CSSOM, which the Content-Security-Policy permits (it governs
// style attributes and stylesheets, not property writes) and which is the one carve-out from "no
// inline styles", recorded in DESIGN.md. Nothing happens for a coarse pointer or for anyone who has
// asked for less motion.
(() => {
  const fine = matchMedia("(pointer: fine)").matches;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (!fine || still) return;
  for (const object of document.querySelectorAll(".block > .object")) {
    const block = object.parentElement;
    block.addEventListener("pointermove", (e) => {
      const r = block.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width - .5;    // -.5 .. .5
      const y = (e.clientY - r.top) / r.height - .5;
      object.style.setProperty("--tx", `${(x * 10).toFixed(2)}deg`);
      object.style.setProperty("--ty", `${(-y * 8).toFixed(2)}deg`);
    });
    block.addEventListener("pointerleave", () => {
      object.style.setProperty("--tx", "0deg");
      object.style.setProperty("--ty", "0deg");
    });
  }
})();

// The bar stays. A hairline appears under it once the page has moved, so that it reads as a bar and
// not as a strip of the page that failed to scroll.
(() => {
  let queued = false;
  const mark = () => { queued = false; document.body.dataset.scrolled = scrollY > 8 ? "1" : "0"; };
  addEventListener("scroll", () => { if (!queued) { queued = true; requestAnimationFrame(mark); } }, { passive: true });
  mark();
})();

// ---------- surfaces ----------
const SURFACES = ["check", "find", "draft"];
let surface = "check", swapping = 0;

// Changing surface is a crossfade, not a cut. The words on the block that is leaving go first; then
// the sections swap, and the new block starts in the old block's colour and turns into its own. Three
// attributes on <body> are the whole mechanism: `data-surface` moves the thumb, `data-leaving` fades
// the outgoing words, `data-prev` tells the stylesheet which colour to start from. No style is written.
// Under prefers-reduced-motion, and on arrival from a link, the swap is immediate.
function showTab(which, instant) {
  if (which === surface && !instant) return;
  const prev = surface;
  surface = which;
  for (const name of SURFACES) {
    const tab = $("tab-" + name);
    const on = which === name;
    tab.classList.toggle("on", on);
    // The class is what a sighted reader sees; this is what everyone else gets told.
    tab.setAttribute("aria-selected", String(on));
  }
  document.body.dataset.surface = which;
  // The surface is part of where you are, so it belongs in the URL: reloading, or sending somebody
  // the link, should not drop them back on the first tab.
  if (location.hash.slice(1) !== which) history.replaceState(null, "", "#" + which);

  const swap = () => {
    for (const name of SURFACES) $("view-" + name).hidden = name !== which;
    delete document.body.dataset.leaving;
    if (!instant) document.body.dataset.prev = prev;
  };
  clearTimeout(swapping);
  if (instant || matchMedia("(prefers-reduced-motion: reduce)").matches) { swap(); return; }
  // The thumb's squash is a class put back on, so it plays again for every change.
  const thumb = document.querySelector(".tabs .thumb");
  if (thumb) { thumb.classList.remove("moving"); void thumb.offsetWidth; thumb.classList.add("moving"); }
  document.body.dataset.leaving = "1";
  swapping = setTimeout(swap, 160);
}
$("tab-check").onclick = () => showTab("check");
$("tab-find").onclick = () => showTab("find");
$("tab-draft").onclick = () => showTab("draft");
if (SURFACES.includes(location.hash.slice(1))) showTab(location.hash.slice(1), true);
// The URL is the surface, so the browser's back button and a hash typed by hand both count.
addEventListener("hashchange", () => { if (SURFACES.includes(location.hash.slice(1))) showTab(location.hash.slice(1)); });

function showPanel(which) {
  for (const [tab, panel] of [["t-detail","detail"],["t-judgment","judgment"],["t-memo","memo"]]) {
    const on = panel === which;
    $(tab).classList.toggle("on", on);
    $(panel).hidden = !on;
  }
}
$("t-detail").onclick = () => showPanel("detail");
$("t-judgment").onclick = () => { showPanel("judgment"); loadJudgment(); };
$("t-memo").onclick = () => { showPanel("memo"); loadMemo(); };

// ---------- checking ----------
$("demo").onclick = () => { $("brief").value = DEMO; $("upnote").hidden = true; };

// A file is read into the box rather than checked straight away: what gets checked is what the
// reader can see, so a mangled extraction is obvious in a second instead of arriving as nine
// inexplicable phantom citations.
$("pick").onclick = () => $("file").click();
$("file").onchange = async () => {
  const chosen = $("file").files[0];
  if (!chosen) return;
  $("pick").disabled = true;
  $("prog").textContent = `reading ${chosen.name}…`;
  const form = new FormData();
  form.append("file", chosen);
  try {
    const response = await fetch("/api/upload", { method: "POST", body: form });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    $("brief").value = body.text;
    const bits = [`${chosen.name} — ${body.text.length.toLocaleString()} characters`];
    if (body.pages) bits.push(`${body.pages} pages`);
    if (body.note) bits.push(body.note);
    $("upnote").textContent = bits.join(" · ");
    $("upnote").hidden = false;
    $("prog").textContent = "read it — check what is in the box";
  } catch (e) {
    $("upnote").textContent = String(e.message || e);
    $("upnote").hidden = false;
    $("prog").textContent = "";
  }
  $("pick").disabled = false;
  $("file").value = "";
};

$("go").onclick = async () => {
  const text = $("brief").value.trim();
  if (!text) return;
  working("go", "Checking…");
  verdicts = []; chosen = null;
  $("summary").textContent = "";
  $("count").textContent = "–"; countShown = 0;
  $("bundle").dataset.flipped = "0";
  $("stair").dataset.grade = ""; $("stair").dataset.partial = "0";
  $("board").innerHTML = skeleton(5);
  $("detail").innerHTML = '<p class="none">Choose a citation to see what was found.</p>';
  $("exports").hidden = true;

  try {
    const started = await post("/api/verify", { text, use_model: $("usemodel").checked });
    job = started.job;
    listen(job);
  } catch (e) {
    $("board").innerHTML = `<p class="none">${escape(String(e.message || e))}</p>`;
    idle("go");
  }
};

function listen(id) {
  const stream = new EventSource(`/api/jobs/${id}/events`);
  stream.addEventListener("progress", (e) => {
    const d = JSON.parse(e.data);
    $("prog").textContent = d.total ? `${d.done} of ${d.total} checked` : "finding citations…";
    // Five pages can turn. Each fifth of the citations found turns the next one.
    if (d.total) $("bundle").dataset.flipped = String(Math.min(5, Math.floor(5 * d.done / d.total)));
  });
  stream.addEventListener("verdict", (e) => {
    const d = JSON.parse(e.data);
    verdicts[d.index] = d.verdict;
    drawBoard();
    // Open the first verdict as soon as there is one. An empty panel beside a filling board is a
    // panel the reader has to be told about; showing the first result says what a verdict looks
    // like without anyone reading an instruction. Only ever the first, and only once: re-selecting
    // as later verdicts land would move the ground under somebody already reading one.
    if (chosen === null) { chosen = d.index; drawBoard(); drawDetail(); }
  });
  stream.addEventListener("done", (e) => {
    const d = JSON.parse(e.data);
    stream.close();
    idle("go");
    $("bundle").dataset.flipped = "5";
    $("prog").textContent = d.error ? d.error : `${d.checked} citation${d.checked === 1 ? "" : "s"} checked`;
    if (verdicts.length) $("exports").hidden = false;
    else $("board").innerHTML = '<p class="none">No case-law citations found in that text.</p>';
  });
  stream.onerror = () => { stream.close(); idle("go"); };
}

function drawBoard() {
  const rows = verdicts.map((v, i) => {
    // One badge per failure mode, carrying what the finding says rather than its number. "5" tells
    // a reader nothing; "not the court's words" is the whole point of having looked.
    const byMode = new Map(v.findings.map(f => [f.mode, f]));
    const modes = [...byMode.values()]
      .map(f => `<span class="mode" title="mode ${escape(String(f.mode))}">${escape(f.label)}</span>`)
      .join("");
    const review = !modes && v.needs_review ? '<span class="review">needs review</span>' : "";
    // A grade earned with checks that could not run is not the same as one earned with all of them,
    // and on a board that is read at a glance the badge has to say so.
    const partial = !modes && v.needs_review ? " part" : "";
    // A real <button>, not a clickable row. The board is a list of citations you choose between,
    // which is what a button does; a <tr onclick> is unreachable by keyboard, invisible to a screen
    // reader, and needs a pile of ARIA to pretend otherwise. Semantics first, per the guidelines.
    return `<li>
      <button class="pick${i === chosen ? " on" : ""}" data-i="${i}" aria-pressed="${i === chosen}">
        <span class="g ${v.grade}${partial}"${partial ? ' title="not everything was checked"' : ""}>${escape(v.grade)}</span>
        <span class="pick-cite">
          <b translate="no">${escape(v.citation)}</b>
          <span class="sub">${escape(v.case || "—")}</span>
        </span>
        <span class="pick-findings">${modes || review || '<span class="sub">—</span>'}</span>
      </button>
    </li>`;
  }).join("");
  $("board").innerHTML = `<ul class="board-list">${rows}</ul>`;
  drawSummary();
  for (const button of $("board").querySelectorAll("button.pick")) {
    button.addEventListener("click", () => {
      chosen = +button.dataset.i;
      drawBoard();
      drawDetail();
      // Keep the keyboard where the reader is: redrawing replaced the element that had focus.
      const again = $("board").querySelector(`button.pick[data-i="${chosen}"]`);
      if (again) again.focus();
    });
  }
}

// Supported, checked and not supported, not checked: never collapsed into one number, because
// collapsing them is how a tool overclaims. A citation with a finding is flagged; one with none and
// nothing left unchecked is clean; one that needed a check that could not run is neither.
let countShown = 0;
function rollCount(target) {
  const el = $("count");
  if (!el) return;
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (still || target <= countShown) { el.textContent = String(target); countShown = target; return; }
  const from = countShown;
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / 600);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = String(Math.round(from + (target - from) * eased));
    if (t < 1) requestAnimationFrame(step); else countShown = target;
  };
  requestAnimationFrame(step);
}

function drawSummary() {
  const done = verdicts.filter(Boolean);
  if (!done.length) { $("summary").textContent = ""; $("count").textContent = "–"; countShown = 0; return; }
  rollCount(done.length);
  const flagged = done.filter(v => v.findings.length).length;
  const unchecked = done.filter(v => !v.findings.length && v.needs_review).length;
  const clean = done.length - flagged - unchecked;
  $("summary").innerHTML =
    `<span class="n-total">${done.length}</span>` +
    `<span class="n-bad">${flagged} flagged</span>` +
    `<span class="n-good">${clean} clean</span>` +
    (unchecked ? `<span class="n-part">${unchecked} not checked</span>` : "");
}

function drawDetail() {
  const v = verdicts[chosen];
  if (!v) return;
  // Not checked is not a low grade. The marker stays off the stair, hollow, rather than on a step.
  const unchecked = !v.findings.length && v.needs_review;
  $("stair").dataset.grade = unchecked ? "" : v.grade;
  $("stair").dataset.partial = unchecked ? "1" : "0";
  const findings = v.findings.map(f =>
    `<div class="finding"><b>[${f.mode}] ${escape(f.label)}</b><span>${escape(f.detail)}</span></div>`).join("");
  const quote = v.quote
    ? `<blockquote>“${escape(v.quote)}”<br><span class="attrib">verified word for word against paragraph ${escape(v.paragraph || "?")}</span></blockquote>`
    : "";
  const narrowed = v.narrowed
    ? `<p class="instead"><b>Argue instead:</b> ${escape(v.narrowed)}</p>` : "";
  const review = v.needs_review
    ? `<p class="review">Needs review: ${escape(v.review_reason || "")}</p>` : "";
  const treatment = v.treatment && v.treatment.doubtful
    ? `<div class="finding"><b>${escape(v.treatment.status.replace(/_/g, " "))}</b><span>${escape(v.treatment.note || "")}</span></div>` : "";

  const partial = !v.findings.length && v.needs_review ? " part" : "";
  $("detail").innerHTML = `
    <p><span class="g ${v.grade}${partial}">${escape(v.grade)}</span> <b>${escape(v.citation)}</b></p>
    <p class="case">${escape(v.case || "not resolved")}</p>
    <p class="claim">“${escape(v.proposition)}”</p>
    ${quote}${narrowed}${findings}${treatment}${review}
    ${!findings && !review ? '<p class="none">Nothing found against it in what was checked.</p>' : ""}`;
  // The memo says in full what was checked and what was not; the panel says which of the two this is.
  showPanel("detail");
  $("judgment").innerHTML = '<p class="none">Open the Judgment tab to read the paragraph.</p>';
  $("memo").innerHTML = '<p class="none">Open the Memo tab.</p>';
}

async function loadJudgment() {
  const v = verdicts[chosen];
  if (!v) return;
  if (!v.key) { $("judgment").innerHTML = '<p class="none">This citation resolves to no judgment, so there is nothing to read.</p>'; return; }
  $("judgment").innerHTML = '<p class="none">Loading the judgment…</p>';
  const url = `/api/judgment/${encodeURIComponent(v.key)}` + (v.quote ? `?highlight=${encodeURIComponent(v.quote)}` : "");
  try {
    const j = await (await fetch(url)).json();
    const want = v.paragraph || v.claimed_pinpoint;
    const paras = j.paragraphs.map(p => {
      // The server cut the paragraph where the quote begins and ends, so there is no offset to get
      // wrong here: Python counts characters and JavaScript counts UTF-16 units.
      const body = p.quoted
        ? escape(p.body) + "<mark>" + escape(p.quoted) + "</mark>" + escape(p.rest)
        : escape(p.body);
      const here = p.label && want && String(p.label) === String(want);
      const op = p.opinion && p.opinion !== "majority"
        ? `<span class="op">${escape(p.opinion)}${p.author ? " · " + escape(p.author) : ""}</span>` : "";
      return `<div class="p ${here ? "here" : ""}" ${here ? 'id="anchor"' : ""}><b>${escape(p.label || "—")}</b>${op}${body}</div>`;
    }).join("");
    $("judgment").innerHTML = `
      <p class="title"><b>${escape(j.title)}</b><br>
      <span class="sub">${escape(j.citation || j.key)} · ${escape(j.court || "")} ·
      ${escape(j.decided_on || "")} · bench ${j.bench_strength ?? "?"}</span></p>
      <div id="para">${paras}</div>`;
    const anchor = document.getElementById("anchor");
    if (anchor) anchor.scrollIntoView({ block: "center" });
  } catch {
    $("judgment").innerHTML = '<p class="none">The judgment could not be loaded.</p>';
  }
}

async function loadMemo() {
  if (chosen === null || !job) return;
  $("memo").innerHTML = '<p class="none">Writing the memo…</p>';
  const text = await (await fetch(`/api/jobs/${job}/memo/${chosen}`)).text();
  $("memo").innerHTML = `<pre>${escape(text)}</pre>`;
}

$("dl-report").onclick = () => download(`/api/jobs/${job}/report`, "verification-report.md");
$("dl-annotated").onclick = () => download(`/api/jobs/${job}/annotated`, "annotated-brief.txt");

async function download(url, name) {
  const text = await (await fetch(url)).text();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------- searching ----------
$("search").onclick = async () => {
  const q = $("query").value.trim();
  if (!q) return;
  working("search", "Searching…");
  $("results").innerHTML = skeleton(4);
  $("sprog").textContent = "searching every paragraph…";
  // The shelf: volumes come down one after another while this runs, and one stays out if it found any.
  $("shelf").dataset.state = "searching";
  try {
    const r = await (await fetch(`/api/search?q=${encodeURIComponent(q)}`)).json();
    if (r.detail) throw new Error(r.detail);
    $("shelf").dataset.state = r.authorities.length ? "found" : "idle";
    $("results").innerHTML = r.authorities.length ? r.authorities.map(a => `
      <div class="p">
        <b>${escape(a.pinpoint)}</b>
        ${a.doubtful ? `<span class="mode">no longer good law</span>` : ""}
        <div class="title"><b>${escape(a.title)}</b></div>
        <div class="sub"><span class="nums">${escape(decided(a.decided_on))} · bench ${escape(String(a.bench_strength ?? "?"))} · score ${escape(String(a.score))}</span></div>
        ${a.line ? `<blockquote>${escape(a.line)}</blockquote>` : ""}
        ${a.doubtful ? `<div class="finding"><span>${escape(a.treatment_note || "")}</span></div>` : ""}
      </div>`).join("") : '<p class="none">Nothing in the corpus carries those words.</p>';
    $("sprog").textContent = `${r.authorities.length} found`;
  } catch (e) {
    $("results").innerHTML = `<p class="none">${escape(String(e.message || e))}</p>`;
    $("sprog").textContent = "";
    $("shelf").dataset.state = "idle";
  }
  idle("search");
};

// ---------- helpers ----------
async function post(url, body) {
  const r = await fetch(url, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
  return r.json();
}
// Loading that has the shape of the thing being loaded, rather than a spinner that could be
// anything. The board is about to be a list of rows, so it shows a list of rows.
function skeleton(rows) {
  return `<ul class="skeleton" aria-hidden="true">${"<li></li>".repeat(rows)}</ul>`;
}

// A button that is working says so, and says so where the reader is already looking -- on the
// control they just pressed -- rather than only in a status line beside it.
function working(id, label) {
  const button = $(id);
  // A primary button carries an arrow beside its words; write into the label so the arrow survives.
  const text = button.querySelector(".label") || button;
  if (!button.dataset.idle) button.dataset.idle = text.textContent;
  button.disabled = true;
  text.textContent = label;
}

function idle(id) {
  const button = $(id);
  const text = button.querySelector(".label") || button;
  button.disabled = false;
  if (button.dataset.idle) text.textContent = button.dataset.idle;
}

function escape(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

// ---------- drafting ----------
let draftJob = null, bindings = [], attacks = [];

function showDraftPanel(which) {
  for (const [tab, panel] of [["t-doc", "doc"], ["t-attack", "attack"]]) {
    const on = panel === which;
    $(tab).classList.toggle("on", on);
    $(panel).hidden = !on;
  }
}
$("t-doc").onclick = () => showDraftPanel("doc");
$("t-attack").onclick = () => showDraftPanel("attack");

$("demoplan").onclick = () => { $("plan").value = DEMO_PLAN; $("parsed").innerHTML = ""; };

// Read the plan back before anything is bound. A typo should still be a typo, not something
// discovered after four minutes of model calls.
$("readplan").onclick = async () => {
  const response = await fetch("/api/plan", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan: $("plan").value }),
  });
  const body = await response.json();
  if (!response.ok) {
    $("parsed").innerHTML = `<p class="review">${escape(body.detail || "the plan cannot be read")}</p>`;
    return;
  }
  const issues = body.issues.map(i =>
    `<div class="p"><b>${escape(i.title)}</b><br>` +
    i.propositions.map(x => escape(x)).join("<br>") + "</div>").join("");
  $("parsed").innerHTML =
    `<p class="hint">${escape(body.court || "—")} · ${escape(body.parties || "—")} · ` +
    `${body.issues.length} issue(s) · ${body.propositions} proposition(s)</p>${issues}`;
};

$("build").onclick = async () => {
  const plan = $("plan").value.trim();
  if (!plan) return;
  working("build", "Drafting…");
  $("bindings").innerHTML = skeleton(4);
  $("dprog").textContent = "reading the plan…";
  bindings = []; attacks = [];
  // The tome: its lines write themselves while the plan is read, and its tabs go back in.
  $("book").dataset.state = "drafting";
  drawTabs();
  try {
    const response = await fetch("/api/draft", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan, use_model: $("usemodel2").checked }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || `HTTP ${response.status}`);
    draftJob = body.job;
    $("parsed").innerHTML = "";
    watchDraft(body.total);
  } catch (e) {
    $("dprog").textContent = "";
    $("parsed").innerHTML = `<p class="review">${escape(String(e.message || e))}</p>`;
    $("book").dataset.state = "idle";
    idle("build");
  }
};

function watchDraft(total) {
  const stream = new EventSource(`/api/draft/${draftJob}/events`);
  stream.addEventListener("progress", (e) => {
    const d = JSON.parse(e.data);
    $("dprog").textContent = `${d.done} of ${d.total || total} bound…`;
  });
  stream.addEventListener("binding", (e) => {
    bindings.push(JSON.parse(e.data).binding);
    $("dprog").textContent = `${bindings.length} of ${total} bound…`;
    drawBindings();
    drawTabs();
  });
  stream.addEventListener("done", async (e) => {
    stream.close();
    idle("build");
    const d = JSON.parse(e.data);
    $("dprog").textContent = d.error ? `stopped: ${d.error}` : "";
    $("book").dataset.state = "done";
    const full = await (await fetch(`/api/draft/${draftJob}`)).json();
    bindings = full.bindings; attacks = full.attacks;
    drawBindings(); drawAttacks(); drawTabs();
    $("doc").innerHTML = `<pre>${escape(await (await fetch(`/api/draft/${draftJob}/document`)).text())}</pre>`;
    $("dexports").hidden = false;
  });
  stream.onerror = () => { stream.close(); $("book").dataset.state = "idle"; idle("build"); };
}

// One index tab per sentence, out of the right edge of the tome: cobalt where an authority stands
// behind it, coral where the draft says in terms that none does. Eight tabs; a longer plan fills them.
function drawTabs() {
  document.querySelectorAll("#book .tab").forEach((tab, i) => {
    const b = bindings[i];
    tab.classList.toggle("out", Boolean(b));
    tab.dataset.state = b ? (b.usable ? "bound" : "none") : "";
  });
}

function drawBindings() {
  if (!bindings.length) return;
  // A list, not a table: a status and the sentence it belongs to are not two columns of data, and a
  // table with one real column and a blank header is a layout borrowed from somewhere else.
  const rows = bindings.map(b => `<li class="bind">
    <span class="st ${escape(b.status)}">${escape(b.status)}</span>
    <span class="bind-text">${escape(b.proposition)}
      ${b.citation ? `<br><b translate="no">${escape(b.citation)}</b>` : ""}
      ${b.narrowed_to ? `<br><span class="instead-inline">argue instead: ${escape(b.narrowed_to)}</span>` : ""}
      ${b.usable ? "" : `<br><span class="review">${escape(b.reason)}</span>`}</span>
  </li>`).join("");
  $("bindings").innerHTML = `<ul class="board-list">${rows}</ul>`;
}

function drawAttacks() {
  if (!attacks.length) {
    $("attack").innerHTML = '<p class="none">Nothing found in the citation graph against the authorities cited.</p>';
    return;
  }
  $("attack").innerHTML = attacks.map(a =>
    `<div class="attack"><b>${escape(a.says)}</b>` +
    (a.citation ? `<span>${escape(a.citation)}</span><br>` : "") +
    `<span>${escape(a.fix)}</span></div>`).join("");
}

$("dl-docx").onclick = () => window.location = `/api/draft/${draftJob}/document.docx`;
$("dl-md").onclick = () => window.location = `/api/draft/${draftJob}/document`;

const DEMO_PLAN = `court: In the Supreme Court of India
cause: Civil Appeal No. 4521 of 2025
parties: Ashok Kumar versus Union of India and others
for: the Appellant

# dates
12 March 2019 - the agreement to sell was executed
19 January 2024 - the trial court dismissed the suit for non-joinder

# issue Whether the suit was liable to be dismissed for non-joinder
A subsequent purchaser who holds a prior agreement to sell is a necessary party to a suit for specific performance.
The plaintiff is dominus litis and cannot be compelled to add a party against whom he does not want to fight.

# prayer
allow the appeal and set aside the judgment of the High Court
restore the suit to the file of the trial court for decision on the merits
`;

const DEMO = `WRITTEN SUBMISSIONS ON BEHALF OF THE APPELLANT

1. It is submitted at the outset that the appellant cannot be impleaded as a defendant in a suit for specific performance of a contract to which he is not a party, as held in 2019 INSC 770, para 7.

2. A subsequent purchaser who holds a prior agreement to sell is a necessary party to the suit and must be impleaded to protect his interest, as this Court held in 2019 INSC 770, para 3.2.

3. This Court has further held that the controversies between the parties to the litigation alone are to be gone into under Order 1 Rule 10 CPC: see 2019 INSC 770, para 73.

4. The proposition is settled beyond argument by the decision of this Court in Mohanlal Sharma v. State of Rajasthan, (2023) 7 SCC 4412.

5. The doctrine of delay and laches cannot be applied stricto senso to writ petitions invoking public interest jurisdiction, as this Court held in 2024 INSC 1027, para 17.

6. A Constitution Bench of this Court has settled that the plaintiff cannot be compelled to implead a stranger to the contract: 2019 INSC 770, para 7.`;
