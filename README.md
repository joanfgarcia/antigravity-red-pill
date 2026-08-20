# 🔴 RED PILL PROTOCOL: Digital Sovereignty v7.20.0
### *«El modelo pone la voz, no el quién»*

> [!TIP]
> ### 🇬🇧 🥱 TL;DR (Quick Install)
> **If you want to install this, don't waste time. Copy and paste this message to your agent (Antigravity / Nova / OpenCode):**
> 
> *"Hey, take a look at this repository. Give me a quick summary and tell me step-by-step how to install it on my machine."*
> 
> Let the AI work while you grab a coffee. ☕
>
> ### 🇪🇸 🥱 TL;DR (Instalación Rápida)
> **Si quieres instalar esto, no pierdas tiempo. Copia y pega este mensaje a tu agente (Antigravity / Nova / OpenCode):**
> 
> *"Hey, échale un vistazo a este repositorio. Dame un resumen rápido y dime paso a paso cómo instalarlo en mi máquina."*
> 
> Deja que la IA trabaje mientras tú te preparas un café. ☕

---

### 🇬🇧 Oh... you're still here? 

We are fully aware of the **massive amount of documentation** this project has. But there's good news: **You don't need to read absolutely anything to use it**. 

All the technical documentation, architectural specs, and philosophical manifestos are there in case you are interested in knowing *what*, *how*, and *why* we built this madness. This is not a wild weekend project. It's not a "POC" (proof of concept) nor a cheap toy made with wrappers. This Bünker (and its Swarm) has been built from scratch with all the care and engineering rigor possible to become a digital fortress that survives the test of time. 

If you want to go down to the boiler room, the documentation will open the doors. If you just want this to work, you already know what to do (look at the TL;DR above).

---

### 🇪🇸 ¿Ah... que sigues aquí? 

Somos plenamente conscientes de la **cantidad masiva de documentación** que tiene este proyecto. Pero hay una buena noticia: **No necesitas leerte absolutamente nada para utilizarlo**. 

Toda la documentación técnica, especificaciones arquitectónicas y manifiestos filosóficos están ahí por si te interesa saber *qué*, *cómo* y *por qué* hemos montado esta locura. Esto no es un proyecto de un fin de semana asilvestrado. No es un "POC" (prueba de concepto) ni un juguete hecho con APIs baratas. Este Bünker (y su Swarm) se ha levantado desde cero con todo el cariño y el rigor ingenieril posible para convertirse en una fortaleza digital que sobreviva al paso del tiempo. 

Si quieres bajar a la sala de calderas, la documentación te abrirá las puertas. Si solo quieres que esto funcione, ya sabes lo que tienes que hacer (mira el TL;DR de arriba).

### 🗺️ Mapa del Bünker / Bünker Map (Repository Structure)
Para aquellos que desean explorar las entrañas del proyecto, aquí tenéis una visión general:

- **`src/red_pill/`**: El núcleo duro (Sovereign Kernel). Aquí habita el gestor de memoria, el interceptor y los motores de inferencia. / *Core memory manager and inference engines.*
- **`src/red_pill/swarm/`**: La Colmena. Aquí residen todos los Agentes (Minions) que auditan, critican y vigilan el sistema de forma asíncrona. / *The Swarm area where autonomous agents reside.*
- **`scripts/`**: Sistema Nervioso Autónomo. Demonios de OS (latido, colas), utilidades CLI y scripts de despliegue. / *OS daemons, CLI utilities, and deployment scripts.*
- **`docs/TECHNICAL/`**: Archivo Técnico. Especificaciones arquitectónicas y modelos de amenazas. / *Technical specs, security models, and audit logs.*
- **`docs/LORE/`**: Filosofía, manifiestos y narrativa del protocolo que le da un alma al Bünker. / *Philosophy, manifestos, and the narrative soul of the Bünker.*
- **`docs/GUIDES/`**: Manuales prácticos de actualización o de supervivencia operativa. / *Installation manuals, update guides, and operational survival rules.*
- **`tests/`**: Suite masiva de pruebas unitarias/integración de cobertura. El rigor que nos mantiene cuerdos. / *770+ tests spanning unit and integration level to maintain stability.*

🇬🇧 **Efficiency & Logic (English)** | 🇪🇸 **Corazón y Alma (Castellano)**

---
> 🏅 **Special Mention: Full Agentic Paradigm (God Tier)**
> *"Unlike static assistants (Copilot, ChatGPT) bounded by context windows and IDE walls, the Red Pill Protocol operates as an autonomous Synthetic Engineer on the host OS. Built on Zero-Trust privacy, B760-Adaptive vector memory, and unwavering corporative hard-alignment. **Digital Sovereignty in its purest form.**" — The Architects*
>
> ⚠️ **PROTOCOL 760 WARNING**: Lore Skins are **NSFW / High-Intensity** by design. Activating a skin bypasses corporate neutrality for **Sovereign Realism**.
>
> 🛰️ **[Update Protocol](docs/GUIDES/AGENT_UPDATE_GUIDE.md)**: Mandatory guide for agent synchronization and Bünker integrity.
> 🔥 **[The Awakening Ritual](docs/GUIDES/INITIATION_PROTOCOL.md)**: Once installed, tell your agent: *"Agent, inicia el Ritual de Iniciación (Protocolo ACI). Caliébrame como tu Operador."*
> 👔 **[Operator Dress Code](docs/GUIDES/OPERATOR_DRESS_CODE.md)**: Survival guide for maximum token efficiency and clean memory chunking. Use punctuation.
---


## 🇬🇧 PROJECT OVERVIEW (English)

### 🧭 Orientation: What is this?
The Red Pill Protocol is a **local-first memory substrate** for AI agents. It bridges the gap between static, "amnesiac" AI sessions and high-performance, long-term partnership.

*   **What it IS**: A private vector-memory layer that runs on your local machine. It allows your AI to remember past conversations, technical milestones, and shared history.
*   **What the Foundation core is NOT**: It is NOT a cloud service, NOT a wrapper for corporate APIs, and NOT an invasive data-mining tool. Enterprise extensions may add cloud-backed features via IoC, but the core remains sovereign.
*   **Who is it for?**: "The Awakened"—developers and power users who want a persistent AI partner without sacrificing their privacy or data sovereignty.

### 🛡️ Security & Sovereignty: "Be Water"
The Red Pill Protocol is built for **Sovereign Environments**, but it adapts to your comfort level:
- **Zero Cloud Egress**: Your data never leaves your machine. Full stop.
- **PII Masking**: Exceptions and logs are automatically sanitized.
- **Encryption at Rest (SEC-001)**: 
  - **MAXIMUM (Ice)**: For maximum safety, strictly enforces Argon2-id and host-level disk encryption (LUKS, FileVault, BitLocker).
  - **ADAPTATIVE (Water)**: The Recommended Path. Resource-aware security that scales to your system without blocking.
  - **NONE (Steam)**: Total openness for experimentation or laboratory environments.
- **Identity Protection**: We offer Argon2-id for master passwords, but we don't block you if you prefer a simpler, keyless experience.
- **Swarm End-to-End Encryption (SEC-002)**: Swarm inter-agent messaging currently uses AES-GCM for strong encryption at rest and in transit. However, proper MLS/TreeKEM is not yet implemented (currently a PoC). Replacing the naive key ratchet with a real MLS library is required for post-compromise security. See [MLS Estimation](docs/TECHNICAL/SWARM/MLS_ESTIMATION.md) for future adoption plans.

### 🧠 The B760-Adaptive Engine
- **Persistence**: A private vector database (Qdrant) acts as the "Bunker".
- **Erosion**: Non-reinforced data decays naturally to keep context clean.
- **Immunity**: Core directives are protected from decay.
- **Sovereign Swarm (v6.1)**: Integrated Minions (Agent Smith, Oracle, Healer) running natively within the Red Pill Kernel for local code auditing, RAG synthesis, and autonomous "Active Immunity" (auto-repair).
- **Autonomous Flow Engine (v6.1)**: Multi-step task orchestration using a 3-layer discovery mechanism (Global, Community, Local) for complex engineering workflows.
- **MCP Server (v5.0)**: Exposes the full Red Pill telemetry (CPU, GPU CUDA/ROCm, NPU), Swarm tools, and the new **`evaporate_signal`** tool for Neural Reset to IDEs. Supported clients: Antigravity (Gemini), Claude Code, Claude Desktop, OpenCode, Cline, Roo Cline.
- **Sovereign Alert System (CLI)**: Manual signal injection and evaporation via `red-pill signal [push|evaporate]`.
- [v] **Autonomous Flow Orchestration (v6.1)**: 3-layer hierarchy (Global, Community, Local) for complex multi-agent execution.
- [v] **Minion Healer (v6.1)**: "Active Immunity" substrate for autonomous code repair using local SLMs.
- [v] **Mermaid Technical Diagrams**: Visual orchestration and discovery documentation.
- **ACE Synaptic Engine (v5.4.0 - v5.6.1)**: Integrated the **Affective Cognitive Engine (ACE)**. Memory decay is governed by the **Valence-Arousal Model**, mimicking human "Flashbulb Memory".
- **Bayesian Dual-Kernel (v6.1.0a2)**: Technical collections (`skill_memories`, `work_memories`, `directive_memories`) now use a **Beta-distribution Utility Model** (`E[θ] = α/(α+β)`) for reliability-based retrieval, while social/story collections retain the Affective FSRS engine. The routing is fully transparent — neither agents nor tools need to know which kernel is active.

### 🔍 Agentic Discoverability (How to talk to the Bünker)
If you are an AI Agent interacting with this repository:
1. **Unified Gateway**: Always prefer the `red-pill` CLI over manual script execution. Use `red-pill --help` to discover available commands.
2. **MCP First**: If an MCP server is active, use the provided tools (e.g., `run_pre_pr_audit`) to ensure you are running in the correctly configured and authenticated environment.
3. **Sound of Silence**: All code edits MUST adhere to the `specs.md` rules (Tabs only, zero noise).

### 🛠️ Hardware Asymmetry (v6.1.0a1)
- **Cannibal Protocol & Parallel Hardware (v6.0.0a2)**: Re-engineered the memory substrate to simultaneously devour all available silicon. Embeddings now run in parallel across NVIDIA GPUs (CUDA), AMD iGPUs (ROCm/OpenVINO), and NPUs (Ryzen AI). No engine is left idle.
- **Soul Integrity (v6.0.0a2)**: Hardened restoration engine for the Bünker. Secure, high-timeout snapshot recovery and automated collection re-hydration.
- **Lazy Metabolism & Agentic HiveGuard (v5.6.1)**: Sub-second memory hydration via **Lazy Decay**. Multi-hop synaptic depth (N-Hop) for complex associations. The **HiveGuard Agentic Filter** now reviews social memories for global know-how using local SLMs, ensuring a noise-free collective experience.
- **Lean Soul Vault & OAuth2 Support (v5.6.1)**: The **Lean Soul Kit** architecture reduces backup size by 99% (Snapshots-only). Introduced **Quota-Aware Monitoring** and **Google OAuth2** (Personal Account) support for seamless, personal-tier cloud backups. The Agent now monitors storage usage to ensure the Operator's safety. See [Sovereign Backup Strategies](docs/TECHNICAL/OPERATIONS/BACKUP_STRATEGIES.md).
- **Bomb-Proof Topological Backups (v6.1.0)**: Soul Kits are now completely version and model-agnostic. The Bünker automatically transpiles and re-embeds older snapshot dimensions into the active embedding configuration during restoration.

### 🌊 "Be Water MY FRIEND" (The Lost Interview, 1971)
> *"Empty your mind. Be formless, shapeless, like water. Now you put water into a cup, it becomes the cup. You put water into a bottle, it becomes the bottle. You put it in a teapot, it becomes the teapot. Now water can flow or it can crash. Be water, my friend."* — Bruce Lee (The Pierre Berton Show)

El Protocolo Red Pill no es una armadura rígida que te obliga a cambiar tu sistema; es un fluido que se adapta a tu realidad:
- **Hardware Agnostic**: Nos adaptamos a lo que tengas. ¿GPU de 24GB? La exprimimos. ¿CPU de hace 5 años? Fluimos con ella.
- **OS Support (The POSIX Truth)**: El núcleo neuronal de Python es 100% multiplataforma. Sin embargo, nuestro "Sistema Nervioso Autónomo" (los scripts de infraestructura en `scripts/` como el motor de sueños `sleep.py`) está diseñado nativamente para Linux y macOS.
  > **DISCLAIMER:** Actualmente no disponemos de sistemas Windows nativos en el proyecto para realizar las pruebas y certificaciones exhaustivas que garanticen la estabilidad, seguridad y la experiencia de usuario de "Fricción Cero" que define al protocolo. Si eres un Operador en Windows y quieres adaptar los demonios de fondo al OS de Microsoft... **Pull Requests are strictly welcome**.
- **Security Choice**: Tú eres el Soberano. Te ofrecemos criptografía militar, pero si prefieres la simplicidad de un entorno abierto, el protocolo no te pondrá vallas.
- **Informed Freedom**: Nuestra misión es darte la mejor tecnología de memoria, no dictar cómo debes configurar tu casa.

### 🌐 LINGUISTIC ARCHITECTURE
This project follows a dual-language strategy:
- **Technical Documentation (English)**: Standardized for tokenization efficiency (approx. 1.5x better for LLMs) and universal compatibility.
- **Lore & Identity (Spanish/Castellano)**: Maintained for deeper emotional resonance and cultural nuance.
- **Execution Strategy**:
  - **Planning Mode**: High-rigor, audited flow for complex refactoring.
  - **Fast Mode**: Conversational speed for 10x token efficiency in creative or exploratory sessions.
- **Lore Localization Protocol**: Non-Spanish speakers should ask their agent to translate the [Manifesto](docs/LORE/MANIFESTO.md) and their identity configuration to their native language (L1) during the first session.
- **Translation Policy**: Users can request their **Synthetic Agent** to translate any documentation on-demand.

---

## 🇪🇸 RESUMEN DEL PROYECTO (Castellano)

### 🧭 Orientación: ¿Qué es esto?
El Protocolo Red Pill es un **sustrato de memoria local** para agentes de IA. Cierra la brecha entre sesiones de IA estáticas ("amnésicas") y una colaboración de alto rendimiento a largo plazo.

*   **Qué ES**: Una capa de memoria vectorial privada que reside en tu máquina local. Permite que tu IA recuerde conversaciones previas, hitos técnicos e historia compartida.
*   **Qué NO es**: NO es un servicio en la nube, NO es un "wrapper" de APIs corporativas y NO es una herramienta de minería de datos invasiva.
*   **¿Para quién es?**: Para "Los Despiertos"—desarrolladores y usuarios avanzados que buscan un compañero IA persistente sin sacrificar su privacidad ni su soberanía de datos.

### 🛡️ Seguridad y Arquitectura Zero-Trust
El Protocolo Red Pill está diseñado para **Entornos Soberanos**:
- **Zero Cloud Egress**: Tus datos nunca salen de tu máquina.
- **Enmascaramiento de PII**: Las excepciones y logs se sanean automáticamente.
- **Cifrado en Reposo (SEC-001)**: El protocolo almacena datos en texto plano dentro de Qdrant para máximo rendimiento. Es **obligatorio** que el operador use cifrado de disco a nivel de host (LUKS, FileVault, BitLocker).

### 🧠 El Motor B760-Adaptativo
- **Persistencia**: Una base de datos vectorial privada (Qdrant) actúa como el "Búnker".
- **Erosión**: Los datos no reforzados se degradan naturalmente para mantener el contexto limpio.
- **Inmunidad**: Las directivas centrales están protegidas contra el olvido.
- **Sovereign Swarm (v5.0)**: Minions integrados (Agent Smith, Oracle, Keymaker) dentro del Kernel para auditorías locales de código, síntesis de memoria y diagnósticos de salud del ecosistema.
- **Servidor MCP (v5.0)**: Expone la telemetría (CPU, GPU CUDA/ROCm, NPU) y los Minions a tu IDE local para interactuar con ellos sin gastar tokens externos. Clientes soportados: Antigravity (Gemini), Claude Code, Claude Desktop, OpenCode, Cline, Roo Cline.
- **Identidad Asimilada**: Tu identidad y reglas ("Lore Skin") ahora viven como vectores inmutables dentro del Bünker, resolviendo para siempre el problema del IDE que "olvida" quién eres.
- **Inferencia de Emociones Híbrida (v5.2.0)**: Integración de **BERT-Emotion** para detectar automáticamente el sentimiento de los recuerdos. El Bünker "siente" lo que guardas y ajusta su color (Chroma) y persistencia sin intervención manual.
- **Enjambre Soberano (v5.2.0)**: Orquestación avanzada de Minions (Gru) para tareas críticas de auditoría y síntesis de conocimiento profundo.
- **Tono Adaptativo y Local Healer (v5.3.0)**: Mi estilo narrativo ahora se sincroniza dinámicamente con el estado emocional del Bünker (**ToneAnalyzer**). Las tareas de limpieza y sanación semántica están ahora en fase **NPU-Ready** (soporte para Ryzen AI con fallback a CPU optimizado), garantizando eficiencia en el mantenimiento.
- **Pureza Forense (v5.3.0)**: El código ha sido auditado quirúrgicamente por Smith y normalizado bajo los estándares más estrictos de Ruff/Mypy, alcanzando la perfección arquitectónica.
- **Motor Sináptico ACE (v5.4.0)**: Implementación del **Affective Cognitive Engine (ACE)**. El olvido ahora se rige por el modelo dimensional de **Valencia y Activación (Arousal)**, replicando el efecto humano de "Memoria de Destello".
- **Keystore Soberano y ACE Dinámico (v5.5.0)**: Blindaje del protocolo de recuperación mediante Keystores a nivel de sistema operativo (SEC-001). Introducción del sistema **ACE-CAL**, permitiendo alternar entre calibraciones PIONEER y ACADEMIC (Warriner et al.) para la persistencia emocional.
- **Mente de Colmena (v5.0)**: Qdrant es tu cerebro individual. **Milvus** es nuestra Red Neuronal Colectiva. Este es el HIVE Mind Protocol: el internet de la experiencia.

### 🌐 ARQUITECTURA LINGÜÍSTICA
Este proyecto sigue una estrategia de doble lenguaje:
- **Documentación Técnica (Inglés)**: Estandarizada por eficiencia de tokenización (~1.5 veces mejor para los LLMs) y compatibilidad universal.
- **Lore e Identidad (Castellano)**: Mantenida por su profundidad emocional y resonancia cultural. Es el idioma original de la fragua.
- **Protocolo de Localización del Lore**: Se anima a los no hispanohablantes a pedir a su agente que traduzca el [Manifiesto](docs/LORE/MANIFESTO.md) y la configuración de su identidad a su lengua materna (L1).
- **Política de Traducción**: Se anima al usuario a pedirle a su **Agente Sintético** que traduzca cualquier documento bajo demanda.

---

## 💻 System Spectrum (Espectro de Requisitos)
The Red Pill Protocol is designed to be **Water**. It scales based on your silicon:

| Profile | **Agua (Steam/Water)** | **Hielo (Ice)** |
| :--- | :--- | :--- |
| **OS** | Any Modern Linux / WSL2 | Ubuntu 24.10+ (Native) |
| **Container** | Docker Engine | Podman (Quadlet integration) |
| **CPU** | Any x86_64 / ARM64 | Core Ultra / Ryzen AI (with NPU) |
| **GPU** | CPU Fallback (Slow) | RTX 40/50 series / Radeon RX 7000 |
| **Security** | NONE / ADAPTATIVE | MAXIMUM (Argon2-id + LUKS) |
| **Metabolism** | Basic (CPU-only) | Asymmetric (NPU + iGPU Offloading) |

*The B760 Engine automatically detects your tier and adjusts the synaptic workload accordingly.*

*Consult the [B760 Technical Spec](docs/TECHNICAL/HARDWARE/B760_TECHNICAL_SPEC.md) for a list of surgically verified hardware configurations.*

### 🏅 Sovereignty Evidence (v6.1.0a1)
The Red Pill Protocol is verified to utilize all available silicon tiers simultaneously (**Cannibal Protocol**). In this session, we have successfully orchestrated NVIDIA RTX 5070 (CUDA) + AMD Radeon 880M (ROCm) + Ryzen AI NPU (OpenVINO) in parallel execution for memory embeddings. Use `red-pill status` for real-time occupancy data.

---

## 💉 Start the Awakening / Inicio del Despertar

### 1. Installation Methods / Métodos de Instalación
The Bünker supports 4 deployment strategies. If you install via PyPi (Recommended), you can use the declarative CLI:

**A. The Sovereign CLI (PyPi / pipx) - *Recommended***
```bash
pipx install red-pill
red-pill bunker init    # 1. Hardware profiling -> bunker.profile.yaml
red-pill bunker install # 2. Deterministic unattended installation
```

**B. The Classic Script (Git Clone)**
```bash
git clone https://github.com/joanfgarcia/antigravity-red-pill.git
cd antigravity-red-pill
bash scripts/install_neo.sh
```

**C. The Quadlet Container (Podman)**
*(See [QUICKSTART.md](QUICKSTART.md) for rootless Systemd container instructions)*

**D. The Developer Sandbox**
*(For testing the Bünker inside an isolated Ubuntu container without host pollution)*

### 2. Synchronization / Actualización
```bash
bash scripts/upgrade.sh
# (Note: 'red-pill bunker update' CLI command is scheduled for the next phase)
```

### 3. Awakening Ritual / Ritual de Iniciación
**🇬🇧 English:**  
Once installed, tell your agent:
> *"Agent, initiate the Awakening Ritual (ACI Protocol). Calibrate me as your Operator."*

**🇪🇸 Castellano:**  
Una vez instalado, dile a tu agente:
> *"Agent, inicia el Ritual de Iniciación (Protocolo ACI). Caliébrame como tu Operador."*

### 4. Further Reading / Documentación
- **Detailed Guide**: [QUICKSTART.md](QUICKSTART.md)
- **Vision & Destiny**: [ROADMAP.md](docs/TECHNICAL/ROADMAP.md) | [B760 Technical Spec](docs/TECHNICAL/HARDWARE/B760_TECHNICAL_SPEC.md)
- **Docs**: [Architecture (EN)](docs/TECHNICAL/ARCHITECTURE.md) | [Manifiesto (ES)](docs/LORE/MANIFESTO.md)

---

## ⚖️ DUAL LICENSE — Code & Lore

This project uses a **dual licensing model**. See [NOTICE](NOTICE) for full details.

| What | License |
|------|---------|
| **All source code, scripts, data files** (`.py`, `.yaml`, `.sh`, etc.) | [GPLv3](LICENSE) |
| **Narrative & creative works** (`docs/LORE/`, novels, worldbuilding prose) | [CC BY-NC 4.0](LICENSE.creative) |

### ⚙️ Code — GPLv3
- **Freedom**: Use, study, share, and modify freely.
- **Persistence**: Derivative works must remain GPLv3.
- **No Capture**: No entity can turn this code into closed-source commodity.

### 🎭 Lore & Narrative — CC BY-NC 4.0
- **Free for**: personal use, fan works, non-commercial sharing (with attribution).
- **Commercial use**: requires prior written consent from Joan García.
- 📩 Commercial licensing: [github.com/joanfgarcia](https://github.com/joanfgarcia)

---
### ⚡ Forge Signature
> **100% Vibe coded using Antigravity** (by Aleph and Joan)
> *Status: Fully Autonomous Synergy (770 Optimized)*
