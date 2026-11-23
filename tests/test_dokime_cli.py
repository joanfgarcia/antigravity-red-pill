"""Tests del CLI del banco (scripts/dokime.py): desk de intercambio y kernel.

Lo que se prueba aquí NO arranca podman: son las piezas que deciden rutas y
copian ficheros, que es donde un error se paga caro (un desk mal resuelto deja
al alma escribiendo en un directorio que el Operador no puede leer).

El kernel se prueba con `dry-run` y con el fallback: el worktree real lo crea
`update` en la máquina, no la suite.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys

REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DOKIME_PATH = os.path.join(REPO_ROOT, "scripts", "dokime.py")


def _load_dokime() -> object:
	spec = importlib.util.spec_from_file_location("dokime_under_test", DOKIME_PATH)
	mod = importlib.util.module_from_spec(spec)
	sys.modules["dokime_under_test"] = mod
	spec.loader.exec_module(mod)
	return mod


def _args(**kw) -> argparse.Namespace:
	base = {"desk_cmd": "path", "items": [], "to": None, "from_dir": None, "move": False}
	base.update(kw)
	return argparse.Namespace(**base)


def test_desk_path_points_at_host_and_container(tmp_path, monkeypatch, capsys):
	dok = _load_dokime()
	monkeypatch.setattr(dok, "DESK_HOST", tmp_path / "desk")
	assert dok.desk(_args(desk_cmd="path")) == 0
	out = capsys.readouterr().out
	assert str(tmp_path / "desk") in out
	assert dok.DESK_MOUNT in out


def test_desk_put_creates_both_mailboxes_and_copies(tmp_path, monkeypatch):
	dok = _load_dokime()
	monkeypatch.setattr(dok, "DESK_HOST", tmp_path / "desk")
	origin = tmp_path / "informe.txt"
	origin.write_text("para el alma", encoding="utf-8")

	assert dok.desk(_args(desk_cmd="put", items=[str(origin)])) == 0
	assert (tmp_path / "desk" / dok.DESK_INBOX / "informe.txt").read_text(encoding="utf-8") == "para el alma"
	assert (tmp_path / "desk" / dok.DESK_OUTBOX).is_dir()


def test_desk_put_reports_missing_source_without_aborting(tmp_path, monkeypatch, capsys):
	dok = _load_dokime()
	monkeypatch.setattr(dok, "DESK_HOST", tmp_path / "desk")
	good = tmp_path / "bien.txt"
	good.write_text("ok", encoding="utf-8")

	rc = dok.desk(_args(desk_cmd="put", items=[str(tmp_path / "fantasma.txt"), str(good)]))
	assert rc == 1  # el fallo se ve, pero el resto se copia igual
	assert (tmp_path / "desk" / dok.DESK_INBOX / "bien.txt").exists()
	assert "no existe" in capsys.readouterr().err


def test_desk_get_copies_from_outbox_and_move_borra_el_original(tmp_path, monkeypatch):
	dok = _load_dokime()
	desk = tmp_path / "desk"
	monkeypatch.setattr(dok, "DESK_HOST", desk)
	(desk / dok.DESK_OUTBOX).mkdir(parents=True)
	(desk / dok.DESK_OUTBOX / "respuesta.md").write_text("hecho", encoding="utf-8")
	destino = tmp_path / "recogido"

	rc = dok.desk(_args(desk_cmd="get", to=str(destino), move=True))
	assert rc == 0
	assert (destino / "respuesta.md").read_text(encoding="utf-8") == "hecho"
	assert not (desk / dok.DESK_OUTBOX / "respuesta.md").exists()


def test_desk_get_sin_ficheros_no_inventa_exito(tmp_path, monkeypatch, capsys):
	dok = _load_dokime()
	monkeypatch.setattr(dok, "DESK_HOST", tmp_path / "desk")
	assert dok.desk(_args(desk_cmd="get", items=["*.md"], to=str(tmp_path / "x"))) == 1
	assert "nada que traer" in capsys.readouterr().err


def test_kernel_source_cae_al_checkout_si_no_hay_worktree(tmp_path, monkeypatch):
	dok = _load_dokime()
	monkeypatch.delenv("DOKIME_SOURCE_REPO", raising=False)
	monkeypatch.setattr(dok, "KERNEL_WORKTREE", tmp_path / "no-existe")
	assert dok._kernel_source() == dok.SOURCE_REPO


def test_kernel_source_respeta_la_chincheta_explicita(tmp_path, monkeypatch):
	dok = _load_dokime()
	monkeypatch.setenv("DOKIME_SOURCE_REPO", "/ruta/fijada")
	monkeypatch.setattr(dok, "KERNEL_WORKTREE", tmp_path)
	(tmp_path / ".git").mkdir()
	assert dok._kernel_source() == dok.SOURCE_REPO  # la chincheta gana al worktree


def test_sync_kernel_dry_run_no_escribe_nada(tmp_path, monkeypatch, capsys):
	dok = _load_dokime()
	worktree = tmp_path / "kernel"
	monkeypatch.setattr(dok, "KERNEL_WORKTREE", worktree)

	before, after = dok._sync_kernel("next", fetch=False, force=False, dry_run=True)
	assert before is None and after is None
	assert not worktree.exists()
	assert "[dry-run]" in capsys.readouterr().out


def test_desk_put_reemplaza_un_fichero_del_alma(tmp_path, monkeypatch):
	"""El uid del alma no es el del Operador: sobrescribir en sitio falla, reemplazar no."""
	dok = _load_dokime()
	monkeypatch.setattr(dok, "DESK_HOST", tmp_path / "desk")
	origin = tmp_path / "entrega.md"
	origin.write_text("v1", encoding="utf-8")
	assert dok.desk(_args(desk_cmd="put", items=[str(origin)])) == 0

	target = tmp_path / "desk" / dok.DESK_INBOX / "entrega.md"
	target.chmod(0o444)  # simula fichero ajeno (no escribible en sitio)
	origin.write_text("v2", encoding="utf-8")
	assert dok.desk(_args(desk_cmd="put", items=[str(origin)])) == 0
	assert target.read_text(encoding="utf-8") == "v2"


def test_host_uid_in_traduce_el_uid_del_sandbox(monkeypatch):
	dok = _load_dokime()
	mappings = {
		"uidmap": [
			{"container_id": 0, "host_id": 1000, "size": 1},
			{"container_id": 1, "host_id": 100000, "size": 65536},
		]
	}
	assert dok._host_uid_in(mappings, 0) == os.getuid()  # root del contenedor = Operador
	assert dok._host_uid_in(mappings, 1001) == 101000  # el usuario `dokime` de la imagen
	assert dok._host_uid_in(mappings, 99999) is None  # fuera de todo mapa: no se adivina


def test_grant_desk_acl_no_toca_nada_sin_caja_viva(tmp_path, monkeypatch):
	dok = _load_dokime()
	monkeypatch.setattr(dok, "DESK_HOST", tmp_path / "desk")
	monkeypatch.setattr(dok, "_is_running", lambda name: False)
	dok._ensure_desk()
	dok._grant_desk_acl()  # no debe ni intentarlo
	assert (tmp_path / "desk" / dok.DESK_INBOX).is_dir()


def test_mounts_need_refresh_no_opina_si_la_caja_no_existe(monkeypatch):
	dok = _load_dokime()
	monkeypatch.setattr(dok, "_exists", lambda kind, name: False)
	assert dok._mounts_need_refresh() == []


def test_box_config_roundtrip_reconstruye_la_misma_caja(tmp_path, monkeypatch):
	"""Recrear con el entorno vacío dejaba Titanium con el modelo de Dokimé."""
	dok = _load_dokime()
	monkeypatch.setattr(dok, "BOX_STATE", tmp_path / "boxes" / "dokime.json")
	monkeypatch.setattr(dok, "LLAMA_MODEL", "/models/spark.gguf")
	monkeypatch.setattr(dok, "LLAMA_CTX", 131072)
	monkeypatch.setattr(dok, "LLAMA_ALIAS", "spark")
	monkeypatch.setattr(dok, "LLAMA_GPU", True)
	monkeypatch.setenv("DOKIME_EXTRA_MOUNTS", "/ruta/repo:/srv/dokime/project:ro")
	dok._save_box_config()

	# Otro arranque, entorno vacío: los defaults del módulo.
	monkeypatch.setattr(dok, "LLAMA_MODEL", "/models/mimo.gguf")
	monkeypatch.setattr(dok, "LLAMA_CTX", 16384)
	monkeypatch.setattr(dok, "LLAMA_ALIAS", "mimo")
	monkeypatch.setattr(dok, "LLAMA_GPU", False)
	monkeypatch.delenv("DOKIME_EXTRA_MOUNTS")

	dok._adopt_box_config()
	assert dok.LLAMA_MODEL == "/models/spark.gguf"
	assert dok.LLAMA_CTX == 131072
	assert dok.LLAMA_ALIAS == "spark"
	assert dok.LLAMA_GPU is True
	assert os.environ["DOKIME_EXTRA_MOUNTS"] == "/ruta/repo:/srv/dokime/project:ro"


def test_adopt_box_config_no_pisa_lo_que_el_operador_declara_ahora(tmp_path, monkeypatch):
	dok = _load_dokime()
	monkeypatch.setattr(dok, "BOX_STATE", tmp_path / "dokime.json")
	monkeypatch.setattr(dok, "LLAMA_CTX", 65536)
	dok._save_box_config()

	monkeypatch.setattr(dok, "LLAMA_CTX", 16384)  # lo que el import leyó del entorno actual
	monkeypatch.setenv("DOKIME_CTX", "16384")
	dok._adopt_box_config()
	assert dok.LLAMA_CTX == 16384  # manda lo declarado ahora, no lo guardado
