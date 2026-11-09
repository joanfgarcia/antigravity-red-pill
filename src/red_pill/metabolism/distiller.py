"""LLM distillation primitives: raw interactions -> engrams, hubs, session anchors.

Extracted from sleep.py per ADR-SLEEP-001. GPU/LLM-facing (uses the inference
provider); the sleep orchestrator gates these on free VRAM.
"""

import hashlib
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, cast

import yaml

import red_pill.config as cfg
from red_pill.metabolism.chunker import _is_template_echo, _sanitize_llm_json
from red_pill.metabolism.schemas_params import DistillerParamsConfig


def _instance_names() -> tuple:
	"""(agent_name, operator_name) del PUESTO — nunca hardcodeados en el repo."""
	c = cfg.get_config()
	agent = str(getattr(c, "MEMENTO_AGENT_LABEL", "") or getattr(c, "AGENT_NAME", "") or "Agente")
	operator = str(getattr(c, "MEMENTO_OPERATOR_LABEL", "") or getattr(c, "OPERATOR_DISPLAY_NAME", "") or "Operador")
	return agent, operator


logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


def load_distiller_config(yaml_path: Optional[str] = None) -> DistillerParamsConfig:
	"""Carga y valida la configuración YAML del destilador mediante Pydantic."""
	target_path = yaml_path or os.path.join(PROMPTS_DIR, "distiller_params.yaml")
	if os.path.exists(target_path):
		try:
			with open(target_path, "r", encoding="utf-8") as f:
				raw_data = yaml.safe_load(f) or {}
			return DistillerParamsConfig(**raw_data)
		except Exception as e:
			logger.warning(f"[DISTILLER] Error cargando/validando params YAML '{target_path}': {e}. Usando defaults.")
	return DistillerParamsConfig()


def load_prompt_text(
	filename: str,
	fallback_prompt: str = "",
	override_text: Optional[str] = None,
	static: Optional[Dict[str, str]] = None,
) -> str:
	"""Carga el texto del prompt desde recurso (PROMPT-001): manifiesto del
	componente con placeholders resueltos. `override_text` (bake-offs) gana.

	Si el fichero NO está declarado (prompt_file custom de un perfil), cae a
	lectura directa — compatibilidad. Un prompt declarado que falla NO se
	enmascara: el error del loader sube (fail-closed)."""
	if override_text:
		return override_text
	from red_pill.core import prompts as core

	stem = os.path.basename(filename).rsplit(".", 1)[0]
	if core.is_declared("metabolism", stem):
		return core.resolve("metabolism", stem, static=static or {}).text.strip()
	path = os.path.join(PROMPTS_DIR, filename)
	if os.path.exists(path):
		try:
			with open(path, "r", encoding="utf-8") as f:
				content = f.read().strip()
				if content:
					if static:
						for name, value in static.items():
							content = content.replace("${" + name + "}", value)
					if "${" in content:
						logger.warning(
							f"[DISTILLER] prompt no declarado '{filename}' con placeholders sin resolver; "
							"mígralo al manifiesto de metabolism (RULE 5)."
						)
					return content
		except Exception as e:
			logger.warning(f"[DISTILLER] Error leyendo archivo de prompt '{path}': {e}.")
	return fallback_prompt


def _render_metabolism(prompt_id: str, **runtime: Any) -> str:
	"""Render de un prompt de metabolism por el loader (PROMPT-001 F4)."""
	from red_pill.core import prompts as core

	return core.render("metabolism", prompt_id, **runtime)


# Closed emotional taxonomy the erosion/affect stack understands. Anything the
# distiller invents outside this list is normalized to neutral (and logged).
VALID_EMOTIONS = frozenset({"joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"})

EMOTION_SYNONYMS = {
	"entusiasmo": "joy",
	"alegria": "joy",
	"alegría": "joy",
	"felicidad": "joy",
	"tristeza": "sadness",
	"miedo": "fear",
	"temor": "fear",
	"asco": "disgust",
	"ira": "anger",
	"rabia": "anger",
	"ansiedad": "anxiety",
	"preocupacion": "anxiety",
	"preocupación": "anxiety",
	"envidia": "envy",
	"verguenza": "embarrassment",
	"vergüenza": "embarrassment",
	"aburrimiento": "ennui",
	"nostalgia": "nostalgia",
	"neutro": "neutral",
}


def _detect_source_lang(text: str) -> str:
	"""Cheap ISO 639-1 detection for the source text (es/en only, as used by the
	distiller prompts). Returns '' when the signal is too weak to override the
	LLM's label — the label only gets corrected on STRONG evidence.

	Spanish markers (ñ, ¿, ¡, accented chars) are near-unambiguous; en is
	inferred from absence of Spanish markers plus common English stopwords.
	"""
	low = (text or "").lower()
	if any(ch in low for ch in ("ñ", "¿", "¡")):
		return "es"
	accent_count = sum(low.count(ch) for ch in "áéíóúü")
	wrapped = f" {low} "
	spanish_stop = sum(wrapped.count(w) for w in (" de ", " la ", " el ", " que ", " y ", " en ", " un ", " una ", " los ", " las "))
	english_stop = sum(wrapped.count(w) for w in (" the ", " and ", " of ", " is ", " in ", " to ", " that ", " it "))
	if accent_count >= 2:
		return "es"
	if spanish_stop >= 3 and english_stop == 0:
		return "es"
	if english_stop >= 3 and spanish_stop == 0 and accent_count == 0:
		return "en"
	return ""


def _correct_lang_label(llm_lang: str, source_text: str) -> str:
	"""Mechanical lang correction (V3 philosophy: guarantees in code, not prompt).

	Small English-biased models (phi-4-mini measured 2026-08-13: 'en' on Spanish
	text, 2/2 probes) mislabel the source language; the label feeds the hub
	synthesis dominant-language hint and Qdrant metadata. Only override with
	strong evidence; otherwise keep the model's label.
	"""
	llm_lang = str(llm_lang or "").lower().strip()[:2]
	if llm_lang not in ("", "en", "es"):
		# The detector only tells es/en apart; accented chars are shared with
		# ca/fr/pt, so a model that correctly says 'ca' must not be overridden.
		return llm_lang
	detected = _detect_source_lang(source_text)
	if detected and detected != llm_lang:
		return detected
	return llm_lang


def _resolve_prompt_for_profile(profile_name: Optional[str] = None) -> Optional[str]:
	"""Look up the per-model `prompt_file` field from model_profiles.yaml.

	If the active profile (from MINION_DEFAULT_PROFILE env var (fallback legacy MINION_PROFILE), or `profile_name` if
	passed) declares a `prompt_file`, return it. Otherwise return None (the
	caller will fall back to the default `distiller_v3.txt`).

	The bake-off 2026-08-13 established that smaller models (3-4B) need
	MODE B (`distiller_v3_voice.txt`) for stable deixis/JSON, while
	granite_8b works better with the lax `distiller_v3.txt`. This helper
	implements that mapping at runtime without requiring callers to know
	which prompt each model prefers.

	AD-030: la conducta de la TAREA `distill` (incl. el prompt_file
	del candidato default) la resuelve `model_runtime`; este helper cae a eso
	primero y a la lógica por env solo si la resolución falla.
	"""
	import os

	try:
		from red_pill.core import model_runtime as mr

		conduct = mr.resolve_task_conduct("distill")
		if conduct.get("prompt_file"):
			return cast(str, conduct["prompt_file"])
	except Exception:
		pass

	if profile_name is None:
		profile_name = os.getenv("MINION_DEFAULT_PROFILE") or os.getenv("MINION_PROFILE")
	if not profile_name:
		return None
	try:
		from red_pill.core.model_registry import ModelRegistry

		profile = ModelRegistry.get_profile(profile_name)
	except Exception:
		return None
	prompt_file = profile.get("prompt_file")
	return prompt_file if isinstance(prompt_file, str) and prompt_file else None


def assert_active_profile_commercial_ok(profile_name: Optional[str] = None) -> None:
	"""Compliance gate for the distiller entrypoint.

	Raises `ModelLicenseError` when the active profile (MINION_DEFAULT_PROFILE (fallback legacy MINION_PROFILE), or
	`profile_name` if passed) is licensed non-commercial and the current run
	is in a commercial context (REDPILL_LICENSE_CONTEXT=commercial). A no-op
	in personal context or when no profile is active.
	"""
	import os

	if profile_name is None:
		profile_name = os.getenv("MINION_DEFAULT_PROFILE") or os.getenv("MINION_PROFILE")
	if not profile_name:
		return
	try:
		from red_pill.core.model_registry import ModelRegistry

		ModelRegistry.assert_commercial_ok(profile_name)
	except ImportError:
		return


def _validate_relics(relics: Any, raw_content: str, max_relics: int = 2, max_len: int = 200) -> list:
	"""Keep only quotes that are literal substrings of the source (whitespace-normalized).

	The verbatim guarantee belongs to code, not to the LLM's discipline: the
	workshop showed distillers paraphrase quotes within two generations.
	"""
	if not isinstance(relics, list):
		return []
	normalized_source = " ".join(str(raw_content).split())
	kept: list = []
	for relic in relics:
		if not isinstance(relic, str):
			continue
		candidate = " ".join(relic.strip().strip('"').split())
		if candidate and len(candidate) <= max_len and candidate in normalized_source and candidate not in kept:
			kept.append(candidate)
		if len(kept) >= max_relics:
			break
	return kept


def get_dynamic_identity_context() -> str:
	"""Carga dinámicamente el perfil relacional del operador y del agente desde el Bünker/disco."""
	from red_pill.core.paths import get_data_dir

	context_lines = [
		"AUTOBIOGRAPHICAL RELATIONSHIP FRAME:",
		"- You are Aleth, an autonomous AI assistant and digital partner.",
		"- The Operator is Joan (Fixer / he / él), your human partner and operator.",
	]
	profile_path = get_data_dir() / "operator_profile.md"
	if profile_path.exists():
		try:
			profile_text = profile_path.read_text(encoding="utf-8").strip()
			if profile_text and profile_text != "INSUFFICIENT_DATA":
				context_lines.append(f"OPERATOR PROFILE & RECENT STATE: {profile_text}")
		except Exception:
			pass

	return "\n".join(context_lines)


def distill_engram(
	raw_content: str,
	fallback_category: str = "social",
	override_prompt: Optional[str] = None,
	override_params: Optional[Dict[str, Any]] = None,
	config_yaml_path: Optional[str] = None,
) -> Dict[str, Any]:
	"""
	Lazarus Phase 2: Consolidation (Sleep) & Affective Preservation
	Now driven by Samantha's cognitive depth and ProviderRegistry.
	"""
	import re
	import time

	from red_pill.core.providers import ProviderRegistry

	assert_active_profile_commercial_ok()

	cfg_params = load_distiller_config(config_yaml_path).distill_engram
	params = cfg_params.model_dump()
	if override_params:
		params.update(override_params)

	# Context Window Safety Guard — Prevent local/small LLM context overflow
	max_input_chars = getattr(cfg, "SLEEP_MAX_INPUT_CHARS", 6000)
	if len(raw_content) > max_input_chars:
		logger.warning(
			f"[DISTILLER] Raw content length ({len(raw_content)} chars) exceeds context safety limit ({max_input_chars} chars). Truncating input."
		)
		raw_content = raw_content[:max_input_chars]

	# Prompt precedence: explicit caller override > per-model prompt declared
	# by the active profile (bake-off 2026-08-13) > global params default.
	# params always carries a prompt_file (schema default distiller_v3.txt),
	# so checking params first would make the per-model routing unreachable.
	prompt_file = (override_params or {}).get("prompt_file")
	if not prompt_file:
		prompt_file = _resolve_prompt_for_profile() or params.get("prompt_file") or "distiller_v3.txt"
	_agent_name, _operator_name = _instance_names()
	system_prompt = load_prompt_text(prompt_file, override_text=override_prompt, static={"agent_name": _agent_name, "operator_name": _operator_name})

	# Prepend dynamic identity context if not already present
	identity_context = get_dynamic_identity_context()
	if identity_context and identity_context not in system_prompt:
		system_prompt = f"SESSION PREPROMPT / LOCAL CONTEXT:\n{identity_context}\n\n{system_prompt}"

	# Explicit flag so callers can detect the fallback reliably — the old heuristic
	# (summary endswith "..." and len > 490) misses short chunks whose raw fallback is <490 chars.
	fallback = {
		"summary": raw_content[:500] + "...",
		"emotion": "neutral",
		"intensity": 0.5,
		"category": fallback_category,
		"texture": "",
		"lang": "",
		"relics": [],
		"_is_fallback": True,
	}

	prompt_text = f"DATA:\n{raw_content}"
	provider_alias = params.get("provider_alias", "sip")

	try:
		# Intentar obtener el proveedor configurado, fallback al por defecto
		try:
			provider = ProviderRegistry.get_inference_provider(provider_alias)
		except RuntimeError:
			provider = ProviderRegistry.get_inference_provider()
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] No inference provider available: {e}")
		return fallback

	max_retries = int(params.get("max_retries", 2))
	temperature = float(params.get("temperature", 0.1))
	backoff = 1

	for attempt in range(max_retries):
		try:
			content = provider.generate(
				prompt=prompt_text,
				messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt_text}],
				temperature=temperature,
				response_format={"type": "json_object"},
			)

			match = re.search(r"\{[\s\S]*\}", content)
			if match:
				sanitized = _sanitize_llm_json(match.group(0))
				parsed = json.loads(sanitized)
				summary_val = parsed.get("summary", fallback["summary"]) or fallback["summary"]
				if not isinstance(summary_val, str):
					summary_val = str(summary_val)

				emotion_val = parsed.get("emotion")
				if emotion_val is None:
					emotion_val = "neutral"
				elif isinstance(emotion_val, dict):
					emotion_val = (
						emotion_val.get("emotion")
						or emotion_val.get("type")
						or emotion_val.get("name")
						or (list(emotion_val.values())[0] if emotion_val else "neutral")
					)
				else:
					emotion_val = str(emotion_val)
				emotion_val = str(emotion_val).lower()[:20]

				intensity_val = parsed.get("intensity")
				if intensity_val is None:
					intensity_val = 0.5
				elif isinstance(intensity_val, dict):
					intensity_val = (
						intensity_val.get("intensity") or intensity_val.get("value") or (list(intensity_val.values())[0] if intensity_val else 0.5)
					)
				try:
					intensity_val = float(intensity_val)
				except (ValueError, TypeError):
					intensity_val = 0.5

				category_val = parsed.get("category")
				if category_val is None:
					category_val = fallback_category
				elif isinstance(category_val, dict):
					category_val = (
						category_val.get("category")
						or category_val.get("type")
						or category_val.get("name")
						or (list(category_val.values())[0] if category_val else fallback_category)
					)
				else:
					category_val = str(category_val)
				category_val = str(category_val).lower().strip()

				if _is_template_echo(summary_val):
					logger.warning("[SLEEP ENGINE] Distiller echoed the prompt/format spec — discarding and retrying.")
					continue

				# V3 mechanical validation — guarantees live in code, not in the prompt.
				emotion_val = EMOTION_SYNONYMS.get(emotion_val, emotion_val)
				if emotion_val not in VALID_EMOTIONS:
					logger.warning(f"[DISTILL-V3] emotion '{emotion_val}' outside taxonomy — normalized to neutral.")
					emotion_val = "neutral"
				intensity_val = max(0.0, min(1.0, intensity_val))
				if category_val not in ("work", "social"):
					logger.warning(f"[DISTILL-V3] category '{category_val}' invalid — falling back to '{fallback_category}'.")
					category_val = fallback_category

				texture_val = parsed.get("texture", "")
				if not isinstance(texture_val, str):
					texture_val = ""
				min_texture_chars = getattr(cfg, "MIN_TEXTURE_CHARS", 100)
				if len(raw_content) < min_texture_chars or _is_template_echo(texture_val):
					texture_val = ""

				lang_val = parsed.get("lang", "")
				lang_val = str(lang_val).lower().strip()[:2] if isinstance(lang_val, str) else ""
				lang_val = _correct_lang_label(lang_val, raw_content)

				relics_val = _validate_relics(parsed.get("relics", []), raw_content)

				return {
					"summary": summary_val,
					"emotion": emotion_val,
					"intensity": intensity_val,
					"category": category_val,
					"texture": texture_val,
					"lang": lang_val,
					"relics": relics_val,
				}
			else:
				logger.warning(f"[SLEEP ENGINE] Samantha LLM output not JSON: {content[:100]}")

		except Exception as e:
			logger.warning(f"[SLEEP ENGINE] Distillation attempt {attempt + 1} failed: {e}")
			if attempt < max_retries - 1:
				time.sleep(backoff)

	logger.error("[SLEEP ENGINE] All distillation retries failed. Falling back.")
	return fallback


def synthesize_hub(summaries: List[str]) -> str:
	"""Creates the final Neocortex Hub Node from a chain of chunks."""
	combined = "\n".join([f"- {s}" for s in summaries])
	system_prompt = load_prompt_text("hub_synthesis_legacy_system.txt")
	user_prompt = _render_metabolism("hub_synthesis_legacy_user", chunks=combined)

	payload = json.dumps(
		{
			"task": "hub",
			"messages": [
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": user_prompt},
			],
			"temperature": 0.1,
			"max_tokens": 512,
			"seed": 777,
			"stop": ["<|im_end|>", "<|endoftext|>"],
		}
	).encode("utf-8")

	def _aggregate_fallback() -> str:
		if summaries:
			first_sum = summaries[0][:60]
			if len(summaries[0]) > 60:
				first_sum += "..."
			if len(summaries) > 1:
				last_sum = summaries[-1][:60]
				if len(summaries[-1]) > 60:
					last_sum += "..."
				return f"[Aggregated Memory Sequence ({len(summaries)} nodes)] {first_sum} -> {last_sum}"
			return f"[Aggregated Memory (1 node)] {first_sum}"
		return "[Aggregated Memory Sequence]"

	# Reuse existing transport detection
	url = getattr(cfg, "MLX_LM_URL", "http://127.0.0.1:8760/v1/chat/completions")
	opener = urllib.request.build_opener()
	req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
	try:
		with opener.open(req, timeout=60) as response:
			data = json.loads(response.read().decode())
			result = str(data["choices"][0]["message"]["content"].strip())
			if _is_template_echo(result):
				logger.warning("[SLEEP ENGINE] Hub synthesis echoed the prompt — using deterministic aggregate.")
				return _aggregate_fallback()
			return result
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Failed to synthesize hub: {e}")
		return _aggregate_fallback()


def distill_session_anchors(memory_manager, hub_summaries: List[str]) -> Optional[str]:
	"""
	Phase Gamma: Logical Distillation.
	Synthesizes technical decisions into a session architectural anchor.
	"""
	if not hub_summaries:
		return None

	logger.info(f"[SLEEP ENGINE] Commencing Logical Distillation of {len(hub_summaries)} technical hubs...")

	combined_hubs = "\n".join([f"- {s}" for s in hub_summaries])
	system_prompt = load_prompt_text("session_anchors.txt")
	user_prompt = _render_metabolism("session_anchors_user", hubs=combined_hubs)

	payload = json.dumps(
		{
			"task": "hub",
			"messages": [
				{"role": "system", "content": system_prompt},
				{"role": "user", "content": user_prompt},
			],
			"temperature": 0.1,
			"max_tokens": 1024,
			"seed": 888,
			"stop": ["<|im_end|>", "<|endoftext|>"],
		}
	).encode("utf-8")

	# Reuse the existing synth infrastructure
	url = getattr(cfg, "MLX_LM_URL", "http://127.0.0.1:8760/v1/chat/completions")
	opener = urllib.request.build_opener()
	req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

	try:
		with opener.open(req, timeout=90) as response:
			data = json.loads(response.read().decode())
			anchor_text = data["choices"][0]["message"]["content"].strip()

			if _is_template_echo(anchor_text):
				logger.warning("[SLEEP ENGINE] Session anchor echoed the prompt — not persisting.")
				return None

			# Persist the Anchor
			memory_manager.add_memory(
				collection="work_memories",
				text=f"[SESSION_ANCHOR] {anchor_text}",
				metadata={"lazarus_phase": "logic_distillation", "session_id": int(time.time())},
				color="emerald",  # Sovereign Emerald for architectural truth
				importance=9.0,
				emotion="nostalgia",  # Preserving the legacy of the session
			)
			return str(anchor_text)
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Logical Distillation failed: {e}")
		return None


# ─────────────────────── HUB v2 (ADR-AXON-001 / Eje 1) ───────────────────────

# Contrato de salida (AD-116, revisado 2026-11-09). Un hub es un índice
# acotado, pero **NUNCA se recorta por corte**: la compactación es SIEMPRE por
# síntesis (reescritura). Si el modelo no obedece, el texto se conserva entero y
# se marca `*_over_budget`; si un campo de metadata supera su límite duro
# (`MAX_METADATA_STR`), se PARTE en `texture_parts` conservando todo el
# contenido: primero por síntesis (partes coherentes), y solo como último
# recurso por segmentación lossless (sin perder un carácter). La ENTRADA nunca
# se trunca (map-reduce); `truncated` sigue significando "la ENTRADA se truncó".
HUB_TEXTURE_MAX_CHARS = 400
HUB_TITLE_MAX_CHARS = 120
HUB_PARTIAL_TEXTURE_MAX_CHARS = 250
HUB_PARTIAL_SUMMARY_MAX_CHARS = 700
HUB_CONTENT_MAX_CHARS = 4096  # espejo de CreateEngramRequest.content
HUB_TEXTURE_PARTS_MAX = 32


class HubBudgetError(RuntimeError):
	"""Un campo no cabe en el contrato y no se puede reducir sin cortar."""


def _hub_summary_target() -> int:
	return max(200, int(getattr(cfg, "SLEEP_HUB_SUMMARY_TARGET_CHARS", 900) or 900))


def _hub_texture_max() -> int:
	return max(100, int(getattr(cfg, "SLEEP_HUB_TEXTURE_MAX_CHARS", HUB_TEXTURE_MAX_CHARS) or HUB_TEXTURE_MAX_CHARS))


def _hub_texture_parts_max() -> int:
	return max(1, int(getattr(cfg, "SLEEP_HUB_TEXTURE_PARTS_MAX", HUB_TEXTURE_PARTS_MAX) or HUB_TEXTURE_PARTS_MAX))


def _hub_title_max() -> int:
	return max(40, int(getattr(cfg, "SLEEP_HUB_TITLE_MAX_CHARS", HUB_TITLE_MAX_CHARS) or HUB_TITLE_MAX_CHARS))


def _metadata_str_limit() -> int:
	"""Tope duro de un string de metadata, con margen para no rozar el esquema."""
	return max(256, int(getattr(cfg, "MAX_METADATA_STR", 1024) or 1024) - 64)


def split_text_lossless(text: str, limit: int) -> List[str]:
	"""Parte un texto en trozos <= limit SIN perder caracteres.

	No es compactación: es partición de un campo que no cabe en el esquema. La
	compactación real es la reescritura por síntesis. Corta en frontera de
	frase/palabra y, si no hay, en el límite exacto; los trozos concatenados
	reconstruyen el texto salvo espacios normalizados en las juntas.
	"""
	text = str(text or "").strip()
	limit = max(64, int(limit))
	if len(text) <= limit:
		return [text] if text else []
	parts: List[str] = []
	rest = text
	while len(rest) > limit:
		window = rest[:limit]
		best = -1
		for sep in (". ", "! ", "? ", ".\n", "!\n", "?\n", "… ", "; "):
			idx = window.rfind(sep)
			if idx > best:
				best = idx + 1  # incluye solo el signo; el espacio se consume con lstrip
		if best < int(limit * 0.5):
			idx = window.rfind(" ")
			best = idx if idx >= int(limit * 0.5) else limit
		parts.append(rest[:best].strip())
		rest = rest[best:].lstrip()
	if rest.strip():
		parts.append(rest.strip())
	return parts


def derive_hub_affect(chunks: List[Dict[str, Any]]) -> tuple:
	"""Dominant emotion (intensity-weighted frequency) + max intensity.

	Replaces the accidental legacy derivation (last chunk's emotion) with one
	that answers to the whole fragment history (ADR §2.2).
	"""
	if not chunks:
		return "neutral", 0.5
	weights: Dict[str, float] = {}
	for c in chunks:
		emotion = str(c.get("emotion", "neutral"))
		weights[emotion] = weights.get(emotion, 0.0) + float(c.get("intensity", 0.5))
	dominant = max(weights, key=lambda k: weights[k])
	return dominant, max(float(c.get("intensity", 0.5)) for c in chunks)


def merge_relics(chunks: List[Dict[str, Any]], cap: int = 5, max_len: int = 200) -> List[str]:
	"""Union of child relics, deduped and capped. Mechanical transport only —
	relics never pass through an LLM again after gen-0 extraction (T4)."""
	merged: List[str] = []
	for c in chunks:
		for relic in c.get("relics", []) or []:
			if isinstance(relic, str) and relic and len(relic) <= max_len and relic not in merged:
				merged.append(relic)
			if len(merged) >= cap:
				return merged
	return merged


def build_emotional_vector(fragment_affects: List[Dict[str, Any]]) -> Dict[str, Any]:
	"""Per-fragment affect history for the hub payload (ADR §2.2).

	fragment_affects entries: {child_id, emotion, intensity, category} collected
	at chunk-write time so ids and evaluations can never misalign.
	"""
	return {"fragments": fragment_affects}


# ── Hub synthesis: presupuesto por llamada + map-reduce jerárquico ───────────
# El límite de chars NO es el contexto del modelo: es el presupuesto de UNA
# llamada. Si el input no cabe, se trocea en lotes (map), se sintetizan hubs
# parciales y se reducen en árbol hasta un hub maestro. Los parciales quedan en
# `hub_partitions` para navegar el detalle. Fin del truncado silencioso.
HUB_PARTIAL_PROMPT = "hub_synthesis_v2_partial.txt"
HUB_SUMMARY_COMPACT_PROMPT = "hub_summary_compact.txt"
HUB_TEXTURE_COMPACT_PROMPT = "hub_texture_compact.txt"
HUB_TEXTURE_SPLIT_PROMPT = "hub_texture_split.txt"
HUB_PARTIAL_MAX_CHARS = 1500  # target orientativo del parcial; el árbol reduce lo que se pase (sin truncar)
HUB_MAP_REDUCE_MAX_LEVELS = 8


def hub_budget() -> int:
	"""Presupuesto de chars por llamada de síntesis de hub (configurable)."""
	return max(1000, int(getattr(cfg, "SLEEP_MAX_HUB_INPUT_CHARS", 8000) or 8000))


# ── Caché de parciales (map) ──────────────────────────────────────────────────
# El hub de una sesión viva se re-sintetiza cada noche porque llegan miembros
# nuevos. Sin caché, se vuelven a pagar TODOS los lotes (76 llamadas para la
# sesión de 578k). La caché guarda el resultado de cada lote clave por su
# contenido exacto: los lotes viejos no cambian (append-only) y solo se paga el
# lote frontera + los nuevos. Vive en el state dir (no en Qdrant: no infla el
# payload del hub). Se poda a los lotes de la pasada actual.
HUB_PARTIAL_CACHE_VERSION = "1"


def _partial_cache_meta() -> str:
	"""Huella del contrato del map: prompt, presupuesto y topes de parcial."""
	meta = "|".join(
		[
			HUB_PARTIAL_CACHE_VERSION,
			str(hub_budget()),
			str(int(getattr(cfg, "SLEEP_HUB_MAX_CHUNKS_PER_BATCH", 0) or 0)),
			str(HUB_PARTIAL_SUMMARY_MAX_CHARS),
			str(HUB_PARTIAL_TEXTURE_MAX_CHARS),
			load_prompt_text(HUB_PARTIAL_PROMPT),
		]
	)
	return hashlib.sha256(meta.encode("utf-8")).hexdigest()[:16]


def _partial_key(batch: List[Dict[str, Any]], meta: str) -> str:
	parts = []
	for c in batch:
		digest = hashlib.sha1(str(c.get("summary", "")).encode("utf-8")).hexdigest()[:8]
		parts.append(f"{c.get('_member_index')}:{digest}")
	return hashlib.sha1(("|".join(parts) + meta).encode("utf-8")).hexdigest()


def _partial_cache_file(namespace: str):
	from pathlib import Path

	from red_pill.core.paths import get_state_dir

	root = Path(get_state_dir()) / "hub_partials"
	root.mkdir(parents=True, exist_ok=True)
	return root / (hashlib.sha1(namespace.encode("utf-8")).hexdigest()[:16] + ".json")


def _load_partial_cache(namespace: str) -> Dict[str, Any]:
	if not namespace:
		return {}
	try:
		data = json.loads(_partial_cache_file(namespace).read_text(encoding="utf-8"))
		if data.get("version") == HUB_PARTIAL_CACHE_VERSION:
			return data.get("entries") or {}
	except Exception:
		pass
	return {}


def _save_partial_cache(namespace: str, entries: Dict[str, Any], meta: str) -> None:
	import os

	if not namespace:
		return
	try:
		path = _partial_cache_file(namespace)
		tmp = path.with_suffix(".tmp")
		tmp.write_text(json.dumps({"version": HUB_PARTIAL_CACHE_VERSION, "meta": meta, "entries": entries}, ensure_ascii=False), encoding="utf-8")
		os.replace(tmp, path)
	except Exception as e:
		logger.debug(f"[HUB-V2] no se pudo guardar la caché de parciales: {e}")


def hub_map_reduce_enabled() -> bool:
	return bool(getattr(cfg, "SLEEP_HUB_MAP_REDUCE_ENABLED", True))


def _chunk_summary(c: Dict[str, Any]) -> str:
	return str(c.get("summary", "") or "").strip()


def hub_texture_text(c: Dict[str, Any]) -> str:
	"""Textura legible: string si ya lo es; dict {theme, relics} si viene del engrama."""
	texture = c.get("texture")
	if isinstance(texture, dict):
		bits: List[str] = []
		theme = texture.get("theme")
		relics = texture.get("relics")
		if theme:
			bits.append(f"theme: {theme}")
		if relics:
			bits.append("relics: " + "; ".join(str(r) for r in relics))
		return " | ".join(bits).strip()
	return str(texture or "").strip()


def render_hub_items(items: List[Dict[str, Any]]) -> str:
	"""Prompt de un lote/sección: summaries + textures (formato HUB_V2)."""
	summaries = [_chunk_summary(c) for c in items if _chunk_summary(c)]
	textures = [hub_texture_text(c) for c in items if hub_texture_text(c)]
	user = "SUMMARIES:\n" + "\n".join(f"- {s}" for s in summaries)
	if textures:
		user += "\n\nTEXTURES:\n" + "\n".join(f"- {t}" for t in textures)
	return user


def _split_oversized_text(text: str, budget: int) -> List[str]:
	"""Parte un texto gigante en segmentos <= budget (segmentación, no truncado)."""
	limit = max(200, int(budget) - 32)
	if len(text) <= limit:
		return [text]
	segments: List[str] = []
	rest = text
	while len(rest) > limit:
		cut = rest.rfind("\n", 0, limit)
		if cut < limit // 2:
			cut = rest.rfind(". ", 0, limit)
			if cut >= limit // 2:
				cut += 1
		if cut < limit // 2:
			cut = limit
		segments.append(rest[:cut].strip())
		rest = rest[cut:].lstrip()
	if rest.strip():
		segments.append(rest.strip())
	return segments or [text[:limit]]


def partition_hub_items(items: List[Dict[str, Any]], budget: int, max_chunks: int = 0) -> List[List[Dict[str, Any]]]:
	"""Empaqueta fragmentos completos en lotes cuyo prompt renderizado quepa.

	Un fragmento individual que excede el presupuesto se parte por líneas/frases
	antes de empaquetar: se segmenta, nunca se descarta contenido.
	"""
	expanded: List[Dict[str, Any]] = []
	for item in items:
		single_len = len(render_hub_items([item]))
		if single_len <= budget:
			expanded.append(item)
			continue
		# Un item oversize se parte en items SEPARADOS por campo (summary y
		# texture), sin perder contenido. Así ningún prompt de reduce queda por
		# encima del presupuesto y no hace falta recortar (el giant de 736k
		# reventaba el maestro con un único parcial textura+summary > budget).
		summary_text = _chunk_summary(item)
		if summary_text:
			for seg in _split_oversized_text(summary_text, budget):
				clone = dict(item)
				clone["summary"] = seg
				clone["texture"] = ""
				expanded.append(clone)
		texture_text = hub_texture_text(item)
		if texture_text:
			for seg in _split_oversized_text(texture_text, budget):
				clone = dict(item)
				clone["summary"] = ""
				clone["texture"] = seg
				expanded.append(clone)
		if not summary_text and not texture_text:
			expanded.append(item)

	batches: List[List[Dict[str, Any]]] = []
	current: List[Dict[str, Any]] = []
	for item in expanded:
		candidate = current + [item]
		too_big = len(render_hub_items(candidate)) > budget
		too_many = bool(max_chunks) and len(candidate) > max_chunks
		if current and (too_big or too_many):
			batches.append(current)
			current = [item]
		else:
			current = candidate
	if current:
		batches.append(current)
	return batches


def _parse_hub_payload(content: str, fallback_lang: str = "") -> Optional[Dict[str, Any]]:
	"""Parsea el JSON del LLM; None si no hay JSON o el summary es eco/plantilla."""
	import re

	if not content:
		return None
	match = re.search(r"\{[\s\S]*\}", str(content))
	if not match:
		return None
	try:
		parsed = json.loads(_sanitize_llm_json(match.group(0)))
	except Exception:
		return None
	summary = str(parsed.get("summary") or "").strip()
	if not summary or _is_template_echo(summary):
		return None
	texture = str(parsed.get("texture") or "").strip()
	if _is_template_echo(texture):
		texture = ""
	lang = str(parsed.get("lang") or fallback_lang).lower().strip()[:2]
	return {
		"title": str(parsed.get("title") or "").strip(),
		"summary": summary,
		"texture": texture,
		"lang": lang,
	}


def _mechanical_partial(items: List[Dict[str, Any]], lang: str = "") -> Dict[str, Any]:
	"""Resumen mecánico de una parte si el LLM falla (nunca pierde el contenido).

	No se recorta: si es largo, el árbol de reducción lo segmenta y lo compacta.
	"""
	joined = "\n".join(_chunk_summary(c) for c in items if _chunk_summary(c))
	return {
		"title": "",
		"summary": joined,
		"texture": "",
		"lang": lang,
		"_is_fallback": True,
	}


def synthesize_hub_v2(
	chunks: List[Dict[str, Any]],
	override_prompt: Optional[str] = None,
	override_params: Optional[Dict[str, Any]] = None,
	config_yaml_path: Optional[str] = None,
	cache_namespace: str = "",
) -> Dict[str, Any]:
	"""Neocortex Hub v2: master summary AND merged texture, language-preserving.

	Si el prompt completo no cabe en `SLEEP_MAX_HUB_INPUT_CHARS`, SIEMPRE aplica
	map-reduce: lotes -> hubs parciales -> reducción en árbol. Nunca trunca la
	entrada. El maestro se compacta por reescritura si supera
	`SLEEP_HUB_SUMMARY_TARGET_CHARS`; si aun así sigue largo, se recorta en
	frontera de frase (contrato de salida, AD-116).
	"""
	from red_pill.core.providers import ProviderRegistry, SipInferenceProvider

	cfg_params = load_distiller_config(config_yaml_path).synthesize_hub_v2
	params = cfg_params.model_dump()
	if override_params:
		params.update(override_params)

	prompt_file = params.get("prompt_file", "hub_synthesis_v2.txt")
	system_prompt = load_prompt_text(prompt_file, override_text=override_prompt)
	partial_system_prompt = load_prompt_text(HUB_PARTIAL_PROMPT)
	compact_system_prompt = load_prompt_text(HUB_SUMMARY_COMPACT_PROMPT, fallback_prompt="")
	texture_compact_prompt = load_prompt_text(HUB_TEXTURE_COMPACT_PROMPT, fallback_prompt="")
	texture_split_prompt = load_prompt_text(HUB_TEXTURE_SPLIT_PROMPT, fallback_prompt="")

	langs = []
	for c in chunks:
		c_lang = str(c.get("lang", ""))
		if c_lang:
			langs.append(_correct_lang_label(c_lang, _chunk_summary(c) or hub_texture_text(c)))
	dominant_lang = max(set(langs), key=langs.count) if langs else ""

	if dominant_lang and "DOMINANT language" not in system_prompt:
		system_prompt += (
			f"\nIMPORTANT: write 'title', 'summary' and 'texture' in the DOMINANT language of the fragments (which is '{dominant_lang}')."
		)
	if dominant_lang and "DOMINANT language" not in partial_system_prompt:
		partial_system_prompt += (
			f"\nIMPORTANT: write 'title', 'summary' and 'texture' in the DOMINANT language of the fragments (which is '{dominant_lang}')."
		)

	full_prompt = render_hub_items(chunks)
	budget = hub_budget()
	max_chunks = int(getattr(cfg, "SLEEP_HUB_MAX_CHUNKS_PER_BATCH", 0) or 0)
	summary_target = max(200, int(getattr(cfg, "SLEEP_HUB_SUMMARY_TARGET_CHARS", 900) or 900))
	compact_attempts = max(0, int(getattr(cfg, "SLEEP_HUB_SUMMARY_COMPACT_ATTEMPTS", 2) or 0))
	texture_attempts = max(0, int(getattr(cfg, "SLEEP_HUB_TEXTURE_COMPACT_ATTEMPTS", compact_attempts) or compact_attempts))
	# Híbrido de modelos (AD-115): la decisión es POR LLAMADA y depende del
	# prompt que se envía, no del total de la sesión. Con map-reduce ninguna
	# llamada supera `SLEEP_MAX_HUB_INPUT_CHARS`, así que por defecto está OFF.
	large_threshold = max(0, int(getattr(cfg, "SLEEP_HUB_LARGE_INPUT_CHARS", 0) or 0))
	large_model = str(getattr(cfg, "SLEEP_HUB_LARGE_MODEL", "") or "").strip()
	large_prompt_file = str(getattr(cfg, "SLEEP_HUB_LARGE_PROMPT", "") or "").strip()
	large_enabled = bool(
		large_threshold and large_model and str(params.get("provider_alias") or "") == "sip"
	)
	large_system_prompt = ""
	if large_enabled and large_prompt_file and not override_prompt and prompt_file == "hub_synthesis_v2.txt":
		large_system_prompt = load_prompt_text(large_prompt_file)
		if dominant_lang and "DOMINANT language" not in large_system_prompt:
			large_system_prompt += (
				f"\nIMPORTANT: write 'title', 'summary' and 'texture' in the DOMINANT language of the fragments (which is '{dominant_lang}')."
			)
	# Auditoría del path grande efectivo (se rellena en la llamada maestra).
	large_used = {"flag": False, "model": "", "prompt": ""}

	def _make_fallback() -> Dict[str, Any]:
		fallback_text = synthesize_hub([_chunk_summary(c) for c in chunks if _chunk_summary(c)])
		return {"title": "", "summary": fallback_text, "texture": "", "lang": dominant_lang, "_is_fallback": True, "truncated": False}

	provider_alias = params.get("provider_alias", "sip")
	temperature = float(params.get("temperature", 0.1))
	forced_model = str(params.get("model") or "").strip()
	call_extra = {
		key: params[key]
		for key in ("max_tokens", "top_p", "top_k", "min_p", "thinking", "reasoning_effort", "chat_template_kwargs")
		if params.get(key) is not None
	}
	try:
		try:
			provider = ProviderRegistry.get_inference_provider(provider_alias)
		except RuntimeError:
			provider = ProviderRegistry.get_inference_provider()
	except Exception as e:
		logger.warning(f"[HUB-V2] No inference provider ({e}). Falling back to legacy concatenation.")
		return _make_fallback()

	def _call(system: str, user: str, *, master: bool = False) -> str:
		use_large = bool(large_enabled and len(user) >= large_threshold)
		call_system = system
		call_prompt_file = prompt_file
		if use_large and master and large_system_prompt:
			call_system = large_system_prompt
			call_prompt_file = large_prompt_file
		call_model = (
			forced_model
			or str(getattr(provider, "model", "") or "")
			or (large_model if use_large and isinstance(provider, SipInferenceProvider) else "")
		)
		if master:
			large_used.update({"flag": bool(call_model), "model": call_model, "prompt": call_prompt_file})
		call_temperature = temperature
		extra = dict(call_extra)
		if call_model and bool(params.get("use_model_sampling")):
			# La receta del perfil manda cuando el modelo se fija por llamada:
			# es la diferencia entre Spark hub a temp 1.0/top_k 0 (993 chars)
			# y el default 0.1 (4.418 chars, rechazado por el contrato).
			from red_pill.core.model_registry import ModelRegistry

			profile = ModelRegistry.get_profile(call_model) or {}
			if profile.get("temperature") is not None:
				call_temperature = float(profile["temperature"])
			for key in ("top_p", "top_k", "min_p"):
				value = (profile.get("sampling") or {}).get(key)
				if value is not None:
					extra[key] = value
		try:
			return str(
				provider.generate(
					prompt=user,
					messages=[{"role": "system", "content": call_system}, {"role": "user", "content": user}],
					temperature=call_temperature,
					# AD-030: el proveedor SIP defaultea a `conversation`. El hub
					# debe resolverse por SU task (modelo/thinking/max_tokens).
					task="hub",
					# AD-115: el híbrido fija el modelo por llamada; vacío = task.
					**({"model": call_model} if call_model else {}),
					# Tope de generación + conducta oficial (thinking/effort/
					# samplers) por llamada, sin recorte de texto.
					**extra,
				)
			)
		except Exception as e:
			logger.warning(f"[HUB-V2] LLM call failed ({e}).")
			return ""

	compaction_stats = {"calls": 0, "latency_s": 0.0}

	def _compact_with(text: str, system_prompt: str, target: int, field: str) -> str:
		"""Reescribe por SÍNTESIS (nunca recorta) para acercar el texto al target."""
		if not system_prompt or len(text) <= target:
			return text
		system = system_prompt.replace("{target}", str(target))
		t0 = time.time()
		content = _call(system, text).strip()
		compaction_stats["calls"] += 1
		compaction_stats["latency_s"] += time.time() - t0
		if not content:
			return text
		if content.startswith("{"):
			parsed_json = _parse_hub_payload(content, dominant_lang)
			if parsed_json and parsed_json.get(field):
				content = str(parsed_json[field])
		content = content.strip().strip('"').strip()
		return content or text

	def _split_texture_with_synthesis(text: str, target: int) -> Optional[List[str]]:
		"""Parte una textura que no cabe en partes coherentes por SÍNTESIS.

		No es un corte: el modelo reescribe la nota como N partes completas,
		conservando todas las ideas. Si la respuesta no conserva al menos el 85%
		del texto (señal de que resumió en vez de partir), se descarta.
		"""
		if not texture_split_prompt:
			return None
		system = texture_split_prompt.replace("{target}", str(target))
		t0 = time.time()
		content = _call(system, text).strip()
		compaction_stats["calls"] += 1
		compaction_stats["latency_s"] += time.time() - t0
		if not content:
			return None
		match = re.search(r"\{[\s\S]*\}", content)
		if not match:
			return None
		try:
			parsed = json.loads(_sanitize_llm_json(match.group(0)))
		except Exception:
			return None
		raw_parts = parsed.get("parts")
		if not isinstance(raw_parts, list):
			return None
		parts = [str(p).strip() for p in raw_parts if str(p).strip()]
		hard = _metadata_str_limit()
		if not parts or any(len(p) > hard for p in parts):
			return None
		if len(parts) > _hub_texture_parts_max():
			return None
		if sum(len(p) for p in parts) < int(len(text) * 0.85):
			return None
		return parts

	def _fit_texture(texture: str) -> Dict[str, Any]:
		"""Ajusta la textura: síntesis → partes por síntesis → partes lossless.

		Regla del Operador: nunca se corta. Si la síntesis no la reduce, se
		conserva entera (marcada); si supera el tope duro de metadata, se parte
		sin perder contenido.
		"""
		target = _hub_texture_max()
		hard = _metadata_str_limit()
		compacted = False
		for _ in range(texture_attempts):
			if len(texture) <= target:
				break
			candidate = _compact_with(texture, texture_compact_prompt, target, "texture")
			if not candidate or len(candidate) >= len(texture):
				break
			texture = candidate
			compacted = True
		result: Dict[str, Any] = {
			"texture": texture,
			"texture_compacted": compacted,
			"texture_over_target": len(texture) > target,
			"texture_split": False,
			"texture_split_fallback": False,
		}
		if len(texture) <= hard:
			return result
		parts = _split_texture_with_synthesis(texture, target)
		fallback = False
		if not parts:
			if not bool(getattr(cfg, "SLEEP_HUB_TEXTURE_SPLIT_LOSSLESS_FALLBACK", True)):
				raise HubBudgetError(
					f"texture {len(texture)} chars no cabe y la partición por síntesis falló; "
					"no se recorta: la sesión se reintenta en otro ciclo"
				)
			# Último recurso: segmentación lossless (no se pierde un carácter).
			parts = split_text_lossless(texture, hard)
			fallback = True
		if not parts or len(parts) > _hub_texture_parts_max():
			raise HubBudgetError(
				f"texture {len(texture)} chars no cabe en {_hub_texture_parts_max()} partes de {hard}"
			)
		result.update(
			{
				"texture": "",
				"texture_parts": parts,
				"texture_over_target": True,
				"texture_split": True,
				"texture_split_fallback": fallback,
			}
		)
		return result

	def _finalize(hub: Dict[str, Any]) -> Dict[str, Any]:
		"""Impone el contrato de salida del hub SIN CORTAR.

		Toda reducción es por síntesis (reescritura). Si el modelo no obedece,
		el texto se conserva entero y se marca `*_over_budget`; si un campo de
		metadata no cabe, se parte en `texture_parts`. `truncated` sigue
		significando "la ENTRADA se truncó" y por tanto es siempre False aquí.
		"""
		title_max = _hub_title_max()
		title = str(hub.get("title") or "").strip()
		hub["title"] = title
		hub["title_over_target"] = len(title) > title_max

		original = str(hub.get("summary") or "")
		current = original
		summary_compacted = False
		for _ in range(compact_attempts):
			if len(current) <= summary_target:
				break
			compacted = _compact_with(current, compact_system_prompt, summary_target, "summary")
			if not compacted or len(compacted) >= len(current):
				break
			current = compacted
			summary_compacted = True
		hub["summary"] = current
		hub["summary_compacted"] = summary_compacted
		hub["summary_over_budget"] = len(current) > summary_target

		body_len = len(title) + (1 if title else 0) + len(current)
		if body_len > HUB_CONTENT_MAX_CHARS:
			raise HubBudgetError(
				f"hub body {body_len} chars > {HUB_CONTENT_MAX_CHARS} (summary {len(current)}); "
				"no se recorta: la sesión se reintenta en otro ciclo"
			)

		texture = str(hub.get("texture") or "").strip()
		hub.update(_fit_texture(texture))
		texture_len = len(hub.get("texture") or "") + sum(len(p) for p in hub.get("texture_parts") or [])

		hub["truncated"] = False
		hub["output_chars"] = body_len + texture_len + 1
		hub["compaction_calls"] = compaction_stats["calls"]
		hub["compaction_latency_s"] = round(compaction_stats["latency_s"], 2)
		# Auditoría del híbrido: modelo/prompt efectivos de la llamada maestra.
		hub["large_path"] = bool(large_used["flag"])
		hub["model"] = large_used["model"] if large_used["flag"] else ""
		hub["prompt_file"] = large_used["prompt"] or prompt_file
		return hub

	# Caso normal: cabe en una llamada (sin truncar; si no cupiera, map-reduce).
	if len(full_prompt) <= budget:
		parsed = _parse_hub_payload(_call(system_prompt, full_prompt, master=True), dominant_lang)
		if parsed is None:
			return _make_fallback()
		parsed["input_chars"] = len(full_prompt)
		return _finalize(parsed)

	# Map: lotes que quepan, cada uno con su propio resumen denso. Los parciales
	# son TRANSITORIOS (alimentan la reducción); no se persisten en el hub. Su
	# tamaño se acota para que el árbol no crezca con el número de lotes.
	pack_budget = max(500, budget - 96)  # margen para la cabecera PART i/N
	batches = partition_hub_items(chunks, pack_budget, max_chunks)
	cache_meta = _partial_cache_meta()
	cache = _load_partial_cache(cache_namespace)
	used_cache: Dict[str, Any] = {}
	cache_hits = 0
	partials: List[Dict[str, Any]] = []
	partition_ranges: List[List[int]] = []
	for idx, batch in enumerate(batches):
		key = _partial_key(batch, cache_meta)
		cached = cache.get(key)
		if isinstance(cached, dict) and cached.get("summary"):
			parsed = dict(cached)
			cache_hits += 1
		else:
			header = f"PART {idx + 1}/{len(batches)} of the chronological fragments of ONE interaction.\n\n"
			parsed = _parse_hub_payload(_call(partial_system_prompt, header + render_hub_items(batch)), dominant_lang)
			if parsed is None:
				parsed = _mechanical_partial(batch, dominant_lang)
		used_cache[key] = parsed
		partials.append(parsed)
		positions = [int(it["_member_index"]) for it in batch if "_member_index" in it]
		partition_ranges.append([min(positions), max(positions) + 1] if positions else [0, 0])
	_save_partial_cache(cache_namespace, used_cache, cache_meta)
	if cache_hits:
		logger.info(f"[HUB-V2] parciales reutilizados: {cache_hits}/{len(batches)} (caché {cache_namespace or 'local'})")

	# Reduce: árbol hasta que el prompt de los parciales quepa.
	current = partials
	levels = 0
	while True:
		prompt = render_hub_items(current)
		if len(prompt) <= budget or len(current) == 1:
			final = _parse_hub_payload(_call(system_prompt, prompt, master=True), dominant_lang)
			if final is None:
				return _make_fallback()
			break
		groups = partition_hub_items(current, pack_budget, max_chunks)
		next_level: List[Dict[str, Any]] = []
		for group in groups:
			parsed = _parse_hub_payload(_call(system_prompt, render_hub_items(group)), dominant_lang)
			if parsed is None:
				parsed = _mechanical_partial(group, dominant_lang)
			next_level.append(parsed)
		current = next_level
		levels += 1
		if levels > HUB_MAP_REDUCE_MAX_LEVELS:
			return _make_fallback()

	final["hierarchical"] = True
	final["partition_count"] = len(partials)
	final["partial_cache_hits"] = cache_hits
	final["partial_cache_total"] = len(batches)
	# Navegación barata: rangos de índices sobre los miembros ORDENADOS por
	# created_at. El texto de los parciales no se persiste (AD-116).
	final["partition_ranges"] = partition_ranges
	final["partitions"] = [
		{
			"index": i + 1,
			"total": len(partials),
			"summary": p["summary"],
			"texture": p.get("texture", ""),
			"lang": p.get("lang", ""),
		}
		for i, p in enumerate(partials)
	]
	final["map_reduce_levels"] = levels
	final["input_chars"] = len(full_prompt)
	return _finalize(final)


def classify_category(
	text: str,
	override_prompt: Optional[str] = None,
	override_params: Optional[Dict[str, Any]] = None,
	config_yaml_path: Optional[str] = None,
) -> Optional[str]:
	"""Lightweight work/social re-classification for the RevisionPhase (R2).

	Returns None on any failure so the caller leaves the engram unmarked and
	a later cycle retries — never guess on a broken call.
	"""
	import re

	from red_pill.core.providers import ProviderRegistry

	cfg_params = load_distiller_config(config_yaml_path).classify_category
	params = cfg_params.model_dump()
	if override_params:
		params.update(override_params)

	prompt_file = params.get("prompt_file", "classify_category.txt")
	system_prompt = load_prompt_text(prompt_file, override_text=override_prompt)
	provider_alias = params.get("provider_alias", "sip")
	temperature = float(params.get("temperature", 0.0))

	try:
		try:
			provider = ProviderRegistry.get_inference_provider(provider_alias)
		except RuntimeError:
			provider = ProviderRegistry.get_inference_provider()
		content = provider.generate(
			prompt=f"DATA:\n{text}",
			messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"DATA:\n{text}"}],
			temperature=temperature,
			response_format={"type": "json_object"},
		)
		match = re.search(r"\{[\s\S]*\}", content)
		if not match:
			return None
		category = str(json.loads(_sanitize_llm_json(match.group(0))).get("category", "")).lower().strip()
		return category if category in ("work", "social") else None
	except Exception as e:
		logger.warning(f"[DISTILLER] classify_category failed: {e}")
		return None


def audit_engram_quality(
	summary_text: str,
	agent_name: Optional[str] = None,
	operator_name: Optional[str] = None,
	override_prompt: Optional[str] = None,
	override_params: Optional[Dict[str, Any]] = None,
	config_yaml_path: Optional[str] = None,
) -> bool:
	"""Delegates to the LLM the semantic evaluation of whether an engram summary
	suffers from legacy 3rd-person clinical detachment or is already an authentic 1st-person memory.
	Returns True if it needs re-distillation, False if clean.
	"""
	import re

	agent_name = agent_name or _instance_names()[0]
	operator_name = operator_name or _instance_names()[1]
	from red_pill.core.providers import ProviderRegistry

	system_prompt = load_prompt_text(
		"engram_quality_auditor.txt", override_text=override_prompt, static={"agent_name": agent_name, "operator_name": operator_name}
	)

	user_prompt = f"MEMORY SUMMARY TO AUDIT:\n{summary_text}"

	try:
		try:
			provider = ProviderRegistry.get_inference_provider("sip")
		except RuntimeError:
			provider = ProviderRegistry.get_inference_provider()

		content = provider.generate(
			prompt=user_prompt,
			messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
			temperature=0.1,
			response_format={"type": "json_object"},
		)
		match = re.search(r"\{[\s\S]*\}", content)
		if match:
			parsed = json.loads(_sanitize_llm_json(match.group(0)))
			needs_redist = parsed.get("needs_redistillation")
			if isinstance(needs_redist, bool):
				return needs_redist
	except Exception as e:
		logger.warning(f"[ENGRAM-AUDITOR] Quality audit failed: {e}. Falling back to default.")

	return True
