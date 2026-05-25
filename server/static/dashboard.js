"use strict";

/* Sceance Ledger — dashboard for recent séances. */

const state = {
  days: 7,
  limit: 20,
  offset: 0,
  total: 0,
  openSessionId: null,
};

// ─── Formatters ──────────────────────────────────────────────────────

const nf = new Intl.NumberFormat("en-US");

function fmtInt(n) {
  if (n == null) return "—";
  return nf.format(n);
}

function fmtTokens(n) {
  if (n == null) return "—";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}

function fmtDuration(seconds) {
  if (seconds == null || isNaN(seconds)) return "—";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}m ${String(s).padStart(2, "0")}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function fmtMs(seconds) {
  if (seconds == null) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  return `${seconds.toFixed(2)}s`;
}

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}

function shortProcessor(p) {
  // "AnthropicLLMService#0" -> "Anthropic LLM"
  if (!p) return "?";
  return p
    .replace(/#\d+$/, "")
    .replace(/Service$/, "")
    .replace(/([a-z])([A-Z])/g, "$1 $2");
}

// ─── Fetchers ────────────────────────────────────────────────────────

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json();
}

// ─── Aggregate / KPIs ───────────────────────────────────────────────

async function loadAggregate() {
  const agg = document.getElementById("aggregate");
  agg.innerHTML = `<div class="agg-placeholder">Summoning…</div>`;
  try {
    const data = await getJSON(`/api/aggregate?days=${state.days}`);
    renderAggregate(data);
    renderTtfb(data.ttfb || []);
  } catch (e) {
    agg.innerHTML = `<div class="agg-placeholder">Could not load aggregate · ${e.message}</div>`;
  }
}

function renderAggregate(data) {
  const s = data.sessions;
  const live = (s.total_sessions || 0) - (s.finished_sessions || 0);
  const subSessions = live > 0 ? `${live} still open` : `${s.finished_sessions || 0} finished`;
  const kpis = [
    {
      label: "Séances",
      value: fmtInt(s.total_sessions),
      sub: subSessions,
    },
    {
      label: "Total time",
      value: fmtDuration(s.total_duration_s),
      sub: "across all sessions",
    },
    {
      label: "Prompt tokens",
      value: fmtTokens(s.prompt_tokens),
      sub: `${fmtTokens(s.cache_read_tokens)} cache-read`,
    },
    {
      label: "Completion",
      value: fmtTokens(s.completion_tokens),
      sub: "tokens generated",
    },
    {
      label: "TTS characters",
      value: fmtTokens(s.tts_chars),
      sub: "spoken aloud",
    },
  ];

  const agg = document.getElementById("aggregate");
  agg.innerHTML = kpis.map(k => `
    <div class="kpi">
      <div class="label">${k.label}</div>
      <div class="value">${k.value}</div>
      <div class="accent-rule"></div>
      <div class="sub">${k.sub}</div>
    </div>
  `).join("");
}

function renderTtfb(ttfb) {
  const el = document.getElementById("ttfb");
  if (!ttfb.length) {
    el.innerHTML = `<div class="ttfb-pill"><span class="n">no latency data yet</span></div>`;
    return;
  }
  el.innerHTML = ttfb.map(t => `
    <div class="ttfb-pill">
      <span class="who">${shortProcessor(t.processor)} ttfb</span>
      <span class="v">${fmtMs(t.avg_ttfb)}</span>
      <span class="n">over ${t.n} sample${t.n === 1 ? "" : "s"}</span>
    </div>
  `).join("");
}

// ─── Sessions list ──────────────────────────────────────────────────

async function loadSessions() {
  const list = document.getElementById("sessions");
  list.innerHTML = `<li class="loading">Loading…</li>`;
  try {
    const data = await getJSON(`/api/sessions?limit=${state.limit}&offset=${state.offset}`);
    state.total = data.total;
    renderSessions(data.sessions);
    renderPager();
  } catch (e) {
    list.innerHTML = `<li class="loading">Could not load sessions · ${e.message}</li>`;
  }
}

function renderSessions(sessions) {
  const list = document.getElementById("sessions");
  if (!sessions.length) {
    list.innerHTML = `<li class="loading">No séances yet. Pick up the phone.</li>`;
    return;
  }
  list.innerHTML = sessions.map(s => {
    const live = !s.ended_at;
    const lang = (s.lang || "—").toUpperCase();
    return `
      <li class="session ${live ? "live" : ""}" data-id="${s.id}">
        <div class="session-row">
          <div class="s-persona">
            ${escapeHtml(s.persona_name || "(unnamed)")}
            <span class="lang">${escapeHtml(lang)}</span>
          </div>
          <div class="s-date">${fmtDate(s.started_at)}</div>
          <div class="s-dur">${fmtDuration(s.duration_s)}</div>
          <div class="s-msgs">${s.msg_count} turn${s.msg_count === 1 ? "" : "s"}</div>
          <div class="s-tok">
            ${fmtTokens(s.prompt_tokens)} <span class="small">in</span>
            · ${fmtTokens(s.completion_tokens)} <span class="small">out</span>
          </div>
          <div class="s-chev">›</div>
        </div>
        <div class="detail" hidden></div>
      </li>
    `;
  }).join("");

  // Attach click handlers.
  list.querySelectorAll(".session").forEach(li => {
    li.addEventListener("click", (e) => {
      if (e.target.closest("a, button")) return;
      toggleSession(li);
    });
  });

  // If something was open before reload, re-open it.
  if (state.openSessionId) {
    const li = list.querySelector(`[data-id="${state.openSessionId}"]`);
    if (li) toggleSession(li, true);
  }
}

function renderPager() {
  const pager = document.getElementById("pager");
  const page = Math.floor(state.offset / state.limit) + 1;
  const pages = Math.max(1, Math.ceil(state.total / state.limit));
  pager.innerHTML = `
    <button id="prev" ${state.offset === 0 ? "disabled" : ""}>← Prev</button>
    <span class="pos">${page} / ${pages}</span>
    <button id="next" ${state.offset + state.limit >= state.total ? "disabled" : ""}>Next →</button>
  `;
  pager.querySelector("#prev").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    state.openSessionId = null;
    loadSessions();
  });
  pager.querySelector("#next").addEventListener("click", () => {
    state.offset += state.limit;
    state.openSessionId = null;
    loadSessions();
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// ─── Session detail (expand inline) ─────────────────────────────────

async function toggleSession(li, forceOpen = false) {
  const id = li.dataset.id;
  const wasOpen = li.classList.contains("open");
  // Close all others.
  li.parentElement.querySelectorAll(".session.open").forEach(other => {
    if (other !== li) {
      other.classList.remove("open");
      const d = other.querySelector(".detail");
      if (d) { d.hidden = true; d.innerHTML = ""; }
    }
  });
  if (wasOpen && !forceOpen) {
    li.classList.remove("open");
    const d = li.querySelector(".detail");
    d.hidden = true;
    d.innerHTML = "";
    state.openSessionId = null;
    return;
  }
  li.classList.add("open");
  state.openSessionId = id;
  const detail = li.querySelector(".detail");
  detail.hidden = false;
  detail.innerHTML = `<div class="agg-placeholder">Loading the transcript…</div>`;
  try {
    const data = await getJSON(`/api/sessions/${id}`);
    detail.innerHTML = renderDetail(data);
  } catch (e) {
    detail.innerHTML = `<div class="agg-placeholder">Could not load · ${e.message}</div>`;
  }
}

function renderDetail(s) {
  // metrics summary table
  const metricsRows = s.metrics.map(m => `
    <tr>
      <td>${shortProcessor(m.processor)}</td>
      <td>${m.kind}</td>
      <td class="num">${m.n}</td>
      <td class="num">${formatMetricValue(m.kind, m.avg)}</td>
      <td class="num">${formatMetricValue(m.kind, m.sum)}</td>
    </tr>
  `).join("") || `<tr><td colspan="5" class="empty">no metrics captured</td></tr>`;

  // transcript
  const turns = s.messages.length
    ? s.messages.map(m => `
        <div class="turn ${m.role}">
          <div class="who">${escapeHtml(m.role)}${m.language ? ` · ${escapeHtml(m.language)}` : ""}</div>
          <div class="text">${escapeHtml(m.text)}</div>
        </div>
      `).join("")
    : `<div class="empty">No transcript recorded.</div>`;

  // metadata
  const persona = s.persona || {};
  const meta = [
    ["Persona", persona.name || s.persona_name || "—"],
    ["Language", s.lang || "—"],
    ["LLM", persona.llm_model || "—"],
    ["TTS voice", persona.tts_voice_id || "—"],
    ["Started", fmtDate(s.started_at)],
    ["Ended", s.ended_at ? fmtDate(s.ended_at) : "—"],
    ["Duration", fmtDuration(s.duration_s)],
    ["Prompt tokens", fmtInt(s.prompt_tokens)],
    ["Completion", fmtInt(s.completion_tokens)],
    ["Cache read", fmtInt(s.cache_read_tokens)],
    ["Cache create", fmtInt(s.cache_creation_tokens)],
    ["TTS chars", fmtInt(s.tts_chars)],
    ["Session id", `<span style="color:var(--text-3)">${s.id}</span>`],
  ];

  return `
    <div class="detail-meta">
      <h3>Session</h3>
      <dl class="meta-grid">
        ${meta.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}
      </dl>
      ${renderResponseLatency(s.response_latency)}
      <h3>Per-step metrics</h3>
      <table class="metrics-table">
        <thead>
          <tr><th>Processor</th><th>Kind</th><th>n</th><th>avg</th><th>sum</th></tr>
        </thead>
        <tbody>${metricsRows}</tbody>
      </table>
    </div>
    <div class="detail-transcript">
      <h3>Transcript</h3>
      <div class="transcript">${turns}</div>
    </div>
  `;
}

// ─── Response latency block (stats + bar chart) ─────────────────────

function renderResponseLatency(r) {
  if (!r || !r.count) {
    return `
      <h3>Response latency</h3>
      <div class="empty" style="color:var(--text-2);padding:0.5rem 0 1.5rem">
        no completed turns yet
      </div>
    `;
  }
  const stats = [
    ["mean",   fmtMs(r.mean)],
    ["median", fmtMs(r.median)],
    ["p90",    fmtMs(r.p90)],
    ["max",    fmtMs(r.max)],
  ];
  return `
    <h3>Response latency · user → bot first word</h3>
    <div class="lat-stats">
      ${stats.map(([k, v]) => `
        <div class="lat-stat">
          <div class="lat-stat-label">${k}</div>
          <div class="lat-stat-value">${v}</div>
        </div>
      `).join("")}
    </div>
    <div class="lat-chart">
      ${renderLatencyChart(r.per_turn, r.median, r.p90)}
    </div>
  `;
}

function renderLatencyChart(perTurn, median, p90) {
  const n = perTurn.length;
  if (!n) return "";
  const w = 360, h = 140;
  const padL = 6, padR = 6, padT = 8, padB = 20;
  const innerW = w - padL - padR;
  const innerH = h - padT - padB;
  const max = Math.max(...perTurn.map(t => t.latency_s), p90 || 0, median || 0, 1);
  // round max up to a nice value for the y scale
  const yMax = Math.ceil(max * 1.1 * 10) / 10;

  const barW = Math.max(2, (innerW / n) - 2);
  const gap  = (innerW / n) - barW;

  const bars = perTurn.map((t, i) => {
    const x = padL + i * (innerW / n) + gap / 2;
    const barH = Math.max(1, (t.latency_s / yMax) * innerH);
    const y = padT + (innerH - barH);
    const color = t.latency_s > (p90 ?? Infinity)
      ? "var(--vermillion)"
      : "var(--accent)";
    return `<rect x="${x.toFixed(2)}" y="${y.toFixed(2)}"
                  width="${barW.toFixed(2)}" height="${barH.toFixed(2)}"
                  fill="${color}">
              <title>turn ${t.turn}: ${fmtMs(t.latency_s)}</title>
            </rect>`;
  }).join("");

  const refLines = [];
  if (median != null) {
    const y = padT + innerH - (median / yMax) * innerH;
    refLines.push(`
      <line x1="${padL}" x2="${padL + innerW}" y1="${y}" y2="${y}"
            stroke="var(--text-3)" stroke-dasharray="3 3" stroke-width="1"/>
      <text x="${padL + innerW - 2}" y="${y - 3}" text-anchor="end"
            font-family="JetBrains Mono, monospace" font-size="9"
            fill="var(--text-3)">median ${fmtMs(median)}</text>
    `);
  }
  if (p90 != null && p90 !== median) {
    const y = padT + innerH - (p90 / yMax) * innerH;
    refLines.push(`
      <line x1="${padL}" x2="${padL + innerW}" y1="${y}" y2="${y}"
            stroke="var(--vermillion)" stroke-dasharray="3 3" stroke-width="1"/>
      <text x="${padL + innerW - 2}" y="${y - 3}" text-anchor="end"
            font-family="JetBrains Mono, monospace" font-size="9"
            fill="var(--vermillion)">p90 ${fmtMs(p90)}</text>
    `);
  }

  // x-axis: first and last turn labels
  const xAxis = `
    <text x="${padL}" y="${h - 4}" font-family="JetBrains Mono, monospace"
          font-size="9" fill="var(--text-3)">turn 1</text>
    <text x="${padL + innerW}" y="${h - 4}" text-anchor="end"
          font-family="JetBrains Mono, monospace" font-size="9"
          fill="var(--text-3)">turn ${n}</text>
  `;
  // y-axis: max label
  const yLabel = `
    <text x="${padL}" y="${padT + 8}" font-family="JetBrains Mono, monospace"
          font-size="9" fill="var(--text-3)">${fmtMs(yMax)}</text>
  `;

  return `
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"
         xmlns="http://www.w3.org/2000/svg" class="lat-svg" role="img"
         aria-label="response latency per turn">
      ${bars}
      ${refLines.join("")}
      ${xAxis}
      ${yLabel}
    </svg>
  `;
}

function formatMetricValue(kind, v) {
  if (v == null) return "—";
  if (kind === "ttfb" || kind === "processing") return fmtMs(v);
  if (kind === "tts_usage") return fmtInt(Math.round(v));
  return v.toFixed(2);
}

// ─── Period selector ────────────────────────────────────────────────

function bindPeriod() {
  const nav = document.getElementById("period");
  nav.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      nav.querySelectorAll("button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      state.days = parseInt(btn.dataset.days, 10);
      loadAggregate();
    });
  });
}

// ─── Boot ───────────────────────────────────────────────────────────

bindPeriod();
loadAggregate();
loadSessions();
