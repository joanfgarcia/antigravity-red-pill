"""scaffold_desk.sh — política de divergencia del GERMEN (código vs prosa).

Fija la matriz de TRES hashes (base sembrada / cur en el desk / new en el seed)
contra el bug que motivó el cambio: comparando sólo `cur != new`, una edición
local del desk se revertía **aunque el seed no hubiera cambiado nada**.

Doctrina que se comprueba aquí:

  CÓDIGO  → el seed manda siempre; si no consta que el desk esté intacto, se
            respalda antes y se avisa (un parche local invisible es un fork).
  PROSA   → el desk manda; no se pisa nunca, y si hay novedad del seed se deja
            al lado como `*.seed-new`.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "scaffold_desk.sh"

PROSE = "planner/README.md"
CODE = "planner/tools/panel.py"
PUESTO = "INDEX.md"


def _seed_tree(tmp_path: Path) -> Path:
	seed = tmp_path / "repo" / "seeds" / "desk"
	for rel, body in {
		PROSE: "# Planner\n\nv1\n",
		CODE: "print('v1')\n",
		PUESTO: "# índice del seed\n",
	}.items():
		p = seed / rel
		p.parent.mkdir(parents=True, exist_ok=True)
		p.write_text(body, encoding="utf-8")
	(seed / ".germ").write_text(f"{PROSE}\n{CODE}\n", encoding="utf-8")
	return seed


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
	env = dict(os.environ)
	env["REPO_ROOT"] = str(tmp_path / "repo")
	env["AGENT_CORE_DIR"] = str(tmp_path / "desk")
	return subprocess.run(
		["bash", str(SCRIPT)],
		env=env,
		capture_output=True,
		text=True,
		check=True,
	)


def _install(tmp_path: Path) -> tuple[Path, Path]:
	seed = _seed_tree(tmp_path)
	_run(tmp_path)
	return seed, tmp_path / "desk"


def _write(path: Path, body: str) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(body, encoding="utf-8")


def test_primera_instalacion_crea_y_siembra_la_base(tmp_path: Path) -> None:
	seed = _seed_tree(tmp_path)
	res = _run(tmp_path)
	desk = tmp_path / "desk"
	assert res.returncode == 0
	assert (desk / PROSE).read_text(encoding="utf-8") == (seed / PROSE).read_text(encoding="utf-8")
	assert (desk / CODE).exists()
	state = (desk / ".germ.state").read_text(encoding="utf-8")
	assert PROSE in state and CODE in state
	assert "nuevos=3" in res.stdout


def test_sin_cambios_no_toca_nada(tmp_path: Path) -> None:
	seed, desk = _install(tmp_path)
	before = (desk / PROSE).read_text(encoding="utf-8")
	res = _run(tmp_path)
	assert (desk / PROSE).read_text(encoding="utf-8") == before
	assert "intactos=3" in res.stdout  # 2 germen idénticos + 1 puesto
	assert "AVISO" not in res.stderr


def test_solo_cambio_el_seed_actualiza_en_silencio(tmp_path: Path) -> None:
	seed, desk = _install(tmp_path)
	_write(seed / PROSE, "# Planner\n\nv2\n")
	res = _run(tmp_path)
	assert (desk / PROSE).read_text(encoding="utf-8") == "# Planner\n\nv2\n"
	assert not (desk / f"{PROSE}.seed-new").exists()
	assert "AVISO" not in res.stderr
	assert "actualizados=1" in res.stdout


def test_solo_cambio_el_desk_se_respeta_por_el_bug_que_esto_arregla(tmp_path: Path) -> None:
	"""El caso que hoy revertía trabajo: desk editado, seed SIN cambios."""
	seed, desk = _install(tmp_path)
	_write(desk / PROSE, "# Planner\n\nmi versión local\n")
	res = _run(tmp_path)
	assert (desk / PROSE).read_text(encoding="utf-8") == "# Planner\n\nmi versión local\n"
	assert not (desk / f"{PROSE}.seed-new").exists(), "el seed no cambió: no hay nada que ofrecer"
	assert "AVISO" not in res.stderr, "no hay conflicto que anunciar"
	assert "locales=1" in res.stdout
	assert not (desk / ".germ.bak").exists(), "no se respalda lo que no se toca"


def test_ambos_cambiaron_la_prosa_conserva_el_desk_y_deja_el_seed_al_lado(tmp_path: Path) -> None:
	seed, desk = _install(tmp_path)
	_write(desk / PROSE, "# Planner\n\nmi versión local\n")
	_write(seed / PROSE, "# Planner\n\nv2 del seed\n")
	res = _run(tmp_path)
	assert (desk / PROSE).read_text(encoding="utf-8") == "# Planner\n\nmi versión local\n"
	assert (desk / f"{PROSE}.seed-new").read_text(encoding="utf-8") == "# Planner\n\nv2 del seed\n"
	assert "cambiado en el desk y en el seed" in res.stderr
	assert "conflictos=1" in res.stdout


def test_el_conflicto_de_prosa_sigue_vivo_hasta_resolverlo(tmp_path: Path) -> None:
	"""La base NO se reescribe con la versión del desk: el aviso se repite."""
	seed, desk = _install(tmp_path)
	_write(desk / PROSE, "local\n")
	_write(seed / PROSE, "seed v2\n")
	_run(tmp_path)
	res = _run(tmp_path)
	assert "conflictos=1" in res.stdout
	assert (desk / PROSE).read_text(encoding="utf-8") == "local\n"


def test_codigo_parcheado_en_el_desk_se_revierte_con_backup_y_aviso(tmp_path: Path) -> None:
	seed, desk = _install(tmp_path)
	_write(desk / CODE, "print('parche local')\n")
	res = _run(tmp_path)
	assert (desk / CODE).read_text(encoding="utf-8") == (seed / CODE).read_text(encoding="utf-8")
	backups = list((desk / ".germ.bak").rglob("panel.py"))
	assert len(backups) == 1
	assert backups[0].read_text(encoding="utf-8") == "print('parche local')\n"
	assert "el código no se parchea en local" in res.stderr
	assert "revertidos=1" in res.stdout


def test_sin_registro_previo_la_prosa_no_se_pisa(tmp_path: Path) -> None:
	"""Sin `.germ.state` no se sabe quién cambió qué: en prosa, gana el desk."""
	seed = _seed_tree(tmp_path)
	_write(tmp_path / "desk" / PROSE, "texto del desk sin registro\n")
	res = _run(tmp_path)
	assert (tmp_path / "desk" / PROSE).read_text(encoding="utf-8") == "texto del desk sin registro\n"
	assert not (tmp_path / "desk" / f"{PROSE}.seed-new").exists(), "sin base no se duplica: el seed está en el repo"
	assert "sin registro de siembra previa" in res.stderr
	assert str(seed / PROSE) in res.stderr, "el aviso debe decir contra qué fichero se compara"

	# El aviso es ÚNICO: a partir de la primera vez la base ya existe y se calla.
	res2 = _run(tmp_path)
	assert "sin registro de siembra previa" not in res2.stderr
	assert "locales=1" in res2.stdout
	assert "sin_registro=1" in res.stdout


def test_sin_registro_previo_el_codigo_se_alinea_con_el_seed(tmp_path: Path) -> None:
	"""Caso real: un `state.py` viejo en el desk. Se alinea, pero con copia."""
	seed = _seed_tree(tmp_path)
	_write(tmp_path / "desk" / CODE, "print('viejo')\n")
	res = _run(tmp_path)
	assert (tmp_path / "desk" / CODE).read_text(encoding="utf-8") == (seed / CODE).read_text(encoding="utf-8")
	assert list((tmp_path / "desk" / ".germ.bak").rglob("panel.py"))
	assert "AVISO" in res.stderr


def test_el_puesto_nunca_se_pisa(tmp_path: Path) -> None:
	"""`INDEX.md` es el mapa del desk: copy-if-absent y punto."""
	_seed_tree(tmp_path)
	_write(tmp_path / "desk" / PUESTO, "# mi índice, 99 líneas propias\n")
	_run(tmp_path)
	_run(tmp_path)
	assert (tmp_path / "desk" / PUESTO).read_text(encoding="utf-8") == "# mi índice, 99 líneas propias\n"


def test_no_siembra_bytecode_ni_basura_de_sistema(tmp_path: Path) -> None:
	"""El seed llevaba un `__pycache__` suelto: no es contenido, es residuo."""
	seed = _seed_tree(tmp_path)
	pyc = seed / "planner" / "tools" / "__pycache__" / "panel.cpython-314.pyc"
	pyc.parent.mkdir(parents=True, exist_ok=True)
	pyc.write_text("basura", encoding="utf-8")
	(seed / ".DS_Store").write_text("x", encoding="utf-8")
	_run(tmp_path)
	desk = tmp_path / "desk"
	assert not (desk / "planner" / "tools" / "__pycache__").exists()
	assert not (desk / ".DS_Store").exists()
