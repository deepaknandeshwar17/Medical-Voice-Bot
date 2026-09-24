# Swasthya Voice — Multilingual Healthcare Receptionist Voice Agent

**Project type:** Interview-prep prototype (portfolio-grade, not production-scale)
**Timeline:** Build from scratch, target completion ~7 days, remaining days for rehearsal
**Author:** Deepak
**Purpose:** Demonstrate understanding of production voice-agent architecture (STT → routing → RAG/tool-calling → TTS) for an interview at a company that sells a healthcare voice receptionist product. This system deliberately mirrors that product category's real architecture, scoped down to demo size.

---

## 1. What this system is (and is not)

**Is:** A turn-based (not real-time streaming) multilingual voice agent that acts as a clinic receptionist. It answers clinic-info questions grounded in a small knowledge base, books/checks/cancels appointments through tool-calling against a mock database, routes prescription-refill requests, detects emergencies and escalates instead of engaging, and does all of this across English, Hindi, and Kannada — including code-mixed input (e.g. "ನನಗೆ tomorrow appointment ಬೇಕು").

**Is not:** A real-time/streaming voice agent (no interrupt handling, no partial-transcript processing). Not a diagnostic or prescribing system — it must never attempt to answer a medical question about symptoms, conditions, or treatment. Not connected to any real EHR, real patient data, or real payment/insurance system. All data is synthetic.

**Core engineering point being demonstrated:** not every turn should reach the LLM. A tiered routing system decides, per turn, whether to answer from a pre-cached response, from retrieval-augmented generation, or from a tool-calling agent — and only the last two touch an LLM at all. This is the actual architecture pattern used in production voice-agent latency optimization, not a shortcut.

---

## 2. Tech stack (decided — do not substitute without a documented reason)

| Layer | Choice | Why |
|---|---|---|
| Backend framework | Python 3.11+, FastAPI | Async-friendly, fast to build, matches the ecosystem used across this whole project |
| Speech-to-Text | Sarvam AI Saaras v3, **`translate` mode** (all input → English text) | Normalizes every language to English internally; avoids needing multilingual embeddings or a translation round-trip |
| Text-to-Speech | Sarvam AI Bulbul v3 | Native support for the target output languages (English, Hindi, Kannada) |
| LLM — RAG/Q&A tier | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) via Anthropic API | Fast, cheap, adequate for grounded Q&A where a wrong answer isn't costly |
| LLM — Tool-calling/agent tier | ~~Claude Sonnet~~ **Claude Haiku 4.5** via Anthropic API | Originally spec'd as Sonnet for tool-call reliability. Tested both head-to-head on the actual tool set (6 simple, well-defined tools, no deep multi-hop reasoning) — Haiku matched Sonnet on every case including multi-tool sequencing (check-then-book) and correct cancel-by-ID. Switched for lower per-token cost since Sonnet's extra reliability wasn't needed for this tool complexity. |
| Embeddings | Local, self-hosted: `BAAI/bge-small-en-v1.5` (via `sentence-transformers`) | English-only is sufficient because STT normalizes to English before retrieval; local avoids network round-trip latency |
| Vector store | FAISS (flat/brute-force index) | Corpus is tiny (~30–50 chunks); no need for approximate search |
| Database | SQLite (via `sqlite3` or SQLAlchemy) | Mock doctors, time slots, appointments, refill requests — zero setup overhead |
| Audio cache | Local disk (`cache/audio/`) | Pre-synthesized TTS for Tier 0/Tier 1 canned responses — generated once at build time, played back instantly at runtime |
| Frontend | Plain HTML + CSS + vanilla JavaScript, no framework, no build step, served directly by FastAPI via `StaticFiles` | Zero extra tooling (no npm/Vite dev server to run alongside the backend), lowest failure surface for a solo demo, and reads as a deliberate build rather than a generic prototyping-tool look |
| Config/secrets | `.env` (git-ignored) + `.env.example` (committed, no real values) | Never hardcode API keys in source, ever |
| Logging | Structured per-turn logging (JSON lines), one row per conversation turn with per-stage latency | This is a first-class feature — the demo should be able to show *why* a turn was fast or slow |
| Version control | Git, initialized on day one | Commit early, commit often, meaningful messages |

**Explicitly out of scope:** Docker (stretch goal only, do last if time permits), real-time/streaming STT-TTS, any EHR/FHIR integration beyond a mocked stub, authentication (not needed for a local demo, but note in docs as a known production gap), CI/CD.

---

## 3. Architecture

```
                              ┌─────────────────────────┐
                              │  Browser (plain HTML/    │
                              │  CSS/JS, served by       │
                              │  FastAPI's StaticFiles — │
                              │  record button, log,     │
                              │  language selector)      │
                              └───────────┬──────────────┘
                                          │ fetch() POST /voice/turn (audio + target_language)
                                          ▼
                              ┌─────────────────────────┐
                              │   FastAPI backend        │
                              └───────────┬──────────────┘
                                          ▼
                              ┌─────────────────────────┐
                              │  1. Sarvam STT           │
                              │  mode=translate          │
                              │  (any language → English)│
                              └───────────┬──────────────┘
                                          ▼
                              ┌─────────────────────────┐
                              │  2. TIER 0: Safety check │
                              │  keyword/embedding match │
                              │  against emergency set   │
                              └───────────┬──────────────┘
                                  match ──►│ (skip everything below,
                                           │  play canned emergency/
                                           │  escalation audio)
                                          ▼ no match
                              ┌─────────────────────────┐
                              │  3. TIER 1: Canonical    │
                              │  intent cache            │
                              │  embedding similarity vs │
                              │  fixed intent set        │
                              └───────────┬──────────────┘
                                  hit ────►│ (skip LLM + RAG entirely,
                                           │  play pre-synthesized audio
                                           │  for that intent+language)
                                          ▼ miss
                              ┌─────────────────────────┐
                              │  4. Router decision:     │
                              │  RAG question, or        │
                              │  action/tool-call?       │
                              └──────┬────────────┬───────┘
                                     ▼            ▼
                    ┌───────────────────┐  ┌────────────────────┐
                    │ TIER 2: RAG        │  │ TIER 3: Agent       │
                    │ FAISS retrieve     │  │ Sonnet + tool       │
                    │ + Claude Haiku     │  │ schemas + SQLite    │
                    │ answers in         │  │ executes tool,      │
                    │ target_language    │  │ Sonnet confirms in  │
                    │                    │  │ target_language     │
                    └─────────┬──────────┘  └──────────┬──────────┘
                              └───────────┬─────────────┘
                                          ▼
                              ┌─────────────────────────┐
                              │  5. Sarvam TTS           │
                              │  synthesize reply in     │
                              │  target_language         │
                              └───────────┬──────────────┘
                                          ▼
                              ┌─────────────────────────┐
                              │  Audio + transcript +    │
                              │  reply text + latency    │
                              │  breakdown → frontend    │
                              └─────────────────────────┘
```

**Key design decision — English-normalized internal pipeline:** STT always runs in `translate` mode, so every downstream component (safety check, intent cache, RAG, agent reasoning) operates on English text regardless of what language the person spoke. Only the final TTS step needs to know the target output language. This decouples "what language did they speak" from "what language should I reply in" — which is the actual feature being demonstrated (input language ≠ output language) — while avoiding the need for multilingual embeddings or a separate translation step.

---

## 4. Tiered response system — full detail

### Tier 0: Safety / emergency detection
- Runs on every turn, before anything else, on the English-normalized transcript.
- Detects two categories: (a) medical emergencies — chest pain, difficulty breathing, severe bleeding, loss of consciousness, and similar; (b) mental health crisis indicators.
- Implementation: a small set of exemplar phrases per category, embedded once at startup; incoming transcript embedding compared via cosine similarity, plus a simple keyword backstop for the most unambiguous terms.
- On match: do not call any LLM. Play a pre-synthesized, pre-approved response instructing the person to contact emergency services or offering immediate transfer to a human, in their target language. Log the trigger category (not the transcript) for later review.
- This must be deterministic and never depend on LLM judgment — a safety-critical path should not be able to fail because a prompt was worded imperfectly.

### Tier 1: Canonical intent cache
- A fixed, small list of common intents defined in `data/canonical_intents.json`: greeting, goodbye, clinic hours, clinic address, services offered, human handoff request, thanks/acknowledgement.
- Each intent has: a few example phrases (for computing a reference embedding), and a canned reply template per supported language (English, Hindi, Kannada).
- At startup, embed all example phrases once and cache the reference vectors in memory.
- At runtime: embed the incoming transcript, compare against all canonical intent vectors, and if the best match is above a similarity threshold, treat it as a hit.
- On hit: look up the pre-synthesized audio file for that intent+language (generated at build time by `scripts/pregenerate_audio_cache.py`) and return it directly. No LLM call, no RAG call, no live TTS call.
- On miss: fall through to Tier 2/3 routing.

### Tier 2: RAG-grounded Q&A
- For clinic-specific questions that aren't canonical intents (e.g. "does Dr. Ravi see patients on Saturday", "what documents do I need for my first visit").
- Embed the transcript (local `bge-small-en-v1.5`), retrieve top-k (k=3) chunks from the FAISS index built over `data/clinic_kb/`.
- Call Claude Haiku with: a system prompt (cached — see §6), the retrieved chunks, the transcript, and an explicit instruction to answer only from the provided context, to say so if the answer isn't in the context, and to reply in `target_language`.
- No tool access at this tier — it only answers questions, it never takes actions.

### Tier 3: Tool-calling agent
- For anything requiring an action: checking availability, booking, cancelling an appointment, requesting a prescription refill, or an explicit request to speak to a human.
- Call Claude Sonnet with the tool schemas (§5), the transcript, and conversation history.
- If Sonnet invokes a tool, execute it against the SQLite mock database, feed the structured result back to Sonnet, and let it produce the final confirmation in `target_language`.
- If Sonnet's tool call fails validation (e.g., no such slot), the tool function returns a structured error the model can react to — never let a raw exception surface to the person.

---

## 5. Tools (Tier 3) — schemas to implement

Implement each as a Python function in `backend/app/core/tools.py`, plus the corresponding Claude tool-use JSON schema.

1. **`check_availability(specialty: str | None, doctor_name: str | None, date: str)`**
   → returns a list of available time slots for the given day, filtered by doctor or specialty if given.
2. **`book_appointment(doctor_name: str, date: str, time: str, patient_name: str, patient_phone: str)`**
   → validates the slot is still free, creates a row in the `appointments` table, returns a confirmation with an appointment ID.
3. **`cancel_appointment(appointment_id: str | None, patient_phone: str | None, date: str | None)`**
   → looks up by ID if given, else by phone+date; marks the appointment cancelled; returns confirmation or a clear "not found" result.
4. **`get_clinic_hours(day: str | None)`**
   → returns opening hours (this may overlap with Tier 1 — that's fine, Tier 1 exists specifically to avoid this tool being called for the common case).
5. **`request_prescription_refill(patient_name: str, medicine_name: str, doctor_name: str | None)`**
   → logs a refill request row (status: "pending review") — does **not** approve or fulfill it. The bot must never confirm a refill is approved.
6. **`transfer_to_human()`**
   → takes no parameters; returns a flag the backend uses to end the automated turn and signal the frontend to show a "connecting you to the front desk" state.

**Safety boundary, enforced in the system prompt for both Tier 2 and Tier 3:** the assistant must never answer a question about symptoms, diagnosis, treatment, or medication dosing. It must identify itself as a clinic assistant, not a medical professional, if asked. It must never claim a prescription refill is approved. These are prompt-level instructions in addition to the deterministic Tier 0 safety check — the two are not redundant, they cover different failure modes (Tier 0 catches acute emergencies before any LLM runs at all; the prompt instructions bound what the LLM is allowed to say once it is running).

---

## 6. LLM prompting details

- **System prompt is static across turns** (except for a small injected `target_language` and `retrieved_context` block) — structure it so the static portion comes first and dynamic content comes last, so Anthropic prompt caching can cache the stable prefix (system prompt + tool schemas) and reduce repeated-token latency/cost on every call.
- Tier 2 system prompt: clinic assistant persona, safety boundary (above), instruction to answer strictly from retrieved context, instruction to reply fluently in `target_language` regardless of what language the retrieved context or the question was in.
- Tier 3 system prompt: same persona and safety boundary, plus tool definitions, plus an instruction to confirm details back to the caller before finalizing a booking/cancellation when ambiguous.

---

## 7. Data to create

### `backend/data/clinic_kb/` (RAG source — a fictional clinic, e.g. "Aarogya Clinic")
- `doctors.json` — 3–5 fictional doctors: name, specialty, days available, timing.
- `services.json` — services offered (general medicine, pediatrics, blood tests, etc.).
- `timings.json` — clinic opening hours, holiday schedule.
- `faq.md` — first-visit documents needed, parking, payment methods accepted.
- `appointment_policy.md` — cancellation window, late-arrival policy.
- `prescription_policy.md` — how refill requests are handled, turnaround time.
- `emergency_policy.md` — what the clinic tells callers to do in an emergency (used to inform Tier 0's canned response wording, not retrieved live).

Keep every file short — a few short paragraphs or a small JSON array each. Total corpus should be roughly 20–40 chunks after splitting.

### `backend/data/canonical_intents.json`
Structure: array of `{ intent_id, example_phrases: [...], replies: { en: "...", hi: "...", kn: "..." } }` for: greeting, goodbye, clinic_hours, clinic_address, services_offered, human_handoff_request, thanks.

### Mock database (`backend/data/clinic.db`, generated by `scripts/seed_db.py`)
Tables: `doctors` (id, name, specialty, available_days), `slots` (id, doctor_id, date, time, is_booked), `appointments` (id, doctor_id, date, time, patient_name, patient_phone, status), `refill_requests` (id, patient_name, medicine_name, doctor_name, status, created_at).

All data synthetic — no real names, no real phone numbers, no real medical information.

---

## 8. File structure (build exactly this — production-style organization)

```
swasthya-voice/
├── README.md
├── .env.example
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md          # mirrors §3 of this spec, kept in sync with actual build
│   └── DEMO_SCRIPT.md           # the exact rehearsed demo conversation, written once stable
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app, mounts frontend/ via StaticFiles, serves index.html at "/", CORS, startup hooks
│   │   ├── config.py            # pydantic-settings, loads from .env
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── routes_voice.py  # POST /voice/turn
│   │   │   └── routes_admin.py  # GET /health, POST /admin/reset
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── pipeline.py      # orchestrates one full turn end-to-end
│   │   │   ├── safety.py        # Tier 0
│   │   │   ├── intent_cache.py  # Tier 1
│   │   │   ├── rag.py           # Tier 2
│   │   │   ├── agent.py         # Tier 3
│   │   │   └── tools.py         # tool implementations + schemas
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── sarvam_client.py     # transcribe(), synthesize()
│   │   │   ├── claude_client.py     # call_haiku(), call_sonnet()
│   │   │   ├── embeddings.py        # embed() via local model
│   │   │   ├── vector_store.py      # FAISS build/load/query
│   │   │   └── db.py                # SQLite access layer
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── schemas.py       # Pydantic request/response models
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── logging_config.py    # structured per-turn latency logging
│   │       └── audio_utils.py
│   ├── data/
│   │   ├── clinic_kb/           # see §7
│   │   ├── canonical_intents.json
│   │   └── clinic.db            # generated, git-ignored
│   ├── cache/
│   │   ├── audio/               # generated, git-ignored (keep a .gitkeep)
│   │   └── faiss_index/         # generated, git-ignored
│   ├── scripts/
│   │   ├── build_index.py       # embeds clinic_kb → FAISS index
│   │   ├── pregenerate_audio_cache.py  # synthesizes Tier 0/1 canned audio per language
│   │   └── seed_db.py           # populates clinic.db with sample data
│   └── tests/
│       ├── test_safety.py
│       ├── test_intent_cache.py
│       ├── test_tools.py
│       └── test_pipeline.py
└── frontend/
    ├── index.html            # page structure: record button, language dropdown, conversation log, latency badge
    ├── style.css             # all styling
    └── script.js             # all behavior: mic recording, fetch() calls to the backend, playback, DOM updates
```

No build step and no separate dev server — these three files are served directly by the FastAPI backend (see `main.py` above) at `http://localhost:8000/`. There is exactly one process to run.

`.gitignore` must exclude: `.env`, `backend/data/clinic.db`, `backend/cache/`, `__pycache__/`, `node_modules/`, `*.pyc`.

---

## 9. Environment variables (`.env.example`)

```
SARVAM_API_KEY=
ANTHROPIC_API_KEY=
EMBEDDING_MODEL_NAME=BAAI/bge-small-en-v1.5
FAISS_INDEX_PATH=backend/cache/faiss_index
AUDIO_CACHE_DIR=backend/cache/audio
DB_PATH=backend/data/clinic.db
ALLOWED_ORIGINS=http://localhost:8000
# Note: frontend is served by this same FastAPI app (same origin), so CORS
# middleware is mostly a formality here — keep it restricted regardless,
# rather than wildcard, as a matter of habit.
LOG_LEVEL=INFO
```

---

## 10. API contract

**`POST /voice/turn`**
Request: multipart form — `audio` (wav/webm blob), `target_language` (`en` | `hi` | `kn`), `conversation_id` (string, for multi-turn context).
Response (JSON):
```json
{
  "transcript": "string — English-normalized transcript",
  "reply_text": "string — in target_language",
  "audio_url": "string — path/URL to synthesized reply audio",
  "tier": "0 | 1 | 2 | 3",
  "latency_ms": {
    "stt": 0,
    "routing": 0,
    "llm": 0,
    "tts": 0,
    "total": 0
  }
}
```

**`GET /health`** → `{"status": "ok"}`
**`POST /admin/reset`** → clears in-memory conversation state for a given `conversation_id`.

---

## 11. Build order (execute in this sequence)

1. **Scaffold** — create the full file structure above (empty/stub files), init git, write `.gitignore` and `.env.example`, set up Python venv and `requirements.txt`.
2. **Verify external services** — smallest possible scripts to confirm: Sarvam STT transcribes a test WAV, Sarvam TTS synthesizes a test phrase, Claude Haiku and Sonnet both respond to a trivial prompt, local embedding model embeds a test sentence. Do not proceed until all four work.
3. **Data layer** — write `clinic_kb/` content, `canonical_intents.json`, `scripts/seed_db.py` (run it to create `clinic.db`), `scripts/build_index.py` (run it to create the FAISS index).
4. **Services layer** — implement `sarvam_client.py`, `claude_client.py`, `embeddings.py`, `vector_store.py`, `db.py` as thin, testable wrappers.
5. **Core pipeline, tier by tier** — implement and manually test Tier 0 (safety) in isolation, then Tier 1 (intent cache) in isolation, then Tier 2 (RAG), then Tier 3 (tools + agent). Run `scripts/pregenerate_audio_cache.py` once Tier 1's intents and languages are finalized.
6. **Wire the pipeline orchestrator** (`core/pipeline.py`) — full turn logic, tier routing, latency logging.
7. **API layer** — `routes_voice.py`, `routes_admin.py`, `main.py`.
8. **Frontend** — plain HTML/CSS/JS: record button (browser `MediaRecorder` API) → `fetch()` POST to `/voice/turn` → play returned audio + show transcript/reply/latency badge. Mount it in `main.py` via `StaticFiles` so it's served from the same FastAPI process — no separate dev server.
9. **End-to-end testing per tier** — confirm each tier is actually reachable and behaves correctly, confirm code-mixed input works, confirm mid-conversation language switching works, confirm a full booking flow completes and appears in `clinic.db`.
10. **Docs and demo prep** — fill in `docs/ARCHITECTURE.md` and `docs/DEMO_SCRIPT.md`, record a backup screen capture of a clean run.

---

## 12. Definition of done

- All four tiers are implemented and individually demonstrable.
- A full conversation can: greet in Kannada → get clinic hours (Tier 1, instant) → ask a doctor-availability question not in the canned set (Tier 2, RAG) → book an appointment (Tier 3, tool-calling) → switch to English mid-conversation and get a reply in English → say something indicating an emergency and get the Tier 0 safety response instead of any LLM engagement.
- The latency breakdown is visible per turn (in logs and in the frontend), showing which tier handled each turn.
- No secrets are committed to git. `.env` is git-ignored; `.env.example` has no real values.
- The bot never answers a symptom/diagnosis/treatment question and never confirms a prescription refill as approved.
- README explains what the project is, how to run it, and states plainly that it uses synthetic data and is a prototype, not a production system.
