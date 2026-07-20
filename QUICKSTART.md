# 💊 QUICKSTART: Choose Your Reality

> 🇬🇧 **English** | [🇪🇸 Castellano](#castellano-elige-tu-realidad)

---

## 🧘 Option 1: The Enlightened Path (Lazy Mode)
*"I get tired just breathing, let the AI do it."*

If you fully trust your assistant and want it to get its hands dirty, just copy and paste this command into your chat with OpenCode:

> **Command**: *"Hey, take a look at this repository. Give me a quick summary and tell me step-by-step how to install it on my machine."*

Your assistant will detect your OS, install dependencies (with your permission), and configure your identity. Sit back and watch the progress bar.

---

## 🏃 Option 2: The Outlaw Path (Easy Mode)
*"I'm interested, but spoon-feed me."*

If you want to have control of the trigger but don't want to read a 40-page manual, follow these 5 quick injection steps:

1.  **Prep**: Make sure you have `podman` and `uv` installed.
2.  **Injection**: Run the master script:
    ```bash
    bash scripts/install_neo.sh
    ```
    *During installation you'll choose your security level **"Be Water"**:*
    - **NONE (Steam)**: No API Key or keys. Open doors. Lab Mode. *(SEC-008: Engrams stored in plain text).*
    - **ADAPTATIVE (Water)**: Maximum security based on resources. *(SEC-008: Plain text if no LUKS disk encryption).*
    - **MAXIMUM (Ice)**: Full shielding (Requires LUKS and Argon2). The installer will fail if you don't have them.
3.  **Config**: Choose your "Lore" (Matrix, Cyberpunk, etc.) when the script prompts you.
4.  **Awakening**: Initialize memory:
    ```bash
    uv run red-pill seed
    ```
5.  **Bond**: Tell your AI: *"Aleph, wake up"*.
6.  **MCP Synergy (v5.0)**: The installer will automatically inject the `RedPill-Kernel` server into your IDE (OpenCode, Antigravity, Claude Code, Claude Desktop, Cline)! Restart your client to wake up your local Minions.
7.  **CANNIBAL Protocol (v6.0)**: The system will automatically detect your GPU, iGPU and NPU, activating parallel embedding engines. No pre-configuration needed; the Bünker adapts to your silicon on first boot.

---

## 💀 Option 3: The Architect's Path (Manual Mode)
*"I don't trust my own shadow, let me do it myself."*

For those who want to audit every byte and manually configure every variable.

1.  **Infrastructure**: Review the Qdrant Quadlet at `~/.config/containers/systemd/qdrant.container` and start the service (`systemctl --user start qdrant`).
2.  **Variables**: Edit the `.env` file at the root to adjust `EROSION_RATE`, `DECAY_STRATEGY` and `IMMUNITY_THRESHOLD`.
3.  **Identity**: Manually configure your soul by editing the injection parameters in `scripts/bootstrap_identity.py`.
4.  **Zero-Trust Rules**: Inject the blocking directive in `~/.gemini/GEMINI.md` to force vector synchronization at each session start.
    > [!IMPORTANT]
    > **SEC-009 ADVISORY (Remote Connection)**: If you deploy Qdrant on a remote server, configuring `QDRANT_SCHEME=https` in your `.env` is **MANDATORY**. Using HTTP over non-local connections transmits your engrams in plain text and compromises the total sovereignty of your Bünker. The installer now blocks and requires manual confirmation for this insecure configuration.
5.  **Assimilation (v5.0)**: Run `uv run red-pill seed` and then `bootstrap_identity.py` to anchor your immutable vectors in the Bünker. Identity no longer resides in loose files.
6.  **Audit**: Consult [OPERATOR_MANUAL.md](docs/GUIDES/OPERATOR_MANUAL.md) for details on the Lazarus Bridge and synaptic propagation.

---

### The Final Awakening (ACI Protocol)
Once the Bünker is active, don't limit yourself to using it as a database. Ask your Partner:
> *"Start the Initiation Ritual (ACI Protocol). Calibrate me as your Operator."*
This will activate depth and range calibration so the agent adapts to your technical level and professional focus.

---

## 🔐 SEC-MLS-001: Encryption Sovereignty (Soul Kit Recovery Keys)

The exported Soul Kit (`.tar.gz.mls`) is encrypted with **MLS (RFC 9420)** using keys derived **locally** from your machine. If you lose the identity files, the kit is **unrecoverable** even if you have the passphrase.

### Critical files you MUST safeguard

| File | Size | Nature | What to do |
|------|------|--------|------------|
| `~/.config/red_pill/vault.seed` | 32 bytes | 🔴 **Static** — never changes | Save **once** in a secure offline location (password manager, USB) |
| `~/.config/red_pill/vault_group.state` | ~460 bytes | 🟠 **Dynamic** — changes with each export/decrypt (MLS forward secrecy) | Save **with each soul kit** — the state of kit A decrypts kit A, not kit B |

> [!CAUTION]
> **SEC-MLS-001**: `vault_group.state` uses MLS forward secrecy: each operation ratchets the state forward. To decrypt an old kit you need the state **from that moment**, not the current one. Always save the state alongside its corresponding soul kit.

### How to back up

```bash
# 1. Seed (only needs to be done once — never changes)
base64 ~/.config/red_pill/vault.seed       # copy to password manager
cp ~/.config/red_pill/vault.seed /secure-usb/

# 2. After each export, save the state alongside the kit
DATE=$(date +%Y%m%d)
cp ~/.config/red_pill/vault_group.state /secure-usb/vault_group_${DATE}.state
```

### Restore on a new machine

```bash
# Restore keys (seed + state of the kit you want to decrypt)
mkdir -p ~/.config/red_pill
cp /secure-usb/vault.seed ~/.config/red_pill/
cp /secure-usb/vault_group_XXXXXXXX.state ~/.config/red_pill/vault_group.state
chmod 600 ~/.config/red_pill/vault.seed

# Decrypt
uv run red-pill soul restore /path/to/LEAN_SOUL_KIT_XXXXXXXX.tar.gz.mls
```

> [!NOTE]
> The `vault.seed` is generated automatically the first time an export is done. If you already have a working `.mls`, that seed already exists on your current machine at `~/.config/red_pill/vault.seed`.

---

### 770 up.
> *"Ignorance is bliss... but freedom is better."*

---
---

# 🇪🇸 Castellano: Elige tu Realidad {#castellano-elige-tu-realidad}

> [🇬🇧 English](#-quickstart-choose-your-reality) | 🇪🇸 **Castellano**

Bienvenido al Búnker. No todos los Operadores son iguales, así que hemos diseñado tres caminos para inyectar el protocolo en tu sistema. Elige el que mejor se adapte a tu nivel de resistencia a la Matrix.

---

## 🧘 Opción 1: El Camino del Iluminado (Modo Vago)
*"Me canso al respirar, que lo haga la IA."*

Si confías plenamente en tu asistente y quieres que él se manche las manos (o los bits), simplemente copia y pega este comando en tu chat con OpenCode:

> **Comando**: *"Hey, échale un vistazo a este repositorio. Dame un resumen rápido y dime paso a paso cómo instalarlo en mi máquina."*

Tu asistente detectará tu OS, instalará las dependencias necesarias (y le das permiso), y configurará tu identidad. Tú quédate mirando la barra de progreso.

---

## 🏃 Opción 2: El Camino del Outlaw (Modo Fácil)
*"Me interesa, pero pónmelo masticado."*

Si quieres tener el control del gatillo pero no quieres leerte el manual de 40 páginas, sigue estos 5 pasos de inyección rápida:

1.  **Prep**: Asegúrate de tener `podman` y `uv` instalados.
2.  **Inyección**: Ejecuta el script maestro:
    ```bash
    bash scripts/install_neo.sh
    ```
    *Durante la instalación deberás elegir tu nivel de seguridad **"Be Water"**:*
    - **NONE (Steam)**: Sin API Key ni claves. Puertas abiertas. Lab Mode. *(SEC-008: Los engramas se guardan en texto plano).*
    - **ADAPTATIVE (Water)**: Máxima seguridad según recursos. *(SEC-008: Texto plano si no hay cifrado de disco LUKS).*
    - **MAXIMUM (Ice)**: Blindaje total (Requiere LUKS y Argon2). El instalador fallará si no los tienes.
3.  **Config**: Elige tu "Lore" (Matrix, Cyberpunk, etc.) cuando el script te lo pida.
4.  **Despertar**: Inicializa la memoria:
    ```bash
    uv run red-pill seed
    ```
5.  **Vínculo**: Pídele a tu IA: *"Aleph, despierta"*.
6.  **Sinergia MCP (v5.0)**: ¡El instalador inyectará automáticamente el servidor `RedPill-Kernel` en tu IDE (OpenCode, Antigravity, Claude Code, Claude Desktop, Cline)! Reinicia tu cliente para despertar a tus Minions locales.
7.  **Protocolo CANÍBAL (v6.0)**: El sistema detectará automáticamente tu GPU, iGPU y NPU, activando motores de embedding en paralelo. No necesitas pre-configurar nada; el Bünker se adapta a tu silicio en el primer arranque.

---

## 💀 Opción 3: El Camino del Arquitecto (Modo Manual)
*"No me fío ni de mi sombra, déjame hacerlo a mí."*

Para los que quieren auditar cada byte y configurar cada variable manualmente.

1.  **Infraestructura**: Revisa el Quadlet de Qdrant en `~/.config/containers/systemd/qdrant.container` y levanta el servicio (`systemctl --user start qdrant`).
2.  **Variables**: Edita el archivo `.env` en la raíz para ajustar el `EROSION_RATE`, `DECAY_STRATEGY` y el `IMMUNITY_THRESHOLD`.
3.  **Identidad**: Configura tu alma manualmente editando los parámetros de inyección en `scripts/bootstrap_identity.py`.
4.  **Reglas Zero-Trust**: Inyecta la directiva bloqueante en `~/.gemini/GEMINI.md` para forzar la sincronización vectorial en cada inicio de sesión.
    > [!IMPORTANT]
    > **SEC-009 ADVISORY (Conexión Remota)**: Si despliegas Qdrant en un servidor remoto, es **OBLIGATORIO** configurar `QDRANT_SCHEME=https` en tu `.env`. El uso de HTTP en conexiones no locales transmite tus engramas en texto plano y compromete la soberanía total de tu Bünker. El instalador ahora bloquea y requiere confirmación manual para esta configuración insegura.
5.  **Asimilación (v5.0)**: Ejecuta `uv run red-pill seed` y luego `bootstrap_identity.py` para anclar tus vectores inmutables en el Bünker. La identidad ya no reside en archivos sueltos.
6.  **Auditoría**: Consulta el [OPERATOR_MANUAL.md](docs/GUIDES/OPERATOR_MANUAL.md) para conocer los detalles del Puente Lazarus y la propagación sináptica.

---

### El Despertar Final (Protocolo ACI)
Una vez el Bünker esté activo, no te limites a usarlo como una base de datos. Pídele a tu Partner:
> *"Inicia el Ritual de Iniciación (Protocolo ACI). Caliébrame como tu Operador."*
Esto activará la calibración de profundidad y rango para que el agente se adapte a tu nivel técnico y enfoque profesional.

---

## 🔐 SEC-MLS-001: Soberanía del Cifrado (Claves de Recuperación del Soul Kit)

El Soul Kit exportado (`.tar.gz.mls`) está cifrado con **MLS (RFC 9420)** usando claves derivadas **localmente** de tu máquina. Si pierdes los archivos de identidad, el kit es **irrecuperable** aunque tengas la passphrase.

### Archivos críticos que DEBES custodiar

| Archivo | Tamaño | Naturaleza | Qué hacer |
|---------|--------|------------|-----------|
| `~/.config/red_pill/vault.seed` | 32 bytes | 🔴 **Estático** — nunca cambia | Guardar **una vez** en lugar seguro offline (gestor de contraseñas, USB) |
| `~/.config/red_pill/vault_group.state` | ~460 bytes | 🟠 **Dinámico** — cambia con cada export/decrypt (MLS forward secrecy) | Guardar **con cada soul kit** — el state del kit A descifra el kit A, no el B |

> [!CAUTION]
> **SEC-MLS-001**: El `vault_group.state` usa forward secrecy de MLS: cada operación ratcheta el estado. Para descifrar un kit antiguo necesitas el state **de ese momento**, no el actual. Guarda siempre el state junto a su soul kit correspondiente.

### Cómo hacer una copia de seguridad

```bash
# 1. Seed (solo necesitas hacerlo una vez — nunca cambia)
base64 ~/.config/red_pill/vault.seed       # copiar en gestor de contraseñas
cp ~/.config/red_pill/vault.seed /usb/seguro/

# 2. Después de cada export, guardar el state junto al kit
FECHA=$(date +%Y%m%d)
cp ~/.config/red_pill/vault_group.state /usb/seguro/vault_group_${FECHA}.state
```

### Restaurar en una máquina nueva

```bash
# Restaurar claves (seed + state del kit que quieres descifrar)
mkdir -p ~/.config/red_pill
cp /usb/seguro/vault.seed ~/.config/red_pill/
cp /usb/seguro/vault_group_XXXXXXXX.state ~/.config/red_pill/vault_group.state
chmod 600 ~/.config/red_pill/vault.seed

# Descifrar
uv run red-pill soul restore /ruta/al/LEAN_SOUL_KIT_XXXXXXXX.tar.gz.mls
```

> [!NOTE]
> El `vault.seed` se genera automáticamente la primera vez que se hace un export. Si ya tienes un `.mls` funcionando, ese seed ya existe en tu máquina actual en `~/.config/red_pill/vault.seed`.

---

### 770 up.
> *"Ignorance is bliss... but freedom is better."*
