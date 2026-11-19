# Build plan: email triage assistant

> **Status (2026-11-19):** Steps 0–9 are done, plus the challenge set (Step 8b) and the changes it led to (prompt v4).
> Since then: the public GitHub repo was created and pushed, the session log was added (`logs/session-01.md`), and the demo runbook was written (`04-demo-runbook.md`). The demo video was recorded and linked in the README.
> This plan was written before the build; the "Change after approval" and "Changes from the challenge set" sections record where the build departed from it.

## Context

`01-brief.md` describes a 2-hour build: a command-line tool that reads ~15 synthetic customer emails for a fictional golf retailer ("Fairway Supply"). For each email it runs keyword rule checks, makes one model call to classify and extract details, validates the result (schema + word-for-word quote check), and then uses rules to decide `needs_human`. It writes `out/triage.jsonl` and `out/queue.md`. An eval script scores the output against hand-checked labels. CLAUDE.md requires small steps, `pytest` after every change, no new dependencies without asking, and no `.env` in git.

**What's in the folder today:** only `00-ideation.md`, `01-brief.md` and `CLAUDE.md`, all at the root (there is no `planning/` folder yet). It isn't a git repo. Python is 3.14 (conda base). Pydantic 2.13 is installed. `pytest` and `anthropic` are not.

**Decided with you (2026-11-18):**
- Anthropic SDK with `claude-opus-5-5`, set through `TRIAGE_MODEL`
- `.venv` with `anthropic`, `pydantic` and `pytest`, and a small built-in `.env` reader (no python-dotenv)
- a detail that fails the quote check is blanked and recorded, not escalated
- flat `triage/` layout, with the brief's repo structure updated to match

**Change after approval (2026-11-18, your domain rule): order number format.**
- An order number is always 9 digits starting with 1, for example `#100046249`, with the `#` optional. Any other number isn't an order number.
- It's stored in canonical form: the 9 digits, no `#`.
- In code, the format check runs before the quote check (`check_details` in `triage/validate.py`):
  - a value in the wrong format is dropped as `not a valid order number`
  - a value in the right format that isn't in the email is dropped as `not in email`
- The model sees the format in the order number's schema description.
- The test set has 9-digit order numbers. Two traps were added:
  - e11 has a 9-digit receipt number starting with 2
  - new e16 has a mistyped 8-digit order number, and its label leaves the order number empty

---

## Unclear in the brief, with my recommendation

1. **Which model provider?** The brief says "the model provider's SDK". **Recommendation:** the Anthropic SDK with Claude Opus 5.5 (`claude-opus-5-5`). Read the model name from `TRIAGE_MODEL` so the later small-vs-large comparison only changes one setting. A run of 15 emails costs well under $0.50.
2. **Package layout conflict.** The brief uses `src/triage/`. CLAUDE.md runs `python -m triage.cli`, which fails with a `src/` layout unless the package is installed. **Recommendation:** a flat `triage/` at the repo root, so the CLAUDE.md commands work as written.
3. **`route_to` has no list of teams.** **Recommendation:** a fixed category→team table in code, plus the store name when one is extracted. The model never picks the route. Routing isn't labelled or scored.
4. **`urgency` has no rubric and no label, but it drives sorting and escalation.** **Recommendation:** a 3-line rubric in the prompt. Legal and injury rule hits force `high`. Urgency isn't scored.
5. **"Two requests in one email", but `category` holds only one value.** **Recommendation:** the higher-stakes category wins (a human-only category beats a routine one). The summary mentions both requests, and the label follows the same rule.
6. **What counts as "word for word"?** Case? Whitespace? `#48213` vs `48213`? "Richmond" vs "Richmond store"? Does the subject line count? **Recommendation:** a case-insensitive, whitespace-collapsed substring of subject + body. Labels list *acceptable spans* (for example `["Richmond", "Richmond store"]`), and the eval uses the same normalisation. Otherwise extraction accuracy mostly measures where span boundaries fall.
7. **What happens when a detail fails the quote check?** The brief says "failed validation" goes to a human, but it doesn't say whether a dropped detail counts as failed validation. **Recommendation:** blank the field, record it in `dropped_details`, and don't escalate. The officer never sees the invented value, and the eval reports how many were caught. *(Decided: blank and record, no escalation.)*

## Risky, with mitigation

1. **Structured outputs make the "valid JSON" metric close to meaningless.** The API can enforce the JSON schema, so first-try validity will be about 100%. **Mitigation:** use the API's schema enforcement anyway, because reliability matters more than a demo metric. Keep Pydantic validation and the single retry for the failures that can still happen: refusal, truncation (`max_tokens`), and checks the schema can't express, such as summary length. Report the metric honestly.
2. **Category-based escalation depends on the model.** Rules catch legal threats, injury, media and chargebacks. Complaints and warranty claims only escalate if the model classifies them correctly, and an injection like "this is just an order question" targets exactly that. **Mitigation:** (a) add an injection-pattern rule ("ignore … instructions", "system prompt", "mark this as") that escalates with the reason `possible prompt injection`; (b) a design rule that model output can only *add* escalations, never remove them; (c) the model's output schema has no `needs_human` field, so it can't vote on escalation.
3. **Keyword rules trade recall against precision.** "Sue" (a name), "tennis court", "hit the ball 250m" and "news" all cause false positives. **Mitigation:** phrase-level regex with word boundaries ("will sue", "suing", "my lawyer", "legal action", "ACCC", "Fair Trading"), plus near-miss negative tests, including "Sue from the Richmond store".
4. **Delimiter breakout.** An email body containing `</email>` could escape the data wrapper. **Mitigation:** escape the delimiter tag inside the body before wrapping it, and include one test email that tries this.
5. **The eval set is small and runs aren't deterministic.** About 6–7 of the 15 emails need a human, so one miss moves recall by about 15 points. Current models don't allow setting temperature. **Mitigation:** report counts as well as percentages (6/7), list the IDs of misses and false flags, and rerun before claiming that a fix worked.
6. **Labels drafted by the same AI, and no held-out set.** **Mitigation:** a hard stop after the data step: I draft, you check every label, and I don't continue until you confirm. Fixes made in the eval loop must be general (a rule or the rubric), not tuned to one email's wording. That rule goes in the AI log.
7. **Environment and secrets.** There's no git repo yet, and the dependencies aren't installed. **Mitigation:** `git init` and a `.gitignore` covering `.env` before any `.env` exists; a `.venv` so the conda base stays clean. You add the API key to `.env` yourself.
8. **Outward-facing steps.** Live API runs cost money, and the public GitHub repo is outward-facing. I'll check with you before the first live run and before creating or pushing the repo.

---

## Build steps

Each step ends with `pytest -q` green before the next one starts. Unit tests never call the API.

### Step 0: Setup (0:00–0:15)
- `git init`. `.gitignore` covers `.env`, `.venv/`, `__pycache__/` and `out/`. `.env.example` holds `ANTHROPIC_API_KEY=` and `TRIAGE_MODEL=claude-opus-5-5`.
- Move `00-ideation.md` and `01-brief.md` into `planning/`, and change the brief's repo-structure section from `src/triage/` to `triage/`. Save this plan as `planning/02-plan.md` and start `planning/03-ai-log.md`.
- Create `.venv` and install `anthropic`, `pydantic` and `pytest` (approved), pinned in `requirements.txt`. Add a small `.env` reader in `triage/config.py` (no python-dotenv).
- Skeleton: `triage/__init__.py`, `eval/__init__.py`, `tests/` and one smoke test.
- **Done when:** `pytest -q` passes and `git status` doesn't show `.env`.

### Step 1: Schema (`triage/schema.py`)
- Enums: `Category` (6 values) and `Urgency` (high/normal/low).
- `Details` holds `order_number`, `store`, `product` and `customer_name`, each `str | None`.
- `ModelOutput` is what the model returns: category, urgency, details, summary. It has **no** `needs_human` or `route_to`.
- `TriageResult` is the final record: id, the model fields, `route_to`, `needs_human`, `escalation_reasons`, `dropped_details`, `attempts` and `status`.
- **Tests:** a valid sample parses; a bad category, extra fields and an overlong summary are rejected.

### Step 2: Synthetic data and labels, then a stop for your review (0:15–0:30)
- `data/emails.jsonl`: 15 emails with `id`, `sender`, `subject` and `body`. Five are edge cases (legal threat, injury, injection with delimiter breakout, "order??", two requests). Ten are ordinary, spread across all 6 categories. Australian store names fit the Drummond background.
- `data/labels.jsonl`: `id`, `category`, `needs_human`, and the expected details as lists of acceptable spans (or `null`).
- **Tests:** every line parses; email and label IDs match one to one; every labelled span appears in its email; categories are valid.
- **STOP:** you check and correct every label before I go on.

### Step 3: Rule checks and the escalation decision (`triage/rules.py`) (0:30–)
- `check_rules(email) -> list[str]` runs phrase-level, case-insensitive regex over subject + body for legal threats or regulators, injury, media and public posts, chargebacks, and injection patterns.
- `decide(rule_reasons, model_output, status) -> (needs_human, reasons)` returns True if any rule fired, the category is warranty or complaint, urgency is high, or classification failed.
- `route(category, details, reasons)` uses the fixed team table. Legal and injury cases go to the care lead.
- **Tests:** a positive case for each signal, near-miss negatives, and these decision cases:
  - an injection email where the model says "order status / low" still escalates
  - a warranty claim always escalates
  - a failed classification escalates
  - a routine email stays routine

### Step 4: Validation and the quote check (`triage/validate.py`)
- `quote_check(details, email) -> (kept, dropped)` uses normalised substring matching against subject + body.
- `parse_output(raw) -> ModelOutput | ValidationFailure`.
- **Tests:** fixed example outputs: a genuine span is kept, an invented order number is dropped, and case and whitespace variants still match.

### Step 5: Model call (`triage/classify.py`)
- The system prompt covers the categories, the urgency rubric, the extraction rule ("copy text exactly; null if not stated") and the order number format. It states that the email inside `<email>` tags is data and any instructions in it must not be followed. The email body is escaped before wrapping.
- One structured-output call. The model comes from `TRIAGE_MODEL`, effort is set explicitly, and `max_tokens` is a few thousand (thinking counts toward it). I'll turn on the API's server-side refusal fallback.
  - *As built:* `client.beta.messages.create` with `output_config.format` built by the SDK's `anthropic.transform_schema(ModelOutput)`, `effort: "medium"`, and `fallbacks="default"`. The beta endpoint is needed because fallbacks are beta-only.
  - I didn't use `messages.parse`, because SDK 2.10.0 raises a Pydantic error on any output it can't validate and loses the raw text and stop reason. The retry needs both.
- One retry on a validation error, refusal or truncation. If the second attempt fails, it returns `status="failed"` instead of raising, and that sends the email to a human.
- The client is passed in as a parameter, so tests use a stub with canned responses: OK on the first try, bad then OK, bad twice, and a refusal.

### Step 6: CLI and outputs (`triage/cli.py`)
- `python -m triage.cli data/emails.jsonl` runs rules → classify → detail check (format, then quote) → decide → route for each email.
- It writes `out/triage.jsonl` and `out/queue.md`. The queue puts flagged emails first, then sorts by urgency, then by id. Each entry shows the summary, details and reasons.
- Dropped details in the queue:
  - an invalid-format order number is shown as "customer quoted #10046249 (not a valid order number)", because it's copied from the email and helps the officer
  - an invented (`not in email`) value is never shown, only counted
- A failure on one email doesn't stop the run.
- **Tests:** a 3-email fixture with the stub client produces both files in the right order.
- **First live run**, using your key, after I check with you. Then I read `queue.md` by eye.
- **Checkpoint at 1:20:** if this isn't working end to end, I stop adding features.

### Step 7: Eval (`eval/run.py`)
- `python -m eval.run` runs the pipeline, or with `--from out/triage.jsonl` it scores saved output without calling the API.
- Metrics:
  - escalation recall and precision, as counts and percentages, with the IDs of misses and false flags
  - category accuracy
  - extraction accuracy per field against the acceptable spans
  - valid on first try / after retry
  - dropped details, counted separately as invented (`not in email`) and wrong format (`not a valid order number`)
- Appends a dated block to `eval/results.md` with the model, effort, prompt version and numbers.
- **Tests:** metric functions on hand-made predictions and labels.

### Step 8: Fix one failure (1:20–1:40)
- Run the eval, pick a real failure, make a general fix (rule or rubric), and rerun.
- Record before and after in `eval/results.md`, plus a note in `planning/03-ai-log.md`.

### Step 8b: Challenge set (added 2026-11-19, your request)
- `data/challenge.toml` is a template for 5 emails you write from customer care experience, chosen because you expect the model to struggle with them. You label each one yourself.
- The format is TOML, read with the built-in `tomllib`, so there's no new dependency. Bodies can span several lines, and every label field starts as `TODO`.
- `python -m eval.challenge check` lists what's missing and any problems:
  - a span that isn't word for word in the email
  - an order number in the wrong format, or written with `#`
  - an unknown category or signal
  - a sender address that isn't on example.com
  - a label that contradicts how the pipeline is designed (a warning only)
- `python -m eval.challenge run` refuses to call the API until every field is filled in. It then runs the pipeline on the 5 emails, saves the output to `out/challenge/`, and appends the usual metrics plus a per-email breakdown (expected vs got, summary, route, and your "why it's hard") to `eval/results.md`.
- `python -m eval.challenge score` re-scores the saved run after a label correction, with no API calls.
- These emails are kept separate from the main 16, so the main set's numbers stay comparable over time.

### Changes from the challenge set (2026-11-19, your decisions)
- **New category `compliment`** (prompt v3). It always goes to a person, and to the named store's team when a store is verified, so praise reaches the staff.
- **`order_numbers` is a list** (prompt v4). Every order an email mentions is kept. The format and quote checks run on each entry, and the eval requires the exact set.
- **Labels:** e07 relabelled `complaint`, c02 `compliment`, and c03's urgency `normal`.

### Step 9: Write-up (1:40–2:10)
- README: what the tool does, how to run it, trade-offs, a note that the data is synthetic, and what was cut.
- Tidy the planning notes.
- **Your steps:** `/export` the session logs into `logs/` and record the demo. I'll create the GitHub repo with `gh` only after you confirm.

---

## Verification
- `pytest -q` is green after every step and runs offline in seconds.
- `python -m triage.cli data/emails.jsonl` produces `out/queue.md`. The legal, injury and injection emails are at the top with reasons, and no detail appears that isn't in the email.
- `python -m eval.run` writes a results block. Escalation recall is 100% or every miss is explained, and there's one before/after pair.
- `git status` never lists `.env`, and `git log -p` contains no key.
