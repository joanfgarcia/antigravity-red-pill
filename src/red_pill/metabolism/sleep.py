import json
import logging
import urllib.request
from typing import Any, Dict, List, Optional

from qdrant_client.models import Filter

import red_pill.config as cfg
from red_pill.events import SleepCompletedEvent, get_event_bus

logger = logging.getLogger(__name__)


def chunk_text(text: str, size: Optional[int] = None) -> List[str]:
	"""Break large interactions into biologially manageable sequences."""
	if size is None:
		size = cfg.SLEEP_CHUNK_SIZE

	chunks = []
	start = 0
	while start < len(text):
		end = start + size
		if end >= len(text):
			chunks.append(text[start:])
			break
		# Heuristic 1: Try finding a newline near the cut
		last_break = text.rfind("\n", start, end)
		if last_break != -1 and last_break > start + (size // 2):
			end = last_break + 1
		else:
			# Heuristic 2: Try finding a sentence terminator or comma
			found_punct = -1
			for punct in [". ", "? ", "! ", ", "]:
				p_idx = text.rfind(punct, start, end)
				if p_idx > found_punct:
					found_punct = p_idx

			if found_punct != -1 and found_punct > start + (size // 2):
				end = found_punct + 1  # Include the punctuation mark
			else:
				# Heuristic 3: Fallback to the last space
				last_space = text.rfind(" ", start, end)
				if last_space != -1 and last_space > start + (size // 2):
					end = last_space + 1
		chunks.append(text[start:end])
		start = end
	return chunks


def distill_engram(raw_content: str) -> Dict[str, Any]:
	"""
	Lazarus Phase 2: Consolidation (Sleep) & Affective Preservation
	"""
	prompt = (
		"Distill the following interaction into a JSON object with strictly these keys: "
		"'summary' (concise essence of facts/conclusions), "
		"'emotion' (one of: joy, sadness, fear, disgust, anger, anxiety, envy, embarrassment, ennui, nostalgia, or neutral), "
		"and 'intensity' (float from 0.0 to 1.0 representing emotional arousal). "
		"Ignore raw terminal logs and formatting. Output ONLY valid JSON.\n\nDATA:\n"
	)
	prompt += raw_content

	payload = json.dumps(
		{
			"messages": [
				{
					"role": "system",
					"content": "You are an Amygdala-driven consolidation sub-routine. Output ONLY valid JSON without markdown fences. Be extremely concise.",
				},
				{"role": "user", "content": prompt},
			],
			"temperature": 0.1,
			"max_tokens": 512,
			"seed": 760,
			"stop": ["<|im_end|>", "<|endoftext|>", "user:", "assistant:"],
		}
	).encode("utf-8")

	import os
	import urllib.parse
	import urllib.request

	from red_pill.utils.uds_adapter import get_uds_opener

	uds_path = os.path.expanduser("~/.agent/red_pill.sock")
	if os.path.exists(uds_path):
		encoded_path = urllib.parse.quote(uds_path, safe="")
		url = f"unix://{encoded_path}/v1/chat/completions"
		opener = get_uds_opener()
	else:
		url = getattr(cfg, "MLX_LM_URL", "http://127.0.0.1:8760/v1/chat/completions")
		opener = urllib.request.build_opener()

	if not url:
		return {"summary": raw_content[:500] + "...", "emotion": "neutral", "intensity": 0.5}  # Fallback if URL is empty

	req = urllib.request.Request(
		url,
		data=payload,
		headers={"Content-Type": "application/json"},
	)
	import time

	max_retries = 3
	backoff = 2
	fallback = {"summary": raw_content[:500] + "...", "emotion": "neutral", "intensity": 0.5}

	for attempt in range(max_retries):
		try:
			with opener.open(req, timeout=45) as response:
				data = json.loads(response.read().decode())
				content = data["choices"][0]["message"]["content"].strip()
				import re

				# Clean possible LLM markdown
				if content.startswith("```json"):
					content = content[7:]
				if content.startswith("```"):
					content = content[3:]
				if content.endswith("```"):
					content = content[:-3]

				# Robust JSON extraction
				match = re.search(r"\{.*\}", content, re.DOTALL)
				if match:
					content = match.group(0)

				parsed = json.loads(content)

				return {
					"summary": parsed.get("summary", fallback["summary"]),
					"emotion": parsed.get("emotion", "neutral").lower()[:20],
					"intensity": float(parsed.get("intensity", 0.5)),
				}
		except Exception as e:
			logger.warning(f"[SLEEP ENGINE] Distillation attempt {attempt + 1} failed: {e}")
			if attempt < max_retries - 1:
				time.sleep(backoff ** (attempt + 1))
			else:
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
			"messages": [
				{
					"role": "system",
					"content": "You are a Neocortex synthesis sub-routine. Output ONLY the short master summary string. No JSON, no conversational filler.",
				},
				{"role": "user", "content": prompt},
			],
			"temperature": 0.1,
			"max_tokens": 512,
			"seed": 777,
			"stop": ["<|im_end|>", "<|endoftext|>"],
		}
	).encode("utf-8")

	url = getattr(cfg, "MLX_LM_URL", "http://127.0.0.1:8080/v1/chat/completions")
	if not url:
		url = "http://127.0.0.1:8080/v1/chat/completions"
	req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
	try:
		with urllib.request.urlopen(req, timeout=60) as response:
			data = json.loads(response.read().decode())
			return str(data["choices"][0]["message"]["content"].strip())
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Failed to synthesize hub: {e}")
		return "Aggregated Memory Sequence Synthesis."


def perform_sleep_cycle(memory_manager, mode: str = "lazy") -> int:
	"""
	Lazarus Phase 2, 3 & 4: Consolidation, Fixation, and Synaptic Dreaming.
	"""
	logger.info("=== LAZARUS PULSE: Initiating Synaptic Dreaming (NREM/REM) ===")

	client = memory_manager.client
	collection = "interaction_memories"

	if not client.collection_exists(collection):
		logger.warning("Sleep cycle aborted: fast buffer does not exist.")
		return 0

	try:
		scroll_result, _ = client.scroll(collection_name=collection, scroll_filter=Filter(), limit=50, with_payload=True)
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Failed to fetch raw buffer: {e}")
		return 0

	if not scroll_result:
		logger.info("Sleep Cycle complete. No unprocessed interactions found.")
		return 0

	processed_count = 0
	for point in scroll_result:
		raw_id = point.id
		raw_text = (point.payload or {}).get("content", "")

		if not raw_text:
			continue

		logger.debug(f"[SLEEP ENGINE] Processing raw interaction sequence: {raw_id}")

		# Biological Refactor: Semantic Engram Decoupling (Prompt vs Response + Axon Link)
		chunks = []
		if raw_text.startswith("USER: ") and "\n\nASSISTANT: " in raw_text:
			parts = raw_text.split("\n\nASSISTANT: ", 1)
			p_text = parts[0].replace("USER: ", "", 1).strip()
			r_text = parts[1].strip()

			if p_text:
				for c in chunk_text(p_text):
					chunks.append(f"Operator Prompt: {c}")
			if r_text:
				for c in chunk_text(r_text):
					chunks.append(f"AI Response Node: {c}")
		elif raw_text.startswith("USER: ") and "\n\nTOOL: " in raw_text:
			parts = raw_text.split("\n\nTOOL: ", 1)
			p_text = parts[0].replace("USER: ", "", 1).strip()
			r_text = parts[1].strip()

			if p_text:
				for c in chunk_text(p_text):
					chunks.append(f"Operator Objective: {c}")
			if r_text:
				for c in chunk_text(r_text):
					chunks.append(f"System Action: {c}")
		else:
			chunks = chunk_text(raw_text)

		surviving_chunks = []
		prev_chunk_id = None

		target_col = "social_memories"
		if any(kw in raw_text.lower() for kw in ["code", "error", "bash", "python", "script", "commit"]):
			target_col = "work_memories"

		for i, chunk in enumerate(chunks):
			distilled = distill_engram(chunk)
			emotion = distilled.get("emotion", "neutral")
			intensity = distilled.get("intensity", 0.5)
			summary = distilled.get("summary", "")

			# Phase 2: Affective Culling (Amygdala Validation)
			if emotion == "neutral" and intensity < cfg.SLEEP_CULL_THRESHOLD and len(chunks) > 1:
				logger.debug(f"[AFFECTIVE CULLING] Dropped chunk {i + 1} (low biological relevance).")
				continue

			surviving_chunks.append(distilled)

			# Phase 3: Immediate Fixation of Sub-node
			meta = {"lazarus_phase": "sequence_chunk", "chunk_index": i, "source_buffer_id": raw_id, "raw_content_preview": chunk[:200]}

			try:
				# Insert memory
				new_id = memory_manager.add_memory(
					collection=target_col,
					text=summary,
					metadata=meta,
					color="blue" if target_col == "work_memories" else "purple",
					emotion=emotion,
					intensity=intensity,
				)

				# Assign Graph Topology (Linked Thread)
				if prev_chunk_id and new_id:
					client.set_payload(collection_name=target_col, payload={"associations": [prev_chunk_id]}, points=[new_id])

				prev_chunk_id = new_id
				processed_count += 1

			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to fixate child chunk: {e}")

		# Phase 4: Hub Synthesis (Neocortex)
		if len(surviving_chunks) > 1 and prev_chunk_id:
			hub_summary = synthesize_hub([c["summary"] for c in surviving_chunks])
			hub_emotion = surviving_chunks[-1]["emotion"]  # Heuristic: retain last emotion
			hub_intensity = max([c["intensity"] for c in surviving_chunks])  # Heuristic: peak arousal

			try:
				hub_id = memory_manager.add_memory(
					collection=target_col,
					text=hub_summary,
					metadata={"lazarus_phase": "synthesis_hub", "source_buffer_id": raw_id},
					color="cyan",  # Hub Node color
					emotion=hub_emotion,
					intensity=hub_intensity,
				)
				if hub_id:
					client.set_payload(collection_name=target_col, payload={"associations": [prev_chunk_id]}, points=[hub_id])
					processed_count += 1
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to fixate synthesis hub: {e}")

		# Erase the raw memory sequence
		try:
			client.delete(collection_name=collection, points_selector=[raw_id])
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Could not purge fast buffer node {raw_id}: {e}")

	logger.info(f"=== LAZARUS PULSE: Sleep Cycle complete. {processed_count} engrams synaptically woven. ===")
	get_event_bus().emit(SleepCompletedEvent(
		collection=collection,
		processed_count=processed_count,
		mode=mode,
	))
	return processed_count
