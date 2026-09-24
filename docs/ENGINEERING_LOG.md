# Engineering Log — problems found and how they were solved

A running record of every real problem hit while building Swasthya Voice, in the order they happened, with root cause and fix. Kept for two reasons: it's the actual debugging history of the project, and it's good interview material — "tell me about a bug you found and fixed" answers, with real specifics instead of a generic story.

Format per entry: **What happened → Root cause → How it was found → Fix → Why it matters.**

---

## 1. Real API keys pasted into `.env.example` instead of `.env`

**What happened:** After building the initial scaffold, real Sarvam and Anthropic keys ended up in `.env.example` — the file meant to be committed to git with blank placeholder values. `.env` (the gitignored file meant to hold real secrets) didn't exist yet.

**Root cause:** Manual copy-paste error while setting up environment variables for the first time.

**How it was found:** Caught on review before any git commit happened — noticed the diff showed real key values in a file that should never contain them.

**Fix:** Moved real values into `.env` (gitignored), reset `.env.example` back to blank keys.

**Why it matters:** Basic secret hygiene — the fix is trivial, but the habit of checking *which* file secrets land in before committing anything is the actual lesson.

---

## 2. `.ps1` script "opening" instead of running in the terminal

**What happened:** Running `.\venv\Scripts\Activate.ps1` didn't activate the virtual environment — the file just tried to open.

**Root cause:** The integrated terminal was running `cmd.exe`, not PowerShell. cmd doesn't execute `.ps1` scripts, it just tries to open the file by its file association.

**How it was found:** Noticed the "cmd" label on the terminal panel and the specific error text.

**Fix:** Used the cmd-compatible `venv\Scripts\activate.bat` instead of the PowerShell script.

**Why it matters:** A reminder that "wrong shell for the command" produces confusing errors that look unrelated to the real cause — always check which shell you're actually in before debugging the command itself.

---

## 3. Sarvam TTS model `bulbul:v2` rejected — deprecated

**What happened:** First real test of Sarvam TTS failed with a generic `400 Bad Request`, no useful detail visible.

**Root cause:** `bulbul:v2` had been deprecated in favor of `bulbul:v3` — a model name I'd written from memory/training data, not verified against current docs.

**How it was found:** The verify script initially only logged `resp.raise_for_status()`'s exception, which hides the response body. Added explicit body-printing on `httpx.HTTPStatusError`, re-ran, and the real error appeared: `"Model 'bulbul:v2' has been deprecated. Please use 'bulbul:v3' instead."`

**Fix:** Switched to `bulbul:v3`. Same pattern caught the STT model name too (`saaras:v2.5` → `saaras:v3`), fixed proactively before it broke the same way.

**Why it matters:** Never trust a swallowed exception — the actual API error was the fix, and it would've stayed invisible without surfacing the response body explicitly. Also: don't guess external API model/version names from training data on projects like this — verify against current docs or let the first real call tell you.

---

## 4. `No module named app` when starting the server

**What happened:** Running `uvicorn backend.app.main:app` from the repo root failed with `ModuleNotFoundError: No module named 'app'`.

**Root cause:** `main.py`'s own internal imports (`from app.config import ...`) assume the working directory is `backend/` (so `app` resolves as a top-level package). Starting uvicorn with the dotted path `backend.app.main:app` from the repo root put `backend` on the import path, not `app` directly — a mismatch between how the module was launched and how it imported itself.

**How it was found:** Read the traceback carefully, recognized it as a Python import-resolution issue tied to working directory, not a missing dependency.

**Fix:** Standardized on running `uvicorn app.main:app` from *inside* `backend/`, matching the internal import style.

**Why it matters:** Import paths in Python are resolved relative to `sys.path`, which depends on both *how* you invoke something and *where* you invoke it from — the two have to agree.

---

## 5. `.env` silently not found by the server (but found by standalone scripts)

**What happened:** Verify scripts run from the repo root worked fine. The FastAPI server, launched from `backend/`, failed every Sarvam/Claude call with `invalid_api_key_error` — even though the exact same key worked seconds earlier via direct `curl`.

**Root cause:** `pydantic-settings`'s `env_file=".env"` is resolved relative to the process's current working directory. The server ran from `backend/`, but `.env` lives at the repo root — so `Settings()` silently loaded every field as its empty-string default. The key wasn't wrong; it was blank.

**How it was found:** Isolated by testing whether *other* routes on the same running server also failed (they did — Haiku, TTS, everything), which ruled out "STT-specific bug" and pointed at something process-wide, i.e. config loading.

**Fix:** Made the `.env` path absolute in `config.py` (`REPO_ROOT / ".env"`) so it resolves correctly regardless of which directory the server is launched from.

**Why it matters:** "Invalid API key" errors aren't always about the key — silently-empty config from a bad relative path produces the exact same symptom. Worth checking config resolution before assuming credentials are wrong.

---

## 6. Tier 0 safety threshold: naive similarity cutoff produced false positives

**What happened:** First attempt at the emergency-detection embedding threshold (0.55, later 0.78) let ordinary phrases like *"I have a mild headache"* and *"I feel a bit dizzy sometimes"* score dangerously close to real emergencies (0.79–0.80 vs. 0.90+ for genuine cases).

**Root cause:** `bge-small` sentence embeddings have a known anisotropy quirk — cosine similarity runs generally high for *any* semantically related pair, not just true matches. A threshold picked without real calibration data looked reasonable in isolation but broke on realistic inputs.

**How it was found:** Deliberately tested borderline mild-symptom phrases (not just obvious positives/negatives) before trusting the tier, and printed the raw scores instead of just pass/fail.

**Fix:** Recalibrated the threshold to 0.85 after seeing the actual score distribution — true positives clustered ≥0.90, worst false positive was 0.80, leaving real margin.

**Why it matters:** For a safety-critical path, "the number 0.55 seemed reasonable" isn't good enough — thresholds need real calibration data, especially adversarial/borderline test cases, not just obvious hits and misses.

---

## 7. Tier 1 intent cache: absolute threshold couldn't separate hits from misses

**What happened:** Similar issue to #6 but worse — *no* single absolute threshold worked. *"is parking available at the clinic"* (should miss, it's a FAQ/RAG question) scored 0.82 against the `clinic_address` intent, higher than some genuine `thanks` intent hits scored against their own intent (0.83 lowest).

**Root cause:** The embedding space doesn't cleanly separate "generically clinic-related" from "actually this specific canonical intent" using magnitude alone.

**How it was found:** Systematic calibration pass — printed scores for a battery of should-hit and should-miss phrases side by side, found the overlap.

**Fix:** Switched from an absolute-threshold check to a **margin** check: the top-matching intent must beat the runner-up intent by a real gap (≥0.10), on top of an absolute floor (≥0.75). Verified this separates all 19 test cases cleanly (true hits: 0.12–0.37 margin; genuine misses: ≤0.06 margin).

**Why it matters:** When one similarity-scoring approach doesn't cleanly separate real data, the fix isn't a different magic number — it's a different decision rule. Margin-based confidence (best vs. second-best) is a standard trick for exactly this failure mode.

---

## 8. Sarvam TTS rejected long replies — 500-character input limit

**What happened:** A longer, genuinely correct Haiku/Sonnet reply (~600+ characters) crashed live TTS synthesis with `"String should have at most 500 characters"`.

**Root cause:** Sarvam's TTS API caps a single input string at 500 characters; nothing in the pipeline accounted for this, so any reply over that length broke outright.

**How it was found:** Live user testing surfaced it directly in the browser as a raw error bubble; traced to the exact Sarvam validation message.

**Fix:** Added sentence-aware text chunking (pack sentences greedily under 500 chars, hard-split as a last resort) plus WAV re-concatenation using Python's stdlib `wave` module — multiple TTS calls stitched into one continuous audio file, transparent to every caller of `synthesize()`.

**Why it matters:** External API limits that don't show up in short test calls will eventually show up in real usage — worth testing with realistically long inputs, not just "hello, this is a test."

---

## 9. Tier 2/3 router lost conversation context mid-booking

**What happened:** During a real multi-turn booking flow, the turn *"at 10, my name is X, phone is Y"* (answering the bot's own question) got routed to Tier 2 (RAG) instead of continuing Tier 3 (the agent doing the booking) — the bot lost the entire in-progress booking and got confused.

**Root cause:** The Tier 2 vs. Tier 3 router was a stateless per-turn keyword check ("book", "cancel", "appointment", etc.). A natural follow-up answer to the bot's own question has no reason to contain those keywords, so it silently fell through to the stateless RAG tier, which has no tool access and no memory of the conversation.

**How it was found:** Found by reading the actual plain-text conversation log (built specifically to make this kind of thing reviewable) after a real test conversation, not by a unit test — the bug only shows up in a genuine multi-turn flow.

**Fix:** Made Tier 3 "sticky" — once a conversation has engaged the agent, it stays in Tier 3 for the rest of that conversation, rather than re-deciding the tier from keywords alone on every turn. Documented trade-off: an unrelated question later in the same conversation also goes to the agent instead of back to RAG.

**Why it matters:** A per-turn classifier with no session memory is fundamentally the wrong tool for routing decisions that depend on "are we mid-flow." This is the kind of bug that only shows up in real conversation, not synthetic single-turn tests — which is exactly why the plain-text conversation log was worth building.

---

## 10. Tier 3 model choice: Sonnet vs. Haiku, tested instead of assumed

**What happened:** The original spec called for Claude Sonnet on Tier 3 (tool-calling) for reliability. Pushed on this — is that actually necessary for *this* tool set (6 simple, well-defined tools, no deep multi-hop reasoning)?

**Root cause:** N/A — this wasn't a bug, it was an unexamined assumption carried over from the spec without being tested against the actual scope of the tools built.

**How it was found:** Direct question, then resolved empirically: ran the same test battery (availability → booking → confirmation, refill, cancel, dosage-refusal) against both models head-to-head instead of arguing from priors.

**Fix:** Switched Tier 3 to Haiku after confirming it matched Sonnet on every test case, including multi-tool sequencing. Updated `PROJECT_SPEC.md` itself with the tested rationale (the spec explicitly says "don't substitute without a documented reason" — so the reason is now documented in the spec).

**Why it matters:** "Use the strongest model for reliability" is a reasonable default, but defaults should be tested against the actual task, not assumed to always hold. Also: Sarvam TTS turned out to be ~96% of API spend vs. ~4% STT — the LLM model tier barely moved total cost either way, which reframed where the real cost lever was.

---

## 11. Confusion over which server process was actually running

**What happened:** After stopping a server in the terminal (`Ctrl+C`), it kept responding to requests. Looked like the terminal command hadn't worked.

**Root cause:** Two different `uvicorn` processes existed simultaneously — one started manually in the terminal, one started separately in the background for testing. Stopping one didn't stop the other; whichever was still up kept answering on the same port.

**How it was found:** `Get-NetTCPConnection` initially returned a stale/unkillable PID (System Idle Process). Switched to `Get-CimInstance Win32_Process -Filter "Name='python.exe'"` to see full command lines, which revealed two separate `uvicorn app.main:app --port 8000` processes.

**Fix:** Killed both explicitly by PID once identified correctly.

**Why it matters:** "It's still running" isn't always the command failing — check for *multiple* processes bound to the same port before assuming a stop command didn't work.

---

## 12. Mic recording failing silently in the browser

**What happened:** Clicking the record button did nothing — no error, no recording, no feedback.

**Root cause:** No error handling around `getUserMedia`/`MediaRecorder` — if the browser denied mic permission or threw for any reason, the failure was swallowed with no user-visible signal.

**How it was found:** Asked the user to open DevTools console; in parallel, added a `try/catch` around the recording code that surfaces the actual error via `alert()`.

**Fix:** Wrapped mic access in `try/catch`, shows the real error name/message, and re-enables the button on failure instead of leaving it stuck.

**Why it matters:** Silent failure in a browser API is one of the worst debugging experiences — always assume a permission-gated API (mic, camera, location) can fail, and make that failure visible immediately.

---

## 13. On-screen reply text was in the wrong language for reading

**What happened:** With the language selector set to Kannada, the bot correctly *spoke* Kannada — but the on-screen transcript also showed Kannada text, making the conversation log unreadable for anyone demoing or reviewing in English (an interview panel, for instance).

**Root cause:** The same reply string was used both for TTS input and for on-screen display — there was only ever one version of the text, in the target language.

**Fix:** Changed the Tier 2/3 system prompts to make Claude output **two** versions in one call — `EN: <english>` / `SPOKEN: <target language>` — parsed apart, with English always shown on screen and the target-language version sent to TTS. Tier 0/1 already had per-language text stored, just needed to always display the English key regardless of target language.

**Why it matters:** "What's spoken" and "what's displayed" are different product requirements that happened to share one field by accident — worth spotting when a single value is being asked to serve two different purposes. Verified by inspecting the raw parsed output directly (not just trusting the UI), confirming genuine Kannada was actually reaching TTS.

---

## 14. Hands-free mic burning API calls on background noise

**What happened:** In a hands-free (continuous listening) test session, 4 turns in one conversation had an empty transcript (`YOU: ` with nothing) but still got a full LLM + TTS reply — the bot answering confused nonsense to silence.

**Root cause:** The client-side voice-activity detection (simple RMS amplitude threshold) occasionally triggered on background noise, not real speech. Sarvam STT correctly transcribed that audio as an empty string — but the backend pipeline didn't check for that before routing it through Tier 2/3, spending a real LLM + TTS call answering nothing.

**How it was found:** Reading the plain-text conversation log again — the empty `YOU:` lines were visible immediately, then cross-referenced against `turns.jsonl` to confirm STT genuinely ran and returned `""`.

**Fix:** Added an early short-circuit in the pipeline — if the transcript is empty/whitespace after STT, skip all further processing (no safety/intent/RAG/agent/TTS call, no log entry) and just silently resume listening.

**Why it matters:** Client-side signals (VAD, in this case) shouldn't be trusted blindly by the backend — validate at the boundary regardless of how good the frontend heuristic is. Also ties back to the earlier cost finding: since STT is cheap and TTS/LLM are the expensive part, this fix specifically targets the expensive part, leaving the (already-cheap) STT call as the only unavoidable cost of a false trigger.

---

## 15. Cancel-appointment silently cancelled the wrong appointment

**What happened:** Asked to cancel an appointment with "Ravi" (meaning Dr. Ravi Kulkarni). The system reported success — but it had actually cancelled a *different* appointment (with Dr. Suresh Iyer), leaving the intended one still confirmed.

**Root cause:** `cancel_appointment`'s phone+date lookup used `fetchone()` — when a patient had two active appointments on the same date with different doctors, it silently grabbed whichever row the database happened to return first, ignoring the doctor name the caller had actually specified. It never told the agent "there are two matches" — it just returned a false success for the wrong one.

**How it was found:** User flagged that "Ravi" was meant as the doctor's name; checking the database directly showed two active appointments on the same date under the same phone number, and the wrong one was the one marked cancelled.

**Fix:** Added `doctor_name` as an optional disambiguating filter on the tool. When multiple appointments still match after filtering, the tool now returns a structured `"ambiguous"` result listing every candidate (doctor + time) instead of guessing — the agent's system prompt already said to confirm ambiguous details, so once the tool actually *reported* the ambiguity instead of hiding it, the agent correctly asked "which one?" on the next test. Verified both the raw tool behavior and the full agent conversation flow before considering it fixed.

**Why it matters:** A tool that can silently do the wrong thing and still report success is worse than one that fails loudly — for anything that mutates real state (bookings, cancellations, payments), ambiguity in a lookup should be surfaced, never resolved by picking an arbitrary row. The system prompt telling the model to "confirm ambiguous details" was never the actual fix — the tool itself had to stop hiding the ambiguity in the first place.

---

## 16. Tier 2 (RAG) had zero conversation memory — and a bilingual-parser leak, and a "yes" dead-end

**What happened:** Three compounding problems surfaced in one real conversation. (a) The bot answered "yes" (to its own question, "would you like to schedule an appointment?") with "I'm not sure what you're asking" — total non-sequitur. (b) That same reply literally showed `SPOKEN: I'm not sure what you're asking...` printed twice on screen — raw internal formatting leaking to the user. (c) Asking the same question twice in one conversation got the exact same generic answer both times, no sign the bot remembered the first time.

**Root cause:** Tier 2 (RAG/Q&A) had no conversation history at all — every call was fully stateless, built fresh from just the current transcript + retrieved context, with no memory of anything said earlier in the same conversation. Tier 3 (the agent) already carried history; Tier 2 never got the same treatment. Two further consequences fell out of that: a bare "yes" has no action keyword, so the Tier 2/3 router had no way to know it was answering an invitation to book, and Haiku occasionally failed to follow the `EN:`/`SPOKEN:` output format (likely worse without conversation context to ground it), and the parser's fallback for a malformed response just showed the broken raw text as-is instead of handling it.

**How it was found:** User explicitly noticed "it is not having the context of the current conversation" after reviewing a real conversation log — the repeated-question and leaked-format symptoms were visible directly in the plain-text log.

**Fix, three parts:**
1. Gave Tier 2 real conversation memory — `rag.answer()` now accepts/returns history (last 5 Q&A pairs, plain text, kept separate from Tier 3's tool-call-formatted history to avoid bloating either with irrelevant structure).
2. Hardened `parse_bilingual()`'s fallback — if the model drops `EN:` but still includes `SPOKEN:`, split on that marker instead of showing the raw malformed text.
3. Added a "did the last reply invite an action" flag per conversation (regex over reply text: "would you like to/do you want to" + book/schedule/cancel/refill) — a bare affirmative ("yes", "sure", "ok") now routes to Tier 3 if the previous turn invited one.
4. When a conversation hands off from Tier 2 to Tier 3 for the first time, seed the agent's starting context with the recent RAG exchange instead of starting blind — verified this directly: after the fix, "yes" (following a cough question) made the agent jump straight into collecting booking details instead of asking "what would you like to do?" from scratch.

**Why it matters:** This is the same root-cause pattern as bug #9 (Tier 3 losing context) but one layer earlier — a tier that doesn't carry its own conversation state will eventually break on any follow-up that depends on what was already said, and the fix isn't a special case for "yes," it's giving the tier actual memory. Also a good example of one user observation ("no context") turning out to explain three separate-looking symptoms at once — worth looking for the shared root cause before patching each symptom individually.

---

## 17. Streaming TTS: built the "safe" version first, shipped the actually-wrong one, caught it from real latency numbers

**What happened:** Added Tier 2 response streaming (Claude generates token-by-token, each sentence gets synthesized to audio as soon as it's ready, instead of waiting for the whole reply). Designed it as an overlapped pipeline — TTS for sentence 1 running while Claude writes sentence 2. Measured a great result in an isolated test (1.91s to first audio vs. 5.4s baseline) and shipped it. Then real conversation testing showed **total** turn time had gotten *worse* than before streaming existed (9.9s vs. ~6s), and the latency log showed an impossible negative number: `"llm": -2088`.

**Root cause:** The isolated test only measured time-to-*first*-chunk, which looked great — but I never measured total time end-to-end before calling it done. The actual bug: my code did `await sarvam_client.synthesize(...)` **inside** the same loop that was reading Claude's token stream. In Python, `async for` on a generator pauses that generator while you're awaiting something else in the loop body — so while sentence 1's TTS call was in flight, Claude's stream was fully paused, not still writing sentence 2. There was **zero actual overlap**; it was fully sequential (read sentence → wait for its TTS → resume stream → read sentence → wait for its TTS...), just chunked instead of batched — and chunking means N separate network round-trips to Sarvam instead of 1, so total time went *up*. Separately, the latency math summed each chunk's own TTS duration as if that time was purely additive, which double-counts time when calls actually do run concurrently (once fixed) — producing the negative number.

**How it was found:** The user explicitly asked "so what did you do, can I test it?" and then, after testing, said the total experience didn't feel right — that prompted checking the actual conversation log and `turns.jsonl` instead of trusting the earlier isolated benchmark. The negative `llm` latency was the concrete, undeniable signal something was structurally wrong, not just "a bit slow."

**Fix:** Rebuilt as a real producer/consumer: a background task reads Claude's stream and *fires TTS calls as `asyncio.create_task`s without awaiting them* (never blocks the stream), while a separate consumer loop drains completed TTS results from an `asyncio.Queue` in order and yields them to the caller the moment each is ready. This genuinely runs concurrently — verified directly: total time dropped from the broken 9.9s to 3.05-5.3s (better than the pre-streaming baseline), while time-to-first-chunk stayed fast (1.9-2.4s for well-spread replies). Also fixed the latency math to track wall-clock *phases* (when text-generation finished vs. how much *additional* time TTS needed after that) instead of summing per-chunk durations, so `llm + tts` is honestly additive again.

**Why it matters:** "I measured the metric I set out to improve, saw a good number, and shipped it" is exactly how a well-intentioned optimization silently regresses something else — I designed the overlapped version correctly on paper, then implemented the simpler sequential version without noticing the two weren't the same thing, because the one number I checked (first-chunk latency) genuinely did look great either way. The real lesson: verify total effect, not just the metric you're targeting, especially for anything that changes an execution model (sequential → concurrent) rather than just a parameter.

## 18. Tier 2 falsely claimed "I don't have any information about our doctors" — twice, in real use

**What happened:** Asked "which are the doctors in your clinic" and "tell me the available doctors" (twice, in separate real conversations) — Tier 2 replied "I don't have information about our doctors' names and specialties" / "I don't have detailed information about our specific doctors." This is false — `doctors.json` is indexed and answers about specific doctors (e.g. "does Dr. Suresh Iyer see patients Saturday") had worked correctly many times before.

**How it was found:** Reading real conversation logs again (same pattern as #9 and #14 — bugs that only show up in actual multi-turn use, not synthetic single-question tests).

**Root cause, in two parts, and they needed to be told apart:**
1. **A real grounding bug**: for phrasing that *did* retrieve a relevant doctor chunk (e.g. "who are your doctors" retrieves Dr. Suresh Iyer + Dr. Ravi Kulkarni), the model still claimed to have "no information" rather than sharing the partial match it actually had. The system prompt's grounding instruction ("if the answer is not contained in the retrieved context, say you don't have it") was ambiguous about *partial* matches — the model read "the complete answer isn't here" as license to claim zero knowledge, instead of sharing what it did have.
2. **A separate, non-bug limitation**: for the *other* two failing phrasings, I checked retrieval directly and it genuinely returned zero doctor-related chunks — because both had typos ("**ur** clinic", "**availale** doctors") that shifted the embedding enough to miss every `doctors.json` chunk, even at `k=5`. The model saying "I don't have that" was *correct* given what it was actually handed — this one isn't a grounding failure, it's inherent sensitivity of small-corpus semantic search to typos, and widening `k` only partially compensated (fixed one phrasing, not the other) at the cost of deviating from the spec's documented `k=3` choice for a partial win — not worth it.

**Fix:** Rewrote the grounding instruction to explicitly require sharing partial matches ("if the retrieved context includes ANY relevant information, share what it actually contains, even if incomplete... only say you have nothing if there is truly nothing relevant"). Verified directly: "who are your doctors" now correctly names both indexed doctors and offers the front desk for the rest. Left the typo-sensitivity limitation undocumented-as-a-bug and documented-as-a-known-limitation instead — no code change, because the two "fixes" available (bump `k`, or heavier query normalization) either didn't fully solve it or cost more than the demo scope justifies.

**Why it matters:** Two symptoms that look identical from the outside ("bot claims no info") had genuinely different causes, and conflating them would have led to over-fixing one path (retrieval tuning) for a problem that was actually in the other (prompt wording), or under-fixing a real bug by writing it off as "just a RAG limitation." Diagnosing *which* layer failed — retrieval returned nothing relevant, vs. retrieval returned something the model ignored — before touching either is what made both the fix and the "don't fix this" call correct instead of a guess.

## 19. "List all doctors" only ever named 1 of 5 — and the real fix was a chunking strategy, not `k` tuning

**What happened:** Follow-up to #18. After the grounding-instruction fix, "tell me the available doctors" correctly stopped claiming "no information" — but it still only ever named **one** doctor out of five, every time, regardless of phrasing. I'd initially written this off in #18 as an accepted, unfixable limitation of small-corpus retrieval. The user pushed back: "but it only said about one doctor" — a fair challenge to accepting that as good enough.

**Root cause:** Each of the 5 doctors was indexed as its own tiny separate chunk in `doctors.json`. With `top_k=3`, a "list all doctors" query competes chunk-by-chunk against unrelated services/FAQ chunks for only 3 retrieval slots — there was never a code path that could return more than 2-3 doctors even in the best case, regardless of exact phrasing or embedding quality. The earlier attempt to fix this by raising `k` to 5 (documented in #18) was treating the symptom — it occasionally caught one more doctor chunk, but could never reliably return the *whole* list, because the underlying representation had no single chunk that ever contained all 5.

**How it was found:** Direct comparison after the fact — re-read the exact chunks retrieved for the query and noticed only 1 of 3 slots went to `doctors.json`, the other 2 to unrelated `services.json` content. That reframed the fix target: not "retrieve more chunks," but "make a single chunk exist that has the full list to retrieve in the first place."

**Fix:** Added one consolidated "all doctors" chunk to the index alongside the existing per-doctor chunks (`build_index.py`, `chunk_doctors_with_summary`) — a plain-text rollup listing every doctor's name, specialty, days, and timing together. Individual per-doctor chunks stay, so specific lookups ("does Dr. Iyer work Saturdays") are unaffected. Rebuilt the index (26 → 27 chunks) and verified directly: the summary chunk now gets retrieved as the top or near-top result for every doctor-listing phrasing tried, *including* the two typo'd ones ("**ur** clinic", "**availale** doctors") that had defeated even `k=5` before — because now there's one chunk whose content is unambiguously "the full doctor list," instead of relying on enough of 5 scattered fragments coincidentally surviving to the top-3. Confirmed specific single-doctor lookups still work correctly (no regression from the summary chunk competing for a retrieval slot).

**Why it matters:** The first fix attempt (#18, tuning `k`) treated this as a retrieval-*ranking* problem and only partially helped. The actual problem was a *representation* problem — no amount of better ranking finds information that isn't consolidated anywhere in the index. This is a real, general RAG lesson: for any small, enumerable, "list all X" category (doctors, services, locations), index a rollup chunk deliberately, don't rely on top-k averaging across N separate item-chunks to reconstruct a complete list. Also worth being honest about the process here: my first attempt (#18) explicitly called this "not worth fixing further" — the user's pushback ("but it only said about one doctor") was the reason a better fix got found at all. Don't let a documented "known limitation" become a reason to stop looking when someone reasonably points out the limitation still doesn't sit well as an actual answer.

## 20. Two confirmed bugs from a structured adversarial test pass — and the services fix needed a second attempt

**What happened:** Ran a deliberate adversarial test pass (a structured list of probes targeting specific architectural seams from bugs #9/#14/#16/#18/#19) rather than incidental testing. Two real bugs confirmed: (a) "what all services do you offer" only named 3 of 6 services, same shape as bug #19 but on `services.json` instead of `doctors.json`; (b) `"sure, go ahead"` wasn't recognized as answering "would you like to book?" even though "sure" alone was.

**Root cause (services, part 1 — the fix that didn't work):** First attempt copied #19's exact pattern: add one consolidated "all services" chunk to the index. Rebuilt, retested — still only 3 of 6 services. Checked retrieval directly: the summary chunk ranked **#6**, not even in the top-3. Reason: `doctors.json`'s summary chunk worked because "list doctors" queries are entity-listing queries that a concatenated summary naturally matches well. But "what all services do you offer" is topically identical to what *every individual service chunk already is* — each one IS a service, so they all score highly on the general "services" topic, and a summary chunk competing for the same 3 retrieval slots doesn't reliably win that contest no matter how it's worded (tried both a verbose and a compact version — still lost to individual chunks).

**Root cause (affirmative), and it's the same shape as #16's original "yes" bug, one layer more general:** `_is_affirmative` checked `transcript.strip().lower() in AFFIRMATIVE_PHRASES` — **exact string equality** against the whole trimmed transcript. "sure" (exact match) passed; "sure, go ahead" (a superset containing "sure") failed, because the check was never "does this contain a known affirmative," it was "does this equal one."

**How it was found:** A structured, deliberately adversarial test pass — not incidental use this time. Ran ~15 targeted probes directly against `rag.answer()`/`agent.handle_turn()` (bypassing TTS entirely to keep it a single bounded pass, no wasted audio-synthesis cost) instead of waiting for these to surface in a real conversation, which is how every previous bug in this log was found. Worth noting as a shift in method: once the bug *pattern* is understood (tier losing context, incomplete-list retrieval, exact-match brittleness), targeted adversarial testing finds the next instance of that pattern faster than incidental use does.

**Fix (affirmative):** Changed from exact-set-membership to a regex searching for any known affirmative phrase appearing anywhere in the transcript as a whole word (`\b(yes please|sounds good|go ahead|do it|yes|yeah|...)\b`). Verified against 8 cases including the original failure and a deliberate negative ("no thanks" correctly still returns `False`).

**Fix (services), take two — the real one: stop relying on retrieval ranking at all.** Tagged both summary chunks (`is_summary: True`) at index-build time, and changed `rag.py` to **always** include every `is_summary` chunk in context on top of whatever normal top-k retrieval returns — not conditional on whether it ranks in the top-3. This removes the dependency on winning an embedding-similarity contest entirely. Verified: "what all services do you offer" now lists all 6 with prices; re-verified doctors listing and both specific single-item lookups (a doctor's Saturday hours, a specific service's price) still work correctly — the 2 extra always-included chunks don't crowd out or confuse specific-item answers.

**Why it matters:** The first services fix failed not because the *idea* (rollup chunk) was wrong, but because I assumed a solution that worked once (doctors) would transfer directly to a structurally similar-looking case (services) without checking whether the *reason* it worked would hold. It didn't — doctors and services differ in how distinctly a "list them all" query separates from individual-item queries in embedding space. The actual fix (always include, don't rely on ranking) is strictly more robust and would have avoided both the original doctors problem AND this one if applied from the start — worth remembering: when a fix depends on winning a similarity/ranking contest, that's often a sign the more robust version doesn't need to win the contest at all.

## 21. Three voice-UX polish issues, all caught by the user's own demo run

**What happened:** User ran a real conversation and flagged three things that felt off for a *voice* product specifically: (a) prices got read out unprompted for plain "what services do you offer" questions, sounding like a sales pitch; (b) the booking flow literally asked the caller to speak a date "in DD-MM-YYYY format" — an internal API format leaking into spoken conversation; (c) lists (e.g. "documents to bring") came out as `1. ... 2. ... 3. ...`, which a TTS engine reads aloud as literal digits, sounding robotic.

**Root cause:** None of these were logic bugs — the system worked exactly as instructed, and none of the instructions accounted for what's *appropriate for a spoken interface specifically* vs. a text chat interface. (a) and (c) are the same root shape: the model defaults to normal LLM writing habits (mention relevant details like price, format lists with numbers) unless told those habits are wrong for this medium. (b) was a literal implementation leak — the booking tool's `date` parameter needs `YYYY-MM-DD` internally, and with no instruction telling the model to keep that requirement to itself, it surfaced the internal format directly in what it said out loud.

**How it was found:** User's own real usage, reading their own transcript — not something any automated test in this project would have caught, since all three are UX/tone judgments, not correctness bugs. A useful reminder that "is the answer factually right" and "does this sound right coming out of a speaker" are different review passes.

**Fix:** Added one shared `STYLE_GUIDELINES` block (`rag.py`, imported by both Tier 2 and Tier 3 since they share the same SPOKEN/EN output format) covering all three: no prices unless asked, natural spoken-language dates only (the model converts internally, tool schemas already require `YYYY-MM-DD` — unchanged, that instruction was never wrong, just needed to stay internal), and — the one genuinely enabled by the existing dual-output architecture — numbered/bulleted lists are banned in `SPOKEN` specifically but still allowed in `EN`, since `EN` is only ever read on screen, never synthesized. Verified all three directly: services list now has zero prices, a booking flow asked "what date would work best for you" with no format mentioned, and a documents-list reply came back as natural prose with no digits to read aloud.

**Why it matters:** This is a "know your medium" mistake, not an engineering one — the same reply would have been perfectly fine, even good, in a text chat interface. All three symptoms trace back to the same gap: nothing in the prompts distinguished "written for reading" from "written for speaking," even though the project's whole dual-output design already had the plumbing to treat them differently — it just hadn't been told to. Worth remembering when reusing content-generation patterns from chat/text products in a voice product: the format conventions that make text answers good (structure, precision, completeness) are sometimes exactly what makes spoken answers sound artificial.

<!-- Append new entries below this line as new problems are found and solved. -->
