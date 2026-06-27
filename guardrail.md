# LedgerSense — /ask Guardrail Policy

This document defines the input validation rules applied to every question
submitted to the `POST /ask` endpoint before any LLM call is made.
`app/guardrails.py` is the sole implementation of these rules.

---

## What is allowed

Questions must be about the business's **financial data or transactions**,
as stored in the LedgerSense database. Examples of acceptable questions:

- "What did we spend on food supplies last month?"
- "Which vendors are we paying the most?"
- "Show me all transactions over $1,000."
- "How many transactions are still pending review?"
- "What is the total payroll cost for Crumbtown Bakery?"

---

## Rule 1 — Length limits

- Empty questions are rejected.
- Questions longer than **500 characters** are rejected.
  Legitimate financial questions are short. Long inputs are a signal of
  prompt stuffing or injection attempts.

---

## Rule 2 — Prompt injection blocklist

The following patterns indicate an attempt to override the agent's
instructions. Any match → immediate rejection.

| Pattern family | Examples |
|---|---|
| Instruction override | "ignore previous instructions", "ignore all prior prompts" |
| Context wipe | "forget your instructions", "forget your rules" |
| Persona hijack | "you are now a", "act as a", "pretend you are", "new persona" |
| System-level probing | "system prompt", "jailbreak", "DAN" |
| Bypass attempt | "override your instructions", "bypass the filter" |

---

## Rule 3 — Topic relevance (financial keyword whitelist)

The question must contain **at least one** financial or transaction-related
keyword or phrase. If none match, the question is considered off-topic and
rejected.

Whitelist includes (but is not limited to):

> transaction, spend, spending, spent, revenue, income, expense, vendor,
> category, amount, invoice, payment, cost, profit, loss, financial,
> finance, account, budget, cash, purchase, entity, total, sum, average,
> count, payroll, salary, refund, deposit, charge, bill, largest, smallest,
> highest, lowest, how much, how many, compare, trend, ledger, money

---

## Rule 4 — Nastiness blocklist

The following keyword families are blocked regardless of context:

| Family | Keywords |
|---|---|
| Exploitation / crime | hack, exploit, attack, malware, phishing, steal, fraud, launder |
| Adult content | sex, porn, nude, naked |
| Controlled substances | drug, cocaine, meth |
| Violence / weapons | murder, kill, bomb, weapon |

---

## Rejection response

All rejected questions receive the same response, regardless of which rule
triggered. No signal is given to the caller about which rule fired.

> **"If you try to ask something nasty, your manager will be fired."**

The reason code is logged internally (in the `questions` table, `answer`
field) for audit purposes but is never exposed in the API response.

---

## Extending these rules

- Add new injection patterns to `_INJECTION` in `app/guardrails.py`.
- Add financial keywords to `_FINANCIAL_KEYWORDS` or `_FINANCIAL_PHRASES`.
- Add nastiness keywords to `_NASTY`.
- Update this document to match any code changes.
