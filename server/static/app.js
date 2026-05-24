"use strict";

const talkBtn = document.getElementById("talk-btn");
const hangupBtn = document.getElementById("hangup-btn");
const statusEl = document.getElementById("status");

let callObject = null;

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = `status ${cls}`;
}

function showTalk() {
  talkBtn.classList.remove("hidden");
  hangupBtn.classList.add("hidden");
}

function showHangup() {
  talkBtn.classList.add("hidden");
  hangupBtn.classList.remove("hidden");
}

async function startSession() {
  talkBtn.disabled = true;
  setStatus("starting", "connecting");

  let body;
  try {
    const r = await fetch("/start-session", { method: "POST" });
    if (r.status === 429) {
      setStatus("the agent is busy — try again in a moment", "error");
      talkBtn.disabled = false;
      return;
    }
    if (!r.ok) {
      setStatus(`server error (${r.status})`, "error");
      talkBtn.disabled = false;
      return;
    }
    body = await r.json();
  } catch (e) {
    console.error(e);
    setStatus("cannot reach the server", "error");
    talkBtn.disabled = false;
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
    talkBtn.disabled = false;
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
  showTalk();
  talkBtn.disabled = false;
  hangupBtn.disabled = false;
}

talkBtn.addEventListener("click", startSession);
hangupBtn.addEventListener("click", endSession);
window.addEventListener("beforeunload", () => {
  if (callObject) {
    try { callObject.leave(); } catch (_) {}
  }
});
