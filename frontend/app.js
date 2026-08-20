// app.js — plain vanilla JS, no build step, no framework.
// Talks directly to the API Gateway endpoints defined in the terraform/ dir.

const API = CONFIG.API_BASE_URL;

let authToken = localStorage.getItem("vaultrag_token") || null;
let tenantId = localStorage.getItem("vaultrag_tenant") || null;
let sessionId = crypto.randomUUID(); // one chat session per browser tab load

// --- DOM refs ---
const authScreen = document.getElementById("auth-screen");
const appScreen = document.getElementById("app-screen");
const tenantLabel = document.getElementById("tenant-label");

// --- Tab switching (login/signup) ---
document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(`${btn.dataset.tab}-form`).classList.add("active");
  });
});

// --- Auth: signup ---
document.getElementById("signup-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("signup-email").value;
  const password = document.getElementById("signup-password").value;
  const org_name = document.getElementById("signup-org").value || undefined;
  const invite_token = document.getElementById("signup-invite").value || undefined;
  const errorEl = document.getElementById("signup-error");
  errorEl.textContent = "";

  try {
    const res = await fetch(`${API}/auth/signup`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password, org_name, invite_token }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Signup failed");
    onAuthSuccess(data.token, data.tenant_id);
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

// --- Auth: login ---
document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("login-email").value;
  const password = document.getElementById("login-password").value;
  const errorEl = document.getElementById("login-error");
  errorEl.textContent = "";

  try {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Login failed");
    onAuthSuccess(data.token, data.tenant_id);
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

function onAuthSuccess(token, tenant) {
  authToken = token;
  tenantId = tenant;
  localStorage.setItem("vaultrag_token", token);
  localStorage.setItem("vaultrag_tenant", tenant);
  showApp();
}

document.getElementById("logout-btn").addEventListener("click", () => {
  localStorage.removeItem("vaultrag_token");
  localStorage.removeItem("vaultrag_tenant");
  authToken = null;
  tenantId = null;
  appScreen.classList.add("hidden");
  authScreen.classList.remove("hidden");
});

function showApp() {
  authScreen.classList.add("hidden");
  appScreen.classList.remove("hidden");
  tenantLabel.textContent = tenantId;
  refreshDocuments();
}

function authHeaders() {
  return { Authorization: `Bearer ${authToken}` };
}

// --- Invite flow ---
const inviteModal = document.getElementById("invite-modal");
document.getElementById("invite-btn").addEventListener("click", () => inviteModal.classList.remove("hidden"));
document.getElementById("close-invite-modal").addEventListener("click", () => inviteModal.classList.add("hidden"));

document.getElementById("send-invite-btn").addEventListener("click", async () => {
  const email = document.getElementById("invite-email").value;
  const resultEl = document.getElementById("invite-result");
  try {
    const res = await fetch(`${API}/auth/invite`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ email }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to create invite");
    resultEl.textContent = `Invite token: ${data.invite_token} (share this with them — production would email it via SES)`;
  } catch (err) {
    resultEl.textContent = err.message;
  }
});

// --- Document upload (presigned URL flow) ---
document.getElementById("file-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const statusEl = document.getElementById("upload-status");
  statusEl.textContent = "Requesting upload URL...";

  try {
    // 1. Ask backend for a presigned S3 URL (tenant_id is derived server-side from JWT)
    const urlRes = await fetch(`${API}/documents/upload-url`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ filename: file.name }),
    });
    const urlData = await urlRes.json();
    if (!urlRes.ok) throw new Error(urlData.error || "Failed to get upload URL");

    // 2. Upload the file directly to S3 using that presigned URL
    statusEl.textContent = "Uploading...";
    const putRes = await fetch(urlData.upload_url, { method: "PUT", body: file });
    if (!putRes.ok) throw new Error("Upload to S3 failed");

    statusEl.textContent = "Uploaded — processing in background...";
    setTimeout(refreshDocuments, 2000); // give the S3->SQS->Lambda pipeline a moment
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
  }
});

// --- Document list ---
async function refreshDocuments() {
  try {
    const res = await fetch(`${API}/documents`, { headers: authHeaders() });
    const data = await res.json();
    const list = document.getElementById("document-list");
    list.innerHTML = "";
    (data.documents || []).forEach(doc => {
      const li = document.createElement("li");
      li.innerHTML = `
        <span>${doc.filename} <span class="doc-status ${doc.status}">${doc.status}</span></span>
        <button class="delete-doc-btn" data-id="${doc.document_id}">delete</button>
      `;
      list.appendChild(li);
    });
    document.querySelectorAll(".delete-doc-btn").forEach(btn => {
      btn.addEventListener("click", () => deleteDocument(btn.dataset.id));
    });
  } catch (err) {
    console.error("Failed to list documents", err);
  }
}

async function deleteDocument(documentId) {
  if (!confirm("Delete this document? This removes it and its embeddings permanently.")) return;
  try {
    await fetch(`${API}/documents/${documentId}`, { method: "DELETE", headers: authHeaders() });
    refreshDocuments();
  } catch (err) {
    alert(`Failed to delete: ${err.message}`);
  }
}

// --- Chat ---
document.getElementById("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const question = input.value.trim();
  if (!question) return;
  input.value = "";

  appendMessage("user", question);
  const loadingEl = appendMessage("assistant", "Thinking...");

  try {
    const res = await fetch(`${API}/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ question, session_id: sessionId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Query failed");

    loadingEl.querySelector(".msg-text").textContent = data.answer;
    if (data.sources && data.sources.length) {
      const sourcesEl = document.createElement("div");
      sourcesEl.className = "sources";
      sourcesEl.textContent = "Sources: " + data.sources
        .map(s => `${s.document_name} (p.${s.page_number})`)
        .join(", ");
      loadingEl.appendChild(sourcesEl);
    }
    const modelTag = document.createElement("div");
    modelTag.className = "model-tag";
    modelTag.textContent = `Answered by ${data.model_used}`;
    loadingEl.appendChild(modelTag);

  } catch (err) {
    loadingEl.querySelector(".msg-text").textContent = `Error: ${err.message}`;
  }
});

function appendMessage(role, text) {
  const container = document.getElementById("chat-messages");
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = `<div class="msg-text">${escapeHtml(text)}</div>`;
  container.appendChild(el);
  container.scrollTop = container.scrollHeight;
  return el;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// --- Auto-login if a token is already stored ---
if (authToken && tenantId) {
  showApp();
}
