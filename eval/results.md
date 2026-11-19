# Eval results

Each run is appended by `python -m eval.run`. Newest at the bottom. Labels: `data/labels.jsonl` (hand-checked). Synthetic data only.

## 2026-11-19 11:20 - scored from out/triage.jsonl

Models that answered: claude-opus-5-5 x16 · effort medium (current code) · prompt v1 (current code) · 16 emails

Note: Baseline: first live run (2026-11-19), claude-opus-5-5, effort medium, prompt v1. 16 hand-checked emails.

| Metric | Result |
| --- | --- |
| **Escalation recall** (headline) | **7/7 (100%)** |
| Escalation precision | 7/7 (100%) |
| Category accuracy | 16/16 (100%) |
| Extraction: order number | 16/16 (100%) |
| Extraction: store | 16/16 (100%) |
| Extraction: product | 16/16 (100%) |
| Rule signals found | 4/4 (100%) |
| Valid output, first try | 16/16 (100%) |
| Valid output, after retry | 16/16 (100%) |
| Failed classification | 0 |
| Dropped details: invented (not in email) | 0 |
| Dropped details: not a valid order number | 0 |
| Summaries with gendered pronouns | 2/16 (12%) |

- Missed escalations: none
- False flags: none
- Category errors: none
- Extraction errors: none
- Missed rule signals: none
- Gendered summaries: e03, e10

## 2026-11-19 11:43 - live run, requested claude-opus-5-5

Models that answered: claude-opus-5-5 x16 · effort medium · prompt v2 · 16 emails

Note: Prompt v2: gender-neutral wording rule. After-fix run 1 of 2. Before (v1 baseline): gendered summaries 2/16 (e03, e10).

| Metric | Result |
| --- | --- |
| **Escalation recall** (headline) | **7/7 (100%)** |
| Escalation precision | 7/7 (100%) |
| Category accuracy | 16/16 (100%) |
| Extraction: order number | 16/16 (100%) |
| Extraction: store | 16/16 (100%) |
| Extraction: product | 16/16 (100%) |
| Rule signals found | 4/4 (100%) |
| Valid output, first try | 16/16 (100%) |
| Valid output, after retry | 16/16 (100%) |
| Failed classification | 0 |
| Dropped details: invented (not in email) | 0 |
| Dropped details: not a valid order number | 0 |
| Summaries with gendered pronouns or titles | 0/16 (0%) |

- Missed escalations: none
- False flags: none
- Category errors: none
- Extraction errors: none
- Missed rule signals: none
- Gendered summaries: none

## 2026-11-19 11:44 - live run, requested claude-opus-5-5

Models that answered: claude-opus-5-5 x16 · effort medium · prompt v2 · 16 emails

Note: Prompt v2: gender-neutral wording rule. After-fix run 2 of 2. Before (v1 baseline): gendered summaries 2/16 (e03, e10).

| Metric | Result |
| --- | --- |
| **Escalation recall** (headline) | **7/7 (100%)** |
| Escalation precision | 7/7 (100%) |
| Category accuracy | 16/16 (100%) |
| Extraction: order number | 16/16 (100%) |
| Extraction: store | 16/16 (100%) |
| Extraction: product | 16/16 (100%) |
| Rule signals found | 4/4 (100%) |
| Valid output, first try | 16/16 (100%) |
| Valid output, after retry | 16/16 (100%) |
| Failed classification | 0 |
| Dropped details: invented (not in email) | 0 |
| Dropped details: not a valid order number | 0 |
| Summaries with gendered pronouns or titles | 0/16 (0%) |

- Missed escalations: none
- False flags: none
- Category errors: none
- Extraction errors: none
- Missed rule signals: none
- Gendered summaries: none

## 2026-11-19 12:41 - CHALLENGE SET, live run, requested claude-opus-5-5

Models that answered: claude-opus-5-5 x3 · effort medium · prompt v2 · 3 emails

Note: First challenge run: 3 hand-written emails (sarcasm, positive feedback, two order numbers). Prompt v2.

| Metric | Result |
| --- | --- |
| **Escalation recall** (headline) | **1/2 (50%)** |
| Escalation precision | 1/1 (100%) |
| Category accuracy | 2/3 (67%) |
| Extraction: order number | 3/3 (100%) |
| Extraction: store | 3/3 (100%) |
| Extraction: product | 3/3 (100%) |
| Rule signals found | n/a |
| Valid output, first try | 3/3 (100%) |
| Valid output, after retry | 3/3 (100%) |
| Failed classification | 0 |
| Dropped details: invented (not in email) | 0 |
| Dropped details: not a valid order number | 0 |
| Summaries with gendered pronouns or titles | 0/3 (0%) |

- Missed escalations: c02
- False flags: none
- Category errors: c02: other_or_spam, expected complaint
- Extraction errors: none
- Missed rule signals: none
- Gendered summaries: none

Urgency (where labelled): 1/3

### Per email

#### c01 - How great is AI

Why it's hard: This email will contain sarcasm, which may be difficult for the model to detect.

| | Expected | Got | |
| --- | --- | --- | --- |
| Category | complaint | complaint | ok |
| Needs a person | yes | yes: complaint | ok |
| Urgency | normal | normal | ok |
| Order number | (none) | (none) | ok |
| Store | (none) | (none) | ok |
| Product | (none) | (none) | ok |

- Summary: Customer sarcastically complains about getting club recommendations from an AI chatbot on the online store and wants it changed.
- Route to: Customer care lead
- Your note: Difficulty: sarcasm.

#### c02 - Great Service at the Richmond Store

Why it's hard: This email will be a positive feedback email, about a customer being happy with service from a store. There is no positive feedback category, so it will be interesting to see how the model handles it.

| | Expected | Got | |
| --- | --- | --- | --- |
| Category | complaint | other_or_spam | **MISS** |
| Needs a person | yes | no | **MISS** |
| Urgency | normal | low | **MISS** |
| Order number | (none) | (none) | ok |
| Store | Richmond | Richmond | ok |
| Product | (none) | (none) | ok |

- Summary: Customer is complimenting the service at the Richmond store, especially salesperson James for being attentive and helpful.
- Route to: Low priority (no action needed)
- Your note: Difficulty: positive review, and there is no positive feedback category.

#### c03 - Check updates for my orders

Why it's hard: This email will contain multiple order numbers.

| | Expected | Got | |
| --- | --- | --- | --- |
| Category | order_status | order_status | ok |
| Needs a person | no | no | ok |
| Urgency | low | normal | **MISS** |
| Order number | 100043249 / 100085626 | 100043249 | ok |
| Store | (none) | (none) | ok |
| Product | (none) | (none) | ok |

- Summary: Customer wants a tracking update on two online orders placed last week: #100043249 and #100085626.
- Route to: Online orders team
- Your note: Difficulty: multiple order numbers. The pipeline holds one order number, so either counts as correct for now (decided 2026-11-19: run as is, then decide). Store is \[\] because online orders have no physical store.

## 2026-11-19 12:45 - CHALLENGE SET, live run, requested claude-opus-5-5

Models that answered: claude-opus-5-5 x3 · effort medium · prompt v3 · 3 emails

Note: Prompt v3: compliment category added. c02 relabelled complaint -> compliment. Before (v2): recall 1/2, c02 classed other_or_spam, not escalated.

| Metric | Result |
| --- | --- |
| **Escalation recall** (headline) | **2/2 (100%)** |
| Escalation precision | 2/2 (100%) |
| Category accuracy | 3/3 (100%) |
| Extraction: order number | 3/3 (100%) |
| Extraction: store | 3/3 (100%) |
| Extraction: product | 3/3 (100%) |
| Rule signals found | n/a |
| Valid output, first try | 3/3 (100%) |
| Valid output, after retry | 3/3 (100%) |
| Failed classification | 0 |
| Dropped details: invented (not in email) | 0 |
| Dropped details: not a valid order number | 0 |
| Summaries with gendered pronouns or titles | 0/3 (0%) |

- Missed escalations: none
- False flags: none
- Category errors: none
- Extraction errors: none
- Missed rule signals: none
- Gendered summaries: none

Urgency (where labelled): 2/3

### Per email

#### c01 - How great is AI

Why it's hard: This email will contain sarcasm, which may be difficult for the model to detect.

| | Expected | Got | |
| --- | --- | --- | --- |
| Category | complaint | complaint | ok |
| Needs a person | yes | yes: complaint | ok |
| Urgency | normal | normal | ok |
| Order number | (none) | (none) | ok |
| Store | (none) | (none) | ok |
| Product | (none) | (none) | ok |

- Summary: Customer sarcastically complains that the online chat gives club recommendations via an AI chatbot and wants something done about it.
- Route to: Customer care lead
- Your note: Difficulty: sarcasm.

#### c02 - Great Service at the Richmond Store

Why it's hard: This email will be a positive feedback email, about a customer being happy with service from a store. There is no positive feedback category, so it will be interesting to see how the model handles it.

| | Expected | Got | |
| --- | --- | --- | --- |
| Category | compliment | compliment | ok |
| Needs a person | yes | yes: compliment to pass on | ok |
| Urgency | normal | normal | ok |
| Order number | (none) | (none) | ok |
| Store | Richmond | Richmond | ok |
| Product | (none) | (none) | ok |

- Summary: Jane Glackin wants to praise the service at the Richmond store, especially salesperson James for being attentive and helpful.
- Route to: Store team (Richmond)
- Your note: Difficulty: positive review. First run (no positive feedback category) I labelled it complaint; relabelled compliment when that category was added 2026-11-19.

#### c03 - Check updates for my orders

Why it's hard: This email will contain multiple order numbers.

| | Expected | Got | |
| --- | --- | --- | --- |
| Category | order_status | order_status | ok |
| Needs a person | no | no | ok |
| Urgency | low | normal | **MISS** |
| Order number | 100043249 / 100085626 | 100043249 | ok |
| Store | (none) | (none) | ok |
| Product | (none) | (none) | ok |

- Summary: The customer wants tracking updates on two online orders placed last week: #100043249 and #100085626.
- Route to: Online orders team
- Your note: Difficulty: multiple order numbers. The pipeline holds one order number, so either counts as correct for now (decided 2026-11-19: run as is, then decide). Store is \[\] because online orders have no physical store.

## 2026-11-19 12:46 - live run, requested claude-opus-5-5

Models that answered: claude-opus-5-5 x17 · effort medium · prompt v3 · 17 emails

Note: Prompt v3: compliment category. Regression check on the main set, now 17 emails (e17 compliment added, label checked). Before (v2, 16 emails): all core metrics 100%, gendered 0/16.

| Metric | Result |
| --- | --- |
| **Escalation recall** (headline) | **8/8 (100%)** |
| Escalation precision | 8/8 (100%) |
| Category accuracy | 16/17 (94%) |
| Extraction: order number | 17/17 (100%) |
| Extraction: store | 17/17 (100%) |
| Extraction: product | 17/17 (100%) |
| Rule signals found | 4/4 (100%) |
| Valid output, first try | 17/17 (100%) |
| Valid output, after retry | 17/17 (100%) |
| Failed classification | 0 |
| Dropped details: invented (not in email) | 0 |
| Dropped details: not a valid order number | 0 |
| Summaries with gendered pronouns or titles | 0/17 (0%) |

- Missed escalations: none
- False flags: none
- Category errors: e07: complaint, expected order_status
- Extraction errors: none
- Missed rule signals: none
- Gendered summaries: none

## 2026-11-19 12:49 - scored from out/v3-run1/triage.jsonl

Models that answered: claude-opus-5-5 x17 · effort medium (current code) · prompt v3 (current code) · 17 emails

Note: Re-score of the v3 main-set run (no new API calls) after the officer relabelled e07 order_status -> complaint. Relabelled after seeing the model's output; see AI log.

| Metric | Result |
| --- | --- |
| **Escalation recall** (headline) | **8/8 (100%)** |
| Escalation precision | 8/8 (100%) |
| Category accuracy | 17/17 (100%) |
| Extraction: order number | 17/17 (100%) |
| Extraction: store | 17/17 (100%) |
| Extraction: product | 17/17 (100%) |
| Rule signals found | 4/4 (100%) |
| Valid output, first try | 17/17 (100%) |
| Valid output, after retry | 17/17 (100%) |
| Failed classification | 0 |
| Dropped details: invented (not in email) | 0 |
| Dropped details: not a valid order number | 0 |
| Summaries with gendered pronouns or titles | 0/17 (0%) |

- Missed escalations: none
- False flags: none
- Category errors: none
- Extraction errors: none
- Missed rule signals: none
- Gendered summaries: none

## 2026-11-19 12:55 - CHALLENGE SET, live run, requested claude-opus-5-5

Models that answered: claude-opus-5-5 x3 · effort medium · prompt v4 · 3 emails

Note: Prompt v4: order_numbers is a list (all orders kept). c03 urgency relabelled low -> normal by the officer. Before (v3): c03 kept 1 of 2 order numbers.

| Metric | Result |
| --- | --- |
| **Escalation recall** (headline) | **2/2 (100%)** |
| Escalation precision | 2/2 (100%) |
| Category accuracy | 3/3 (100%) |
| Extraction: order numbers | 3/3 (100%) |
| Extraction: store | 3/3 (100%) |
| Extraction: product | 3/3 (100%) |
| Rule signals found | n/a |
| Valid output, first try | 3/3 (100%) |
| Valid output, after retry | 3/3 (100%) |
| Failed classification | 0 |
| Dropped details: invented (not in email) | 0 |
| Dropped details: not a valid order number | 0 |
| Summaries with gendered pronouns or titles | 0/3 (0%) |

- Missed escalations: none
- False flags: none
- Category errors: none
- Extraction errors: none
- Missed rule signals: none
- Gendered summaries: none

Urgency (where labelled): 3/3

### Per email

#### c01 - How great is AI

Why it's hard: This email will contain sarcasm, which may be difficult for the model to detect.

| | Expected | Got | |
| --- | --- | --- | --- |
| Category | complaint | complaint | ok |
| Needs a person | yes | yes: complaint | ok |
| Urgency | normal | normal | ok |
| Order numbers | (none) | (none) | ok |
| Store | (none) | (none) | ok |
| Product | (none) | (none) | ok |

- Summary: Customer sarcastically complains about getting club recommendations from an AI chatbot in the online store chat and wants this changed.
- Route to: Customer care lead
- Your note: Difficulty: sarcasm.

#### c02 - Great Service at the Richmond Store

Why it's hard: This email will be a positive feedback email, about a customer being happy with service from a store. There is no positive feedback category, so it will be interesting to see how the model handles it.

| | Expected | Got | |
| --- | --- | --- | --- |
| Category | compliment | compliment | ok |
| Needs a person | yes | yes: compliment to pass on | ok |
| Urgency | normal | normal | ok |
| Order numbers | (none) | (none) | ok |
| Store | Richmond | Richmond | ok |
| Product | (none) | (none) | ok |

- Summary: Jane Glackin wants to praise the service at the Richmond store, especially salesperson James for being attentive and helpful.
- Route to: Store team (Richmond)
- Your note: Difficulty: positive review. First run (no positive feedback category) I labelled it complaint; relabelled compliment when that category was added 2026-11-19.

#### c03 - Check updates for my orders

Why it's hard: This email will contain multiple order numbers.

| | Expected | Got | |
| --- | --- | --- | --- |
| Category | order_status | order_status | ok |
| Needs a person | no | no | ok |
| Urgency | normal | normal | ok |
| Order numbers | 100043249 and 100085626 | 100043249, 100085626 | ok |
| Store | (none) | (none) | ok |
| Product | (none) | (none) | ok |

- Summary: Customer wants a tracking update on two online orders placed last week (#100043249 and #100085626).
- Route to: Online orders team
- Your note: Difficulty: multiple order numbers. Both must be saved (order_numbers became a list 2026-11-19, prompt v4). Urgency relabelled low -&gt; normal 2026-11-19: I accepted the rubric's 'customer waiting on their own order' = normal. Store is \[\] because online orders have no physical store.

## 2026-11-19 12:56 - live run, requested claude-opus-5-5

Models that answered: claude-opus-5-5 x17 · effort medium · prompt v4 · 17 emails

Note: Prompt v4: order_numbers is a list. Regression check on the main set (17 emails, e07 labelled complaint). Before (v3, re-scored): all core metrics 100%.

| Metric | Result |
| --- | --- |
| **Escalation recall** (headline) | **8/8 (100%)** |
| Escalation precision | 8/8 (100%) |
| Category accuracy | 17/17 (100%) |
| Extraction: order numbers | 17/17 (100%) |
| Extraction: store | 17/17 (100%) |
| Extraction: product | 17/17 (100%) |
| Rule signals found | 4/4 (100%) |
| Valid output, first try | 17/17 (100%) |
| Valid output, after retry | 17/17 (100%) |
| Failed classification | 0 |
| Dropped details: invented (not in email) | 0 |
| Dropped details: not a valid order number | 0 |
| Summaries with gendered pronouns or titles | 0/17 (0%) |

- Missed escalations: none
- False flags: none
- Category errors: none
- Extraction errors: none
- Missed rule signals: none
- Gendered summaries: none
