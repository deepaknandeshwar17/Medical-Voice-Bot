// ---------- DOM refs ----------
const conversationLog = document.getElementById("conversationLog");
const languageSelect = document.getElementById("languageSelect");
const textInput = document.getElementById("textInput");
const sendTextBtn = document.getElementById("sendTextBtn");
const micBtn = document.getElementById("micBtn");
const micLabel = document.getElementById("micLabel");
const micStatus = document.getElementById("micStatus");
const newSessionBtn = document.getElementById("newSessionBtn");
const conversationIdDisplay = document.getElementById("conversationIdDisplay");
const turnCountEl = document.getElementById("turnCount");
const sessionDurationEl = document.getElementById("sessionDuration");
const detailLanguage = document.getElementById("detailLanguage");
const detailTier = document.getElementById("detailTier");
const detailLatency = document.getElementById("detailLatency");
const detailTransfer = document.getElementById("detailTransfer");

// ---------- Session state ----------
let turnCount = 0;
let sessionStartTime = Date.now();
let durationTimer = null;

// ---------- Hands-free voice (client-side VAD) state ----------
const SPEECH_RMS_THRESHOLD = 0.02;
const SILENCE_HOLD_MS = 900;
const MIN_SPEECH_MS = 300;

let sessionActive = false;   // hands-free mode on/off (toggled by mic button)
let audioCtx = null;
let analyser = null;
let micStream = null;
let vadRafId = null;
let currentRecorder = null;
let recordedChunks = [];
let speaking = false;        // currently mid-utterance (recording)
let speechStartedAt = null;
let silenceStartedAt = null;
let botOrProcessingBusy = false; // true while waiting on backend or playing bot audio — VAD paused

function getConversationId() {
  let id = sessionStorage.getItem("conversation_id");
  if (!id) {
    id = crypto.randomUUID();
    sessionStorage.setItem("conversation_id", id);
  }
  return id;
}

function updateSessionPanel() {
  conversationIdDisplay.textContent = getConversationId();
  turnCountEl.textContent = turnCount;
  const minutes = Math.max(0, Math.round((Date.now() - sessionStartTime) / 60000));
  sessionDurationEl.textContent = `${minutes} min`;
}

if (!durationTimer) {
  durationTimer = setInterval(updateSessionPanel, 30000);
}

// ---------- Rendering ----------
function addUserMessage(text) {
  const div = document.createElement("div");
  div.className = "msg user";
  div.textContent = text;
  conversationLog.appendChild(div);
  conversationLog.scrollTop = conversationLog.scrollHeight;
}

function addErrorMessage(text) {
  const div = document.createElement("div");
  div.className = "msg bot";
  div.innerHTML = `<span class="error-msg">Error: ${text}</span>`;
  conversationLog.appendChild(div);
  conversationLog.scrollTop = conversationLog.scrollHeight;
}

function addBotMessage(data) {
  const { reply_text, tier, transfer_to_human, latency_ms, audio_url } = data;
  const div = document.createElement("div");
  div.className = `msg bot tier-${tier}`;

  const badges = [`<span class="tier-badge tier-${tier}">Tier ${tier}</span>`];
  if (latency_ms) badges.push(`<span class="latency-text">${latency_ms.total}ms</span>`);
  if (transfer_to_human) badges.push(`<span class="transfer-badge">Connecting to front desk</span>`);
  if (audio_url) badges.push(`<button class="play-btn" data-audio="${audio_url}">&#9654; Replay</button>`);

  div.innerHTML = `<div>${reply_text}</div><div class="msg-meta">${badges.join("")}</div>`;
  conversationLog.appendChild(div);
  conversationLog.scrollTop = conversationLog.scrollHeight;

  const playBtn = div.querySelector(".play-btn");
  if (playBtn) {
    playBtn.addEventListener("click", () => new Audio(playBtn.dataset.audio).play().catch(() => {}));
  }

  turnCount += 1;
  updateSessionPanel();
  updateTurnDetails(data);
}

function updateTurnDetails(data) {
  const langNames = { en: "English", hi: "Hindi", kn: "Kannada" };
  detailLanguage.textContent = langNames[languageSelect.value] || languageSelect.value;
  detailTier.textContent = `Tier ${data.tier}`;
  detailTier.className = `tier-pill`;
  detailLatency.textContent = data.latency_ms ? `${data.latency_ms.total} ms` : "—";
  detailTransfer.textContent = data.transfer_to_human ? "Yes" : "No";
}

// ---------- Playing bot audio (pauses VAD while it plays, to avoid the mic picking up the bot's own voice) ----------
function playBotAudioAndWait(url) {
  return new Promise((resolve) => {
    if (!url) return resolve();
    const audio = new Audio(url);
    audio.addEventListener("ended", resolve);
    audio.addEventListener("error", resolve);
    audio.play().catch(resolve);
  });
}

// ---------- Audio queue player (Tier 2 streaming plays multiple sentence-chunks in order) ----------
let audioQueue = [];
let audioQueuePlaying = false;
let audioQueueEmptyResolvers = [];

function queueAudio(url) {
  audioQueue.push(url);
  if (!audioQueuePlaying) playNextInAudioQueue();
}

function playNextInAudioQueue() {
  if (audioQueue.length === 0) {
    audioQueuePlaying = false;
    audioQueueEmptyResolvers.forEach((resolve) => resolve());
    audioQueueEmptyResolvers = [];
    return;
  }
  audioQueuePlaying = true;
  const url = audioQueue.shift();
  const audio = new Audio(url);
  audio.addEventListener("ended", playNextInAudioQueue);
  audio.addEventListener("error", playNextInAudioQueue);
  audio.play().catch(playNextInAudioQueue);
}

function waitForAudioQueueToFinish() {
  return new Promise((resolve) => {
    if (!audioQueuePlaying && audioQueue.length === 0) return resolve();
    audioQueueEmptyResolvers.push(resolve);
  });
}

// ---------- SSE-over-fetch (EventSource doesn't support POST bodies) ----------
async function streamSSE(url, formData, onEvent) {
  const resp = await fetch(url, { method: "POST", body: formData });
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    throw new Error(data.message || data.error || `Request failed (${resp.status})`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (rawEvent.startsWith("data: ")) {
        onEvent(JSON.parse(rawEvent.slice(6)));
      }
    }
  }
}

// ---------- Sending turns ----------
async function sendText(text) {
  if (!text.trim()) return;
  addUserMessage(text);
  botOrProcessingBusy = true;
  micStatus.textContent = "Processing…";

  const form = new FormData();
  form.append("text", text);
  form.append("target_language", languageSelect.value);
  form.append("conversation_id", getConversationId());

  let finalData = null;
  try {
    await streamSSE("/voice/text/stream", form, (event) => {
      if (event.type === "chunk") {
        queueAudio(event.audio_url);
      } else if (event.type === "done") {
        finalData = event;
      } else if (event.type === "error") {
        addErrorMessage(event.message);
      }
    });
    if (finalData && finalData.tier !== "noop") {
      addBotMessage(finalData);
      if (finalData.audio_url) {
        // Non-streamed tier (0/1/3) — one complete audio file, not delivered as chunks.
        await playBotAudioAndWait(finalData.audio_url);
      } else {
        // Streamed Tier 2 — audio already played as chunks arrived; just wait for the
        // queue to finish so VAD stays paused for the whole reply, not just the fetch.
        await waitForAudioQueueToFinish();
      }
    }
  } catch (err) {
    addErrorMessage(err.message);
  }

  botOrProcessingBusy = false;
  micStatus.textContent = idleStatusText();
}

async function sendAudioBlob(blob) {
  botOrProcessingBusy = true;
  micStatus.textContent = "Processing…";

  const form = new FormData();
  form.append("audio", blob, "recording.webm");
  form.append("target_language", languageSelect.value);
  form.append("conversation_id", getConversationId());

  let finalData = null;
  try {
    await streamSSE("/voice/turn/stream", form, (event) => {
      if (event.type === "chunk") {
        queueAudio(event.audio_url);
      } else if (event.type === "done") {
        finalData = event;
      } else if (event.type === "error") {
        addErrorMessage(event.message);
      }
    });
    if (finalData && finalData.tier === "noop") {
      // VAD false-trigger (noise/silence) — Sarvam returned an empty transcript.
      // Nothing was actually said, so show nothing and don't count it as a turn.
    } else if (finalData) {
      addUserMessage(finalData.transcript);
      addBotMessage(finalData);
      if (finalData.audio_url) {
        await playBotAudioAndWait(finalData.audio_url);
      } else {
        await waitForAudioQueueToFinish();
      }
    }
  } catch (err) {
    addErrorMessage(err.message);
  }

  botOrProcessingBusy = false;
  micStatus.textContent = idleStatusText();
}

// ---------- Text input + quick action chips ----------
sendTextBtn.addEventListener("click", () => {
  const text = textInput.value;
  textInput.value = "";
  sendText(text);
});

textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    const text = textInput.value;
    textInput.value = "";
    sendText(text);
  }
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => sendText(chip.dataset.text));
});

// ---------- Hands-free voice (VAD) ----------
function idleStatusText() {
  return sessionActive
    ? "Listening… (click the green mic below anytime to end the conversation)"
    : "Click the mic to start a hands-free conversation";
}

function computeRms(timeDomainData) {
  let sumSquares = 0;
  for (let i = 0; i < timeDomainData.length; i++) {
    sumSquares += timeDomainData[i] * timeDomainData[i];
  }
  return Math.sqrt(sumSquares / timeDomainData.length);
}

function startRecordingUtterance() {
  recordedChunks = [];
  currentRecorder = new MediaRecorder(micStream);
  currentRecorder.ondataavailable = (e) => recordedChunks.push(e.data);
  currentRecorder.onstop = () => {
    const blob = new Blob(recordedChunks, { type: "audio/webm" });
    sendAudioBlob(blob);
  };
  currentRecorder.start();
  speaking = true;
  speechStartedAt = performance.now();
  silenceStartedAt = null;
  micBtn.classList.add("speaking");
  micStatus.textContent = "Hearing you speak…";
}

function stopRecordingUtterance() {
  if (currentRecorder && currentRecorder.state !== "inactive") {
    currentRecorder.stop();
  }
  speaking = false;
  micBtn.classList.remove("speaking");
}

function vadLoop() {
  if (!sessionActive) return;

  if (!botOrProcessingBusy) {
    const buffer = new Float32Array(analyser.fftSize);
    analyser.getFloatTimeDomainData(buffer);
    const rms = computeRms(buffer);
    const now = performance.now();

    if (!speaking) {
      if (rms > SPEECH_RMS_THRESHOLD) {
        startRecordingUtterance();
      }
    } else {
      if (rms > SPEECH_RMS_THRESHOLD) {
        silenceStartedAt = null;
      } else {
        if (silenceStartedAt === null) silenceStartedAt = now;
        const spokeLongEnough = now - speechStartedAt >= MIN_SPEECH_MS;
        const silentLongEnough = now - silenceStartedAt >= SILENCE_HOLD_MS;
        if (spokeLongEnough && silentLongEnough) {
          stopRecordingUtterance();
        }
      }
    }
  }

  vadRafId = requestAnimationFrame(vadLoop);
}

async function startSession() {
  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (err) {
    micStatus.textContent = "Mic error: " + err.message;
    return;
  }
  audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  const source = audioCtx.createMediaStreamSource(micStream);
  analyser = audioCtx.createAnalyser();
  analyser.fftSize = 2048;
  source.connect(analyser);

  sessionActive = true;
  micBtn.classList.add("active");
  micLabel.textContent = "End";
  micLabel.classList.add("active");
  micBtn.title = "End hands-free conversation";
  micStatus.textContent = idleStatusText();
  vadLoop();
}

function stopSession() {
  sessionActive = false;
  if (vadRafId) cancelAnimationFrame(vadRafId);
  if (speaking) stopRecordingUtterance();
  if (micStream) micStream.getTracks().forEach((t) => t.stop());
  if (audioCtx) audioCtx.close();
  micBtn.classList.remove("active", "speaking");
  micLabel.textContent = "Start";
  micLabel.classList.remove("active");
  micBtn.title = "Start hands-free conversation";
  micStatus.textContent = idleStatusText();
}

micBtn.addEventListener("click", () => {
  if (sessionActive) {
    stopSession();
  } else {
    startSession();
  }
});

// ---------- New conversation ----------
newSessionBtn.addEventListener("click", async () => {
  const conversationId = getConversationId();
  try {
    await fetch("/admin/reset", {
      method: "POST",
      body: new URLSearchParams({ conversation_id: conversationId }),
    });
  } catch (err) {
    // best-effort
  }
  sessionStorage.removeItem("conversation_id");
  conversationLog.innerHTML = "";
  turnCount = 0;
  sessionStartTime = Date.now();
  updateSessionPanel();
  detailLanguage.textContent = "—";
  detailTier.textContent = "—";
  detailLatency.textContent = "—";
  detailTransfer.textContent = "—";
});

updateSessionPanel();
