/**
 * Cypher Frontend Application Logic
 * Integrates with FastAPI v1 endpoints:
 *   - /api/v1/auth/signup & /api/v1/auth/login
 *   - /api/v1/repository/upload-and-analyze & /api/v1/repository/my-repositories
 *   - /api/v1/chat/{repository_id}
 */

// State
let token = localStorage.getItem("cypher_token") || "";
let currentUser = null;
let currentRepoId = "";
let authMode = "login"; // 'login' | 'signup'

// DOM Elements
const authModal = document.getElementById("auth-modal");
const authForm = document.getElementById("auth-form");
const authEmail = document.getElementById("auth-email");
const authPassword = document.getElementById("auth-password");
const authError = document.getElementById("auth-error");
const modalTitle = document.getElementById("modal-title");
const authSubmitBtn = document.getElementById("auth-submit-btn");
const modalToggleBtn = document.getElementById("modal-toggle-btn");
const modalToggleText = document.getElementById("modal-toggle-text");
const userInfo = document.getElementById("user-info");
const userEmail = document.getElementById("user-email");
const guestActions = document.getElementById("guest-actions");
const logoutBtn = document.getElementById("logout-btn");

const repoSelect = document.getElementById("repo-select");
const refreshReposBtn = document.getElementById("refresh-repos-btn");
const dropZone = document.getElementById("drop-zone");
const zipFileInput = document.getElementById("zip-file-input");
const selectedFileName = document.getElementById("selected-file-name");
const fileLabel = document.getElementById("file-label");
const uploadBtn = document.getElementById("upload-btn");
const uploadStatus = document.getElementById("upload-status");
const uploadProgressBar = document.getElementById("upload-progress-bar");
const uploadStatusText = document.getElementById("upload-status-text");

const repoStatsCard = document.getElementById("repo-stats-card");
const statEntities = document.getElementById("stat-entities");
const statRels = document.getElementById("stat-rels");
const statNodes = document.getElementById("stat-nodes");

const messagesContainer = document.getElementById("messages-container");
const emptyState = document.getElementById("empty-state");
const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendBtn = document.getElementById("send-btn");

let selectedFile = null;

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  if (token) {
    await fetchUserProfile();
    await loadRepositories();
  } else {
    updateAuthUI();
  }

  setupEventListeners();
});

function setupEventListeners() {
  // Drop zone clicks & drag/drop
  dropZone.addEventListener("click", () => zipFileInput.click());
  zipFileInput.addEventListener("change", handleFileSelection);

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("border-brand-500", "bg-brand-500/10");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("border-brand-500", "bg-brand-500/10");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("border-brand-500", "bg-brand-500/10");
    if (e.dataTransfer.files.length > 0) {
      zipFileInput.files = e.dataTransfer.files;
      handleFileSelection();
    }
  });

  uploadBtn.addEventListener("click", uploadAndAnalyze);
  logoutBtn.addEventListener("click", handleLogout);
  refreshReposBtn.addEventListener("click", loadRepositories);

  repoSelect.addEventListener("change", (e) => {
    currentRepoId = e.target.value;
    addSystemNotice(`Switched to repository <strong>${currentRepoId}</strong>. You can now ask questions!`);
  });

  chatForm.addEventListener("submit", handleChatSubmit);

  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.dispatchEvent(new Event("submit"));
    }
  });

  authForm.addEventListener("submit", handleAuthSubmit);
}

// ---------------------------------------------------------------------------
// Auth Handlers
// ---------------------------------------------------------------------------
function openAuthModal(mode = "login") {
  authMode = mode;
  modalTitle.textContent = mode === "login" ? "Log In to Cypher" : "Create Cypher Account";
  authSubmitBtn.textContent = mode === "login" ? "Log In" : "Sign Up";
  modalToggleText.textContent = mode === "login" ? "Don't have an account?" : "Already have an account?";
  modalToggleBtn.textContent = mode === "login" ? "Sign Up" : "Log In";
  authError.classList.add("hidden");
  authModal.classList.remove("hidden");
  authEmail.focus();
}

function closeAuthModal() {
  authModal.classList.add("hidden");
  authEmail.value = "";
  authPassword.value = "";
}

function toggleAuthMode() {
  openAuthModal(authMode === "login" ? "signup" : "login");
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  authError.classList.add("hidden");
  authSubmitBtn.disabled = true;
  authSubmitBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Processing...';

  const email = authEmail.value.trim();
  const password = authPassword.value;

  try {
    if (authMode === "signup") {
      const res = await fetch("/api/v1/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Signup failed");
    }

    // Now Login to acquire JWT
    const loginRes = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    const loginData = await loginRes.json();
    if (!loginRes.ok) throw new Error(loginData.detail || "Login failed");

    token = loginData.access_token;
    localStorage.setItem("cypher_token", token);

    closeAuthModal();
    await fetchUserProfile();
    await loadRepositories();
  } catch (err) {
    authError.textContent = err.message;
    authError.classList.remove("hidden");
  } finally {
    authSubmitBtn.disabled = false;
    authSubmitBtn.textContent = authMode === "login" ? "Log In" : "Sign Up";
  }
}

async function fetchUserProfile() {
  if (!token) return;
  try {
    const res = await fetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      currentUser = await res.json();
      updateAuthUI();
    } else {
      handleLogout();
    }
  } catch {
    handleLogout();
  }
}

function handleLogout() {
  token = "";
  currentUser = null;
  localStorage.removeItem("cypher_token");
  updateAuthUI();
  repoSelect.innerHTML = '<option value="" disabled selected>Select a repository...</option>';
}

function updateAuthUI() {
  if (currentUser) {
    guestActions.classList.add("hidden");
    userInfo.classList.remove("hidden");
    userEmail.textContent = currentUser.email;
  } else {
    guestActions.classList.remove("hidden");
    userInfo.classList.add("hidden");
  }
}

// ---------------------------------------------------------------------------
// Repository Management & Upload
// ---------------------------------------------------------------------------
function handleFileSelection() {
  const file = zipFileInput.files[0];
  if (!file) return;
  selectedFile = file;
  fileLabel.textContent = file.name;
  selectedFileName.classList.remove("hidden");
}

async function uploadAndAnalyze() {
  if (!selectedFile) return;
  if (!token) {
    openAuthModal("login");
    return;
  }

  const formData = new FormData();
  formData.append("file", selectedFile);

  uploadBtn.disabled = true;
  uploadStatus.classList.remove("hidden");
  uploadProgressBar.style.width = "30%";
  uploadStatusText.textContent = "Uploading & extracting ZIP...";

  try {
    const res = await fetch("/api/v1/repository/upload-and-analyze", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });

    uploadProgressBar.style.width = "75%";
    uploadStatusText.textContent = "Analyzing AST & Knowledge Graph...";

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Analysis failed");

    uploadProgressBar.style.width = "100%";
    uploadStatusText.textContent = "Done! Repository ready.";

    currentRepoId = data.repository_id;

    // Display Stats Card
    statEntities.textContent = data.analysis.total_entities.toLocaleString();
    statRels.textContent = data.analysis.total_relationships.toLocaleString();
    statNodes.textContent = (data.ingestion ? data.ingestion.nodes_total : 0).toLocaleString();
    repoStatsCard.classList.remove("hidden");

    await loadRepositories();
    repoSelect.value = currentRepoId;

    addSystemNotice(
      `Analyzed <strong>${data.name}</strong> successfully! Identified <strong>${data.analysis.total_entities}</strong> entities and <strong>${data.analysis.total_relationships}</strong> relations.`
    );
  } catch (err) {
    alert("Upload failed: " + err.message);
    uploadStatus.classList.add("hidden");
  } finally {
    uploadBtn.disabled = false;
    selectedFile = null;
    selectedFileName.classList.add("hidden");
    zipFileInput.value = "";
    setTimeout(() => uploadStatus.classList.add("hidden"), 3000);
  }
}

async function loadRepositories() {
  if (!token) return;
  try {
    const res = await fetch("/api/v1/repository/my-repositories", {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;

    const repos = await res.json();
    repoSelect.innerHTML = "";

    if (repos.length === 0) {
      repoSelect.innerHTML = '<option value="" disabled selected>No repositories found</option>';
      return;
    }

    repos.forEach((r, idx) => {
      const opt = document.createElement("option");
      opt.value = r.repository_id;
      opt.textContent = `${r.name} (${r.status})`;
      if (idx === 0 && !currentRepoId) {
        currentRepoId = r.repository_id;
        opt.selected = true;
      } else if (r.repository_id === currentRepoId) {
        opt.selected = true;
      }
      repoSelect.appendChild(opt);
    });
  } catch (err) {
    console.error("Failed to load repositories:", err);
  }
}

// ---------------------------------------------------------------------------
// Chat Pipeline
// ---------------------------------------------------------------------------
function setSamplePrompt(btn) {
  chatInput.value = btn.textContent.replace("⚡ ", "").trim();
  chatInput.focus();
}

async function handleChatSubmit(e) {
  e.preventDefault();
  const question = chatInput.value.trim();
  if (!question) return;

  if (!token) {
    openAuthModal("login");
    return;
  }

  if (!currentRepoId) {
    alert("Please select or upload a repository first!");
    return;
  }

  chatInput.value = "";
  sendBtn.disabled = true;
  emptyState?.classList.add("hidden");

  // 1. Append User Message
  appendUserMessage(question);

  // 2. Append Assistant Typing Indicator
  const botMessageId = "msg-" + Date.now();
  appendBotTypingIndicator(botMessageId);

  try {
    const res = await fetch(`/api/v1/chat/${currentRepoId}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ question }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "RAG query failed");

    // Replace typing indicator with actual response
    renderBotResponse(botMessageId, data);
  } catch (err) {
    renderBotError(botMessageId, err.message);
  } finally {
    sendBtn.disabled = false;
    chatInput.focus();
  }
}

function appendUserMessage(text) {
  const div = document.createElement("div");
  div.className = "flex justify-end";
  div.innerHTML = `
    <div class="max-w-2xl bg-brand-600 text-white rounded-2xl rounded-tr-sm px-4 py-3 text-sm shadow-md">
      ${escapeHtml(text)}
    </div>
  `;
  messagesContainer.appendChild(div);
  scrollToBottom();
}

function appendBotTypingIndicator(id) {
  const div = document.createElement("div");
  div.id = id;
  div.className = "flex gap-3 max-w-3xl";
  div.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-surface-850 border border-slate-700 flex items-center justify-center text-indigo-400 shrink-0">
      <i class="fa-solid fa-robot text-sm"></i>
    </div>
    <div class="flex-1 bg-surface-900 border border-slate-800 rounded-2xl rounded-tl-sm p-4 text-sm text-slate-300">
      <div class="flex items-center gap-2 text-indigo-400 text-xs">
        <i class="fa-solid fa-circle-notch fa-spin"></i>
        <span>Traversing Neo4j Graph & searching ChromaDB vectors...</span>
      </div>
    </div>
  `;
  messagesContainer.appendChild(div);
  scrollToBottom();
}

function renderBotResponse(id, data) {
  const container = document.getElementById(id);
  if (!container) return;

  const parsedMarkdown = marked.parse(data.answer);
  const diag = data.retrieval_diagnostics || {};

  let sourcesHtml = "";
  if (data.sources && data.sources.length > 0) {
    sourcesHtml = `
      <div class="mt-4 pt-3 border-t border-slate-800">
        <details class="group cursor-pointer">
          <summary class="text-xs font-semibold text-indigo-400 hover:text-indigo-300 flex items-center justify-between list-none">
            <span><i class="fa-solid fa-file-code mr-1.5"></i> Evidence Sources (${data.sources.length} cited files)</span>
            <span class="group-open:rotate-180 transition text-[10px]"><i class="fa-solid fa-chevron-down"></i></span>
          </summary>
          <div class="mt-2.5 space-y-2">
            ${data.sources
              .map(
                (s) => `
              <div class="bg-surface-850 p-2.5 rounded-lg border border-slate-800 text-xs">
                <div class="flex justify-between items-center font-mono text-[11px] text-slate-300 mb-1">
                  <span class="font-bold text-indigo-300">${escapeHtml(s.file_path)}</span>
                  <span class="text-slate-500">Lines ${s.start_line}-${s.end_line} • ${s.source}</span>
                </div>
                ${s.snippet ? `<pre class="bg-surface-950 p-2 rounded text-[10px] overflow-x-auto"><code class="language-python">${escapeHtml(s.snippet)}</code></pre>` : ""}
              </div>
            `
              )
              .join("")}
          </div>
        </details>
      </div>
    `;
  }

  container.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-surface-850 border border-slate-700 flex items-center justify-center text-indigo-400 shrink-0">
      <i class="fa-solid fa-robot text-sm"></i>
    </div>
    <div class="flex-1 bg-surface-900 border border-slate-800 rounded-2xl rounded-tl-sm p-4 text-sm text-slate-200 chat-bubble">
      <div class="prose prose-invert max-w-none text-sm leading-relaxed space-y-2">
        ${parsedMarkdown}
      </div>
      
      ${sourcesHtml}

      <!-- Diagnostics badge -->
      <div class="mt-3 pt-2 border-t border-slate-800/80 flex items-center gap-3 text-[10px] text-slate-500">
        <span><i class="fa-solid fa-diagram-project text-indigo-400"></i> ${diag.graph_entities_found || 0} graph nodes</span>
        <span><i class="fa-solid fa-vector-square text-emerald-400"></i> ${diag.vector_chunks_found || 0} vector chunks</span>
        <span><i class="fa-solid fa-bolt text-amber-400"></i> ${Math.round(diag.total_latency_ms || 0)}ms</span>
      </div>
    </div>
  `;

  // Syntax highlight code blocks
  Prism.highlightAllUnder(container);
  scrollToBottom();
}

function renderBotError(id, errorMsg) {
  const container = document.getElementById(id);
  if (!container) return;

  container.innerHTML = `
    <div class="w-8 h-8 rounded-lg bg-rose-950/60 border border-rose-800 flex items-center justify-center text-rose-400 shrink-0">
      <i class="fa-solid fa-triangle-exclamation text-sm"></i>
    </div>
    <div class="flex-1 bg-surface-900 border border-rose-900/50 rounded-2xl rounded-tl-sm p-4 text-xs text-rose-300">
      <strong class="block mb-1 font-semibold text-rose-200">Error generating answer:</strong>
      ${escapeHtml(errorMsg)}
    </div>
  `;
  scrollToBottom();
}

function addSystemNotice(html) {
  const div = document.createElement("div");
  div.className = "flex justify-center my-2";
  div.innerHTML = `
    <div class="bg-surface-850 border border-slate-800 rounded-full px-3 py-1 text-slate-400 text-xs">
      ${html}
    </div>
  `;
  messagesContainer.appendChild(div);
  scrollToBottom();
}

function scrollToBottom() {
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
