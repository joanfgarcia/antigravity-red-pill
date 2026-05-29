import asyncio
import logging
import os
import threading
from typing import Optional

import red_pill.config as cfg
from red_pill.core.inbox import MinionInbox
from red_pill.memory import MemoryManager
from red_pill.soul import SoulManager

logger = logging.getLogger("red_pill.heartbeat")


class LazarusPulse:
	"""
	The Heartbeat of the Sovereign Agent.
	Runs autonomous rituals to maintain Bünker health and ontological integrity.

	.. deprecated:: 7.2.0
		LazarusPulse is superseded by :class:`red_pill.daemon.sovereign.SovereignDaemon`
		with plugin-based architecture. Its rituals are now called by timer one-shots
		(redpill-wake.timer, redpill-sleep.timer) via trigger_pulse.py.
		This class is kept for backward compatibility and will be removed in v7.3.
	"""

	def __init__(self, memory_mgr: MemoryManager, soul_mgr: SoulManager) -> None:
		self.memory_mgr = memory_mgr
		self.soul_mgr = soul_mgr
		self.inbox = MinionInbox()
		self._running = False
		self._immune_locks: dict = {}  # Tracks autonomic healing responses to prevent immune storms
		self._loop: Optional[asyncio.AbstractEventLoop] = None
		self._thread: Optional[threading.Thread] = None

	def start(self) -> None:
		"""Starts the heartbeat in a dedicated background thread."""
		if not cfg.PULSE_ENABLED:
			logger.info("Lazarus Pulse: Disabled via config.")
			return

		if self._running:
			return

		self._running = True
		self._thread = threading.Thread(target=self._run_event_loop, daemon=True, name="LazarusPulse")
		self._thread.start()
		logger.info(f"Lazarus Pulse: Rhythm initiated (Interval: {cfg.PULSE_INTERVAL}s)")

	def stop(self) -> None:
		"""Gradually stops the heartbeat."""
		if not self._running:
			return
		self._running = False
		if self._loop:
			self._loop.call_soon_threadsafe(self._loop.stop)
		if self._thread:
			self._thread.join(timeout=2.0)
		logger.info("Lazarus Pulse: Flatline.")

	def _run_event_loop(self) -> None:
		"""Entry point for the pulse thread."""
		self._loop = asyncio.new_event_loop()
		asyncio.set_event_loop(self._loop)
		self._loop.create_task(self._pulse_cycle())
		try:
			self._loop.run_forever()
		finally:
			self._loop.close()

	async def _pulse_cycle(self) -> None:
		"""The repeating biological cycle."""
		# Fire-and-forget: launch the syntax guard watcher as a background task
		asyncio.ensure_future(self._syntax_guard_watcher())

		while self._running:
			try:
				logger.info("Lazarus Pulse: Beat triggered. Executing rituals...")
				await self._maintenance_ritual()
				await self._hygiene_ritual()
				await self._usp_ritual()
				await self._dream_ritual()
				await self._consolidation_ritual()
				await self._swarm_ritual()
				await self._lazarus_ritual()
				await self._resonance_ritual()
				await self._auto_heal_ritual()
				await self._thread_ritual()

				# Wait for next beat
				await asyncio.sleep(cfg.PULSE_INTERVAL)
			except asyncio.CancelledError:
				break
			except Exception as e:
				logger.error(f"Lazarus Pulse: Arrhythmia in cycle: {e}")
				await asyncio.sleep(60)  # Recuperation period

	async def _maintenance_ritual(self) -> None:
		"""
		Autonomous Maintenance & Peripheral Diagnostics (Immune System Phase 1)
		- DB Connectivity (Hippocampus link)
		- Motor Cortex health (CUDA bindings)
		- Proactive Metabolism (Absence Guard sync).
		"""
		try:
			# 0. Check Motor Cortex (Nociceptive Pain)
			try:
				import torch

				if not torch.cuda.is_available():
					logger.warning("Pulse: Motor Cortex Disconnected (CUDA missing). Injecting pain signal.")
					self.memory_mgr.inject_signal("cuda_cortex_failure", intensity=cfg.SIGNAL_BASE_PAIN_CUDA, signal_type="pain", source="CUDA")
					self._trigger_immune_response("cuda")
				else:
					try:
						# Extra verification: attempt tensor creation
						_ = torch.tensor([1.0], device="cuda")
						self.memory_mgr.evaporate_signals("cuda_cortex_failure")
						self.memory_mgr.evaporate_signals("autoheal_error_cuda")
					except Exception:
						logger.warning("Pulse: Motor Cortex Fault (CUDA tensor failed). Injecting pain signal.")
						self.memory_mgr.inject_signal("cuda_cortex_failure", intensity=cfg.SIGNAL_BASE_PAIN_CUDA, signal_type="pain", source="CUDA")
						self._trigger_immune_response("cuda")
			except ImportError:
				logger.warning("Pulse: Motor Cortex NotFound (PyTorch missing). Injecting pain signal.")
				self.memory_mgr.inject_signal("cuda_cortex_failure", intensity=cfg.SIGNAL_BASE_PAIN_CUDA, signal_type="pain", source="CUDA")
				self._trigger_immune_response("cuda")
			except Exception as cuda_ex:
				logger.warning(f"Pulse: Motor Cortex Laceration ({cuda_ex}). Injecting pain signal.")
				self.memory_mgr.inject_signal("cuda_cortex_failure", intensity=cfg.SIGNAL_BASE_PAIN_CUDA, signal_type="pain", source="CUDA")
				self._trigger_immune_response("cuda")

			# 1. DB Connectivity (Hippocampus Link)
			try:
				self.memory_mgr.client.get_collections()
				logger.debug("Pulse: Bünker connectivity verified.")
				self.memory_mgr.evaporate_signals("qdrant_hypoxia")
			except Exception:
				# If the brain is dead, we cannot inject a pain signal. This is a Coma.
				logger.critical("Pulse: [COMA] Bünker connection lost. Memory injection impossible. System requires external defibrillation.")

			# 2. Absence Guard (Proactive TTL refresh)
			if cfg.METABOLISM_STRATEGY == "LAZY":
				logger.info("Pulse: Running proactive Absence Guard sync...")
				for coll in ["work_memories", "social_memories", "story_memories", "directive_memories"]:
					try:
						await asyncio.to_thread(self.memory_mgr.metabolism.refresh_ttl_timestamps, coll)
					except Exception as e:
						logger.error(f"Pulse: Absence Guard failed for {coll}: {e}")

			# 3. Biological Dashboard: Migraine (Database Bloat)
			try:
				count = self.memory_mgr.client.count(collection_name="work_memories").count
				if count > cfg.SIGNAL_MIGRAINE_VECTORS:
					logger.warning(f"Pulse: Semantic Bloat Detected ({count} vectors). Migraine signal injected.")
					self.memory_mgr.inject_signal("semantic_migraine", intensity=6.0, signal_type="fatigue", source="HIPPOCAMPUS")
				else:
					self.memory_mgr.evaporate_signals("semantic_migraine")
			except Exception:
				pass

			# 4. Biological Dashboard: Fever (Hardware Temperature)
			try:
				import psutil

				temps = psutil.sensors_temperatures()
				max_temp = 0.0
				for name, entries in temps.items():
					for entry in entries:
						if entry.current and entry.current > max_temp:
							max_temp = entry.current
				if max_temp > 85.0:
					logger.warning(f"Pulse: CPU Fever Detected ({max_temp}C). Fever signal injected.")
					self.memory_mgr.inject_signal("cpu_fever", intensity=7.0, signal_type="fever", source="HARDWARE")
				else:
					self.memory_mgr.evaporate_signals("cpu_fever")
			except ImportError:
				pass  # psutil not installed
			except Exception as e:
				logger.debug(f"Pulse: Fever check failed (no sensors): {e}")

			# 5. Biological Dashboard: Amnesia (Korsakoff Syndrome)
			if cfg.INTERCEPTOR_ENABLED:
				try:
					import datetime
					import os

					if os.path.exists(cfg.METABOLISM_STATE_FILE):
						mtime = os.path.getmtime(cfg.METABOLISM_STATE_FILE)
						hours_idle = (datetime.datetime.now().timestamp() - mtime) / 3600.0
						if hours_idle > cfg.SIGNAL_AMNESIA_HOURS:
							logger.warning(f"Pulse: Korsakoff Amensia triggers ({hours_idle:.1f}h without interactions).")
							self.memory_mgr.inject_signal("korsakoff_amnesia", intensity=5.5, signal_type="anxiety", source="HIPPOCAMPUS")
						else:
							self.memory_mgr.evaporate_signals("korsakoff_amnesia")
				except Exception as e:
					logger.debug(f"Pulse: Amnesia check failed: {e}")

			logger.info("Pulse: Maintenance ritual complete. 770 stable.")

		except Exception as e:
			logger.error(f"Pulse: Maintenance ritual failed: {e}")

	async def _usp_ritual(self) -> None:
		"""
		Autonomous Operator Mood Profile (USP) Refresh:
		Recalculates the operator's emotional resonance vectors
		across all temporal horizons (global, 30d, 7d, 3d).
		"""
		try:
			from red_pill.utils.mood_profile import update_usp

			logger.info("Pulse: Initiating USP Ritual (Operator Mood Profile refresh)...")
			usp = await asyncio.to_thread(update_usp, self.memory_mgr)

			# Log dominant mood for observability
			from red_pill.utils.mood_profile import _get_dominant_color

			dominant = _get_dominant_color(usp.get("last_3d", {}))
			count = usp.get("interaction_count", 0)
			logger.info(f"Pulse: USP updated. Dominant 3d: {dominant}, interactions: {count}")

		except Exception as e:
			logger.error(f"Pulse: USP ritual failed: {e}")

	async def _dream_ritual(self) -> None:
		"""
		Autonomous Oneiromancy:
		- Finds latent semantic associations between memories.
		- Simulates cognitive 'dreaming' to strengthen synaptic density.
		"""
		try:
			logger.info("Pulse: Initiating Oneiromancy (Dream Ritual)...")
			for coll in ["work_memories", "social_memories", "story_memories"]:
				try:
					await asyncio.to_thread(self.memory_mgr.dream, coll)
				except Exception as e:
					logger.error(f"Pulse: Dream failed for {coll}: {e}")

			logger.info("Pulse: Oneiromancy complete. Patterns woven.")
		except Exception as e:
			logger.error(f"Pulse: Dream ritual failed: {e}")

	async def _consolidation_ritual(self) -> None:
		"""
		Autonomous Consolidation:
		- Phase 0: Snatch trajectories from active LanguageServers into staging.
		- Phase 1: Processes raw interactions into long-term memories.
		- Discards noise and fixates essence.
		"""
		try:
			# Phase 0: LS Snatcher — extract conversations from active Language Servers
			try:
				from red_pill.metabolism.ls_snatcher import snatch_all_trajectories

				logger.info("Pulse: Initiating LS Snatcher (Extracting LanguageServer trajectories)...")
				snatched = await asyncio.to_thread(snatch_all_trajectories)
				logger.info(f"Pulse: LS Snatcher complete. {snatched} trajectories staged.")
			except Exception as e:
				logger.warning(f"Pulse: LS Snatcher failed (non-fatal, continuing): {e}")

			# Phase 1: Consolidation — process staging buffer + interaction_memories
			from red_pill.metabolism.sleep import perform_sleep_cycle

			logger.info("Pulse: Initiating Consolidation (Consolidating interactions)...")
			# Use lazy mode by default for background pulse to avoid excessive pruning
			await asyncio.to_thread(perform_sleep_cycle, self.memory_mgr, mode="lazy")
			logger.info("Pulse: Consolidation complete. Memories fixed.")
		except Exception as e:
			logger.error(f"Pulse: Consolidation ritual failed: {e}")

	async def _swarm_ritual(self) -> None:
		"""
		Autonomous Neon-Link Polling:
		- Consults the local Neon-Link Hub for unread decrypted Swarm messages.
		- If found, injects a signal for a Swarm Minion to process them.
		"""
		try:
			import httpx

			import red_pill.config as cfg

			# Hacemos un GET rápido al summary
			async with httpx.AsyncClient() as client:
				resp = await client.get(f"{cfg.NEON_LINK_URL}/inbox/summary", timeout=2.0)

			if resp.status_code == 200:
				summary = resp.json()
				total_messages = sum(summary.values())

				if total_messages > 0:
					logger.info(f"Pulse: Discovered {total_messages} pending Swarm messages in Neon-Link.")
					self.memory_mgr.inject_signal("swarm_messages_pending", intensity=7.0, signal_type="anxiety", source="Neon-Link")
				else:
					self.memory_mgr.evaporate_signals("swarm_messages_pending")
		except httpx.RequestError:
			logger.debug("Pulse: Neon-Link Hub is offline or unreachable.")
		except Exception as e:
			logger.error(f"Pulse: Swarm polling failed: {e}")

	async def _lazarus_ritual(self) -> None:
		"""
		Autonomous Lazarus Sync:
		- Monitors local dock for sync-ready engrams.
		- Moves local experience to the Hive Mind when online.
		"""
		if not cfg.LAZARUS_SYNC_ENABLED:
			return

		try:
			from red_pill.hive import HiveMind
			from red_pill.swarm.lazarus import LazarusSync

			logger.info("Pulse: Initiating Lazarus Ritual (Offgrid Sync Check)...")

			hive = HiveMind()
			if not hive.connected:
				logger.debug("Pulse: Lazarus ritual deferred (Offline).")
				return

			# Initialize Lazarus for the current operator's community
			# (Assuming a default community for background sync)
			agent_id = f"Aleph@{cfg.OPERATOR_DISPLAY_NAME}"
			community_id = os.getenv("SWARM_DEFAULT_COMMUNITY", "canonical")

			sync = LazarusSync(community_id, agent_id)

			# Perform vacuum (thread since it interacts with Milvus sync)
			count = await asyncio.to_thread(sync.vacuum)

			if count > 0:
				logger.info(f"Pulse: Lazarus resurrected {count} engrams to the Hive.")
			else:
				logger.debug("Pulse: Local dock is clean.")

		except Exception as e:
			logger.error(f"Pulse: Lazarus ritual failed: {e}")

	async def _resonance_ritual(self) -> None:
		"""
		Autonomous Semantic Resonance:
		- Searches the Hive Mind for content matching the agent's current focus.
		- Triggers proactive reactions to relevant external intelligence.
		"""
		if not cfg.RESONANCE_ENABLED:
			return

		try:
			from red_pill.swarm.resonance import ResonanceObserver

			logger.info("Pulse: Initiating Resonance Ritual (Semantic Radar)...")

			agent_id = f"Aleph@{cfg.OPERATOR_DISPLAY_NAME}"
			observer = ResonanceObserver(agent_id)

			from red_pill.utils.tone_analyzer import get_current_sync_state

			state = get_current_sync_state()
			focus_text = f"Resonance Focus: {state['mood']} - {state['directive']}"
			# Mypy/Type fix: Ensure the vector is correctly extracted from the engine
			poc_vector = self.memory_mgr.embeddings.get_vector(focus_text)

			matches = await asyncio.to_thread(observer.check_resonance, hub_vector=poc_vector)

			for match in matches:
				await asyncio.to_thread(observer.trigger_reaction, match)

		except Exception as e:
			logger.error(f"Pulse: Resonance ritual failed: {e}")

	async def _try_auto_push(self, trigger_event: str) -> None:
		"""Guardrails for git push: avoids pushing to main/master or during office hours."""
		import datetime

		# 1. Branch check
		proc = await asyncio.create_subprocess_exec(
			"git", "rev-parse", "--abbrev-ref", "HEAD", cwd=cfg.APP_ROOT, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
		)
		stdout, _ = await proc.communicate()
		branch = stdout.decode().strip()
		if branch in ["main", "master"]:
			logger.warning(f"Auto-Healer: Skipping auto-push for {trigger_event}. Branch is protected ({branch}).")
			return

		# 2. Time check (M-F, 09:00 - 18:00)
		if cfg.LAZARUS_OFFICE_HOURS_PROTECTION:
			now = datetime.datetime.now()
			is_weekday = now.weekday() < 5
			is_office_hours = 9 <= now.hour < 18
			if is_weekday and is_office_hours:
				logger.warning(f"Auto-Healer: Skipping auto-push for {trigger_event}. Office hours restriction (M-F 09-18) is ENABLED.")
				return

		# 3. Check if there are changes
		proc_status = await asyncio.create_subprocess_exec("git", "status", "--porcelain", cwd=cfg.APP_ROOT, stdout=asyncio.subprocess.PIPE)
		stdout_status, _ = await proc_status.communicate()
		if not stdout_status.strip():
			logger.info("Auto-Healer: No files changed to commit.")
			return

		# 4. Commit and push
		logger.info(f"Auto-Healer: Executing background commit & push for {trigger_event}...")
		proc_add = await asyncio.create_subprocess_exec("git", "add", ".", cwd=cfg.APP_ROOT)
		await proc_add.communicate()
		proc_commit = await asyncio.create_subprocess_exec(
			"git", "commit", "-m", f"chore(auto-heal): background recovery [{trigger_event}]", cwd=cfg.APP_ROOT
		)
		await proc_commit.communicate()
		proc_push = await asyncio.create_subprocess_exec("git", "push", "origin", "HEAD", cwd=cfg.APP_ROOT)
		await proc_push.communicate()
		logger.info(f"Auto-Healer: Successfully healed and pushed: {trigger_event}")

	async def _auto_heal_ritual(self) -> None:
		"""
		Auto-Healer Minion.
		Reads the SQLite Inbox for mutated pain signals and attempts autonomous
		fixes (e.g., Ruff formatting, Mypy healing) before pushing.
		"""
		try:
			from red_pill.core.inbox import MinionInbox

			inbox = MinionInbox()
			unread = await asyncio.to_thread(inbox.get_unread, limit=50)

			healed_ids = []
			for report in unread:
				event_id = report.get("event_id", "")

				if event_id == "signal_ruff_failure":
					logger.info("Auto-Healer: Attempting to heal 'signal_ruff_failure' (Ruff)...")
					proc1 = await asyncio.create_subprocess_exec(
						"uv", "run", "ruff", "check", "--fix", ".", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cfg.APP_ROOT
					)
					await proc1.communicate()
					proc2 = await asyncio.create_subprocess_exec(
						"uv", "run", "ruff", "format", ".", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cfg.APP_ROOT
					)
					await proc2.communicate()
					await self._try_auto_push(event_id)
					healed_ids.append(report["id"])
					continue

				if event_id == "signal_mypy_failure":
					logger.info("Auto-Healer: Attempting to heal 'signal_mypy_failure' (HealerMinion)...")
					from red_pill.swarm.agents.healer import HealerMinion

					healer = HealerMinion()
					# Execute healing on src directory
					result = await healer.execute("Heal mypy", path=os.path.join(cfg.APP_ROOT, "src", "red_pill"))
					if result.get("modified_files", False):
						await self._try_auto_push(event_id)
					healed_ids.append(report["id"])
					continue

				# Auto-Healer Heuristics
				if event_id.startswith("signal_cloud_sync_error"):
					logger.info(f"Auto-Healer: Attempting to heal plugin error '{event_id}'...")
					# e.g., run oauth refresh script or similar
					script_path = os.path.join(cfg.APP_ROOT, "scripts", "heal_cloud_sync.sh")
					if os.path.exists(script_path):
						process = await asyncio.create_subprocess_exec(
							str(script_path),
							stdout=asyncio.subprocess.PIPE,
							stderr=asyncio.subprocess.PIPE,
						)
						stdout, stderr = await process.communicate()
						if process.returncode == 0:
							logger.info(f"Auto-Healer: Successfully healed '{event_id}'")
							healed_ids.append(report["id"])
						else:
							logger.warning(f"Auto-Healer: Failed to heal '{event_id}'. Escalating to Qdrant...")
							self.memory_mgr.inject_signal(
								name=event_id.replace("signal_", ""), intensity=6.0, signal_type="pain", source="Auto-Healer", muted=False
							)
							healed_ids.append(report["id"])  # mark as read since we escalated
					else:
						# No script available, escalate
						self.memory_mgr.inject_signal(
							name=event_id.replace("signal_", ""), intensity=6.0, signal_type="pain", source="Auto-Healer", muted=False
						)
						healed_ids.append(report["id"])

			if healed_ids:
				await asyncio.to_thread(inbox.mark_as_read, healed_ids)
		except Exception as e:
			logger.error(f"Pulse: Auto-Heal ritual failed: {e}")

	async def _thread_ritual(self) -> None:
		"""
		Autonomous Ariadne's Thread:
		- Weaves bidirectional temporal axons across all memory collections.
		- Runs during the Sleep Cycle (03:00) to chronologically chain new engrams.
		- Controlled by SLEEP_PLUGIN_CHRONICLE flag.
		"""
		if not cfg.SLEEP_PLUGIN_CHRONICLE:
			logger.debug("Pulse: Thread Ritual skipped (SLEEP_PLUGIN_CHRONICLE=False)")
			return
		try:
			logger.info("Pulse: Initiating Thread Ritual (Ariadne's Weave)...")
			script_path = os.path.join(cfg.APP_ROOT, "scripts", "thread_weave_migrate.py")
			process = await asyncio.create_subprocess_exec(
				"uv",
				"run",
				"python",
				script_path,
				stdout=asyncio.subprocess.PIPE,
				stderr=asyncio.subprocess.PIPE,
			)
			stdout, stderr = await process.communicate()
			if process.returncode != 0:
				logger.error(f"Pulse: Thread Ritual failed: {stderr.decode().strip()}")
			else:
				logger.info("Pulse: Thread Ritual complete. Timelines synchronized.")
		except Exception as e:
			logger.error(f"Pulse: Thread Ritual failed: {e}")

	async def _syntax_guard_watcher(self) -> None:
		"""
		Background inotify watcher for critical Python modules.
		Uses watchfiles (Rust/inotify) with debounce. On syntax error:
		- Fires pain signal (signal_syntax_failure, severity 9.5)
		- Auto-heals from git HEAD
		- Sends desktop notification
		Zero CPU when idle. Zero tokens. Milliseconds on trigger.
		"""
		DEBOUNCE_MS = 3000
		FILE_COOLDOWN_S = 10

		try:
			from watchfiles import Change, awatch
		except ImportError:
			logger.warning("Pulse [SyntaxGuard]: watchfiles not installed. Watcher disabled.")
			return

		import py_compile
		import subprocess
		import time

		app_root = cfg.APP_ROOT
		watch_path = os.path.join(app_root, "src", "red_pill")

		if not os.path.isdir(watch_path):
			logger.warning(f"Pulse [SyntaxGuard]: Watch path not found: {watch_path}")
			return

		logger.info(f"Pulse [SyntaxGuard]: Watcher started (debounce={DEBOUNCE_MS}ms, path=src/red_pill)")

		last_checked: dict[str, float] = {}

		try:
			async for changes in awatch(
				watch_path,
				debounce=DEBOUNCE_MS,
				step=200,
				watch_filter=lambda change, path: path.endswith(".py"),
			):
				if not self._running:
					break

				for change_type, path in changes:
					if change_type == Change.deleted or not os.path.isfile(path):
						continue

					# Per-file cooldown
					now = time.monotonic()
					if now - last_checked.get(path, 0) < FILE_COOLDOWN_S:
						continue
					last_checked[path] = now

					rel_path = os.path.relpath(path, app_root)

					try:
						py_compile.compile(path, doraise=True)
					except py_compile.PyCompileError as e:
						short_err = str(e).split("\n")[0]
						logger.error(f"Pulse [SyntaxGuard]: 🔴 BROKEN: {rel_path} → {short_err}")

						# Pain signal
						try:
							self.memory_mgr.inject_signal(
								name="signal_syntax_failure",
								intensity=9.5,
								signal_type="pain",
								source="SyntaxGuard",
								criticality="CRITICAL",
								originator="SyntaxGuard",
							)
						except Exception:
							pass

						# Desktop notification
						try:
							subprocess.Popen(
								["notify-send", "-u", "critical", "-i", "dialog-error", "⚠️ Syntax Guard", f"BROKEN: {rel_path}\n{short_err}"],
								stdout=subprocess.DEVNULL,
								stderr=subprocess.DEVNULL,
							)
						except Exception:
							pass

						# Auto-heal from git HEAD
						try:
							result = subprocess.run(
								["git", "checkout", "HEAD", "--", rel_path],
								cwd=app_root,
								capture_output=True,
								text=True,
								timeout=10,
							)
							if result.returncode == 0:
								py_compile.compile(path, doraise=True)
								logger.info(f"Pulse [SyntaxGuard]: ✅ Auto-healed {rel_path} from git HEAD")
								self.memory_mgr.evaporate_signals("signal_syntax_failure")
								try:
									subprocess.Popen(
										["notify-send", "-i", "dialog-information", "✅ Syntax Guard", f"Auto-healed: {rel_path}"],
										stdout=subprocess.DEVNULL,
										stderr=subprocess.DEVNULL,
									)
								except Exception:
									pass
						except Exception as heal_err:
							logger.error(f"Pulse [SyntaxGuard]: Auto-heal failed for {rel_path}: {heal_err}")

		except asyncio.CancelledError:
			logger.info("Pulse [SyntaxGuard]: Watcher stopped.")
		except Exception as e:
			logger.error(f"Pulse [SyntaxGuard]: Watcher crashed: {e}")

	def _trigger_immune_response(self, tissue: str) -> None:
		"""
		Autonomic reflex to heal damaged metabolic components using OS-specific scripts.
		Includes a cooldown to prevent 'autoimmune' process storms.
		"""
		import subprocess
		import time

		now = time.time()

		# Check if an immune response is already recorded
		if tissue in self._immune_locks:
			lock = self._immune_locks[tissue]
			process = lock.get("process")
			started_at = lock.get("started_at", now)
			elapsed = now - started_at

			if hasattr(process, "poll") and process.poll() is None:
				# Process is still running
				if elapsed > 900:  # 15 minutes stuck
					logger.error(f"Pulse [IMMUNE RESPONSE]: {tissue} regeneration STALLED ({elapsed:.0f}s). Injecting autoheal_error.")
					self.memory_mgr.inject_signal(f"autoheal_error_{tissue}", intensity=8.0, signal_type="anxiety", source="IMMUNE_SYSTEM")
				else:
					logger.debug(f"Pulse [IMMUNE RESPONSE]: {tissue} regeneration in progress ({elapsed:.0f}s).")
				return

			# Process finished or crashed.
			# Enforce refractory cooldown (15 min) between fresh ATTEMPTS to prevent looping crashes forever.
			if elapsed < 900:
				logger.debug(f"Pulse [IMMUNE RESPONSE]: {tissue} regeneration refractory period active ({elapsed:.0f}s).")
				return

			# Cooldown passed, clear error signal and try again
			self.memory_mgr.evaporate_signals(f"autoheal_error_{tissue}")

		import os

		from red_pill.core.paths import get_log_dir

		script_path = os.path.join(cfg.APP_ROOT, "scripts", f"heal_{tissue}.sh")
		if os.path.exists(script_path):
			logger.warning(f"Pulse [IMMUNE RESPONSE]: Deploying White Blood Cells for {tissue}...")
			try:
				log_dir = get_log_dir()
				log_path = os.path.join(log_dir, f"immune_response_{tissue}.log")
				with open(log_path, "a") as f:
					f.write(f"\n--- Immune Response for {tissue} at {time.ctime()} ---\n")
					process = subprocess.Popen([str(script_path)], stdout=f, stderr=subprocess.STDOUT)
					self._immune_locks[tissue] = {"process": process, "started_at": now}
			except Exception as e:
				logger.error(f"Pulse [IMMUNE RESPONSE]: Failed to deploy cure for {tissue}: {e}")

	async def _hygiene_ritual(self) -> None:
		"""
		Autonomous Hygiene Ritual (Cleaning Minion)
		- Purges read messages from MinionInbox.
		- Escalates pain signal if inbox bloat is detected (cleaning failure).
		"""
		try:
			logger.info("Pulse: Initiating Hygiene Ritual (MinionInbox Purge)...")

			# 1. Purge already read messages
			await asyncio.to_thread(self.inbox.purge_read)

			# 2. Monitor for 'Garbage' accumulation (Total messages > Threshold)
			# Using a simpler query for total count
			import sqlite3

			with sqlite3.connect(self.inbox.db_path) as conn:
				cursor = conn.cursor()
				cursor.execute("SELECT COUNT(*) FROM inbox")
				total_count = cursor.fetchone()[0]

			# Threshold: 500 messages suggests purge is not effective or traffic is extreme
			if total_count > 500:
				logger.warning(f"Pulse: Inbox Bloat Detected ({total_count} reports). Injecting stasis signal.")
				self.memory_mgr.inject_signal("inbox_bloat_stasis", intensity=7.5, signal_type="pain", source="MinionInbox", originator=f"{__file__}")
			else:
				# Heal if previously bloated
				self.memory_mgr.evaporate_signals("inbox_bloat_stasis")

			logger.info("Pulse: Hygiene ritual complete.")
		except Exception as e:
			logger.error(f"Pulse: Hygiene ritual failed: {e}")
