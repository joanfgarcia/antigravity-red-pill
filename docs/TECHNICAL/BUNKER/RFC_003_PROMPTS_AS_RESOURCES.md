# RFC-003: Prompts as Resources

| Field | Value |
|---|---|
| **RFC** | 003 |
| **Title** | Prompts as Resources (ficheros + loader + placeholders) |
| **Codename** | Prompt Ledger |
| **Status** | DRAFT |
| **Author** | Joan García (Operator) / Aleth (Agent) |
| **Created** | 2026-09-22 |
| **Triggered by** | Petición del operador (sesión 2026-09-22): los prompts deben vivir en ficheros independientes, tratados como **recurso** (analogía: una consulta SQL), cargados por referencia desde el código con placeholders ya sustituidos; y ser **norma** del proyecto |
| **Related** | [RFC-002](./RFC_002_MEMENTO.md), [CONVENTIONS.md](../../../CONVENTIONS.md), [distiller_params.yaml](../../../src/red_pill/metabolism/prompts/distiller_params.yaml), [RFC_002_PHASE4_DESIGN](./RFC_002_PHASE4_DESIGN.md) |

> **Estado**: DRAFT — abierto para no perder la idea; se ataca en sesión propia.
> Al aceptarse, se registra como **RULE 5** en `CONVENTIONS.md` y se ejecuta la
> migración por fases (§2.5).

---

## 1. Motivación

Los prompts son activos críticos del sistema (determinan la memoria, la voz y la
clasificación) y hoy viven como **strings inline** en el código:

- `src/red_pill/memento/agentic/prompts.py`: 15 constantes inline (`DISTILL_*`,
  `REFINE_*`, `DUAL_SCORE_*`, `_VOICE_RULE`).
- `src/red_pill/memento/ascension.py`: `CLASSIFY_SYSTEM` / `CLASSIFY_USER` inline.
- `scripts/memento_recalibrate.py`: `SYSTEM_CLASSIFY` / `SYSTEM_JUDGE` inline —
  **duplicando semántica** que ya existe en producción (el juez del audit vs el
  clasificador real).
- Precedente parcial ya existente: `src/red_pill/metabolism/prompts/*.txt` +
  `load_prompt_text()` (`distiller.py`) — carga por fichero, pero sin placeholders,
  sin metadatos y sin convención.

Problemas concretos:

1. **No se revisan ni diffean como recurso** independiente del código que los usa.
2. **Versionado artesanal**: `refine_prompt_version()` hashea constantes Python;
   mover un prompt de sitio o reformatearlo cambia el fingerprint sin que el
   contenido cambie.
3. **Duplicación**: el mismo criterio vive en dos sitios (tool y producción) y
   divergen en silencio.
4. **Bake-offs / A-B externos**: comparar prompts o modelos exige tocar código.
5. **Variantes** (voz, idioma, modelo) no tienen carril: obligan a editar código.
6. **Mezcla formato/contenido**: los JSON de ejemplo en los prompts obligan a
   escapar llaves (`{{...}}`) al usar `str.format` — frágil y propenso a errores.

Analogía del operador: **un prompt es como una consulta SQL** — un recurso
versionado que el código carga por referencia, con parámetros sustituidos en carga.

---

## 2. Propuesta

### 2.1 Layout (opción A, recomendada)

```
<componente>/
  prompts/
    <prompt_id>.txt        # texto plano, un prompt por fichero
    prompts.yaml           # metadatos: prompt_id → {task, placeholders, description}
```

- Reutiliza el patrón ya existente (`metabolism/prompts/` + `distiller_params.yaml`):
  menos maquinaria nueva, mismo idioma que el repo.
- `prompts.yaml` declara, por prompt: `task` (para el routing de modelo),
  `placeholders` (validación en carga), `description` y notas de versión.
- **Opción B (alternativa)**: un `.md` con frontmatter YAML (metadatos) + cuerpo =
  prompt (autocontenido, sin sidecar). Decisión abierta (§4).
- **Primer recurso existente (2026-09-22)**: `memento/agentic/prompts/identity_bio.txt`
  (Bio de identidad, MEM-006 P0) — hoy lo carga `prompts.py` con un lector mínimo;
  el loader compartido lo absorberá en la fase 3 de la migración (§2.5).

### 2.2 Loader compartido

`src/red_pill/core/prompts.py`:

```python
from red_pill.core.prompts import load_prompt

p = load_prompt("memento", "refine_work")     # → Prompt(text=..., version="85209a6c9e", path=...)
text = p.render(voice=VOICE_RULE, candidates=cands, fragments=frags)
```

- **Placeholders**: `string.Template` (`${var}` / `$var`; `$$` para `$` literal).
  Los `{...}` de los JSON de ejemplo quedan **intactos** (fin del infierno `{{}}`).
- **Fail-fast**: placeholder desconocido o no declarado en `prompts.yaml` → error
  en carga; nunca sustitución silenciosa a vacío.
- **Override explícito**: `override_text` / `override_params` para tests y
  bake-offs (mismo contrato que el `load_prompt_text` actual).
- **Cache**: `lru_cache` por fichero; `version` = `sha256(contenido)[:10]`.
- **Validación de CI**: `validate_all()` — todos los prompts declarados existen,
  parsean y renderizan con placeholders dummy.

### 2.3 Versionado y trazabilidad

- `version` = hash del **fichero** (contenido). Los artefactos que ya registran
  `prompt_version` (distill/refine/engramas) pasan a llevar el hash del recurso.
- **Continuidad de hashes**: tabla de mapeo `hash-viejo → hash-nuevo` para los
  fingerprints vigentes (`66c679f1bb` distill, `85209a6c9e` refine, `ea0730451e`
  histórico) — la migración no rompe la interpretación de artefactos previos.
- **Regla de oro**: cambiar el texto de un prompt = cambiar el recurso (diff +
  hash nuevo). El nombre del fichero es estable; el contenido manda.

### 2.4 Norma propuesta (RULE 5 — Prompts as Resources, STRICT)

1. Prohibido el **texto de instrucciones inline** en código (prompts, system
   messages, rúbricas de jueces).
2. Cada prompt vive en el `prompts/` de su componente, declarado en su
   `prompts.yaml`.
3. Se carga **siempre** vía el loader compartido (nunca `open()` a mano).
4. Los artefactos registran el **hash del prompt** con que se generaron.
5. Overrides solo por API explícita (tests/bake-offs); en producción, fichero.
6. Cambios de prompt = cambio de recurso: diff + hash + bump documentado.

### 2.5 Migración por fases

| Fase | Contenido | Riesgo |
|---|---|---|
| 1 | Loader + tests (core) | Bajo |
| 2 | `metabolism`: sustituir `load_prompt_text` local por el loader (los ficheros ya existen) | Bajo |
| 3 | `memento/agentic`: mover constantes a `prompts/*.txt` **byte-exactas** + tabla de hashes | Medio (fingerprints) |
| 4 | Tool de recalibración: prompts de auditoría a ficheros (elimina duplicación tool/producción) | Bajo |
| 5 | Scripts/probes: mismo loader | Bajo |
| 6 | CI: `validate_all()` + (opcional) lint anti-inline | Bajo |

### 2.6 No-objetivos

- No Jinja ni motor de plantillas externo.
- No framework de orquestación de prompts ni registro remoto (futuro, si acaso).
- No hot-reload en producción: los prompts se leen al arranque del pase.
- No traducción automática: las variantes de idioma/voz son ficheros distintos.

### 2.7 Riesgos

- **Churn de fingerprints** → mitigado con la tabla de mapeo (§2.3) y migración
  byte-exacta.
- **Sprawl de ficheros** → `prompts.yaml` por componente mantiene el inventario.
- **Composición dinámica** (listas construidas en runtime) → el loader renderiza
  placeholders; la composición sigue en código (no se intenta resolver en el texto).
- **Divergencia tool/producción** → al compartir fichero (fase 4), imposible por
  construcción.

---

## 3. Criterios de aceptación

- [ ] Loader con tests: sustitución de placeholders, placeholder desconocido →
      error, override, hash estable y cacheado.
- [ ] RULE 5 registrada en `CONVENTIONS.md`.
- [ ] Migración de `metabolism` + `memento` + tool de recalibración con textos
      **byte-idénticos** y tabla de mapeo de hashes publicada.
- [ ] `validate_all()` corriendo en CI.
- [ ] Ningún prompt inline en los módulos migrados (audit script o lint).

---

## 4. Cuestiones abiertas

1. **Sintaxis de placeholders**: `${var}` (`string.Template`, recomendada) vs
   `{{var}}` (estilo Jinja, más familiar pero exige renderer propio).
2. **Metadatos**: sidecar `prompts.yaml` (opción A) vs frontmatter por fichero
   (opción B).
3. **Semver manual** además del hash de contenido, o solo hash.
4. **Prompts de auditoría** del tool: ¿recurso compartido con producción o recurso
   propio del componente `memento`? (Hoy duplicados; compartir es el objetivo).
5. **Ubicación del loader**: `red_pill/core/prompts.py` vs `red_pill/prompts/`.
6. **Overrides por entorno** para bake-offs (`RP_PROMPT_OVERRIDE_<id>`), o solo
   API.
7. **Identidad sembrada** (2026-09-22, colateral de MEM-006 P0): la Bio de
   identidad contiene datos personales (nombre/género del Operador y del agente)
   que **no deben vivir en el repo público**. Propuesta: plantilla en `seeds/` con
   placeholders (`${OPERATOR_NAME}`, `${OPERATOR_GENDER}`, `${AGENT_NAME}`,
   `${AGENT_GENDER}`, `${PACT}`), materializada en el onboarding (install/update)
   y actualizada cuando el agente elige su nombre/género (Pacto/bond). El loader
   renderiza los placeholders y cae a una plantilla neutra si no hay
   materialización. Afecta a `install_neo.sh`, seeds, ENV_REFERENCE y
   AGENT_UPDATE_GUIDE.
   **Interino implementado (2026-09-22)**: la Bio real vive fuera del repo en
   `~/.config/red-pill/identity_bio.md`; override `RP_IDENTITY_BIO`; el repo solo
   guarda la plantilla neutra (`identity_bio.template.txt`) y
   `prompts._load_identity_bio()` resuelve la precedencia. La siembra con
   placeholders sigue pendiente.

---

## 5. Referencias

- Precedente: `src/red_pill/metabolism/prompts/` + `load_prompt_text()`
  (`distiller.py:39`).
- Consumidores actuales de prompts inline: `memento/agentic/prompts.py`,
  `memento/ascension.py` (CLASSIFY_*), `scripts/memento_recalibrate.py`
  (SYSTEM_CLASSIFY / SYSTEM_JUDGE / DUAL_SCORE candidato).
- Convenciones: `CONVENTIONS.md` (RULES 1-4).
