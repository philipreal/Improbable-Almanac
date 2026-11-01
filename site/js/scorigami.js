// Scorigami grid: winning score on the vertical axis, losing score across.
const LEAGUES = [
  { id: "nfl", label: "NFL", maxW: 73, maxL: 55 },
  { id: "cfb", label: "College FB", maxW: 90, maxL: 70 },
  { id: "mlb", label: "MLB", maxW: 30, maxL: 22 },
];
const cache = {};
let current = "nfl";

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function hexToRgb(h) {
  h = h.replace("#", "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  const n = parseInt(h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

async function load(id) {
  if (!cache[id]) {
    try {
      const res = await fetch(`data/scorigami/${id}.json?t=${Math.floor(Date.now() / 600000)}`);
      cache[id] = res.ok ? await res.json() : null;
    } catch { cache[id] = null; }
  }
  return cache[id];
}

function geometry(cfg, wrap) {
  const cols = cfg.maxL + 2; // + label column
  const rows = cfg.maxW + 2;
  const avail = Math.max(280, wrap.clientWidth - 4);
  const cell = Math.max(5, Math.min(14, Math.floor(avail / cols)));
  return { cols, rows, cell, width: cols * cell, height: rows * cell };
}

function draw(cfg, table) {
  const canvas = document.getElementById("sg-canvas");
  const wrap = canvas.parentElement;
  const g = geometry(cfg, wrap);
  const dpr = window.devicePixelRatio || 1;
  canvas.width = g.width * dpr;
  canvas.height = g.height * dpr;
  canvas.style.width = `${g.width}px`;
  canvas.style.height = `${g.height}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, g.width, g.height);

  const scores = table?.scores || {};
  const newKeys = new Set((table?.recent || []).map((r) => r.score));
  const maxN = Math.max(1, ...Object.values(scores).map((s) => s.n));
  const empty = hexToRgb(css("--sg-empty")), lo = hexToRgb(css("--sg-lo")), hi = hexToRgb(css("--sg-hi"));
  const gold = css("--gold"), ink3 = css("--ink-3");
  const c = g.cell;
  const gap = c >= 8 ? 1 : 0.5;

  ctx.font = `600 ${Math.max(8, Math.min(10, c))}px Inter, system-ui, sans-serif`;
  ctx.fillStyle = ink3;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const step = cfg.maxW > 40 ? 10 : 5;
  for (let l = 0; l <= cfg.maxL; l += step) ctx.fillText(String(l), (l + 1.5) * c, 0.5 * c + 1);
  ctx.textAlign = "right";
  for (let w = 0; w <= cfg.maxW; w += step) ctx.fillText(String(w), c - 2, (w + 1.5) * c);

  for (let w = 0; w <= cfg.maxW; w++) {
    for (let l = 0; l <= Math.min(w, cfg.maxL); l++) {
      const key = `${w}-${l}`;
      const s = scores[key];
      const x = (l + 1) * c, y = (w + 1) * c;
      if (newKeys.has(key)) ctx.fillStyle = gold;
      else if (s) ctx.fillStyle = `rgb(${mix(lo, hi, Math.log(s.n + 1) / Math.log(maxN + 1)).join(",")})`;
      else ctx.fillStyle = `rgb(${empty.join(",")})`;
      ctx.fillRect(x + gap, y + gap, c - gap * 2, c - gap * 2);
    }
  }
  return g;
}

function side(cfg, table) {
  const el = document.getElementById("sg-side");
  if (!table) { el.innerHTML = `<p>Scorigami data isn't available yet.</p>`; return; }
  const recent = table.recent || [];
  el.innerHTML = `
    <h3>${cfg.label} scorigami</h3>
    <div class="big">${Object.keys(table.scores).length.toLocaleString()}</div>
    <p>different final scores across ${table.games.toLocaleString()} games since ${table.since}.</p>
    <div class="big" style="color:var(--gold)">${recent.length}</div>
    <p>brand-new final score${recent.length === 1 ? "" : "s"} this season.</p>
    ${recent.length ? `<ol>${recent.slice(0, 8).map((r) => `<li><a href="${r.link}" target="_blank" rel="noopener">${r.score.replace("-", "–")}</a> · ${r.game} <small>(${r.date})</small></li>`).join("")}</ol>` : ""}
    <p style="margin-top:12px;font-size:11px">${table.source || ""}</p>`;
}

function tooltip(cfg, table, g) {
  const canvas = document.getElementById("sg-canvas");
  const tip = document.getElementById("sg-tip");
  const show = (clientX, clientY) => {
    const r = canvas.getBoundingClientRect();
    const l = Math.floor((clientX - r.left) / g.cell) - 1;
    const w = Math.floor((clientY - r.top) / g.cell) - 1;
    if (l < 0 || w < 0 || l > w || w > cfg.maxW || l > cfg.maxL) { tip.hidden = true; return; }
    const s = table?.scores?.[`${w}-${l}`];
    const isNew = (table?.recent || []).find((x) => x.score === `${w}-${l}`);
    tip.innerHTML = s
      ? `<b>${w}–${l}</b><br>${s.n.toLocaleString()} time${s.n === 1 ? "" : "s"}${isNew ? " · <span style='color:var(--gold)'>new this season!</span>" : ""}<br>First: ${s.firstGame || ""} (${s.first || "?"})${s.n > 1 ? `<br>Last: ${s.lastGame || ""} (${s.last || "?"})` : ""}`
      : `<b>${w}–${l}</b><br>Never happened. Yet.`;
    tip.hidden = false;
    const wrapR = canvas.parentElement.getBoundingClientRect();
    let x = clientX - wrapR.left + canvas.parentElement.scrollLeft + 14;
    const y = clientY - wrapR.top + 14;
    if (x + 240 > canvas.parentElement.scrollLeft + wrapR.width) x -= 260;
    tip.style.left = `${Math.max(0, x)}px`;
    tip.style.top = `${y}px`;
  };
  canvas.onmousemove = (e) => show(e.clientX, e.clientY);
  canvas.onmouseleave = () => (tip.hidden = true);
  canvas.onclick = (e) => show(e.clientX, e.clientY);
}

async function render() {
  const cfg = LEAGUES.find((l) => l.id === current);
  const table = await load(current);
  const g = draw(cfg, table);
  side(cfg, table);
  tooltip(cfg, table, g);
}

export function initScorigami() {
  const tabs = document.getElementById("sg-tabs");
  tabs.innerHTML = LEAGUES.map((l) => `<button class="chip" role="tab" data-v="${l.id}" aria-pressed="${l.id === current}">${l.label}</button>`).join("");
  tabs.onclick = (e) => {
    const b = e.target.closest(".chip");
    if (!b) return;
    current = b.dataset.v;
    tabs.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", c.dataset.v === current));
    render();
  };
  let t;
  window.addEventListener("resize", () => { clearTimeout(t); t = setTimeout(render, 150); });
  window.addEventListener("themechange", render);
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", render);
  render();
}
