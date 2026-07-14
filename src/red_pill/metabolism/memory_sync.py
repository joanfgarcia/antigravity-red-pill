import importlib.util
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, List, Optional

import red_pill.config as cfg
from red_pill.core import workspaces as ws_core
from red_pill.core.workspaces import Workspace
from red_pill.memory import MemoryManager
from red_pill.swarm.bridges import create_bridge

logger = logging.getLogger("red_pill.metabolism.memory_sync")


def _resolve_prompt_path(prompt_setting: str) -> Path:
	"""Resolve the compaction prompt path.
	If relative, resolves relative to APP_ROOT. Otherwise absolute."""
	path = Path(prompt_setting)
	if path.is_absolute():
		return path
	return Path(cfg.get_config().APP_ROOT) / path


def execute_preservation_hook(ws: Workspace) -> str:
	"""Dynamically loads and runs memory_hooks.py in .red-pill/ or fallback .agent/ (read-only).
	Returns the preservation context string, or empty string on error/absence."""
	hook_file = ws.root / ".red-pill" / "memory_hooks.py"
	if not hook_file.exists():
		hook_file = ws.root / ".agent" / "memory_hooks.py"
		if not hook_file.exists():
			return ""

	logger.info(f"Workspace Memory Hook: Found hooks at {hook_file}")
	try:
		# Isolate module load using a unique namespace based on workspace name
		module_name = f"rp_hooks_{ws.name}"
		spec = importlib.util.spec_from_file_location(module_name, str(hook_file))
		if spec and spec.loader:
			module = importlib.util.module_from_spec(spec)
			sys.modules[module_name] = module
			spec.loader.exec_module(module)
			if hasattr(module, "get_preservation_context"):
				context = module.get_preservation_context(str(ws.root))
				logger.info(f"Workspace Memory Hook [{ws.name}]: Executed successfully.")
				return str(context or "").strip()
			else:
				logger.warning(f"Workspace Memory Hook [{ws.name}]: get_preservation_context function not found in hook file.")
	except Exception as hook_err:
		logger.error(f"Workspace Memory Hook [{ws.name}]: Failed to load/execute: {hook_err}", exc_info=True)
	return ""


def sync_workspace_memory(ws: Workspace, mm: MemoryManager) -> None:
	"""Scaffolds workspace memory directory and projects memories from Qdrant into decisions.md."""
	mem_path = ws.get_memory_path
	if not mem_path:
		logger.debug(f"Workspace Memory [{ws.name}]: Memory serving disabled.")
		return

	try:
		# 1. Scaffolding
		os.makedirs(str(mem_path), exist_ok=True)
		os.makedirs(str(mem_path / "history" / "archived"), exist_ok=True)

		# 2. MEMORY.md Scaffold if missing
		memory_file = mem_path / "MEMORY.md"
		if not memory_file.exists():
			template_path = Path(cfg.get_config().APP_ROOT) / "seeds" / "memory" / "MEMORY.md.template"
			if template_path.exists():
				template = template_path.read_text(encoding="utf-8")
				content = template.replace("${WORKSPACE_NAME}", ws.name)
				memory_file.write_text(content, encoding="utf-8")
				logger.info(f"Workspace Memory [{ws.name}]: Scaffolded MEMORY.md from template.")
			else:
				# Fallback if seed template is missing
				memory_file.write_text(f"# Workspace Memory: {ws.name}\n\nPer-workspace technical index.\n", encoding="utf-8")

		# 3. Fetch from Qdrant work_memories
		client = mm.client
		points: List[Any] = []
		offset = None
		while True:
			pts, offset = client.scroll(collection_name="work_memories", limit=100, offset=offset, with_payload=True)
			points.extend(pts)
			if not offset:
				break

		# A workspace matches by its registry name OR by the munged absolute path
		# used by IDE chroniclers (Claude Code names project dirs "-home-joan-...").
		ws_aliases = {ws.name, str(ws.root).replace(os.sep, "-")}

		# Filter workspace-specific memories
		matching_points = []
		for p in points:
			if not p.payload:
				continue
			meta = p.payload.get("metadata", {})
			# Check flat and nested metadata tags
			ws_val = p.payload.get("workspace") or p.payload.get("project") or meta.get("workspace") or meta.get("project")
			if ws_val in ws_aliases:
				matching_points.append(p)

		# Sort chronologically by created_at (default to 0.0 if missing)
		matching_points.sort(key=lambda x: x.payload.get("created_at", 0.0))

		# Format decisions history in markdown
		decisions_lines = [
			f"# Technical Decisions & Timeline: {ws.name}",
			"",
			"Chronological history of technical decisions, patterns, and events recorded in the Bünker.",
			"",
		]
		for p in matching_points:
			created_at_float = p.payload.get("created_at", 0.0)
			try:
				time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created_at_float))
			except Exception:
				time_str = "Unknown Date"
			importance = p.payload.get("importance", 1.0)
			emotion = p.payload.get("emotion", "neutral")
			content = p.payload.get("content", "").strip()
			decisions_lines.append(f"### [{time_str}] (Importance: {importance}, Emotion: {emotion})")
			decisions_lines.append(content)
			decisions_lines.append("")

		decisions_file = mem_path / f"{ws.name}-decisions.md"
		decisions_file.write_text("\n".join(decisions_lines), encoding="utf-8")
		logger.info(f"Workspace Memory [{ws.name}]: Projected {len(matching_points)} engrams into decisions.md.")

		# 4. Preservation Hooks (checks pending indicator or missing architecture file)
		pending_indicator = mem_path / ".arch_sync_pending"
		arch_file = mem_path / f"{ws.name}-architecture.md"
		if pending_indicator.exists() or not arch_file.exists():
			context = execute_preservation_hook(ws)
			if context:
				arch_file.write_text(context, encoding="utf-8")
				logger.info(f"Workspace Memory [{ws.name}]: Regeneration of architecture file completed.")
			elif not arch_file.exists():
				# Write a placeholder if hooks return empty but file is missing
				arch_file.write_text(f"# Architecture Index: {ws.name}\n\n(No custom hooks configured or executed)\n", encoding="utf-8")

			# Clean up indicator
			if pending_indicator.exists():
				try:
					pending_indicator.unlink()
				except Exception:
					pass

	except Exception as err:
		logger.error(f"Workspace Memory [{ws.name}]: Synchronization failed: {err}", exc_info=True)


def sync_all_workspaces(mm: MemoryManager) -> None:
	"""Triggers memory sync for all workspaces with memory enabled."""
	workspaces = ws_core.list_workspaces()
	enabled_ws = [w for w in workspaces if w.memory is not False]
	logger.info(f"Workspace Memory Sync: Starting sync for {len(enabled_ws)} workspaces.")
	for ws in enabled_ws:
		sync_workspace_memory(ws, mm)
	logger.info("Workspace Memory Sync: Sychronization pass completed.")


def compact_workspace_memory(ws: Workspace, mm: MemoryManager) -> None:
	"""Triggers LLM compaction on workspace memory files to avoid context bloat."""
	mem_path = ws.get_memory_path
	if not mem_path:
		return

	memory_file = mem_path / "MEMORY.md"
	decisions_file = mem_path / f"{ws.name}-decisions.md"
	arch_file = mem_path / f"{ws.name}-architecture.md"

	if not decisions_file.exists():
		logger.debug(f"Workspace Compaction [{ws.name}]: No decisions file found; compaction skipped.")
		return

	# Load context files
	decisions_text = decisions_file.read_text(encoding="utf-8")
	arch_text = arch_file.read_text(encoding="utf-8") if arch_file.exists() else ""
	current_memory = memory_file.read_text(encoding="utf-8") if memory_file.exists() else ""

	conf = cfg.get_config()
	prompt_seed_path = _resolve_prompt_path(conf.WORKSPACE_MEMORY_COMPACT_PROMPT)
	if not prompt_seed_path.exists():
		logger.warning(f"Workspace Compaction [{ws.name}]: Compaction prompt seed not found at {prompt_seed_path}. Compaction aborted.")
		return

	logger.info(f"Workspace Compaction [{ws.name}]: Initiating LLM consolidation...")
	try:
		prompt_template = prompt_seed_path.read_text(encoding="utf-8")
		full_prompt = (
			f"{prompt_template}\n\n"
			f"--- ARCHITECTURE REFERENCE ---\n{arch_text}\n\n"
			f"--- CURRENT MEMORY INDEX ---\n{current_memory}\n\n"
			f"--- LATEST TIMELINE LOG ---\n{decisions_text}\n"
		)

		bridge = create_bridge(conf.WORKSPACE_MEMORY_COMPACT_BACKEND)
		res = bridge.prompt(text=full_prompt, model=conf.WORKSPACE_MEMORY_COMPACT_MODEL, cwd=str(ws.root), timeout=300)

		if not res.ok:
			logger.warning(f"Workspace Compaction [{ws.name}]: LLM execution failed: {res.error}")
			return

		compacted_text = res.response.strip()
		if not compacted_text:
			logger.warning(f"Workspace Compaction [{ws.name}]: LLM returned empty result. Preserving original memory.")
			return

		# Atomic Replace Strategy (OOM & Amnesia Shield)
		tmp_file = mem_path / "MEMORY.md.tmp"
		bak_file = mem_path / "MEMORY.md.bak"

		tmp_file.write_text(compacted_text, encoding="utf-8")
		if memory_file.exists():
			if bak_file.exists():
				bak_file.unlink()
			shutil.copy2(str(memory_file), str(bak_file))

		os.replace(str(tmp_file), str(memory_file))
		logger.info(f"Workspace Compaction [{ws.name}]: Consolidation completed atomically. Backup saved to MEMORY.md.bak.")

	except Exception as comp_err:
		logger.error(f"Workspace Compaction [{ws.name}]: Compaction process failed: {comp_err}", exc_info=True)


def compact_all_workspaces(mm: MemoryManager) -> None:
	"""Runs compaction/optimization cycle across all enabled workspaces."""
	workspaces = ws_core.list_workspaces()
	enabled_ws = [w for w in workspaces if w.memory is not False]
	logger.info(f"Workspace Compaction: Optimizing {len(enabled_ws)} workspaces.")
	for ws in enabled_ws:
		compact_workspace_memory(ws, mm)
	logger.info("Workspace Compaction: Pass completed.")


def enable_workspace_memory(ws_name_or_path: str, custom_path: Optional[str] = None) -> bool:
	"""Enables memory indexation for a workspace, setting up scaffolding and pending indicator."""
	registry = ws_core.load_registry()
	target = ws_core._match(registry, ws_name_or_path)
	if not target:
		logger.error(f"Enable Workspace Memory: Workspace '{ws_name_or_path}' not found in registry.")
		return False

	# Resolve custom memory path representation if provided
	val: Any = True
	if custom_path:
		val = Path(os.path.expanduser(custom_path))
		# If relative, validate it could resolve relative to root
		if not val.is_absolute():
			val = Path(custom_path)

	updated = target.model_copy(update={"memory": val})
	workspaces = [updated if w.name == target.name else w for w in registry.workspaces]
	ws_core.save_registry(ws_core.WorkspaceRegistry(agent_core=registry.agent_core, workspaces=workspaces, version=registry.version))
	logger.info(f"Enable Workspace Memory: Workspace '{target.name}' memory serving enabled.")

	# Touch .arch_sync_pending in the memory folder to trigger initial hook sync
	mem_path = updated.get_memory_path
	if mem_path:
		os.makedirs(str(mem_path), exist_ok=True)
		pending_indicator = mem_path / ".arch_sync_pending"
		pending_indicator.touch(exist_ok=True)

	# Trigger immediate sync
	sync_workspace_memory(updated, MemoryManager())
	return True


def disable_workspace_memory(ws_name_or_path: str) -> bool:
	"""Disables memory serving for a workspace by setting its memory field to False."""
	registry = ws_core.load_registry()
	target = ws_core._match(registry, ws_name_or_path)
	if not target:
		logger.error(f"Disable Workspace Memory: Workspace '{ws_name_or_path}' not found in registry.")
		return False

	updated = target.model_copy(update={"memory": False})
	workspaces = [updated if w.name == target.name else w for w in registry.workspaces]
	ws_core.save_registry(ws_core.WorkspaceRegistry(agent_core=registry.agent_core, workspaces=workspaces, version=registry.version))
	logger.info(f"Disable Workspace Memory: Workspace '{target.name}' memory serving disabled.")
	return True
