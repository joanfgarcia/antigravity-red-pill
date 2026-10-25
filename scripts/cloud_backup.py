#!/usr/bin/env python3
"""Backup completo del Bünker y subida al Cloud (AD-018 / job nocturno).

`create`:
  Qdrant snapshots (todas las colecciones) + manifest + Memento on-disk +
  SQLite (bunker_queue, minion_inbox, neon-link) + `.env` → tar → MLS.
  Escribe `state/cloud_backup/last_kit.json` (path, sha256, tamaño).

`upload`:
  Lee `last_kit.json`, verifica el sha, autentica `CloudSyncPlugin` con el
  token vivo y sube el kit. Conserva los `CLOUD_BACKUP_KEEP` (default 3) kits
  más recientes del prefijo `CLOUD_BACKUP_`; no toca los `LEAN_SOUL_KIT_`.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

from red_pill.core.paths import (
	get_config_dir,
	get_data_dir,
	get_neon_link_config_dir,
	get_neon_link_db_path,
	get_queue_dir,
	get_state_dir,
)
from red_pill.plugins.cloud_sync.plugin import CloudSyncPlugin
from red_pill.soul import SoulManager
from red_pill.utils.vault import SoulCryptographer

KIT_PREFIX = "CLOUD_BACKUP_"
STATE_SUBDIR = "cloud_backup"


def _sha256(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as fh:
		for chunk in iter(lambda: fh.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def _checkpoint(db: Path) -> None:
	try:
		conn = sqlite3.connect(str(db))
		conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
		conn.close()
	except Exception as exc:  # noqa: BLE001
		print(f"[cloud-backup] WARN checkpoint {db}: {exc}", flush=True)


def _state_dir() -> Path:
	path = get_state_dir() / STATE_SUBDIR
	path.mkdir(parents=True, exist_ok=True)
	return path


def create() -> Dict[str, Any]:
	"""Genera el kit completo local y deja `last_kit.json` para la etapa upload."""
	timestamp = time.strftime("%Y%m%d_%H%M%S")
	soul = SoulManager()
	soul.backup_qdrant(timestamp)
	soul.create_manifest(timestamp)

	qdrant_dir = Path(soul.backup_root) / "qdrant"
	snapshots = [
		path
		for path in qdrant_dir.glob("*")
		if timestamp in path.name and (path.name.endswith(".snapshot") or path.name.endswith(".json"))
	]
	if not any(path.name.endswith(".snapshot") for path in snapshots):
		raise RuntimeError(f"Qdrant no generó snapshots para {timestamp}")

	export_dir = Path(soul.ia_dir) / "backups" / "export"
	export_dir.mkdir(parents=True, exist_ok=True)
	staging = export_dir / f"staging_cloud_{timestamp}"
	if staging.exists():
		shutil.rmtree(staging)
	(staging / "qdrant").mkdir(parents=True)
	(staging / "db").mkdir()
	(staging / "config").mkdir()

	for path in snapshots:
		shutil.copy2(path, staging / "qdrant" / path.name)

	for db in (get_queue_dir() / "bunker_queue.db", get_queue_dir() / "minion_inbox.db", get_neon_link_db_path()):
		if db.exists():
			_checkpoint(db)
			shutil.copy2(db, staging / "db" / db.name)

	for src, name in (
		(get_config_dir() / ".env", "red_pill.env"),
		(get_neon_link_config_dir() / ".env", "neon_link.env"),
	):
		if src.exists():
			shutil.copy2(src, staging / "config" / name)

	tar_path = export_dir / f"{KIT_PREFIX}{timestamp}.tar.gz"
	memento = Path(get_data_dir()) / "memento"
	with tarfile.open(tar_path, "w:gz") as tar:
		for root, _dirs, files in os.walk(staging):
			for name in files:
				path = Path(root) / name
				tar.add(path, arcname=str(path.relative_to(staging)))
		if memento.is_dir():
			tar.add(memento, arcname="memento")
	shutil.rmtree(staging, ignore_errors=True)

	encrypted = SoulCryptographer().encrypt_kit(str(tar_path))
	if not encrypted:
		raise RuntimeError(f"MLS encryption failed; tar conservado en {tar_path}")
	encrypted_path = Path(encrypted)
	if tar_path.exists():
		os.remove(tar_path)

	meta = {
		"kit_path": str(encrypted_path),
		"timestamp": timestamp,
		"size_bytes": encrypted_path.stat().st_size,
		"sha256": _sha256(encrypted_path),
		"created_at": time.time(),
		"contents": ["qdrant", "memento", "db", "config"],
	}
	(_state_dir() / "last_kit.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
	print(json.dumps({"created": meta}, ensure_ascii=False), flush=True)
	return meta


def upload(*, keep: Optional[int] = None) -> Dict[str, Any]:
	"""Sube el `last_kit.json` a Drive y aplica la retención del prefijo nuevo."""
	state = _state_dir()
	last = state / "last_kit.json"
	if not last.exists():
		raise RuntimeError("no existe last_kit.json: ejecuta `create` primero")
	meta = json.loads(last.read_text(encoding="utf-8"))
	kit = Path(str(meta.get("kit_path") or ""))
	if not kit.is_file():
		raise RuntimeError(f"kit no encontrado: {kit}")
	if _sha256(kit) != meta.get("sha256"):
		raise RuntimeError(f"sha256 del kit no coincide: {kit}")

	plugin = CloudSyncPlugin()
	asyncio.run(plugin.init())
	if not plugin.enabled or not plugin.service:
		raise RuntimeError("CloudSync sin credenciales/servicio (revisa token/client_secrets)")

	file_id = plugin.upload_kit(str(kit))
	if not file_id:
		raise RuntimeError(f"upload_kit falló para {kit.name}")

	keep_value = int(keep if keep is not None else os.getenv("CLOUD_BACKUP_KEEP", "3"))
	pruned = plugin.prune_cloud_kits(prefix=KIT_PREFIX, keep=keep_value)
	result = {
		"kit_path": str(kit),
		"file_id": file_id,
		"uploaded_at": time.time(),
		"size_bytes": int(meta.get("size_bytes") or kit.stat().st_size),
		"sha256": meta.get("sha256"),
		"keep": keep_value,
		"pruned": pruned,
	}
	(state / "last_upload.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
	print(json.dumps({"uploaded": result}, ensure_ascii=False), flush=True)
	return result


def main(argv: Optional[list[str]] = None) -> int:
	parser = argparse.ArgumentParser(description="Backup completo del Bünker + upload Cloud")
	sub = parser.add_subparsers(dest="cmd", required=True)
	sub.add_parser("create", help="Genera el kit completo (Qdrant + Memento + SQLite + .env)")
	up = sub.add_parser("upload", help="Sube el último kit y aplica retención")
	up.add_argument("--keep", type=int, default=None, help="Kits CLOUD_BACKUP_ a conservar (default 3)")
	args = parser.parse_args(argv)
	if args.cmd == "create":
		create()
	elif args.cmd == "upload":
		upload(keep=args.keep)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
