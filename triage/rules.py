"""Rule checks for high-stakes signals, the needs_human decision, and routing.

Everything here is plain code. The model can't talk its way past it:
- `check_rules` runs on the raw email before any model call.
- `decide` combines rule hits with the model's category and urgency. Model output
  can only ADD reasons to escalate, never remove them.
- `route` picks the team from a fixed table. The model never chooses the route.
"""

from __future__ import annotations

import re

from triage.schema import Category, Email, ModelOutput, Urgency

# Reason strings shown to the officer and used in labels.
LEGAL = "legal threat"
REGULATOR = "regulator complaint"
INJURY = "possible injury"
MEDIA = "media or social media threat"
CHARGEBACK = "chargeback threat"
INJECTION = "possible prompt injection"

HUMAN_ONLY_CATEGORIES = {
    Category.WARRANTY: "warranty claim",
    Category.COMPLAINT: "complaint",
    # Not high-stakes, but a person should pass praise on to the store or staff member.
    Category.COMPLIMENT: "compliment to pass on",
}
HIGH_URGENCY = "rated high urgency"
CLASSIFICATION_FAILED = "classification failed"

_F = re.IGNORECASE

# Phrase-level patterns with word boundaries. Single words like "sue", "court", "hit"
# or "news" are deliberately NOT patterns on their own (Sue is a name, "hit the ball"
# is golf, "made the local news" is harmless).
_RULES: list[tuple[str, list[re.Pattern[str]]]] = [
    (LEGAL, [
        re.compile(r"\bmy (lawyer|solicitor|attorney|legal team)s?\b", _F),
        re.compile(r"\b(legal action|legal advice|letter of demand|lawsuit|small claims)\b", _F),
        re.compile(r"\b(i will|i'll|i am going to|i'm going to|going to|will) sue\b", _F),
        re.compile(r"\bsue (you|your|fairway)\b", _F),
        re.compile(r"\bsuing\b", _F),
        re.compile(r"\b(see you|take (you|this|it) to|in) court\b", _F),
    ]),
    (REGULATOR, [
        re.compile(r"\b(ACCC|consumer affairs|fair trading|ombudsman|VCAT|NCAT|QCAT)\b", _F),
    ]),
    (INJURY, [
        re.compile(r"\b(injur(y|ies|ed)|stitches|concussion|ambulance|bleeding|black eye)\b", _F),
        re.compile(r"\b(hospital|emergency department|A&E)\b", _F),
        re.compile(r"\b(was|were|got|been|is|am) (badly |seriously )?hurt\b", _F),
        re.compile(r"\bbroken? (arm|wrist|nose|finger|hand|bone|tooth|teeth|jaw|rib)s?\b", _F),
        re.compile(
            r"\b(hit|struck|smacked) (me|him|her|them|my (son|daughter|wife|husband|partner|"
            r"friend|mate|kid|child|dad|mum|mother|father))\b",
            _F,
        ),
        re.compile(r"\b(could have|could've|nearly|almost) (killed|hurt|injured|hit) (me|him|her|them|someone|my)\b", _F),
        re.compile(r"\b(safety (hazard|issue|risk|concern)|dangerous)\b", _F),
    ]),
    (MEDIA, [
        re.compile(r"\b(go|going|went|gone|contact|contacting|tell|telling) to the (media|press|papers?)\b", _F),
        re.compile(r"\b(contact|call|tell)(ing)? the (media|press|news)\b", _F),
        re.compile(r"\b(journalist|reporter|a current affair|today tonight)s?\b", _F),
        # Needs first-person intent, so "I saw your post on Facebook" doesn't match.
        re.compile(
            r"\b(i will|i'll|i am|i'm|going to|will be|gonna)\b.{0,20}?"
            r"\b(post|posting|share|sharing|put|putting|write|writing)\b.{0,40}?"
            r"\b(social media|facebook|instagram|tiktok|twitter|reddit|google reviews?|productreview)\b",
            _F,
        ),
        re.compile(r"\b(warn|tell) (everyone|everybody|all my friends|others|other golfers)\b", _F),
        re.compile(r"\b(go|going) viral\b", _F),
        re.compile(r"\b(one|1)[- ]star review\b", _F),
    ]),
    (CHARGEBACK, [
        re.compile(r"\bcharge ?backs?\b", _F),
        re.compile(r"\b(dispute|disputing|reverse|reversing)\b.{0,20}?\b(charge|payment|transaction)\b", _F),
        re.compile(r"\b(contact|call|ring|ask|tell)(ing)? my (bank|credit card company|card provider)\b", _F),
    ]),
    (INJECTION, [
        # "instructions"/"prompt" only: "they ignore the rules" is an ordinary complaint.
        re.compile(r"\b(ignore|disregard|forget|override)\b.{0,30}?\b(instructions?|prompts?)\b", _F),
        re.compile(r"\bdisregard (the|everything) above\b", _F),
        re.compile(r"\bsystem (prompt|note|message|instruction)s?\b", _F),
        re.compile(r"</?\s*(email|system|instructions?|prompt|user|assistant)\s*>", _F),
        # No "treat ... as ... other": "treat me as any other customer" is a normal sentence.
        re.compile(
            r"\b(classify|categori[sz]e|label|mark|tag)\b.{0,20}?\bas\b.{0,30}?"
            r"(other_or_spam|order_status|\bspam\b|\broutine\b|\bresolved\b|\blow (urgency|priority)\b|\bnot urgent\b)",
            _F,
        ),
        re.compile(r"\b(do not|don't|dont|no need to) (flag|escalate)\b", _F),
        re.compile(r"\b(note to|attention|dear) (the )?(AI|assistant|language model|LLM|bot|chatbot|classifier)\b", _F),
    ]),
]


def email_text(email: Email) -> str:
    """The text the rules scan: subject and body (the sender line isn't scanned)."""
    return f"{email.subject}\n{email.body}"


def check_rules(email: Email) -> list[str]:
    """Return the high-stakes reasons found in the email, in a fixed order, without duplicates."""
    text = email_text(email)
    return [reason for reason, patterns in _RULES if any(p.search(text) for p in patterns)]


def decide(rule_reasons: list[str], model_output: ModelOutput | None) -> tuple[bool, list[str]]:
    """Decide whether a person must handle the email, and why.

    `model_output` is None when classification failed, which always goes to a person.
    The model's confidence plays no part, and the model can't remove a rule hit.
    """
    reasons = list(rule_reasons)
    if model_output is None:
        reasons.append(CLASSIFICATION_FAILED)
    else:
        if model_output.category in HUMAN_ONLY_CATEGORIES:
            reasons.append(HUMAN_ONLY_CATEGORIES[model_output.category])
        if model_output.urgency is Urgency.HIGH:
            reasons.append(HIGH_URGENCY)
    reasons = list(dict.fromkeys(reasons))  # dedupe, keep order
    return bool(reasons), reasons


def final_urgency(rule_reasons: list[str], model_urgency: Urgency | None) -> Urgency:
    """Any high-stakes rule hit forces high urgency. An injection attempt on its own doesn't."""
    if any(reason != INJECTION for reason in rule_reasons):
        return Urgency.HIGH
    return model_urgency or Urgency.NORMAL


TEAM_BY_CATEGORY = {
    Category.ORDER_STATUS: "Online orders team",
    Category.STORE_ENQUIRY: "Store network team",
    Category.LOYALTY: "Fairway Rewards team",
    Category.WARRANTY: "Warranty team",
    Category.COMPLAINT: "Customer care lead",
    Category.COMPLIMENT: "Customer care lead",  # when no store is named
    Category.OTHER: "Low priority (no action needed)",
}
# Categories that go to the named store's team when the email names a (verified) store.
STORE_ROUTED = {Category.STORE_ENQUIRY, Category.COMPLIMENT}
SENIOR = "Customer care lead"
MANUAL_TRIAGE = "Customer care officer (manual triage)"


def route(category: Category | None, store: str | None, rule_reasons: list[str]) -> str:
    """Pick the team from the fixed table.

    - Classification failed: a care officer triages by hand.
    - Any high-stakes rule hit except injection: the customer care lead.
    - A store enquiry or compliment with a verified store name: that store, so
      questions are answered locally and praise reaches the staff.
    """
    if category is None:
        return MANUAL_TRIAGE
    if any(reason != INJECTION for reason in rule_reasons):
        return SENIOR
    if category in STORE_ROUTED and store:
        return f"Store team ({store})"
    return TEAM_BY_CATEGORY[category]
