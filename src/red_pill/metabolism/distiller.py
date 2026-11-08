"""LLM distillation primitives: raw interactions -> engrams, hubs, session anchors.

Extracted from sleep.py per ADR-SLEEP-001. GPU/LLM-facing (uses the inference
provider); the sleep orchestrator gates these on free VRAM.
"""

import json
import logging
import os
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

HUB_TEXTURE_MAX_CHARS = 800


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
HUB_PARTIAL_MAX_CHARS = 1500
HUB_MAP_REDUCE_MAX_LEVELS = 8


def hub_budget() -> int:
	"""Presupuesto de chars por llamada de síntesis de hub (configurable)."""
	return max(1000, int(getattr(cfg, "SLEEP_MAX_HUB_INPUT_CHARS", 8000) or 8000))


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
		segments = _split_oversized_text(_chunk_summary(item), budget)
		for idx, seg in enumerate(segments):
			clone = dict(item)
			clone["summary"] = seg
			# La textura pertenece al fragmento, no a cada segmento: va en el primero.
			clone["texture"] = item.get("texture") if idx == 0 else ""
			expanded.append(clone)

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
	if len(texture) > HUB_TEXTURE_MAX_CHARS:
		logger.warning(
			f"[HUB-V2] texture over {HUB_TEXTURE_MAX_CHARS} chars ({len(texture)}) — truncating (compression instruction ignored)."
		)
		texture = texture[:HUB_TEXTURE_MAX_CHARS]
	lang = str(parsed.get("lang") or fallback_lang).lower().strip()[:2]
	return {
		"title": str(parsed.get("title") or "").strip(),
		"summary": summary,
		"texture": texture,
		"lang": lang,
	}


def _mechanical_partial(items: List[Dict[str, Any]], lang: str = "") -> Dict[str, Any]:
	"""Resumen mecánico de una parte si el LLM falla (nunca pierde el contenido)."""
	joined = "\n".join(_chunk_summary(c) for c in items if _chunk_summary(c))
	return {
		"title": "",
		"summary": joined[:HUB_PARTIAL_MAX_CHARS],
		"texture": "",
		"lang": lang,
		"_is_fallback": True,
	}


def synthesize_hub_v2(
	chunks: List[Dict[str, Any]],
	override_prompt: Optional[str] = None,
	override_params: Optional[Dict[str, Any]] = None,
	config_yaml_path: Optional[str] = None,
) -> Dict[str, Any]:
	"""Neocortex Hub v2: master summary AND merged texture, language-preserving.

	Si el prompt completo no cabe en `SLEEP_MAX_HUB_INPUT_CHARS`, aplica
	map-reduce: lotes -> hubs parciales -> reducción en árbol. El resultado
	maestro incluye `partitions` (nivel intermedio) para navegar el detalle.
	Sin map-reduce (flag OFF), mantiene el recorte como última red — y lo marca
	en `truncated`.
	"""
	from red_pill.core.providers import ProviderRegistry

	cfg_params = load_distiller_config(config_yaml_path).synthesize_hub_v2
	params = cfg_params.model_dump()
	if override_params:
		params.update(override_params)

	prompt_file = params.get("prompt_file", "hub_synthesis_v2.txt")
	system_prompt = load_prompt_text(prompt_file, override_text=override_prompt)
	partial_system_prompt = load_prompt_text(HUB_PARTIAL_PROMPT) if hub_map_reduce_enabled() else system_prompt

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

	def _make_fallback() -> Dict[str, Any]:
		fallback_text = synthesize_hub([_chunk_summary(c) for c in chunks if _chunk_summary(c)])
		return {"title": "", "summary": fallback_text, "texture": "", "lang": dominant_lang, "_is_fallback": True, "truncated": False}

	provider_alias = params.get("provider_alias", "sip")
	temperature = float(params.get("temperature", 0.1))
	try:
		try:
			provider = ProviderRegistry.get_inference_provider(provider_alias)
		except RuntimeError:
			provider = ProviderRegistry.get_inference_provider()
	except Exception as e:
		logger.warning(f"[HUB-V2] No inference provider ({e}). Falling back to legacy concatenation.")
		return _make_fallback()

	def _call(system: str, user: str) -> str:
		try:
			return str(
				provider.generate(
					prompt=user,
					messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
					temperature=temperature,
				)
			)
		except Exception as e:
			logger.warning(f"[HUB-V2] LLM call failed ({e}).")
			return ""

	# Caso normal: cabe en una llamada (comportamiento histórico).
	if not hub_map_reduce_enabled() or len(full_prompt) <= budget:
		user_prompt = full_prompt
		truncated = False
		if len(user_prompt) > budget:
			logger.warning(
				f"[DISTILLER] Hub synthesis input ({len(user_prompt)} chars) exceeds context safety limit ({budget} chars). Truncating user prompt."
			)
			user_prompt = user_prompt[:budget]
			truncated = True
		parsed = _parse_hub_payload(_call(system_prompt, user_prompt), dominant_lang)
		if parsed is None:
			return _make_fallback()
		parsed["truncated"] = truncated
		parsed["input_chars"] = len(full_prompt)
		return parsed

	# Map: lotes que quepan, cada uno con su propio resumen denso.
	pack_budget = max(500, budget - 96)  # margen para la cabecera PART i/N
	batches = partition_hub_items(chunks, pack_budget, max_chunks)
	partials: List[Dict[str, Any]] = []
	for idx, batch in enumerate(batches):
		header = f"PART {idx + 1}/{len(batches)} of the chronological fragments of ONE interaction.\n\n"
		parsed = _parse_hub_payload(_call(partial_system_prompt, header + render_hub_items(batch)), dominant_lang)
		if parsed is None:
			parsed = _mechanical_partial(batch, dominant_lang)
		parsed["summary"] = str(parsed.get("summary") or "")[:HUB_PARTIAL_MAX_CHARS]
		parsed["texture"] = str(parsed.get("texture") or "")[:HUB_TEXTURE_MAX_CHARS]
		partials.append(parsed)

	# Reduce: árbol hasta que el prompt de los parciales quepa.
	current = partials
	levels = 0
	while True:
		prompt = render_hub_items(current)
		if len(prompt) <= budget or len(current) == 1:
			final = _parse_hub_payload(_call(system_prompt, prompt), dominant_lang)
			if final is None:
				return _make_fallback()
			break
		groups = partition_hub_items(current, pack_budget, max_chunks)
		next_level: List[Dict[str, Any]] = []
		for group in groups:
			parsed = _parse_hub_payload(_call(system_prompt, render_hub_items(group)), dominant_lang)
			if parsed is None:
				parsed = _mechanical_partial(group, dominant_lang)
			parsed["summary"] = str(parsed.get("summary") or "")[:HUB_PARTIAL_MAX_CHARS]
			parsed["texture"] = str(parsed.get("texture") or "")[:HUB_TEXTURE_MAX_CHARS]
			next_level.append(parsed)
		current = next_level
		levels += 1
		if levels > HUB_MAP_REDUCE_MAX_LEVELS:
			return _make_fallback()

	final["hierarchical"] = True
	final["partition_count"] = len(partials)
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
	final["truncated"] = False
	return final


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
