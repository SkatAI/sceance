// Sceance — landing page client.
//
// Auth: passwordless email sign-in. The browser posts the email to
// /api/auth/login; the server (holding the service-role key) mints a one-time
// token_hash without sending any email, which we redeem here via verifyOtp to
// establish a real Supabase session. Session is persisted by supabase-js in
// localStorage and auto-refreshed; we attach the access_token as a Bearer
// header to /start-session so the FastAPI side can attribute the séance.

import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const agentsEl = document.getElementById("agents");
const hangupBtn = document.getElementById("hangup-btn");
const statusEl = document.getElementById("status");

const authForm = document.getElementById("auth-form");
const authLoggedIn = document.getElementById("auth-logged-in");
const authEmailInput = document.getElementById("auth-email-input");
const authInviteInput = document.getElementById("auth-invite-input");
const authSubmitBtn = document.getElementById("auth-submit");
const authStatusEl = document.getElementById("auth-status");
const authUsernameEl = document.getElementById("auth-username");
const authDashboardLink = document.getElementById("auth-dashboard-link");
const authLogoutBtn = document.getElementById("auth-logout");

let callObject = null;
let supabase = null;
let currentUser = null;

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = `status ${cls}`;
  statusEl.classList.remove("hidden");
}

function setAuthStatus(text, cls = "idle") {
  authStatusEl.textContent = text || "";
  authStatusEl.className = `status ${cls}`;
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
    ? "Discutons"
    : "Let's talk";
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
    btn.className = "primary talk-btn";
    btn.textContent = talkLabel(agent);
    btn.addEventListener("click", () => startSession(agent.id));
    card.appendChild(btn);

    const rows = [];
    if (agent.llm) rows.push(["Model", agent.llm]);
    if (agent.tts_provider) rows.push(["TTS", agent.tts_provider]);
    if (agent.lang) rows.push(["Lang", String(agent.lang).toUpperCase()]);
    rows.push(["Memory", agent.memory === false ? "off" : "on"]);
    if (rows.length) {
      const meta = document.createElement("dl");
      meta.className = "agent-meta";
      for (const [label, value] of rows) {
        const k = document.createElement("dt");
        k.textContent = label;
        const v = document.createElement("dd");
        v.textContent = value;
        meta.appendChild(k);
        meta.appendChild(v);
      }
      card.appendChild(meta);
    }

    agentsEl.appendChild(card);
  }
}

async function startSession(agentId) {
  setAgentButtonsDisabled(true);
  setStatus("starting", "connecting");

  const { data: { session } } = await supabase.auth.getSession();
  if (!session) {
    setStatus("please sign in first", "error");
    setAgentButtonsDisabled(false);
    renderAuthState(null);
    return;
  }

  let body;
  try {
    const r = await fetch("/start-session", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({ agent: agentId }),
    });
    if (r.status === 401 || r.status === 403) {
      setStatus("session expired — please sign in again", "error");
      setAgentButtonsDisabled(false);
      await supabase.auth.signOut();
      return;
    }
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

// ─── Auth ───────────────────────────────────────────────────────────

async function fetchMe(session) {
  const r = await fetch("/api/me", {
    headers: { "Authorization": `Bearer ${session.access_token}` },
  });
  if (!r.ok) return null;
  return r.json();
}

function renderAuthState(me) {
  currentUser = me;
  if (me) {
    authForm.classList.add("hidden");
    authLoggedIn.classList.remove("hidden");
    authUsernameEl.textContent = me.username;
    authDashboardLink.classList.toggle("hidden", !me.is_admin);
    agentsEl.classList.remove("hidden");
    loadAgents();
  } else {
    authForm.classList.remove("hidden");
    authLoggedIn.classList.add("hidden");
    agentsEl.classList.add("hidden");
    setAuthStatus("");
  }
}

authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = authEmailInput.value.trim();
  if (!email) return;
  const inviteCode = authInviteInput.value.trim();
  authSubmitBtn.disabled = true;
  setAuthStatus("connecting…", "connecting");
  try {
    const r = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, invite_code: inviteCode }),
    });
    if (r.status === 202) {
      setAuthStatus(
        "You're on the beta waitlist — we'll be in touch.",
        "idle",
      );
      authInviteInput.value = "";
      return;
    }
    if (r.status === 400) {
      let detail = "invalid_email";
      try { detail = (await r.json()).detail || detail; } catch (_) {}
      setAuthStatus(
        detail === "invalid_invite"
          ? "That invite code is invalid or expired."
          : detail === "invalid_email"
          ? "that email looks off"
          : detail,
        "error",
      );
      return;
    }
    if (r.status === 403) {
      setAuthStatus(
        "This is a private beta. Contact the website owner for an invite.",
        "error",
      );
      return;
    }
    if (!r.ok) {
      let detail = `error (${r.status})`;
      try { detail = (await r.json()).detail || detail; } catch (_) {}
      setAuthStatus(detail, "error");
      return;
    }
    const { token_hash, type } = await r.json();
    const { error } = await supabase.auth.verifyOtp({ token_hash, type });
    if (error) {
      setAuthStatus(error.message, "error");
      return;
    }
    // onAuthStateChange takes over from here (fetchMe + renderAuthState).
    setAuthStatus("", "idle");
  } catch (err) {
    console.error(err);
    setAuthStatus("could not reach the auth server", "error");
  } finally {
    authSubmitBtn.disabled = false;
  }
});

authLogoutBtn.addEventListener("click", async () => {
  await supabase.auth.signOut();
});

async function bootAuth() {
  let cfg;
  try {
    cfg = await (await fetch("/api/config")).json();
  } catch (e) {
    console.error(e);
    setAuthStatus("could not load config", "error");
    return;
  }
  if (!cfg.supabase_url || !cfg.supabase_anon_key) {
    setAuthStatus("auth not configured on the server", "error");
    return;
  }
  supabase = createClient(cfg.supabase_url, cfg.supabase_anon_key, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      storageKey: "sceance-auth",
    },
  });

  const { data: { session } } = await supabase.auth.getSession();
  if (session) {
    const me = await fetchMe(session);
    renderAuthState(me);
  } else {
    renderAuthState(null);
  }

  supabase.auth.onAuthStateChange(async (_event, session) => {
    if (session) {
      const me = await fetchMe(session);
      renderAuthState(me);
    } else {
      renderAuthState(null);
    }
  });
}

bootAuth();
