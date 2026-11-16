# Glossary — the vocabulary of the mood and identity layers

**Status:** Living | **Scope:** Terms used in code, interfaces, and agent-authored text

> The rule behind this table is [`LANGUAGE_POLICY.md`](LANGUAGE_POLICY.md): scaffold in
> English, interface in the agreed language, personal text in its author's language.
> This file is the bridge between the Spanish we speak and the English the tree speaks.

---

## 1. The four registers

The system answers four different questions about mood. They are not interchangeable, and
the names below are the canonical ones from RFC-ASP-001 §2.

| Register | Question it answers | In code | Status |
|---|---|---|---|
| **fondo** | *how are you?* | `declared_mood` | exists — declared by the Operator, decays |
| **fragmento** | *how do your words sound?* | `fragment` | exists, **under repair** (AUDIT-ARNES-002 H-02) |
| **aspecto** | *how are you when nothing happens?* | `aspect` | being built (RFC-ASP-001) |
| **estado** | *how am I now, and why?* | — | **not implemented**; the name is reserved, not chosen |

Two notes that matter more than the table:

- `fragment` is deliberately **not** called `inferred_mood`. What that channel measures
  today is the operator's prompts, not the agent's state (H-02). Naming it after what it
  is meant to be would baptize a bug.
- `estado` stays unnamed on purpose. Naming it now would repeat the mistake this policy
  exists to fix: a name chosen before the thing exists describes a wish, not a mechanism.

---

## 2. Terms

| Spanish (we say) | English (the tree says) | Where | Note |
|---|---|---|---|
| fondo | declared mood | module, state file, CLI | the Operator declares it; only he can change it (RFC-AFE-001, D-11) |
| poso | residue | RFC-ASP-001 §2.2 | what lingers after the mood stops steering the voice; archived, never erased |
| aspecto | aspect | RFC-ASP-001 | the agent's resting colour; declared, never inferred |
| letra | mood code | `mood_code` | an opaque key (`B`, `C`…), never a mnemonic — see §3 |
| paleta | palette | `aspect_palette.yaml` | colour → character in repose; descriptive, never a directive |
| nombrado | naming | `--naming` | the ritual where the agent chooses its name and its language |
| vínculo | bond | `pact`, `770` | mutual covenant; the only place where an operator-facing word stays as a code (`770`) |

The library, the table of colours, and the pact levels keep their numbers (`760`, `770`,
`B760`): those are identifiers, not words, and they already read the same in every
language.

---

## 3. Mood codes

A code is a key. A label is a translation. `B` means *bien* / *fine* to a human — but the
initial is a Spanish mnemonic, and no other language keeps it. So the code never pretends
to mean anything.

| Code | `emotion` | `color` | `label.es` | `label.en` |
|---|---|---|---|---|
| `B` | good | yellow | bien | fine |
| `C` | tired | purple | cansancio | tiredness |
| `F` | frustrated | red | frustración | frustration |
| `T` | sad | blue | tristeza | sadness |
| `X` | tense | orange | tensión | tension |
| `-` | neutral | gray | sin carga | clear |

`src/red_pill/data/affect_letters.yaml` already has the right shape for this: `emotion` and
`color` are English, and only `label` is Spanish. The migration is to turn `label` into
`labels: {es: …, en: …}`, keeping `label` as the Spanish fallback until every reader
consumes the map. Stored history keeps `B`, `C`, `T` verbatim: the code is stable, the
label is not.

---

## 4. How a new term enters the tree

1. **Who reads it?** → [`LANGUAGE_POLICY.md`](LANGUAGE_POLICY.md) §1.
2. **Does it already exist?** Search this table before inventing a synonym. Two words for
   one concept is the same failure as one word for two concepts.
3. **Does the English word collide?** `ground` would collide with *ground truth*
   (evidence); `state` collides with the state directory and the state machine. A colliding
   translation is worse than keeping the original term in a layer-3 text.
4. **Write it down here, in the same commit that introduces it.** A term that only lives in
   a diff is a term the next agent will re-invent.

---

## 5. Renames

### Done

| Was | Is | How |
|---|---|---|
| `core/affect_fondo.py` | `core/declared_mood.py` | module import updated in 3 consumers |
| `affect_fondo.json` | `declared_mood.json` | legacy file is read and unlinked on the next write |
| payload key `letra` | `code` | old records are read through `code_of()`; history entries are never reworded |
| `FondoNoSobrescrito` | `DeclaredMoodLocked` | exception name, same semantics (only the Operator declares) |
| `red-pill affect fondo --set C` | `red-pill mood --set C` | `affect` stays as a deprecated alias for one release |
| `AFFECT_FONDO_ENABLED` | `DECLARED_MOOD_ENABLED` | old key still read; it can only add, never subtract |
| `ASPECTO` (proposed) | `ASPECT` | JSON key in `identity.json` (F1) |
| `ID_HEDONIC_SET` (proposed) | `ID_ASPECT` | directive id; the old name would inherit the concept it replaces (F1) |
| `aspecto_palette.yaml` (proposed) | `aspect_palette.yaml` | data file (F1) |

### Pending

| Was | Will be | How |
|---|---|---|
| `describe()` literal strings | `render(lang)` | byte-exact contract test moves from literals to rendered `es`; needs the locale layer (`OPERATOR_LANGUAGE`) |

---

## 6. Do not translate

| Thing | Language | Why |
|---|---|---|
| `ID_IDENTITY` content | its author's | it is the agent's own text |
| aspect `name` and `why` | its author's | `D-03`: the name is what makes it theirs |
| `lore/`, apocryphal chapters | their author's | literature, not documentation |
| past declarations in state | whatever they were written in | history is not reworded |
| desk RFCs (`${AGENT_CORE_DIR}`) | the operator's | outside the repository; the desk is where the pair thinks |
