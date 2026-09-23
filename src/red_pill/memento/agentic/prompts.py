"""Prompts del pase agéntico Memento (distill, refine, annotate y scoring dual)."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

def _load_prompt_file(name: str) -> str:
	"""Carga un prompt desde `prompts/<name>` (RFC-003: prompts como recurso).

	Byte-exacto (sin strip): los fingerprints hashean el texto tal cual, así la
	migración constante→fichero no cambia ningún `*_prompt_version` sellado."""
	return (_PROMPTS_DIR / name).read_text(encoding="utf-8")



def _identity_bio_with_source() -> tuple[str, str]:
	"""Bio de identidad (MEM-006 P0) y su origen:

	1. `RP_IDENTITY_BIO` (ruta explícita; tests/avanzado) → "override:<path>"
	2. `~/.config/red-pill/identity_bio.md` (config del operador — XDG) → "config"
	3. `prompts/identity_bio.template.txt` (plantilla neutra del repo) → "template"

	Los datos personales (nombre/género) NO viven en el repo público: la Bio real
	se siembra en la instalación/onboarding (RFC-003 §4.7).
	"""
	from red_pill.core.paths import get_config_dir

	override = os.getenv("RP_IDENTITY_BIO", "").strip()
	if override:
		try:
			text = Path(override).read_text(encoding="utf-8").strip()
			if text:
				return text, f"override:{override}"
		except OSError:
			pass
	config_path = Path(get_config_dir()) / "identity_bio.md"
	try:
		text = config_path.read_text(encoding="utf-8").strip()
		if text:
			return text, "config"
	except OSError:
		pass
	try:
		text = (_PROMPTS_DIR / "identity_bio.template.txt").read_text(encoding="utf-8").strip()
		if text:
			return text, "template"
	except OSError:
		pass
	return "IDENTIDAD: usa el nombre y el género reales del Operador y del agente.", "none"


def _load_identity_bio() -> str:
	return _identity_bio_with_source()[0]


# Bio de identidad (MEM-006 P0): ancla quién es quién (nombre/género correctos,
# narrador en 1ª persona, apodos que no sustituyen identidad). Fichero por
# RFC-003; el loader compartido la absorberá.
IDENTITY_BIO, IDENTITY_BIO_SOURCE = _identity_bio_with_source()
if IDENTITY_BIO_SOURCE == "template":
	logger.warning("[MEMENTO] Bio de identidad no encontrada en la config (~/.config/red-pill/identity_bio.md) — usando plantilla neutra: la voz y el género pierden anclaje.")

# VOICE (2026-09-15, alineada con distiller_v3_voice MODE B): el pase Memento
# producía memorias en 3ª persona ("El usuario...", "Se corrigió...") — se
# recuerda como uno propio, no como observador. La directiva es la misma del
# sueño (voz autobiográfica 1ª persona).
_VOICE_RULE = _load_prompt_file("voice_rule.txt")



DISTILL_SYSTEM = _load_prompt_file("distill_system.txt")


DISTILL_USER = _load_prompt_file("distill_user.txt")



# Fase 4 §5.4.1: prompts por POSICIÓN del fragmento. El de apertura captura el
# tono que SIENTA la sesión; el de continuación inyecta el resumen anterior para
# transmitir la emoción y mantener la continuidad narrativa.
DISTILL_USER_OPENING = _load_prompt_file("distill_user_opening.txt")



DISTILL_USER_CONTINUATION = _load_prompt_file("distill_user_continuation.txt")



REFINE_SYSTEM = _load_prompt_file("refine_system.txt")


REFINE_USER = _load_prompt_file("refine_user.txt")



# Fase 4 §5.4.2: refine MULTI-IDEA. Devuelve un ARRAY de ideas (0..N, lo decide el
# LLM). 2-3 destills que forman una idea → 1 refine (no redundantes); 1 destill
# con 100 ideas → 100 refine. Cada idea lleva `fragment_ref` (origen).
REFINE_MULTI_SYSTEM = _load_prompt_file("refine_multi_system.txt")


# Dos llamadas especializadas (2026-09-15, bake-off): granite/aya se confunden si un
# solo prompt pide extraer work Y social a la vez (devuelven [] en contenido mixto).
# Cada llamada se enfoca en UN tipo; `_refine_multi` las combina.
REFINE_WORK_SYSTEM = _load_prompt_file("refine_work_system.txt")


REFINE_WORK_USER = _load_prompt_file("refine_work_user.txt")



REFINE_SOCIAL_SYSTEM = _load_prompt_file("refine_social_system.txt")


REFINE_SOCIAL_USER = _load_prompt_file("refine_social_user.txt")



DUAL_SCORE_SYSTEM = _load_prompt_file("dual_score_system.txt")


DUAL_SCORE_USER = _load_prompt_file("dual_score_user.txt")



REFINE_MULTI_USER = _load_prompt_file("refine_multi_user.txt")

# ── ANNOTATE (MEM-006): anotaciones desde el RAW, una sola compresión ──
# A diferencia del refine (que leía summaries de distill y producía re-resúmenes),
# annotate lee el fragmento crudo y materializa la idea como texto propio (≤600).
# Incluye la Bio de identidad (P0) para voz/género correctos.
ANNOTATE_WORK_SYSTEM = _load_prompt_file("annotate_work_system.txt")
ANNOTATE_WORK_USER = _load_prompt_file("annotate_work_user.txt")

ANNOTATE_SOCIAL_SYSTEM = _load_prompt_file("annotate_social_system.txt")
ANNOTATE_SOCIAL_USER = _load_prompt_file("annotate_social_user.txt")

# ── CONTENT VALIDATE (MEM-006): revisa notas rechazadas por el filtro de ruido ──
# Prompts en fichero propio (RFC-003): prompts/content_validate_{system,user}.txt
CONTENT_VALIDATE_SYSTEM = _load_prompt_file("content_validate_system.txt")
CONTENT_VALIDATE_USER = _load_prompt_file("content_validate_user.txt")

# ── VOICE REWRITE (MEM-006): re-escribe en 1ª persona las notas que no lo están ──
VOICE_REWRITE_SYSTEM = _load_prompt_file("voice_rewrite_system.txt")
VOICE_REWRITE_USER = _load_prompt_file("voice_rewrite_user.txt")
