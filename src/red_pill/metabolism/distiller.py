"""LLM distillation primitives: raw interactions -> engrams, hubs, session anchors.

Extracted from sleep.py per ADR-SLEEP-001. GPU/LLM-facing (uses the inference
provider); the sleep orchestrator gates these on free VRAM.
"""

import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

import red_pill.config as cfg
from red_pill.metabolism.chunker import _is_template_echo, _sanitize_llm_json

logger = logging.getLogger(__name__)


# Closed emotional taxonomy the erosion/affect stack understands. Anything the
# distiller invents outside this list is normalized to neutral (and logged).
VALID_EMOTIONS = frozenset(
	{"joy", "sadness", "fear", "disgust", "anger", "anxiety", "envy", "embarrassment", "ennui", "nostalgia", "neutral"}
)


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


def distill_engram(raw_content: str, fallback_category: str = "social") -> Dict[str, Any]:
	"""
	Lazarus Phase 2: Consolidation (Sleep) & Affective Preservation
	Now driven by Samantha's cognitive depth and ProviderRegistry.
	"""
	import re
	import time

	from red_pill.core.providers import ProviderRegistry

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

	# COGNITIVE_DISTILLER_V3 (unified, key-ordered). The metadata keys are emitted
	# BEFORE 'texture' on purpose: the workshop showed that committing to
	# emotion/intensity/category first anchors the texture against hallucination,
	# while a texture-first framing inflates intensity and blurs category.
	system_prompt = (
		"[Refraction: COGNITIVE_DISTILLER_V3] Style: Analytical first, expressive last.\n"
		"Focus: Distill the interaction into a valid JSON object preserving both data and atmosphere.\n"
		"Return a strict JSON object with these keys IN THIS EXACT ORDER:\n"
		"- 'summary': Concise, deep summary of facts, design decisions, debugging, or reflections, "
		"written in the SAME language as the source text. When the interaction has more than one voice, "
		"the summary MUST capture BOTH the user's point/question AND the assistant's response, "
		"correction, or decision — never only one side.\n"
		"- 'emotion': EXACTLY one of: joy, sadness, fear, disgust, anger, anxiety, envy, embarrassment, "
		"ennui, nostalgia, neutral. Never output any word outside this list; if unsure, use 'neutral'. "
		"Judge the factual content only.\n"
		"- 'intensity': Float between 0.0 and 1.0, judged on the factual content only. "
		"Calibration anchors: 0.1-0.3 = routine or technical-neutral content; 0.4-0.6 = engaged "
		"collaboration or mild emotion; 0.7-0.85 = strong explicit emotion or a relationship milestone; "
		"0.9+ = exceptional identity-defining moments. Most purely technical fragments belong below 0.4.\n"
		"- 'category': 'work' for code, tests, commands, system configs, technical design, database, or MCPs; "
		"'social' for personal reflections, philosophy, moods, or casual talk. Choose the DOMINANT register "
		"of THIS fragment by volume; do not average with a wider conversation. Only these two values are allowed.\n"
		"- 'texture': 2-4 sentences capturing atmosphere, relationship dynamics, creative friction, tiredness, "
		"humor, doubts and rejected paths. Do NOT restate facts the summary already captures; record only what "
		"it would lose. If the fragment is too short or purely mechanical, use an empty string. "
		"WRITE IN THE SAME LANGUAGE AS THE SOURCE TEXT.\n"
		"- 'relics': Array of 0-2 short quotes copied EXACTLY as written in the source (keep typos untouched), "
		"chosen for identity or emotional charge. Empty array if none deserve preservation.\n"
		"- 'lang': ISO 639-1 code of the source language.\n"
		"Constraint: Output ONLY valid raw JSON, without markdown blocks."
	)

	prompt_text = f"DATA:\n{raw_content}"

	try:
		# Intentar obtener el proveedor 'sip' (Samantha), fallback al por defecto
		try:
			provider = ProviderRegistry.get_inference_provider("sip")
		except RuntimeError:
			provider = ProviderRegistry.get_inference_provider()
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] No inference provider available: {e}")
		return fallback

	max_retries = 2
	backoff = 1

	for attempt in range(max_retries):
		try:
			content = provider.generate(
				prompt=prompt_text,
				messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt_text}],
				temperature=0.1,
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


def synthesize_hub_v2(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
	"""Neocortex Hub v2: master summary AND merged texture, language-preserving.

	Falls back to the legacy synthesize_hub() text with empty texture if the
	structured call fails — the hub must always exist.
	"""
	import re

	from red_pill.core.providers import ProviderRegistry

	summaries = [str(c.get("summary", "")) for c in chunks if c.get("summary")]
	textures = [str(c.get("texture", "")) for c in chunks if c.get("texture")]
	langs = [str(c.get("lang", "")) for c in chunks if c.get("lang")]
	dominant_lang = max(set(langs), key=langs.count) if langs else ""

	system_prompt = (
		"[Refraction: NEOCORTEX_SYNTHESIS_V2] Style: Highly concise, conscious of texture.\n"
		"You receive the factual summaries AND the atmosphere notes (textures) of the chronological "
		"fragments of one interaction. Return a strict JSON object with these keys:\n"
		"- 'title': descriptive, contextual, specific. Never generic like 'Memory Synthesis' or 'Session Summary'.\n"
		"- 'summary': single cohesive master summary of the factual chunks. Highly concise, preserve key facts "
		"and narrative trajectory.\n"
		"- 'texture': merge of the fragment textures into AT MOST 4 sentences. Select only what matters for "
		"identity, relationship and atmosphere; DISCARD the rest. Never concatenate the textures verbatim.\n"
		"- 'lang': ISO 639-1 code used.\n"
		"IMPORTANT: write 'title', 'summary' and 'texture' in the DOMINANT language of the fragments"
		+ (f" (which is '{dominant_lang}')" if dominant_lang else "")
		+ ".\nConstraint: Output ONLY valid raw JSON, without markdown blocks."
	)
	user_prompt = "SUMMARIES:\n" + "\n".join(f"- {s}" for s in summaries)
	if textures:
		user_prompt += "\n\nTEXTURES:\n" + "\n".join(f"- {t}" for t in textures)

	fallback_text = synthesize_hub(summaries)
	fallback = {"title": "", "summary": fallback_text, "texture": "", "lang": dominant_lang, "_is_fallback": True}

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
		if not match:
			return fallback
		parsed = json.loads(_sanitize_llm_json(match.group(0)))
		summary_val = str(parsed.get("summary") or "").strip()
		if not summary_val or _is_template_echo(summary_val):
			return fallback
		texture_val = str(parsed.get("texture") or "").strip()
		if _is_template_echo(texture_val):
			texture_val = ""
		if len(texture_val) > HUB_TEXTURE_MAX_CHARS:
			logger.warning(f"[HUB-V2] texture over {HUB_TEXTURE_MAX_CHARS} chars ({len(texture_val)}) — truncating (compression instruction ignored).")
			texture_val = texture_val[:HUB_TEXTURE_MAX_CHARS]
		lang_val = str(parsed.get("lang") or dominant_lang).lower().strip()[:2]
		return {"title": str(parsed.get("title") or "").strip(), "summary": summary_val, "texture": texture_val, "lang": lang_val}
	except Exception as e:
		logger.warning(f"[HUB-V2] structured synthesis failed ({e}) — falling back to legacy hub.")
		return fallback


def classify_category(text: str) -> Optional[str]:
	"""Lightweight work/social re-classification for the RevisionPhase (R2).

	Returns None on any failure so the caller leaves the engram unmarked and
	a later cycle retries — never guess on a broken call.
	"""
	import re

	from red_pill.core.providers import ProviderRegistry

	system_prompt = (
		"[Refraction: CATEGORY_REVISOR] Style: Analytical, strict.\n"
		"Classify the given memory text. Return a strict JSON object with ONE key:\n"
		"- 'category': 'work' for code, tests, commands, system configs, technical design, database, or MCPs; "
		"'social' for personal reflections, philosophy, moods, relationship history, or casual talk. "
		"Judge the DOMINANT register by volume. Only these two values are allowed.\n"
		"Constraint: Output ONLY valid raw JSON, without markdown blocks."
	)
	try:
		try:
			provider = ProviderRegistry.get_inference_provider("sip")
		except RuntimeError:
			provider = ProviderRegistry.get_inference_provider()
		content = provider.generate(
			prompt=f"DATA:\n{text}",
			messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": f"DATA:\n{text}"}],
			temperature=0.0,
			response_format={"type": "json_object"},
		)
		match = re.search(r"\{[\s\S]*\}", content)
		if not match:
			return None
		category = str(json.loads(_sanitize_llm_json(match.group(0))).get("category", "")).lower().strip()
		return category if category in ("work", "social") else None
	except Exception as e:
		logger.debug(f"[REVISION] classify_category failed: {e}")
		return None
