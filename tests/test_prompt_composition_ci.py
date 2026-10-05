"""CI del modelo de prompts (PROMPT-001 F4).

- `validate_all()` en verde para todos los componentes.
- Sin prompts huérfanos (todo `.txt` declarado en su manifiesto).
- Sin fragmentos duplicados inline en los templates.
- Sin prompts inline en los módulos ya migrados (RULE 5).
"""

from __future__ import annotations

from pathlib import Path

from red_pill.core import prompts as core

# Plantilla de identidad: no es un prompt del pase (la Bio se resuelve aparte).
_EXCEPTIONS = {"identity_bio.template.txt"}


def _base(component: str) -> Path:
	return core._manifest_path(component).parent


def test_validate_all_en_verde():
	assert core.validate_all() == []


def test_sin_prompts_huerfanos():
	for component in core.discover_components():
		declared = set()
		for spec in core._load_manifest(component).values():
			declared.add(Path(spec["template"]).name)
			if spec.get("system"):
				declared.add(Path(spec["system"]).name)
		orphans = {p.name for p in _base(component).rglob("*.txt")} - declared - _EXCEPTIONS
		assert not orphans, f"{component}: prompts huérfanos {sorted(orphans)}"


def test_fragmentos_no_duplicados_inline():
	"""Un fragmento no debe aparecer copiado en ningún template (ni declarado ni
	no declarado). Se compara en forma normalizada (NFC/LF) contra el template
	CRUDO, no contra el source compuesto (que lo contiene por construcción)."""
	for component in core.discover_components():
		specs = core._load_manifest(component)
		rels = {rel for spec in specs.values() for rel in (spec.get("fragments") or {}).values()}
		for pid, spec in specs.items():
			raw = core._normalize((_base(component) / spec["template"]).read_text(encoding="utf-8"))
			for rel in rels:
				frag = core._normalize((core._FRAGMENTS_DIR / rel).read_text(encoding="utf-8"))
				assert frag not in raw, f"{component}/{pid}: fragmento {rel} duplicado inline"


def test_sin_prompts_inline_en_modulos_migrados():
	repo_root = Path(core.__file__).resolve().parents[3]
	src = repo_root / "src" / "red_pill"

	def text(rel: str) -> str:
		return (src / rel).read_text(encoding="utf-8")

	ascension = text("memento/ascension.py")
	assert "CLASSIFY_SYSTEM" not in ascension and "CLASSIFY_USER" not in ascension

	distiller = text("metabolism/distiller.py")
	assert "[Refraction: NEOCORTEX_SYNTHESIS]" not in distiller
	assert "Analyze these technical memory hubs" not in distiller

	recalibrate = (repo_root / "scripts" / "memento_recalibrate.py").read_text(encoding="utf-8")
	assert "SYSTEM_CLASSIFY = " not in recalibrate and "SYSTEM_JUDGE = " not in recalibrate
	assert "Clasifica estos " not in recalibrate and "Juzga estos " not in recalibrate

	phases = src / "metabolism" / "phases"
	for name in ("recent_activity_phase.py", "operator_profile_phase.py"):
		phase = (phases / name).read_text(encoding="utf-8")
		assert 'USER_PROMPT = """' not in phase and "SYSTEM_PROMPT = " not in phase

	# ── F5: perímetro completo (RULE 5) ────────────────────────────────────
	assert "Resume en UNA frase el ESTADO actual" not in text("metabolism/situation_semaphore.py")
	assert "You are a conversation summarizer" not in text("inference/samantha_worker.py")
	assert "You are an internal routing Gatekeeper" not in text("interceptors/03_circuit_breaker.py")
	assert "You are the internal consciousness of Aleth" not in text("cognitive/drive_evaluator.py")
	assert "You are a local minion. You have EXACTLY these tools" not in text("swarm/agents/local_minion.py")
	assert "You are a local minion. Answer the task" not in text("swarm/agents/local_minion.py")
	assert "You are an expert Python developer fixing Mypy" not in text("swarm/agents/healer.py")
	assert "Security Analysis Request" not in text("swarm/agents/smith.py")
	assert "[Refraction: SAMANTHA]" not in text("swarm/agents/samantha.py")
	assert "[Refraction: TECHNICAL_EXTRACTOR]" not in text("swarm/agents/edge_engine.py")
	assert "Is this interaction 'Know-How'" not in text("hive.py")
	assert "Responde SOLO: OK" not in text("swarm/bridges/claude.py")
	assert "Responde SOLO: OK" not in text("swarm/bridges/opencode.py")
	assert "Responde SOLO: OK" not in text("swarm/bridges/pi.py")
	assert "Responde SOLO: OK" not in text("plugins/antigravity_ide/agy_bridge.py")
	assert "<conversation_history>" not in text("core/agent_worker.py")
	assert "[SYSTEM: COGNITIVE EVALUATOR INJECTION]" not in text("plugins/antigravity_ide/pulse.py")
