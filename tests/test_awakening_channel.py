"""Tests del canal de notas del despertar (AWAKEN-002, direcciones 1 y 3)."""

from __future__ import annotations

from pathlib import Path

from red_pill.core import awakening_channel as ch


def _write(p: Path, text: str) -> Path:
	p.parent.mkdir(parents=True, exist_ok=True)
	p.write_text(text, encoding="utf-8")
	return p


def test_ensure_channel_crea_notes_y_done(tmp_path):
	notes = ch.ensure_channel(tmp_path)
	assert notes.is_dir() and (tmp_path / "awakening" / "done").is_dir()
	assert ch.get_notes_root(tmp_path) == tmp_path / "awakening" / "notes"


def test_nota_para_operador_pendiente_y_leida(tmp_path):
	ch.ensure_channel(tmp_path)
	f = _write(
		tmp_path / "awakening" / "notes" / "20260928_0600_job-muerto.md",
		"---\ntitle: Job muerto\npara: Joan\n---\n\n# Decisión pendiente\n\nEl job bd6dc260 murió por disyuntor.\n\n" + ch.signature("Aleth", "2026-09-28T06:00") + "\n",
	)
	n = ch.parse_note(f)
	assert n.title == "Job muerto"
	assert n.targets_operator("Joan")
	assert n.pending_for_operator("Joan")
	assert ch.count_for_operator(tmp_path, operator="Joan") == 1

	f.write_text(f.read_text(encoding="utf-8") + f"\n## Leída 2026-09-28T07:00\n\nVisto, re-encolo.\n\n{ch.signature('Joan', '2026-09-28T07:00')}\n", encoding="utf-8")
	assert not ch.parse_note(f).pending_for_operator("Joan")
	assert ch.count_for_operator(tmp_path, operator="Joan") == 0


def test_nota_deber_direccion_1(tmp_path):
	ch.ensure_channel(tmp_path)
	f = _write(
		tmp_path / "awakening" / "notes" / "20260928_0100_deber.md",
		"# Mañana comprueba X\n\nTermina el bake-off.\n",
	)
	n = ch.parse_note(f)
	assert not n.targets_operator("Joan")
	assert not n.marks
	assert [d.slug for d in ch.duty_notes(tmp_path, operator="Joan")] == ["20260928_0100_deber"]


def test_para_en_cuerpo_no_frontmatter(tmp_path):
	ch.ensure_channel(tmp_path)
	f = _write(tmp_path / "awakening" / "notes" / "n.md", "# Hola\n\npara: Joan\n\nAlgo.\n")
	assert ch.parse_note(f).targets_operator("Joan")


def test_marca_ajena_no_cuenta_como_leida_por_operador(tmp_path):
	ch.ensure_channel(tmp_path)
	f = _write(
		tmp_path / "awakening" / "notes" / "n.md",
		"# Hola\n\npara: Joan\n\n## Leída 2026-09-28T06:00\n\nLo vi.\n\n" + ch.signature("Aleth", "2026-09-28T06:00") + "\n",
	)
	assert not ch.parse_note(f).operator_read("Joan")
	assert ch.parse_note(f).pending_for_operator("Joan")


def test_signature_y_filename():
	assert ch.signature("Aleth", "2026-09-28T06:00") == "— Aleth · 2026-09-28T06:00"
	assert ch.note_filename.__name__ == "note_filename"
	fn = ch.note_filename(__import__("datetime").datetime(2026, 9, 28, 6, 0), "Job muerto!!")
	assert fn == "20260928_0600_job-muerto.md"


def test_list_notes_include_done(tmp_path):
	ch.ensure_channel(tmp_path)
	_write(tmp_path / "awakening" / "notes" / "a.md", "# A\n")
	_write(tmp_path / "awakening" / "done" / "b.md", "# B\n")
	assert len(ch.list_notes(tmp_path)) == 1
	assert len(ch.list_notes(tmp_path, include_done=True)) == 2
	assert ch.parse_note(tmp_path / "awakening" / "done" / "b.md").done is True
