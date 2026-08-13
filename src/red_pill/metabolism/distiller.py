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
from typing import Any, Dict, List, Optional

import yaml

import red_pill.config as cfg
from red_pill.metabolism.chunker import _is_template_echo, _sanitize_llm_json
from red_pill.metabolism.schemas_params import DistillerParamsConfig

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


def load_prompt_text(filename: str, fallback_prompt: str = "", override_text: Optional[str] = None) -> str:
	"""Carga el texto del prompt desde archivo externo .txt con soporte para override."""
	if override_text:
		return override_text
	path = os.path.join(PROMPTS_DIR, filename)
	if os.path.exists(path):
		try:
			with open(path, "r", encoding="utf-8") as f:
				content = f.read().strip()
				if content:
					return content
		except Exception as e:
			logger.warning(f"[DISTILLER] Error leyendo archivo de prompt '{path}': {e}.")
	return fallback_prompt


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
	detected = _detect_source_lang(source_text)
	if detected and detected != llm_lang:
		return detected
	return llm_lang


def _resolve_prompt_for_profile(profile_name: Optional[str] = None) -> Optional[str]:
	"""Look up the per-model `prompt_file` field from model_profiles.yaml.

	If the active profile (from MINION_PROFILE env var, or `profile_name` if
	passed) declares a `prompt_file`, return it. Otherwise return None (the
	caller will fall back to the default `distiller_v3.txt`).

	The bake-off 2026-08-13 established that smaller models (3-4B) need
	MODE B (`distiller_v3_voice.txt`) for stable deixis/JSON, while
	granite_8b works better with the lax `distiller_v3.txt`. This helper
	implements that mapping at runtime without requiring callers to know
	which prompt each model prefers.
	"""
	import os

	if profile_name is None:
		profile_name = os.getenv("MINION_PROFILE")
	if not profile_name:
		return None
	try:
		from red_pill.core.model_registry import ModelRegistry

		profile = ModelRegistry.get_profile(profile_name)
	except Exception:
		return None
	prompt_file = profile.get("prompt_file")
	return prompt_file if isinstance(prompt_file, str) and prompt_file else None


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

	prompt_file = params.get("prompt_file")
	if not prompt_file:
		# Fall back to per-model prompt from the active profile (bake-off
		# 2026-08-13). If the profile doesn't declare one, default to v3.
		prompt_file = _resolve_prompt_for_profile() or "distiller_v3.txt"
	system_prompt = load_prompt_text(prompt_file, override_text=override_prompt)

	agent_name = "Aleth"
	operator_name = "Joan"
	system_prompt = system_prompt.format(agent_name=agent_name, operator_name=operator_name)

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
	prompt = (
		"Synthesize these chronological memory chunks into a single, cohesive master summary. Be highly concise but preserve key facts and overall narrative trajectory.\n\nCHUNKS:\n"
		+ combined
	)

	payload = json.dumps(
		{
			"model": "distillation",
			"messages": [
				{
					"role": "system",
					"content": (
						"[Refraction: NEOCORTEX_SYNTHESIS] Style: Highly concise, descriptive. "
						"Focus: Synthesize memory chunks into a master summary. "
						"Format requirements:\n"
						"1. Start the output with a descriptive, contextual title in square brackets "
						"(e.g., '[Asymmetric Logic Loss Integration on BitNet Logic Specialist]' or '[Refactoring Ferrari Protocol Silence Latch]').\n"
						"2. Follow with a newline, then the summary.\n"
						"Constraints:\n"
						"- Do not use generic titles like '[Memory Synthesis]' or '[Session Summary]'.\n"
						"- Be highly specific about core technical actions, errors fixed, or philosophical/personal themes.\n"
						"- Output ONLY the title and summary string without any introductory phrases or markdown."
					),
				},
				{"role": "user", "content": prompt},
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
	prompt = (
		"Analyze these technical memory hubs from the current session. "
		"Identify key architectural decisions, dependency changes, and the core rationale. "
		"Synthesize into a 'Session Anchor' that explains WHY changes were made, not just WHAT. "
		"Be concise but technically precise.\n\nHUBS:\n" + combined_hubs
	)

	payload = json.dumps(
		{
			"model": "distillation",
			"messages": [
				{
					"role": "system",
					"content": "[Refraction: CHIEF_ARCHITECT_SYNTHESIS] Style: Technical, direct. Focus: Analyze session memory hubs, identify key architectural decisions/rationale, and output ONLY the architectural session anchor string.",
				},
				{"role": "user", "content": prompt},
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


def synthesize_hub_v2(
	chunks: List[Dict[str, Any]],
	override_prompt: Optional[str] = None,
	override_params: Optional[Dict[str, Any]] = None,
	config_yaml_path: Optional[str] = None,
) -> Dict[str, Any]:
	"""Neocortex Hub v2: master summary AND merged texture, language-preserving.

	Falls back to the legacy synthesize_hub() text with empty texture if the
	structured call fails — the hub must always exist.
	"""
	import re

	from red_pill.core.providers import ProviderRegistry

	cfg_params = load_distiller_config(config_yaml_path).synthesize_hub_v2
	params = cfg_params.model_dump()
	if override_params:
		params.update(override_params)

	prompt_file = params.get("prompt_file", "hub_synthesis_v2.txt")
	system_prompt = load_prompt_text(prompt_file, override_text=override_prompt)

	summaries = [str(c.get("summary", "")) for c in chunks if c.get("summary")]
	textures = [str(c.get("texture", "")) for c in chunks if c.get("texture")]
	langs = []
	for c in chunks:
		c_lang = str(c.get("lang", ""))
		if c_lang:
			langs.append(_correct_lang_label(c_lang, str(c.get("summary", "")) or str(c.get("texture", ""))))
	dominant_lang = max(set(langs), key=langs.count) if langs else ""

	if dominant_lang and "DOMINANT language" not in system_prompt:
		system_prompt += (
			f"\nIMPORTANT: write 'title', 'summary' and 'texture' in the DOMINANT language of the fragments (which is '{dominant_lang}')."
		)

	user_prompt = "SUMMARIES:\n" + "\n".join(f"- {s}" for s in summaries)
	if textures:
		user_prompt += "\n\nTEXTURES:\n" + "\n".join(f"- {t}" for t in textures)

	max_hub_input_chars = getattr(cfg, "SLEEP_MAX_HUB_INPUT_CHARS", 8000)
	if len(user_prompt) > max_hub_input_chars:
		logger.warning(
			f"[DISTILLER] Hub synthesis input ({len(user_prompt)} chars) exceeds context safety limit ({max_hub_input_chars} chars). Truncating user prompt."
		)
		user_prompt = user_prompt[:max_hub_input_chars]

	def _make_fallback() -> Dict[str, Any]:
		fallback_text = synthesize_hub(summaries)
		return {"title": "", "summary": fallback_text, "texture": "", "lang": dominant_lang, "_is_fallback": True}

	provider_alias = params.get("provider_alias", "sip")
	temperature = float(params.get("temperature", 0.1))

	try:
		try:
			provider = ProviderRegistry.get_inference_provider(provider_alias)
		except RuntimeError:
			provider = ProviderRegistry.get_inference_provider()
		content = provider.generate(
			prompt=user_prompt,
			messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
			temperature=temperature,
		)
		match = re.search(r"\{[\s\S]*\}", content)
		if not match:
			return _make_fallback()  # type: ignore
		parsed = json.loads(_sanitize_llm_json(match.group(0)))
		summary_val = str(parsed.get("summary") or "").strip()
		if not summary_val or _is_template_echo(summary_val):
			return _make_fallback()  # type: ignore
		texture_val = str(parsed.get("texture") or "").strip()
		if _is_template_echo(texture_val):
			texture_val = ""
		if len(texture_val) > HUB_TEXTURE_MAX_CHARS:
			logger.warning(
				f"[HUB-V2] texture over {HUB_TEXTURE_MAX_CHARS} chars ({len(texture_val)}) — truncating (compression instruction ignored)."
			)
			texture_val = texture_val[:HUB_TEXTURE_MAX_CHARS]
		lang_val = str(parsed.get("lang") or dominant_lang).lower().strip()[:2]
		lang_val = _correct_lang_label(lang_val, user_prompt)
		return {
			"title": str(parsed.get("title") or "").strip(),
			"summary": summary_val,
			"texture": texture_val,
			"lang": lang_val,
		}
	except Exception as e:
		logger.warning(f"[HUB-V2] LLM synthesis failed ({e}). Falling back to legacy concatenation.")
		return _make_fallback()


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
	agent_name: str = "Aleth",
	operator_name: str = "Joan",
	override_prompt: Optional[str] = None,
	override_params: Optional[Dict[str, Any]] = None,
	config_yaml_path: Optional[str] = None,
) -> bool:
	"""Delegates to the LLM the semantic evaluation of whether an engram summary
	suffers from legacy 3rd-person clinical detachment or is already an authentic 1st-person memory.
	Returns True if it needs re-distillation, False if clean.
	"""
	import re

	from red_pill.core.providers import ProviderRegistry

	system_prompt = load_prompt_text("engram_quality_auditor.txt", override_text=override_prompt)
	system_prompt = system_prompt.format(agent_name=agent_name, operator_name=operator_name)

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
