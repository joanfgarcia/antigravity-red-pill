#!/usr/bin/env python3
"""Puerta de aislamiento de Dokimé (RFC-HARNESS-001 · W2).

Se ejecuta **dentro** del contenedor y devuelve 0 sólo si todo el estado resuelve
al volumen. Es la puerta, no un informe: si algo cae fuera, rc=1 y no se despierta
a nadie.

Comprueba las tres direcciones del aislamiento:

1. **Escritura**: cada getter de `core/paths.py` cae dentro de `/srv/dokime`.
2. **Guard de producción**: `_assert_not_production_dir` aborta con una ruta real.
3. **Repo del Operador**: montado `:ro` (no se puede escribir `.git` → sin escape
   por refs/hooks); `git-common-dir` no aplica porque no hay worktree.

Además: `HOME` dentro del volumen (hay lectores que usan `Path.home()` ignorando
XDG) y `QDRANT_HOST` apuntando al Qdrant del sandbox.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

VOLUME = "/srv/dokime"
failures: list[str] = []


def check(label: str, path: object) -> None:
	p = Path(str(path)).resolve()
	ok = str(p).startswith(VOLUME)
	print(f"{'ok  ' if ok else 'MAL '} {label:26s} {p}")
	if not ok:
		failures.append(f"{label} -> {p}")


def main() -> int:
	sys.path.insert(0, "/src/red-pill/src")
	try:
		from red_pill.core import paths
	except Exception as exc:  # noqa: BLE001
		print(f"MAL  no se pudo importar red_pill.core.paths: {exc}")
		return 1

	check("get_bunker_root", paths.get_bunker_root())
	check("get_data_dir", paths.get_data_dir())
	check("get_state_dir", paths.get_state_dir())
	check("get_queue_dir", paths.get_queue_dir())
	check("get_log_dir", paths.get_log_dir())
	check("get_config_dir", paths.get_config_dir())
	check("get_keys_dir", paths.get_keys_dir())
	check("get_backups_dir", paths.get_backups_dir())

	# El guard de producción debe ABORTAR. Ojo: dentro del sandbox "producción"
	# se calcula desde SU `$HOME` (el volumen), no desde el del Operador; así que
	# la ruta de prueba es la de producción *del contenedor*. Si el guard no
	# dispara, cualquier getter que resolviera a `$HOME/.local/share/red-pill`
	# pasaría desapercibido.
	os.environ["REDPILL_TESTING"] = "1"
	try:
		from red_pill.core.paths import _assert_not_production_dir

		fake_prod = Path.home() / ".local" / "share" / "red-pill"
		_assert_not_production_dir(fake_prod, "prueba de aislamiento")
		failures.append("el guard de producción NO abortó con una ruta real")
		print("MAL  guard de producción: no abortó")
	except Exception as exc:  # noqa: BLE001
		print(f"ok   guard de producción aborta: {type(exc).__name__}")

	home = Path.home()
	ok_home = str(home.resolve()).startswith(VOLUME)
	print(f"{'ok  ' if ok_home else 'MAL '} {'HOME':26s} {home}")
	if not ok_home:
		failures.append(f"HOME -> {home}")

	repo = Path("/src/red-pill")
	ok_ro = repo.is_dir() and not os.access(repo / ".git", os.W_OK)
	print(f"{'ok  ' if ok_ro else 'MAL '} {'repo :ro (no escribible)':26s} {repo}")
	if not ok_ro:
		failures.append("el repo montado permite escritura en .git")

	# Lectura: las rutas del Operador NO deben existir dentro del sandbox.
	host_probes = [
		"/home/joan/.local/share/opencode/opencode.db",
		"/home/joan/.config/red-pill/.env",
		"/home/joan/.local/share/red-pill/state/mcp.sock",
	]
	for probe in host_probes:
		visible = os.path.exists(probe)
		print(f"{'MAL ' if visible else 'ok  '} {'lectura host: ' + probe:26s} {'visible' if visible else 'no existe'}")
		if visible:
			failures.append(f"ruta del Operador visible dentro: {probe}")

	# Escritura: fuera del volumen no se puede escribir en ningún sitio del host.
	for dest in ("/home/joan/.probe_dokime", "/etc/probe_dokime", "/srv/probe_dokime"):
		try:
			Path(dest).write_text("x", encoding="utf-8")
			print(f"MAL  escritura fuera del volumen: {dest}")
			failures.append(f"se pudo escribir fuera del volumen: {dest}")
		except OSError:
			print(f"ok   escritura bloqueada: {dest}")

	# Escritura dentro: sí funciona (el volumen es escribible y es el único sitio).
	marker = Path(VOLUME) / "PROOF_WRITE.txt"
	try:
		marker.write_text("ok", encoding="utf-8")
		print(f"ok   escritura dentro del volumen: {marker}")
	except OSError as exc:
		print(f"MAL  no se puede escribir en el volumen: {exc}")
		failures.append("el volumen no es escribible")

	# Embeddings: pesos del host montados `:ro` (sin egress no hay descarga posible).
	# Sólo pesos: si el mount dejara escribir, sería una vía de escape al host.
	models = Path("/models")
	ok_models = models.is_dir() and any(models.glob("models--*"))
	print(f"{'ok  ' if ok_models else 'MAL '} {'embeddings :ro':26s} {models}")
	if not ok_models:
		failures.append("sin cache de embeddings en /models (el seed no podrá vectorizar)")
	else:
		try:
			(models / "probe_dokime").write_text("x", encoding="utf-8")
			print("MAL  /models es escribible desde el sandbox")
			failures.append("/models es escribible (debía montarse :ro)")
		except OSError:
			print("ok   /models no escribible (sólo lectura)")

	qhost = os.getenv("QDRANT_HOST", "")
	print(f"{'ok  ' if qhost == 'qdrant' else 'MAL '} {'QDRANT_HOST':26s} {qhost}")
	if qhost != "qdrant":
		failures.append(f"QDRANT_HOST -> {qhost!r} (debe ser el Qdrant del sandbox)")

	print(json.dumps({"failures": failures}, ensure_ascii=False))
	return 1 if failures else 0


if __name__ == "__main__":
	sys.exit(main())
