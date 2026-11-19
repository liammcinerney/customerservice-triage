# 00 - Ideation

How I chose this project. I brainstormed and compared options with Claude (in chat) before starting the build, then made the final calls myself.

## What I was optimising for

The brief rewards judgement and process over size, so I scored ideas on:

1. Useful to a real team, ideally one I understand
2. Buildable in about 2 hours
3. Easy to demo in a couple of minutes
4. Has a built-in way to show quality (tests, evals, a before and after)
5. Plays to my strengths: data, evaluation, and working with agents

## Options I considered

| Idea | What it would show | Why I didn't pick it |
| --- | --- | --- |
| Mission brief builder (discovery notes to MVP brief) | Grounding, citations, scoping | Strong fit, but judging brief quality is more subjective, and I know the customer care domain better |
| Improve my Gene Triage Assistant's grounding | Before and after eval numbers | Graders would spend time learning a genomics domain instead of looking at my process |
| Reusable agent eval kit | Evaluation discipline | Abstract and harder to demo without a target agent |
| AI cost estimator | Cost and model trade-offs | Closer to a calculator than an AI tool |
| Pilot-readiness checker | Governance thinking | Mostly prompt writing, thin technically |
| Q&A over a document set (RAG) | Retrieval quality | Very common idea, and nothing here needed retrieval |
| Document extractor (forms to JSON) | Structured output | Solid, but less of a story |
| Messy-CSV cleaner with approvals | Data engineering and safe agent design | Good option, but less clear business value in a demo |
| Golf round summary for my strokes-gained app | "Code computes, the model narrates" | Memorable, but harder to frame as work-relevant |
| **Customer email triage** | Structured output, human-in-the-loop, injection handling, evals | **Chosen** |

## Why email triage

- I did this job by hand at Drummond Golf (customer emails, complaints and warranty claims across 53 stores), so I understand the workflow and the edge cases.
- It shows several core AI engineering ideas in a small space: structured output with validation, rules that decide when a person must step in, a check that stops invented details, and prompt-injection handling.
- It has objective metrics. Escalation recall (did every email that needed a person get flagged) is the number that matters most.
- It is easy to understand in seconds: messy inbox in, prioritised queue out.

## Scoping it down to 2 hours

My first plan included drafting replies from a policy document. I cut that, because drafting needs policy grounding and a check that blocks unapproved promises, which is effectively a second feature. The 2-hour version triages, extracts, summarises and flags. Drafting is the planned next step.

Also cut: a real inbox connection, any automatic sending, a vector database, multi-agent orchestration, a web interface and deployment. Reasons are in `01-brief.md`.
