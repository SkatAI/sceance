/* Sceance — single séance detail page (/sessions/{id}). */

import { bootAdmin, makeGetJSON } from "/auth.js";
import { renderDetail, escapeHtml } from "/format.js";

// Pull the session id from the /sessions/{id} path.
function sessionIdFromPath() {
  const m = window.location.pathname.match(/\/sessions\/([^/?#]+)/);
  return m ? decodeURIComponent(m[1]) : null;
}

async function boot() {
  const auth = await bootAdmin();
  if (!auth) return;
  const getJSON = makeGetJSON(auth.getToken);

  const id = sessionIdFromPath();
  const detail = document.getElementById("detail");
  if (!id) {
    detail.innerHTML = `<div class="agg-placeholder">No session id in the URL.</div>`;
    return;
  }

  try {
    const data = await getJSON(`/api/sessions/${encodeURIComponent(id)}`);
    detail.innerHTML = renderDetail(data);
    const name = (data.persona && data.persona.name) || data.persona_name;
    if (name) {
      document.getElementById("page-title").textContent = name;
      document.title = `Sceance · ${name}`;
    }
    document.getElementById("page-subtitle").textContent =
      `Session ${id}`;
  } catch (e) {
    detail.innerHTML = `<div class="agg-placeholder">Could not load · ${escapeHtml(e.message)}</div>`;
  }
}

boot();
