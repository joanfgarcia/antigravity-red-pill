"""
Lazarus Sleep Engine — Memory Consolidation Pipeline
=====================================================
Biological sleep cycle for the Red Pill ecosystem. Processes raw interaction
buffers (Qdrant + filesystem staging) through distillation, fixation, hub
synthesis, thread weaving, erosion and identity evolution.

Architecture Decision Record (ADR-SLEEP-001) — 2026-05-31
----------------------------------------------------------
STATUS: Deferred.

This module is a known God Class (~940 LOC, 12 top-level symbols). A
decomposition into a pipeline orchestrator + phase plugins was analyzed
and *intentionally deferred* for the following reasons:

1. The module works reliably in autonomous nightly cycles (AWAKENINGs).
2. The macro phases (preflight → drain → staging → gamma → delta →
	evolution → cleanup) are sequential and could be pipeline stages.
	However, the drain loop's micro-level (chunk → distill → fixate →
	link → hub) has tightly coupled mutable state that resists clean
	plugin boundaries.
3. The file is rarely modified — the cost/risk of reorganization does
	not justify the marginal readability gain today.

TRIGGER TO REVISIT: If the file exceeds ~1200 LOC, or if new phases
need to be added to the cycle, revisit decomposition into:

	metabolism/
	├── sleep.py              → Orchestrator (SleepPipeline + SleepContext)
	├── phases/preflight.py   → VRAM check, signal gating
	├── phases/drain.py       → Core drain loop (uses chunker, distiller)
	├── phases/staging.py     → Filesystem cascade ingestion
	├── phases/gamma.py       → Session anchor distillation
	├── phases/delta.py       → Bayesian hub erosion
	├── chunker.py            → chunk_text, _sanitize_llm_json
	├── distiller.py          → distill_engram, synthesize_hub
	├── categorizer.py        → detect_category_heuristics
	├── ephemeral_server.py   → EphemeralServer + _check_llm_available
	└── thread_weaver.py      → Thread state persistence + linking

See: https://github.com/joanfgarcia/antigravity-red-pill/pull/62
"""

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from qdrant_client.models import Filter

import red_pill.config as cfg
from red_pill.core.paths import get_daemon_persistent_dir, get_staging_dir, get_thread_state_path
from red_pill.core.vram_probe import VramProbe
from red_pill.events import SleepCompletedEvent, get_event_bus
from red_pill.metabolism.evolution import IdentityEvaluator

logger = logging.getLogger(__name__)

# ── Thread Weaving state ──────────────────────────────────────────────────────


def _load_thread_state() -> dict:
	"""Load the last hub_id per collection for inter-session thread weaving."""
	try:
		path = get_thread_state_path()
		if path.exists():
			with open(path) as f:
				return dict(json.load(f))
	except Exception:
		pass
	return {}


def _save_thread_state(state: dict) -> None:
	"""Persist the last hub_id per collection."""
	try:
		path = get_thread_state_path()
		path.parent.mkdir(parents=True, exist_ok=True)
		with open(path, "w") as f:
			json.dump(state, f)
	except Exception as e:
		logger.warning(f"[THREAD WEAVER] Could not save thread state: {e}")


def detect_category_heuristics(text: Any) -> str:
	"""
	Detects if the text has technical/development signals to classify it as 'work'.
	Otherwise returns 'social'.
	"""
	if not isinstance(text, str):
		text = str(text)
	text_lower = text.lower()
	if "```" in text:
		return "work"

	tech_keywords = {
		"code",
		"código",
		"test",
		"pytest",
		"bug",
		"error",
		"git",
		"github",
		"diff",
		"patch",
		"repo",
		"repository",
		"docker",
		"systemd",
		"systemctl",
		"mcp",
		"api",
		"endpoint",
		"database",
		"db",
		"query",
		"python",
		"rust",
		"compile",
		"script",
		"cli",
		"command",
		"terminal",
		"bash",
		"shell",
		"exception",
		"traceback",
		"stacktrace",
		"import",
		"class",
		"def",
		"fn",
		"const",
		"impl",
		"interface",
		"refactor",
		"build",
		"deploy",
		"server",
		"client",
		"vram",
		"gpu",
		"cuda",
		"npu",
		"cpu",
		"memory",
		"cache",
		"token",
		"llm",
		"prompt",
		"model",
		"config",
		"port",
		"socket",
		"grpc",
		"json",
		"xml",
		"yaml",
		"file",
		"directory",
		"path",
		"permissions",
		"chmod",
		"chown",
		"ssh",
		"curl",
		"wget",
		"http",
	}

	import re

	words = set(re.findall(r"[a-zA-Z0-9_]+", text_lower))
	if words.intersection(tech_keywords):
		return "work"
	return "social"


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


def _sanitize_llm_json(raw_json: str) -> str:
	"""
	Sanitize JSON output from local LLMs that may contain invalid backslash
	escape sequences (e.g. \\e, \\s, \\a).  JSON only allows: \\" \\\\
	\\/ \\b \\f \\n \\r \\t \\uXXXX.  Any other \\X is illegal and causes
	``json.loads`` to raise ``Invalid \\escape``.

	Strategy: use a regex to find all backslash sequences and double the
	backslash for any that are not in the legal set, turning them into
	literal characters.
	"""
	import re as _re

	_VALID_ESCAPES = frozenset('"\\bfnrtu/')

	def _fix_escape(m: _re.Match) -> str:
		char_after = m.group(1)
		if char_after in _VALID_ESCAPES:
			return str(m.group(0))  # legal — leave untouched
		# Illegal escape: double the backslash so it becomes a literal '\'
		return str("\\\\" + char_after)

	return _re.sub(r"\\(.)", _fix_escape, raw_json)


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
	fallback = {"summary": raw_content[:500] + "...", "emotion": "neutral", "intensity": 0.5, "category": fallback_category, "_is_fallback": True}

	system_prompt = (
		"[Refraction: COGNITIVE_DISTILLER] Style: Analytical, strict. "
		"Focus: Distill the interaction into a valid JSON object. "
		"Format requirements:\n"
		"Return a strict JSON object with these keys:\n"
		"- 'summary': Concise, deep summary of facts, design decisions, debugging, or reflections.\n"
		"- 'emotion': One of: joy, sadness, fear, disgust, anger, anxiety, envy, embarrassment, ennui, nostalgia, neutral.\n"
		"- 'intensity': Float between 0.0 and 1.0 representing severity or emotional charge.\n"
		"- 'category': 'work' for code, tests, commands, system configs, technical design, database, or MCPs; "
		"'social' for personal reflections, philosophy, moods, or casual talk.\n"
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

				return {
					"summary": summary_val,
					"emotion": emotion_val,
					"intensity": intensity_val,
					"category": category_val,
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

		start_sh = str(get_daemon_persistent_dir() / "start.sh")
		if not os.path.exists(start_sh):
			logger.error("[EPHEMERAL SERVER] start.sh not found. Aborting.")
			SovereignNotifier.notify_bunker(memory_manager, "local_llm_offline", intensity=7.0, signal_type="pain", source="SLEEP_ENGINE")
			return False

		if shutil.which("systemctl"):
			subprocess.run(
				["systemctl", "--user", "restart", "redpill-llm.service"],
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
		if self.is_managed_service:
			try:
				import urllib.request

				req = urllib.request.Request("http://127.0.0.1:8760/unload", method="POST")
				with urllib.request.urlopen(req, timeout=5):
					logger.info("[EPHEMERAL SERVER] Explicit model unload triggered successfully on local daemon.")
			except Exception as e:
				logger.warning(f"[EPHEMERAL SERVER] Failed to trigger explicit model unload on local daemon: {e}")
			return

		if self._process is None:
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


def erode_work_hubs(memory_manager) -> None:
	"""
	Applies Bayesian erosion to old/unreferenced synthesis hubs in work_memories.
	Hubs that haven't been recalled/referenced in the last cycle have their
	utility_beta increased (reducing utility score) and their intensity decayed.
	"""
	client = memory_manager.client
	collection = "work_memories"
	if not client.collection_exists(collection):
		return

	from qdrant_client import models as qm

	# Retrieve all synthesis hubs in work_memories
	scroll_filter = qm.Filter(must=[qm.FieldCondition(key="metadata.lazarus_phase", match=qm.MatchValue(value="synthesis_hub"))])

	try:
		# Scroll to get all hubs (limit=1000 should be plenty for hubs)
		scroll_res = client.scroll(collection_name=collection, scroll_filter=scroll_filter, limit=1000, with_payload=True)
		if isinstance(scroll_res, tuple) and len(scroll_res) == 2:
			hubs = scroll_res[0]
		else:
			hubs = scroll_res if isinstance(scroll_res, list) else []
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Failed to fetch hubs for erosion: {e}")
		return

	if not hubs or not isinstance(hubs, list):
		return

	now = time.time()
	update_operations = []
	points_to_delete = []

	# Cycle duration threshold: 1 cycle is approx 12 hours.
	threshold_seconds = 12 * 3600

	for hub in hubs:
		payload = hub.payload or {}
		if payload.get("immune"):
			continue

		last_recalled = float(payload.get("last_recalled_at", now))

		# If it hasn't been recalled recently
		if now - last_recalled > threshold_seconds:
			alpha = float(payload.get("utility_alpha", 1.0))
			beta = float(payload.get("utility_beta", 1.0))
			intensity = float(payload.get("intensity", 0.5))

			# 1. Bayesian Erosion: Increase uncertainty (beta)
			new_beta = beta + 0.5
			new_utility = alpha / (alpha + new_beta)
			new_score = round(new_utility, 3)

			# 2. Intensity decay: decay intensity by 15% (factor 0.85)
			new_intensity = round(intensity * 0.85, 3)

			# Deletion threshold: if score <= 0.3 or intensity <= 0.05
			deletion_threshold = 0.3
			if new_score <= deletion_threshold or new_intensity <= 0.05:
				points_to_delete.append(hub.id)
				logger.info(
					f"[SLEEP ENGINE] Hub {hub.id} in 'work_memories' eroded below threshold (score={new_score}, intensity={new_intensity}). Deleting."
				)
			else:
				update_payload = {"utility_beta": new_beta, "reinforcement_score": new_score, "intensity": new_intensity, "last_recalled_at": now}
				update_operations.append(qm.SetPayloadOperation(set_payload=qm.SetPayload(payload=update_payload, points=[hub.id])))

	if update_operations:
		try:
			client.batch_update_points(collection_name=collection, update_operations=update_operations)
			logger.info(f"[SLEEP ENGINE] Erode hubs: updated {len(update_operations)} hubs in work_memories.")
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to update eroded hubs: {e}")

	if points_to_delete:
		try:
			client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=points_to_delete))
			logger.info(f"[SLEEP ENGINE] Erode hubs: deleted {len(points_to_delete)} hubs in work_memories.")
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to delete eroded hubs: {e}")


def run_rhizodb_washout_and_pruning(memory_manager) -> None:
	"""
	Applies global periodic Washout and Structural Pruning to collections utilizing RhizoDB.
	Washout formula: a_v = gamma * a_v + b(s_v)
	Pruning rule: delete if a_v < 0.1 and s_v < 5.0 (days)
	"""
	client = memory_manager.client
	now = time.time()
	gamma = 0.85
	S_max = 365.0

	# Find collections utilizing rhizodb
	rhizodb_collections = [col for col, eng in cfg.MEMORY_ENGINES.items() if eng == "rhizodb"]

	for collection in rhizodb_collections:
		if not client.collection_exists(collection):
			continue

		from qdrant_client import models as qm

		from red_pill.affect import get_memory_engine

		engine = get_memory_engine("rhizodb")

		try:
			# Scroll to get all points (limit=10000 to cover all social/story memories)
			scroll_res = client.scroll(collection_name=collection, limit=10000, with_payload=True)
			if isinstance(scroll_res, tuple) and len(scroll_res) == 2:
				points = scroll_res[0]
			else:
				points = scroll_res if isinstance(scroll_res, list) else []
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to fetch points for rhizodb processing in {collection}: {e}")
			continue

		if not points:
			continue

		update_operations = []
		points_to_delete = []

		for p in points:
			payload = p.payload or {}
			if payload.get("immune"):
				continue

			# 1. Run lazy decay first to get current activation/score
			decay_updates = engine.calculate_lazy_decay(payload, current_time=now)

			# If lazy decay wants to delete it
			if decay_updates.get("_delete"):
				points_to_delete.append(p.id)
				continue

			score = float(decay_updates.get("reinforcement_score", payload.get("reinforcement_score", 1.0)))
			stability = float(payload.get("stability", 1.0))

			# 2. Apply Washout: a_v = gamma * a_v + b(s_v)
			# b(s_v) = (1 - gamma) * (stability / S_max)
			b_sv = (1.0 - gamma) * (stability / S_max)
			new_score = round(gamma * score + b_sv, 3)

			# 3. Structural Pruning (Poda): delete if a_v < 0.1 and s_v < 5.0
			if new_score < 0.1 and stability < 5.0:
				points_to_delete.append(p.id)
				logger.info(f"[SLEEP ENGINE] Pruning engram {p.id} in {collection}: activation={new_score}, stability={stability}")
			else:
				# Otherwise, update score and commit time
				update_payload = {"reinforcement_score": new_score, "last_recalled_at": now}
				update_operations.append(qm.SetPayloadOperation(set_payload=qm.SetPayload(payload=update_payload, points=[p.id])))

		# Execute updates and deletions
		if update_operations:
			try:
				client.batch_update_points(collection_name=collection, update_operations=update_operations)
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to update washout payloads in {collection}: {e}")

		if points_to_delete:
			try:
				client.delete(collection_name=collection, points_selector=qm.PointIdsList(points=points_to_delete))
				logger.info(f"[SLEEP ENGINE] Deleted {len(points_to_delete)} pruned engrams from {collection}.")
			except Exception as e:
				logger.error(f"[SLEEP ENGINE] Failed to delete pruned engrams in {collection}: {e}")


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
	# Skip this check if the LLM is already online (resident model on GPU).
	_vram_backend = VramProbe.get_backend()
	if _vram_backend != "cpu" and not _check_llm_available():
		_free_vram_mb = VramProbe.get_free_mb()
		_min_free_mb = cfg.SLEEP_MIN_FREE_VRAM_MB
		if _free_vram_mb < _min_free_mb:
			logger.warning(f"[SLEEP ENGINE] VRAM preflight failed: {_free_vram_mb} MB free, {_min_free_mb} MB required. Aborting sleep cycle.")
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
	# Raw points that never get deleted (write failures / LLM-failed with 0 chunks) would be
	# re-scrolled from the top every batch and re-distilled into NEW parents (duplicates),
	# spinning up to max_batches. Track them and exclude them from subsequent scrolls.
	failed_ids: set = set()

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
			from qdrant_client import models as _qm

			scroll_filter = Filter(must_not=[_qm.HasIdCondition(has_id=list(failed_ids))]) if failed_ids else Filter()
			scroll_result, _ = client.scroll(collection_name=collection, scroll_filter=scroll_filter, limit=scroll_limit, with_payload=True)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Failed to fetch raw buffer: {e}")
			break

		if not scroll_result:
			break

		batch_processed = 0
		for point in scroll_result:
			raw_id = point.id
			payload = point.payload or {}
			raw_text = payload.get("content", "")
			if not raw_text and "prompt" in payload and "response" in payload:
				raw_text = f"USER: {payload['prompt']}\n\nASSISTANT: {payload['response']}"
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

			import uuid

			parent_id = str(uuid.uuid4())
			child_ids = []

			surviving_chunks = []
			prev_chunk_id = None
			chunks_saved = 0

			# Target collection heuristics
			raw_metadata = (point.payload or {}).get("metadata", {})
			model_name = raw_metadata.get("model", "unknown") if isinstance(raw_metadata, dict) else "unknown"
			llm_category = raw_metadata.get("category", "") if isinstance(raw_metadata, dict) else ""
			if llm_category in ("work", "social"):
				fallback_cat = llm_category
			else:
				fallback_cat = detect_category_heuristics(raw_text)

			# Consistent collection to prevent link fragmentation and hub overwriting
			target_col = f"{fallback_cat}_memories"

			point_write_failed = False
			point_llm_failed = False
			for i, chunk in enumerate(chunks):
				distilled = distill_engram(chunk, fallback_category=fallback_cat)
				summary = distilled.get("summary", "")
				if distilled.get("_is_fallback"):
					consecutive_llm_failures += 1
					point_llm_failed = True
					continue
				consecutive_llm_failures = 0

				current_threshold = 0.0 if hibernating else cfg.SLEEP_CULL_THRESHOLD
				if distilled.get("emotion") == "neutral" and distilled.get("intensity", 0.5) < current_threshold:
					continue

				surviving_chunks.append(distilled)

				# Dynamic chunk-level routing
				chunk_cat = distilled.get("category")
				if chunk_cat not in ("work", "social"):
					chunk_col = target_col
				else:
					chunk_col = f"{chunk_cat}_memories"

				try:
					new_id = memory_manager.add_memory(
						collection=chunk_col,
						text=summary,
						metadata={"lazarus_phase": "sequence_chunk", "source_buffer_id": raw_id, "model": model_name, "parent_id": parent_id},
						color="blue" if chunk_col == "work_memories" else "purple",
						emotion=distilled.get("emotion", "neutral"),
						intensity=distilled.get("intensity", 0.5),
					)
					if prev_chunk_id and new_id:
						client.set_payload(collection_name=chunk_col, payload={"associations": [prev_chunk_id]}, points=[new_id])
					if new_id:
						prev_chunk_id = new_id
						child_ids.append(new_id)
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
						metadata={
							"lazarus_phase": "synthesis_hub",
							"node_type": "synthesis_hub",
							"source_buffer_id": raw_id,
							"model": model_name,
							"parent_id": parent_id,
						},
						color="cyan",
						emotion=surviving_chunks[-1]["emotion"],
						intensity=max([c["intensity"] for c in surviving_chunks]),
					)
					if hub_id:
						client.set_payload(collection_name=target_col, payload={"associations": [prev_chunk_id]}, points=[hub_id])
						child_ids.append(hub_id)
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

			# Save raw_parent verbatim engram
			if chunks_saved > 0 and not point_write_failed:
				try:
					parent_metadata = {
						"lazarus_phase": "raw_parent",
						"source_buffer_id": raw_id,
						"model": model_name,
						"associations": child_ids,
						"immune": True,
					}

					# Ariadne's Thread for raw parents
					thread_state = _load_thread_state()
					prev_parent_key = f"last_raw_parent_{target_col}"
					prev_parent_id = thread_state.get(prev_parent_key)
					if prev_parent_id:
						parent_metadata["prev_raw_parent"] = prev_parent_id

					parent_id_written = memory_manager.add_memory(
						collection=target_col,
						text=raw_text,
						metadata=parent_metadata,
						point_id=parent_id,
						force_immune=True,
					)

					if parent_id_written and prev_parent_id:
						client.set_payload(collection_name=target_col, payload={"next_raw_parent": parent_id_written}, points=[prev_parent_id])

					if parent_id_written:
						thread_state[prev_parent_key] = parent_id_written
						_save_thread_state(thread_state)

					client.delete(collection_name=collection, points_selector=[raw_id])
				except Exception as e:
					logger.error(f"[SLEEP ENGINE] Failed to save raw parent engram: {e}")
					point_write_failed = True
			elif not point_llm_failed and not point_write_failed:
				client.delete(collection_name=collection, points_selector=[raw_id])

			# Any raw point NOT deleted this pass would be re-scrolled and re-distilled into a
			# fresh parent next batch — record it so the scroll filter skips it (no duplicates).
			if point_write_failed or point_llm_failed:
				failed_ids.add(raw_id)

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
				model_name = payload.get("model") or payload.get("summary", {}).get("model") or "unknown"
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

				import uuid

				parent_id = str(uuid.uuid4())
				child_ids = []

				chunks = chunk_text(raw_text)
				surviving_chunks = []
				prev_chunk_id = None

				for chunk in chunks:
					distilled = distill_engram(chunk, fallback_category="work")
					summary = distilled.get("summary", "")
					if distilled.get("_is_fallback"):
						continue  # LLM failed to distill

					current_threshold = 0.0 if hibernating else cfg.SLEEP_CULL_THRESHOLD
					if distilled.get("emotion") == "neutral" and distilled.get("intensity", 0.5) < current_threshold:
						continue

					surviving_chunks.append(distilled)

					# Dynamic category routing for staging chunks
					chunk_cat = distilled.get("category")
					if chunk_cat not in ("work", "social"):
						chunk_col = "work_memories"
					else:
						chunk_col = f"{chunk_cat}_memories"

					try:
						new_id = memory_manager.add_memory(
							collection=chunk_col,
							text=summary,
							metadata={"lazarus_phase": "sequence_chunk", "source_buffer_id": raw_id, "model": model_name, "parent_id": parent_id},
							color="blue" if chunk_col == "work_memories" else "purple",
							emotion=distilled.get("emotion", "neutral"),
							intensity=distilled.get("intensity", 0.5),
						)
						if prev_chunk_id and new_id:
							client.set_payload(collection_name=chunk_col, payload={"associations": [prev_chunk_id]}, points=[new_id])
						if new_id:
							prev_chunk_id = new_id
							child_ids.append(new_id)
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
							metadata={
								"lazarus_phase": "synthesis_hub",
								"node_type": "synthesis_hub",
								"source_buffer_id": raw_id,
								"model": model_name,
								"parent_id": parent_id,
							},
							color="cyan",
							emotion=surviving_chunks[-1]["emotion"],
							intensity=max([c["intensity"] for c in surviving_chunks]),
						)
						if hub_id:
							client.set_payload(collection_name="work_memories", payload={"associations": [prev_chunk_id]}, points=[hub_id])
							child_ids.append(hub_id)
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

				# Save raw_parent verbatim engram for staging file
				if len(child_ids) > 0:
					try:
						parent_metadata = {
							"lazarus_phase": "raw_parent",
							"source_buffer_id": raw_id,
							"model": model_name,
							"associations": child_ids,
							"immune": True,
						}

						# Ariadne's Thread for raw parents in work_memories
						thread_state = _load_thread_state()
						prev_parent_key = "last_raw_parent_work_memories"
						prev_parent_id = thread_state.get(prev_parent_key)
						if prev_parent_id:
							parent_metadata["prev_raw_parent"] = prev_parent_id

						parent_id_written = memory_manager.add_memory(
							collection="work_memories",
							text=raw_text,
							metadata=parent_metadata,
							point_id=parent_id,
							force_immune=True,
						)

						if parent_id_written and prev_parent_id:
							client.set_payload(
								collection_name="work_memories", payload={"next_raw_parent": parent_id_written}, points=[prev_parent_id]
							)

						if parent_id_written:
							thread_state[prev_parent_key] = parent_id_written
							_save_thread_state(thread_state)
					except Exception as e:
						logger.error(f"[SLEEP ENGINE] Failed to save raw parent engram for staging file: {e}")

				# Purge document
				logger.info(f"[SLEEP ENGINE] Ingested cascade {raw_id}. Purging staging file.")
				os.remove(filepath)
		except Exception as e:
			logger.error(f"[SLEEP ENGINE] Staging loop failed: {e}")

	# PHASE GAMMA: Logical Distillation (The Session Anchor)
	if new_work_hubs:
		distill_session_anchors(memory_manager, new_work_hubs)

	# Phase Delta: Hub Bayesian Erosion
	try:
		erode_work_hubs(memory_manager)
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Failed to run Bayesian hub erosion: {e}")

	# RhizoDB Washout and Structural Pruning
	try:
		run_rhizodb_washout_and_pruning(memory_manager)
	except Exception as e:
		logger.error(f"[SLEEP ENGINE] Failed to run RhizoDB washout and pruning: {e}")

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
