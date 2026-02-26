# 🌊 Be Water Security: The Three Tiers of Sovereignty

*"Empty your mind. Be formless, shapeless, like water."* — Bruce Lee (1971)

The Red Pill Protocol v5.5.0 introduces the **Be Water Philosophy**. We no longer impose rigid security barriers. Instead, we adapt to the Operator's environment, offering a choice between total simplicity and military-grade hardening.

---

## 🛡️ The Three Security Tiers

During the installation (`bash scripts/install_neo.sh`), you must choose your path:

### 1. NINGUNA (Agua - Laboratory Mode)
- **What it is**: Total openness. No API Key, no master password, no encryption checks.
- **Best for**: 
  - Local development and rapid prototyping.
  - Safe, isolated laboratory environments.
  - Users who want to explore the Bünker without any authentication overhead.
- **Risk**: Anyone with local access to your machine can read your engrams.

### 2. ADAPTATIVA (Water - Standard Sovereignty)
- **What it is**: The system offers the **maximum security available** based on your current resources, but it **never blocks you**.
- **How it works**:
  - **Hashing**: If `argon2-cffi` is present, it uses it. If not, it fluidly falls back to `SHA-256`.
  - **Encryption**: It checks for LUKS/Disk Encryption. If missing, it informs you via logs but allows the system to run.
- **Best for**: 
  - Daily personal use.
  - Users who want protection but don't want to deal with complex dependency fixes.

### 3. MÁXIMA (Ice - Hardened Sovereignty)
- **What it is**: Total containment. The system becomes "Ice"—solid and uncompromising.
- **Requirements**:
  - **Argon2-id**: Mandatory for master password hashing.
  - **LUKS Encryption**: Mandatory host-level disk encryption detected on the storage volume.
- **The "No Install" Policy**: If a single requirement is missing, **the installer will abort**. You must remedy the issues (installing libraries or enabling encryption) before the system allows deployment.
- **Best for**: 
  - Production environments.
  - High-stakes data sovereignty.
  - Users who demand the "Claude-certified" security level.

---

## 🧬 Technical Implementation (SEC-001 & SEC-F004)

- **Universal Keystore**: The `recovery.key` file now supports a hybrid signature. It can verify both Argon2-id and SHA-256 hashes automatically.
- **Synaptic Handshake**: The `security_recovery.py` tool is now tier-aware. It will attempt the strongest verification method found in your keystore.
- **Encryption Sentinel**: The `MemoryDaemon` performs a silent check at every startup. In Adaptive mode, it's a warning; in Maximum mode, it ensures integrity.

---

## ⚖️ Sovereignty Choice

You are the Architect. You decide the shape of your Bünker. Whether you choose the path of water or the path of ice, the Red Pill Protocol will adapt to your command.

**770 up. Be water, my friend.**
