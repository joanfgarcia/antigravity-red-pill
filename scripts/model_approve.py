#!/usr/bin/env python3
"""model_approve.py — registra la PROCEDENCIA de un modelo aprobado (proceso).

No mueve ni reescribe layout (eso rompía por los symlinks; ver RFC-HARNESS-007).
Su única misión: tras **probar** un modelo, dejar constancia en un **manifiesto**
de qué es, de dónde vino y con qué hashes — con la **revisión pinada**.

Manifiesto: `~/.local/share/red-pill/model_manifest.json` (o `$REDPILL_MODEL_MANIFEST`).

Modos:
  # Repo HF (fija el commit + sha256/lfs.oid de cada fichero, desde la metadata de HF)
  model_approve.py --repo Tongyi-MAI/Z-Image-Turbo [--revision main] [--note "probado"]

  # Modelo custom / composición multi-repo (hashea los ficheros locales)
  model_approve.py --name qwen-image-2.1 --file a.gguf --file b.gguf [:role=path ...]

  model_approve.py --list            # ver lo registrado
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_VERSION = 1


def manifest_path(explicit: str | None = None) -> Path:
	if explicit:
		return Path(explicit).expanduser()
	env = os.environ.get("REDPILL_MODEL_MANIFEST")
	if env:
		return Path(env).expanduser()
	data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
	return Path(data) / "red-pill" / "model_manifest.json"


def load_manifest(path: Path) -> dict:
	if not path.is_file():
		return {"version": MANIFEST_VERSION, "models": {}}
	try:
		data = json.loads(path.read_text(encoding="utf-8"))
	except Exception:
		return {"version": MANIFEST_VERSION, "models": {}}
	data.setdefault("version", MANIFEST_VERSION)
	data.setdefault("models", {})
	return data


def save_manifest(path: Path, data: dict) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(path.suffix + ".tmp")
	tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	tmp.replace(path)  # escritura atómica


def record_model(data: dict, model_id: str, entry: dict) -> dict:
	"""Inserta/actualiza la entrada de `model_id` en el manifiesto (devuelve data)."""
	data.setdefault("models", {})[model_id] = entry
	return data


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for block in iter(lambda: f.read(chunk), b""):
			h.update(block)
	return h.hexdigest()


def local_components(specs: list) -> dict:
	"""`specs` = ["rol=ruta", "ruta", …] → {rol|basename: sha256}."""
	out = {}
	for spec in specs:
		role, _, raw = spec.partition("=")
		if not raw:
			role, raw = "", spec
		p = Path(raw).expanduser()
		if not p.is_file():
			raise SystemExit(f"[error] fichero no encontrado: {p}")
		out[role or p.name] = _sha256(p)
	return out


def hf_components(repo: str, revision: str | None) -> tuple:
	"""(commit_sha, {fichero: sha256}) desde la metadata de HF. Requiere red."""
	try:
		from huggingface_hub import HfApi
	except Exception:
		raise SystemExit("[error] falta `huggingface_hub` (corre con el python del forge).")
	info = HfApi().model_info(repo, revision=revision, files_metadata=True)
	files = {}
	for s in info.siblings or []:
		oid = getattr(getattr(s, "lfs", None), "oid", None) or getattr(s, "blob_id", None)
		if oid:
			files[s.rfilename] = oid
	license_id = ""
	card = getattr(info, "cardData", None) or {}
	if isinstance(card, dict):
		license_id = str(card.get("license") or "")
	return info.sha, files, license_id


def main() -> int:
	ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	ap.add_argument("--repo", help="repo HF (org/name)")
	ap.add_argument("--revision", help="revisión a PINAR (def: la actual → se fija el commit resultante)")
	ap.add_argument("--name", help="id para modelo custom/composición")
	ap.add_argument("--file", action="append", dest="files", default=[], help="fichero local (rol=ruta, repetible)")
	ap.add_argument("--note", default="", help="nota (p.ej. 'probado en 1024x1024')")
	ap.add_argument("--manifest", help="ruta del manifiesto")
	ap.add_argument("--list", action="store_true", help="mostrar lo registrado")
	args = ap.parse_args()

	path = manifest_path(args.manifest)
	data = load_manifest(path)

	if args.list:
		if not data["models"]:
			print("(manifiesto vacío)")
			return 0
		for mid, e in sorted(data["models"].items()):
			rev = e.get("revision") or "-"
			print(f"{mid}  rev={rev[:12]}  rev_files={len(e.get('components') or {})}  {e.get('note', '')}")
		return 0

	now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
	if args.repo:
		commit, components, license_id = hf_components(args.repo, args.revision)
		mid = args.repo
		entry = {"source": "hf", "repo": args.repo, "revision": commit, "license": license_id, "components": components, "approved_at": now, "note": args.note}
	elif args.name:
		if not args.files:
			raise SystemExit("[error] modo --name requiere al menos un --file")
		mid = args.name
		entry = {"source": "custom", "name": args.name, "components": local_components(args.files), "approved_at": now, "note": args.note}
	else:
		raise SystemExit("[error] indica --repo (HF) o --name + --file (custom)")

	record_model(data, mid, entry)
	save_manifest(path, data)
	print(f"[ok] registrado '{mid}' en {path} ({len(entry['components'])} componentes)")
	return 0


if __name__ == "__main__":
	sys.exit(main())
