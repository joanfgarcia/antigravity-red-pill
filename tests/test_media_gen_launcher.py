"""`media_gen.py` — launcher de consola `media-gen`.

Cubre las ramas de fallo limpio (forge/launcher ausentes) y el exec real
(mockeado). SHARD-PV-02: `media_gen.py` era el único módulo del alcance
extendido a 0% de cobertura.
"""

from __future__ import annotations

from red_pill import media_gen


def test_falla_sin_forge(monkeypatch, tmp_path, capsys):
	"""Sin el python del forge → rc=1 y mensaje de error (no revienta)."""
	forge = tmp_path / "noforge"
	forge.mkdir()
	monkeypatch.setattr(media_gen, "get_forge_home", lambda *a, **k: forge)
	assert media_gen.main() == 1
	assert "forge de imagen no encontrado" in capsys.readouterr().err


def test_falla_sin_launcher(monkeypatch, tmp_path, capsys):
	"""Con el forge pero sin gen_cli.py → rc=1."""
	forge = tmp_path / "forge"
	(forge / "venv" / "bin").mkdir(parents=True)
	(forge / "venv" / "bin" / "python").write_text("x")
	root = tmp_path / "root"
	root.mkdir()
	monkeypatch.setattr(media_gen, "get_forge_home", lambda *a, **k: forge)
	monkeypatch.setattr(media_gen, "get_bunker_root", lambda *a, **k: root)
	assert media_gen.main() == 1
	assert "launcher no encontrado" in capsys.readouterr().err


def test_exec_pasa_argv_al_launcher(monkeypatch, tmp_path):
	"""Con ambos presentes → execv(py, [py, launcher, *argv[1:]]) y rc=0 (exec mockeado)."""
	forge = tmp_path / "forge"
	(forge / "venv" / "bin").mkdir(parents=True)
	py = forge / "venv" / "bin" / "python"
	py.write_text("x")
	root = tmp_path / "root"
	launcher = root / "scripts" / "imagegen" / "gen_cli.py"
	launcher.parent.mkdir(parents=True)
	launcher.write_text("x")
	seen: dict = {}
	monkeypatch.setattr(media_gen, "get_forge_home", lambda *a, **k: forge)
	monkeypatch.setattr(media_gen, "get_bunker_root", lambda *a, **k: root)
	monkeypatch.setattr(media_gen.os, "execv", lambda path, argv: seen.update(path=path, argv=argv))
	monkeypatch.setattr("sys.argv", ["media-gen", "--list-models"])
	assert media_gen.main() == 0
	assert seen["path"] == str(py)
	assert seen["argv"] == [str(py), str(launcher), "--list-models"]
