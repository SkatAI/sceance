"use strict";

const agentsEl = document.getElementById("agents");
const hangupBtn = document.getElementById("hangup-btn");
const statusEl = document.getElementById("status");

let callObject = null;

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = `status ${cls}`;
}

function showAgents() {
  agentsEl.classList.remove("hidden");
  hangupBtn.classList.add("hidden");
}

function showHangup() {
  agentsEl.classList.add("hidden");
  hangupBtn.classList.remove("hidden");
}

function talkLabel(agent) {
  return agent.lang === "fr"
    ? `Parlez avec ${agent.name}`
    : `Talk to ${agent.name}`;
}

function setAgentButtonsDisabled(disabled) {
  agentsEl.querySelectorAll("button").forEach((b) => { b.disabled = disabled; });
}

async function loadAgents() {
  try {
    const r = await fetch("/agents");
    if (!r.ok) throw new Error(`status ${r.status}`);
    const { agents } = await r.json();
    renderAgents(agents);
  } catch (e) {
    console.error(e);
    agentsEl.textContent = "could not load agents";
  }
}

function renderAgents(agents) {
  agentsEl.innerHTML = "";
  if (!agents.length) {
    agentsEl.textContent = "no agents available";
    return;
  }
  for (const agent of agents) {
    const card = document.createElement("div");
    card.className = "agent-card";

    const name = document.createElement("h2");
    name.className = "agent-name";
    name.textContent = agent.name;
    card.appendChild(name);

    if (agent.description) {
      const desc = document.createElement("p");
      desc.className = "agent-desc";
      desc.textContent = agent.description;
      card.appendChild(desc);
    }

    const btn = document.createElement("button");
    btn.className = "primary";
    btn.textContent = talkLabel(agent);
    btn.addEventListener("click", () => startSession(agent.id));
    card.appendChild(btn);

    agentsEl.appendChild(card);
  }
}

async function startSession(agentId) {
  setAgentButtonsDisabled(true);
  setStatus("starting", "connecting");

  let body;
  try {
    const r = await fetch("/start-session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent: agentId }),
    });
    if (r.status === 429) {
      setStatus("the agent is busy — try again in a moment", "error");
      setAgentButtonsDisabled(false);
      return;
    }
    if (!r.ok) {
      setStatus(`server error (${r.status})`, "error");
      setAgentButtonsDisabled(false);
      return;
    }
    body = await r.json();
  } catch (e) {
    console.error(e);
    setStatus("cannot reach the server", "error");
    setAgentButtonsDisabled(false);
    return;
  }

  const { room_url, token } = body;

  callObject = window.DailyIframe.createCallObject({
    audioSource: true,
    videoSource: false,
    subscribeToTracksAutomatically: true,
  });

  callObject.on("joined-meeting", () => {
    setStatus("connected", "connected");
    showHangup();
  });

  callObject.on("participant-joined", (ev) => {
    console.log("participant joined", ev.participant?.user_name);
  });

  // In createCallObject mode Daily does NOT auto-attach remote audio
  // to a media element — we have to do it ourselves or nothing plays.
  callObject.on("track-started", (ev) => {
    if (!ev.track || ev.track.kind !== "audio") return;
    if (ev.participant?.local) return;
    const id = `remote-audio-${ev.participant.session_id}`;
    let el = document.getElementById(id);
    if (!el) {
      el = document.createElement("audio");
      el.id = id;
      el.autoplay = true;
      el.playsInline = true;
      document.body.appendChild(el);
    }
    el.srcObject = new MediaStream([ev.track]);
    el.play().catch((err) => console.warn("audio play() rejected:", err));
  });

  callObject.on("track-stopped", (ev) => {
    if (!ev.track || ev.track.kind !== "audio") return;
    if (!ev.participant || ev.participant.local) return;
    const el = document.getElementById(`remote-audio-${ev.participant.session_id}`);
    if (el) {
      el.srcObject = null;
      el.remove();
    }
  });

  callObject.on("left-meeting", () => {
    setStatus("ended", "idle");
    cleanup();
  });

  callObject.on("error", (ev) => {
    console.error("daily error", ev);
    setStatus(`error: ${ev?.errorMsg || "unknown"}`, "error");
    cleanup();
  });

  setStatus("connecting", "connecting");
  try {
    await callObject.join({ url: room_url, token });
  } catch (e) {
    console.error(e);
    setStatus("connection failed", "error");
    cleanup();
  }
}

async function endSession() {
  if (!callObject) return;
  hangupBtn.disabled = true;
  try {
    await callObject.leave();
  } catch (e) {
    console.error(e);
  }
}

function cleanup() {
  if (callObject) {
    try { callObject.destroy(); } catch (_) {}
    callObject = null;
  }
  showAgents();
  setAgentButtonsDisabled(false);
  hangupBtn.disabled = false;
}

hangupBtn.addEventListener("click", endSession);
window.addEventListener("beforeunload", () => {
  if (callObject) {
    try { callObject.leave(); } catch (_) {}
  }
});

loadAgents();
