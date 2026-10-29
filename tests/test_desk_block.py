"""desk_block.py — bloque gestionado del seed dentro de un documento del desk.

Contrato que se fija aquí: el frontmatter y lo que quede FUERA de las marcas es
del desk y no se toca nunca; dentro de las marcas manda el seed, con merge de 3
vías si ambos cambian, y con `*.seed-new` (sin escribir) si hay conflicto.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("desk_block", ROOT / "scripts" / "desk_block.py")
desk_block = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desk_block)

FM = '---\ntitle: "El mío"\nauthor: "Aleth"\n---\n\n'


def _seed(tmp_path: Path, body: str) -> Path:
	p = tmp_path / "seed.md"
	p.write_text(FM + desk_block.build_block(body) + "\n", encoding="utf-8")
	return p


def _desk(tmp_path: Path, body: str | None) -> Path:
	p = tmp_path / "desk" / "doc.md"
	p.parent.mkdir(parents=True, exist_ok=True)
	if body is not None:
		p.write_text(FM + desk_block.build_block(body) + "\n", encoding="utf-8")
	return p


def _base(tmp_path: Path, body: str | None) -> Path:
	p = tmp_path / "desk" / ".germ.baseline" / "doc.md"
	if body is not None:
		p.parent.mkdir(parents=True, exist_ok=True)
		p.write_text(body + "\n", encoding="utf-8")
	return p


def test_created_copia_el_seed_y_anota_la_base(tmp_path: Path) -> None:
	seed = _seed(tmp_path, "convención v1")
	desk = _desk(tmp_path, None)
	base = _base(tmp_path, None)
	assert desk_block.cmd_splice(seed, desk, base) == "created"
	assert "convención v1" in desk.read_text(encoding="utf-8")
	assert base.read_text(encoding="utf-8").strip() == "convención v1"


def test_init_envuelve_el_cuerpo_del_desk_sin_cambiar_una_linea(tmp_path: Path) -> None:
	seed = _seed(tmp_path, "convención del seed")
	desk = tmp_path / "desk" / "doc.md"
	desk.parent.mkdir(parents=True, exist_ok=True)
	original = FM + "## Mi sección local\n\ntexto del desk\n"
	desk.write_text(original, encoding="utf-8")
	base = _base(tmp_path, None)

	assert desk_block.cmd_init(seed, desk, base) == "wrapped"
	after = desk.read_text(encoding="utf-8")
	assert after.startswith(FM), "el frontmatter se queda fuera del bloque"
	assert "texto del desk" in after
	# La base es el cuerpo del SEED: lo del desk queda como modificación local.
	assert base.read_text(encoding="utf-8").strip() == "convención del seed"
	assert desk_block.cmd_splice(seed, desk, base) == "local"
	assert "texto del desk" in desk.read_text(encoding="utf-8")


def test_actualiza_cuando_el_desk_no_toco_el_bloque(tmp_path: Path) -> None:
	seed = _seed(tmp_path, "v1")
	desk = _desk(tmp_path, "v1")
	base = _base(tmp_path, "v1")
	seed.write_text(FM + desk_block.build_block("v2") + "\n", encoding="utf-8")
	assert desk_block.cmd_splice(seed, desk, base) == "updated"
	assert "v2" in desk.read_text(encoding="utf-8")


def test_seed_sin_cambios_respeta_el_bloque_del_desk(tmp_path: Path) -> None:
	seed = _seed(tmp_path, "convención")
	desk = _desk(tmp_path, "convención + excepción del desk")
	base = _base(tmp_path, "convención")
	assert desk_block.cmd_splice(seed, desk, base) == "local"
	assert "excepción del desk" in desk.read_text(encoding="utf-8")


def test_ambos_cambiaron_sin_solapar_se_fusionan(tmp_path: Path) -> None:
	seed = _seed(tmp_path, "linea A\nlinea B\nlinea C")
	desk = _desk(tmp_path, "linea A\nlinea B\nlinea C\nexcepción local")
	base = _base(tmp_path, "linea A\nlinea B\nlinea C")
	seed.write_text(FM + desk_block.build_block("linea A\nlinea B v2\nlinea C") + "\n", encoding="utf-8")
	assert desk_block.cmd_splice(seed, desk, base) == "merged"
	merged = desk.read_text(encoding="utf-8")
	assert "linea B v2" in merged, "la novedad del seed entra"
	assert "excepción local" in merged, "y la excepción del desk sobrevive"


def test_conflicto_no_escribe_y_deja_el_seed_al_lado(tmp_path: Path) -> None:
	seed = _seed(tmp_path, "v1")
	desk = _desk(tmp_path, "v1 del desk")
	base = _base(tmp_path, "v1")
	seed.write_text(FM + desk_block.build_block("v2 del seed") + "\n", encoding="utf-8")
	antes = desk.read_text(encoding="utf-8")
	assert desk_block.cmd_splice(seed, desk, base) == "conflict"
	assert desk.read_text(encoding="utf-8") == antes, "el desk no se toca"
	lado = Path(str(desk) + ".seed-new")
	assert lado.exists() and "v2 del seed" in lado.read_text(encoding="utf-8")


def test_sin_base_conserva_el_desk_y_adopta_el_seed(tmp_path: Path) -> None:
	seed = _seed(tmp_path, "convención")
	desk = _desk(tmp_path, "otra cosa del desk")
	base = _base(tmp_path, None)
	assert desk_block.cmd_splice(seed, desk, base) == "local"
	assert "otra cosa del desk" in desk.read_text(encoding="utf-8")
	assert base.read_text(encoding="utf-8").strip() == "convención"


def test_frontmatter_y_lo_de_fuera_del_bloque_son_del_desk(tmp_path: Path) -> None:
	seed = _seed(tmp_path, "v1")
	desk = tmp_path / "desk" / "doc.md"
	desk.parent.mkdir(parents=True, exist_ok=True)
	desk.write_text(
		FM + desk_block.build_block("v1") + "\n## Notas de este desk\n\nno se tocan\n",
		encoding="utf-8",
	)
	base = _base(tmp_path, "v1")
	seed.write_text(FM + desk_block.build_block("v2") + "\n", encoding="utf-8")
	assert desk_block.cmd_splice(seed, desk, base) == "updated"
	final = desk.read_text(encoding="utf-8")
	assert '"El mío"' in final, "el frontmatter del desk sobrevive"
	assert "v2" in final
	assert "no se tocan" in final, "lo de después del bloque sobrevive"


def test_ficha_sin_bloque_se_añade_al_final_sin_tocar_lo_que_hay(tmp_path: Path) -> None:
	seed = _seed(tmp_path, "convención")
	desk = tmp_path / "desk" / "doc.md"
	desk.parent.mkdir(parents=True, exist_ok=True)
	desk.write_text(FM + "## Prosa antigua del desk\n", encoding="utf-8")
	base = _base(tmp_path, None)
	assert desk_block.cmd_splice(seed, desk, base) == "appended"
	final = desk.read_text(encoding="utf-8")
	assert "Prosa antigua del desk" in final
	assert "convención" in final


def test_remove_retira_la_region_del_seed_y_deja_lo_del_desk(tmp_path: Path) -> None:
	"""Desinstalar es retirar LO NUESTRO: el documento y su prosa se quedan."""
	desk = tmp_path / "desk" / "doc.md"
	desk.parent.mkdir(parents=True, exist_ok=True)
	desk.write_text(FM + desk_block.build_block("convención") + "\n\n## Local\n", encoding="utf-8")
	assert desk_block.cmd_remove(desk) == "removed"
	final = desk.read_text(encoding="utf-8")
	assert "REDPILL:" not in final, "no quedan marcas colgando"
	assert "convención" not in final, "la región del seed se retira con él"
	assert "## Local" in final, "lo del desk se queda"


def test_created_pone_marcas_aunque_el_seed_no_las_traiga(tmp_path: Path) -> None:
	"""Un seed sin marcas no debe acabar en un desk sin bloque (se duplicaría)."""
	seed = tmp_path / "seed.md"
	seed.write_text(FM + "# Título\n\ncuerpo del seed\n", encoding="utf-8")
	desk = _desk(tmp_path, None)
	base = _base(tmp_path, None)
	assert desk_block.cmd_splice(seed, desk, base) == "created"
	assert "REDPILL:BEGIN" in desk.read_text(encoding="utf-8")
	assert desk_block.cmd_splice(seed, desk, base) == "unchanged"
	assert desk.read_text(encoding="utf-8").count("cuerpo del seed") == 1, "no se duplica"
