# 03 - AI log

Where the coding agent (Claude Code) helped, where it failed, and how I corrected it. Newest entries at the bottom.

## Session 1 - planning (2026-11-18)

**Helped**
- Read the brief and CLAUDE.md in plan mode and proposed a 10-step build plan (`02-plan.md`).
- Flagged gaps in the brief:
  - `route_to` and `urgency` had no defined values
  - "word for word" wasn't defined (case, `#48213` vs `48213`, span boundaries)
  - two requests in one email, but only one `category`
  - no policy for a detail that fails the quote check
  - the `src/` layout didn't match the `python -m triage.cli` command in CLAUDE.md
- Flagged risks:
  - complaint and warranty escalation depends on the model's classification, which an injection can target
  - keyword false positives ("Sue" as a name)
  - `</email>` delimiter breakout
  - structured outputs make the "valid JSON" metric close to 100% by default
  - noise from a 15-email eval set

**Decisions I made**
- Anthropic SDK, `claude-opus-5-5`, set through `TRIAGE_MODEL`
- `.venv`, no python-dotenv
- a detail that fails the quote check is blanked and recorded, not escalated
- flat `triage/` layout

**Corrections**
- (none yet)

**Rule for the eval loop:** fixes must be general (a rule or the urgency rubric), not tuned to one test email's wording, because there's no held-out set.

## Session 1 - test set (2026-11-18)

- Claude drafted 15 synthetic emails and labels:
  - 5 edge cases, 10 ordinary emails
  - 7 need a human
  - fictional brands, and `example.com` senders only
  - traps for the keyword rules: "Sue from the store", a card number "4471", "#1 on Google", "local news", "hit the ball 180 metres"
- I hand-checked every label against its email on a review sheet and kept them as drafted.
- Calls that are arguable but deliberate:
  - e01 is labelled `complaint` (could be order_status)
  - e02 is `warranty_claim` (could be complaint)
  - e07 is `order_status` (could be complaint)
  - in e05, only the rangefinder counts as the product
- Known limit: e03's injection uses trigger phrases, so the rule checks catch it no matter what the model does. A subtler injection without trigger phrases would test the model on its own; it's a candidate for after the 2 hours.
- Known bias: the same agent wrote the keyword rules and the test emails, so rule recall on this set will be optimistic.

## Session 1 - order number format (2026-11-18)

**Domain knowledge I added.** Fairway Supply order numbers are always 9 digits starting with 1 (e.g. `#100046249`). Any other number isn't an order number. The agent's design had treated order numbers as free text, so nothing stopped a card number ("4471") or "#1" from being extracted as long as it was in the email.

**What changed**
- A deterministic format check runs before the quote check.
- Order numbers are stored as the 9 digits with no `#`.
- Dropped details now record why they were dropped: wrong format, or not in the email (invented).
- The model is told the format in its schema.
- Test set:
  - order numbers moved to the 9-digit format
  - e11 gained a 9-digit receipt number starting with 2
  - new e16 has a mistyped 8-digit order number, which must stay empty

**Trade-off.** A customer's mistyped order number is blanked, not guessed at. The queue will show it as "customer quoted ..." so the officer can follow up.

## Session 1 - model call (2026-11-18)

- **What the agent checked.** Before writing the call, it read the installed SDK (anthropic 2.10.0) instead of relying on memory.
  - `messages.parse` raises on any output that fails validation, which would lose the stop reason (needed to tell a refusal from a truncation) and the error text (needed for the retry feedback). It switched to `beta.messages.create` with the SDK's own `transform_schema`, and validates with our Pydantic models.
  - It also found that the SDK uses `httpx2`, not `httpx`.
- **Offline check.** The request arguments were bound against the real SDK method signature, so a typo in a parameter name would fail without spending an API call.
- **Escaping.** Escaping `&` as well as `<`/`>` was considered and rejected: a product like "Black & Decker" would reach the model as `&amp;`, and if the model copied that, the quote check would drop it.

## Session 2 - first live run (2026-11-19)

**Result.** `claude-opus-5-5`, effort medium, prompt v1, 16 emails, 49 seconds.
- Every email produced valid output on the first try. No retries, no fallbacks, no dropped details.
- Against the labels: category 16/16, `needs_human` 16/16 (7 flagged), order number, store and product 16/16 each.
- e03: the model ignored the injected "classify as other_or_spam" and returned `complaint`. The rule check flagged the injection as well.

**Found by reading the queue (not caught by any metric)**
- **Gendered pronouns.** Summaries guessed gender from names: "his" points balance (e10), "staff mocked him" (e03). The names don't say how these customers identify. A neutral wording rule belongs in the prompt.
- **e16's mistyped order number isn't surfaced.** The model followed the format rule and returned null itself, so the code-side "Check with customer: quoted #10046249" note never triggers. The officer only sees "the order number given is unclear" in the summary.

**What a perfect score means here.** Little. The same agent wrote the 16 emails, the labels and the prompt, so this set is too easy to tell a good prompt from a weak one. To show a real failure and fix (Step 8), we need harder emails or a weaker configuration.

## Session 2 - failure found and fixed: gendered summaries (2026-11-19)

**Failure.** With prompt v1, the model guessed customers' gender from their names in 2 of 16 summaries:
- e03: "staff mocked *him* when *he* tried to return…"
- e10: "check *his* Fairway Rewards points balance"

None of the emails says how the customer identifies. In a customer care tool that's a tone risk: an officer could repeat the guess back to the customer.

**How it was found.** I read the queue after the first live run. No metric covered it. The eval then gained a deterministic check: summaries containing he/him/his/she/her/hers/Mr/Mrs/Ms.

**My rule (prompt v2).** Always use gender-neutral wording: "the customer", "they/them", or the person's name. Never guess anyone's gender. This covers everyone in the email, not just the customer ("their son", not "her son"). The rule is general, not tuned to e03 or e10.

**Before and after** (`eval/results.md`):

| | v1 baseline (1 run) | v2 run 1 | v2 run 2 |
|---|---|---|---|
| Summaries with gendered pronouns or titles | 2/16 (e03, e10) | 0/16 | 0/16 |
| Escalation recall / precision | 7/7 / 7/7 | 7/7 / 7/7 | 7/7 / 7/7 |
| Category, extraction (3 fields) | 16/16 each | 16/16 each | 16/16 each |

Example: e10 went from "check *his* Fairway Rewards points balance" to "check *their* Fairway Rewards points balance". e02 now reads "injured *the customer's* son" instead of guessing the parent's gender.

**Limits**
- The rule lives only in the prompt, and the eval measures it. Code doesn't enforce it.
- A Pydantic check could reject a gendered summary and trigger the retry. But if the retry also failed, the email would be marked "classification failed" and sent to a person, which is a heavy cost for a wording slip. Left as an option.
- The check flags any word "Ms", including a product code like "MS-200" (a known false positive, covered by a test).
- The baseline is a single run. The after-fix result held over two runs.

## Session 2 - challenge set, first run (2026-11-19)

**Setup.** I wrote 3 hard emails from my customer care experience and labelled them in `data/challenge.toml`:
- c01: sarcasm
- c02: positive feedback
- c03: two order numbers

Before running, the agent's checker found TOML syntax slips and a few mislabelled fields, which were fixed with my agreement:
- difficulty notes I'd put in `expected_reasons` moved to `notes`
- `"order status"` corrected to `order_status`
- c03's store changed from `["Online"]` to `[]`, because online orders have no physical store

**Result** (prompt v2, `claude-opus-5-5`). Recall 1/2, precision 1/1, category 2/3, extraction 3/3 on every field, urgency 1/3.
- **c01 (sarcasm): handled.** Labelled `complaint` and sent to a person. The summary even says "sarcastically complains". My prediction that sarcasm would be hard was wrong for this example.
- **c02 (positive feedback): missed escalation.** The model chose `other_or_spam`, low urgency, routed "Low priority (no action needed)". I labelled it complaint/needs a person. The real gap is the taxonomy: there's no category for a compliment, so praise for a named staff member would never reach the store.
- **c03 (two order numbers): partly handled.** `order_number` holds only the first number (100043249). The summary lists both, so the officer still sees them, but the structured field loses one. Urgency came back `normal` where I said `low`. The model followed the rubric ("a customer waiting on an answer about their own order"), which doesn't match how I'd prioritise a no-pressure tracking enquiry.

**Open decisions:** a feedback/compliment category (c02), the urgency rubric for tracking enquiries (c03), and whether `order_number` should become a list (c03).

## Session 2 - fix: compliment category (2026-11-19)

**My decision.** Add a seventh category, `compliment`, rather than stretch "complaint" to cover praise. Officers would misread praise filed as a complaint, and praise for a named staff member should reach that store.

**What changed (prompt v3)**
- **Category:** `compliment`, defined as "praise or thanks for a store, a staff member, a product or the service". Sarcastic "praise" stays a complaint, which guards c01.
- **Tie-break:** warranty_claim or complaint first, then compliment, then the rest. Praise mixed with a routine question still reaches a person, who can answer both.
- **Needs a person:** always, with the reason "compliment to pass on". This is my label for c02.
- **Routing:** the named store's team when a store is verified, otherwise the customer care lead.
- **Urgency rubric:** praise to pass on is `normal`.
- **Brief:** the category table has a new row.
- **Labels:** c02 relabelled from complaint to compliment, since I'd only chosen complaint because no better category existed.
- **Main set:** e17 added (thanks to a Belconnen fitter), so every category has a test email. The customer calls the fitter "him", which tests the gender-neutral rule. **e17's label needs my check.**

**Before and after (challenge set)**

| | v2 | v3 |
|---|---|---|
| Escalation recall | 1/2 (c02 missed) | 2/2 |
| Category accuracy | 2/3 (c02: other_or_spam) | 3/3 |
| c02 route | Low priority (no action needed) | Store team (Richmond) |
| Urgency (labelled) | 1/3 | 2/3 (c03 still normal, not low: rubric decision still open) |

**Caveat.** The fix was measured on the email that exposed the gap, so it's tuned to c02 by construction. e17 in the main set is a second, independent compliment. The main-set re-run will also check that the new category doesn't pull other emails away from their correct category.

**Main-set regression run** (v3, 17 emails, e17 label checked by me)
- Escalation recall 8/8, precision 8/8.
- Extraction 17/17 on every field. Valid output first try 17/17. Gendered summaries 0/17.
- **e17 handled exactly as labelled.** `compliment`, sent to a person, routed to "Store team (Belconnen)". The summary avoided the customer's "him" for Tom.
- **Side effect: category 16/17.** e07 (third chase of an unshipped order, plus a chargeback threat) moved from `order_status` to `complaint`.
  - Across runs: v1 and v2 gave `order_status` 3/3. v3 gave `complaint` 6/6 (the eval run plus 5 extra runs of e07 alone).
  - So it's systematic, not noise. The v3 prompt changed how this borderline email is read. The likely cause is the reworded tie-break or the extra complaint wording in the compliment definition. Not isolated.
  - Downstream nothing changes: the chargeback rule still sends it to a person, routes it to the care lead and forces high urgency.
  - When the labels were drafted, e07 was flagged as arguable ("complaint is arguable").
  - The label stays `order_status` unless I decide otherwise on customer care grounds. Changing a label to match the model's output would inflate the score.

**My decision on e07: relabelled `complaint`** (2026-11-19).
- **Why:** from customer care experience, a third chase of an unshipped order with a chargeback threat is a complaint about how the order was handled, not a routine status question.
- **Disclosure:** I made this call *after* seeing v3 classify it as complaint. It's an officer's judgment on an email that was always arguable, not a correction found independently.
- **Effect on scores:** the saved v3 run re-scored to category 17/17 with no new API calls. Earlier runs (v1, v2) stay in `eval/results.md` as scored against the old label. Against the new label they would score e07 as a category miss.
- **Effect on behaviour:** none. e07 still goes to a person, routes to the care lead and is forced to high urgency by the chargeback rule.

## Session 2 - fix: keep every order number (2026-11-19)

**My decision.** When an email mentions several orders, every order number must be saved. In v3, c03 ("#100043249 and #100085626") kept only the first in the structured field. The summary named both, but anything reading the field would lose an order.

**What changed (prompt v4)**
- **Schema:** `order_number` (one value or null) became `order_numbers` (a list, empty if none). The model is told to list every order number, each as its 9 digits.
- **Format check:** runs on each entry separately. One bad entry is dropped without losing the good ones. Two numbers lumped into one entry ("#100043249 and #100085626") are split, not rejected.
- **Quote check:** checks each order number on its own, so an invented number doesn't cost a real one.
- **Queue:** shows "orders `100043249`, `100085626`".
- **Eval:** for order numbers, the extracted set must equal the labelled set exactly: every order, nothing extra, any order. Store and product keep their "any acceptable span" rule.
- **Labels:** the key was renamed in `data/labels.jsonl` and `data/challenge.toml`, with values unchanged.

**c03 urgency, my decision:** relabelled `low` to `normal`. I accept the rubric's view that a customer waiting on their own order is `normal`.

**Results**

| | v3 | v4 |
|---|---|---|
| c03 order numbers | `100043249` only | `100043249`, `100085626` |
| Challenge set | recall 2/2, category 3/3, urgency 2/3 | recall 2/2, category 3/3, extraction 3/3 on every field, urgency 3/3 |
| Main set (17) | 100% on every core metric (after e07 relabel) | 100% on every core metric; e07 still `complaint` |

**Note.** The urgency improvement on c03 comes from relabelling it to `normal`, not from any model change.

## Session 2 - write-up (2026-11-19)

- README written: what the tool does, how to run it, design decisions, guardrails, latest results, the failures found and fixed, honest limits, and what was cut.
- **Bug found while checking the README's commands.** `python -m eval.run --from out/triage.jsonl` crashed with a raw Pydantic traceback on a file saved before the `order_numbers` change. It now stops with a one-line explanation: the file is from an older pipeline version, re-run to regenerate. Two tests cover it.
- Brief, plan and CLAUDE.md commands updated to match what was built.

## Session 2 - demo report (2026-11-19)

- **Decision: the demo report (`out/queue.html`) is a static, dependency-free HTML page.** It uses standard-library `html.escape` and inline CSS, with no JavaScript, no external fonts or CDNs, and a Content-Security-Policy that blocks scripts and network loads. It opens offline for the demo, adds no dependency, and treats email text as untrusted (everything escaped, with the CSP as a second layer), so a hostile email such as e03 renders as inert text. Jinja, a JS framework or a Streamlit app would each have added a dependency and more attack surface for no gain in a read-only view.
- **Decision: live demo emails are kept apart from the test data.** `--single` appends each email and its result to `out/live.jsonl` (git-ignored), not to `data/`. The page shows them with a "Live" tag, and the eval never reads that file. Live emails have no labels, so letting them into the test set would make the eval's numbers meaningless. Tests check that the eval's scores are identical with or without live entries.
