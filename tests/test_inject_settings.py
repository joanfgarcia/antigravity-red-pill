"""inject_settings: los bloques de hook de red-pill se reemplazan, no se duplican."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
SCRIPT = os.path.join(REPO_ROOT, "scripts", "inject_settings.py")
SEED = os.path.join(REPO_ROOT, "seeds", "settings", "claude-code.json")
HOOKS_DIR = os.path.join(REPO_ROOT, "seeds", "settings", "hooks")


def _load():
	spec = importlib.util.spec_from_file_location("inject_settings_under_test", SCRIPT)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["inject_settings_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


def _block(script, timeout=10, msg=None):
	hook = {"type": "command", "command": f"python3 /h/.claude/hooks/{script}", "timeout": timeout}
	if msg:
		hook["statusMessage"] = msg
	return {"hooks": [hook]}


USER_BLOCK = {"hooks": [{"type": "command", "command": "notify-send listo"}]}
MIXED_BLOCK = {"hooks": [{"type": "command", "command": "python3 /h/.claude/hooks/redpill_scribe.py"}, {"type": "command", "command": "echo mío"}]}


def _frag():
	return {
		"permissions": {"additionalDirectories": ["/x"]},
		"hooks": {
			"Stop": [_block("redpill_scribe.py", timeout=15, msg="nuevo")],
			"StopFailure": [_block("redpill_turn_start.py", timeout=5)],
		},
	}


def test_changed_block_replaces_old_one():
	m = _load()
	settings = {
		"hooks": {
			"Stop": [USER_BLOCK, _block("redpill_scribe.py", timeout=10, msg="viejo"), MIXED_BLOCK],
		}
	}
	m.merge_fragment(settings, _frag())
	stop = settings["hooks"]["Stop"]
	assert stop == [USER_BLOCK, MIXED_BLOCK, _block("redpill_scribe.py", timeout=15, msg="nuevo")]
	assert settings["hooks"]["StopFailure"] == [_block("redpill_turn_start.py", timeout=5)]
	assert settings["permissions"]["additionalDirectories"] == ["/x"]


def test_merge_is_idempotent_and_collapses_duplicates():
	m = _load()
	current = _block("redpill_scribe.py", timeout=15, msg="nuevo")
	settings = {"hooks": {"Stop": [current, USER_BLOCK, copy.deepcopy(current)]}}
	m.merge_fragment(settings, _frag())
	assert settings["hooks"]["Stop"] == [current, USER_BLOCK]
	once = copy.deepcopy(settings)
	m.merge_fragment(settings, _frag())
	assert settings == once


def test_block_moved_to_another_event_is_dropped():
	m = _load()
	settings = {"hooks": {"Notification": [_block("redpill_turn_start.py")], "PreToolUse": []}}
	m.merge_fragment(settings, _frag())
	assert "Notification" not in settings["hooks"]
	assert settings["hooks"]["PreToolUse"] == []  # lo vacío que no vació la poda se respeta


def test_remove_drops_stale_managed_blocks_only():
	m = _load()
	settings = {
		"hooks": {
			"Stop": [_block("redpill_scribe.py", timeout=10, msg="viejo"), USER_BLOCK],
			"SessionEnd": [_block("redpill_turn_start.py", timeout=3)],
		}
	}
	m.remove_fragment(settings, _frag())
	assert settings == {"hooks": {"Stop": [USER_BLOCK]}}


def test_seed_hooks_carry_the_ownership_marker():
	"""Convención de la que depende la poda: todo script de hook es redpill_*.py y todo
	bloque del fragmento se reconoce como de red-pill (si no, se duplicaría)."""
	m = _load()
	scripts = [f for f in os.listdir(HOOKS_DIR) if f.endswith(".py")]
	assert scripts and all(f.startswith("redpill_") for f in scripts)
	with open(SEED, encoding="utf-8") as f:
		seed = json.load(f)
	for event, blocks in seed["hooks"].items():
		for block in blocks:
			resolved = json.loads(json.dumps(block).replace("${HOME}", "/home/someone"))
			assert m._is_managed_block(resolved), event
