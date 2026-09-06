# QianBi Novel (千笔一文)

[中文](README.md) · **English**

**A long-form fiction workbench where a human and an AI co-write** — the AI writes in full
view, and the human stays the author.

The hard part of writing a novel with AI is never "generate one chapter". It's that by
chapter 300 **the setting still holds, the costs still get paid, and the foreshadowing still
gets resolved**. QianBi Novel turns that into a gated pipeline — plus a co-writing interface
where you can intervene at every step.

> **From the author**: I believe the endgame for a writing agent is not "a model that writes
> better" but **a pipeline that knows how to say no** — which is why this may well be the most
> useful writing agent of the years ahead. That is not a benchmark result, it's an engineering
> bet: models get replaced every few months, but once a machine can pin down *"which setting
> was dropped, in which chapter"*, *"this quote does not exist in the text"*, *"this lock
> bypassed this must-rule"* — that evidence compounds. The heaviest parts of this repo are
> exactly that substrate: the prompt-assembly baseline, quote verification, deterministic
> re-checks, and the dual-codebase parity gate. None of it is glamorous. All of it compounds.

- 🗂️ **Entry-based worldbook** — every setting is a registered entry, activated by anchor,
  injected within budget. A long setting doesn't get truncated into mush 500 chapters in.
- ⛓️ **Costs must be paid** — regex contracts at `must` level + causality audit. Cheat-code
  overreach is blocked outright.
- 🤝 **Six-stage co-writing mode** — pitch → core setting → story outline → worldbook &
  rules → chapter outlines → prose. Each stage ends with an explicit "confirm" after you
  argue it out with that stage's agent.
- 🔍 **Three-layer review** — local deterministic L0 pre-check (free) → 6-dimension LLM
  final review (quote-verified, 3-vote denoising) → targeted repair loop.
- 🔄 **Plot backflow** — new settings that emerge in the prose are written back into the
  worldbook and foreshadowing ledger, and constrain everything after. No parallel universes.
- 📥 **Import external documents (built for fan fiction)** — drop in a setting bible: the
  agent decomposes **only what the document actually contains**, every item is verified, and
  a mapping preview must be confirmed before anything is written. Borrowed canon is pinned
  `[常驻]` so budget trimming can't eat it, divergence points become `must` contracts that
  block OOC at lock time, and the whole batch is reversible.
- 📜 **Contract panel** — every rule of this book is visible, editable, deletable; import
  batches are reverted from the same page. A contract should not be a black box.
- 🎨 **10 genre presets** — xianxia underdog / urban second chance / Cthulhu / rule-based
  horror / infinite flow / post-apocalypse / historical intrigue …, each with 6 stage-specific
  prompt sets.
- 💰 **Cost architecture (v0.19)** — two-tier stable prefixes (73%+ cache hit) + per-chapter
  session stacks + cascaded canon audit (-82%) + per-phase thinking budgets + review fast path
  + off-peak scheduling. Default settings now cost ~60-70% less per chapter than early builds.
- 🧭 **Agent control layer (v0.19)** — say "roll back to before the de-AI pass" or "rewrite
  chapter 2, more setup" in the co-writing chat and the agent actually operates the app
  (checkpoint rollback / outline regeneration / chapter rewrite / settings), destructive
  actions archived first.
- ✍️ **Human review mode (v0.19)** — you act as the reviewer at the finalize gate: type the
  blocking issues, the AI only fixes them. Zero review-model spend.
- 🔑 **BYOK, fully local** — bring your own model key. Manuscripts, config and version history
  live on your machine (MIT, no cloud).
- 🖥️ **Windows desktop app** — PySide6 + QML, one installer, no Python required.

![Co-writing mode: six-stage navigation, multi-turn discussion with the writing agent, live prose preview](docs/shot_co_writing.png)

---

## Download

| Channel | File | Notes |
|---|---|---|
| **Installer (recommended)** | `QianBi-Novel-v<version>-setup.exe` | Inno Setup, per-user (no admin rights); **creates a desktop shortcut**, uninstallable from *Settings → Apps*, and **uninstalling keeps your manuscripts** |
| **Portable** | `QianBi-Novel-v<version>-portable.zip` | Unzip and double-click. Deliberately installs nothing: no shortcut, no registry, no uninstall entry — delete the folder to remove it. Includes a README inside. |

Program and data are separate: config / presets / logs live in `%USERPROFILE%\.qianbi_novel\`,
while manuscripts default to `%USERPROFILE%\Documents\千笔一文\` (the save location is editable
per book). Both channels share these two places, so switching between them is free.

→ **[Releases](https://github.com/GLFzr/QianBi-Novel/releases/latest)** ·
every release ships a `SHA256SUMS.txt`. Verify before running.

Requirements: Windows 10/11 x64. No Python needed.

---

## Updating

An upgrade never touches your manuscripts. When a newer version exists, **a download icon
appears in the left rail** and opens the Update panel. That one screen always offers all
four routes — pick the one that matches your network situation:

| Your situation | What to do |
|---|---|
| GitHub reachable | Click **Download & verify**, then **Install**: the app quits itself, launches the installer and reopens afterwards. You never leave the app. |
| GitHub unreachable | **Open release page** / **Copy link**, get `...-setup.exe` onto the machine by any means that currently works (phone, cloud drive, a friend), then **Pick a downloaded installer** so the app re-computes its SHA-256. Install unlocks only on a match. |
| Can't even reach the manifest | **Import an offline manifest**: hand the ~1KB `latest.json` from the repo root to any online device, bring the file back, import it. Then same as the row above. |
| Portable / from source | Links and hashes only — the app **will not overwrite the binary that is currently running** (that always fails). Unzip over the old folder as before. |

The manifest itself is tried over four ordered channels — custom mirror → GitHub raw →
GitHub Pages → jsDelivr — and the first success stops the chain. The panel **lists how each
channel died** (connection reset / 404 / timeout), which is how you decide whether to
configure a proxy or go offline. Your Windows system proxy is read automatically, and if the
whole chain fails the app repeats it **without a proxy** — a stale proxy setting should not
be able to block updates.

### Why letting you type a mirror or import a friend's file is safe

Because "whoever can push you a new version" is the same person as "whoever can run an exe on
your machine". So the extra channels and the signature landed in the same release:

- The manifest must verify against an **Ed25519 public key pinned in the source**
  (`PUBKEYS` in `app/update_check.py`);
- The installer's **SHA-256 must match the manifest** — a locally picked file is hashed and
  compared the same way;
- If either check fails, the panel **never renders an Install button**. The manifest is only
  displayed to you; the app downloads nothing and executes nothing on its authority.
  URLs the app will download from or open are **https-only** — `file://` and `unc:` forms are
  refused outright. The manifest itself may come over http, because its signature, not the
  transport, is what carries the trust; a mirror you typed yourself is allowed too, and every
  byte it returns still has to match the signed SHA-256.

### "Windows protected your PC"

The installer has **no code-signing certificate** (an annual certificate is not worth it for
a side project), so after downloading and double-clicking it SmartScreen will show the blue
warning. That is the missing certificate, not a broken file: click **More info → Run anyway**.
If you are unsure, compare the SHA-256 against the one listed in the panel / on the release
page — a match means it is the file I published.

Checking at startup is **on by default**: at most one request per launch, downloading a
~1KB public version manifest, throttled to once per 24 hours (6/12/24/72 selectable in the panel), **uploading nothing** (no book
title, no config, no key). Switch it off in the panel and startup makes zero requests.
See [docs/PRIVACY.md](docs/PRIVACY.md).

"Not eating your data" is machine-enforced here, not a polite reminder:

- The installer **writes only into the program directory**
  (`%LocalAppData%\Programs\QianBi-Novel`). Manuscripts and config live outside it.
- An in-place upgrade clears the previous program tree first, so no half-old/half-new modules.
- If you point the install location at a folder containing a book or a `config.json`,
  the directory page **blocks you on the spot**.
- Uninstalling removes program files only; config and manuscripts stay untouched.
- A newer build merges an older `config.json` key by key — unknown keys and your own connection
  profiles survive. If the file is unreadable, it is first preserved as
  `config.json.broken-<timestamp>` instead of being silently discarded.

Outside of actions you take in the app, no background task ever rewrites your manuscript.
Backups are those two directories — copying only `.qianbi_novel` loses every book.

---

## Two modes, one kernel

### Automatic — you set the direction, the AI runs the pipeline

```
pitch → core setting → outline → chapter outlines → [per-chapter micro-loop × N] → done
```

The per-chapter micro-loop:

```
① Context assembly  core setting + genre preset + entry worldbook + regex contracts +
                    chapter outline + scene cards + last 3 chapter summaries + character
                    state + unresolved foreshadowing + previous ending
② Draft generation  writing slot, streamed (thinking → generation → done; pausable to read)
③ Word-count gate   local check; expand if short, compress if long, with anti-padding rules
④ AI-taste scan     local regex, free
⑤ De-taste rewrite  up to 2 rounds
⑥ 6-dimension audit review slot, L0 pre-check first
                    ├─ PASS / PASS-WITH-NOTES → eligible for lock
                    └─ REJECT → repair loop (root cause → targeted edit → re-review, 3 rounds)
⑦ Finalize          prose + 4 tracking files + summary chain + per-chapter config snapshot
```

### Co-writing — you can intervene at every stage

Each of the six stages is a multi-turn discussion with its own agent. When you're satisfied,
"confirm" summarizes it and hands off to the next stage:

| Stage | You talk to | What "confirm" does |
|---|---|---|
| Create project | — | Writes the pitch to disk |
| Core setting | Setting agent | Summarizes → handoff block to the next stage |
| Story outline | Outline agent | Same |
| Worldbook & rules | Worldbook agent | Line-by-line contract reconciliation |
| Chapter outlines | Outline agent | Continuity check → rolls the next batch of 5 chapters |
| Prose | Writing agent | Supervisor continuity check → final lock |

Plus two supporting roles: the **Supervisor** handles cross-chapter continuity and scope
control; the **Readback** agent infers what you meant when you hand-edit prose and points
upstream at what should have changed.

![Automatic mode cockpit: stage cards, step gates, quality trend](docs/shot_pipeline.png)

---

## Things worth calling out

### The entry-based worldbook engine — `app/wb.py`

Cramming the entire setting into the prompt as one string is the number-one reason long
serials fall apart mid-run: if the budget runs out, the string gets cut, and the cut is a rule.
So settings became entries:

- `parse(doc)` accepts four existing writing styles (bold backflow lines / `### Name` +
  attribute lines / `- Name: description` / table rows); same-name entries merge by
  "normalized name # section"
- every entry has a stable `id` and `content_hash` — "still there but changed" is detectable
- `assemble(proj, num, budget, preset=…, phase=…, anchors=…)` fills the budget by priority:
  **pinned > hits this chapter > recently registered > section weight**, returning
  `activated` / `dropped` as evidence
- Selection order ≠ render order: entries are chosen by priority but always emitted in
  original file order, so the same chapter never sees settings in a different order twice
- the fast path keeps its invariant: if the whole book fits the budget, the file is returned verbatim

### Contracts and cost: regex `must` level

Hard rules from your setting are written as
`rule text｜level：must｜scope：whole book`. `must` rules:

- are injected into **every prompt that can write prose** — generation, expansion,
  compression, de-taste rewrite, local rewrite. All five rewrite whole chapters or whole
  passages, so injecting contracts into the first draft only would leave the middle steps naked
- require the agent to **state where each rule lands in this chapter**; if it can't, and the
  rule conflicts with chapter events, it must ask you instead of quietly routing around it
- enter review dimension D (causality audit); a violation fails
- are **re-checked deterministically**: rules carrying a backticked pattern
  (`` No triple exclamation marks: `!{3,}` ``) are judged locally by `app/mustscan.py` at zero
  cost, with no reliance on model discipline; matched fragments become quotable, verifiable evidence

Precedence is fixed: **explicit author instruction > this book's must rules > this book's
worldbook > chapter outline > genre preset template**.

There is an escape hatch, but it never happens quietly: a deterministic violation blocks final
lock. You can still force-lock, and the violation plus its reason is written into that
chapter's force-lock record.

To be precise about the limit: **injection is not execution**. Natural-language musts
("every fate rewrite must exact a price") are not machine-decidable, so they still rely on
prompt constraints plus the reviewer's judgement — probabilistic. Hard gates only cover the
part that *is* decidable; raising a red flag on something undecidable just manufactures false
blocks, and trains people to force-lock without reading.

"Every fate rewrite must exact a price" should not depend on the model's mood.

### Three-layer review

| Layer | Cost | Does |
|---|---|---|
| **L0 deterministic pre-check** `app/core/scan.py` | free | Mangled proper nouns, ≥15-char repeats, numeric contradictions, missing hook, term drift — hard defects first |
| **6-dimension LLM audit** | review slot | Golden opening / payoff closure / cheat-power consistency / causality / character arc / hook |
| **Quote verification + voting** | same | Every finding must carry a source quote, matched by normalized substring + seed-anchored fuzzy matching; **quotes that fail verification are demoted to marginal and excluded from the repair loop**. k=3 votes per dimension, ties resolved strictly |

The third layer exists because of a very annoying real problem: review models **invent quotes**.
A fabricated "original text" isn't in the chapter at all, and a repair loop acting on it never converges.

### Plot backflow

During prose, models routinely invent settings that were never in the outline. The backflow
chain catches them instead of letting them evaporate:

```
lock chapter → MemoryBackflowWorker extracts
   ├─ new entity / new rule → idempotent write into the worldbook "## 追加登记" section
   │                          (merged in place, first-seen chapter preserved)
   ├─ foreshadowing change  → tracking table updated (dedup on add, hits only unresolved rows)
   ├─ divergence point      → registered as marginal findings
   └─ one-line summary      → appended to the summary chain
```

If the worldbook is edited by hand afterwards, locked chapters get an impact notice (with a
suggestion to explicitly unlock and re-check), and unlocked chapters continue under the new contract.

### Per-chapter config snapshots and "solidify as template"

Each generated chapter writes `正文/.annotations/第N.json`: preset, sampling, per-phase
parameters, which worldbook entries were actually activated or dropped for that chapter, and
the slot/model/prompt_hash of every LLM call. It deliberately does **not** go into
`state.json`, so the state file never balloons.

Right-click in the queue → "View generation config…" shows how a chapter actually grew.
Like it? "Solidify as template" stores those two layers of parameters as a user preset you can
reuse in your next book.

### The prompt-assembly baseline (against silently dropped fields)

`tests/probe_prompt_baseline.py` records the sha256 of 45 assembly-point prompts against a
fixed fixture book. Any change to assembly requires an explicit `--update-baseline`, otherwise red.

`wiring_check()` complements it with **positive assertions**: a preset field that has a value
must appear in the prompt that is supposed to carry it — a missing slot is a `WIRING FAIL`.
The motivation is concrete: a `deslop_extra` field once had zero call sites, so an 84–238
character genre-voice budget vanished silently from every prose prompt — and a byte baseline
can never detect that.

---

## Interface

| | |
|---|---|
| **Bookshelf** — multi-book management, pick a genre preset when creating | ![Bookshelf](docs/shot_shelf.png) |
| **Chapter queue** — status badges, stale-conclusion hints, pending-fix summary and one-click repair | ![Chapters](docs/shot_chapters.png) |
| **Preset library** — 10 built-ins, import/export your own, preview all 6 stage prompts | ![Presets](docs/shot_library.png) |
| **Settings** — multiple connection profiles, routing across writing/helper/review slots, sampling parameters | ![Settings](docs/shot_settings.png) |

Reader: fullscreen immersion (F5), 3 themes (night / parchment / plain white, Ctrl+T to cycle),
3-colour annotation highlights + notes + ideas straight into the writing notebook, per-chapter
position memory, multiple bookmarks.

Versioning: save-driven — a version exists only when you press Save (30 per chapter, with diff
and rollback), 5s debounced drafts plus crash recovery. Export to txt / epub; one-click project
zip backup and automatic daily backups.

---

## Running from source

```bash
git clone https://github.com/GLFzr/QianBi-Novel.git
cd QianBi-Novel
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python run.py
```

On first launch, add your API key under *Settings → Connections & models*.
**Keys go into the Windows Credential Manager** (`app/secrets.py`); `config.json` keeps only a
fingerprint, never plaintext. Crash dumps, logs and the telemetry sink are all redacted.

> **Prompt tuning scope**: the built-in prompt engineering (prose / de-taste / review) is tuned
> for the **DeepSeek API** — its thinking, reasoning_effort and parameter habits. That is why
> **all three slots ship pointing at DeepSeek V4 Pro**: one key gets the entire pipeline running.
> Twelve OpenAI-compatible platforms are preconfigured — eight domestic (DeepSeek / Alibaba
> Bailian / Zhipu / Kimi / Volcengine Ark / Tencent Hunyuan / MiniMax / SiliconFlow) and four
> overseas (OpenRouter / Google Gemini / xAI Grok / Groq); every address was probed from this
> machine against `<base>/chat/completions`, and each platform's note in the app records what
> actually came back (401 means the path is right and only auth is missing; a couple of overseas
> endpoints simply time out from within China). Non-DeepSeek models speak the protocol fine,
> but prose quality and gate convergence are not guaranteed at the same level (run three chapters
> and watch the gates before committing a book to one). Relays and local Ollama / LM Studio go
> through "Custom (OpenAI-compatible)". **Azure OpenAI and Cloudflare Workers AI are deliberately
> not preset**: they need a `deployment_id` and an `account_id` respectively — neither is
> expressible as base-url + key + model, and shipping them would only hand users a list of
> connections that cannot be made to work.
> The two factory rows dropped in this version (`ds-v4-flash` / `ocgo-flash`) are removed
> automatically on upgrade — but only when all three hold: never edited, referenced by no
> slot, and no Key stored under their id. Anything you changed, routed to, or typed a Key
> into is kept exactly as it is.

---

## Tests

```bash
# Offline unit tests (no API key, ~3 seconds)
.venv/Scripts/python -m pytest tests/unit -q        # 594 tests

# Offline probes: real Bridge + headless QML, covering gates/locks/backflow/relay/import/export
.venv/Scripts/python tests/probe_agent_relay.py
.venv/Scripts/python tests/probe_word_block.py
.venv/Scripts/python tests/probe_update_ui.py
# …… 44 probe_*.py in total: the offline probes plus the unit tests form the release gate; a few
#     (probe_models, probe_flash_reasoning …) are real-LLM experiments needing QIANBI_TEST_KEY;
#     probe_packaged is invoked by the release pipeline with --exe, and probe_ui_gallery
#     renders the full UI screenshot set.
```

| Probe | Covers |
|---|---|
| `probe_prompt_baseline.py` | 45 assembly-point prompt digests + positive wiring assertions for preset fields |
| `probe_qml_compile.py` | Compiles all 41 QML components (a wrong property silently prevents the whole tree from loading) |
| `probe_agent_relay.py` | Co-writing relay orchestration: each agent sees only the previous stage's output, Supervisor context cap, lock trigger point |
| `probe_word_block.py` | Word-count gate, lock interception, force-lock trail, stale queue |
| `probe_backflow_chain.py` | Full backflow chain: idempotency, external edits, missing outline, interruption, re-queue |
| `probe_import_ui.py` | External import: decompose only what exists → preview mapping → write only what's checked → revert by batch |
| `probe_update_ui.py` | Update chain, 46 checks with zero real network: channel fallback and per-channel failure reasons, unsigned manifests getting no Install button, offline manifest import, local package hashing, the 24h throttle, the settings key whitelist, panel overflow |
| `probe_conn_delete.py` | Connection deletion, 20 checks: two clicks to delete, the Key disappears with the card, the last connection can't be deleted, and the three guards that decide when a retired factory preset row may be auto-removed |
| `probe_about_ui.py` | About dialog: book/config paths match the Bridge, and its "Update…" entry actually opens the panel |
| `probe_packaged.py` | Packaged resource manifest audit + dev-vs-packaged assembly digest diff |
| `probe_panel_fit.py` | Six panels: horizontal/vertical overflow, squeezing, out-of-bounds |

**Real LLM end-to-end** (needs a key, ~20 minutes / on the order of ¥0.07):

```bash
.venv/Scripts/python tests/test_5ch_e2e.py
```

---

## Project layout

```
app/
  wb.py                 ★ entry-based worldbook engine (parse / assemble)
  importdoc.py          ★ external document import (chunked decomposition / verification /
                          slot mapping / batch revert)
  mustscan.py           ★ deterministic re-check of must contracts (free)
  secrets.py            ★ API key into Credential Manager + unified redaction
  selftest.py           ★ packaged-mode self check (imports/resources/assembly/QML load)
  usage.py              token and cost accounting
  update_check.py       update check against GitHub Releases
  singleinstance.py     single-instance lock (second launch raises the existing window)
  crash.py / logger.py / diagnostics.py / telemetry.py
  config.py             connection profiles / slot routing / gate policy
  project.py            project read-write (setting/outline/prose/tracking)
  deslop.py             local AI-taste scan (free)
  export.py             txt / epub export
  llm/                  OpenAI-compatible client (streaming/retry/fallback) + provider presets
  prompts/              planning / writing / review / memory / co_writing / scene_cards
  core/
    orchestrator.py     scheduling (QThread / resume / pause & stop)
    stages.py           stage implementations + 6-dimension review + repair loop + record chain
    scan.py             ★ L0 deterministic pre-check (mirrored on both ends)
    state.py            resume state / staleness / needs-human flag
    gates.py            word-count / AI-taste / review gates + count pre-check
    memory.py           summary chain, tracking, backflow writes, worldbook correction proposals
    versions.py         save-driven versions (30 rolling + diff)
    co_writing.py       co-writing state machine
    co_dialogue.py      co-writing workers (Dialogue/Summarize/Readback/Supervisor/Backflow)
  presets/              10 v2 genre presets
  ui/
    bridge.py           Python↔QML bridge
    qml/                Main + 6 panels + Theme (3 themes)
      components/       25 components (ReaderView / CwDialogueDock / ImportDialog / ReviewIssueDialog / …)
scripts/
  build_release.py      one-shot release pipeline (quality gates → version info → packaging →
                          smoke test → digest diff)
  dual_sync_check.py    shared-layer drift check (file level + symbol level AST digests)
tests/
  unit/                 36 files / 494 offline tests
  probe_*.py            42 headless chain probes
  evals/                prompt assembly baseline + review gold set
docs/                   design & planning docs, privacy notice
```

**What one book looks like on disk** (user directory, entirely local):

```
<BookName>/
  设定/    genre & pitch · worldbook · regex rules · blurb & tags · worldview/characters/factions/
  大纲/    outline.md · arc outline · outline_chNNN.md
  正文/    chNNN_title.md
    .versions/     save-driven versions
    .annotations/  per-chapter config snapshots + notes
    .drafts/       debounced drafts
  追踪/    character state · foreshadowing · timeline · context · chapter summaries · global summary
  pipeline_state.json
```

---

## Development

```bash
.venv/Scripts/python scripts/build_release.py     # full release pipeline
.venv/Scripts/python scripts/dual_sync_check.py   # shared-layer drift check
```

This project shares its business core with its sibling `qianbi-Novel-TUI` (a Textual terminal
version): `app/core`, `app/llm`, `app/prompts`, `app/presets` and `app/wb.py`.

Changes to the shared layer must be mirrored on both ends. Beyond file-level comparison there is
a **symbol-level gate**: key symbols are hashed by AST structure (comments, blank lines and line
endings don't count), which bypasses file-level exemptions. Symbols where the GUI intentionally
runs ahead must be registered in `DEFERRED_SYMBOLS` with "reason + the TUI's watermark at the
time" — if the watermark changed, the TUI was edited too, and it fails loudly.

---

## Privacy and security

- **Your data never leaves the machine.** Manuscripts default to `~/Documents/千笔一文/`;
  config, presets, logs and version history live in `~/.qianbi_novel/`. Apart from your model
  API calls there is no cloud. The only automatic outbound request is the update check: on by
  default at startup, at most once per 24 hours, **downloading** one ~1KB public version manifest
  from GitHub (or a mirror you configured) and uploading nothing — no book title, no config, no
  key. Switch it off in the Update panel and startup makes zero requests.
- **API keys live in the Windows Credential Manager**; no plaintext in the config file. Logs and
  crash dumps are redacted uniformly.
- **Telemetry is off by default**, writes only to local files, and uploads nothing.
  See [docs/PRIVACY.md](docs/PRIVACY.md).
- Third-party dependency and font notices: [THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).

---

## Known limitations

Listed honestly so you don't trip over them:

- **Windows-only packaging.** Linux/macOS require running from source; no distribution testing done.
- **Prompts tuned for DeepSeek.** Other providers produce shakier gate verdicts (the review
  phase now runs at uniformly low temperature to reduce that).
- **Long requests depend on endpoint stability.** Some compatible gateways drop connections on
  long single outputs; the client retries and degrades, but switching models or gateways can
  still surface this.
- **No upstream rework loop in the pipeline.** Changing a setting means manually unlocking the
  affected chapters and re-running (co-writing mode has an entry point for this).
- **`is_chapter_need_human`** is written by the repair loop but not consumed by automatic mode
  yet — it is only a queue marker.
- Chapters that don't converge after 3 repair rounds are marked for human review, not retried forever.
- **External import is "excerpt + mapping", not "read the whole book".** Long documents are
  chunked at 30k characters, capped at 8 chunks; only content genuinely present is processed
  (missing targets are reported explicitly), and anything the model embellishes fails verification.
- **Three things the update chain still cannot do**: ① the installer has **no code-signing
  certificate**, so SmartScreen will always prompt; ② **Install** is offered only to the
  installed build — portable and source builds must not overwrite the binary that is running,
  so they get links and hashes instead; ③ a ~51MB payload **cannot conjure bandwidth**. What
  the app does is shrink "is there a new version?" to one 1KB multi-channel manifest, make the
  offline route a first-class citizen, and pin integrity to the signature and the hash — it
  does not pretend to download a package for you when no network path exists.

---

## Campaign history: what each iteration did

Iterations here are organized as campaigns — one theme each, one evaluation each, one public
report each (all archived under `docs/`, including failures and negative results):

- **Capability rounds** (v0.15–0.18.4): professional-review score 72 → 86 across 8
  write→review→fix iterations; 6-dim review with quote verification and 3-vote denoising;
  repair loop with root-cause attribution; memory layer (continuity ledger / beat check /
  canon audit / calendar drift); 15 de-AI structural fingerprints; 10 genre presets.
- **UX / cost round** (v0.18.4–0.18.5): two-tier stable prefixes + chapter session stacks
  (cache hit 16% → 73.2%); per-phase thinking budgets; token/reasoning observability;
  anonymous beta data packs.
- **Cost experiment campaign** (v0.18.6–0.19.0): 10 experiments (E1-E10) on same-seed books
  with planted-defect ground truth. Kept: cascaded canon audit (-82%), review thinking
  disabled (recall 4/4 vs 3/4), fast path, outline low. Rejected and published as negative
  results: prose=low (+5%), prose=medium (+64%), audit medium/disabled (recall collapse or
  fabricated quotes). **Task nature decides the tier** — checklist tasks don't need reasoning,
  cross-chapter reconciliation does.
- **Agent-ization** (v0.19): tool layer + rule parser (L1) + LLM intent fallback (L2,
  holdout accuracy 44% → 89%, ~255 tokens/call), false-trigger red line 0%. L3 waits for
  real usage data; L4 (fully autonomous pipeline) is explicitly not on the roadmap.

## Versions

The single source of truth for the version number is `__version__` in `app/__init__.py`.
Full history in [CHANGELOG.md](CHANGELOG.md).

| Version | Theme |
|---|---|
| **v0.19.0** | **Cost architecture + agent control**: cascaded canon audit (flash prescan → clean chapters skip the pro pass entirely / only flagged items go to pro re-review, **-82%**), review thinking tier reset (planted-defect test: disabled recall 4/4 vs high 3/4, **-88%** cost, 82s→5s), **human review mode**, **agent control layer** (rule parser + LLM intent fallback; false-trigger rate 0%), review fast path on by default, outline thinking downgraded |
| **v0.18.5** | Proxy-free mirror-accelerated updates (5 measured mirrors, SHA-256 still gates) + cache fixes that made the chapter-tier shared context actually land — blended hit rate 57.8% → 73.2%, review vote latency 170s → 43s |
| **v0.18.4** | Public-beta starting point: two-tier stable prefix architecture (16% → 57.8%) + memory layer (continuity ledger / beat check / canon audit / calendar-drift proposals) + source-novel worldbook import + **anonymous beta data packs** |
| **v0.18.1** | The update chain matures: automatic startup check (on by default, 24h throttle) + persistent left-rail icon + four-channel manifest fetch with per-channel failure reasons + **Ed25519 signature required before anything downloads or runs** + offline manifest import and local-package hash verification + one-click upgrade for installed builds (download → verify → quit → relaunch); connection presets grow from 3 measured platforms to 12 |
| **v0.17.0** | UI maturation: design system 2.0 (luminance steps/self-drawn controls/desaturated semantics) + modal overlays & five text-overlap fixes + reader heading hierarchy & CJK quotes + root-cause fix for zero panel padding (ScrollView ignores Layout.margins) |
| **v0.16.0** | External document import (fan-fiction path: decompose only what exists · preview mapping · batch revert) + per-book contract panel + both update paths stop eating data + interruptible streaming with visible reasoning + panel outlining and outline-batch navigation |
| v0.15.0 | Entry-based worldbook activation + preset assembly layer (scene cards / per-phase sampling / per-chapter snapshots / solidify as template) + three-layer review + plot backflow + word-count gate + packaging parity gate |
| v0.14.0 | Commercial packaging: installer & portable zip, single-instance lock, crash handling, keys into Credential Manager, update check, first-run wizard |
| v0.13.0 | Full port of the TUI's strengths: 10 v2 presets, 6-dimension review + repair loop, 6 scene-card types, 3 themes |

---

## License

[MIT](LICENSE) © 2026 QianBi Novel contributors.

Built with [PySide6](https://www.qt.io/) (Qt for Python), [httpx](https://www.python-httpx.org/),
[Keyring](https://pypi.org/project/keyring/) and others — see
[THIRD-PARTY-LICENSES.md](THIRD-PARTY-LICENSES.md).
