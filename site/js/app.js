// The Improbable Almanac — front end. Plain ES modules, no build step.
import { initScorigami } from "./scorigami.js?v=4";

const TIER = { legendary: 4, epic: 3, rare: 2, notable: 1 };
const TIER_LABEL = { legendary: "Legendary", epic: "Epic", rare: "Rare", notable: "Notable" };
const CAT_LABEL = { "never-before": "Never before", oddity: "Oddity", milestone: "Milestone", wild: "Wild game" };
const LEAGUE_LABEL = { mlb: "MLB", nfl: "NFL", nba: "NBA", cfb: "College FB", other: "Other" };
const PAGE = 30;

const state = { events: [], favs: new Set(), league: "all", cat: "all", tier: 2, mine: false, q: "", shown: PAGE };
const $ = (sel) => document.querySelector(sel);

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { return null; }
}

async function getJSON(path, fallback) {
  try {
    const res = await fetch(`${path}?t=${Math.floor(Date.now() / 60000)}`);
    if (!res.ok) throw new Error(res.status);
    return await res.json();
  } catch { return fallback; }
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function ago(iso) {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso)) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `${hrs} hr ago`;
  return `${Math.round(hrs / 24)} days ago`;
}

function niceDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
}

const isMine = (e) => (e.teams || []).some((t) => state.favs.has(`${e.league}:${t}`));

// ---------- theme ----------
function initTheme() {
  const saved = store("theme");
  if (saved) document.documentElement.dataset.theme = saved;
  $("#theme-toggle").addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    store("theme", document.documentElement.dataset.theme);
    window.dispatchEvent(new Event("themechange"));
  });
}

// ---------- birthday splash ----------
function showSplash() {
  const splash = $("#splash");
  splash.hidden = false;
  const confetti = splash.querySelector(".splash-confetti");
  confetti.innerHTML = "";
  const colors = ["#c98a12", "#b23a2a", "#2a6bb2", "#7a3fb0", "#2f7d4a"];
  for (let i = 0; i < 60; i++) {
    const p = document.createElement("i");
    p.style.left = `${Math.random() * 100}%`;
    p.style.background = colors[i % colors.length];
    p.style.animationDuration = `${2.5 + Math.random() * 3}s`;
    p.style.animationDelay = `${Math.random() * 1.5}s`;
    confetti.appendChild(p);
  }
  $("#splash-close").focus();
}
function initSplash() {
  const close = () => { $("#splash").hidden = true; store("splashSeen", "1"); };
  $("#splash-close").addEventListener("click", close);
  $("#splash").addEventListener("click", (e) => { if (e.target.id === "splash") close(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
  $("#replay-splash").addEventListener("click", (e) => { e.preventDefault(); showSplash(); });
  if (!store("splashSeen") || new URLSearchParams(location.search).has("birthday")) showSplash();
}

// ---------- header bits ----------
function applyNames(cfg) {
  const name = cfg.name || "Dad";
  document.querySelectorAll("[data-name]").forEach((el) => (el.textContent = name));
  document.querySelectorAll("[data-name-possessive]").forEach((el) => (el.textContent = name.endsWith("s") ? `${name}'` : `${name}'s`));
  if (cfg.site_title) {
    document.querySelectorAll("[data-title]").forEach((el) => (el.textContent = cfg.site_title));
    document.title = cfg.site_title;
  }
}

function renderStatus(status) {
  const el = $("#status");
  const last = status?.last_poll;
  if (!last) { el.textContent = "Waiting for first update"; el.className = "status stale"; return; }
  const mins = (Date.now() - new Date(last)) / 60000;
  const broken = Object.entries(status.sources || {}).filter(([, s]) => !s.ok).map(([k]) => LEAGUE_LABEL[k] || k);
  el.innerHTML = `<span class="hide-sm">Updated </span>${ago(last)}`;
  el.className = "status" + (mins > 90 ? " down" : mins > 40 || broken.length ? " stale" : "");
  el.title = broken.length ? `Trouble reaching: ${broken.join(", ")}` : "All feeds healthy";
}

function renderLive(live) {
  const box = $("#live");
  const alerts = live?.alerts || [];
  if (!alerts.length || Date.now() - new Date(live.updated) > 45 * 60000) { box.hidden = true; return; }
  // Most dramatic first.
  const order = { "no-hitter": 0, "scorigami-watch": 1, "favorite-live": 2 };
  alerts.sort((a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9));
  box.innerHTML = alerts.map((a) => `
    <a class="live-item ${esc(a.kind)}" href="${esc(a.link)}" target="_blank" rel="noopener">
      <span class="live-dot"></span>
      ${(a.logos || []).slice(0, 2).map((l) => l ? `<img src="${esc(l)}" alt="">` : "").join("")}
      <div><strong>${esc(a.title)}</strong><span>${esc(a.detail)}</span></div>
    </a>`).join("");
  box.hidden = false;
}

// ---------- teams ----------
const oddities = (t) => state.events.filter((e) => e.source !== "news" && e.league === t.league && (e.teams || []).includes(t.abbr)).length;

function renderTeams(cfg) {
  const grid = $("#teams");
  const teams = cfg.teams || [];
  if (!teams.length) { grid.innerHTML = `<p class="team-empty">No teams set up yet. Add them in config/teams.yaml.</p>`; return; }
  grid.innerHTML = teams.map((t) => {
    const color = t.color ? `#${t.color.replace("#", "")}` : "";
    const results = (t.recent || []).slice(0, 6).reverse().map((g) => `
      <a class="res ${g.result} ${g.events?.length ? "odd" : ""}" href="${esc(g.link)}" target="_blank" rel="noopener"
         title="${esc(`${niceDate(g.date)}: ${g.home ? "vs" : "at"} ${g.opp_name} ${g.us}-${g.them}${g.events?.length ? ` · ${g.events.length} oddit${g.events.length === 1 ? "y" : "ies"}` : ""}`)}">
        ${g.result} ${g.us}-${g.them}</a>`).join("");
    let line = "";
    if (t.live) line = `<p class="team-line live">● Live: ${t.live.home ? "vs" : "at"} ${esc(t.live.opp)} ${t.live.us}-${t.live.them} · ${esc(t.live.detail)}</p>`;
    else if (t.next) line = `<p class="team-line">Next: ${t.next.home ? "vs" : "at"} ${esc(t.next.opp_name)} · ${new Date(t.next.date).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</p>`;
    const last = t.recent?.[0];
    if (!line && last) line = `<p class="team-line">Last: ${last.result} ${last.us}-${last.them} ${last.home ? "vs" : "at"} ${esc(last.opp_name)}, ${niceDate(last.date)}</p>`;
    return `
      <article class="team-card" style="${color ? `--team:${color}` : ""}">
        <div class="team-top">
          ${t.logo ? `<img src="${esc(t.logo)}" alt="">` : ""}
          <div><div class="team-name">${esc(t.name)}</div><div class="team-league">${LEAGUE_LABEL[t.league]}</div></div>
          <div class="team-oddities">${oddities(t)}<small>oddities</small></div>
        </div>
        ${results ? `<div class="results">${results}</div>` : `<p class="team-empty">No games yet this season.</p>`}
        ${line}
      </article>`;
  }).join("");
}

// ---------- feed ----------
function filtered() {
  const q = state.q.trim().toLowerCase();
  return state.events.filter((e) =>
    e.source !== "news" &&
    (state.league === "all" || e.league === state.league) &&
    (state.cat === "all" || e.category === state.cat) &&
    TIER[e.tier] >= state.tier &&
    (!state.mine || isMine(e)) &&
    (!q || `${e.title} ${e.detail} ${e.matchup} ${(e.players || []).join(" ")} ${(e.teams || []).join(" ")}`.toLowerCase().includes(q)));
}

function card(e) {
  const mine = isMine(e);
  const facts = (e.facts || []).filter(Boolean);
  const logos = (e.team_logos || []).filter(Boolean).slice(0, 2).map((l) => `<img src="${esc(l)}" alt="" loading="lazy">`).join("");
  return `
    <li class="ev ${e.tier} ${mine ? "is-mine" : ""}">
      <div class="ev-bar"></div>
      <div class="ev-body">
        <div class="ev-meta">
          <span class="tier">${TIER_LABEL[e.tier]}</span>
          <span class="cat ${e.category}">${CAT_LABEL[e.category] || e.category}</span>
          <span>${LEAGUE_LABEL[e.league] || esc(e.sport || e.league)}</span>
          ${mine ? `<span class="mine-tag">★ Your team</span>` : ""}
          <span class="ev-date">${niceDate(e.date)}</span>
        </div>
        <h3 class="ev-title">${esc(e.title)}</h3>
        ${e.blurb ? `<p class="ev-blurb">${esc(e.blurb)}</p><p class="ev-detail">${esc(e.detail)}</p>` : `<p class="ev-blurb">${esc(e.detail)}</p>`}
        ${facts.length ? `<p class="ev-facts"><b>How rare:</b> ${facts.map(esc).join(" ")}</p>` : ""}
        <div class="ev-foot">
          ${logos ? `<span class="logos">${logos}</span>` : ""}
          ${e.matchup ? `<span class="matchup">${esc(e.matchup)}</span>` : ""}
          ${e.link ? `<a class="ev-link" href="${esc(e.link)}" target="_blank" rel="noopener">${e.source === "news" ? "Read" : "Box score"} →</a>` : ""}
        </div>
      </div>
    </li>`;
}

function renderFeed() {
  const list = filtered();
  const shown = list.slice(0, state.shown);
  $("#feed").innerHTML = shown.length ? shown.map(card).join("")
    : `<li class="empty">Nothing matches these filters yet. Rare things are rare!</li>`;
  $("#feed-count").textContent = `${list.length.toLocaleString()} event${list.length === 1 ? "" : "s"}`;
  $("#more").hidden = list.length <= state.shown;
}

function chipGroup(el, options, key) {
  el.innerHTML = options.map(([value, label, n]) =>
    `<button class="chip" data-v="${value}" aria-pressed="${state[key] === value}">${label}${n != null ? `<span class="n">${n}</span>` : ""}</button>`).join("");
  el.onclick = (ev) => {
    const b = ev.target.closest(".chip");
    if (!b) return;
    state[key] = b.dataset.v;
    state.shown = PAGE;
    el.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", c.dataset.v === state[key]));
    renderFeed();
    saveFilters();
  };
}

function saveFilters() {
  store("filters", JSON.stringify({ league: state.league, cat: state.cat, tier: state.tier, mine: state.mine }));
}

function initFilters() {
  try { Object.assign(state, JSON.parse(store("filters") || "{}")); } catch { /* ignore */ }
  const det = state.events.filter((e) => e.source !== "news");
  const count = (fn) => det.filter(fn).length;
  chipGroup($("#league-filter"), [["all", "All leagues", det.length],
    ...["mlb", "nfl", "nba", "cfb"].map((l) => [l, LEAGUE_LABEL[l], count((e) => e.league === l)])], "league");
  chipGroup($("#cat-filter"), [["all", "Everything"],
    ...Object.entries(CAT_LABEL).map(([k, v]) => [k, v, count((e) => e.category === k)])], "cat");
  $("#tier-filter").value = String(state.tier);
  $("#tier-filter").onchange = (e) => { state.tier = Number(e.target.value); state.shown = PAGE; renderFeed(); saveFilters(); };
  $("#mine").checked = !!state.mine;
  $("#mine").onchange = (e) => { state.mine = e.target.checked; state.shown = PAGE; renderFeed(); saveFilters(); };
  $("#search").oninput = (e) => { state.q = e.target.value; state.shown = PAGE; renderFeed(); };
  $("#more").onclick = () => { state.shown += PAGE; renderFeed(); };
}

// ---------- side panels ----------
function renderSeason() {
  const det = state.events.filter((e) => e.source !== "news");
  const n = (fn) => det.filter(fn).length;
  const rarest = [...det].sort((a, b) => b.score - a.score || (b.date > a.date ? 1 : -1)).slice(0, 6);
  const mine = det.filter(isMine).sort((a, b) => b.score - a.score).slice(0, 3);
  $("#season").innerHTML = `
    <div class="stat-grid">
      <div class="stat legendary"><b>${n((e) => e.tier === "legendary")}</b><span>Legendary</span></div>
      <div class="stat"><b>${n((e) => e.category === "never-before")}</b><span>Never-before-seen</span></div>
      <div class="stat"><b>${n((e) => e.category === "oddity")}</b><span>Stat oddities</span></div>
      <div class="stat"><b>${det.length}</b><span>Total this season</span></div>
    </div>
    <div class="rarest">
      <h3>Rarest of the season</h3>
      <ol>${rarest.map((e) => `<li><a href="${esc(e.link)}" target="_blank" rel="noopener">${esc(e.title)}</a> <small>(${LEAGUE_LABEL[e.league]}, ${niceDate(e.date)})</small></li>`).join("")}</ol>
      ${mine.length ? `<h3 style="margin-top:12px">Best of your teams</h3>
      <ol>${mine.map((e) => `<li><a href="${esc(e.link)}" target="_blank" rel="noopener">${esc(e.title)}</a> <small>(${niceDate(e.date)})</small></li>`).join("")}</ol>` : ""}
    </div>`;
}

function renderElsewhere() {
  const news = state.events.filter((e) => e.source === "news").slice(0, 12);
  $("#elsewhere").innerHTML = news.length ? news.map((e) => `
    <li>
      <a href="${esc(e.link)}" target="_blank" rel="noopener">${esc(e.title)}</a>
      <p>${esc(e.blurb || e.detail)}</p>
      <small>${esc(e.sport || LEAGUE_LABEL[e.league] || "")} · ${esc(e.source_name)} · ${niceDate(e.date)}</small>
    </li>`).join("") : `<li class="team-empty">Nothing historic in the wider sports world yet today.</li>`;
}

// ---------- boot ----------
async function main() {
  initTheme();
  const [feed, teams, live, status] = await Promise.all([
    getJSON("data/events.json", { events: [] }),
    getJSON("data/teams.json", { teams: [] }),
    getJSON("data/live.json", null),
    getJSON("data/status.json", null),
  ]);
  state.events = feed.events || [];
  state.favs = new Set((teams.teams || []).map((t) => t.key));
  applyNames(teams);
  initSplash();
  renderStatus(status);
  renderLive(live);
  renderTeams(teams);
  initFilters();
  renderFeed();
  renderSeason();
  renderElsewhere();
  initScorigami();
  // Refresh live bits every 5 minutes while the page is open.
  setInterval(async () => {
    renderLive(await getJSON("data/live.json", null));
    renderStatus(await getJSON("data/status.json", null));
  }, 5 * 60000);
}

main();
