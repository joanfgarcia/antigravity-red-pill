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
		orphans = {p.name for p in _base(component).glob("*.txt")} - declared - _EXCEPTIONS
		assert not orphans, f"{component}: prompts huérfanos {sorted(orphans)}"


def test_fragmentos_no_duplicados_inline():
	for component in core.discover_components():
		for pid, spec in core._load_manifest(component).items():
			tpl = (_base(component) / spec["template"]).read_text(encoding="utf-8")
			for name, rel in (spec.get("fragments") or {}).items():
				frag = (core._FRAGMENTS_DIR / rel).read_text(encoding="utf-8")
				assert frag not in tpl, f"{component}/{pid}: fragmento '{name}' duplicado inline"


def test_sin_prompts_inline_en_modulos_migrados():
	repo_root = Path(core.__file__).resolve().parents[3]
	memento = repo_root / "src" / "red_pill" / "memento"
	ascension = (memento / "ascension.py").read_text(encoding="utf-8")
	assert "CLASSIFY_SYSTEM" not in ascension and "CLASSIFY_USER" not in ascension

	recalibrate = (repo_root / "scripts" / "memento_recalibrate.py").read_text(encoding="utf-8")
	assert "SYSTEM_CLASSIFY = " not in recalibrate and "SYSTEM_JUDGE = " not in recalibrate

	phases = repo_root / "src" / "red_pill" / "metabolism" / "phases"
	for name in ("recent_activity_phase.py", "operator_profile_phase.py"):
		text = (phases / name).read_text(encoding="utf-8")
		assert 'USER_PROMPT = """' not in text and "SYSTEM_PROMPT = " not in text
