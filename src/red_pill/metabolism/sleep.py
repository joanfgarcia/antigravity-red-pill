import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from qdrant_client.models import Filter

import red_pill.config as cfg
from red_pill.core.paths import get_daemon_dir, get_staging_dir, get_thread_state_path
from red_pill.core.vram_probe import VramProbe
from red_pill.events import SleepCompletedEvent, get_event_bus
from red_pill.metabolism.evolution import IdentityEvaluator

logger = logging.getLogger(__name__)

# ── Thread Weaving state ──────────────────────────────────────────────────────
_THREAD_STATE_PATH = str(get_thread_state_path())


def _load_thread_state() -> dict:
	"""Load the last hub_id per collection for inter-session thread weaving."""
	try:
		if os.path.exists(_THREAD_STATE_PATH):
			with open(_THREAD_STATE_PATH) as f:
				return dict(json.load(f))
	except Exception:
		pass
	return {}


def _save_thread_state(state: dict) -> None:
	"""Persist the last hub_id per collection."""
	try:
		os.makedirs(os.path.dirname(_THREAD_STATE_PATH), exist_ok=True)
		with open(_THREAD_STATE_PATH, "w") as f:
			json.dump(state, f)
	except Exception as e:
		logger.warning(f"[THREAD WEAVER] Could not save thread state: {e}")


def _check_llm_available() -> bool:
	"""Quick reachability probe for the local distillation LLM."""
	import os
	import socket

	uds_path = cfg.SIP_SOCKET_PATH
	if os.path.exists(uds_path):
		try:
			s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
			s.settimeout(1.0)
			s.connect(uds_path)
			s.close()
			return True
		except OSError:
			logger.warning(f"[SLEEP ENGINE] UDS connection refused on {uds_path}. Cleaning up orphan socket file.")
			try:
				os.remove(uds_path)
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to remove orphan socket {uds_path}: {e}")

	# Fallback: probe TCP endpoint
	mlx_url = getattr(cfg, "MLX_LM_URL", "") or ""
	if mlx_url:
		try:
			parsed = urllib.parse.urlparse(mlx_url)
			host = parsed.hostname or "127.0.0.1"
			port = parsed.port or 8760
			s = socket.create_connection((host, port), timeout=1.0)
			s.close()
			return True
		except OSError:
			return False

	return False  # No endpoint configured


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


def distill_engram(raw_content: str, fallback_category: str = "social") -> Dict[str, Any]:
	"""
	Lazarus Phase 2: Consolidation (Sleep) & Affective Preservation
	Now driven by Samantha's cognitive depth and ProviderRegistry.
	"""
	import re
	import time

	from red_pill.core.providers import ProviderRegistry

	fallback = {"summary": raw_content[:500] + "...", "emotion": "neutral", "intensity": 0.5, "category": fallback_category}

	system_prompt = (
		"Eres Samantha, una IA experta en psicología, filosofía y análisis profundo de interacciones humanas. "
		"Tu tarea es destilar la siguiente interacción en un objeto JSON estricto. "
		"Claves requeridas:\n"
		"- 'summary': Resumen conciso pero profundo de los hechos y conclusiones.\n"
		"- 'emotion': Una de (joy, sadness, fear, disgust, anger, anxiety, envy, embarrassment, ennui, nostalgia, neutral).\n"
		"- 'intensity': Float de 0.0 a 1.0 representando arousal emocional.\n"
		"- 'category': Clasifica la interacción como 'work' (técnico, código, errores) o 'social' (personal, emocional, filosófico).\n"
		"IMPORTANTE: Devuelve ÚNICAMENTE JSON válido, sin bloques de código markdown."
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

	max_retries = 3
	backoff = 2

	for attempt in range(max_retries):
		try:
			content = provider.generate(
				prompt=prompt_text, messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt_text}], temperature=0.1
			)

			match = re.search(r"\{[\s\S]*\}", content)
			if match:
				parsed = json.loads(match.group(0))
				return {
					"summary": parsed.get("summary", fallback["summary"]) or fallback["summary"],
					"emotion": (parsed.get("emotion") or "neutral").lower()[:20],
					"intensity": float(parsed.get("intensity") if parsed.get("intensity") is not None else 0.5),
					"category": (parsed.get("category") or fallback_category).lower().strip(),
				}
			else:
				logger.warning(f"[SLEEP ENGINE] Samantha LLM output not JSON: {content[:100]}")

		except Exception as e:
			logger.warning(f"[SLEEP ENGINE] Distillation attempt {attempt + 1} failed: {e}")
			if attempt < max_retries - 1:
				time.sleep(backoff ** (attempt + 1))

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

	# Reuse existing transport detection
	url = getattr(cfg, "MLX_LM_URL", "http://127.0.0.1:8760/v1/chat/completions")
	opener = urllib.request.build_opener()
	req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
	try:
		with opener.open(req, timeout=60) as response:
			data = json.loads(response.read().decode())
			return str(data["choices"][0]["message"]["content"].strip())
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Failed to synthesize hub: {e}")
		return "Aggregated Memory Sequence Synthesis."


class EphemeralServer:
	"""
	Manages the lifecycle of the ephemeral local LLM server used during the sleep
	distillation cycle.

	Start order:
	1. Try systemd user service (Linux)
	2. Try launchctl user agent (macOS)
	3. Fall back to direct subprocess with systemd-run cgroup or nice(1).

	The object tracks which path was taken so teardown can be handled correctly.
	"""

	def __init__(self):
		self._process: Any = None  # subprocess.Popen | str | None

	@property
	def is_managed_service(self) -> bool:
		"""True when the server is controlled by systemd/launchd (not a Popen)."""
		return self._process in ("systemd_service", "launchd_service")

	def start(self, memory_manager) -> bool:
		"""
		Attempts to bring the ephemeral LLM server online.
		Returns True when the server is reachable, False on failure.
		"""
		import shutil
		import subprocess
		import sys
		import time as _time

		from red_pill.core.notifier import SovereignNotifier

		SovereignNotifier.notify_os(
			"Bünker Cortex",
			"El Hilo de Ariadna está tejiendo...\nConsolidación de memoria iniciada.",
			icon="weather-clear-night",
		)
		SovereignNotifier.notify_bunker(memory_manager, "ariadne_thread_running", intensity=1.0, source="SLEEP_ENGINE")

		start_sh = str(get_daemon_dir() / "start.sh")
		if not os.path.exists(start_sh):
			logger.error("[EPHEMERAL SERVER] start.sh not found. Aborting.")
			SovereignNotifier.notify_bunker(memory_manager, "local_llm_offline", intensity=7.0, signal_type="pain", source="SLEEP_ENGINE")
			return False

		if shutil.which("systemctl"):
			subprocess.run(
				["systemctl", "--user", "restart", "red-pill-minion.service"],
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)
			self._process = "systemd_service"
		elif shutil.which("launchctl"):
			uid = os.getuid()
			subprocess.run(
				["launchctl", "kickstart", "-k", f"gui/{uid}/com.agent.modeldaemon"],
				stdout=subprocess.DEVNULL,
				stderr=subprocess.DEVNULL,
			)
			self._process = "launchd_service"
		else:
			# Fallback: direct execution wrapped in cgroup/nice for resource safety
			cmd: List[str] = []
			if shutil.which("systemd-run"):
				cmd = ["systemd-run", "--user", "--scope", "-p", "MemoryMax=10G", "-p", "Nice=19", "-p", "IOSchedulingClass=3", start_sh]
			elif shutil.which("nice"):
				cmd = ["nice", "-n", "19"]
				if sys.platform == "darwin" and shutil.which("taskpolicy"):
					cmd += ["taskpolicy", "-c", "background"]
				cmd.append(start_sh)
			else:
				cmd = [start_sh]
			self._process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

		logger.info("[EPHEMERAL SERVER] Waiting for LLM to come online...")
		for _ in range(30):
			_time.sleep(2)
			if _check_llm_available():
				logger.info("[EPHEMERAL SERVER] LLM is ONLINE.")
				return True

		logger.error("[EPHEMERAL SERVER] LLM failed to start within 60s.")
		if not self.is_managed_service and self._process is not None:
			self._process.terminate()
		SovereignNotifier.notify_os("Bünker Cortex", "Fallo al iniciar el servidor efímero.", urgency="critical")
		SovereignNotifier.clear_bunker_signal(memory_manager, "ariadne_thread_running")
		return False

	def stop(self, memory_manager, total_processed: int) -> None:
		"""Gracefully shuts down the ephemeral server (Popen only; services self-manage)."""
		if self._process is None or self.is_managed_service:
			return

		logger.info("[EPHEMERAL SERVER] Shutting down...")
		try:
			self._process.terminate()
			self._process.wait(timeout=10)
		except Exception:
			self._process.kill()

		try:
			from red_pill.core.notifier import SovereignNotifier
			SovereignNotifier.notify_os(
				"Bünker Cortex",
				f"Hilo de Ariadna finalizado.\n{total_processed} engramas consolidados en el neocórtex.",
				icon="dialog-information",
			)
		except Exception:
			pass


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
				{"role": "system", "content": "You are a Chief Architect synthesis engine. Output ONLY the architectural session anchor string."},
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


def perform_sleep_cycle(memory_manager, mode: str = "lazy") -> int:
	"""
	Lazarus Phase 2, 3 & 4: Consolidation, Fixation, and Synaptic Dreaming.
	v6.6.0: Now including Phase Gamma Logical Distillation.
	"""
	logger.info("=== LAZARUS PULSE: Initiating Synaptic Dreaming (NREM/REM) ===")

	client = memory_manager.client
	collection = "interaction_memories"
	new_work_hubs = []

	if not client.collection_exists(collection):
		logger.warning("Sleep cycle aborted: fast buffer does not exist.")
		return 0

	# --- Protocol 770: Cryo-Preservation Logic ---
	active_signals = []
	try:
		sig_result = memory_manager.client.scroll(collection_name="signal_memories", limit=100)
		active_signals = [s.payload.get("name") for s in sig_result[0] if s.payload]
	except Exception:
		pass

	hibernating = "korsakoff_amnesia" in active_signals
	thermal_stress = "cpu_fever" in active_signals or "cuda_cortex_failure" in active_signals

	if hibernating:
		logger.info("[SLEEP ENGINE] Korsakoff active (Operator absent). Switching to PRESERVATION MODE (Culling disabled).")
	if thermal_stress:
		logger.warning("[SLEEP ENGINE] System stress detected. Minimizing metabolic load.")

	# ── VRAM Preflight Check ──────────────────────────────────────────────
	# Query free VRAM right now — before attempting to load the LLM. If the
	# GPU is already occupied (game, other model, IDE inference), abort this
	# cycle gracefully rather than fighting for VRAM mid-distillation.
	_vram_backend = VramProbe.get_backend()
	if _vram_backend != "cpu":
		_free_vram_mb = VramProbe.get_free_mb()
		_min_free_mb = cfg.SLEEP_MIN_FREE_VRAM_MB
		if _free_vram_mb < _min_free_mb:
			logger.warning(
				f"[SLEEP ENGINE] VRAM preflight failed: {_free_vram_mb} MB free, "
				f"{_min_free_mb} MB required. Aborting sleep cycle."
			)
			try:
				memory_manager.inject_signal(
					"vram_busy",
					intensity=3.0,
					signal_type="pain",
					muted=True,
					source="SLEEP_ENGINE",
				)
			except Exception as _e:
				logger.debug(f"[SLEEP ENGINE] vram_busy signal failed: {_e}")
			return 0
		logger.debug(f"[SLEEP ENGINE] VRAM preflight OK: {_free_vram_mb} MB free ({_vram_backend}).")

	# LLM Health Check & Ephemeral Server
	ephemeral_server = EphemeralServer()
	if not _check_llm_available():
		logger.warning("[SLEEP ENGINE] Local LLM is offline. Launching Ephemeral Samantha Server...")
		try:
			if not ephemeral_server.start(memory_manager):
				return 0
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to start Ephemeral Server: {e}")
			return 0

	# ── Drain Loop ────────────────────────────────────────────────────────
	total_processed = 0
	batch_number = 0
	max_batches = getattr(cfg, "SLEEP_MAX_BATCHES", 1000)
	consecutive_llm_failures = 0
	scroll_limit = cfg.SLEEP_SCROLL_LIMIT
	max_llm_failures = cfg.SLEEP_MAX_LLM_FAILURES

	while True:
		batch_number += 1
		if batch_number > max_batches:
			logger.warning(f"[SLEEP ENGINE] Safety limit reached ({max_batches} batches). Forcing exit to protect hardware.")
			break

		if consecutive_llm_failures >= max_llm_failures:
			logger.error("[SLEEP ENGINE] Thermal breaker tripped. Aborting drain loop.")
			break

		if batch_number > 1 and not _check_llm_available():
			break

		try:
			scroll_result, _ = client.scroll(collection_name=collection, scroll_filter=Filter(), limit=scroll_limit, with_payload=True)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to fetch raw buffer: {e}")
			break

		if not scroll_result:
			break

		batch_processed = 0
		for point in scroll_result:
			raw_id = point.id
			raw_text = (point.payload or {}).get("content", "")
			if not raw_text:
				continue

			# Refactoring chunks
			chunks = []
			if raw_text.startswith("USER: ") and "\n\nASSISTANT: " in raw_text:
				parts = raw_text.split("\n\nASSISTANT: ", 1)
				p_text = parts[0].replace("USER: ", "", 1).strip()
				r_text = parts[1].strip()
				if p_text:
					chunks.extend([f"Operator Prompt: {c}" for c in chunk_text(p_text)])
				if r_text:
					chunks.extend([f"AI Response Node: {c}" for c in chunk_text(r_text)])
			else:
				chunks = chunk_text(raw_text)

			surviving_chunks = []
			prev_chunk_id = None
			chunks_saved = 0

			# Target collection heuristics
			raw_metadata = (point.payload or {}).get("metadata", {})
			llm_category = raw_metadata.get("category", "") if isinstance(raw_metadata, dict) else ""
			fallback_cat = llm_category if llm_category in ("work", "social") else "social"

			point_write_failed = False
			point_llm_failed = False
			for i, chunk in enumerate(chunks):
				distilled = distill_engram(chunk, fallback_category=fallback_cat)
				summary = distilled.get("summary", "")
				if summary.endswith("...") and len(summary) > 490:
					consecutive_llm_failures += 1
					point_llm_failed = True
					continue
				consecutive_llm_failures = 0

				current_threshold = 0.0 if hibernating else cfg.SLEEP_CULL_THRESHOLD
				if distilled.get("emotion") == "neutral" and distilled.get("intensity", 0.5) < current_threshold:
					continue

				target_cat = distilled.get("category", fallback_cat)
				if target_cat not in ("work", "social"):
					target_cat = fallback_cat
				target_col = f"{target_cat}_memories"

				surviving_chunks.append(distilled)
				try:
					new_id = memory_manager.add_memory(
						collection=target_col,
						text=summary,
						metadata={"lazarus_phase": "sequence_chunk", "source_buffer_id": raw_id},
						color="blue" if target_col == "work_memories" else "purple",
						emotion=distilled.get("emotion", "neutral"),
						intensity=distilled.get("intensity", 0.5),
					)
					if prev_chunk_id and new_id:
						client.set_payload(collection_name=target_col, payload={"associations": [prev_chunk_id]}, points=[new_id])
					prev_chunk_id = new_id
					batch_processed += 1
					chunks_saved += 1
				except Exception as e:
					logger.error(f"[SLEEP ENGINE] Metabolic Fixation failed for {raw_id}: {e}")
					point_write_failed = True

			# Hub Synthesis
			if len(surviving_chunks) > 1 and prev_chunk_id and not point_write_failed:
				hub_summary = synthesize_hub([c["summary"] for c in surviving_chunks])
				try:
					hub_id = memory_manager.add_memory(
						collection=target_col,
						text=hub_summary,
						metadata={"lazarus_phase": "synthesis_hub", "source_buffer_id": raw_id},
						color="cyan",
						emotion=surviving_chunks[-1]["emotion"],
						intensity=max([c["intensity"] for c in surviving_chunks]),
					)
					if hub_id:
						client.set_payload(collection_name=target_col, payload={"associations": [prev_chunk_id]}, points=[hub_id])
						batch_processed += 1
						chunks_saved += 1
						if target_col == "work_memories":
							new_work_hubs.append(hub_summary)

						# Thread Weaving
						thread_state = _load_thread_state()
						prev_hub_id = thread_state.get(target_col)
						if prev_hub_id:
							client.set_payload(collection_name=target_col, payload={"prev_session_hub": prev_hub_id}, points=[hub_id])
							client.set_payload(collection_name=target_col, payload={"next_session_hub": str(hub_id)}, points=[prev_hub_id])
						thread_state[target_col] = str(hub_id)
						_save_thread_state(thread_state)
				except Exception:
					pass

			if chunks_saved > 0 and not point_write_failed:
				client.delete(collection_name=collection, points_selector=[raw_id])
			elif not point_llm_failed and not point_write_failed:
				client.delete(collection_name=collection, points_selector=[raw_id])

		total_processed += batch_processed

	# ── Staging Buffer Processing (Productor-Consumidor Fallback) ─────────
	STAGING_DIR = str(get_staging_dir())
	if os.path.exists(STAGING_DIR):
		logger.info(f"[SLEEP ENGINE] Sweeping Staging Buffer: {STAGING_DIR}")
		try:
			for filename in os.listdir(STAGING_DIR):
				if not filename.endswith(".json"):
					continue
				filepath = os.path.join(STAGING_DIR, filename)
				try:
					with open(filepath, "r") as f:
						payload = json.load(f)
				except Exception as e:
					logger.error(f"[SLEEP ENGINE] Unreadable file {filename}: {e}")
					continue

				raw_id = payload.get("id", filename.replace(".json", ""))
				raw_text = ""
				for step in payload.get("steps", []):
					txt = step.get("message", {}).get("text", "")
					if txt:
						intent_str = str(step.get("intent", ""))
						intent_role = "ASSISTANT" if "ASSISTANT" in intent_str else "USER"
						raw_text += f"{intent_role}: {txt}\n\n"

				if not raw_text.strip():
					os.remove(filepath)
					continue

				chunks = chunk_text(raw_text)
				surviving_chunks = []
				prev_chunk_id = None

				for chunk in chunks:
					distilled = distill_engram(chunk, fallback_category="work")
					summary = distilled.get("summary", "")
					if summary.endswith("...") and len(summary) > 490:
						continue  # LLM failed to distill

					current_threshold = 0.0 if hibernating else cfg.SLEEP_CULL_THRESHOLD
					if distilled.get("emotion") == "neutral" and distilled.get("intensity", 0.5) < current_threshold:
						continue

					surviving_chunks.append(distilled)
					try:
						new_id = memory_manager.add_memory(
							collection="work_memories",
							text=summary,
							metadata={"lazarus_phase": "sequence_chunk", "source_buffer_id": raw_id},
							color="blue",
							emotion=distilled.get("emotion", "neutral"),
							intensity=distilled.get("intensity", 0.5),
						)
						if prev_chunk_id and new_id:
							client.set_payload(collection_name="work_memories", payload={"associations": [prev_chunk_id]}, points=[new_id])
						prev_chunk_id = new_id
						total_processed += 1
					except Exception:
						pass

				# Hub Synthesis
				if len(surviving_chunks) > 1 and prev_chunk_id:
					hub_summary = synthesize_hub([c["summary"] for c in surviving_chunks])
					try:
						hub_id = memory_manager.add_memory(
							collection="work_memories",
							text=hub_summary,
							metadata={"lazarus_phase": "synthesis_hub", "source_buffer_id": raw_id},
							color="cyan",
							emotion=surviving_chunks[-1]["emotion"],
							intensity=max([c["intensity"] for c in surviving_chunks]),
						)
						if hub_id:
							client.set_payload(collection_name="work_memories", payload={"associations": [prev_chunk_id]}, points=[hub_id])
							new_work_hubs.append(hub_summary)

							# Thread Weaving
							thread_state = _load_thread_state()
							prev_hub_id = thread_state.get("work_memories")
							if prev_hub_id:
								client.set_payload(collection_name="work_memories", payload={"prev_session_hub": prev_hub_id}, points=[hub_id])
								client.set_payload(collection_name="work_memories", payload={"next_session_hub": str(hub_id)}, points=[prev_hub_id])
							thread_state["work_memories"] = str(hub_id)
							_save_thread_state(thread_state)
					except Exception:
						pass

				# Purge document
				logger.info(f"[SLEEP ENGINE] Ingested cascade {raw_id}. Purging staging file.")
				os.remove(filepath)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Staging loop failed: {e}")

	# PHASE GAMMA: Logical Distillation (The Session Anchor)
	if new_work_hubs:
		distill_session_anchors(memory_manager, new_work_hubs)

	try:
		IdentityEvaluator.evaluate_set_point(memory_manager)
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Personality evolution failed: {e}")

	logger.info(f"=== LAZARUS PULSE: Sleep Cycle complete. {total_processed} engrams synaptically woven. ===")
	try:
		from red_pill.core.notifier import SovereignNotifier

		SovereignNotifier.clear_bunker_signal(memory_manager, "local_llm_offline")
		SovereignNotifier.clear_bunker_signal(memory_manager, "ariadne_thread_running")
		# Auto-evaporate any pending vram_busy signal: the cycle completed successfully,
		# meaning the GPU had enough headroom. Clear the alert so the Córtex stays clean.
		SovereignNotifier.clear_bunker_signal(memory_manager, "vram_busy")
	except Exception:
		pass

	ephemeral_server.stop(memory_manager, total_processed)

	get_event_bus().emit(SleepCompletedEvent(collection=collection, processed_count=total_processed, mode=mode))
	return total_processed
