// StoryGuard 화면. 상태는 화면이 들고 다닌다: original(처음 불러온 게임), base(지금 기준 게임), playGame(플레이 중인 게임)
const $ = (id) => document.getElementById(id);
const S = { original: null, base: null, playGame: null, playState: null, last: null, request: "" };

const PRESETS = [
  "두 번째 퀘스트 보상을 황금 열쇠에서 마법 지팡이로 바꿔 줘",
  "촌장의 대화를 '어서 오게, 용사여'로 바꿔 줘",
  "대장장이의 부탁을 완료하면 방패도 함께 주게 해 줘",
];
const SRC = { live: "실시간", mock: "모의 응답", replay: "저장된 결과", template: "규칙 설명" };
const ERR = {
  timeout: "응답 시간 초과", server_error: "AI 서버 오류", rate_limited: "요청이 몰려 거절됨(429)",
  json_error: "AI 답이 정해진 형식이 아님", config_error: ".env 설정 오류", no_recording: "저장된 결과 없음",
  storage_error: "저장소 연결 실패", refusal: "AI가 요청을 거절함",
};
const KIND = { area: "지역", quest: "퀘스트", item: "아이템", event: "이벤트", flag: "조건", ending: "엔딩" };

async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || data.detail || `요청 실패 (${res.status})`);
  return data;
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// ------------------------------------------------------------ 시작
// 틸론 GPU에서 만든 이미지(app/static/assets). 파일이 없으면 아무것도 바꾸지 않는다.
function loadAssets() {
  const logo = $("logo");
  logo.onload = () => { logo.hidden = false; };
  logo.src = "/static/assets/logo_256.png";
  const bg = new Image();
  bg.onload = () => {
    document.documentElement.style.setProperty("--bg-url", "url('/static/assets/background.webp')");
    document.body.classList.add("has-bg");
  };
  bg.src = "/static/assets/background.webp";
  fetch("/static/assets/credits.json").then((r) => (r.ok ? r.json() : null)).then((c) => {
    if (!c || !c.gpu || !c.model) return;
    const el = $("credits");
    el.textContent = `로고·배경 이미지: 교내 GPU(${c.gpu})에서 오픈소스 모델 ${c.model}로 생성`;
    el.hidden = false;
  }).catch(() => {});
}

async function init() {
  loadAssets();
  PRESETS.forEach((p) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "preset"; b.textContent = p;
    b.onclick = () => { $("reqText").value = p; $("reqText").focus(); };
    $("presets").appendChild(b);
  });
  const st = await api("/api/status");
  const badge = $("modeBadge");
  badge.className = "badge " + st.mode;
  badge.textContent = { live: st.provider === "anthropic" ? "실시간 Claude 연결" : "실시간 GPU 연결", mock: "모의 모드 (발표 숫자로 쓰지 않음)", replay: "저장된 결과 재생", replay_first: "저장된 결과 우선 (없으면 실시간)" }[st.mode] || st.mode;
  const store = $("storeText");
  if (store) {  // 예전 index.html이 캐시에 남아 있어도 아래 GPU 상태 표시가 멈추지 않게
    store.textContent = { supabase: "기록: Supabase", local: "기록: 이 PC", none: "기록 저장 안 됨" }[st.store] || "";
    store.classList.toggle("bad", st.store === "none");
  }
  api("/api/health").then((h) => {
    const el = $("healthText");
    if (h.ok === null) { el.textContent = st.mode === "mock" ? "AI 서버 없이 동작 중" : h.message; return; }
    el.textContent = h.ok ? `연결됨: ${st.models.join(", ")}` : h.message;
    el.classList.toggle("bad", !h.ok);
  }).catch(() => {});
  const g = await api("/api/game/sample_game");
  S.original = g.game; S.base = g.game;
  $("gameTitle").textContent = g.game.meta?.title || "게임";
  renderMap(g.graph, g.verify, false);
  renderVerdict(g.verify, "원본 게임");
  startPlay(g.game, "원본 게임으로 플레이 중");
}

// ------------------------------------------------------------ 판정 문구
// 거절 이유를 한 줄로. 엔딩에 못 가는 이유가 없고 요청 밖 변경만 있으면 무엇이 바뀌었는지 보여 준다.
function whyRejected(v) {
  const b = (v.blockers || [])[0]?.message;
  if (b) return b;
  const un = v.unintended_changes || [];
  if (un.length) return "요청하지 않은 변경: " + describeChanges(un, S.original).join(" / ");
  if ((v.schema_errors || []).length) return "게임 데이터 형식 오류";
  return "검증 실패";
}

function renderVerdict(v, label) {
  const el = $("verdict");
  if (!v) { el.className = "verdict"; el.textContent = ""; return; }
  const ok = v.reachable && !(v.unintended_changes || []).length && !(v.schema_errors || []).length;
  el.className = "verdict " + (ok ? "ok" : "bad");
  const steps = (v.path || []).length;
  const unint = v.unintended_changes || [];
  el.innerHTML = ok
    ? `${esc(label)}: 엔딩까지 갈 수 있습니다<small>검증 엔진이 ${steps}단계 만에 엔딩에 도달하는 경로를 찾았습니다.</small>`
    : (v.reachable && unint.length)
      ? `${esc(label)}: 엔딩에는 갈 수 있지만 요청하지 않은 변경이 있어 거절했습니다<small>${esc(describeChanges(unint, S.original).join(" / "))}</small>`
      : `${esc(label)}: 엔딩에 갈 수 없습니다<small>${esc(whyRejected(v))}</small>`;
}

// ------------------------------------------------------------ 스토리 지도 (SVG)
const LANES = ["area", "quest", "event", "item", "ending"];
// 위에서 아래로 = 이야기가 진행되는 순서. 열은 종류별 줄(지역, 퀘스트, 이벤트, 아이템, 엔딩)
function renderMap(graph, verify, animatePath) {
  const svg = $("map");
  const W = 168, H = 46, LANE = 196, GY = 14, PAD = 12, HEAD = 26;
  const reach = graph.nodes.filter((n) => n.depth !== null && n.depth !== undefined && n.status === "ok");
  const depths = [...new Set(reach.map((n) => n.depth))].sort((a, b) => a - b);
  const rankOf = Object.fromEntries(depths.map((d, i) => [d, i]));
  const rest = graph.nodes.filter((n) => !reach.includes(n)).sort((a, b) => a.col - b.col);
  const restCols = [...new Set(rest.map((n) => n.col))];
  const used = {}; // lane -> Set(row)
  const pos = {};
  const place = (n, row) => {
    const lane = n.kind === "flag" ? "event" : n.kind;
    used[lane] = used[lane] || new Set();
    while (used[lane].has(row)) row++;
    used[lane].add(row);
    pos[n.id] = { x: PAD + LANES.indexOf(lane) * LANE, y: PAD + HEAD + row * (H + GY), row };
  };
  reach.sort((a, b) => a.depth - b.depth).forEach((n) => place(n, rankOf[n.depth]));
  const base = depths.length;
  rest.forEach((n) => place(n, base + restCols.indexOf(n.col)));
  const maxRow = Math.max(0, ...Object.values(pos).map((p) => p.row));
  const width = PAD * 2 + (LANES.length - 1) * LANE + W, height = PAD * 2 + HEAD + (maxRow + 1) * (H + GY);
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("width", width); svg.setAttribute("height", height);
  const status = Object.fromEntries(graph.nodes.map((n) => [n.id, n.status]));
  let html = `<defs><marker id="arr" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8FA0BF"/></marker>
    <marker id="arrBad" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#E0413A"/></marker></defs>`;
  LANES.forEach((l, i) => {
    html += `<rect class="lane-bg" x="${PAD + i * LANE - 6}" y="${PAD}" width="${W + 12}" height="${height - PAD * 2}"/>
      <text class="lane-title" x="${PAD + i * LANE + W / 2}" y="${PAD + 17}" text-anchor="middle">${KIND[l]}</text>`;
  });
  graph.edges.forEach((e) => {
    const a = pos[e.from], b = pos[e.to];
    if (!a || !b) return;
    const bad = status[e.from] === "missing" && status[e.to] === "blocked";
    let d;
    if (a.x === b.x) {           // 같은 줄: 아래로 곧게, 위로 가면 옆으로 돌아감
      d = b.y > a.y ? `M${a.x + W / 2},${a.y + H} L${b.x + W / 2},${b.y}`
        : `M${a.x + W},${a.y + H / 2} C${a.x + W + 26},${a.y + H / 2} ${b.x + W + 26},${b.y + H / 2} ${b.x + W},${b.y + H / 2}`;
    } else {
      const right = b.x > a.x;
      const x1 = right ? a.x + W : a.x, x2 = right ? b.x : b.x + W;
      const y1 = a.y + H / 2, y2 = b.y + H / 2, dx = (x2 - x1) / 2;
      d = `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`;
    }
    html += `<path class="edge${bad ? " bad" : ""}" d="${d}" marker-end="url(#${bad ? "arrBad" : "arr"})"><title>${esc(e.rel)}</title></path>`;
  });
  graph.nodes.forEach((n) => {
    const p = pos[n.id];
    const label = n.label.length > 10 ? n.label.slice(0, 10) + "…" : n.label;
    const lit = verify?.reachable && n.status === "ok";
    html += `<g class="node k-${n.kind} s-${n.status}" data-depth="${n.depth ?? 99}" data-lit="${lit}">
      <title>${esc(KIND[n.kind])} ${esc(n.label)}${n.sub ? " (" + esc(n.sub) + ")" : ""}</title>
      <rect x="${p.x}" y="${p.y}" width="${W}" height="${H}" rx="${n.kind === "item" ? 0 : n.kind === "ending" ? 10 : 3}"/>
      <text class="kind" x="${p.x + 8}" y="${p.y + 15}">${n.sub ? esc(n.sub) + "에게서 받음" : ""}</text>
      <text x="${p.x + 8}" y="${p.y + (n.sub ? 35 : 29)}" font-size="15">${esc(label)}</text></g>`;
  });
  svg.innerHTML = html;
  if (animatePath && verify?.reachable) lightPath();
}

function lightPath() {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const nodes = [...document.querySelectorAll('#map .node[data-lit="true"]')]
    .sort((a, b) => Number(a.dataset.depth) - Number(b.dataset.depth));
  nodes.forEach((g, i) => setTimeout(() => g.classList.add("lit"), reduce ? 0 : 160 * i));
}

// ------------------------------------------------------------ 게임 플레이
const SCENE = {
  village: { sky: "#9fd0ff", ground: "#7cc36a", deco: "house" },
  forest: { sky: "#8cc7f0", ground: "#4f9a47", deco: "tree" },
  cave: { sky: "#3a3550", ground: "#5a5268", deco: "rock" },
  final_dungeon: { sky: "#2a2140", ground: "#4b3b6b", deco: "brick" },
};
function drawScene(areaId, npcs) {
  const c = $("scene"), x = c.getContext("2d");
  const sc = SCENE[areaId] || { sky: "#9fd0ff", ground: "#8fcf7a", deco: "tree" };
  x.fillStyle = sc.sky; x.fillRect(0, 0, 320, 168);
  x.fillStyle = sc.ground; x.fillRect(0, 112, 320, 56);
  x.fillStyle = "rgba(0,0,0,.12)"; for (let i = 0; i < 320; i += 16) x.fillRect(i, 112, 8, 4);
  const px = (gx, gy, w, h, col) => { x.fillStyle = col; x.fillRect(gx, gy, w, h); };
  for (let i = 0; i < 4; i++) {
    const bx = 24 + i * 78;
    if (sc.deco === "house") { px(bx, 74, 40, 38, "#f6e7c8"); px(bx - 4, 64, 48, 12, "#d0574f"); px(bx + 15, 92, 10, 20, "#8a5a3b"); }
    if (sc.deco === "tree") { px(bx + 14, 84, 10, 28, "#7a4f2e"); px(bx, 52, 38, 36, "#2f7a3a"); px(bx + 6, 44, 26, 12, "#3e9448"); }
    if (sc.deco === "rock") { px(bx, 82, 44, 30, "#6e6684"); px(bx + 8, 70, 26, 14, "#857d9c"); }
    if (sc.deco === "brick") { for (let r = 0; r < 3; r++) px(bx + (r % 2) * 6, 70 + r * 14, 40, 10, "#6a5590"); }
  }
  if (sc.deco === "rock" || sc.deco === "brick") { px(150, 70, 20, 30, "#f2b705"); px(154, 60, 12, 10, "#ffd84a"); }
  npcs.forEach((n, i) => {
    const nx = 200 + i * 40;
    px(nx, 88, 16, 24, "#7b68c8"); px(nx + 3, 78, 10, 10, "#f2c9a0");
    x.fillStyle = "#1B2A4A"; x.font = "11px Galmuri11, monospace"; x.fillText(n.name, nx - 4, 74);
  });
  px(60, 86, 16, 26, "#1B2A4A"); px(63, 76, 10, 10, "#f2c9a0"); px(58, 96, 20, 6, "#e0413a");
}

async function startPlay(game, label) {
  S.playGame = game; S.playState = null;
  $("playSource").textContent = label;
  $("playLog").innerHTML = "";
  renderPlay(await api("/api/play", { game }));
}
async function doAction(a) {
  try {
    const out = await api("/api/play", { game: S.playGame, state: S.playState, action: a });
    if (out.log) { const li = document.createElement("li"); li.textContent = out.log; $("playLog").appendChild(li); li.scrollIntoView({ block: "nearest" }); }
    renderPlay(out);
  } catch (e) { alert(e.message); }
}
function renderPlay(v) {
  S.playState = v.state;
  $("areaName").textContent = v.area_name;
  $("npcs").innerHTML = v.npcs.map((n) => `<p><b>${esc(n.name)}</b> “${esc(n.dialogue[0] || "...")}”</p>`).join("");
  $("items").innerHTML = v.items.length ? v.items.map((i) => `<span class="chip">${esc(i.name)}</span>`).join("") : "비어 있음";
  const box = $("actions");
  box.innerHTML = "";
  if (v.ending) {
    box.innerHTML = `<div class="ending-banner">엔딩: ${esc(v.ending_name)}</div>`;
  } else if (!v.actions.length) {
    box.innerHTML = `<p class="err">더 할 수 있는 행동이 없습니다. 이 게임은 여기서 막힙니다.</p>`;
  } else {
    v.actions.forEach((a) => {
      const b = document.createElement("button");
      b.className = "act"; b.textContent = a.text; b.onclick = () => doAction(a);
      box.appendChild(b);
    });
  }
  drawScene(v.state.area, v.npcs);
}

// ------------------------------------------------------------ 수정 요청
$("reqForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const request = $("reqText").value.trim();
  if (!request) { $("reqText").focus(); return; }
  S.request = request;
  setBusy(true, "AI가 게임을 고치고, 검증 엔진이 확인하는 중입니다…");
  try {
    const res = await api("/api/modify", { game: S.base, request, auto_retry: $("autoRetry").checked });
    showResult(res);
  } catch (e) {
    $("result").innerHTML = `<div class="res-status bad">요청을 처리하지 못했습니다</div><p class="err">${esc(e.message)}</p>`;
  } finally { setBusy(false); }
});

function setBusy(on, msg) {
  $("reqBtn").disabled = on;
  $("reqBtn").textContent = on ? "처리 중" : "수정 요청";
  if (on) $("result").innerHTML = `<p class="empty">${esc(msg)}</p>`;
}

function srcBadge(s) { return s ? `<span class="src ${esc(s)}">${esc(SRC[s] || s)}</span>` : ""; }

function showResult(res) {
  S.last = res;
  const el = $("result");
  let head;
  if (res.status === "passed") {
    const retried = res.first_pass === false;
    head = `<div class="res-status ok">${retried ? "고쳐서 통과했습니다" : "통과: 엔딩까지 갈 수 있습니다"}</div>`;
    if (retried) head += `<p>처음 수정은 엔딩을 막았고, ${res.attempts.length - 1}번 다시 고쳐서 통과했습니다. 요청한 변경은 그대로 남아 있습니다.</p>`;
  } else if (res.status === "failed") {
    const un = res.verify?.unintended_changes || [];
    head = (res.verify?.reachable && un.length)
      ? `<div class="res-status bad">엔딩에는 갈 수 있지만 요청하지 않은 변경이 있어 거절했습니다</div>
         <ul class="changes">${describeChanges(un, S.original).map((t) => `<li>${esc(t)}</li>`).join("")}</ul>`
      : `<div class="res-status bad">엔딩에 갈 수 없습니다</div>`;
  } else if (res.status === "question") {
    head = `<div class="res-status warn">확인이 필요합니다</div><p>${esc(res.question)}</p>`;
  } else {
    const a = res.attempts[0]?.llm || {};
    head = `<div class="res-status bad">AI 응답 실패: ${esc(ERR[a.error_kind] || a.error_kind || "알 수 없음")}</div>
      <p class="err">게임은 바뀌지 않았습니다. ${esc(a.error_message || "")}</p>`;
  }
  let body = "";
  const ex = res.explanation;
  if (ex && res.status !== "passed") {
    body += `<div class="explain"><p class="problem">${esc(ex.problem)} ${srcBadge(ex.source)}</p><p class="cause">${esc(ex.cause)}</p></div>`;
    if ((ex.fixes || []).length) {
      body += `<div class="fixes">` + ex.fixes.map((f, i) =>
        `<button class="fix" data-i="${i}"><b>${esc(f.title)}</b><span>${esc(f.description)}</span></button>`).join("") + `</div>`;
    }
  }
  body += `<ol class="timeline">` + res.attempts.map((a, i) => {
    const pass = a.passed, label = a.kind === "modify" ? "1차 수정" : `다시 고치기 ${i}`;
    const why = a.verify ? (pass ? "엔딩 도달 확인" : whyRejected(a.verify)) : (a.note || "");
    const meta = a.llm.ok ? `${esc(a.llm.model)} ${a.llm.latency_ms}ms` : esc(ERR[a.llm.error_kind] || a.llm.error_kind);
    return `<li class="${pass ? "pass" : "fail"}"><b>${label}</b> ${srcBadge(a.llm.source)}<br>${esc(why)}<span class="meta">${meta}${a.note && a.verify ? "<br>" + esc(a.note) : ""}</span></li>`;
  }).join("") + `</ol>`;
  if (res.verify?.path?.length && res.status === "passed") {
    body += `<details class="path" open><summary>엔딩까지의 경로 ${res.verify.path.length}단계</summary><ol>${res.verify.path.map((p) => `<li>${esc(p.text)}</li>`).join("")}</ol></details>`;
  }
  el.innerHTML = head + body;
  el.querySelectorAll(".fix").forEach((b) => (b.onclick = () => applyFix(ex.fixes[Number(b.dataset.i)])));

  renderMap(res.graph, res.verify, res.status === "passed");
  renderVerdict(res.verify, res.status === "passed" ? "수정한 게임" : "수정 시도");
  if (res.status === "passed") {
    S.base = res.final_game;
    startPlay(res.final_game, "수정한 게임으로 플레이 중 (검증 통과)");
  } else if (res.final_game) {
    startPlay(res.final_game, "수정 시도한 게임으로 플레이 중 (엔딩에 못 감)");
  }
}

async function applyFix(fix) {
  const res0 = S.last;
  setBusy(true, `'${fix.title}' 방법으로 고치고 다시 확인하는 중입니다…`);
  try {
    const res = await api("/api/apply_fix", {
      original: S.base, request: S.request, failed_game: res0.final_game, fix,
      intent_paths: res0.intent_paths || [], declared: res0.declared || [],
    });
    res.first_pass = false;
    res.attempts = [...res0.attempts, ...res.attempts];
    res.explanation = res.status === "passed" ? null : res0.explanation;
    if (res.status !== "passed") res.final_game = res0.final_game;
    showResult(res);
  } catch (e) {
    $("result").innerHTML += `<p class="err">${esc(e.message)}</p>`;
  } finally { setBusy(false); if (S.last) {/* 결과 유지 */} }
}

$("resetBtn").onclick = async () => {
  S.base = S.original;
  const r = await api("/api/verify", { game: S.original });
  renderMap(r.graph, r.verify, false);
  renderVerdict(r.verify, "원본 게임");
  $("result").innerHTML = `<p class="empty">원본 게임으로 되돌렸습니다.</p>`;
  startPlay(S.original, "원본 게임으로 플레이 중");
};
$("saveBtn").onclick = async () => {
  const r = await api("/api/save_game", { game: S.base });
  alert(r.message);
};
$("playReset").onclick = () => startPlay(S.playGame, $("playSource").textContent);

init().catch((e) => { $("result").innerHTML = `<p class="err">시작하지 못했습니다: ${esc(e.message)}</p>`; });
