# 🛡️ Security Architecture — Overview

> *"Empty your mind. Be formless, shapeless, like water."* — Bruce Lee (1971)

The Red Pill Protocol implements a **Three-Tier Security Model** (Be Water Philosophy) that adapts to the operator's environment instead of imposing rigid barriers.

---

## The Three Tiers

| Tier | Name | Description | Default |
|------|------|-------------|---------|
| **MINIMUM** | The Stream | Zero-config, local-only. Qdrant unauthenticated on localhost. No API keys. | ✅ Default |
| **STANDARD** | The River | Qdrant API key, encrypted `.env`, LUKS-aware. Recommended for multi-agent setups. | — |
| **MAXIMUM** | The Ocean | Full disk encryption, TLS on all connections, signed engrams, network isolation. | — |

Each tier is fully documented. Navigate to the specific area:

---

## Security Documentation Map

### Philosophy & Model
| Document | Focus |
|----------|-------|
| [Be Water Security](BE_WATER_SECURITY.md) | The three-tier sovereignty model — philosophy and implementation |
| [Threat Model](THREAT_MODEL.md) | Scope, assumptions, and threat surface analysis |

### Operational Security
| Document | Focus |
|----------|-------|
| [Security Strategy](SECURITY_STRATEGY.md) | API key management and identity recovery protocol |
| [Key Recovery](ANTIGRAVITY_KEY_RECOVERY.md) | Antigravity key recovery procedures |
| [Prompt Injection](PROMPT_INJECTION_MECANISM.md) | How prompt injection is detected and mitigated |

### Exceptions & Acknowledgements
| Document | Focus |
|----------|-------|
| [WONTFIX](WONTFIX.md) | Known security exceptions formally acknowledged and accepted |

---

> *"Sovereignty is not isolation. It is the freedom to choose what you share."*
