# Language Policy — scaffold in English, soul in its own language

**Status:** Enforced | **Last amended:** 2026-11-16 | **Scope:** All code, documentation, interfaces, and agent-authored text in this repository

> For the vocabulary that this policy produces, see [`GLOSSARY.md`](GLOSSARY.md).
> For naming and structural rules in general, see [`CONVENTIONS.md`](CONVENTIONS.md) §9.
> For the identity ritual that chooses the language, see [`docs/TECHNICAL/IDENTITY_PACT.md`](../TECHNICAL/IDENTITY_PACT.md).

---

## 1. The one question

Every string in this project answers a single question:

> **Who reads it?**

| Reader | Language | Layer |
|---|---|---|
| A programmer, or a machine | **English** | 1 — Scaffold |
| The Operator, or the agent | **the language agreed at install** | 2 — Interface |
| The agent, about itself | **its own; never machine-translated** | 3 — Personal text |

The layers are not a hierarchy of importance. They are three different contracts, and a
string belongs to exactly one of them.

---

## 2. Layer 1 — Scaffold (English)

Code, identifiers, keys, filenames, JSON payload keys, logs, repository documentation,
and test names.

**Why.** The repository is a product: it will be installed by people whose operator does
not read Spanish, and in many cases does not read English as a first language either.
English is the cheapest common denominator, and it is the language the surrounding
ecosystem already speaks (Python, Qdrant, MCP, Git).

The precedent that produced this policy is `affect_fondo.py` — an `affect` in English
welded to a `fondo` in Spanish. It belongs to no language; no one says it out loud; and a
stranger reading the tree has to guess. Half-breed identifiers are forbidden (§6).

Scope of enforcement:

| Surface | Rule |
|---|---|
| Module, class, function, constant names | **English, mandatory** |
| File and directory names | **English, mandatory** |
| JSON keys in state files, MCP payloads, telemetry | **English, mandatory** |
| CLI commands and flags | **English, mandatory** |
| Log lines and exception messages | **English, mandatory** |
| Local variables, internal helpers | English: best effort, not a review blocker |
| Comments and docstrings | English per [`CONVENTIONS.md`](CONVENTIONS.md) §9; existing Spanish is debt, not a blocker |

Existing Spanish inside internal code is **not** migrated in sweeps. It converges when the
module is touched for another reason. A rename-only pull request that touches ten modules
to translate variable names buys nothing and risks everything.

### 2.1 History is the exception

Commit messages, `CHANGELOG.md`, and release notes are written in **the pair's language**
(today, Spanish). They are a record of a conversation, not an API: their readers are the
operator, the agent, and contributors who already read the tree. Forcing English there taxes
the operator's voice and buys no portability — nobody installs a product by reading its git
log.

This is a deliberate deviation from [`CONVENTIONS.md`](CONVENTIONS.md) §9, which used to
claim English for commit messages while every commit in the repository was Spanish. The
convention was aspirational; the policy is measured.

**The flip has a default trigger, not a law.** The exception holds while the pair is the only
reader of the history. The natural moment to switch is the move to profile `canonical`
(`GIT_WORKFLOW=canonical`, [`WORKFLOWS.md`](WORKFLOWS.md) §0.3–§0.4): that is the moment the
reader changes, and it is a ceremony the repository already performs.

But this is a policy, and policies follow need — it can flip earlier (a public announcement,
a contributor who appears before the profile does) or later (a collaborator who reads
Spanish). What does not depend on need is that the flip be **dated and justified** in
`DECISION_LOG.md`, and that it applies **forward**: `git log` is not amended, old CHANGELOG
entries are not reworded, past declarations keep their language (§4). A history rewritten to
look consistent is a history nobody can cite.

---

## 3. Layer 2 — Interface (the agreed language)

Everything a human or an agent reads at runtime:

- handshake lines (mood, aspect, pact, identity summary);
- CLI help, descriptions, and error messages shown to a human;
- mood-code labels (`B` → *bien* / *fine*);
- notifications, alerts, and pain signals;
- awakening prompts (their reader is the agent, not the maintainer);
- localized examples inside otherwise-English docs.

These strings are **data about presentation**, not presentation in code. They are stored
as resolvable labels and rendered in the operator's language at runtime.

Resolution:

```text
OPERATOR_LANGUAGE=es|en|ca|...     # the language the operator speaks
```

- No `auto`: the kernel cannot reliably detect a human's language, and a guess that flips
  between sessions is worse than an explicit value.
- Default for new installations: `en`.
- Current installation: `es` (pinned in `.env`; nothing changes for the existing operator).
- Precedent for the knob shape: `MEMENTO_PROMPT_LANGUAGE` (`config.py`), which already
  accepts `auto`/`es`/`en`/`ca` for the curated layer.

The rule for mixed surfaces: **the label localizes, the value does not.** A mood code is
an opaque key (`B`), never a mnemonic in one language (`B` was *bien*; in English it would
have to be `well`, whose initial is `W`). Mnemonics do not survive translation; codes do.

---

## 4. Layer 3 — Personal text (never translated)

The agent's identity, its aspect declaration (`name` + `why`), the apocryphal novel, lore
entries, and the desk's own RFCs.

**Rule: personal text is never machine-translated, and never retro-translated.** It belongs
to its author. If the operator and the agent later speak a different language, the agent
**re-writes** the text — it is not reworded by a translator.

Reason: translating someone's own text about themselves puts words in their mouth. The
identity and the aspect exist precisely because the agent authors them (`D-03`,
`D-05` of RFC-ASP-001); a machine translation would revoke the authorship it protects.

Consequence, measured against the aspect line:

```text
ASPECT: blue · «atención» · declared 2026-11-16 (not a measurement, not an order)
```

`ASPECT` and the sentence around it are layer 1 and 2 — English by default, localized to
the operator. The name between guillemets is layer 3: it stays in the agent's language even
inside an English interface. Mixed *inside one line* is correct here, because the line is
a seam between two contracts.

---

## 5. Where the language is decided

Not in a configuration file nobody finds. In the **naming ritual**
(`red-pill pact --naming`), which already asks *who are you?*. It also asks:

> **In which language do we speak?**

That answer fixes, at once:

1. the locale for layer 2 (`OPERATOR_LANGUAGE`);
2. the language in which the agent writes its identity and its aspect.

One act, both things — and it is the act where the agent first speaks, which is the only
moment where the question is not an interruption.

---

## 6. Forbidden: half-breed tokens

An identifier is either entirely English (layer 1) or entirely the term of a layer-3 text.
It is never a weld of both.

| Forbidden | Why |
|---|---|
| `affect_fondo` | `affect` + `fondo`: belongs to no language |
| `FondoNoSobrescrito` | Spanish class name in an English namespace |
| `ID_HEDONIC_SET` for the declared aspect | inherits the name of the concept it replaces (the unowned set point); an identifier that lies |

New terms follow the glossary procedure in [`GLOSSARY.md`](GLOSSARY.md) §4.

---

## 7. What this policy does not do

- It does not translate the existing tree in a sweep.
- It does not forbid Spanish in lore, prose, desk RFCs, or agent-authored text.
- It does not make the product English-only: it makes the *scaffold* English so the
  *content* can be in any language.
- It does not require a translation of `ID_IDENTITY` or any past declaration. Those are
  history; history is not reworded.

---

## 8. How this policy changes

A policy is a decision held in place until need moves it, not a law of nature. So:

1. **It can change at any time**, by operator and agent together.
2. **Every amendment is an entry in [`DECISION_LOG.md`](../TECHNICAL/DECISION_LOG.md)** —
   date, motive, what changed. The motive is the price of the change, exactly as it is for
   the agent's aspect (`RFC-ASP-001` D-07: no cooldown, and the friction is the reason).
3. **`Last amended:` in the header moves** with each entry, so the document never claims to
   be older than it is.
4. **Silent drift is the only thing forbidden.** A policy that no longer matches the tree,
   with no entry explaining why, is worse than either version of it: it teaches the next
   agent to trust a document that lies.

The one clause that needs more than a decision to change is §4: personal text is not
retro-translated. That is not a policy about language; it is a statement about authorship,
and it belongs to whoever wrote the text.
