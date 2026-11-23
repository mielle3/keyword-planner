"use strict";
/* 키워드 플래너 화면 동작 */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (path, body) => {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok && j.error) throw new Error(j.error);
  return j;
};

let STATE = null, RESULT = null, SAVED = [], CURRENT_TOPIC = null, SORT = { key: "score", dir: -1 }, POLL = null, ITEMS = {};
let ANALYZE = null, SAVED_FILTER = "전체", PREEMPT = null;

/* ---------- 표시 형식 ---------- */
function fmtN(n) {
  if (n == null) return null;
  if (n >= 100000000) return (n / 100000000).toFixed(1).replace(/\.0$/, "") + "억";
  if (n >= 10000) return (n / 10000).toFixed(n >= 100000 ? 0 : 1).replace(/\.0$/, "") + "만";
  return n.toLocaleString("ko-KR");
}
function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "long", day: "numeric", weekday: "short", hour: "2-digit", minute: "2-digit" });
}
function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 1800);
}
async function copy(text, label = "복사했어요") {
  try { await navigator.clipboard.writeText(text); }
  catch { const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); }
  toast(label);
}
function demandText(it) {
  const m = it.metrics || {};
  if (m.volume != null) return { v: fmtN(m.volume), sub: "월 검색" };
  return { v: Math.round(it.parts?.demand ?? it.ac_index), sub: "수요 지수(추정)", est: true };
}
function siteMark(it) { return it.site_fit ? `<span class="site-mark" title="${esc(STATE?.site?.name || "내 사이트")} 연계 · ${esc(it.site_fit)}">${esc(STATE?.site?.name || "내 사이트")}</span>` : ""; }
function siteBadge(it) { return it.site_fit ? `<span class="site-badge" title="내 사이트 서비스(${esc(it.site_fit)})와 연결되는 키워드">${esc(STATE?.site?.name || "내 사이트")} 연계</span>` : ""; }
function urgPill(u) { return u ? `<span class="pill urg-${esc(u)}">${esc(u === "상시" ? "언제든" : u)}</span>` : ""; }

/* ---------- 탭 ---------- */
/* ---------- 뒤로·앞으로 가기: 화면 상태를 브라우저 기록에 쌓음 ---------- */
const navNow = () => ({ tab: document.body.dataset.tab || "today", view: typeof VIEW === "undefined" ? "front" : VIEW,
  topic: CURRENT_TOPIC, ns: typeof NEWS_SEC === "undefined" ? "전체" : NEWS_SEC });
function navPush(patch) {
  const next = { ...navNow(), ...patch };
  delete next.drawer; delete next.dialog;
  Object.assign(next, patch);
  if (!patch.drawer && !patch.dialog) hideDrawer();  // 다른 화면으로 가면 열린 기획안은 닫기
  history.pushState(next, "", "#" + next.tab);
}
function showTab(name, push = true) {
  if (name === "drafts" && typeof markDockSeen === "function") setTimeout(() => { markDockSeen(); renderDock(); }, 0);
  if (push && document.body.dataset.tab && document.body.dataset.tab !== name) navPush({ tab: name });
  document.body.dataset.tab = name;
  $$(".tabs [data-tab]").forEach(b => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  $$(".view").forEach(v => v.hidden = v.id !== "view-" + name);
  if (name === "saved") renderSaved();
  if (name === "settings") renderSettings();
  if (name === "preempt") renderPreempt();
  if (name === "news") { if (!NEWS) loadNews(); else renderNews(); }
  if (name === "analyze") { if (!EG) loadEvergreen(); else renderEvergreen(); }
  if (name === "drafts") loadDrafts();
  window.scrollTo({ top: 0 });
}
$$(".tabs [data-tab]").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));

/* ---------- 상태 ---------- */
async function loadState() {
  STATE = await api("/api/state");
  renderLevel();
  renderTodayShell();
  if (STATE.auto_topics) setTimeout(() => toast("‘공연·여행 (떠나셈 맞춤)’ 주제로 시작했어요 · ‘내 주제’에서 바꿀 수 있어요"), 600);
}
function renderLevel() {
  if ($("#appVer") && !$("#appVer").classList.contains("has-upd")) $("#appVer").textContent = STATE.version ? "v" + STATE.version.slice(5) : "";
  if ($("#verNow")) $("#verNow").textContent = STATE.version ? "지금 v" + STATE.version.slice(5) : "";
  const lv = STATE.level;
  const names = { 1: "기본 분석", 2: "검색량 분석", 3: "정밀 분석" };
  $("#levelBadge").innerHTML = `<button class="level-pill" id="levelPill" title="설정에서 키를 넣으면 분석 단계가 올라갑니다">
    <span class="level-dots">${[1, 2, 3].map(i => `<i class="${i <= lv ? "on" : ""}"></i>`).join("")}</span><span class="lp-lv">${lv}단계</span><span class="lp-text"> · ${names[lv]}</span></button>`;
  $("#levelPill").onclick = () => showTab("settings");
  $("#levelPill").title = `설정에서 키를 넣으면 분석 단계가 올라갑니다 · 버전 ${STATE.version || ""}`;
}

/* ---------- 오늘의 추천: 셸 ---------- */
function renderTodayShell() {
  const has = STATE.topics.length > 0;
  $("#onboarding").hidden = has;
  $("#todayMain").hidden = !has;
  if (!has) { renderOnboarding(); return; }
  const tlist = STATE.topics.join(" · ") + (STATE.include_issues ? " · 오늘의 이슈 · 분야별 뉴스(사회·문화·경제·국제 등)" : "");
  $("#myTopics").innerHTML = `<button class="topic-btn" id="editTopics" title="${esc(tlist)} · 눌러서 바꾸기">
    <span class="tb-k">내 주제</span><b>${STATE.topics.length}개</b><span class="tb-v">${esc(tlist)}</span><span class="tb-edit">변경</span></button>`;
  $("#editTopics").onclick = openTopicDialog;
  const est = { "빠름": "1분", "보통": "2분", "정밀": "4분" };
  $("#runEst").textContent = `${STATE.scale} · ~${est[STATE.scale] || "1분"}`;
  $("#scaleSeg").innerHTML = STATE.scales.map(s => `<button role="radio" aria-checked="${s === STATE.scale}" data-s="${s}" title="예상 소요 약 ${est[s]} (추정)">${s}<small>~${est[s]}</small></button>`).join("");
  $$("#scaleSeg button").forEach(b => b.onclick = async () => { STATE = await api("/api/prefs", { scale: b.dataset.s }); renderTodayShell(); });
  $("#mineInput").value = (STATE.my_keywords || []).join("\n");
  $("#mineCount").textContent = STATE.my_keywords?.length || "";
}

function topicPickerHTML(selected) {
  const ex = STATE.topic_examples || {};
  const presets = `<div class="presets"><span class="presets-label">추천 묶음 · 누르면 한 번에 골라져요</span>${(STATE.topic_presets || []).map((p, i) =>
    `<button type="button" class="preset" data-preset="${i}"><b>${esc(p.name)}</b><span>${p.topics.map(esc).join(" · ")}</span></button>`).join("")}</div>`;
  const groups = Object.entries(STATE.topics_catalog).map(([g, ts]) => `
    <section class="tg">
      <header class="tg-head"><h3>${esc(g)}</h3><span class="tg-count"></span><button type="button" class="tg-all">모두 선택</button></header>
      <div class="tiles">${ts.map(t => `<button type="button" class="tile" aria-pressed="${selected.includes(t)}" data-topic="${esc(t)}">
        <span class="tile-name">${esc(t)}</span><span class="tile-ex">${(ex[t] || []).map(esc).join(" · ")}</span><span class="tile-check" aria-hidden="true"></span></button>`).join("")}</div>
    </section>`).join("");
  return presets + `<div class="tg-grid">${groups}</div>`;
}
function bindPicker(root, onChange) {
  const sync = () => {
    $$(".tg", root).forEach(g => {
      const n = $$(".tile[aria-pressed=true]", g).length, all = $$(".tile", g).length;
      $(".tg-count", g).textContent = n ? `${n}개 선택` : "";
      $(".tg-all", g).textContent = n === all ? "모두 해제" : "모두 선택";
    });
    $$(".preset", root).forEach(b => {
      const want = STATE.topic_presets[+b.dataset.preset].topics;
      const on = new Set(pickedIn(root));
      b.classList.toggle("on", want.length === on.size && want.every(x => on.has(x)));
    });
    onChange();
  };
  $$(".tile", root).forEach(c => c.onclick = () => { c.setAttribute("aria-pressed", String(c.getAttribute("aria-pressed") !== "true")); sync(); });
  $$(".tg-all", root).forEach(b => b.onclick = () => {
    const tiles = $$(".tile", b.closest(".tg")), on = tiles.every(x => x.getAttribute("aria-pressed") === "true");
    tiles.forEach(x => x.setAttribute("aria-pressed", String(!on))); sync();
  });
  $$(".preset", root).forEach(b => b.onclick = () => {
    const want = STATE.topic_presets[+b.dataset.preset].topics;
    $$(".tile", root).forEach(x => x.setAttribute("aria-pressed", String(want.includes(x.dataset.topic)))); sync();
  });
  sync();
}
const pickedIn = root => $$(".tile[aria-pressed=true]", root).map(c => c.dataset.topic);

function renderOnboarding() {
  const el = $("#onboarding");
  el.innerHTML = `<div class="card onboard">
    <div class="onboard-head">
      <div class="eyebrow">시작하기 · 1분이면 끝나요</div>
      <h1>어떤 블로그를 운영하세요?</h1>
      <p class="muted">네이버 블로그 공식 주제 중 내 블로그 분야를 골라 주세요. 매일 이 주제 안에서 쓸 만한 키워드를 찾아 순위와 글 기획안으로 정리해 드려요.</p>
    </div>
    <div class="topic-picker" id="obPicker">${topicPickerHTML([])}</div>
    <div class="onboard-foot">
      <span class="muted" id="obCount">주제를 골라 주세요 (권장 3~6개)</span>
      <button class="btn primary lg" id="obStart" disabled>이 주제로 시작하기</button>
    </div></div>`;
  const upd = () => { const n = pickedIn($("#obPicker")).length; $("#obCount").textContent = n ? `${n}개 선택` : "주제를 골라 주세요 (권장 3~6개)"; $("#obStart").disabled = !n; };
  bindPicker($("#obPicker"), upd);
  $("#obStart").onclick = async () => {
    STATE = await api("/api/prefs", { topics: pickedIn($("#obPicker")) });
    renderTodayShell(); showEmptyOrResult(); toast("주제를 저장했어요");
  };
}
function openDialog(d) {
  if (d.open) return;
  d.showModal();
  navPush({ dialog: d.id });
  if (!d.dataset.navBound) {
    d.dataset.navBound = "1";
    d.addEventListener("close", () => { if (history.state?.dialog === d.id) history.back(); });
  }
}
function openTopicDialog() {
  const d = $("#topicDialog");
  $("#topicPicker").innerHTML = topicPickerHTML(STATE.topics);
  const upd = () => $("#pickCount").textContent = `${pickedIn($("#topicPicker")).length}개 선택`;
  bindPicker($("#topicPicker"), upd);
  $("#pickNone").onclick = () => { $$("#topicPicker .tile").forEach(c => c.setAttribute("aria-pressed", "false")); bindPicker($("#topicPicker"), upd); };
  openDialog(d);
}
$("#topicForm").addEventListener("submit", async e => {
  const btn = e.submitter;
  if (!btn || btn.value !== "save") return;
  const ts = pickedIn($("#topicPicker"));
  if (!ts.length) { e.preventDefault(); toast("주제를 하나 이상 골라 주세요"); return; }
  STATE = await api("/api/prefs", { topics: ts });
  renderTodayShell(); toast("주제를 바꿨어요. 오늘 추천 받기를 누르면 반영돼요");
});

$("#mineSave").onclick = async () => {
  const kws = $("#mineInput").value.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
  STATE = await api("/api/prefs", { my_keywords: kws }); renderTodayShell(); $("#mineDialog").close(); toast(kws.length ? `유입 검색어 ${kws.length}개를 저장했어요` : "비웠어요");
};
$("#mineClear").onclick = () => { $("#mineInput").value = ""; };
$("#mineBtn").onclick = () => openDialog($("#mineDialog"));

/* ---------- 기록 ---------- */
async function loadHistory(selectId) {
  const list = await api("/api/history");
  const sel = $("#history");
  sel.innerHTML = list.length ? list.map(h => `<option value="${h.id}">${esc(fmtTime(h.generated_at))} · ${h.count}개</option>`).join("") : `<option value="">아직 기록 없음</option>`;
  sel.disabled = !list.length;
  if (list.length) {
    sel.value = selectId || list[0].id; await showResult(sel.value);
    // 처음 열었을 때 마지막 분석이 3시간보다 오래됐으면: 최신 이슈를 먼저 띄우고 새 분석을 자동으로 시작
    if (!selectId && !loadHistory._auto && STATE?.topics?.length) {
      loadHistory._auto = true;
      const ageH = (Date.now() - new Date(list[0].generated_at).getTime()) / 36e5;
      if (ageH > 3) {
        refreshHotNow();
        const st = await api("/api/status");
        if (!st.running) { await api("/api/generate", {}); toast(`${fmtTime(list[0].generated_at)} 분석이라 오래됐어요 · 최신 뉴스로 새로 분석하고 있어요`); }
        watch();
      }
    }
  }
  else {
    showEmptyOrResult();
    // 기록이 하나도 없으면 첫 추천을 바로 시작 (빈 화면 대신 진행 표시 → 1면)
    if (STATE?.topics?.length && !loadHistory._auto) {
      loadHistory._auto = true;
      const st = await api("/api/status");
      if (!st.running) { await api("/api/generate", {}); }
      watch();
    }
  }
}
$("#history").onchange = e => showResult(e.target.value);
function showEmptyOrResult() { $("#emptyResult").hidden = !!RESULT; $("#result").hidden = !RESULT; }

/* ---------- 실행 ---------- */
$("#runBtn").onclick = async () => {
  const r = await api("/api/generate", {});
  if (!r.started) toast("이미 분석 중이에요");
  watch();
};
function watch() {
  $("#runBtn").disabled = true; $("#progress").hidden = false; $("#emptyResult").hidden = true;
  clearInterval(POLL);
  const tick = async () => {
    const s = await api("/api/status");
    $("#pStage").textContent = s.stage || "준비 중";
    $("#pPct").textContent = s.pct || 0;
    $("#pBar").style.width = (s.pct || 0) + "%";
    const steps = $$("#pSteps li");
    steps.forEach((li, i) => {
      const at = +li.dataset.at, next = steps[i + 1] ? +steps[i + 1].dataset.at : 101;
      li.className = s.pct >= next ? "done" : s.pct >= at ? "now" : "";
    });
    $("#pLog").textContent = (s.log || []).join("\n");
    if (!s.running) {
      clearInterval(POLL); $("#runBtn").disabled = false;
      if (s.error) { $("#progress").hidden = true; toast(s.error); showEmptyOrResult(); return; }
      if (s.result_id) {
        await loadHistory(s.result_id); STATE = await api("/api/state"); renderLevel();
        setTimeout(() => $("#progress").hidden = true, 600);
        toast("오늘의 추천이 준비됐어요");
      }
    }
  };
  tick(); POLL = setInterval(tick, 1200);
}

/* ---------- 결과 ---------- */
/* 최신 이슈만 먼저: 새 분석이 끝나기 전에도 오늘의 이슈 칸은 지금 뉴스로 */
async function refreshHotNow() {
  try {
    const d = await api("/api/hot?refresh=1");
    if (!d.hot_issues?.length) return;
    $("#issues").innerHTML = d.hot_issues.slice(0, 8).map(h => `<button class="issue-item" data-analyze="${esc(h.keyword)}"><b>${h.section ? `<i class="iss-sec">${esc(h.section)}</i>` : ""}${esc(h.keyword)}</b><span>${esc(h.summary || h.source)}</span></button>`).join("");
    const head = document.querySelector("#issueBlock .col-head h2");
    if (head) head.innerHTML = `오늘의 이슈 <small class="live-tag">${esc(fmtTime(d.fetched_at).split(" ").slice(-2).join(" "))} 기준</small>`;
  } catch {}
}
async function showResult(id) {
  if (!id) return;
  RESULT = await api("/api/history/" + id);
  ITEMS = {};
  RESULT.topics.forEach(t => t.items.forEach(it => ITEMS[it.id] = it));
  if (!CURRENT_TOPIC || (CURRENT_TOPIC !== "전체" && !RESULT.topics.some(t => t.name === CURRENT_TOPIC))) CURRENT_TOPIC = "전체";
  renderResult(); showEmptyOrResult();
}
let VIEW = "front";
function setView(v) {
  VIEW = v;
  // 표(전체 순위)는 분야별의 한 단계 안쪽이라, 표를 볼 때도 '분야별'에 불을 켬
  $$("#viewSeg button").forEach(b => b.setAttribute("aria-checked", String(b.dataset.view === v || (v === "table" && b.dataset.view === "fields"))));
  $("#viewFront").hidden = v !== "front"; $("#viewTable").hidden = v !== "table";
  $("#viewFields").hidden = v !== "fields";
  if (v === "fields") renderFields();
}
/* 분야별: 분야마다 카드 한 장 (상위 3개) */
const FIELD_ICON = t => /생활 제도/.test(t) ? "🗓" : /오늘의 이슈/.test(t) ? "🔥" : / 뉴스$/.test(t) ? "📰" : /여행/.test(t) ? "✈" : /맛집|요리/.test(t) ? "🍽" : /공연|음악|영화|드라마|방송|스타/.test(t) ? "🎤" : /경제|비즈니스/.test(t) ? "💰" : /건강/.test(t) ? "🩺" : /IT/.test(t) ? "💻" : /육아|교육/.test(t) ? "🎒" : "📌";
function renderFields() {
  if (!RESULT) return;
  const groups = [["지금 챙길 것", t => /생활 제도|오늘의 이슈/.test(t)], ["내 주제", t => !/ 뉴스$|생활 제도|오늘의 이슈|분야별 뉴스|내 유입/.test(t)], ["분야별 뉴스", t => / 뉴스$|분야별 뉴스/.test(t)], ["내 유입 검색어", t => /내 유입/.test(t)]];
  $("#viewFields").innerHTML = `<p class="fv-intro">분야마다 지금 쓰기 좋은 글 3개씩입니다. 카드의 글감을 누르면 기획안, <b>표로 보기</b>를 누르면 그 분야 전체 순위가 열려요.</p>` +
    groups.map(([g, f]) => {
      const ts = RESULT.topics.filter(t => f(t.name) && t.items.length);
      if (!ts.length) return "";
      return `<section class="fv-group"><h3 class="fv-gtitle">${esc(g)}<small>${ts.length}개 분야</small></h3><div class="fv-grid">${ts.map(t => {
        // 같은 씨앗(브루노마스 내한/내한공연처럼)에서 나온 비슷한 글감은 하나만: 카드마다 서로 다른 주제 3개
        const seen = new Set(), top = [];
        for (const it of [...t.items].sort((a, b) => b.score - a.score)) {
          const key = (it.seed || it.keyword).replace(/\s/g, "").slice(0, 6);
          if (seen.has(key)) continue;
          seen.add(key); top.push(it);
          if (top.length === 3) break;
        }
        return `<article class="fv-card"><header><span class="fv-ico" aria-hidden="true">${FIELD_ICON(t.name)}</span><b>${esc(t.name)}</b><small>${t.items.length}개</small></header>
          <ol>${top.map(it => `<li><button data-open="${it.id}"><span class="fv-kw">${esc(it.keyword)}</span>${it.urgency && it.urgency !== "상시" ? `<em class="urg-${esc(it.urgency)}">${esc(it.urgency)}</em>` : ""}<i>${Math.round(it.score)}</i></button></li>`).join("")}</ol>
          <button class="fv-more" data-fieldtable="${esc(t.name)}">표로 보기 →</button></article>`;
      }).join("")}</div></section>`;
    }).join("");
}
$$("#viewSeg button").forEach(b => b.onclick = () => { if (b.dataset.view !== VIEW) navPush({ view: b.dataset.view }); setView(b.dataset.view); });
$("#toAll").onclick = () => { navPush({ view: "table", topic: "전체" }); CURRENT_TOPIC = "전체"; renderResult(); setView("table"); };
document.addEventListener("click", e => {
  const ft = e.target.closest("[data-fieldtable]");
  if (ft) { navPush({ view: "table", topic: ft.dataset.fieldtable }); CURRENT_TOPIC = ft.dataset.fieldtable; renderResult(); setView("table"); }
});
function renderResult() {
  const R = RESULT, d = new Date(R.generated_at);
  $("#tbDate").textContent = d.toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul", month: "long", day: "numeric", weekday: "long" })
    + " · " + d.toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit" }) + " 편집";
  $("#rMeta").textContent = `후보 ${R.stats.candidates.toLocaleString()}개 중 ${R.stats.items.toLocaleString()}개 분석 · 기회 점수 순`;
  $("#rSources").innerHTML = Object.entries(R.sources).map(([k, v]) => `<span class="src ${v.ok ? "" : v.missing ? "off" : "err"}" title="${esc(v.note)}"><i></i>${esc(k)}</span>`).join("");
  const missing = Object.values(R.sources).some(v => v.missing);
  const n = $("#estimateNotice");
  n.hidden = !missing;
  n.innerHTML = `<span>지금은 <b>추정치</b>로 매긴 순위예요. 무료 키를 넣으면 실제 검색수·발행량으로 바뀝니다.</span><button class="link-btn" data-goto="settings">키 넣기</button>`;
  const top = R.top.map(id => ITEMS[id]).filter(Boolean);
  $("#leadCol").innerHTML = leadHTML(top[0]);
  $("#rankList").innerHTML = top.slice(1).map((it, i) => rankRowHTML(it, i + 2)).join("");
  $("#issueBlock").hidden = !R.hot_issues.length;
  $("#issues").innerHTML = R.hot_issues.slice(0, 8).map((h, i) => `<button class="issue-item" ${h.section && h.section !== "실시간" ? `data-issueplan="${i}" title="이 기사로 블로그 기획안 만들기"` : `data-analyze="${esc(h.keyword)}"`}><b>${h.section ? `<i class="iss-sec">${esc(h.section)}</i>` : ""}${esc(h.keyword)}</b><span>${esc(h.summary || h.source)}</span></button>`).join("");
  renderPreMini();
  const allCount = R.topics.reduce((a, t) => a + t.items.length, 0);
  $("#topicTabs").innerHTML = `<button role="tab" aria-selected="${CURRENT_TOPIC === "전체"}" data-topic="전체">전체<small>${allCount}</small></button>`
    + R.topics.map(t => `<button role="tab" class="${isNewsTopic(t.name) ? "tt-news" : ""}" aria-selected="${t.name === CURRENT_TOPIC}" data-topic="${esc(t.name)}">${esc(isNewsTopic(t.name) ? t.name.replace(/ 뉴스$/, "") : t.name)}<small>${t.items.length}</small></button>`).join("");
  renderTable();
  setView(VIEW);
}
function rankRowHTML(it, no) {
  const m = it.metrics || {}, dmd = demandText(it);
  const figs = [`${dmd.est ? "수요" : "월 검색"} <b>${esc(dmd.v)}</b>`];
  if (m.blog_total != null) figs.push(`글 <b>${fmtN(m.blog_total)}</b>`);
  if (m.growth != null) figs.push(`추이 <b class="${m.growth >= 0 ? "growth-up" : "growth-down"}">${m.growth >= 0 ? "+" : ""}${Math.round(m.growth)}%</b>`);
  return `<li><button class="rank-row" data-open="${it.id}" style="animation-delay:${no * 25}ms">
    <span class="rr-no">${String(no).padStart(2, "0")}</span>
    <span class="rr-main"><span class="rr-kw">${esc(it.keyword)}</span>
      <span class="rr-sub"><em>${esc(it.topic)}</em>${siteMark(it)}${it.urgency && it.urgency !== "상시" ? `<em class="urg-${esc(it.urgency)}">${esc(it.urgency)}</em>` : ""}${figs.map(f => `<span>${f}</span>`).join("")}</span></span>
    <span class="rr-score">${Math.round(it.score)}</span>
  </button></li>`;
}
function renderPreMini() {
  const box = $("#preMini");
  const items = (PREEMPT?.items || []).filter(i => i.preempt_label === "지금 선점").slice(0, 3);
  if (!items.length) {
    box.innerHTML = `<p class="muted pm-empty">콘서트 예매·개봉·출시처럼 곧 검색이 몰릴 주제를 먼저 찾아 드려요.</p><button class="btn sm" data-goto="preempt">미리 쓸 글감 찾기</button>`;
    return;
  }
  box.innerHTML = items.map(it => `<button class="pm-item" data-open="${it.id}"><span class="pm-kw">${esc(it.keyword)}</span><span class="pm-sub">선점 ${Math.round(it.preempt)} · ${esc(it.timing.split(".")[0])}</span></button>`).join("");
}
document.addEventListener("click", e => {
  const g = e.target.closest("[data-goto]");
  if (g) { e.preventDefault(); showTab(g.dataset.goto); }
});
function figuresHTML(it, opts = {}) {
  const m = it.metrics || {}, dmd = demandText(it);
  const f = [];
  f.push(`<div class="score-fig"><dt>기회 점수</dt><dd>${Math.round(it.score)}</dd></div>`);
  f.push(`<div><dt>${dmd.est ? "수요 지수 (추정)" : "월 검색"}</dt><dd>${esc(dmd.v)}</dd></div>`);
  f.push(`<div><dt>블로그 글</dt><dd class="${m.blog_total == null ? "na" : ""}">${m.blog_total == null ? "키 필요" : fmtN(m.blog_total)}</dd></div>`);
  if (opts.full || m.recent7 != null) f.push(`<div><dt>7일 새 글</dt><dd class="${m.recent7 == null ? "na" : ""}">${m.recent7 == null ? "키 필요" : m.recent7_capped ? "100+" : m.recent7}</dd></div>`);
  if (opts.full || m.growth != null) f.push(`<div><dt>검색 추이</dt><dd class="${m.growth == null ? "na" : m.growth >= 0 ? "up" : "down"}">${m.growth == null ? "키 필요" : (m.growth >= 0 ? "+" : "") + Math.round(m.growth) + "%"}</dd></div>`);
  if (it.preempt != null) f.push(`<div><dt>선점 지수</dt><dd>${Math.round(it.preempt)}</dd></div>`);
  return `<dl class="figures">${f.join("")}</dl>`;
}
function metaHTML(it) {
  return `<div class="top-meta"><span class="pill topic">${esc(it.topic)}</span>${urgPill(it.urgency)}<span class="grade ${it.grade}">기회 ${it.grade}</span></div>`;
}
function leadHTML(it) {
  if (!it) return "";
  return `<button class="lead" data-open="${it.id}">
    <div class="lead-top">${metaHTML(it)}<span class="lead-no">오늘의 1순위</span></div>
    <h3 class="lead-kw">${esc(it.keyword)}${siteBadge(it)}</h3>
    <p class="lead-deck">${esc(it.brief.one_line)}</p>
    <p class="lead-title"><small>추천 제목</small>${esc(it.brief.titles[0])}</p>
    <div class="lead-why"><small>왜 지금</small><p>${esc(it.brief.why.split(/(?<=[.!?])\s+/).slice(0, 2).join(" "))}</p></div>
    <div class="lead-outline"><small>소제목 미리보기</small><ol>${it.brief.outline.slice(1, -1).slice(0, 4).map(o => `<li>${esc(o)}</li>`).join("")}</ol></div>
    <div class="lead-tags">${it.brief.tags.slice(0, 7).map(esc).join(" ")}</div>
    ${figuresHTML(it)}
    <span class="lead-actions"><span class="lead-cta">기획안 펼치기 →</span><span class="lead-write" role="button" tabindex="0" data-write="${it.id}">AI 초안 쓰기 ✍</span></span>
  </button>`;
}
function statsLine(it) {
  const m = it.metrics || {}, d = demandText(it), out = [];
  out.push(`${d.sub} <b>${esc(d.v)}</b>`);
  if (m.blog_total != null) out.push(`블로그 글 <b>${fmtN(m.blog_total)}</b>`);
  if (m.recent7 != null) out.push(`7일 새 글 <b>${m.recent7_capped ? "100+" : m.recent7}</b>`);
  if (m.growth != null) out.push(`검색 추이 <b class="${m.growth >= 0 ? "growth-up" : "growth-down"}">${m.growth >= 0 ? "+" : ""}${Math.round(m.growth)}%</b>`);
  if (m.kin_total != null) out.push(`지식iN <b>${fmtN(m.kin_total)}</b>`);
  return out.map(s => `<span>${s}</span>`).join("");
}
const COLS = [
  { key: "no", label: "#", cls: "c-no" },
  { key: "keyword", label: "키워드 · 한 줄 기획", cls: "c-kw", sort: true },
  { key: "score", label: "기회 점수", sort: true },
  { key: "demand", label: "검색 수요", cls: "c-n", sort: true },
  { key: "blog", label: "블로그 글", cls: "c-n", sort: true },
  { key: "recent", label: "7일 새 글", cls: "c-n", sort: true },
  { key: "growth", label: "검색 추이", cls: "c-n", sort: true },
  { key: "urgency", label: "시기", sort: true },
  { key: "save", label: "", cls: "c-no" },
];
const sortVal = (it, k) => {
  const m = it.metrics || {};
  return { keyword: it.keyword, score: it.score, demand: m.volume ?? (it.parts?.demand ?? 0) / 1000, blog: m.blog_total ?? -1,
    recent: m.recent7 ?? -1, growth: m.growth ?? -999, urgency: { "오늘": 0, "이번주": 1, "이번달": 2, "상시": 3 }[it.urgency] ?? 4 }[k];
};
function tableHTML(items, opts = {}) {
  const q = (opts.search || "").trim().toLowerCase();
  let rows = items.filter(it => !q || it.keyword.toLowerCase().includes(q));
  const ranked = [...items].sort((a, b) => b.score - a.score).map(it => it.id);
  rows.sort((a, b) => { const x = sortVal(a, SORT.key), y = sortVal(b, SORT.key); return (x > y ? 1 : x < y ? -1 : 0) * SORT.dir; });
  const savedSet = new Set(SAVED.map(s => s.item.keyword));
  const head = `<thead><tr>${COLS.map(c => `<th class="${c.cls || ""} ${SORT.key === c.key ? "sorted" : ""}" ${c.sort ? `data-sort="${c.key}"` : ""}>${c.label}${c.sort ? `<span class="arrow">${SORT.key === c.key ? (SORT.dir < 0 ? "↓" : "↑") : "↕"}</span>` : ""}</th>`).join("")}</tr></thead>`;
  const body = rows.length ? rows.map(it => {
    const m = it.metrics || {}, d = demandText(it);
    return `<tr data-open="${it.id}">
      <td class="c-no">${ranked.indexOf(it.id) + 1}</td>
      <td class="c-kw"><div class="kw">${esc(it.keyword)}${siteMark(it)}</div><div class="line">${opts.showTopic ? `<b class="line-topic">${esc(it.topic)}</b> · ` : ""}${esc(it.brief.one_line)}</div></td>
      <td><div class="scorebar"><b>${Math.round(it.score)}</b><div class="track"><div class="fill ${it.grade}" style="width:${it.score}%"></div></div></div></td>
      <td class="c-n">${d.est ? `<span class="est" title="키가 없어 자동완성 기반으로 추정한 지수">${d.v} 추정</span>` : `<b>${d.v}</b>`}</td>
      <td class="c-n">${m.blog_total != null ? fmtN(m.blog_total) : `<span class="est">—</span>`}</td>
      <td class="c-n">${m.recent7 != null ? (m.recent7_capped ? "100+" : m.recent7) : `<span class="est">—</span>`}</td>
      <td class="c-n">${m.growth != null ? `<span class="${m.growth >= 0 ? "growth-up" : "growth-down"}">${m.growth >= 0 ? "+" : ""}${Math.round(m.growth)}%</span>` : `<span class="est">—</span>`}</td>
      <td>${urgPill(it.urgency)}</td>
      <td class="c-no"><button class="star ${savedSet.has(it.keyword) ? "on" : ""}" data-star="${it.id}" aria-label="저장">★</button></td>
    </tr>`;
  }).join("") : `<tr><td colspan="${COLS.length}" class="empty-row">검색 결과가 없어요</td></tr>`;
  return head + `<tbody>${body}</tbody>`;
}
function renderTable() {
  if (CURRENT_TOPIC === "전체") {
    const all = RESULT.topics.flatMap(t => t.items);
    $("#rankTable").innerHTML = tableHTML(all, { search: $("#tableSearch").value, showTopic: true });
    return;
  }
  const t = RESULT.topics.find(t => t.name === CURRENT_TOPIC);
  $("#rankTable").innerHTML = t ? tableHTML(t.items, { search: $("#tableSearch").value }) : "";
}
$("#tableSearch").addEventListener("input", renderTable);
$("#csvBtn").onclick = () => {
  const rows = [["주제", "순위", "키워드", "기회점수", "등급", "월간검색수", "수요지수(추정)", "블로그글수", "7일새글", "검색추이(%)", "지식iN", "시기", "한줄기획", "추천제목1", "추천제목2", "태그"]];
  RESULT.topics.forEach(t => t.items.forEach((it, i) => {
    const m = it.metrics || {};
    rows.push([t.name, i + 1, it.keyword, it.score, it.grade, m.volume ?? "", m.volume == null ? Math.round(it.parts?.demand ?? 0) : "", m.blog_total ?? "", m.recent7 ?? "",
      m.growth ?? "", m.kin_total ?? "", it.urgency, it.brief.one_line, it.brief.titles[0], it.brief.titles[1] || "", it.brief.tags.join(" ")]);
  }));
  const csv = "﻿" + rows.map(r => r.map(v => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
  a.download = `키워드추천_${RESULT.date || "결과"}.csv`; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast("CSV 파일을 저장했어요 (엑셀에서 열 수 있어요)");
};

/* ---------- 공통 클릭 ---------- */
document.addEventListener("click", async e => {
  const star = e.target.closest("[data-star]");
  if (star) { e.stopPropagation(); await toggleSave(findItem(star.dataset.star)); return; }
  const wr = e.target.closest("[data-write]");
  if (wr) { e.preventDefault(); e.stopPropagation(); openPlan(findItem(wr.dataset.write), { from: "오늘의 추천" }); return; }
  const open = e.target.closest("[data-open]");
  if (open) { openDrawer(findItem(open.dataset.open)); return; }
  const sortTh = e.target.closest("th[data-sort]");
  if (sortTh) {
    const k = sortTh.dataset.sort; SORT = SORT.key === k ? { key: k, dir: -SORT.dir } : { key: k, dir: k === "keyword" || k === "urgency" ? 1 : -1 };
    if (sortTh.closest("#rankTable")) renderTable(); else renderAnalyze(); return;
  }
  const tab = e.target.closest("#topicTabs [data-topic]");
  if (tab) { if (tab.dataset.topic !== CURRENT_TOPIC) navPush({ topic: tab.dataset.topic }); CURRENT_TOPIC = tab.dataset.topic; $$("#topicTabs button").forEach(b => b.setAttribute("aria-selected", String(b === tab))); renderTable(); return; }
  const an = e.target.closest("[data-analyze]");
  if (an) { hideDrawer(); showTab("analyze"); $("#analyzeInput").value = an.dataset.analyze; runAnalyze(); return; }
  const cp = e.target.closest("[data-copy]");
  if (cp) { copy(cp.dataset.copy); return; }
});
function findItem(id) {
  return ITEMS[id] || PREEMPT?.items?.find(x => x.id === id) || ANALYZE?.items.find(x => x.id === id) || SAVED.find(s => s.item.id === id)?.item;
}

/* ---------- 기획안 패널 ---------- */
function planText(it) {
  const b = it.brief;
  return [`[${it.keyword}] 블로그 글 기획안`, "", `한 줄 기획: ${b.one_line}`, `왜 지금: ${b.why}`, `독자: ${b.reader}`, `담을 내용: ${b.content}`, `차별화: ${b.angle}`, "",
    ...(it.event_line ? ["행사 날짜: " + it.event_line, ""] : []),
    ...(it.timing ? ["발행 시점: " + it.timing, ""] : []),
    ...(b.site ? [`${STATE?.site?.name || "내 사이트"} 연결: ${b.site.placement}`, ...b.site.ctas.map(c => `- ${c}`), ""] : []),
    "추천 제목", ...b.titles.map(t => `- ${t}`), "", "소제목 구성", ...b.outline.map((o, i) => `${i + 1}. ${o}`), "", "도입부 예시", b.intro, "", "태그", b.tags.join(" ")].join("\n");
}
function mrow(label, val, note) {
  return `<tr><th>${label}</th>${val == null ? `<td class="na">${esc(note)}</td>` : `<td><b>${esc(val)}</b>${note ? `<span>${esc(note)}</span>` : ""}</td>`}</tr>`;
}
const DRAWER_CACHE = {};
/* 기획안을 열었는데 수치가 비어 있고 키는 있으면: 그 자리에서 다시 측정 */
const MEASURE = {};  // keyword → "busy" | {errors}
function needsMeasure(it) {
  const m = it.metrics || {}, k = STATE?.keys || {};
  return (k.searchad && m.volume == null) || (k.naver && (m.blog_total == null || m.kin_total == null));
}
function missTxt(it, key, name) {
  if (!STATE?.keys?.[key]) return `${name} 키를 넣으면 표시`;
  const st = MEASURE[it.keyword];
  if (st === "busy") return "지금 측정하는 중…";
  if (st && st.errors?.length) return "측정 실패 · 아래 이유 확인";
  if (st) return key === "searchad" ? "검색광고에 집계되지 않는 키워드예요(검색량이 매우 적음)" : "결과 없음";
  return "아직 측정 안 됨";
}
function measureNote(it) {
  const st = MEASURE[it.keyword];
  if (st === "busy") return `<p class="measure-note busy">수치가 비어 있어서(키를 넣기 전에 만든 결과이거나 그때 측정이 실패한 경우) 지금 다시 측정하고 있어요…</p>`;
  if (st && st.errors?.length) return `<p class="measure-note err">측정하지 못했어요: ${esc(st.errors.join(" · "))}<br>설정 → <b>연결 확인</b>에서 키 상태를 확인해 주세요.</p>`;
  if (!st && needsMeasure(it)) return `<p class="measure-note"><button class="btn sm" data-remeasure="${esc(it.id)}">수치 지금 측정하기</button></p>`;
  return "";
}
async function remeasure(it) {
  if (!it || MEASURE[it.keyword] === "busy") return;
  MEASURE[it.keyword] = "busy";
  if (document.querySelector("#drawer.open")) renderDrawer(it);
  try {
    const r = await api("/api/measure", { keyword: it.keyword });
    it.metrics = { ...(it.metrics || {}), ...Object.fromEntries(Object.entries(r.metrics).filter(([, v]) => v != null)) };
    if (r.top_posts?.length) it.top_posts = r.top_posts;
    MEASURE[it.keyword] = { errors: r.errors || [] };
  } catch (e) { MEASURE[it.keyword] = { errors: [e.message] }; }
  if (history.state?.drawer === it.id) renderDrawer(it);
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-remeasure]");
  if (b) remeasure(findItem(b.dataset.remeasure) || DRAWER_CACHE[b.dataset.remeasure]);
});
function openDrawer(it) {
  if (!it) return;
  if (needsMeasure(it) && !MEASURE[it.keyword]) setTimeout(() => remeasure(it), 0);
  DRAWER_CACHE[it.id] = it;
  if (history.state?.drawer) history.replaceState({ ...history.state, drawer: it.id }, "", location.hash);
  else navPush({ drawer: it.id });
  renderDrawer(it);
}
function renderDrawer(it) {
  if (!it) return;
  const b = it.brief, m = it.metrics || {}, p = it.parts || {};
  const saved = SAVED.some(s => s.item.keyword === it.keyword);
  const site = STATE?.site?.name || "내 사이트";
  const sec = (label, body, copyText) => `<section class="sec"><h3>${label}${copyText != null ? `<button class="copy" data-copy="${esc(copyText)}">복사</button>` : ""}</h3><div class="sec-body">${body}</div></section>`;
  $("#drawerBody").innerHTML = `
  <header class="d-head">
    ${metaHTML(it)}
    <h2 id="dKeyword">${esc(it.keyword)}${siteBadge(it)}</h2>
    <p class="d-deck">${esc(b.one_line)}</p>
    <div class="d-write"><button class="btn primary" id="dDraftTop">AI 초안 쓰기 ✍</button><span class="muted">작가 지침대로 네이버 블로그 초안을 써서 초안 탭에 보관해요</span></div>

    ${figuresHTML(it)}

  </header>
  <div class="d-body">
    ${it.event_line ? sec("행사 날짜", `<div class="ev-line ${evCls(it)}">${esc(it.event_line)}</div>${it.event?.evidence?.link ? `<a class="ev-src" href="${esc(it.event.evidence.link)}" target="_blank" rel="noopener">근거 기사 열기 →</a>` : ""}`) : ""}
    ${it.timing ? sec("발행 시점", `<div class="timing-box">${esc(it.timing)}</div>${it.signals?.length ? `<div class="signals">${it.signals.filter(x => !x.includes("연계")).map(sigHTML).join("")}</div>` : ""}`) : ""}
    ${sec("기획", `<dl class="plan">
        <div class="plan-row"><dt>왜 지금</dt><dd>${esc(b.why)}</dd></div>
        <div class="plan-row"><dt>누가 읽나</dt><dd>${esc(b.reader)}</dd></div>
        <div class="plan-row"><dt>무엇을 담나</dt><dd>${esc(b.content)}</dd></div>
        <div class="plan-row"><dt>어떻게 다르게</dt><dd>${esc(b.angle)}</dd></div>
      </dl>`)}
    ${sec("추천 제목", `<div class="titles">${b.titles.map(t => `<div class="title-opt"><span>${esc(t)}</span><button class="copy" data-copy="${esc(t)}">복사</button></div>`).join("")}</div>`)}
    ${sec("소제목", `<ol class="outline">${b.outline.map(o => `<li>${esc(o)}</li>`).join("")}</ol>`, b.outline.map((o, i) => `${i + 1}. ${o}`).join("\n"))}
    ${sec("도입부", `<p class="intro">${esc(b.intro)}</p>`, b.intro)}
    ${b.site ? sec(`${esc(site)} 연결`, `<div class="site-box"><p><b>링크 위치</b> · ${esc(b.site.placement)}</p>
        ${b.site.ctas.map(c => `<div class="cta"><span>${esc(c)}</span><button class="copy" data-copy="${esc(c)}">복사</button></div>`).join("")}
        <p class="caution">${esc(b.site.caution)}</p></div>`) : ""}
    ${sec("태그", `<div class="tags">${b.tags.map(esc).join(" ")}</div>`, b.tags.join(" "))}
    ${sec("제목 검사", `<div class="checker"><input id="titleCheck" value="${esc(b.titles[0])}" aria-label="검사할 제목"></div>
      <div class="checker-head"><span id="tcLen"></span><span id="tcScore"></span></div><ul class="rules" id="tcRules"></ul>`)}
    ${sec("수치", `${measureNote(it)}<table class="metrics-table"><tbody>
        ${mrow("월간 검색수", fmtN(m.volume), m.volume != null ? `PC ${fmtN(m.volume_pc)} · 모바일 ${fmtN(m.volume_mobile)}` : missTxt(it, "searchad", "검색광고"))}
        ${mrow("블로그 글 수", fmtN(m.blog_total), m.blog_total != null ? "네이버 블로그 검색 결과" : missTxt(it, "naver", "API HUB"))}
        ${mrow("최근 7일 새 글", m.recent7 == null ? null : m.recent7_capped ? "100+" : String(m.recent7), m.recent7 != null ? "최신 글 100개 기준" : missTxt(it, "naver", "API HUB"))}
        ${mrow("검색 추이", m.growth == null ? null : (m.growth >= 0 ? "+" : "") + Math.round(m.growth) + "%", m.growth != null ? "최근 7일 vs 직전 3주" : missTxt(it, "naver", "API HUB"))}
        ${mrow("지식iN 질문", fmtN(m.kin_total), m.kin_total != null ? "궁금해하는 사람 수 참고" : missTxt(it, "naver", "API HUB"))}
        ${m.daum_total != null ? mrow("다음 블로그 글", fmtN(m.daum_total), "카카오 검색 결과") : ""}
        ${mrow("자동완성 지수", String(Math.round(it.ac_index)), `노출 ${it.ac_hits}회 · 연관어 ${it.ac_children ?? "?"}개 (추정)`)}
      </tbody></table>`)}
    ${sec("점수 근거", `<div class="parts">${[["수요", p.demand, ""], ["상승세", p.growth, ""], ["경쟁", p.competition, "comp"], ["글감 적합도", p.fit, ""]].map(([l, v, c]) =>
        `<div class="part"><span>${l}</span><div class="track"><div class="fill ${c}" style="width:${v ?? 0}%"></div></div><b>${v == null ? "—" : Math.round(v)}</b></div>`).join("")}</div>
      <ul class="notes">${it.score_notes.map(n => `<li>${esc(n)}</li>`).join("")}<li>계산식: ${esc(it.score_formula)}</li>${it.preempt_formula ? `<li>선점 지수: ${esc(it.preempt_formula)}</li>` : ""}</ul>`)}
    ${it.top_posts?.length ? sec("상위 글", `<div class="posts">${it.top_posts.map(t => `<a class="post" href="${esc(t.link)}" target="_blank" rel="noopener"><b>${esc(t.title)}</b><span>${esc(t.blogger || "")} · ${esc((t.date || "").replace(/(\d{4})(\d{2})(\d{2})/, "$1.$2.$3"))}</span></a>`).join("")}</div>`) : ""}
    ${it.src?.news_list?.length ? sec(`출발한 기사 · ${esc(it.src.section || "")}`, `<div class="posts">${it.src.news_list.slice(0, 5).map(n => `<a class="post" ${/^https?:/.test(n.link || "") ? `href="${esc(n.link)}" target="_blank" rel="noopener"` : ""}><b>${esc(n.title)}</b><span>${esc(n.source || "")}</span></a>`).join("")}</div>`) : ""}
    ${it.related?.length ? sec("연관 키워드", `<div class="rel">${it.related.map(r => `<button data-analyze="${esc(r)}" title="이 키워드 분석하기">${esc(r)}</button>`).join("")}</div>`) : ""}
  </div>
  <div class="d-foot">
    <button class="btn" data-copy="${esc(planText(it))}">기획안 전체 복사</button>
    <button class="btn ghost" id="dDislike" title="이 글감과 비슷한 키워드는 다음부터 순위를 내려요">관심 없음</button>
    <button class="btn primary" id="dDraft">AI 초안 쓰기</button>
    <button class="btn ${saved ? "" : "dark"}" id="dSave">${saved ? "저장됨 ✓" : "저장함에 담기"}</button>
  </div>`;

  $("#dSave").onclick = async () => { await toggleSave(it); openDrawer(it); };
  $("#dDraft").onclick = () => openPlan(it, { from: "기획안" });
  $("#dDraftTop").onclick = () => openPlan(it, { from: "기획안" });
  $("#dDislike").onclick = async () => { STATE = await api("/api/prefs", { dislike: it.keyword }); toast(`‘${it.keyword}’ 같은 글감은 다음 분석부터 내릴게요`); hideDrawer(); };
  const tc = $("#titleCheck"); tc.oninput = () => checkTitle(tc.value, it.keyword); checkTitle(tc.value, it.keyword);
  $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false"); $("#scrim").hidden = false;
  $("#drawerBody").scrollTop = 0;
  setTimeout(() => $("#dCloseFixed")?.focus({ preventScroll: true }), 50);
}
function closeDrawer() { if (history.state?.drawer) history.back(); else hideDrawer(); }
function hideDrawer() { $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true"); $("#scrim").hidden = true; }
$("#scrim").onclick = closeDrawer;
$("#dCloseFixed").onclick = closeDrawer;
document.addEventListener("keydown", e => { if (e.key === "Escape" && $("#drawer").classList.contains("open")) closeDrawer(); });

/* ---------- 제목 검사 (네이버 블로그 제목 기본 규칙) ---------- */
function checkTitle(title, kw) {
  const t = title.trim(), len = [...t].length, words = kw.split(/\s+/).filter(Boolean);
  const pos = t.indexOf(kw);
  const head = [...t].slice(0, 15).join("");
  const counts = {}; t.split(/\s+/).forEach(w => { if (w.length > 1) counts[w] = (counts[w] || 0) + 1; });
  const spam = Object.entries(counts).filter(([, c]) => c >= 3).map(([w]) => w);
  const special = (t.match(/[^\p{L}\p{N}\s,.?!·()'"~:|%+-]/gu) || []).length;
  const hype = (t.match(/충격|경악|대박|무조건|100%|역대급|미쳤|레전드|클릭/g) || []);
  const rules = [
    [t.includes(kw) || words.every(w => t.includes(w)), "메인 키워드가 들어 있어요", `'${kw}'를 그대로 넣어 주세요`],
    [pos > -1 ? pos < 12 : head.includes(words[0] || ""), "키워드가 앞쪽에 있어요", "키워드를 제목 앞쪽(15자 안)으로 옮기면 검색에 유리해요"],
    [len >= 18 && len <= 40, `길이가 적당해요 (${len}자)`, len < 18 ? `조금 짧아요 (${len}자) · 18~40자를 권장해요` : `길어요 (${len}자) · 검색 결과에서 잘릴 수 있어요`],
    [!spam.length, "같은 단어를 반복하지 않았어요", `'${spam.join(", ")}'가 3번 이상 반복돼요 · 키워드 도배로 보일 수 있어요`],
    [special <= 2 && !hype.length, "특수문자·자극적 표현이 없어요", hype.length ? `'${hype.join(", ")}' 같은 자극적 표현은 빼는 게 좋아요` : "특수문자·이모지를 2개 이하로 줄여 주세요"],
  ];
  const pass = rules.filter(r => r[0]).length;
  $("#tcLen").textContent = `${len}자`;
  $("#tcScore").innerHTML = `<b style="color:${pass === 5 ? "var(--hi)" : "var(--accent)"}">${pass}/5</b> 통과`;
  $("#tcRules").innerHTML = rules.map(([ok, good, bad]) => `<li class="${ok ? "pass" : "fail"}">${ok ? esc(good) : `<span>${esc(bad)}</span>`}</li>`).join("");
}

/* ---------- 저장함 ---------- */
async function loadSaved() { SAVED = await api("/api/saved"); $("#savedCount").textContent = SAVED.length || 0; }
async function toggleSave(it) {
  if (!it) return;
  const has = SAVED.some(s => s.item.keyword === it.keyword);
  SAVED = await api("/api/saved", has ? { action: "remove", keyword: it.keyword } : { action: "add", item: it });
  $("#savedCount").textContent = SAVED.length || 0;
  toast(has ? "저장함에서 뺐어요" : "저장함에 담았어요");
  if (RESULT) renderTable();
  if (ANALYZE) renderAnalyze();
}
const STATUSES = ["쓸 예정", "작성 중", "발행 완료"];
function renderSaved() {
  $("#savedFilter").innerHTML = ["전체", ...STATUSES].map(s => `<button role="radio" aria-checked="${s === SAVED_FILTER}" data-sf="${s}">${s} <small>${s === "전체" ? SAVED.length : SAVED.filter(x => x.status === s).length}</small></button>`).join("");
  $$("#savedFilter button").forEach(b => b.onclick = () => { SAVED_FILTER = b.dataset.sf; renderSaved(); });
  const list = SAVED.filter(s => SAVED_FILTER === "전체" || s.status === SAVED_FILTER);
  if (!SAVED.length) {
    $("#savedList").innerHTML = `<div class="card empty"><h2>저장한 키워드가 없어요</h2><p class="muted">추천 목록에서 ★을 누르거나 기획안의 “저장함에 담기”를 누르면 여기에 모여요.</p></div>`;
    return;
  }
  $("#savedList").innerHTML = `<div class="saved-grid">${list.map(s => {
    const it = s.item;
    return `<article class="card saved-card">
      <div class="top-meta"><span class="pill topic">${esc(it.topic)}</span><span class="grade ${it.grade}">기회 ${it.grade} · ${Math.round(it.score)}</span></div>
      <div class="top-kw" data-open="${it.id}">${esc(it.keyword)}</div>
      <div class="saved-title">${esc(it.brief.titles[0])}</div>
      <div class="top-stats" style="margin:0">${statsLine(it)}</div>
      <div class="saved-foot">
        <select data-status="${esc(it.keyword)}" aria-label="상태">${STATUSES.map(x => `<option ${x === s.status ? "selected" : ""}>${x}</option>`).join("")}</select>
        <span class="muted" style="font-size:12.5px">${esc(fmtTime(s.saved_at))} 저장</span>
        <button class="btn sm ghost" data-unsave="${esc(it.keyword)}">빼기</button>
      </div></article>`;
  }).join("")}</div>`;
  $$("[data-status]").forEach(sel => sel.onchange = async () => { SAVED = await api("/api/saved", { action: "status", keyword: sel.dataset.status, status: sel.value }); renderSaved(); toast(`‘${sel.value}’로 바꿨어요`); });
  $$("[data-unsave]").forEach(b => b.onclick = async () => { SAVED = await api("/api/saved", { action: "remove", keyword: b.dataset.unsave }); $("#savedCount").textContent = SAVED.length || 0; renderSaved(); });
}

/* ---------- 키워드 분석 ---------- */
const RECENT_KEY = "kp-recent-analyze";
function recentList() { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]"); } catch { return []; } }
function renderRecent() {
  const r = recentList();
  $("#analyzeRecent").innerHTML = r.length ? `<span class="muted" style="font-size:13px;align-self:center">최근</span>` + r.map(k => `<button data-analyze="${esc(k)}">${esc(k)}</button>`).join("") : "";
}
$("#analyzeForm").addEventListener("submit", e => { e.preventDefault(); runAnalyze(); });
/* 맨 위 검색창: 어느 화면에서든 키워드를 넣으면 바로 분석 */
$("#topSearch").addEventListener("submit", e => {
  e.preventDefault();
  const kw = $("#topSearchInput").value.trim();
  if (!kw) { $("#topSearchInput").focus(); return; }
  showTab("analyze"); $("#analyzeInput").value = kw; $("#topSearchInput").value = ""; runAnalyze();
});
async function runAnalyze() {
  const kw = $("#analyzeInput").value.trim();
  if (!kw) { $("#analyzeInput").focus(); return; }
  try { localStorage.setItem(RECENT_KEY, JSON.stringify([kw, ...recentList().filter(x => x !== kw)].slice(0, 8))); } catch {}
  renderRecent();
  $("#analyzeBtn").disabled = true;
  $("#analyzeResult").innerHTML = `<div class="card loading"><div class="spinner"></div><div><b>‘${esc(kw)}’ 분석 중</b><div class="muted" style="font-size:13px">연관 키워드를 모으고 수치를 재고 있어요 · 10~40초</div></div></div>`;
  try {
    ANALYZE = await api("/api/analyze", { keyword: kw });
    SORT = { key: "score", dir: -1 };
    renderAnalyze();
  } catch (err) {
    $("#analyzeResult").innerHTML = `<div class="card empty"><h2>분석하지 못했어요</h2><p class="muted">${esc(err.message)}</p></div>`;
  } finally { $("#analyzeBtn").disabled = false; }
}
function renderAnalyze() {
  if (!ANALYZE) return;
  const main = ANALYZE.items[0];
  $("#analyzeResult").innerHTML = `
    <div class="card analyze-summary" data-open="${main.id}">
      ${metaHTML(main)}
      <h2>${esc(main.keyword)}${siteBadge(main)}</h2>
      <p class="lead-deck">${esc(main.brief.one_line)}</p>
      ${figuresHTML(main)}
      <span class="lead-cta">기획안 펼치기 →</span>
    </div>
    ${recordsHTML(ANALYZE.records)}
    ${conceptsHTML(ANALYZE.concepts || [])}
    <div class="block" id="ideasBlock">${ideasHTML(IDEAS_STATE[ANALYZE.keyword])}</div>
    <div class="block"><div class="block-head"><h2>함께 찾는 키워드 순위</h2><span class="muted">${ANALYZE.items.length - 1}개 · 행을 누르면 기획안</span></div>
    <div class="table-wrap"><table class="rank" id="analyzeTable">${tableHTML(ANALYZE.items.slice(1))}</table></div></div>`;
}

/* ---------- 설정 ---------- */
const AI_NAME = { antigravity: "Gemini 자동 작성", gemini_cli: "Gemini CLI", gemini: "Gemini API", manual: "직접 붙여넣기", claude_code: "Claude 자동 작성", claude: "Claude API" };
function renderAI() {
  const ai = STATE.ai || {};
  $$("#aiProvider button").forEach(b => b.setAttribute("aria-checked", String(b.dataset.p === ai.provider)));
  $$(".ai-mode-box[data-mode]").forEach(x => { if (x.dataset.mode !== "api") x.hidden = x.dataset.mode !== ai.provider; else if (["claude", "gemini"].includes(ai.provider)) x.open = true; });
  $("#aiWeb").checked = ai.web !== false;
  $("#geminiModel").value = ai.gemini_model || "";
  $("#claudeCodePath").value = ai.claude_code_path || "";
  $("#agyPath").value = ai.agy_path || ""; $("#agyModel").value = ai.agy_model || "";
  const st = $("#state-ai");
  const ready = { antigravity: ai.antigravity, gemini_cli: ai.gemini_cli, claude_code: true, manual: true, claude: ai.claude, gemini: ai.gemini }[ai.provider];
  const name = AI_NAME[ai.provider] || "";
  st.className = "keystate " + (ready ? "ok" : "");
  st.textContent = ai.provider === "antigravity"
    ? (ai.antigravity ? "Gemini로 자동 작성 · 준비됨" : "Antigravity 설치 필요 · 아래 안내")
    : (ready ? `${name} 사용` : `${name} · 키 필요`) + (ai.provider === "gemini" ? " · 항상 최고 버전" : "");
  if ($("#draftCount")) $("#draftCount").textContent = ai.drafts || 0;
}
let GUIDE_STYLE = "info", MEM = null;
document.addEventListener("click", e => {
  const g = e.target.closest("[data-gs]");
  if (!g) return;
  GUIDE_STYLE = g.dataset.gs;
  $$("#guideStyle [data-gs]").forEach(b => b.setAttribute("aria-checked", String(b === g)));
  if (MEM) { $("#guideText").value = ({ essay: MEM.guide_essay, deal: MEM.guide_deal }[GUIDE_STYLE] || MEM.guide); $("#guidePath").textContent = ({ essay: MEM.guide_essay_path, deal: MEM.guide_deal_path }[GUIDE_STYLE] || MEM.guide_path); }
});
async function loadMemory() {
  try {
    const d = await api("/api/memory");
    MEM = d;
    if (document.activeElement !== $("#guideText")) $("#guideText").value = ({ essay: d.guide_essay, deal: d.guide_deal }[GUIDE_STYLE] || d.guide);
    $("#memoryText").textContent = d.memory;
    $("#guidePath").textContent = ({ essay: d.guide_essay_path, deal: d.guide_deal_path }[GUIDE_STYLE] || d.guide_path); $("#memoryPath").textContent = d.memory_path;
  } catch {}
}
function renderAuto() {
  const au = STATE.auto || {}, le = STATE.learn || {};
  $("#autoStartup").checked = !!au.startup; $("#autoStartup").disabled = au.windows === false;
  $("#autoHours").value = String(au.hours ?? 4);
  $("#autoDrafts").value = String(au.drafts_per_day ?? 2);
  if ($("#morningOn")) {
    $("#morningOn").checked = au.morning !== false;
    if (document.activeElement !== $("#morningTime")) $("#morningTime").value = au.morning_time || "07:30";
    const ml = au.morning_last || {};
    $("#morningInfo").innerHTML = au.morning_running ? "아침 글을 고르고 쓰는 중이에요…" : ml.date
      ? `최근 실행: ${esc(ml.date)} ${esc(ml.at || "")} · 상시 <b>${esc(ml.evergreen || "없음")}</b> · 오늘 <b>${esc(ml.today || "없음")}</b>${(ml.errors || []).length ? " · " + esc(ml.errors.join(", ")) : ""}`
      : "상시 주제는 상시 키워드 검증에서 '1년 내내 찾음'·검색량 큰 순, 오늘 최적 주제는 오늘의 글 계획(요일 코너·최근 7일 이슈)으로 골라요. 그 시각에 PC가 꺼져 있으면 켜진 뒤 그날 한 번 실행해요.";
  }
  if (document.activeElement !== $("#blogId")) $("#blogId").value = le.blog_id || "";
  $("#blogInfo").textContent = le.error ? le.error : le.posts != null ? `최근 글 ${le.posts}개를 읽었어요` : (le.blog_id ? "아직 안 읽음" : "");
  const d = le.dislikes || [];
  $("#dislikeChips").innerHTML = d.length ? d.map(k => `<span class="wchip">${esc(k)}<button data-undislike="${esc(k)}" aria-label="${esc(k)} 다시 보기">✕</button></span>`).join("") : `<span class="muted" style="font-size:12.5px">관심 없음으로 표시한 글감이 없어요</span>`;
}
function renderSettings() {
  renderAI(); renderAuto(); loadMemory();
  const lv = STATE.level, k = STATE.keys;
  const L = [
    [1, "기본 분석", "키 없이 바로 · 네이버 자동완성, 구글 트렌드, 시즌 캘린더로 추정 순위", true],
    [2, "검색량 분석", "+ 검색광고 키 · 실제 월간 검색수와 경쟁 정도", k.searchad],
    [3, "정밀 분석", "+ API HUB 키 · 블로그 발행량, 최근 7일 새 글, 검색어 트렌드, 지식iN", k.naver],
  ];
  $("#levels").innerHTML = L.map(([n, t, d, on]) => `<div class="level ${on ? "on" : ""}"><span class="lv">${n}단계 ${on ? "· 사용 중" : ""}</span><b>${t}</b><span>${d}</span></div>`).join("");
  $$(".keycard input[data-k]").forEach(inp => { inp.value = ""; inp.placeholder = STATE.masked[inp.dataset.k] || "붙여넣기"; });
  for (const key of ["searchad", "naver", "kakao"]) {
    const el = $("#state-" + key); el.className = "keystate" + (k[key] ? " ok" : ""); el.textContent = k[key] ? "저장됨" : "미입력";
  }
  $("#optIssues").checked = STATE.include_issues;
  if ($("#dataDir")) $("#dataDir").textContent = STATE.data_dir || "";
  renderSite();
  const u = STATE.usage || {};
  $("#usageBox").innerHTML = `<div class="eyebrow">오늘 API 사용량</div>` + [["검색 (블로그·지식iN)", u.search || 0, STATE.limits.search], ["검색어 트렌드", u.trend || 0, STATE.limits.trend], ["검색광고", u.searchad || 0, null]]
    .map(([n, v, lim]) => `<div class="usage-row"><div><span>${n}</span><span class="num">${v.toLocaleString()}${lim ? ` / ${lim.toLocaleString()}회` : "회"}</span></div>${lim ? `<div class="track"><div class="fill" style="width:${Math.min(100, v / lim * 100)}%"></div></div>` : ""}</div>`).join("");
}
$("#optIssues").onchange = async e => { STATE = await api("/api/prefs", { include_issues: e.target.checked }); toast(e.target.checked ? "오늘의 이슈를 포함해요" : "오늘의 이슈를 빼요"); };
async function saveKeys() {
  const body = {};
  $$(".keycard input[data-k]").forEach(inp => { if (inp.value.trim()) body[inp.dataset.k] = inp.value.trim(); });
  STATE = await api("/api/keys", body);
  renderLevel(); renderSettings();
  return Object.keys(body).length;
}
$("#saveKeys").onclick = async () => { const n = await saveKeys(); toast(n ? "저장했어요 · 연결 확인을 눌러 보세요" : "바뀐 내용이 없어요"); };
$("#checkKeys").onclick = async () => {
  await saveKeys();
  const b = $("#checkKeys"); b.disabled = true; b.textContent = "확인 중…";
  try {
    const r = await api("/api/keys/check", {});
    for (const [key, v] of Object.entries(r)) {
      const el = $("#state-" + key);
      if (!el) continue;
      el.className = "keystate " + (v.ok ? "ok" : STATE.keys[key] ? "bad" : "");
      el.textContent = v.message;
    }
    toast("연결 확인을 마쳤어요");
  } finally { b.disabled = false; b.textContent = "연결 확인"; }
};

/* ---------- 시작 ---------- */
(async () => {
  await loadState();
  await loadSaved();
  PREEMPT = await api("/api/preempt");
  renderRecent();
  if (STATE.topics.length) await loadHistory();
  const s = await api("/api/status");
  if (s.running) watch();
  const tab = location.hash.slice(1);
  const first = ["today", "preempt", "news", "analyze", "drafts", "saved", "settings"].includes(tab) ? tab : "today";
  showTab(first, false);
  history.replaceState(navNow(), "", "#" + first);
})();
window.addEventListener("popstate", e => {
  const tabs = ["today", "preempt", "news", "analyze", "drafts", "saved", "settings"];
  const s = e.state || { tab: tabs.includes(location.hash.slice(1)) ? location.hash.slice(1) : "today" };
  $$("dialog[open]").forEach(d => { if (d.id !== s.dialog) d.close(); });
  if (s.tab && s.tab !== document.body.dataset.tab) showTab(s.tab, false);
  if (s.tab === "today" && RESULT) {
    if (s.topic && s.topic !== CURRENT_TOPIC) {
      CURRENT_TOPIC = s.topic;
      $$("#topicTabs button").forEach(b => b.setAttribute("aria-selected", String(b.dataset.topic === s.topic)));
      renderTable();
    }
    if (s.view && s.view !== VIEW) setView(s.view);
  }
  if (s.tab === "news" && s.ns && s.ns !== NEWS_SEC) { NEWS_SEC = s.ns; renderNews(); }
  if (s.drawer) { const it = DRAWER_CACHE[s.drawer] || findItem(s.drawer); if (it) renderDrawer(it); else hideDrawer(); }
  else hideDrawer();
});

/* ---------- 선제 글감 ---------- */
function sigHTML(x) {
  const cls = /급상승|예매|상승/.test(x) ? "hot" : /연계/.test(x) ? "site" : "";
  return `<span class="sig ${cls}">${esc(x)}</span>`;
}
function renderWatch() {
  const w = STATE.watchlist || [];
  $("#watchChips").innerHTML = w.length ? w.map(k => `<span class="wchip">${esc(k)}<button data-unwatch="${esc(k)}" aria-label="${esc(k)} 빼기">✕</button></span>`).join("")
    : `<span class="muted" style="font-size:13px">아직 없어요. 좋아하는 아티스트나 챙겨 보는 행사를 넣어 보세요.</span>`;
  $$("[data-unwatch]").forEach(b => b.onclick = async () => { STATE = await api("/api/prefs", { watchlist: w.filter(x => x !== b.dataset.unwatch) }); renderWatch(); });
}
$("#watchForm").addEventListener("submit", async e => {
  e.preventDefault();
  const add = $("#watchInput").value.split(",").map(x => x.trim()).filter(Boolean);
  if (!add.length) return;
  const w = [...new Set([...(STATE.watchlist || []), ...add])].slice(0, 20);
  STATE = await api("/api/prefs", { watchlist: w }); $("#watchInput").value = ""; renderWatch(); toast("관심 키워드를 추가했어요");
});
function renderPreempt() {
  renderWatch();
  const P = PREEMPT;
  $("#preMeta").innerHTML = P?.items ? `마지막 확인 ${esc(fmtTime(P.generated_at))} · 후보 ${P.stats.candidates}개 중 ${P.stats.items}개 분석` : "아직 찾아본 적이 없어요 · 20초~1분 걸려요";
  const cal = P?.calendar || [];
  const side = `<aside class="side">
    <div class="side-sec"><h3>다가오는 날짜</h3>${cal.length ? `<ul class="cal">${cal.map(c => `<li><span class="dday">D-${c.d_day}</span><div><b>${esc(c.name)}</b><span>${esc(c.date.slice(5).replace("-", "."))} · ${esc(c.publish_by.slice(5).replace("-", "."))}까지 발행 권장</span></div></li>`).join("")}</ul>` : `<p class="muted" style="font-size:13px;margin:0">75일 안에 정해진 기념일이 없어요.</p>`}</div>
    <div class="side-sec"><h3>선제 글 쓰는 법</h3><ol class="howto">
      <li>일정이 <b>발표되기 전</b>엔 “○○ 콘서트 2026 일정 예상” 같은 글로 먼저 자리를 잡아요.</li>
      <li>발표되면 <b>같은 글을 고쳐</b> 날짜·장소·가격을 채우고 제목에 날짜를 넣어요.</li>
      <li>예매 <b>3~7일 전</b>에 예매 방법·좌석 정보를 보강하고, ${esc(STATE.site?.name || "내 사이트")} 링크를 넣어요.</li>
      <li>공식 공지에서 확인한 내용만 단정적으로 쓰고, 나머지는 “예정”으로 표시해요.</li>
    </ol></div></aside>`;
  if (!P?.items) {
    $("#preResult").innerHTML = `<div class="pre-grid"><div class="card empty" style="margin:0"><h2>미리 쓸 글감을 찾아보세요</h2><p class="muted">관심 키워드와 오늘의 급상승 검색어에서 예매·공개·출시 같은 예고 신호를 찾아, 먼저 써 둘 글을 순서대로 보여 드려요.</p></div>${side}</div>`;
    return;
  }
  const groups = [["지금 선점", "지금 쓰면 좋은 글"], ["준비해 두기", "미리 써 두면 좋은 글"], ["지켜보기", "조금 더 지켜볼 글"]];
  const list = groups.map(([lab, title]) => {
    const all = P.items.filter(i => i.preempt_label === lab);
    if (!all.length) return "";
    const open = PRE_OPEN.has(lab), arr = open ? all : all.slice(0, 10);
    return `<div class="group-title">${title}<small>${all.length}개</small></div>` + arr.map(it => `
      <button class="pre-card" data-open="${it.id}">
        <div><div class="top-meta"><span class="pill topic">${esc(it.topic)}</span><span class="pre-label ${lab.slice(0, 2)}">${esc(lab)}</span></div>
          <div class="top-kw">${esc(it.keyword)}${siteMark(it)}</div>
          <div class="pre-sub">${esc(it.brief.titles[0])}</div></div>
        <div class="prescore"><b>${Math.round(it.preempt)}</b><span>선점 지수</span></div>
        <div class="signals">${it.signals.filter(x => !x.includes("연계")).map(sigHTML).join("")}</div>
        <div class="timing">${esc(it.timing)}</div>
        ${it.event_line ? `<div class="ev-line ${evCls(it)}">${esc(it.event_line)}</div>` : ""}
        ${it.brief?.site ? `<div class="site-line"><b>${esc(STATE?.site?.name || "내 사이트")} 연결</b>${esc(it.brief.site.placement)}</div>` : ""}
      </button>`).join("") + (all.length > 10 ? `<button class="btn ghost more" data-more="${esc(lab)}">${open ? "접기" : `${all.length - 10}개 더 보기`}</button>` : "");
  }).join("");
  $("#preResult").innerHTML = `<div class="pre-grid"><div><div class="sources" style="justify-content:flex-start;max-width:none;margin-bottom:6px">${Object.entries(P.sources).map(([k, v]) => `<span class="src ${v.ok ? "" : v.missing ? "off" : "err"}" title="${esc(v.note)}"><i></i>${esc(k)}</span>`).join("")}</div>
    <div class="pre-list">${list}</div>${P.past_events?.length ? `<details class="past-ev"><summary>이미 끝난 행사라서 뺀 키워드 ${P.past_events.length}개</summary><ul>${P.past_events.map(x => `<li><b>${esc(x.keyword)}</b><span>${esc(x.line)}</span></li>`).join("")}</ul></details>` : ""}</div>${side}</div>`;
}
const evCls = it => /^일정 확인/.test(it.event_line || "") ? "ok" : /^지난/.test(it.event_line || "") ? "past" : "warn";
const PRE_OPEN = new Set();
document.addEventListener("click", e => {
  const m = e.target.closest("[data-more]");
  if (!m) return;
  const k = m.dataset.more; PRE_OPEN.has(k) ? PRE_OPEN.delete(k) : PRE_OPEN.add(k); renderPreempt();
});
$("#preBtn").onclick = async () => {
  const b = $("#preBtn"); b.disabled = true; b.textContent = "찾는 중…";
  $("#preResult").innerHTML = `<div class="card loading"><div class="spinner"></div><div><b>예고 신호를 찾는 중</b><div class="muted" style="font-size:13px">관심 키워드와 급상승 검색어에서 예매·공개·출시 검색을 확인하고 있어요 · 20초~1분</div></div></div>`;
  try { PREEMPT = await api("/api/preempt", {}); renderPreempt(); if (RESULT) renderPreMini(); toast("미리 쓸 글감을 찾았어요"); }
  catch (err) { $("#preResult").innerHTML = `<div class="card empty"><h2>찾지 못했어요</h2><p class="muted">${esc(err.message)}</p></div>`; }
  finally { b.disabled = false; b.textContent = "미리 쓸 글감 찾기"; }
};

/* ---------- 내 사이트 연계 설정 ---------- */
function renderSite() {
  const st = STATE.site || {};
  $("#siteName").value = st.name || ""; $("#siteUrl").value = st.url || "";
  $("#siteOffers").innerHTML = STATE.offer_options.map(o => `<button type="button" class="chip" aria-pressed="${(st.offers || []).includes(o)}" data-offer="${esc(o)}">${esc(o)}</button>`).join("");
  $$("#siteOffers .chip").forEach(c => c.onclick = () => c.setAttribute("aria-pressed", String(c.getAttribute("aria-pressed") !== "true")));
  $("#siteBoost").checked = STATE.site_boost;
  if (typeof renderTools === "function") renderTools();
  const el = $("#state-site"); const on = !!(st.name && st.offers?.length);
  el.className = "keystate" + (on ? " ok" : ""); el.textContent = on ? "연계 중" : "미설정";
}
$("#saveSite").onclick = async () => {
  const offers = $$("#siteOffers .chip[aria-pressed=true]").map(c => c.dataset.offer);
  const name = $("#siteName").value.trim();
  if (name && !offers.length) { toast("사이트에서 할 수 있는 것을 하나 이상 골라 주세요"); return; }
  const tools = ($("#siteTools")?.value || "").split("\n").map(l => l.split("|").map(s => s.trim())).filter(p => p[0])
    .map(([nm, url = "", kws = "", desc = ""]) => ({ name: nm, url, keywords: kws.split(/[,，]/).map(s => s.trim()).filter(Boolean), desc }));
  if (tools.some(t => !t.keywords.length)) { toast("도구마다 연결할 검색어를 하나 이상 적어 주세요 (세 번째 칸)"); return; }
  STATE = await api("/api/prefs", { site: { name, url: $("#siteUrl").value.trim(), offers }, site_boost: $("#siteBoost").checked, site_tools: tools });
  renderSite(); toast(name ? `${name} 연계를 저장했어요 · 다음 추천부터 반영돼요` : "연계를 껐어요");
};

/* ---------- 뉴스 검토 ---------- */
let NEWS = null, NEWS_SEC = "전체", NEWS_FILTER = "all";
const NEWS_KEY = "kp-news-reviewed";
function reviewedSet() { try { return new Set(JSON.parse(localStorage.getItem(NEWS_KEY) || "[]")); } catch { return new Set(); } }
function saveReviewed(set) { try { localStorage.setItem(NEWS_KEY, JSON.stringify([...set].slice(-3000))); } catch {} }
const newsId = r => (r.link || r.title).slice(-120);
async function loadNews(refresh = false) {
  $("#newsMeta").textContent = refresh ? "새로 불러오는 중…" : "분야별 헤드라인을 불러오는 중…";
  $("#newsRefresh").disabled = true;
  try { NEWS = await api("/api/news" + (refresh ? "?refresh=1" : "")); renderNews(); }
  catch (e) { $("#newsMeta").textContent = "뉴스를 불러오지 못했어요: " + e.message; }
  finally { $("#newsRefresh").disabled = false; }
}
const isNewsTopic = n => / 뉴스$/.test(n) || n === "분야별 뉴스 이슈";
let NEWS_ROWS = [];
function newsPlansHTML() {
  if (!RESULT) return `<div class="news-plans empty"><b>이 분야 블로그 제안</b><span>오늘의 추천을 한 번 실행하면 분야별 제안이 여기 나와요.</span></div>`;
  const pool = RESULT.topics.filter(t => NEWS_SEC === "전체" ? isNewsTopic(t.name) : t.name === `${NEWS_SEC} 뉴스`)
    .flatMap(t => t.items).sort((a, b) => b.score - a.score).slice(0, 5);
  const title = NEWS_SEC === "전체" ? "뉴스에서 뽑은 블로그 제안" : `${NEWS_SEC} 분야 블로그 제안`;
  if (!pool.length) return `<div class="news-plans empty"><b>${esc(title)}</b><span>${RESULT.topics.some(t => t.name === "분야별 뉴스 이슈") ? "이전 버전 결과예요. 오늘의 추천을 다시 실행하면 분야별로 나뉘어 나와요." : "이번 분석에서는 이 분야 제안이 없었어요. 아래 기사에서 [기획안 만들기]를 눌러 보세요."}</span></div>`;
  return `<div class="news-plans"><div class="np-head"><b>${esc(title)}</b><span>${fmtTime(RESULT.generated_at)} 분석 · 누르면 기획안</span></div>
    <ol>${pool.map((it, i) => `<li><button data-open="${it.id}"><i>${i + 1}</i><span class="np-kw">${esc(it.keyword)}</span><span class="np-line">${esc(it.brief.titles[0])}</span><em>${Math.round(it.score)}</em></button></li>`).join("")}</ol></div>`;
}
async function newsPlan(btn) {
  const r = NEWS_ROWS[+btn.dataset.newsplan];
  if (!r) return;
  const kw = (r.terms && r.terms[0]) || r.title.replace(/\[[^\]]*\]/g, "").trim().split(/\s+/).slice(0, 2).join(" ");
  // 오늘 분석에 이미 같은 핵심어 기획안이 있으면 바로 열기
  const ready = RESULT?.topics.find(t => t.name === `${r.section} 뉴스`)?.items.find(it => it.keyword.replace(/\s/g, "") === kw.replace(/\s/g, ""));
  if (ready) { const s = reviewedSet(); s.add(newsId(r)); saveReviewed(s); openDrawer(ready); renderNews(); return; }
  btn.disabled = true; btn.classList.add("busy"); if (btn.classList.contains("nr-plan")) btn.textContent = "기획안 쓰는 중…";
  toast("이 기사로 블로그 기획안을 만들고 있어요 · 20~60초");
  try {
    ANALYZE = await api("/api/analyze", { keyword: kw, section: r.section, title: r.title, source: r.source || "", link: /^https?:/.test(r.link || "") ? r.link : "" });
    $("#analyzeInput").value = ANALYZE.keyword;
    const s = reviewedSet(); s.add(newsId(r)); saveReviewed(s);
    openDrawer(ANALYZE.items[0]);
  } catch (e) { toast("기획안을 만들지 못했어요: " + e.message); }
  finally { btn.disabled = false; btn.classList.remove("busy"); renderNews(); }
}
function renderNews() {
  if (!NEWS) return;
  const secs = NEWS.sections || {}, done = reviewedSet();
  const all = Object.entries(secs).flatMap(([k, rows]) => rows.map(r => ({ ...r, section: k })));
  const total = all.length, seen = all.filter(r => done.has(newsId(r))).length;
  const dropped = Object.values(NEWS.dropped || {}).reduce((a, b) => a + b, 0);
  $("#newsMeta").textContent = `${fmtTime(NEWS.fetched_at)} 기준 · 정치·사건사고 기사 ${dropped}건 자동 제외`;
  $("#newsProgress").innerHTML = `<span class="np-label">검토</span><b>${seen}</b><span>/ ${total}</span><div class="np-track"><i style="width:${total ? seen / total * 100 : 0}%"></i></div>`;
  const tabs = [["전체", all]].concat(Object.entries(secs).map(([k, rows]) => [k, rows.map(r => ({ ...r, section: k }))]));
  $("#newsSections").innerHTML = tabs.map(([k, rows]) => {
    const left = rows.filter(r => !done.has(newsId(r))).length;
    return `<button role="tab" aria-selected="${k === NEWS_SEC}" data-ns="${esc(k)}"><span>${esc(k)}</span><small>${left ? `${left}개 남음` : "다 봤어요"}</small>${k !== "전체" && NEWS.dropped?.[k] ? `<em>${NEWS.dropped[k]}건 제외</em>` : ""}</button>`;
  }).join("");
  const q = $("#newsSearch").value.trim().toLowerCase();
  let rows = (tabs.find(t => t[0] === NEWS_SEC) || tabs[0])[1];
  if (NEWS_FILTER === "todo") rows = rows.filter(r => !done.has(newsId(r)));
  if (q) rows = rows.filter(r => r.title.toLowerCase().includes(q));
  $("#newsPlans").innerHTML = newsPlansHTML();
  NEWS_ROWS = rows;
  $("#newsList").innerHTML = rows.length ? rows.map((r, idx) => {
    const id = newsId(r), ok = done.has(id);
    return `<li class="news-row ${ok ? "done" : ""}">
      <label class="nr-check" title="검토 표시"><input type="checkbox" data-review="${esc(id)}" ${ok ? "checked" : ""}><span></span></label>
      <div class="nr-main">
        <div class="nr-meta"><em>${esc(r.section)}</em><span>${esc(r.source || "")}</span><span>${esc(r.pub || "")}</span></div>
        <a class="nr-title" href="${esc(r.link)}" target="_blank" rel="noopener" data-readlink="${esc(id)}">${esc(r.title)}</a>
        <div class="nr-actions"><button class="nr-plan" data-newsplan="${idx}">기획안 만들기</button>
        <div class="nr-terms">${(r.terms || []).slice(0, 3).map(t => `<button data-analyze="${esc(t)}" title="‘${esc(t)}’ 키워드 분석">${esc(t)}</button>`).join("")}</div></div>
      </div>
    </li>`;
  }).join("") : `<li class="news-empty">${NEWS_FILTER === "todo" ? "이 분야 기사는 다 검토했어요." : "기사가 없어요."}</li>`;
}
document.addEventListener("click", e => {
  const ip = e.target.closest("[data-issueplan]");
  if (ip && RESULT) {
    const h = RESULT.hot_issues[+ip.dataset.issueplan];
    NEWS_ROWS = [{ title: h.summary, section: h.section, source: h.news_source || "", terms: [h.keyword], link: h.summary }];
    ip.dataset.newsplan = "0"; newsPlan(ip); return;
  }
  const np = e.target.closest("[data-newsplan]");
  if (np) { e.preventDefault(); newsPlan(np); return; }
  const ns = e.target.closest("[data-ns]");
  if (ns) { if (ns.dataset.ns !== NEWS_SEC) navPush({ ns: ns.dataset.ns }); NEWS_SEC = ns.dataset.ns; renderNews(); $(".news-list-wrap").scrollTop = 0; return; }
  const nf = e.target.closest("[data-nf]");
  if (nf) { NEWS_FILTER = nf.dataset.nf; $$("#newsFilter button").forEach(b => b.setAttribute("aria-checked", String(b === nf))); renderNews(); return; }
  const rl = e.target.closest("[data-readlink]");
  if (rl) { const s = reviewedSet(); s.add(rl.dataset.readlink); saveReviewed(s); setTimeout(renderNews, 200); }
});
document.addEventListener("change", e => {
  const cb = e.target.closest("[data-review]");
  if (!cb) return;
  const s = reviewedSet(); cb.checked ? s.add(cb.dataset.review) : s.delete(cb.dataset.review); saveReviewed(s); renderNews();
});
$("#newsSearch").addEventListener("input", renderNews);
$("#newsRefresh").onclick = () => loadNews(true);


/* ---------- 상시 키워드 사전 ---------- */
let EG = null, EG_TOPIC = "내 주제", EG_V = null, EG_LIMIT = 60, EG_POLL = null;
const EG_ORDER = { "상시": 0, "대체로 상시": 1, "계절형": 2, "미검증": 3, "하락": 4, "검색 적음": 5 };
async function loadEvergreen() {
  try { EG = await api("/api/evergreen"); } catch (e) { $("#egMeta").textContent = "사전을 불러오지 못했어요: " + e.message; return; }
  if (EG_V == null) EG_V = EG.checked_at ? "상시" : "전체";
  renderEvergreen();
  if (EG.job?.running) pollEvergreen();
}
function egSpark(series) {
  if (!series || !series.length || !series.some(v => v > 0)) return `<span class="muted">—</span>`;
  const s = series.slice(-24), max = Math.max(...s, 1);
  const pts = s.map((v, i) => `${(i / (s.length - 1) * 80).toFixed(1)},${(19 - v / max * 17).toFixed(1)}`).join(" ");
  return `<svg class="spark" viewBox="0 0 80 20" width="80" height="20" aria-label="최근 24개월 검색 추이"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
}
function egRows() {
  const topics = EG_TOPIC === "전체" ? Object.keys(EG.topics) : EG_TOPIC === "내 주제" ? STATE.topics.filter(t => EG.topics[t]) : [EG_TOPIC];
  const q = $("#egSearch").value.trim().replace(/\s/g, "");
  const nk = k => k.replace(/\s/g, "").toLowerCase();
  let rows = topics.flatMap(t => EG.topics[t].map(k => ({ k, t, r: EG.results[nk(k)] || {}, m: (EG.meta || {})[nk(k)] || {} })));
  rows.forEach(x => x.v = x.r.verdict || "미검증");
  if (EG_V === "상시") rows = rows.filter(x => x.v === "상시" || x.v === "대체로 상시");
  else if (EG_V === "계절형") rows = rows.filter(x => x.v === "계절형");
  else if (EG_V === "고단가") rows = rows.filter(x => x.r.high_value || (x.r.cpc == null && !x.r.comp && x.m.type === "고단가"));  // 광고 데이터가 없으면 자료상 고단가 후보로
  else if (EG_V === "생활해결") rows = rows.filter(x => x.m.type === "생활해결");
  if (q) rows = rows.filter(x => x.k.replace(/\s/g, "").includes(q));
  rows.sort((a, b) => (EG_ORDER[a.v] - EG_ORDER[b.v]) || ((b.r.score ?? -1) - (a.r.score ?? -1)) || a.k.localeCompare(b.k));
  return rows;
}
function renderEvergreen() {
  if (!EG) return;
  const all = Object.values(EG.results || {});
  const cnt = v => all.filter(r => r.verdict === v).length;
  $("#egMeta").innerHTML = EG.checked_at
    ? `${EG.count}개 · ${fmtTime(EG.checked_at)} 검증 · <b class="v-ok">상시 ${cnt("상시") + cnt("대체로 상시")}</b> · <b class="v-season">계절형 ${cnt("계절형")}</b> · 하락 ${cnt("하락")} · 검색 적음 ${cnt("검색 적음")}${EG.level && !EG.level.naver ? " · <span class='v-warn'>1년 추이는 API HUB 키가 있어야 검증돼요</span>" : ""}`
    : `${EG.count}개 후보 · 아직 검증 전이에요. <b>상시성 검증하기</b>를 누르면 최근 24개월 검색 추이로 ‘정말 1년 내내 찾는지’ 판정합니다(약 3~6분).`;
  const opts = [["내 주제", STATE.topics.filter(t => EG.topics[t]).reduce((a, t) => a + EG.topics[t].length, 0)], ["전체", EG.count]]
    .concat(Object.entries(EG.topics).map(([t, ks]) => [t, ks.length]));
  $("#egTopic").innerHTML = opts.map(([t, n]) => `<option value="${esc(t)}" ${t === EG_TOPIC ? "selected" : ""}>${esc(t)} (${n})</option>`).join("");
  $$("#egVerdict button").forEach(b => b.setAttribute("aria-checked", String(b.dataset.v === EG_V)));
  const rows = egRows();
  const vcls = v => ({ "상시": "ok", "대체로 상시": "ok2", "계절형": "season", "하락": "down", "검색 적음": "low" })[v] || "none";
  const flagTag = { ymyl: ["전문 정보", "돈·건강·법 주제: 공식 자료 근거, 단정 금지"], changes: ["변경 잦음", "앱·절차가 자주 바뀜: 확인 날짜 표시"], phone: ["번호형", "검색 결과에 번호가 바로 떠 클릭이 적을 수 있음(추정)"] };
  const tags = x => (x.m.type === "고단가" ? `<i class="eg-tag hv">고단가 후보</i>` : x.m.type === "생활해결" ? `<i class="eg-tag life">생활 해결</i>` : "") +
    (x.m.flag && flagTag[x.m.flag] ? `<i class="eg-tag fl" title="${esc(flagTag[x.m.flag][1])}">${flagTag[x.m.flag][0]}</i>` : "") +
    (x.m.auto === false ? `<i class="eg-tag off" title="오늘의 추천에는 자동으로 넣지 않아요">추천 제외</i>` : "");
  const adCell = r => r.cpc != null ? `<b>${fmtN(r.cpc)}원</b>${r.high_value ? `<em class="eg-hv">고단가</em>` : ""}` : r.comp ? `<span title="네이버 검색광고 경쟁도">${esc(r.comp)}</span>${r.high_value ? `<em class="eg-hv">고단가</em>` : ""}` : "—";
  $("#egTable").innerHTML = `<thead><tr><th>키워드</th><th>분야</th><th>판정</th><th>최근 24개월</th><th class="num">월 검색수</th><th class="num">블로그 글</th><th class="num" title="모바일 광고 3위 예상 입찰가(클릭당, 네이버 검색광고). 없으면 광고 경쟁도">광고 단가</th><th class="num">점수</th></tr></thead><tbody>` +
    (rows.length ? rows.slice(0, EG_LIMIT).map(x => `<tr data-eg="${esc(x.k)}" title="${esc(x.r.reason || "누르면 이 키워드를 분석해요")}">
      <td class="c-kw"><div class="kw">${esc(x.k)}${tags(x)}</div>${x.r.reason ? `<div class="line">${esc(x.r.reason)}</div>` : ""}</td>
      <td class="eg-t">${esc(x.t)}</td>
      <td><span class="eg-v ${vcls(x.v)}">${esc(x.v)}</span></td>
      <td class="eg-sp ${vcls(x.v)}">${egSpark(x.r.series)}</td>
      <td class="num">${x.r.volume != null ? fmtN(x.r.volume) : "—"}</td>
      <td class="num">${x.r.blog_total != null ? fmtN(x.r.blog_total) : "—"}</td>
      <td class="num eg-ad">${adCell(x.r)}</td>
      <td class="num"><b>${x.r.score != null ? Math.round(x.r.score) : "—"}</b></td></tr>`).join("")
      : `<tr><td colspan="8" class="muted" style="padding:28px;text-align:center">${EG_V === "상시" && !EG.checked_at ? "검증 전이라 ‘상시’ 판정이 아직 없어요. 상시성 검증하기를 눌러 주세요." : "조건에 맞는 키워드가 없어요."}</td></tr>`) + `</tbody>`;
  $("#egMore").innerHTML = rows.length > EG_LIMIT ? `<button class="btn" id="egMoreBtn">${rows.length - EG_LIMIT}개 더 보기</button>` : "";
  const job = EG.job || {};
  $("#egCheck").disabled = !!job.running;
  $("#egCheck").textContent = job.running ? "검증 중…" : EG.checked_at ? "다시 검증하기" : "상시성 검증하기";
  $("#egProgress").hidden = !job.running;
  if (job.running) { $("#egProgress i").style.width = (job.pct || 0) + "%"; $("#egProgress span").textContent = `${job.stage} · ${job.pct || 0}%`; }
}
function pollEvergreen() {
  clearInterval(EG_POLL);
  EG_POLL = setInterval(async () => {
    const d = await api("/api/evergreen").catch(() => null);
    if (!d) return;
    EG = d; renderEvergreen();
    if (!d.job.running) { clearInterval(EG_POLL); toast(d.job.error ? "검증은 끝났지만 일부 실패: " + d.job.error : "상시성 검증을 마쳤어요 · 다음 오늘의 추천부터 반영돼요"); if (EG_V === "전체" && d.checked_at) { EG_V = "상시"; renderEvergreen(); } }
  }, 1500);
}
$("#egCheck").onclick = async () => { const d = await api("/api/evergreen/check", {}); EG.job = d.job; renderEvergreen(); pollEvergreen(); };
$("#egTopic").onchange = e => { EG_TOPIC = e.target.value; EG_LIMIT = 60; renderEvergreen(); };
$("#egSearch").addEventListener("input", () => { EG_LIMIT = 60; renderEvergreen(); });
document.addEventListener("click", e => {
  const v = e.target.closest("#egVerdict [data-v]");
  if (v) { EG_V = v.dataset.v; EG_LIMIT = 60; renderEvergreen(); return; }
  if (e.target.closest("#egMoreBtn")) { EG_LIMIT += 100; renderEvergreen(); return; }
  const row = e.target.closest("[data-eg]");
  if (row) { $("#analyzeInput").value = row.dataset.eg; window.scrollTo({ top: 0, behavior: "smooth" }); runAnalyze(); }
});


/* ---------- AI 글쓰기: 설정 ---------- */
document.addEventListener("click", async e => {
  const pb = e.target.closest("#aiProvider [data-p]");
  if (pb) { STATE = await api("/api/prefs", { ai_provider: pb.dataset.p }); renderAI(); toast(`${pb.querySelector("b").textContent} 방식으로 초안을 써요`); }
});
$("#aiWeb").onchange = async e => { STATE = await api("/api/prefs", { ai_web_check: e.target.checked }); renderAI(); };
$("#autoDrafts").onchange = async e => { STATE = await api("/api/prefs", { auto_draft_per_day: Number(e.target.value) }); renderAuto(); toast(Number(e.target.value) ? `분석이 끝날 때마다 상위 글감으로 하루 ${e.target.value}편까지 미리 써 둘게요` : "자동 초안을 껐어요"); };
$("#agyPath").onchange = async e => { STATE = await api("/api/prefs", { agy_path: e.target.value.trim() }); renderAI(); };
$("#agyModel").onchange = async e => { STATE = await api("/api/prefs", { agy_model: e.target.value.trim() }); renderAI(); };
$("#claudeCodePath").onchange = async e => { STATE = await api("/api/prefs", { claude_code_path: e.target.value.trim() }); renderAI(); };
$("#copyGuideOnly").onclick = async () => { const d = await api("/api/memory"); copy(d.guide); toast("작가 지침을 복사했어요 · Claude 프로젝트 지침이나 Gemini Gems에 붙여 넣으세요"); };
$("#geminiModel").onchange = async e => { STATE = await api("/api/prefs", { gemini_model: e.target.value.trim() }); renderAI(); };
$("#aiCheck").onclick = async () => {
  await saveKeys();
  const b = $("#aiCheck"); b.disabled = true; b.textContent = "확인 중…";
  try {
    const r = await api("/api/ai/check", {});
    const p = STATE.ai.provider, cur = r[p] || { ok: true, message: "붙여넣기는 확인할 것이 없어요" };
    const st = $("#state-ai"); st.className = "keystate " + (cur.ok ? "ok" : "bad");
    st.textContent = p === "antigravity" ? `Antigravity: ${r.antigravity.message}`
      : p === "claude_code" ? `Claude Code: ${r.claude_code.message}` : p === "manual" ? cur.message
      : p === "gemini" ? `Gemini API: ${r.gemini.message}` : `Claude API: ${r.claude.message}`;
  } catch (err) { toast("확인하지 못했어요: " + err.message); }
  finally { b.disabled = false; b.textContent = "AI 연결 확인"; }
};
$("#guideSave").onclick = async () => { await api("/api/memory", { guide: $("#guideText").value, style: GUIDE_STYLE }); await loadMemory(); toast(STYLE_NAME[GUIDE_STYLE] + " 지침을 저장했어요 · 다음 초안부터 반영돼요"); };
$("#guideReset").onclick = async () => {
  if (!confirm(STYLE_NAME[GUIDE_STYLE] + " 지침을 기본값으로 되돌릴까요? 고친 내용은 사라집니다.")) return;
  const d = await api("/api/memory", { reset_guide: true, style: GUIDE_STYLE }); $("#guideText").value = d.guide; await loadMemory(); toast("기본 지침으로 되돌렸어요");
};

/* ---------- AI 초안 쓰기 ---------- */
let DRAFTS = [], DRAFT = null, DRAFT_FILTER = "전체", DRAFT_MODE = "preview";
let TIDY = false; const TIDY_SEL = new Set();  // 정리하기: 여러 초안을 골라 한 번에 삭제
const DRAFT_STATUSES = ["초안", "수정 중", "발행 완료"];
async function writeDraft(it, btn) {
  const ai = STATE.ai || {};
  if (ai.provider === "manual") return openManual(it);
  if (ai.provider === "antigravity" && !ai.antigravity) {
    // 화면을 연 뒤에 설치했을 수 있으니 최신 상태를 한 번 더 확인
    try { STATE = await api("/api/state"); } catch {}
    if ((STATE.ai || {}).antigravity) return writeDraft(it, btn);
    // 이 PC에 Antigravity가 없음 (예: 회사 PC) → 설치하거나, 이번 글은 붙여넣기 방식으로
    if (confirm("이 PC에는 Antigravity(Gemini 자동 작성)가 설치돼 있지 않아요.\n\n[확인] 지금 설치하기 (설정 화면으로 이동)\n[취소] 이번 글은 Gemini 앱에 붙여 넣는 방식으로 쓰기")) {
      hideDrawer(); showTab("settings"); setTimeout(() => { $(".ai-card")?.scrollIntoView({ behavior: "smooth" }); $("#agyState").textContent = "← ①을 눌러 설치하세요"; }, 300);
    } else openManual(it);
    return;
  }
  if ((ai.provider === "claude" && !ai.claude) || (ai.provider === "gemini" && !ai.gemini) || (ai.provider === "antigravity" && !ai.antigravity)) {
    toast(ai.provider === "antigravity" ? "먼저 설정 → AI 글쓰기에서 Antigravity CLI를 설치해 주세요" : "먼저 설정 → AI 글쓰기에서 키를 넣어 주세요"); hideDrawer(); showTab("settings");
    setTimeout(() => $(".ai-card")?.scrollIntoView({ behavior: "smooth" }), 200); return;
  }
  try {
    const r = await api("/api/draft", { item: it });
    WAIT_JOBS.add(r.job);
    toast(r.already ? `‘${it.keyword}’은(는) 이미 쓰는 중이에요 · 끝나면 바로 열어 드릴게요` : `‘${it.keyword}’ 초안을 쓰기 시작했어요 · 다른 화면을 봐도 계속 써요`);
    DQ = r.status; renderDock(); watchDrafts();
    hideDrawer();
  } catch (err) { toast(err.message); }
}

/* ---------- 초안 작성 현황 (오른쪽 아래): 프로그램이 직접 쓰는 중인 글 ---------- */
let DQ = null, DQ_POLL = null, DQ_SEEN = 0;
const WAIT_JOBS = new Set();
function renderDock() {
  let el = $("#writeDock");
  if (!el) { el = document.createElement("aside"); el.id = "writeDock"; el.className = "write-dock"; document.body.appendChild(el); }
  const q = DQ || {}, cur = q.current, wait = q.queue || [];
  const today = new Date().toISOString().slice(0, 10);
  const seen = dockSeenIds();
  const autoToday = DRAFTS.filter(d => d.auto && (d.created_at || "").slice(0, 10) === today && d.status === "초안");
  const fresh = autoToday.filter(d => !seen.includes(d.id));  // 한 번 닫거나 본 초안은 다시 알리지 않음
  if (!cur && !wait.length) {
    if (fresh.length) {
      el.hidden = false;
      el.innerHTML = `<button class="wd-x" data-dockclose aria-label="닫기">✕</button><b>새로 미리 써 둔 초안 ${fresh.length}편</b><span class="wd-sub">${fresh.map(d => esc(d.keyword)).join(" · ")}</span><button class="btn dark sm" data-dockopen="${esc(fresh[0].id)}">초안 보기 →</button>`;
    } else el.hidden = true;
    return;
  }
  const sec = cur ? Math.max(0, Math.round(Date.now() / 1000 - cur.started)) : 0;
  el.hidden = false;
  el.innerHTML = `<div class="wd-row"><span class="wd-spin" aria-hidden="true"></span><b>${cur ? `${cur.auto ? "미리 쓰는 중" : "초안 쓰는 중"}: ${esc(cur.keyword)}` : "곧 시작"}</b>${cur ? `<button class="btn sm wd-cancel" data-dqcancel="${cur.job}">취소</button>` : ""}</div>
    ${cur ? `<span class="wd-sub">${esc(cur.stage || "")} · ${Math.floor(sec / 60)}분 ${sec % 60}초</span>` : ""}
    ${wait.length ? `<div class="wd-wait">다음: ${wait.map(w => `<span class="wchip">${esc(w.keyword)}${w.auto ? "(자동)" : ""}<button data-dqcancel="${w.job}" aria-label="${esc(w.keyword)} 빼기">✕</button></span>`).join("")}</div>` : ""}
    <span class="wd-sub faint">${cur && /고쳐 쓰는/.test(cur.stage || "") ? "양식에서 크게 빠진 곳이 있어 한 번 더 쓰는 중 · 2~4분 더" : "Gemini(Antigravity)가 사실 확인하며 쓰는 중 · 보통 3~5분 · 다른 화면을 봐도 계속 써요 · 멈추려면 취소"}</span>`;
}
function dockSeenIds() { try { return JSON.parse(localStorage.getItem("dockSeenIds") || "[]"); } catch { return []; } }
function markDockSeen() {  // 지금 있는 자동 초안을 모두 '봤음'으로 (브라우저를 껐다 켜도 기억)
  try { localStorage.setItem("dockSeenIds", JSON.stringify([...new Set([...dockSeenIds(), ...DRAFTS.filter(d => d.auto).map(d => d.id)])].slice(-300))); } catch {}
}
function sessionStorageGet(k) { try { return sessionStorage.getItem(k); } catch { return null; } }
function sessionStorageSet(k, v) { try { sessionStorage.setItem(k, v); } catch {} }
async function pollDrafts() {
  try { DQ = await api("/api/draft/status"); } catch { return; }
  for (const ev of DQ.events || []) {
    if (ev.job <= DQ_SEEN && !WAIT_JOBS.has(ev.job)) continue;
    DQ_SEEN = Math.max(DQ_SEEN, ev.job);
    const mine = WAIT_JOBS.delete(ev.job);
    if (ev.cancelled) { if (mine || ev.auto) toast(`‘${ev.keyword}’ 초안을 취소했어요`); continue; }
    if (ev.ok) {
      toast(`‘${ev.keyword}’ 초안 완성 · Gems 양식 ${ev.check}${ev.auto ? " · 자동으로 미리 썼어요" : ""}`);
      await loadDrafts(mine ? ev.id : undefined);
      if (mine) showTab("drafts");
    } else if (mine) {
      if (confirm(`‘${ev.keyword}’ 초안을 쓰지 못했어요.\n\n${ev.error}\n\n대신 붙여넣기 방식으로 만들까요? (요청문을 복사해 Gemini 앱·Gems에 붙여 넣는 방식)`)) {
        const it = findItem(ev.item_id) || { keyword: ev.keyword, brief: {}, metrics: {}, src: {} }; openManual(it);
      }
    }
  }
  renderDock();
  if (!DQ.current && !(DQ.queue || []).length && DQ_POLL) { clearInterval(DQ_POLL); DQ_POLL = null; }
}
function watchDrafts() { if (!DQ_POLL) DQ_POLL = setInterval(pollDrafts, 3000); }
document.addEventListener("click", async e => {
  const o = e.target.closest("[data-dockopen]");
  if (o) { markDockSeen(); showTab("drafts"); await loadDrafts(o.dataset.dockopen); renderDock(); return; }
  const cx = e.target.closest("[data-dqcancel]");
  if (cx) {
    const isCur = DQ?.current && String(DQ.current.job) === cx.dataset.dqcancel;
    if (isCur && !confirm(`‘${DQ.current.keyword}’ 초안 쓰기를 멈출까요? 지금까지 쓴 내용은 저장되지 않아요.`)) return;
    cx.disabled = true; if (isCur) cx.textContent = "멈추는 중…";
    try { const r = await api("/api/draft/cancel", { job: Number(cx.dataset.dqcancel) }); if (!isCur) WAIT_JOBS.delete(Number(cx.dataset.dqcancel)); DQ = r.status; renderDock(); if (!isCur) toast("대기 목록에서 뺐어요"); } catch (err) { toast(err.message); }
    return;
  }
  if (e.target.closest("[data-dockclose]")) { markDockSeen(); renderDock(); }
});
(async () => {  // 처음 열 때: 이미 끝난 이벤트는 알림 없이 넘기고, 쓰는 중이면 현황 표시
  try {
    DQ = await api("/api/draft/status"); DQ_SEEN = Math.max(0, ...(DQ.events || []).map(e => e.job));
    DRAFTS = await api("/api/drafts"); renderDock();
    if (DQ.current || (DQ.queue || []).length) watchDrafts();
  } catch {}
})();

/* ---------- 초안 보관함 ---------- */
async function loadDrafts(openId) {
  DRAFTS = await api("/api/drafts");
  if ($("#draftCount")) $("#draftCount").textContent = DRAFTS.length || 0;
  const id = openId || DRAFT?.id || DRAFTS[0]?.id;
  if (id) DRAFT = await api("/api/drafts/" + id); else DRAFT = null;
  renderDrafts();
}
function draftMd(md) {  // 간단한 마크다운 → 보기용 HTML
  const lines = (md || "").replace(/\r/g, "").split("\n"); let out = [], i = 0;
  const inline = s => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  while (i < lines.length) {
    const s = lines[i].trim();
    if (s.startsWith("|") && s.endsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
        if (!cells.every(c => /^:?-{2,}:?$/.test(c) || !c)) rows.push(cells);
        i++;
      }
      out.push(`<table class="dv-table">${rows.map((r, ri) => `<tr>${r.map(c => ri ? `<td>${inline(c)}</td>` : `<th>${inline(c)}</th>`).join("")}</tr>`).join("")}</table>`);
      continue;
    }
    if (s.startsWith(">")) {
      const q = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) { q.push(lines[i].trim().replace(/^>\s?/, "")); i++; }
      const warn = q.some(x => x.includes("⚠"));
      out.push(`<div class="dv-quote ${warn ? "warn" : "tip"}">${q.map(x => `<p>${inline(x)}</p>`).join("")}</div>`);
      continue;
    }
    if (/^[✔▪]/.test(s)) { out.push(`<p class="dv-chk">${inline(s)}</p>`); i++; continue; }
    if (!s) out.push("");
    else if (s.startsWith("```") || s.startsWith("~~~")) { /* 프롬프트 블록 표시 줄은 숨김 */ }
    else if (/^[-=]{3,}$/.test(s)) out.push("<hr>");
    else if (s.startsWith("## ")) out.push(`<h3>${inline(s.slice(3))}</h3>`);
    else if (s.startsWith("# ")) out.push(`<h2>${inline(s.slice(2))}</h2>`);
    else if (s.startsWith("[📸")) out.push(`<p class="dv-img">${esc(s)}</p>`);
    else if (s.startsWith("[")) out.push(`<p class="dv-mark">${esc(s)}</p>`);
    else if (s.startsWith("■")) out.push(`<p class="dv-sec">${inline(s)}</p>`);
    else if (/^[-*•]\s+/.test(s)) out.push(`<p class="dv-li">• ${inline(s.replace(/^[-*•]\s+/, ""))}</p>`);
    else out.push(`<p>${inline(s)}</p>`);
    i++;
  }
  return out.join("\n");
}
function bodyPart(md) {
  let t = md || ""; const s = t.indexOf("[본문 시작]");
  if (s >= 0) t = t.slice(s + "[본문 시작]".length);
  // 맨 위 '주제 · 세부주제' 라벨 줄·'확인 일자: …' 줄은 복사하지 않음
  { const ls = t.split("\n"); let seen = 0;
    for (let i = 0; i < ls.length && seen < 4; i++) { const x = ls[i].trim(); if (!x) continue; seen++;
      if (/^확인 (일자|시각)\s*[:：]/.test(x) || (x.length <= 30 && /^[^.!?:：#\[\]|>]+ · [^.!?:：#\[\]|>]+$/.test(x))) ls[i] = null; }
    t = ls.filter(x => x !== null).join("\n").replace(/\n{3,}/g, "\n\n"); }
  const e = t.search(/\n(?:-{3,}\s*\n+\s*)?■\s*(?:네이버 블로그|참고한|Gemini 이미지)/);
  let b = (e >= 0 ? t.slice(0, e) : t).trim();
  // 예전 초안에도 AI 이미지 안내 한 줄을 붙여 복사
  if (!/AI로 (만든|생성)/.test(b)) b = b.replace(/\n-{3,}\s*$/, "").trim() + "\n\n※ 본문 이미지 중 일부는 AI로 만든 이미지로, 실제 모습과 다를 수 있습니다.";
  return b;
}
/* 하단의 Gemini 이미지 프롬프트 3개를 뽑아 복사 카드로 */
function imagePrompts(md) {
  const t = md || "";
  const s = t.search(/■\s*(Gemini 이미지 프롬프트|이미지 생성 가이드)/);
  if (s < 0) return [];
  let sec = t.slice(s); const tg = sec.search(/\n(?:-{3,}\s*\n+\s*)?■\s*네이버 블로그/); if (tg > 0) sec = sec.slice(0, tg);
  const parts = sec.split(/(?=\[📸\s*이미지\s*#\d)/).slice(1);
  return parts.map(p => {
    const head = (p.match(/\[📸\s*([^\]]+)\]/) || [, ""])[1].trim();
    const fence = p.match(/(?:~~~|```)[a-z]*\n([\s\S]*?)\n\s*(?:~~~|```)/i);
    const line = p.match(/Prompt:\s*([\s\S]*?)(?:\n\s*-\s|\n\s*\n|$)/);
    const what = (p.match(/-\s*담을 내용:\s*(.+)/) || p.match(/-\s*(?:대표할 내용|핵심 메시지):\s*(.+)/) || [, ""])[1].trim();
    const ko = (p.match(/-\s*(?:이미지 속 한글|카드 문구):\s*(.+)/) || [, ""])[1].trim();
    return { head, what, ko, prompt: (fence ? fence[1] : line ? line[1] : "").trim() };
  }).filter(x => x.prompt);
}
function promptCardsHTML(md) {
  const ps = imagePrompts(md);
  if (!ps.length) return "";
  return `<section class="img-prompts"><div class="ip-head"><b>Gemini 이미지 프롬프트</b><span>복사해서 Gemini에 붙여 넣으면 이미지가 만들어져요</span><a class="btn sm" href="https://gemini.google.com/app" target="_blank" rel="noopener">Gemini 열기 ↗</a></div>
    <div class="ip-grid">${ps.map((x, i) => `<article class="ip-card"><div class="ip-no">#${i + 1}</div><h4>${esc(x.head)}</h4>${x.what ? `<p class="ip-what">${esc(x.what)}</p>` : ""}${x.ko ? `<p class="ip-ko">${esc(x.ko)}</p>` : ""}
      <pre class="ip-pre">${esc(x.prompt)}</pre><button class="btn dark sm" data-copy="${esc(x.prompt)}">프롬프트 복사</button></article>`).join("")}</div></section>`;
}
function refsPart(md) { const m = (md || "").match(/■\s*참고한 공식 자료[^\n]*\n([\s\S]*?)(?=\n\s*(?:-{3,}|■)|$)/); return m ? ("■ 참고한 공식 자료\n" + m[1].trim()) : ""; }
function tagsPart(md) { const m = (md || "").match(/■\s*네이버 블로그[^\n]*\n+([^\n]+)/); return m ? m[1].trim() : ""; }
function renderDrafts() {
  const counts = s => DRAFTS.filter(d => d.status === s).length;
  $("#draftFilter").innerHTML = ["전체", ...DRAFT_STATUSES].map(s => `<button role="radio" aria-checked="${s === DRAFT_FILTER}" data-df="${s}">${s} <small>${s === "전체" ? DRAFTS.length : counts(s)}</small></button>`).join("");
  const list = DRAFTS.filter(d => DRAFT_FILTER === "전체" || d.status === DRAFT_FILTER);
  if ($("#draftTidy")) $("#draftTidy").textContent = TIDY ? "정리 끝내기" : "정리하기";
  const tidyBar = TIDY ? `<div class="tidy-bar"><b>${TIDY_SEL.size}개 선택</b><button class="btn sm" type="button" id="tidyAll">${list.length && list.every(d => TIDY_SEL.has(d.id)) ? "선택 해제" : "모두 선택"}</button><button class="btn sm danger-btn" type="button" id="tidyDel" ${TIDY_SEL.size ? "" : "disabled"}>선택한 초안 삭제</button></div>` : "";
  $("#draftList").innerHTML = tidyBar + (list.length ? list.map(d => `<button class="dl-item ${TIDY ? "tidy" : ""} ${TIDY && TIDY_SEL.has(d.id) ? "sel" : ""} ${!TIDY && DRAFT && d.id === DRAFT.id ? "on" : ""}" data-did="${esc(d.id)}">${TIDY ? `<span class="dl-box" aria-hidden="true">${TIDY_SEL.has(d.id) ? "✓" : ""}</span>` : ""}
      <span class="dl-meta"><i class="dl-st s${DRAFT_STATUSES.indexOf(d.status)}">${esc(d.status)}</i>${d.auto ? `<i class="dl-auto">자동</i>` : ""}${d.check ? `<i class="dl-chk ${d.check.ok ? "ok" : ""}">양식 ${d.check.passed}/${d.check.total}</i>` : ""}${esc(fmtTime(d.created_at))}</span>
      <b>${esc(d.title || d.keyword)}</b><span class="dl-kw">${esc(d.keyword)} · ${d.chars ? d.chars.toLocaleString() + "자" : ""}</span></button>`).join("")
    : `<div class="dl-empty">${DRAFTS.length ? "이 상태의 초안이 없어요." : "아직 초안이 없어요.<br>추천 글감의 기획안에서 <b>AI 초안 쓰기</b>를 누르면 프로그램이 작가 지침대로 써서 여기에 보관해요. 자동 분석 때 상위 글감은 미리 써 두기도 해요."}</div>`);
  if (!DRAFT) { $("#draftView").innerHTML = `<div class="dv-empty"><h2>초안을 고르세요</h2><p class="muted">왼쪽 목록에서 초안을 누르면 여기에서 보고 고칠 수 있어요.</p></div>`; return; }
  const d = DRAFT, chars = d.chars || 0, okLen = chars >= 3000;
  $("#draftView").innerHTML = `
    <header class="dv-head">
      <div class="dv-meta"><span>${esc(d.keyword)}</span><span>${esc(fmtTime(d.created_at))}</span><span>${esc(AI_NAME[d.provider] || d.provider || "")} · ${esc(d.model || "")}</span>${d.style ? `<span>${STYLE_NAME[d.style] || ""} 지침</span>` : ""}<span>${d.web === true ? "웹 검색으로 사실 확인" : d.web === false ? "웹 검색 없이 작성" : "참고 자료 칸에서 출처 확인"}</span>${d.seconds ? `<span>작성 ${Math.floor(d.seconds / 60)}분 ${d.seconds % 60}초${d.fixed && d.first_seconds ? ` (첫 작성 ${Math.floor(d.first_seconds / 60)}분 ${d.first_seconds % 60}초 + 고쳐 쓰기)` : ""}</span>` : ""}</div>
      <h2>${esc(d.title || d.keyword)}</h2>
      <div class="dv-stats"><b class="${okLen ? "ok" : "warn"}">본문 ${chars.toLocaleString()}자</b><span>${okLen ? "분량 기준(3,000자↑) 충족" : "분량 기준 3,000자에 못 미쳐요"} · 확인 일자~자주 묻는 질문, 공백 포함 대략값</span>${d.auto ? `<i class="dv-auto">자동으로 미리 씀</i>` : ""}</div>
      ${d.check ? `<details class="dv-check ${d.check.ok ? "ok" : "warn"}"><summary><b>Gems 양식 검사 ${d.check.passed}/${d.check.total}</b><span>${d.check.ok ? "작가 지침의 출력 양식을 모두 지켰어요" : d.intent ? "내 생각에 맞춰 형식을 바꾼 글이라 기본 틀과 다른 항목은 ✕로 보일 수 있어요 (자동으로 되돌리지 않음)" : "아래 ✕ 항목은 편집에서 손보거나 다시 쓰기를 눌러 주세요"}${d.fixed ? " · 첫 결과에서 빠진 곳을 자동으로 고쳐 썼어요" : ""}</span></summary>
        <ul>${d.check.items.map(x => `<li class="${x.ok ? "ok" : "no"}">${x.ok ? "✓" : "✕"} ${esc(x.name)}${x.note ? ` <small>${esc(x.note)}</small>` : ""}</li>`).join("")}</ul></details>` : ""}
      <div class="dv-actions">
        <div class="dv-group">
          <div class="seg" role="radiogroup" aria-label="보기"><button role="radio" aria-checked="${DRAFT_MODE === "preview"}" data-dm="preview">미리보기</button><button role="radio" aria-checked="${DRAFT_MODE === "edit"}" data-dm="edit">편집</button></div>
          <select id="dvStatus" aria-label="상태">${DRAFT_STATUSES.map(s => `<option ${s === d.status ? "selected" : ""}>${s}</option>`).join("")}</select>
        </div>
        <div class="dv-group">
          <button class="btn copy-main" id="dvCopyBody" title="글자 크기·굵게·표까지 서식째 복사 → 네이버 글쓰기 화면에 그대로 붙여 넣기">📋 블로그에 붙일 본문 복사</button>
          <a class="btn" href="/api/drafts/${encodeURIComponent(d.id)}/docx" download="${esc((d.created_at || "").slice(0, 10) + "_" + (d.keyword || "초안").replace(/[\\/:*?"<>|]+/g, " ").slice(0, 40) + ".docx")}">docx 저장</a>
        </div>
        <div class="dv-group dv-right">
          <button class="btn dark" id="dvRevise" title="고칠 내용을 적으면 이 초안을 그 자리에서 고쳐요">AI로 고치기</button>
          <details class="dv-more">
            <summary class="btn">더보기${d.versions ? ` <small>되돌리기 ${d.versions}</small>` : ""} ▾</summary>
            <div class="dv-menu">
              <button id="dvCopyBody2" class="menu-copy">📋 블로그에 붙일 본문 복사</button>
              <button id="dvImgRedo" title="본문은 그대로 두고 Gemini 이미지 프롬프트만 새 이미지 원칙으로 다시 써요">🖼 이미지 프롬프트만 새로 쓰기</button>
              <button id="dvRedo" title="같은 글감으로 처음부터 다시 써서 이 초안을 덮어써요">다시 쓰기</button>
              <button id="dvRestyle" title="내용은 살리고 형식만 바꿔 이 초안을 덮어써요">형식 바꾸기</button>
              <button id="dvCopyPlain">본문 글자만 복사 (서식 없이)</button>
              <button id="dvCopyAll">전체 복사 (기획·프롬프트 포함)</button>
              ${d.versions ? `<button id="dvUndo">되돌리기 (이전 버전 ${d.versions}개)</button>` : ""}
              <button id="dvDelete" class="danger">삭제</button>
            </div>
          </details>
        </div>
      </div>
    </header>
    <div class="dv-revise" id="dvReviseBox" hidden>
      <b>어떻게 고칠까요?</b> <small class="muted">요청한 부분만 고치고 나머지는 그대로 둬요 · 이 초안을 덮어쓰고, 이전 내용은 되돌리기로 복구할 수 있어요</small>
      <textarea id="dvReviseText" rows="3" placeholder="예) 소제목 2를 더 짧게, 마무리 문단을 담백하게, 대표 이미지 프롬프트를 겨울 분위기로 다시"></textarea>
      <div class="row-end"><button class="btn" type="button" id="dvReviseCancel">닫기</button><button class="btn dark" type="button" id="dvReviseGo">고치기 ✍</button></div>
    </div>
    ${promptCardsHTML(d.text)}
    ${d.sources?.length ? `<details class="dv-sources"><summary>AI가 확인한 웹 자료 ${d.sources.length}개</summary><ul>${d.sources.map(s => `<li><a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.title)}</a></li>`).join("")}</ul></details>` : ""}
    ${DRAFT_MODE === "edit"
      ? `<textarea id="dvText" class="dv-text" spellcheck="false">${esc(d.text)}</textarea><div class="row-end"><span class="muted" id="dvSaved"></span><button class="btn dark" id="dvSave">고친 내용 저장</button></div>`
      : `<div class="dv-body">${draftMd(d.text)}</div>`}`;
  $("#dvStatus").onchange = async e => { DRAFT = await api("/api/drafts/" + d.id, { action: "status", status: e.target.value }); DRAFTS = await api("/api/drafts"); renderDrafts(); toast(`‘${e.target.value}’로 바꿨어요`); };
  $("#dvCopyBody").onclick = () => copySmart(d.text);
  if ($("#dvCopyBody2")) $("#dvCopyBody2").onclick = () => { $(".dv-more").open = false; copySmart(d.text); };
  $("#dvCopyAll").onclick = () => copy(d.text);
  $("#dvCopyPlain").onclick = () => copy(bodyPart(d.text).replace(/\*\*(.+?)\*\*/g, "$1").replace(/^>\s?/gm, "") + (refsPart(d.text) ? "\n\n" + refsPart(d.text) : "") + "\n\n" + tagsPart(d.text));
  $("#dvDelete").onclick = async () => { if (!confirm("이 초안을 삭제할까요?")) return; DRAFTS = await api("/api/drafts/" + d.id, { action: "delete" }); DRAFT = null; await loadDrafts(); toast("삭제했어요"); };
  $("#dvRevise").onclick = () => { $("#dvReviseBox").hidden = false; $("#dvReviseText").focus(); };
  $("#dvReviseCancel").onclick = () => { $("#dvReviseBox").hidden = true; };
  $("#dvImgRedo").onclick = async () => {
    $(".dv-more").open = false;
    if (!confirm("본문은 그대로 두고 이미지 프롬프트만 새로 쓸까요? (이 초안을 덮어쓰고, 되돌리기 가능)")) return;
    await writeDraft({ id: "rv-" + Date.now(), keyword: d.keyword, topic: d.topic || "", style: d.style || "info", brief: {}, metrics: {}, src: {}, target_id: d.id,
      revise_instruction: "본문·참고한 공식 자료·태그는 한 글자도 바꾸지 말고 그대로 두세요. '■ Gemini 이미지 프롬프트' 부분만 작가 지침의 '이미지 최우선 원칙'과 대표 이미지 규칙에 따라 전면 다시 쓰세요: 이미지마다 '전하는 핵심'(본문 문장)을 먼저 정하고, 본문의 고유 대상이 주인공인 이미지로, 장마다 다른 표현 방식(일러스트·플랫레이·디오라마·분할 비교·콜라주 등)으로, 대표 이미지는 글 전체 요약의 두 핵심어가 보이는 잡지 표지급으로. 내용과 상관없는 분위기 이미지는 빼고, 보여 줄 핵심이 없으면 그 이미지는 생략하세요. 본문 속 [📸 이미지 #N …] 자리 표시도 새 프롬프트와 맞게 고치세요." });
  };
  $("#dvReviseGo").onclick = async () => {
    const ins = $("#dvReviseText").value.trim();
    if (!ins) { toast("고칠 내용을 적어 주세요"); return; }
    $("#dvReviseBox").hidden = true;
    await writeDraft({ id: "rv-" + Date.now(), keyword: d.keyword, topic: d.topic || "", style: d.style || "info", brief: {}, metrics: {}, src: {},
                       target_id: d.id, revise_instruction: ins });
  };
  if ($("#dvUndo")) $("#dvUndo").onclick = async () => {
    if (!confirm("덮어쓰기 전 내용으로 되돌릴까요?")) return;
    try { DRAFT = await api("/api/drafts/" + d.id, { action: "undo" }); DRAFTS = await api("/api/drafts"); renderDrafts(); toast("이전 버전으로 되돌렸어요"); } catch (err) { toast(err.message); }
  };
  $("#dvRestyle").onclick = async () => {
    const to = d.style === "info" || !d.style ? "essay" : "info";
    openFix(d.text || "", { style: to, title: d.title || d.keyword, target: d.id,
      note: "다른 형식으로 바꿔 쓰는 초안입니다. 내용과 사실은 살리고, 위에서 고른 글 종류의 지침(구성·편집 형식·이미지 규칙)대로 다시 써 주세요." });
    toast("글 종류를 고르고 '고치기 시작'을 누르세요 · 이 초안을 덮어써요");
  };
  $("#dvRedo").onclick = async () => {
    const it = findItem(d.item_id) || { keyword: d.keyword, topic: d.topic, brief: {}, metrics: {}, src: {} };
    openPlan({ ...it, target_id: d.id }, { from: "초안 다시 쓰기 · 이 초안을 덮어써요" });
  };
  if (DRAFT_MODE === "edit") {
    const ta = $("#dvText");
    $("#dvSave").onclick = async () => { DRAFT = await api("/api/drafts/" + d.id, { action: "save", text: ta.value }); DRAFTS = await api("/api/drafts"); $("#dvSaved").textContent = "저장했어요 " + new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }); renderDrafts(); };
  }
}
document.addEventListener("click", async e => {
  const it = e.target.closest("[data-did]");
  if (it && TIDY) { const id = it.dataset.did; TIDY_SEL.has(id) ? TIDY_SEL.delete(id) : TIDY_SEL.add(id); renderDrafts(); return; }
  if (it) { DRAFT = await api("/api/drafts/" + it.dataset.did); renderDrafts(); $("#draftView").scrollTop = 0; return; }
  if (e.target.closest("#draftTidy")) { TIDY = !TIDY; TIDY_SEL.clear(); renderDrafts(); return; }
  if (e.target.closest("#tidyAll")) {
    const list = DRAFTS.filter(d => DRAFT_FILTER === "전체" || d.status === DRAFT_FILTER);
    if (list.every(d => TIDY_SEL.has(d.id))) TIDY_SEL.clear(); else list.forEach(d => TIDY_SEL.add(d.id));
    renderDrafts(); return;
  }
  if (e.target.closest("#tidyDel")) {
    const ids = [...TIDY_SEL]; if (!ids.length || !confirm(`초안 ${ids.length}개를 삭제할까요? 되돌릴 수 없어요.`)) return;
    for (const id of ids) { try { await api("/api/drafts/" + id, { action: "delete" }); } catch {} }
    if (DRAFT && TIDY_SEL.has(DRAFT.id)) DRAFT = null;
    TIDY_SEL.clear(); TIDY = false; await loadDrafts(); toast(`초안 ${ids.length}개를 삭제했어요`); return;
  }
  const df = e.target.closest("[data-df]");
  if (df) { DRAFT_FILTER = df.dataset.df; renderDrafts(); return; }
  const dm = e.target.closest("[data-dm]");
  if (dm) { DRAFT_MODE = dm.dataset.dm; renderDrafts(); }
});


/* ---------- 자동 업데이트: 새 분석이 끝나면 화면도 스스로 바꿈 ---------- */
setInterval(async () => {
  try {
    if (document.hidden) return;
    const st = await api("/api/status");
    pollDrafts().then(() => { if (DQ && (DQ.current || (DQ.queue || []).length)) watchDrafts(); });
    if (st.running) { if (typeof POLL !== "undefined" && !POLL) watch(); return; }
    const list = await api("/api/history");
    if (list.length && RESULT && list[0].id !== RESULT.id && new Date(list[0].generated_at) > new Date(RESULT.generated_at)) {
      await loadHistory(list[0].id);
      toast(`새 분석이 도착했어요 · ${fmtTime(list[0].generated_at)}`);
    }
  } catch {}
}, 120000);


/* ---------- 붙여넣기 방식 ---------- */
let MANUAL = null;
async function openManual(it) {
  MANUAL = { item: it, prompt: null };
  $("#manualKw").textContent = `글감: ${it.keyword}`;
  $("#mResult").value = ""; $("#mInfo").textContent = "요청문 만드는 중…";
  hideDrawer(); openDialog($("#manualDialog"));
  try {
    MANUAL.prompt = await api("/api/draft/prompt", { item: it });
    $("#mInfo").textContent = `요청문 준비됨 · 지침 포함 ${MANUAL.prompt.full.length.toLocaleString()}자`;
  } catch (e) { $("#mInfo").textContent = "요청문을 만들지 못했어요: " + e.message; }
}
$("#mCopyShort").onclick = () => { if (MANUAL?.prompt) { copy(MANUAL.prompt.short); toast("짧은 요청문을 복사했어요 · 작가 지침이 들어 있는 프로젝트/Gem에 붙여 넣으세요"); } };
$("#mCopyFull").onclick = () => { if (MANUAL?.prompt) { copy(MANUAL.prompt.full); toast("지침 포함 요청문을 복사했어요 · 새 대화에 붙여 넣으세요"); } };
$("#mSave").onclick = async () => {
  const text = $("#mResult").value.trim();
  if (!MANUAL || text.length < 200) { toast("AI가 쓴 초안 전체를 붙여 넣어 주세요"); return; }
  try {
    const rec = await api("/api/draft/import", { item: MANUAL.item, text, where: $("#mWhere").value });
    $("#manualDialog").close();
    showTab("drafts"); await loadDrafts(rec.id);
    toast("초안으로 보관했어요");
  } catch (e) { toast(e.message); }
};


/* ---------- 스스로 일하기 · 공부하기 ---------- */
$("#autoStartup").onchange = async e => {
  try { const r = await api("/api/autostart", { on: e.target.checked }); STATE = r.state; toast(r.message); }
  catch (err) { toast(err.message); e.target.checked = !e.target.checked; }
  renderAuto();
};
$("#autoHours").onchange = async e => { STATE = await api("/api/prefs", { auto_refresh_hours: Number(e.target.value) }); toast(e.target.value === "0" ? "자동 분석을 껐어요" : `${e.target.value}시간마다 스스로 분석해요`); renderAuto(); };
$("#blogId").onchange = async e => { STATE = await api("/api/prefs", { blog_id: e.target.value.trim() }); renderAuto(); };
$("#blogLoad").onclick = async () => {
  STATE = await api("/api/prefs", { blog_id: $("#blogId").value.trim() });
  const b = $("#blogLoad"); b.disabled = true; b.textContent = "읽는 중…";
  try {
    const r = await api("/api/myblog", {});
    $("#blogInfo").textContent = r.error || `최근 글 ${r.posts.length}개를 읽었어요${r.posts[0] ? ` · 최신: ${r.posts[0].title}` : ""}`;
    STATE = await api("/api/state");
  } catch (err) { $("#blogInfo").textContent = err.message; }
  finally { b.disabled = false; b.textContent = "내 글 불러오기"; }
};
document.addEventListener("click", async e => {
  const u = e.target.closest("[data-undislike]");
  if (u) { STATE = await api("/api/prefs", { undislike: u.dataset.undislike }); renderAuto(); toast("다시 추천에 넣을게요"); }
});


/* ---------- 자동 업데이트: 새 버전이 있으면 위쪽에 버튼 ---------- */
async function checkUpdate(manual) {
  let u;
  try { u = await api("/api/update/check"); } catch (e) { if (manual) toast("새 버전을 확인하지 못했어요"); return; }
  let el = $("#updateBar");
  const av = $("#appVer");
  if (!u.available) { if (el) el.remove(); if (av) { av.classList.remove("has-upd"); av.textContent = "v" + String(u.current || "").slice(5); } if (manual) toast(u.error || `최신 버전이에요 (v${u.current})`); return; }
  if (av) { av.classList.add("has-upd"); av.textContent = "⬆ 새 버전"; }
  if (!el) { el = document.createElement("div"); el.id = "updateBar"; el.className = "update-bar"; document.body.prepend(el); }
  el.innerHTML = `<b>새 버전 v${esc(u.latest)}이 있어요</b>${u.notes ? `<span>${esc(u.notes)}</span>` : ""}<button class="btn dark sm" id="updateGo">지금 업데이트</button><button class="wd-x" id="updateLater" aria-label="나중에">✕</button>`;
  $("#updateLater").onclick = () => el.remove();
  $("#updateGo").onclick = async () => {
    if (DQ && (DQ.current || (DQ.queue || []).length) && !confirm("초안을 쓰는 중이에요. 업데이트하면 쓰던 초안은 취소돼요. 계속할까요?")) return;
    const b = $("#updateGo"); b.disabled = true; b.textContent = "받는 중…";
    try {
      await api("/api/update/apply", {});
      el.innerHTML = `<b>새 버전으로 다시 시작하는 중…</b><span>잠시 뒤 화면이 저절로 새로고침돼요. 키·초안·지침·설정은 그대로예요.</span>`;
      const old = (STATE && STATE.version) || "";
      for (let i = 0; i < 25; i++) {  // 최대 약 50초
        await new Promise(r => setTimeout(r, 2000));
        try { const v = await (await fetch("/api/version", { cache: "no-store" })).json(); if (v.version && v.version !== old) { location.reload(); return; } } catch {}
      }
      el.innerHTML = `<b>새 버전 파일은 받았어요.</b><span>다시 시작만 안 된 상태예요. 검은 창을 모두 닫고 START_windows.bat을 실행하면 새 버전으로 열려요.</span>`;
    } catch (err) { toast(err.message); b.disabled = false; b.textContent = "지금 업데이트"; }
  };
}
setTimeout(() => checkUpdate(false), 4000);
if ($("#updateCheck")) $("#updateCheck").onclick = () => checkUpdate(true);
if ($("#appVer")) $("#appVer").onclick = () => checkUpdate(true);
setInterval(() => checkUpdate(false), 6 * 3600 * 1000);


/* ---------- 검색한 키워드 → 글 콘셉트 · 내 기록 · AI 아이디어 ---------- */
const IDEAS_STATE = {};
function recordsHTML(r) {
  if (!r || (!r.posts?.length && !r.drafts?.length && !r.my_keywords?.length)) return "";
  return `<div class="block rec-box"><div class="block-head"><h2>내 기록</h2><span class="muted">이 키워드와 관련해 이미 한 것 · 겹치지 않게 다음 글을 고르세요</span></div>
    ${r.posts?.length ? `<p><b>내 블로그 글</b> ${r.posts.map(p => `<a href="${esc(p.link)}" target="_blank" rel="noopener" class="wchip">${esc(p.title)}</a>`).join("")}</p>` : ""}
    ${r.drafts?.length ? `<p><b>지난 초안</b> ${r.drafts.map(d => `<button class="wchip" data-opendraft="${esc(d.id)}">${esc(d.title)} <small>${esc(d.date)}</small></button>`).join("")}</p>` : ""}
    ${r.my_keywords?.length ? `<p><b>유입·인기 검색어</b> ${r.my_keywords.map(k => `<span class="wchip">${esc(k)}</span>`).join("")}</p>` : ""}</div>`;
}
function conceptsHTML(gs) {
  if (!gs.length) return "";
  return `<div class="block"><div class="block-head"><h2>글 콘셉트</h2><span class="muted">함께 찾는 검색어를 독자 상황별로 묶었어요 · 묶음 하나가 글 한 편</span></div>
    <div class="cc-grid">${gs.map((g, i) => `<article class="cc-card"><header><b>${esc(g.name)}</b><small>${g.guess ? "기본 콘셉트 · 연관 검색어 확인 전" : `검색어 ${g.count}개${g.volume ? ` · 월 ${g.volume.toLocaleString()}회` : ""}`}</small></header>
      <p class="cc-title">${esc(g.title)}</p><p class="cc-reader">${esc(g.reader)}</p>
      <div class="cc-kws">${g.keywords.map(k => `<button class="wchip" data-open="${esc(k.id)}">${esc(k.keyword)}${k.volume ? ` <small>${k.volume.toLocaleString()}</small>` : ""}</button>`).join("")}</div>
      <button class="btn dark sm" data-concept="${i}">이 콘셉트로 초안 쓰기 ✍</button></article>`).join("")}</div></div>`;
}
function ideasHTML(st) {
  const head = `<div class="block-head"><h2>AI 글 아이디어</h2><span class="muted">검색 수치·내 블로그 글·지난 초안·유입 검색어·최근 뉴스를 검토해서 제안 · 30초~2분</span></div>`;
  if (!st) return head + `<button class="btn primary" id="ideasGo">기록 검토해서 아이디어 받기</button>`;
  if (st.running) return head + `<div class="card loading"><div class="spinner"></div><div><b>기록을 검토하고 아이디어를 만드는 중</b><div class="muted" style="font-size:13px">${st.seconds || 0}초 · 다른 화면을 봐도 계속 만들어요</div></div></div>`;
  if (st.error) return head + `<p class="muted">${esc(st.error)}</p><button class="btn" id="ideasGo">다시 시도</button>`;
  return head + `<div class="idea-list">${st.ideas.map((x, i) => `<article class="idea-card"><div class="idea-no">${x.series || i + 1}</div><div class="idea-body">
      <h3>${esc(x.title)}</h3><p>${esc(x.concept)}</p>
      <p class="muted"><b>독자</b> ${esc(x.reader)}${x.keyword ? ` · <b>검색어</b> ${esc(x.keyword)}` : ""}</p>
      ${x.must_include?.length ? `<ul>${x.must_include.map(m => `<li>${esc(m)}</li>`).join("")}</ul>` : ""}
      <p class="idea-ev">근거: ${esc(x.evidence)}${x.link_to ? ` · 이어지는 내 글: ${esc(x.link_to)}` : ""}</p>
      <button class="btn dark sm" data-idea="${i}">이 아이디어로 초안 쓰기 ✍</button></div></article>`).join("")}</div>
    <button class="btn" id="ideasGo">다른 아이디어 받기</button>`;
}
function itemFor(kw) {
  const its = ANALYZE?.items || [];
  return its.find(c => norm2(c.keyword) === norm2(kw)) || its[0];
}
function norm2(s) { return (s || "").replace(/\s+/g, "").toLowerCase(); }
function withPlan(base, plan) {
  const it = JSON.parse(JSON.stringify(base));
  it.concept_plan = plan;
  it.brief = it.brief || {}; it.brief.titles = [plan.title, ...((it.brief.titles) || [])].filter(Boolean).slice(0, 3);
  return it;
}
async function pollIdeas(kw) {
  for (let i = 0; i < 100; i++) {
    let st;
    try { st = await api("/api/ideas?keyword=" + encodeURIComponent(kw)); } catch { break; }
    IDEAS_STATE[kw] = st;
    if (ANALYZE && ANALYZE.keyword === kw && $("#ideasBlock")) $("#ideasBlock").innerHTML = ideasHTML(st);
    if (!st.running) { if (st.ideas?.length) toast(`‘${kw}’ 글 아이디어 ${st.ideas.length}개를 만들었어요`); return; }
    await new Promise(r => setTimeout(r, 3000));
  }
}
document.addEventListener("click", async e => {
  if (e.target.closest("#ideasGo")) {
    const kw = ANALYZE.keyword;
    const items = ANALYZE.items.slice(0, 30).map(c => ({ keyword: c.keyword, score: c.score, metrics: { volume: c.metrics?.volume ?? null, blog_total: c.metrics?.blog_total ?? null }, id: c.id }));
    try { await api("/api/ideas", { keyword: kw, items }); IDEAS_STATE[kw] = { running: true, seconds: 0 }; $("#ideasBlock").innerHTML = ideasHTML(IDEAS_STATE[kw]); pollIdeas(kw); }
    catch (err) { toast(err.message); }
    return;
  }
  const c = e.target.closest("[data-concept]");
  if (c) {
    const g = ANALYZE.concepts[+c.dataset.concept];
    const base = (ANALYZE.items || []).find(x => x.id === g.lead_id) || ANALYZE.items[0];
    return openPlan(withPlan(base, { title: g.title, concept: g.angle, reader: g.reader, keywords: g.keywords.map(k => k.keyword) }),
                    { from: "글 콘셉트", note: `${g.title}\n${g.angle}` });
  }
  const d = e.target.closest("[data-idea]");
  if (d) {
    const x = IDEAS_STATE[ANALYZE.keyword].ideas[+d.dataset.idea];
    const base = itemFor(x.keyword);
    const it = withPlan(base, x);
    if (norm2(base.keyword) !== norm2(x.keyword)) it.keyword = x.keyword;
    return openPlan(it, { from: "AI 글 아이디어", note: [x.title, x.concept, x.must_include?.length ? "꼭 다룰 내용: " + x.must_include.join(", ") : ""].filter(Boolean).join("\n") });
  }
  const od = e.target.closest("[data-opendraft]");
  if (od) { showTab("drafts"); await loadDrafts(od.dataset.opendraft); }
});


/* ---------- 기획안의 '내 생각 반영' (메모 + 내 사이트 도구) ---------- */
function noteGet(kw) { try { return localStorage.getItem("note:" + kw) || ""; } catch { return ""; } }
function noteSet(kw, v) { try { v.trim() ? localStorage.setItem("note:" + kw, v) : localStorage.removeItem("note:" + kw); } catch {} }
function toolOptions(it) {
  const tools = STATE?.site_tools || [];
  const auto = it.tool ? tools.findIndex(t => t.name === it.tool.name) : -1;
  return `<option value="-1" ${auto < 0 ? "selected" : ""}>연결 안 함</option>` +
    tools.map((t, i) => `<option value="${i}" ${i === auto ? "selected" : ""}>${esc(t.name)}${i === auto ? " (자동 연결)" : ""}</option>`).join("");
}
function withMine(it) {
  const x = JSON.parse(JSON.stringify(it));
  const note = ($("#dNote")?.value || "").trim();
  if (note) { x.user_note = note; noteSet(it.keyword, note); }
  const sel = $("#dTool"); const tools = STATE?.site_tools || [];
  if (sel) x.tool = +sel.value >= 0 ? tools[+sel.value] : null;
  const ds = $("#dStyle [aria-checked=true]")?.dataset.ds;
  if (ds) x.style = ds;
  return x;
}
/* 설정: 내 사이트 도구 목록 (한 줄에 하나: 이름 | 주소 | 검색어1, 검색어2 | 설명) */
function toolsText() { return (STATE?.site_tools || []).map(t => [t.name, t.url, (t.keywords || []).join(", "), t.desc].join(" | ")).join("\n"); }
function renderTools() { if ($("#siteTools") && document.activeElement !== $("#siteTools")) $("#siteTools").value = toolsText(); if ($("#toolsCount")) $("#toolsCount").textContent = (STATE?.site_tools || []).length ? `${STATE.site_tools.length}개 등록` : ""; }
if ($("#saveTools")) $("#saveTools").onclick = async () => {
  const tools = $("#siteTools").value.split("\n").map(l => l.split("|").map(s => s.trim())).filter(p => p[0])
    .map(([name, url = "", kws = "", desc = ""]) => ({ name, url, keywords: kws.split(/[,，]/).map(s => s.trim()).filter(Boolean), desc }));
  if (tools.some(t => !t.keywords.length)) { toast("도구마다 연결할 검색어를 하나 이상 적어 주세요 (세 번째 칸)"); return; }
  STATE = await api("/api/prefs", { site_tools: tools }); renderTools();
  toast(tools.length ? `도구 ${tools.length}개를 저장했어요 · 다음 분석·검색부터 자동 연결돼요` : "도구 목록을 비웠어요");
};


/* ---------- '새 글' 창: 키워드 + 내 생각 → 초안 (또는 이미 쓴 글 고치기) ---------- */
let W_MODE = "new", PLAN_BASE = null;
function setWStyle(st) { $$("#wStyle [data-ws]").forEach(x => x.setAttribute("aria-checked", String((x.dataset.ws || "") === (st || "")))); }
/* 모든 글 기획의 단일 루트: 어디서 출발하든 이 창에서 키워드·글 종류·내 생각을 확인하고 쓴다 */
function openPlan(base, opts = {}) {
  PLAN_BASE = base ? JSON.parse(JSON.stringify(base)) : null;
  const kw = opts.keyword || base?.keyword || "";
  $("#wKeyword").value = kw;
  $("#wConcept").value = opts.note != null && opts.note !== "" ? opts.note : (kw ? noteGet(kw) : "");
  setWStyle(opts.style || base?.style || "");
  openWrite("new", opts.from);
  wStyleHint();
}
let FIX_TARGET = null;
function openFix(source, opts = {}) {
  FIX_TARGET = opts.target || null;
  $("#rwSource").value = source || ""; $("#rwNote").value = opts.note || "";
  setWStyle(opts.style || "");
  openWrite("fix", opts.title ? "초안 형식 바꾸기 · 이 초안을 덮어써요" : "");
}
function openWrite(mode, from) {
  W_MODE = mode;
  $("#wNewBox").hidden = mode !== "new"; $("#wFixBox").hidden = mode === "new";
  $("#wTitle").textContent = mode === "new" ? "글 기획" : "이미 쓴 글 고치기";
  $("#wSub").textContent = (from ? `출발: ${from} · ` : "") + (mode === "new" ? "키워드·글 종류·내 생각을 확인하고 쓰세요. 검색 데이터와 내 사이트 도구 연결은 프로그램이 알아서 합니다." : "글을 붙여 넣으면 작가 지침 형식으로 고쳐서 초안에 보관합니다.");
  $("#wSwitch").textContent = mode === "new" ? "이미 쓴 글 고치기 →" : "← 새 글 쓰기";
  $("#wGo").textContent = mode === "new" ? "AI 초안 쓰기 ✍" : "고치기 시작";
  openDialog($("#writeDialog")); setTimeout(() => (mode === "new" ? $("#wKeyword") : $("#rwSource")).focus(), 50);
}
$("#writeNew").onclick = () => openPlan(null, {});
$("#rewriteBtn").onclick = () => openFix("", {});
$("#writeNew").addEventListener("click", () => { FIX_TARGET = null; });
$("#wSwitch").onclick = () => openWrite(W_MODE === "new" ? "fix" : "new");
$("#wGo").onclick = async () => {
  if (W_MODE === "new") {
    const kw = $("#wKeyword").value.trim(), note = $("#wConcept").value.trim();
    if (!kw) { toast("키워드를 적어 주세요"); $("#wKeyword").focus(); return; }
    $("#writeDialog").close();
    const st = $("#wStyle [aria-checked=true]")?.dataset.ws || "";
    noteSet(kw, note);
    let it;
    if (PLAN_BASE && norm2(PLAN_BASE.keyword) === norm2(kw)) {  // 분석된 글감에서 출발: 수치·기획을 그대로 씀
      it = PLAN_BASE; it.user_note = note; delete it.style; if (st) it.style = st;
    } else {  // 키워드만: 서버가 검색 데이터를 먼저 모음
      it = { id: "new-" + Date.now(), keyword: kw.slice(0, 40), topic: "내 기획", brief: {}, metrics: {}, src: {}, user_note: note, enrich: true, ...(st ? { style: st } : {}) };
      if (PLAN_BASE?.concept_plan) it.concept_plan = PLAN_BASE.concept_plan;
      if (PLAN_BASE?.target_id) it.target_id = PLAN_BASE.target_id;
    }
    PLAN_BASE = null;
    await writeDraft(it);
    $("#wKeyword").value = ""; $("#wConcept").value = "";
    return;
  }
  const src = $("#rwSource").value.trim();
  if (src.length < 300) { toast("고칠 글을 300자 이상 붙여 넣어 주세요"); return; }
  const lines = src.split("\n").map(s => s.trim()).filter(s => s && !/^\[?(프로파일|URL 복사|통계|본문 기타 기능)/.test(s) && !/^https?:\/\//.test(s));
  const title = (lines.find(s => s.length >= 8 && !/^\[/.test(s)) || "기존 글").slice(0, 80);
  $("#writeDialog").close();
  const st2 = $("#wStyle [aria-checked=true]")?.dataset.ws || "";
  await writeDraft({ id: "rw-" + Date.now(), keyword: title, topic: "내 글 다듬기", brief: { titles: [title] }, metrics: {}, src: {},
                     rewrite_source: src.slice(0, 20000), user_note: $("#rwNote").value.trim(), ...(st2 ? { style: st2 } : {}), ...(FIX_TARGET ? { target_id: FIX_TARGET } : {}) });
  FIX_TARGET = null;
  $("#rwSource").value = ""; $("#rwNote").value = "";
};


/* ---------- 글 종류: 정보형 / 읽을거리형 (자동 판단은 서버와 같은 규칙) ---------- */
const ESSAY_RE = /영화|드라마|넷플릭스|티빙|디즈니\+|웨이브|쿠팡플레이|OTT|애니|웹툰|책|소설|에세이|도서|시집|음악|앨범|플레이리스트|노래|공연 후기|전시 후기|관람 후기|후기|리뷰|여행기|여행 코스|가볼만한|데이트|맛집|카페|브런치|일상|감성|추천작|작품|시리즈|명작/;
const INFO_RE = /신청|지원금|환급|세금|보험|대출|계산|기준|조건|방법|절차|서류|일정|마감|등급컷|과태료|요금|금리|연말정산|청약|발표|접수/;
function guessStyle(kw, topic) { if (DEAL_RE.test(kw || "")) return "deal"; if (INFO_RE.test(kw || "")) return "info"; return ESSAY_RE.test(`${kw || ""} ${topic || ""}`) ? "essay" : "info"; }
const STYLE_NAME = { info: "정보형", essay: "읽을거리형", deal: "할인·구매형" };
const DEAL_RE = /할인|블프|블랙프라이데이|사이버먼데이|직구|핫딜|특가|쿠폰|프로모션|캐시백|최저가|세일|타임딜|사전예약|사전 예약|얼리버드|예매 오픈|티켓 오픈|티켓팅|예매|요금제|통신사 혜택|카드 혜택|광군제|아마존|알리|테무|쿠팡 로켓|정가/;
function wStyleHint() { const kw = $("#wKeyword").value.trim(); $("#wStyleHint").textContent = kw && ($("#wStyle [aria-checked=true]")?.dataset.ws || "") === "" ? `자동 → ${STYLE_NAME[guessStyle(kw)]}` : ""; }
$("#wKeyword").addEventListener("input", wStyleHint);
document.addEventListener("click", e => {
  const b = e.target.closest("[data-ws]");
  if (b) { $$("#wStyle [data-ws]").forEach(x => x.setAttribute("aria-checked", String(x === b))); wStyleHint(); }
  const d = e.target.closest("[data-ds]");
  if (d) { $$("#dStyle [data-ds]").forEach(x => x.setAttribute("aria-checked", String(x === d))); }
});


/* ---------- 집·회사 같이 쓰기 (데이터 폴더) ---------- */
function renderSync() {
  const s = STATE?.sync; if (!s || !$("#syncState")) return;
  $("#syncState").textContent = s.local ? "· 지금은 이 PC 전용 폴더를 써요" : `· 공유 폴더 사용 중: ${s.data_dir}`;
  $("#syncOneDrive").disabled = !s.onedrive;
  $("#syncOneDrive").title = s.onedrive ? `${s.onedrive}\\KeywordPlanner_data` : "이 PC에서 OneDrive를 찾지 못했어요";
  $("#syncReset").hidden = s.local;
  let bar = $("#otherPcBar");
  if (s.others?.length) {
    if (!bar) { bar = document.createElement("div"); bar.id = "otherPcBar"; bar.className = "other-pc"; document.body.appendChild(bar); }
    bar.textContent = `다른 PC(${s.others.join(", ")})에서도 키워드 플래너가 켜져 있어요 · 자동 분석·자동 초안은 그 PC에서만 돌아요`;
  } else if (bar) bar.remove();
}
async function syncGo(body) {
  if (!confirm("데이터 폴더를 바꾸고 프로그램을 다시 시작할까요?\n(이미 그 폴더에 데이터가 있으면 그 데이터로 이어서 씁니다)")) return;
  try {
    const r = await api("/api/datadir", body);
    toast(r.message + " · 다시 시작하는 중…");
    const old = STATE.version;
    for (let i = 0; i < 25; i++) { await new Promise(r => setTimeout(r, 2000)); try { const v = await (await fetch("/api/version", { cache: "no-store" })).json(); if (v.version) { if (i > 1) { location.reload(); return; } } } catch {} }
    toast("다시 시작이 늦어지면 검은 창을 닫고 START_windows.bat을 실행해 주세요");
  } catch (err) { toast(err.message); }
}
if ($("#syncOneDrive")) {
  $("#syncOneDrive").onclick = () => syncGo({ onedrive: true });
  $("#syncCustom").onclick = () => { const p = $("#syncPath").value.trim(); if (!p) { toast("폴더 경로를 적어 주세요"); return; } syncGo({ path: p }); };
  $("#syncReset").onclick = () => syncGo({ reset: true });
}
setInterval(() => { try { renderSync(); } catch {} }, 3000);

document.addEventListener("click", e => {
  const m = document.querySelector(".dv-more[open]");
  if (m && (!m.contains(e.target) || e.target.closest(".dv-menu button"))) m.removeAttribute("open");
});


/* ---------- 스마트에디터용 서식 복사: 본문 16 · 소제목 19 파란 굵게 · 참고 자료 13 · 표 · 박스 ---------- */
function smartHtml(md) {
  const body = bodyPart(md), refs = refsPart(md), tags = tagsPart(md);
  const inl = s => esc(s).replace(/\*\*(.+?)\*\*/g, "$1");  // 본문 복사에서는 굵게를 쓰지 않음 (소제목만 굵게)
  const FS = (STATE && STATE.editor_fs) || { body: 16, heading: 19, small: 13 };
  // 스마트에디터 ONE이 자기 글에서 쓰는 모양(se-fs-fs크기 클래스)을 같이 넣어야 붙여 넣을 때 글자 크기가 살아남음
  // 글꼴은 네이버 웹폰트 이름(se-nanummaruburi)을 그대로 적어야 함: 네이버 글을 복사하면 이 이름이 들어가고, 에디터는 이 이름을 보고 마루부리로 되돌림
  // (예전처럼 'NanumMaruBuri'로 적거나 비워 두면 표 안 글자가 기본 글꼴로 바뀜)
  const P = (html, size = FS.body, extra = "") => `<p class="se-text-paragraph se-text-paragraph-align-" style="margin:0;line-height:1.9"><span class="se-fs-fs${size} se-ff-nanummaruburi" style="font-size:${size}px;${/font-weight/.test(extra) ? "" : "font-weight:normal;"}${extra}">${html}</span></p>`;
  const lines = body.replace(/\r/g, "").replace(/([^\n]*\S[^\n]*)\n(\*\*Q[.．])/g, "$1\n\n$2").replace(/(^|\n)((?:[✔▪✅❌•①-⑩]|[-*] |\d{1,2}\. )[^\n]*)\n(?=(?:[✔▪✅❌•①-⑩]|[-*] |\d{1,2}\. ))/g, "$1$2\n\n").replace(/(^|\n)((?:[✔▪✅❌•①-⑩]|[-*] |\d{1,2}\. )[^\n]*)\n(?=(?:[✔▪✅❌•①-⑩]|[-*] |\d{1,2}\. ))/g, "$1$2\n\n").split("\n"); const out = []; let i = 0;
  while (i < lines.length) {
    const s = lines[i].trim();
    if (s.startsWith("|")) {
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) { const c = lines[i].trim().replace(/^\||\|$/g, "").split("|").map(x => x.trim()); if (!c.every(x => /^:?-{2,}:?$/.test(x) || !x)) rows.push(c); i++; }
      // 표 글자는 13 (내 블로그 표와 같게) · 스마트에디터 표 모양(se-table/se-cell + se-fs-fs13)으로
      // 열 너비: 표마다 칸 내용 길이를 보고 자동으로 (첫 칸=항목 이름은 줄바꿈 없이 한 줄에 들어가게)
      const ncol = Math.max(...rows.map(r => r.length));
      const tlen = c => [...String(c || "").replace(/\*\*/g, "")].reduce((n, ch) => n + (/[\u3131-\uD79D《》（）]/.test(ch) ? 1 : 0.55), 0);
      const need = [...Array(ncol)].map((_, ci) => Math.max(...rows.map(r => tlen(r[ci]))));
      // 짧은 칸(항목 이름·순위·저자 등)은 한 줄에 들어가는 너비를 먼저 주고, 긴 설명 칸이 남은 너비를 나눠 가짐
      const CAP = (740 - 24 * ncol) / 13;  // 네이버 본문 폭에서 13 크기 글자가 들어가는 칸 수(대략)
      const shortC = need.map(n => n <= 16), base = need.map((n, ci) => shortC[ci] ? n + 1 : 0);
      const used = base.reduce((a, b) => a + b, 0), longs = need.map((n, ci) => shortC[ci] ? 0 : n);
      const longSum = longs.reduce((a, b) => a + b, 0);
      let chars = longSum ? base.map((b, ci) => shortC[ci] ? b : Math.max(8, (CAP - used) * longs[ci] / longSum)) : base.map(b => b + (CAP - used) / ncol);
      if (chars.some(x => x <= 0) || !isFinite(chars[0])) chars = need.map(n => Math.max(n, 3));
      const px = chars.map(c => c * 13 + 24), tot = px.reduce((a, b) => a + b, 0);
      const pcts = px.map(p => p / tot * 100);
      const cell = (c, head, ci) => `<td class="se-cell" colspan="1" rowspan="1" style="width:${pcts[ci].toFixed(2)}%;border-bottom:1px solid #ddd;padding:10px 12px;${head ? "background-color:#F2F2F2;" : ""}"><div class="se-module se-module-text">${P(inl(c), 13)}</div></td>`;  // 표 칸도 본문과 같은 P()로
      out.push(`<div class="se-component se-table se-l-default"><div class="se-component-content"><div class="se-section se-section-table se-l-default" style="width:100%"><div class="se-table-container"><table class="se-table-content" style="border-collapse:collapse;width:100%;table-layout:fixed;border-top:2px solid #333;font-size:13px"><tbody>${rows.map((r, ri) => `<tr class="se-tr">${r.map((c, ci) => cell(c, ri === 0, ci)).join("")}</tr>`).join("")}</tbody></table></div></div></div></div>`);
      continue;
    }
    if (s.startsWith(">")) {
      const q = []; while (i < lines.length && lines[i].trim().startsWith(">")) { q.push(lines[i].trim().replace(/^>\s?/, "")); i++; }
      const warn = q.some(x => x.includes("⚠"));
      out.push(`<blockquote style="margin:8px 0;padding:14px 18px;border-left:4px solid ${warn ? "#E08A00" : "#2563EB"};background:${warn ? "#FFF4E0" : "#EAF1FF"}">${q.map((x, k) => x ? P(inl(x), FS.body) : P("<br>")).join("")}</blockquote>`);
      continue;
    }
    if (!s) out.push(P("<br>"));
    else if (/^```|^~~~/.test(s)) {}
    else if (/^[-=]{3,}$/.test(s)) out.push("<hr>");
    else if (s.startsWith("## ")) {
      // 소제목: 번호는 진한 파랑 두 자리(02) + 제목은 먹색 굵게 + 아래 가는 구분선 (글자로 만들어 붙여 넣어도 남음)
      const hm = s.slice(3).trim().match(/^(\d{1,2})[.)]\s*(.*)$/);
      const head = hm ? `<span style="color:#184f84">${String(hm[1]).padStart(2, "0")}</span>&nbsp;&nbsp;${inl(hm[2])}` : inl(s.slice(3).trim());
      out.push(P(head, FS.heading, "font-weight:bold;color:#1d2433"));
      out.push(P("─".repeat(28), 13, "color:#c9d3df;letter-spacing:-1px"));
    }
    else if (s.startsWith("[📸")) out.push(P(esc(s), 13, "color:#999"));
    else if (/^\*\*Q[.．]/.test(s)) out.push(P(inl(s), FS.body, "font-weight:bold;color:#184f84"));  // 질문 줄은 목록과 같은 진한 파랑, 답은 본문 색
    else if (/^(?:[✔▪✅❌•①-⑩]|[-*] |\d{1,2}\. )/.test(s)) out.push(P(inl(s), FS.body, "color:#184f84"));  // 목록(✔·▪·①·✅·❌·-·1.)은 모두 같은 진한 파랑
    else out.push(P(inl(s)));
    i++;
  }
  // 참고한 공식 자료: 본문과 다른 칸이라 위·아래에 가는 구분선
  const RULE = () => P("─".repeat(28), 13, "color:#c9d3df;letter-spacing:-1px");
  if (refs) out.push(P("<br>"), RULE(), ...refs.split("\n").map((l, k) => P(inl(l), FS.small, k === 0 ? "font-weight:bold" : "")), RULE());
  if (tags) out.push(P("<br>"), P(esc(tags), 15));
  // 연속된 문단은 스마트에디터 글 상자(se-component se-text) 하나로 묶음
  const html = []; let buf = [];
  const flush = () => { if (buf.length) html.push(`<div class="se-component se-text se-l-default"><div class="se-component-content"><div class="se-section se-section-text se-l-default"><div class="se-module se-module-text">${buf.join("")}</div></div></div></div>`); buf = []; };
  for (const x of out) { if (x.startsWith("<p ")) buf.push(x); else { flush(); html.push(x); } }
  flush();
  return `<div class="se-main-container">${html.join("")}</div>`;
}
async function copySmart(md) {
  const html = smartHtml(md);
  const plain = bodyPart(md).replace(/\*\*(.+?)\*\*/g, "$1").replace(/^>\s?/gm, "") + (refsPart(md) ? "\n\n" + refsPart(md) : "") + "\n\n" + tagsPart(md);
  // 복사 경로를 기록: A = 클립보드 API(만든 HTML 그대로), B = 대체 경로(브라우저가 서식을 다시 적음 → 결과가 다를 수 있음)
  let path = "A", ok = true;
  try {
    await navigator.clipboard.write([new ClipboardItem({ "text/html": new Blob([html], { type: "text/html" }), "text/plain": new Blob([plain], { type: "text/plain" }) })]);
  } catch {
    path = "B";
    const box = document.createElement("div"); box.contentEditable = "true"; box.style.cssText = "position:fixed;left:-9999px;top:0;color:#000"; box.innerHTML = html; document.body.appendChild(box);
    const r = document.createRange(); r.selectNodeContents(box); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
    try { ok = document.execCommand("copy"); } catch { ok = false; } sel.removeAllRanges(); box.remove();
  }
  window.LAST_COPY = { path, html, at: new Date().toLocaleTimeString("ko-KR") };
  if (!ok) { toast("복사하지 못했어요 · 다시 눌러 주세요"); return; }
  toast(path === "A" ? "서식째 복사했어요 (경로 A) · 스마트에디터 본문에 붙여 넣으세요" : "복사했어요 (경로 B: 대체 방식이라 서식이 다르게 들어갈 수 있어요)");
}

/* ---------- 내 문체 학습 ---------- */
async function loadVoice() {
  try {
    const v = await api("/api/voice");
    if (document.activeElement !== $("#voiceProfile")) $("#voiceProfile").value = v.profile || "";
    $("#voiceState").className = "keystate" + (v.profile ? " ok" : "");
    $("#voiceState").textContent = v.job.running ? `학습 중… ${v.job.seconds}초` : v.job.error ? v.job.error : v.profile ? "적용 중" : "아직 없음";
    return v;
  } catch {}
}
if ($("#voiceLoad")) {
  $("#voiceLoad").onclick = async () => {
    const b = $("#voiceLoad"); b.disabled = true; b.textContent = "불러오는 중…";
    try {
      if ($("#blogId").value.trim() !== (STATE.learn?.blog_id || "")) STATE = await api("/api/prefs", { blog_id: $("#blogId").value.trim() });
      const r = await api("/api/myblog", {});
      const posts = (r.posts || []).slice(0, 20);
      $("#voiceList").innerHTML = posts.length ? posts.map((p, i) => `<label class="voice-item"><input type="checkbox" value="${esc(p.link)}" ${i < 5 ? "checked" : ""}><span>${esc(p.title)}</span><small>${esc(p.date || "")}</small></label>`).join("")
        : `<p class="muted" style="font-size:13px">${esc(r.error || "글을 찾지 못했어요. 블로그 ID를 확인해 주세요.")}</p>`;
    } catch (err) { toast(err.message); }
    finally { b.disabled = false; b.textContent = "내 글 불러오기"; }
  };
  $("#voiceLearn").onclick = async () => {
    const urls = [...$$("#voiceList input:checked").map(x => x.value), ...$("#voiceUrls").value.split("\n").map(s => s.trim()).filter(s => /blog\.naver\.com/.test(s))];
    if (urls.length < 2) { toast("반응이 좋았던 내 글을 2편 이상 골라 주세요"); return; }
    try {
      await api("/api/voice", { learn: true, urls });
      toast(`글 ${urls.length}편을 읽고 문체를 학습하는 중이에요 (1~3분)`);
      for (let k = 0; k < 120; k++) { await new Promise(r => setTimeout(r, 3000)); const v = await loadVoice(); if (v && !v.job.running) { toast(v.job.error || "문체 학습이 끝났어요 · 다음 초안부터 내 문체로 써요"); break; } }
    } catch (err) { toast(err.message); }
  };
  $("#voiceSave").onclick = async () => { await api("/api/voice", { profile: $("#voiceProfile").value }); await loadVoice(); toast("문체 프로필을 저장했어요"); };
  $("#voiceClear").onclick = async () => { if (!confirm("학습한 문체를 지울까요?")) return; await api("/api/voice", { profile: "" }); await loadVoice(); toast("지웠어요 · 작가 지침의 문체로 써요"); };
}
document.addEventListener("click", e => { if (e.target.closest('[data-tab="settings"]')) setTimeout(loadVoice, 100); });

/* ---------- 이미 쓴 글 고치기: 블로그 글 주소만 넣어도 읽어 옴 ---------- */
if ($("#rwSource")) $("#rwSource").addEventListener("blur", async () => {
  const v = $("#rwSource").value.trim();
  if (!/^https?:\/\/(m\.)?blog\.naver\.com\/\S+$/.test(v)) return;
  toast("블로그 글을 읽어 오는 중…");
  try { const p = await api("/api/naver/post", { url: v }); $("#rwSource").value = `${p.title}\n\n${p.text}`; toast(`‘${p.title.slice(0, 20)}’ 글을 읽어 왔어요 (${p.stats.chars.toLocaleString()}자)`); }
  catch (err) { toast(err.message); }
});


/* ---------- Antigravity 설치·로그인 버튼 ---------- */
if ($("#agyInstall")) {
  const st = t => { $("#agyState").textContent = t; };
  $("#agyInstall").onclick = async () => {
    const b = $("#agyInstall"); b.disabled = true; st("설치 중… (1~3분, 이 화면을 닫지 마세요)");
    try {
      await api("/api/agy/install", {});
      for (let i = 0; i < 300; i++) {
        await new Promise(r => setTimeout(r, 2000));
        const s = await api("/api/agy/install");
        if (!s.running) {
          if (s.ok) { st("설치 완료 ✓ 이제 ② 구글 로그인 창 열기를 누르세요"); STATE = await api("/api/state"); $("#aiCheck")?.click(); }
          else { st("설치하지 못했어요"); alert("설치하지 못했어요.\n\n" + (s.log || "") + "\n\n회사 보안 정책으로 막혔을 수 있어요. 그럴 때는 위에서 '직접 붙여넣기'를 고르세요."); }
          break;
        }
      }
    } catch (e) { st(e.message); }
    finally { b.disabled = false; }
  };
  $("#agyLogin").onclick = async () => {
    try { await api("/api/agy/login", {}); st("검은 창이 열렸어요 · 구글 로그인을 마친 뒤 그 창을 닫고 [AI 연결 확인]을 누르세요"); }
    catch (e) { st(e.message); }
  };
}


/* ---------- 오늘의 글 계획 ---------- */
let PLAN_TEXT = "";
function planShow(md) {
  PLAN_TEXT = md || "";
  $("#planOut").innerHTML = PLAN_TEXT ? draftMd(PLAN_TEXT.replace(/^#{3,}\s+/gm, "## ")) : `<p class="muted">아직 만든 계획이 없어요.</p>`;
  $("#planWrite").disabled = !PLAN_TEXT;
}
function planPick(md) {  // 계획에서 메인 키워드·주제·포맷·추천 제목 뽑기
  const g = re => ((md.match(re) || [])[1] || "").replace(/\*\*/g, "").trim();
  const kw = g(/메인 키워드\s*[:：]\s*([^\n/]+)/) || g(/주제\s*[:：]\s*([^\n]+)/);
  const fmt = g(/포맷\s*[:：]\s*\[?\s*(\d)/);
  const star = g(/^[-*]\s*★\s*([^\n]+)/m) || g(/([^\n]*★[^\n]*)/);
  return { kw: kw.replace(/[()（）]/g, "").slice(0, 40), style: { "1": "info", "2": "essay", "3": "deal" }[fmt] || "", title: star.replace("★", "").trim() };
}
async function planLoad() {
  try {
    const s = await api("/api/plan");
    if (document.activeElement !== $("#planGuide")) $("#planGuide").value = s.guide || "";
    $("#planState").textContent = s.running ? `만드는 중… ${s.seconds}초` : s.error ? s.error : s.at ? `${s.at} 만든 계획` : "";
    if (!s.running && s.text && s.text !== PLAN_TEXT) planShow(s.text);
    return s;
  } catch (e) { $("#planState").textContent = e.message; }
}
if ($("#planBtn")) {
  $("#planBtn").onclick = async () => { openDialog($("#planDialog")); await planLoad(); };
  $("#planRun").onclick = async () => {
    try { await api("/api/plan", {}); } catch (e) { $("#planState").textContent = e.message; return; }
    $("#planRun").disabled = true;
    for (let i = 0; i < 450; i++) {
      await new Promise(r => setTimeout(r, 2000));
      const s = await planLoad(); if (!s || !s.running) break;
    }
    $("#planRun").disabled = false;
  };
  $("#planCopy").onclick = async () => { const r = await api("/api/plan", { prompt: true }); copy(r.prompt); toast("요청문을 복사했어요 · Gemini에 붙여 넣고, 답변은 아래 '붙여넣기 방식' 칸에 넣으세요"); };
  $("#planPasteGo").onclick = () => { const t = $("#planPaste").value.trim(); if (t) planShow(t); };
  $("#planGuideSave").onclick = async () => { await api("/api/plan", { guide: $("#planGuide").value }); toast("계획 지침을 저장했어요"); };
  $("#planGuideReset").onclick = async () => { if (!confirm("기본 계획 지침으로 되돌릴까요?")) return; const r = await api("/api/plan", { guide: "" }); $("#planGuide").value = r.guide; toast("기본 지침으로 되돌렸어요"); };
  $("#planWrite").onclick = () => {
    const p = planPick(PLAN_TEXT);
    $("#planDialog").close();
    openPlan(null, { keyword: p.kw, style: p.style, from: "오늘의 글 계획",
      note: (p.title ? `제목: ${p.title}\n` : "") + "아래 '오늘의 글 계획'의 주제·목차·핵심 데이터(출처·기준일)를 따라 쓰세요. (미확인) 수치는 공식 출처로 다시 확인하고, 확인 못 하면 쓰지 마세요.\n\n" + PLAN_TEXT.slice(0, 6000) });
  };
}


/* ---------- 매일 아침 글 2편 ---------- */
if ($("#morningOn")) {
  $("#morningOn").onchange = async e => { STATE = await api("/api/prefs", { morning_drafts: e.target.checked }); renderAuto(); toast(e.target.checked ? `매일 ${$("#morningTime").value}에 상시 1편 + 오늘 최적 1편을 써 둘게요` : "아침 글 쓰기를 껐어요"); };
  $("#morningTime").onchange = async e => { STATE = await api("/api/prefs", { morning_time: e.target.value }); renderAuto(); toast(`매일 ${e.target.value}에 써 둘게요`); };
  $("#morningRun").onclick = async () => {
    try { await api("/api/morning/run", {}); toast("상시 1편 + 오늘 최적 1편을 고르는 중이에요 · 계획은 2~4분, 초안은 순서대로 써서 초안 탭에 넣어요"); }
    catch (e) { toast(e.message); }
    setTimeout(async () => { STATE = await api("/api/state"); renderAuto(); }, 4000);
  };
}
