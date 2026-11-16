// PDF 자료 검색기 화면 동작
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => Number(n || 0).toLocaleString("ko-KR");
let state = { stats: null, aiEnabled: false, categories: [] };

async function api(url, opts = {}) {
  const o = { ...opts };
  if (o.json !== undefined) {
    o.method = o.method || "POST";
    o.headers = { "Content-Type": "application/json" };
    o.body = JSON.stringify(o.json);
    delete o.json;
  }
  try {
    const r = await fetch(url, o);
    const data = await r.json();
    return data;
  } catch (e) {
    return { ok: false, error: "프로그램과 연결이 끊겼습니다. 검은 창(프로그램)이 켜져 있는지 확인해 주세요." };
  }
}

function toast(msg, ms = 3500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.add("hidden"), ms);
}

function highlight(text, terms) {
  let html = esc(text);
  for (const t of terms || []) {
    if (!t) continue;
    const re = new RegExp(esc(t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    html = html.replace(re, (m) => `<mark>${m}</mark>`);
  }
  return html;
}

const pdfLink = (id, page) => `/api/file/${id}${page ? "#page=" + page : ""}`;

// ------------------------------------------------------------ 탭
function showTab(name) {
  $$("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("on", t.id === "tab-" + name));
  if (name === "docs") loadDocs();
  if (name === "analysis") loadAnalysis();
  if (name === "settings") loadSettings();
  if (name === "ask") renderAskMode();
  if (name === "search") setTimeout(() => $("#q").focus(), 50);
  window.scrollTo(0, 0);
}
$$("#tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

// ------------------------------------------------------------ 시작(대시보드)
async function loadStats() {
  const s = await api("/api/stats");
  if (!s.ok) return;
  state.stats = s;
  state.aiEnabled = s.ai_enabled;
  const badge = $("#aiBadge");
  badge.textContent = s.ai_enabled ? "AI 켜짐" : "AI 꺼짐 · Python만 사용";
  badge.classList.toggle("on", s.ai_enabled);

  $("#statCards").innerHTML = [
    ["문서", fmt(s.documents) + "건"],
    ["전체 쪽수", fmt(s.pages) + "쪽"],
    ["분류", fmt(s.categories.length) + "개"],
    ["스캔본(글자 없음)", fmt(s.scanned) + "건"],
  ].map(([k, v]) => `<div class="card"><b>${v}</b><span>${k}</span></div>`).join("");

  $("#catChips").innerHTML = s.categories.length
    ? s.categories.map((c) => `<button class="chip" data-cat="${esc(c.name)}">${esc(c.name)}<em>${fmt(c.count)}</em></button>`).join("")
    : `<span class="muted">아직 넣은 문서가 없습니다. 위에서 PDF를 넣어 보세요.</span>`;
  $$("#catChips .chip").forEach((c) => c.addEventListener("click", () => {
    $("#docCat").value = c.dataset.cat;
    showTab("docs");
  }));

  const src = s.sources || [];
  $("#sourceList").innerHTML = src.length
    ? `<table><tr><th>폴더</th><th>문서 수</th><th>등록일</th><th></th></tr>${src.map((x) => `
        <tr><td>${esc(x.path)}</td><td>${fmt(x.documents)}</td><td>${esc(x.added_at)}</td>
        <td><button class="btn small" data-remove="${esc(x.path)}">목록에서 빼기</button></td></tr>`).join("")}</table>`
    : `<p class="muted">아직 등록된 폴더가 없습니다. 'PDF넣는곳'과 끌어다 놓은 파일은 항상 자동으로 확인합니다.</p>`;
  $$("[data-remove]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("이 폴더와 그 안의 문서를 검색 목록에서 뺄까요?\n(PC의 원본 파일은 지워지지 않습니다)")) return;
    const r = await api("/api/sources/remove", { json: { path: b.dataset.remove } });
    toast(r.ok ? `목록에서 ${r.removed}건을 뺐습니다.` : r.error);
    loadStats();
  }));

  const opts = `<option value="">전체 분류</option>` + s.categories.map((c) => `<option>${esc(c.name)}</option>`).join("");
  for (const id of ["#searchCat", "#docCat", "#kwCat"]) {
    const el = $(id), v = el.value;
    el.innerHTML = opts;
    el.value = v;
  }
}

$("#pickBtn").addEventListener("click", async () => {
  const b = $("#pickBtn");
  b.disabled = true;
  b.innerHTML = `<span class="spinner"></span> 선택 창 여는 중`;
  toast("폴더 선택 창이 열립니다. 창이 안 보이면 작업 표시줄을 확인해 주세요.", 5000);
  const r = await api("/api/pick-folder", { method: "POST" });
  b.disabled = false;
  b.textContent = "폴더 고르기…";
  if (!r.ok) return toast(r.error, 6000);
  if (r.path) $("#folderInput").value = r.path;
});

$("#importBtn").addEventListener("click", async () => {
  const folder = $("#folderInput").value.trim();
  const r = await api("/api/import", { json: { folder } });
  if (!r.ok) return toast(r.error, 6000);
  watchImport();
});

$("#rescanBtn").addEventListener("click", async () => {
  const r = await api("/api/rescan", { method: "POST" });
  if (!r.ok) return toast(r.error);
  watchImport();
});

$("#openInboxBtn").addEventListener("click", () => api("/api/open-folder", { json: { which: "inbox" } }));
$("#openDataBtn").addEventListener("click", () => api("/api/open-folder", { json: { which: "data" } }));

// 끌어다 놓기·파일 고르기
const dz = $("#dropZone");
["dragenter", "dragover"].forEach((e) => dz.addEventListener(e, (ev) => { ev.preventDefault(); dz.classList.add("over"); }));
["dragleave", "drop"].forEach((e) => dz.addEventListener(e, (ev) => { ev.preventDefault(); dz.classList.remove("over"); }));
dz.addEventListener("drop", (ev) => uploadFiles(ev.dataTransfer.files));
$("#fileBtn").addEventListener("click", () => $("#fileInput").click());
$("#fileInput").addEventListener("change", (ev) => uploadFiles(ev.target.files));
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => e.preventDefault());

async function uploadFiles(files) {
  const pdfs = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length) return toast("PDF 파일만 넣을 수 있습니다.");
  const fd = new FormData();
  pdfs.forEach((f) => fd.append("files", f));
  $("#progress").classList.remove("hidden");
  $("#progressText").textContent = `${pdfs.length}개 파일 복사 중…`;
  const r = await api("/api/upload", { method: "POST", body: fd });
  $("#fileInput").value = "";
  if (!r.ok) return toast(r.error);
  if (r.note) toast(r.note, 6000);
  watchImport();
}

let watching = false;
async function watchImport() {
  if (watching) return;
  watching = true;
  $("#progress").classList.remove("hidden");
  $("#importResult").innerHTML = "";
  while (true) {
    const s = await api("/api/import/status");
    if (!s.ok) break;
    const pct = s.total ? Math.round((s.done / s.total) * 100) : 0;
    $("#progressBar").style.width = (s.running ? pct : 100) + "%";
    $("#progressText").textContent = s.running
      ? `${s.phase} ${fmt(s.done)} / ${fmt(s.total)} ${s.current ? "· " + s.current : ""}`
      : `완료 (${s.finished_at || ""})`;
    if (!s.running) {
      const failed = (s.failed || []).map((f) => `<li>${esc(f.file)}: ${esc(f.reason)}</li>`).join("");
      $("#importResult").innerHTML = `<div class="notice ok">${esc(s.message || "완료")}</div>` +
        (s.scanned ? `<div class="notice warn">글자가 없는 스캔본이 ${s.scanned}건 있습니다. 스캔본은 검색에 걸리지 않습니다. '문서 목록'에서 '스캔본만'을 눌러 확인하세요. ${state.aiEnabled ? "문서를 열고 'AI로 글자 읽기'를 누르면 글자를 넣을 수 있습니다." : "설정에서 AI 키를 넣으면 'AI로 글자 읽기'를 쓸 수 있고, 아니면 한글·Adobe 등에서 OCR(글자 인식) 저장 후 다시 넣어 주세요."}</div>` : "") +
        (failed ? `<div class="notice warn"><b>읽지 못한 파일</b><ul>${failed}</ul></div>` : "");
      break;
    }
    await new Promise((r) => setTimeout(r, 700));
  }
  watching = false;
  loadStats();
}

// ------------------------------------------------------------ 검색
$("#searchForm").addEventListener("submit", (e) => { e.preventDefault(); runSearch(); });

async function runSearch(q) {
  if (q !== undefined) $("#q").value = q;
  const query = $("#q").value.trim();
  if (!query) return;
  const box = $("#searchResults");
  box.innerHTML = `<div class="empty"><span class="spinner"></span> 찾는 중…</div>`;
  const params = new URLSearchParams({ q: query, category: $("#searchCat").value, mode: $("#searchMode").value });
  const r = await api("/api/search?" + params);
  if (!r.ok) return (box.innerHTML = `<div class="notice warn">${esc(r.error)}</div>`);
  if (!r.results.length) {
    box.innerHTML = `<div class="empty">'${esc(query)}'이(가) 들어 있는 문서를 찾지 못했습니다.<br>
      <span class="small">단어를 줄이거나 '하나라도 포함'으로 바꿔 보세요. 스캔본은 검색되지 않습니다.</span></div>`;
    return;
  }
  box.innerHTML = `<p class="muted">문서 ${fmt(r.total)}건${r.total > r.results.length ? ` 중 ${r.results.length}건 표시` : ""}</p>` +
    r.results.map((d) => resultCard(d, r.terms)).join("");
  bindDocLinks(box);
}

function resultCard(d, terms) {
  return `<div class="result">
    <div class="title"><a data-doc="${d.id}">${highlight(d.filename, terms)}</a>
      <span class="tag">${esc(d.category)}</span>
      ${d.doc_date ? `<span class="muted small">${esc(d.doc_date)}</span>` : ""}
      <span class="muted small">${fmt(d.pages)}쪽 중 ${fmt(d.matched_pages)}쪽에서 발견</span></div>
    ${(d.hits || []).map((h) => `<div class="hit"><a class="pg btn small" href="${pdfLink(d.id, h.page)}" target="_blank">p.${h.page}</a>
      <div>${highlight(h.snippet, terms)}</div></div>`).join("")}
  </div>`;
}

function bindDocLinks(root) {
  $$("[data-doc]", root).forEach((a) => a.addEventListener("click", () => openDoc(+a.dataset.doc)));
}

// ------------------------------------------------------------ 문서 목록
["#docName", "#docCat", "#docSort", "#docScanned"].forEach((id) =>
  $(id).addEventListener(id === "#docName" ? "input" : "change", () => loadDocs()));

async function loadDocs() {
  const params = new URLSearchParams({
    name: $("#docName").value.trim(), category: $("#docCat").value, sort: $("#docSort").value,
    scanned: $("#docScanned").checked ? "1" : "",
  });
  const r = await api("/api/documents?" + params);
  const box = $("#docTable");
  if (!r.ok) return (box.innerHTML = `<div class="notice warn">${esc(r.error)}</div>`);
  if (!r.documents.length) return (box.innerHTML = `<div class="empty">조건에 맞는 문서가 없습니다.</div>`);
  box.innerHTML = `<p class="muted">${fmt(r.documents.length)}건</p><table>
    <tr><th>파일명</th><th>분류</th><th>문서 날짜</th><th>쪽</th><th>주요 단어</th></tr>
    ${r.documents.map((d) => `<tr class="clickable" data-doc="${d.id}">
      <td>${esc(d.filename)} ${d.is_scanned ? '<span class="tag warn">스캔본</span>' : ""}${d.text_source === "ai" ? ' <span class="tag ok">AI 판독</span>' : ""}</td>
      <td><span class="tag">${esc(d.category)}</span></td>
      <td>${esc(d.doc_date || "-")}</td><td>${fmt(d.pages)}</td>
      <td class="muted small">${esc((d.keywords || []).slice(0, 6).join(", "))}</td></tr>`).join("")}
  </table>`;
  bindDocLinks(box);
}

// ------------------------------------------------------------ 문서 상세
async function openDoc(id) {
  const r = await api(`/api/documents/${id}`);
  if (!r.ok) return toast(r.error);
  const d = r.document;
  const catOpts = [...new Set([...(state.stats?.categories || []).map((c) => c.name), ...state.categories.map((c) => c.name), "미분류"])];
  if (!state.categories.length) {
    const s = await api("/api/settings");
    if (s.ok) state.categories = s.categories;
    s.ok && s.categories.forEach((c) => catOpts.includes(c.name) || catOpts.push(c.name));
  }
  $("#drawerBody").innerHTML = `
    <h2>${esc(d.filename)}</h2>
    <div class="row">
      ${d.exists ? `<a class="btn primary" href="${pdfLink(d.id)}" target="_blank">원본 PDF 열기</a>` : `<span class="tag warn">원본 파일이 옮겨졌거나 지워짐</span>`}
      <button class="btn" id="localSumBtn">간단 요약 (PC 안에서)</button>
      <button class="btn" id="aiSumBtn" ${state.aiEnabled ? "" : "disabled title='설정에서 AI 키를 넣으면 쓸 수 있습니다'"}>AI 요약</button>
      ${d.is_scanned ? `<button class="btn" id="ocrBtn" ${state.aiEnabled && d.exists ? "" : "disabled title='설정에서 AI 키를 넣으면 쓸 수 있습니다'"}>AI로 글자 읽기</button>` : ""}
    </div>
    ${d.is_scanned ? `<div class="notice warn" style="margin-top:12px">글자가 없는 스캔본입니다. 검색에 걸리지 않습니다.</div>` : ""}
    <dl class="meta">
      <dt>분류</dt><dd><select id="catSel">${catOpts.map((c) => `<option ${c === d.category ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>
        ${d.category_locked ? '<span class="muted small">직접 지정함</span>' : '<span class="muted small">자동 분류</span>'}</dd>
      <dt>문서 날짜</dt><dd>${esc(d.doc_date || "본문에서 날짜를 찾지 못함")}</dd>
      <dt>본문 속 날짜</dt><dd>${esc((d.dates || []).join(", ") || "-")}</dd>
      <dt>쪽수·글자수</dt><dd>${fmt(d.pages)}쪽 · ${fmt(d.chars)}자</dd>
      <dt>주요 단어</dt><dd>${(d.keywords || []).map((k) => `<button class="chip" data-kw="${esc(k)}">${esc(k)}</button>`).join(" ")}</dd>
      <dt>위치</dt><dd class="small">${esc(d.path)}</dd>
    </dl>
    <div id="sumBox">${d.summary_ai ? `<div class="panel"><h3>AI 요약 (저장된 결과)</h3><div class="answer">${esc(d.summary_ai)}</div></div>` : ""}</div>
    <h3>쪽별 본문</h3>
    ${(d.page_texts || []).map((t, i) => `<details class="pagebox" ${i === 0 ? "open" : ""}><summary>p.${i + 1} · ${fmt(t.length)}자
      <a href="${pdfLink(d.id, i + 1)}" target="_blank" class="small">원본 보기</a></summary><pre>${esc(t || "(글자 없음)")}</pre></details>`).join("")}
  `;
  $("#drawer").classList.remove("hidden");
  $("#catSel").addEventListener("change", async (e) => {
    const r2 = await api(`/api/documents/${id}/category`, { json: { category: e.target.value } });
    toast(r2.ok ? "분류를 바꿨습니다. 이 문서는 자동 분류에서 제외됩니다." : r2.error);
    loadStats();
  });
  $$("[data-kw]", $("#drawerBody")).forEach((b) => b.addEventListener("click", () => {
    closeDrawer(); showTab("search"); runSearch(b.dataset.kw);
  }));
  $("#localSumBtn").addEventListener("click", async () => {
    const box = $("#sumBox");
    const s = await api(`/api/documents/${id}/summary`);
    if (!s.ok) return toast(s.error);
    box.insertAdjacentHTML("afterbegin", `<div class="panel"><h3>간단 요약 <span class="muted small">문서에서 중요한 문장을 원문 그대로 골랐습니다</span></h3>
      <ol class="summary">${s.sentences.map((x) => `<li>${esc(x.sentence)} ${x.page ? `<a href="${pdfLink(id, x.page)}" target="_blank" class="small">p.${x.page}</a>` : ""}</li>`).join("")}</ol>
      <p class="small muted">주요 단어: ${esc(s.keywords.join(", "))}${s.dates.length ? ` · 날짜: ${esc(s.dates.join(", "))}` : ""}</p></div>`);
  });
  const aiBtn = $("#aiSumBtn");
  aiBtn && aiBtn.addEventListener("click", async () => {
    if (!confirm("이 문서의 본문이 외부 AI(Anthropic)로 전송됩니다. 계속할까요?")) return;
    aiBtn.disabled = true;
    aiBtn.innerHTML = `<span class="spinner"></span> AI가 읽는 중 (최대 1~2분)`;
    const s = await api(`/api/documents/${id}/ai-summary`, { method: "POST" });
    aiBtn.disabled = false;
    aiBtn.textContent = "AI 요약";
    if (!s.ok) return toast(s.error, 7000);
    $("#sumBox").innerHTML = `<div class="panel"><h3>AI 요약</h3><div class="answer">${esc(s.summary)}</div></div>`;
  });
  const ocr = $("#ocrBtn");
  ocr && ocr.addEventListener("click", async () => {
    if (!confirm("이 스캔본 PDF 파일이 외부 AI(Anthropic)로 전송되어 글자를 읽습니다. 계속할까요?")) return;
    ocr.disabled = true;
    ocr.innerHTML = `<span class="spinner"></span> 글자 읽는 중 (쪽수에 따라 몇 분)`;
    const s = await api(`/api/documents/${id}/ai-ocr`, { method: "POST" });
    if (!s.ok) { ocr.disabled = false; ocr.textContent = "AI로 글자 읽기"; return toast(s.error, 7000); }
    toast(`${s.pages}쪽의 글자를 읽어 넣었습니다. 이제 검색됩니다.`);
    loadStats();
    openDoc(id);
  });
}
function closeDrawer() { $("#drawer").classList.add("hidden"); }
$$("[data-close]").forEach((e) => e.addEventListener("click", closeDrawer));
document.addEventListener("keydown", (e) => e.key === "Escape" && closeDrawer());

// ------------------------------------------------------------ 분석
function bars(items, labelKey, valueKey) {
  if (!items.length) return `<p class="muted">자료가 없습니다.</p>`;
  const max = Math.max(...items.map((x) => x[valueKey]));
  return items.map((x) => `<div class="hbar"><span class="lab" title="${esc(x[labelKey])}">${esc(x[labelKey])}</span>
    <span class="track"><span class="fill" style="width:${(x[valueKey] / max) * 100}%"></span></span>
    <span class="num">${fmt(x[valueKey])}</span></div>`).join("");
}

async function loadAnalysis() {
  await loadStats();
  const s = state.stats;
  $("#chartCat").innerHTML = bars(s.categories, "name", "count");
  $("#chartYear").innerHTML = bars(s.years, "year", "count") +
    (s.no_date ? `<p class="small muted">날짜를 찾지 못한 문서 ${fmt(s.no_date)}건은 빠져 있습니다.</p>` : "");
  loadKeywords();
}
$("#kwCat").addEventListener("change", loadKeywords);
async function loadKeywords() {
  const r = await api("/api/keywords?" + new URLSearchParams({ category: $("#kwCat").value }));
  const box = $("#kwCloud");
  if (!r.ok || !r.keywords.length) return (box.innerHTML = `<span class="muted">자료가 없습니다.</span>`);
  box.innerHTML = r.keywords.map((k) => `<button class="chip" data-kw="${esc(k.word)}">${esc(k.word)}<em>${k.docs}</em></button>`).join("");
  $$("[data-kw]", box).forEach((b) => b.addEventListener("click", () => { showTab("search"); runSearch(b.dataset.kw); }));
}
$("#organizeBtn").addEventListener("click", async () => {
  if (!confirm("분류별_정리 폴더에 PDF 사본을 만듭니다. 원본은 그대로 둡니다. 계속할까요?")) return;
  const r = await api("/api/organize", { method: "POST" });
  $("#organizeResult").innerHTML = r.ok
    ? `<div class="notice ok">사본 ${fmt(r.copied)}건을 만들었습니다${r.missing ? ` (원본이 없어진 ${r.missing}건 제외)` : ""}. 위치: ${esc(r.path)}</div>`
    : `<div class="notice warn">${esc(r.error)}</div>`;
});

// ------------------------------------------------------------ 질문하기
function renderAskMode() {
  $("#askMode").className = "notice " + (state.aiEnabled ? "ok" : "");
  $("#askMode").innerHTML = state.aiEnabled
    ? "<b>AI 답변 모드</b> · 질문과 관련된 대목을 PC에서 먼저 찾은 뒤, 그 대목만 AI에 보내 답을 받습니다. 답에는 근거 문서와 쪽이 붙습니다."
    : "<b>PC 안에서만 동작 중</b> · 질문에서 핵심 단어를 뽑아 관련 문서와 대목을 찾아 보여 줍니다. 설정에서 AI 키를 넣으면 AI가 정리한 답도 받을 수 있습니다.";
}
$("#askForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#question").value.trim();
  if (!q) return;
  const box = $("#askResult");
  box.innerHTML = `<div class="empty"><span class="spinner"></span> ${state.aiEnabled ? "자료를 찾고 AI가 답을 쓰는 중… (최대 1분)" : "관련 자료를 찾는 중…"}</div>`;
  const r = await api("/api/ask", { json: { question: q } });
  if (!r.ok) return (box.innerHTML = `<div class="notice warn">${esc(r.error)}</div>`);
  let html = "";
  if (r.ai_error) html += `<div class="notice warn">AI 답변을 받지 못했습니다: ${esc(r.ai_error)}<br>대신 관련 대목을 보여 드립니다.</div>`;
  if (r.answer) html += `<div class="panel"><h2>답변</h2><div class="answer">${esc(r.answer)}</div></div>`;
  html += `<p class="muted">검색에 쓴 단어: ${esc((r.terms || []).join(", "))}</p>`;
  html += r.sources.length
    ? `<h3>${r.answer ? "근거로 쓴 자료" : "관련 자료"}</h3>` + r.sources.map((d) => resultCard({ ...d, pages: d.pages.length, matched_pages: d.hits.length }, r.terms)).join("")
    : `<div class="empty">관련 자료를 찾지 못했습니다. 다른 단어로 질문해 보세요.</div>`;
  box.innerHTML = html;
  $$(".result .muted.small", box).forEach((el) => { if (el.textContent.includes("쪽 중")) el.remove(); });
  bindDocLinks(box);
});

// ------------------------------------------------------------ 설정
async function loadSettings() {
  const s = await api("/api/settings");
  if (!s.ok) return;
  state.categories = s.categories;
  $("#keyState").textContent = s.ai_enabled ? `AI 켜짐 (키 ${s.key_masked})` : "AI 꺼짐 · Python만으로 동작 중";
  $("#model").innerHTML = s.models.map((m) => `<option value="${m.id}" ${m.id === s.model ? "selected" : ""}>${esc(m.label)}</option>`).join("");
  $("#catText").value = s.categories.map((c) => `${c.name}: ${c.keywords.join(", ")}`).join("\n");
  $("#dataDir").textContent = s.data_dir;
}
$("#saveKeyBtn").addEventListener("click", async () => {
  const b = $("#saveKeyBtn");
  b.disabled = true;
  $("#keyResult").innerHTML = `<p class="muted"><span class="spinner"></span> 연결 확인 중…</p>`;
  const r = await api("/api/settings/ai", { json: { api_key: $("#apiKey").value.trim(), model: $("#model").value, test: true } });
  b.disabled = false;
  $("#apiKey").value = "";
  $("#keyResult").innerHTML = r.ok
    ? `<div class="notice ok">연결되었습니다. 이제 AI 요약과 AI 답변을 쓸 수 있습니다.</div>`
    : `<div class="notice warn">${esc(r.error)}</div>`;
  await loadStats();
  loadSettings();
});
$("#clearKeyBtn").addEventListener("click", async () => {
  await api("/api/settings/ai", { json: { clear: true } });
  $("#keyResult").innerHTML = `<div class="notice">키를 지웠습니다. 이제 Python만으로 동작합니다.</div>`;
  await loadStats();
  loadSettings();
});
$("#saveCatBtn").addEventListener("click", async () => {
  const cats = $("#catText").value.split("\n").map((line) => {
    const i = line.indexOf(":");
    if (i < 0) return null;
    return { name: line.slice(0, i).trim(), keywords: line.slice(i + 1).split(/[,，]/).map((x) => x.trim()).filter(Boolean) };
  }).filter((c) => c && c.name);
  const r = await api("/api/settings/categories", { json: { categories: cats } });
  $("#catResult").innerHTML = r.ok
    ? `<div class="notice ok">저장했습니다. 문서 ${fmt(r.changed)}건의 분류가 바뀌었습니다.</div>`
    : `<div class="notice warn">${esc(r.error)}</div>`;
  loadStats();
});
$("#resetCatBtn").addEventListener("click", async () => {
  if (!confirm("분류 기준을 처음 상태로 되돌릴까요?")) return;
  const r = await api("/api/settings/categories/reset", { method: "POST" });
  $("#catResult").innerHTML = `<div class="notice ok">되돌렸습니다. 문서 ${fmt(r.changed || 0)}건의 분류가 바뀌었습니다.</div>`;
  loadSettings();
  loadStats();
});

// ------------------------------------------------------------ 처음 실행
(async () => {
  await loadStats();
  const s = await api("/api/import/status");
  if (s.ok && s.running) watchImport();
})();
