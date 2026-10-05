"""F5: migración completa a composición — distiller_v3(+voice) y situation_distiller.

Fixture `prompt_goldens_pre_f5.json` generada con el render pre-F5 (rama
`feat/prompt-composition-f1`). Se exige:
- byte-equivalencia en los prompts no tocados (`engram_quality_auditor`);
- reconstrucción controlada en los tocados (`distiller_v3`, `distiller_v3_voice`):
  el bloque de idioma inline → fragmento `language`, el bloque de perspectiva →
  fragmento de voz, y se retiran las frases STRICT de idioma duplicadas en los
  bullets. Nada más cambia.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from red_pill.core import prompts as core

FIXTURE = Path(__file__).parent / "fixtures" / "prompt_goldens_pre_f5.json"
FIX = json.loads(FIXTURE.read_text(encoding="utf-8"))
VALUES = FIX["values"]

STRICT_SUMMARY = (
	"STRICT RULE: Write 'summary' in the EXACT SAME LANGUAGE as the source text (if input is Spanish, write in Spanish; if English, in English). "
)
STRICT_TEXTURE = "STRICT RULE: Write 'texture' in the EXACT SAME LANGUAGE as the source text. "


def _fragment(name: str) -> str:
	return core._normalize((core._FRAGMENTS_DIR / name).read_text(encoding="utf-8"))


def _resolved_fragment(name: str) -> str:
	text = _fragment(name)
	for key, value in VALUES.items():
		text = text.replace("${" + key + "}", value)
	return text.replace("${prompt_language}", str(core._STATIC_PROVIDERS["prompt_language"]()))


def _expected(old: str, voice_fragment: str) -> str:
	lang_block = old[old.index("CRITICAL LANGUAGE RULE (MANDATORY):") : old.index("PERSPECTIVE & RELATIONAL FRAME (MANDATORY):")].rstrip("\n")
	voice_block = old[old.index("PERSPECTIVE & RELATIONAL FRAME (MANDATORY):") : old.index("CRITICAL FIDELITY RULES:")].rstrip("\n")
	out = old.replace(lang_block, _resolved_fragment("language.txt")).replace(voice_block, _resolved_fragment(voice_fragment))
	return out.replace(STRICT_SUMMARY, "").replace(STRICT_TEXTURE, "")


def test_engram_auditor_byte_exacto():
	out = core.render("metabolism", "engram_quality_auditor", static=VALUES)
	assert out == FIX["prompts"]["engram_quality_auditor"]["rendered"]


@pytest.mark.parametrize(
	"pid,voice_fragment",
	[("distiller_v3", "voice_distiller.txt"), ("distiller_v3_voice", "voice_distiller_b.txt")],
)
def test_distiller_reconstruccion_controlada(pid, voice_fragment):
	out = core.render("metabolism", pid, static=VALUES)
	assert out == _expected(FIX["prompts"][pid]["rendered"], voice_fragment)
	assert "LANGUAGE RULE (MANDATORY)" in out
	assert "CRITICAL LANGUAGE RULE" not in out
	assert "STRICT RULE: Write" not in out
	assert "${" not in out


def test_situation_distiller_compone_language_y_text():
	out = core.render("metabolism", "situation_distiller", text="hola")
	assert "LANGUAGE RULE (MANDATORY)" in out
	assert '"situation"' in out and "hola" in out
	assert "${" not in out


def test_circuit_breaker_system_equivale_al_inline():
	out = core.render("interceptors", "circuit_breaker_system")
	assert out.startswith("You are an internal routing Gatekeeper.")
	assert "[VALID]" in out and "INSUFFICIENT_CONTEXT" in out
	assert "${" not in out


def test_drive_evaluator_compone_user_y_system():
	user = core.render("cognitive", "drive_evaluator_user", context="BACKLOG: nada")
	system = core.system_text("cognitive", "drive_evaluator_user")
	assert "BACKLOG: nada" in user
	assert "autonomous_research" in user and "graphify_sync" in user
	assert user.endswith("conversational filler.")
	assert system and "dynamic task generation sub-routine" in system
	assert "${" not in user


def test_swarm_local_minion_budget_y_answer():
	system = core.render("swarm", "local_minion_system", max_tool_calls=8)
	assert "at most 8 tool calls" in system
	answer = core.render("swarm", "local_minion_answer_user", task="T", tool_output="OUT")
	assert answer == "Task: T\n\nTool output:\nOUT\n\nAnswer:"


def test_swarm_healer_smith_hive_y_sonda():
	healer = core.render("swarm", "healer_fix_user", file_path="a.py", error="err", line=7, original_line="    x = 1")
	assert "FILE: a.py" in healer and "LINE 7:     x = 1" in healer
	smith = core.render("swarm", "smith_security_user", snippet="eval(x)", finding="B307")
	assert "eval(x)" in smith and "B307" in smith
	hive = core.render("swarm", "hive_guard_user", content="hola")
	assert 'Engram: "hola"' in hive
	assert core.render("swarm", "liveness_probe") == "Responde SOLO: OK"
	assert core.render("swarm", "samantha_system").startswith("[Refraction: SAMANTHA]")
	assert core.render("swarm", "technical_extractor_system").startswith("[Refraction: TECHNICAL_EXTRACTOR]")


def test_pulse_injection_y_agent_worker():
	queue = core.render(
		"plugins/antigravity_ide",
		"pulse_cognitive_queue_user",
		rule_run_cmd="1. REGLA",
		task_id="T1",
		task_source="drive_evaluator",
		payload='{"a":1}',
	)
	assert queue.startswith("<user_rules>") and queue.endswith("Execute this task silently.")
	assert "1. REGLA" in queue and "Task ID: T1" in queue
	agy = core.render("plugins/antigravity_ide", "pulse_cognitive_agy_user", task_id="T2", task_source="s", payload="P")
	assert "AgyBridge with auto-approval" in agy and "Task ID: T2" in agy
	conv = core.render("core/agent_prompts", "conversation_task_user", history="H", task="T")
	assert conv == "<conversation_history>\nH\n</conversation_history>\n\n<current_task>\nT\n</current_task>"


def test_validate_all_sin_errores():
	assert core.validate_all() == []
