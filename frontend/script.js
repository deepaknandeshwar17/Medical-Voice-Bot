let recordedBlob = null;

const recordBtn = document.getElementById("recordBtn");
const sendBtn = document.getElementById("sendBtn");
const playback = document.getElementById("playback");
const transcriptOut = document.getElementById("transcriptOut");

recordBtn.addEventListener("click", async () => {
  recordBtn.disabled = true;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    recorder.ondataavailable = (e) => chunks.push(e.data);
    recorder.onstop = () => {
      recordedBlob = new Blob(chunks, { type: "audio/webm" });
      playback.src = URL.createObjectURL(recordedBlob);
      stream.getTracks().forEach((t) => t.stop());
      recordBtn.disabled = false;
      sendBtn.disabled = false;
    };
    recorder.start();
    setTimeout(() => recorder.stop(), 3000);
  } catch (err) {
    console.error("mic error:", err);
    alert("Mic error: " + err.name + " — " + err.message);
    recordBtn.disabled = false;
  }
});

sendBtn.addEventListener("click", async () => {
  if (!recordedBlob) return;
  transcriptOut.textContent = "…";
  const form = new FormData();
  form.append("audio", recordedBlob, "recording.webm");
  const resp = await fetch("/debug/transcribe", { method: "POST", body: form });
  const data = await resp.json();
  transcriptOut.textContent = resp.ok ? data.transcript : JSON.stringify(data);
});

document.getElementById("ttsBtn").addEventListener("click", async () => {
  const text = document.getElementById("ttsText").value;
  const form = new FormData();
  form.append("text", text);
  form.append("target_language_code", "en-IN");
  const resp = await fetch("/debug/synthesize", { method: "POST", body: form });
  if (resp.ok) {
    const blob = await resp.blob();
    document.getElementById("ttsPlayback").src = URL.createObjectURL(blob);
  } else {
    alert("TTS failed: " + (await resp.text()));
  }
});

document.getElementById("haikuBtn").addEventListener("click", async () => {
  const prompt = document.getElementById("haikuPrompt").value;
  const out = document.getElementById("haikuOut");
  out.textContent = "…";
  const form = new FormData();
  form.append("prompt", prompt);
  const resp = await fetch("/debug/claude-haiku", { method: "POST", body: form });
  const data = await resp.json();
  out.textContent = resp.ok ? data.reply : JSON.stringify(data);
});

document.getElementById("sonnetBtn").addEventListener("click", async () => {
  const prompt = document.getElementById("sonnetPrompt").value;
  const out = document.getElementById("sonnetOut");
  out.textContent = "…";
  const form = new FormData();
  form.append("prompt", prompt);
  const resp = await fetch("/debug/claude-sonnet", { method: "POST", body: form });
  const data = await resp.json();
  out.textContent = resp.ok ? data.reply : JSON.stringify(data);
});
