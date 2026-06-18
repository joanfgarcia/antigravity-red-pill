"""
Biological Rituals — Stateless async functions for timer-triggered one-shots.

Extracted from heartbeat.py (LazarusPulse) in v7.2.1.
Each function receives its dependencies explicitly (MemoryManager, SoulManager).
No class, no state, no daemon — just pure rituals dispatched by trigger_pulse.py.
"""

import asyncio
import logging
import os
import sqlite3

import red_pill.config as cfg
from red_pill.core.inbox import MinionInbox
from red_pill.memory import MemoryManager

logger = logging.getLogger("red_pill.rituals")


# ──────────────────────────── Wake Rituals ────────────────────────────


async def maintenance_ritual(mm: MemoryManager) -> None:
	"""
	Autonomic Maintenance & Peripheral Diagnostics (Immune System Phase 1).
	- DB Connectivity (Hippocampus link)
	- Motor Cortex health (CUDA bindings)
	- Proactive Metabolism (Absence Guard sync)
	- Biological Dashboard: Migraine, Fever, Amnesia
	"""
	try:
		# 0. Motor Cortex (CUDA)
		try:
			import torch

			if not torch.cuda.is_available():
				logger.warning("Pulse: Motor Cortex Disconnected (CUDA missing). Injecting pain signal.")
				mm.inject_signal("cuda_cortex_failure", intensity=cfg.SIGNAL_BASE_PAIN_CUDA, signal_type="pain", source="CUDA")
			else:
				try:
					_ = torch.tensor([1.0], device="cuda")
					mm.evaporate_signals("cuda_cortex_failure")
					mm.evaporate_signals("autoheal_error_cuda")
				except Exception:
					logger.warning("Pulse: Motor Cortex Fault (CUDA tensor failed). Injecting pain signal.")
					mm.inject_signal("cuda_cortex_failure", intensity=cfg.SIGNAL_BASE_PAIN_CUDA, signal_type="pain", source="CUDA")
		except ImportError:
			logger.warning("Pulse: Motor Cortex NotFound (PyTorch missing). Injecting pain signal.")
			mm.inject_signal("cuda_cortex_failure", intensity=cfg.SIGNAL_BASE_PAIN_CUDA, signal_type="pain", source="CUDA")
		except Exception as cuda_ex:
			logger.warning(f"Pulse: Motor Cortex Laceration ({cuda_ex}). Injecting pain signal.")
			mm.inject_signal("cuda_cortex_failure", intensity=cfg.SIGNAL_BASE_PAIN_CUDA, signal_type="pain", source="CUDA")

		# 1. DB Connectivity (Hippocampus Link)
		try:
			mm.client.get_collections()
			logger.debug("Pulse: Bünker connectivity verified.")
			mm.evaporate_signals("qdrant_hypoxia")
		except Exception:
			logger.critical("Pulse: [COMA] Bünker connection lost. Memory injection impossible.")

		# 2. Absence Guard (Proactive TTL refresh)
		if cfg.METABOLISM_STRATEGY == "LAZY":
			logger.info("Pulse: Running proactive Absence Guard sync...")
			for coll in ["work_memories", "social_memories", "story_memories", "directive_memories"]:
				try:
					await asyncio.to_thread(mm.metabolism.refresh_ttl_timestamps, coll)
				except Exception as e:
					logger.error(f"Pulse: Absence Guard failed for {coll}: {e}")

		# 3. Biological Dashboard: Migraine (Database Bloat)
		try:
			count = mm.client.count(collection_name="work_memories").count
			if count > cfg.SIGNAL_MIGRAINE_VECTORS:
				logger.warning(f"Pulse: Semantic Bloat Detected ({count} vectors). Migraine signal injected.")
				mm.inject_signal("semantic_migraine", intensity=6.0, signal_type="fatigue", source="HIPPOCAMPUS")
			else:
				mm.evaporate_signals("semantic_migraine")
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
				mm.inject_signal("cpu_fever", intensity=7.0, signal_type="fever", source="HARDWARE")
			else:
				mm.evaporate_signals("cpu_fever")
		except ImportError:
			pass
		except Exception as e:
			logger.debug(f"Pulse: Fever check failed (no sensors): {e}")

		# 5. Biological Dashboard: Amnesia (Korsakoff Syndrome)
		if cfg.INTERCEPTOR_ENABLED:
			try:
				import datetime

				if os.path.exists(cfg.METABOLISM_STATE_FILE):
					mtime = os.path.getmtime(cfg.METABOLISM_STATE_FILE)
					hours_idle = (datetime.datetime.now().timestamp() - mtime) / 3600.0
					if hours_idle > cfg.SIGNAL_AMNESIA_HOURS:
						logger.warning(f"Pulse: Korsakoff Amnesia triggers ({hours_idle:.1f}h without interactions).")
						mm.inject_signal("korsakoff_amnesia", intensity=5.5, signal_type="anxiety", source="HIPPOCAMPUS")
					else:
						mm.evaporate_signals("korsakoff_amnesia")
			except Exception as e:
				logger.debug(f"Pulse: Amnesia check failed: {e}")

		logger.info("Pulse: Maintenance ritual complete. 770 stable.")

	except Exception as e:
		logger.error(f"Pulse: Maintenance ritual failed: {e}")


async def swarm_ritual(mm: MemoryManager) -> None:
	"""
	Autonomous Neon-Link Polling.
	Consults the local Neon-Link Hub for unread decrypted Swarm messages.
	"""
	try:
		import httpx

		async with httpx.AsyncClient() as client:
			resp = await client.get(f"{cfg.NEON_LINK_URL}/inbox/summary", timeout=2.0)

		if resp.status_code == 200:
			summary = resp.json()
			total_messages = sum(summary.values())
			if total_messages > 0:
				logger.info(f"Pulse: Discovered {total_messages} pending Swarm messages in Neon-Link.")
				mm.inject_signal("swarm_messages_pending", intensity=7.0, signal_type="anxiety", source="Neon-Link")
			else:
				mm.evaporate_signals("swarm_messages_pending")
	except Exception:
		logger.debug("Pulse: Neon-Link Hub is offline or unreachable.")


async def lazarus_ritual(mm: MemoryManager) -> None:
	"""
	Autonomous Lazarus Sync.
	Monitors local dock for sync-ready engrams and moves them to the Hive Mind.
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

		agent_id = f"Aleph@{cfg.OPERATOR_DISPLAY_NAME}"
		community_id = os.getenv("SWARM_DEFAULT_COMMUNITY", "canonical")

		sync = LazarusSync(community_id, agent_id)
		count = await asyncio.to_thread(sync.vacuum)

		if count > 0:
			logger.info(f"Pulse: Lazarus resurrected {count} engrams to the Hive.")
		else:
			logger.debug("Pulse: Local dock is clean.")

	except Exception as e:
		logger.error(f"Pulse: Lazarus ritual failed: {e}")


async def resonance_ritual(mm: MemoryManager) -> None:
	"""
	Autonomous Semantic Resonance.
	Searches the Hive Mind for content matching the agent's current focus.
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
		poc_vector = mm.embeddings.get_vector(focus_text)

		matches = await asyncio.to_thread(observer.check_resonance, hub_vector=poc_vector)

		for match in matches:
			await asyncio.to_thread(observer.trigger_reaction, match)

	except Exception as e:
		logger.error(f"Pulse: Resonance ritual failed: {e}")


async def hygiene_ritual(mm: MemoryManager) -> None:
	"""
	Autonomous Hygiene Ritual (MinionInbox Purge).
	Purges read messages and monitors for inbox bloat.
	"""
	try:
		logger.info("Pulse: Initiating Hygiene Ritual (MinionInbox Purge)...")

		inbox = MinionInbox()
		await asyncio.to_thread(inbox.purge_read)

		with sqlite3.connect(inbox.db_path) as conn:
			cursor = conn.cursor()
			cursor.execute("SELECT COUNT(*) FROM inbox")
			total_count = cursor.fetchone()[0]

		if total_count > 500:
			logger.warning(f"Pulse: Inbox Bloat Detected ({total_count} reports). Injecting stasis signal.")
			mm.inject_signal("inbox_bloat_stasis", intensity=7.5, signal_type="pain", source="MinionInbox")
		else:
			mm.evaporate_signals("inbox_bloat_stasis")

		logger.info("Pulse: Hygiene ritual complete.")
	except Exception as e:
		logger.error(f"Pulse: Hygiene ritual failed: {e}")


# ──────────────────────────── Sleep Rituals ────────────────────────────


async def usp_ritual(mm: MemoryManager) -> None:
	"""
	Autonomous Operator Mood Profile (USP) Refresh.
	Recalculates emotional resonance vectors across temporal horizons.
	"""
	try:
		from red_pill.utils.mood_profile import _get_dominant_color, update_usp

		logger.info("Pulse: Initiating USP Ritual (Operator Mood Profile refresh)...")
		usp = await asyncio.to_thread(update_usp, mm)

		dominant = _get_dominant_color(usp.get("last_3d", {}))
		count = usp.get("interaction_count", 0)
		logger.info(f"Pulse: USP updated. Dominant 3d: {dominant}, interactions: {count}")

	except Exception as e:
		logger.error(f"Pulse: USP ritual failed: {e}")


async def dream_ritual(mm: MemoryManager) -> None:
	"""
	Autonomous Oneiromancy.
	Finds latent semantic associations between memories (cognitive dreaming).
	"""
	try:
		logger.info("Pulse: Initiating Oneiromancy (Dream Ritual)...")
		for coll in ["work_memories", "social_memories", "story_memories"]:
			try:
				await asyncio.to_thread(mm.dream, coll)
			except Exception as e:
				logger.error(f"Pulse: Dream failed for {coll}: {e}")

		logger.info("Pulse: Oneiromancy complete. Patterns woven.")
	except Exception as e:
		logger.error(f"Pulse: Dream ritual failed: {e}")


async def consolidation_ritual(mm: MemoryManager) -> None:
	"""
	Autonomous Consolidation.
	Phase 0: Snatch trajectories from active LanguageServers into staging.
	Phase 1: Processes raw interactions into long-term memories.
	"""
	try:
		# Phase 0: LS Snatcher
		try:
			from red_pill.metabolism.ls_snatcher import snatch_all_trajectories

			logger.info("Pulse: Initiating LS Snatcher (Extracting LanguageServer trajectories)...")
			snatched = await asyncio.to_thread(snatch_all_trajectories)
			logger.info(f"Pulse: LS Snatcher complete. {snatched} trajectories staged.")
		except Exception as e:
			logger.warning(f"Pulse: LS Snatcher failed (non-fatal, continuing): {e}")

		# Phase 1: Consolidation
		from red_pill.metabolism.sleep import perform_sleep_cycle

		logger.info("Pulse: Initiating Consolidation (Consolidating interactions)...")
		await asyncio.to_thread(perform_sleep_cycle, mm, mode="lazy")
		logger.info("Pulse: Consolidation complete. Memories fixed.")
	except Exception as e:
		logger.error(f"Pulse: Consolidation ritual failed: {e}")


async def thread_ritual() -> None:
	"""
	Autonomous Ariadne's Thread.
	Weaves bidirectional temporal axons across all memory collections.
	Controlled by SLEEP_PLUGIN_CHRONICLE flag.
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


# ──────────────────────────── Healing ────────────────────────────


async def auto_heal_ritual(mm: MemoryManager) -> None:
	"""
	Auto-Healer Minion.
	Reads the SQLite Inbox for mutated pain signals and attempts autonomous fixes.
	"""
	try:
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
				healed_ids.append(report["id"])
				continue

			if event_id == "signal_mypy_failure":
				logger.info("Auto-Healer: Attempting to heal 'signal_mypy_failure' (HealerMinion)...")
				from red_pill.swarm.agents.healer import HealerMinion

				healer = HealerMinion()
				await healer.execute("Heal mypy", path=os.path.join(cfg.APP_ROOT, "src", "red_pill"))
				healed_ids.append(report["id"])
				continue

			if event_id.startswith("signal_cloud_sync_error"):
				logger.info(f"Auto-Healer: Attempting to heal plugin error '{event_id}'...")
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
					else:
						logger.warning(f"Auto-Healer: Failed to heal '{event_id}'. Escalating...")
						mm.inject_signal(name=event_id.replace("signal_", ""), intensity=6.0, signal_type="pain", source="Auto-Healer", muted=False)
					healed_ids.append(report["id"])
				else:
					mm.inject_signal(name=event_id.replace("signal_", ""), intensity=6.0, signal_type="pain", source="Auto-Healer", muted=False)
					healed_ids.append(report["id"])

			# SIP Provisioning heal — local LLM offline or missing volatile artifacts
			if event_id in ("signal_local_llm_offline",) or event_id.startswith("signal_sip_missing_"):
				logger.info(f"Auto-Healer: Attempting SIP provisioning heal for '{event_id}'...")
				try:
					from red_pill.metabolism.sentinel_plugins.check_sip_provisioning import SipProvisioningCheck

					plugin = SipProvisioningCheck()
					config = cfg.get_config()
					findings = await asyncio.to_thread(plugin._audit_provisioning, config)
					if findings:
						healed = await asyncio.to_thread(plugin.heal_specific, config, findings[0])
						if healed:
							logger.info(f"Auto-Healer: SIP infrastructure re-provisioned successfully.")
							mm.evaporate_signals("local_llm_offline")
						else:
							logger.warning(f"Auto-Healer: SIP heal_specific returned False for '{findings[0].type}'.")
					else:
						logger.info("Auto-Healer: SIP provisioning chain is intact, evaporating stale signal.")
						mm.evaporate_signals("local_llm_offline")
				except Exception as sip_err:
					logger.error(f"Auto-Healer: SIP provisioning heal failed: {sip_err}")
				healed_ids.append(report["id"])
				continue

		if healed_ids:
			await asyncio.to_thread(inbox.mark_as_read, healed_ids)
	except Exception as e:
		logger.error(f"Pulse: Auto-Heal ritual failed: {e}")
