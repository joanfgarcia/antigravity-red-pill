#!/usr/bin/env python3
"""model_approve.py — records the PROVENANCE of an approved model (process).

Does not move or rewrite layout (that broke on the symlinks; see docs/TECHNICAL/DECISION_LOG.md).
Its single job: after **testing** a model, leave a record in a **manifest** of what it
is, where it came from and with which hashes — with the **pinned revision**.

Manifest: `~/.local/share/red-pill/model_manifest.json` (or `$REDPILL_MODEL_MANIFEST`).

Modes:
	# HF repo (pins the commit + sha256/lfs.oid of each file, from HF metadata)
	model_approve.py --repo Tongyi-MAI/Z-Image-Turbo [--revision main] [--note "tested"]

	# Custom model / multi-repo composition (hashes the local files)
	model_approve.py --name qwen-image-2.1 --file a.gguf --file b.gguf [:role=path ...]

	model_approve.py --list            # show what is registered
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
	"""Resolve the manifest path: explicit arg → $REDPILL_MODEL_MANIFEST → default."""
	if explicit:
		return Path(explicit).expanduser()
	env = os.environ.get("REDPILL_MODEL_MANIFEST")
	if env:
		return Path(env).expanduser()
	# Default path via the shared helper (no XDG/home literals — §7).
	import sys

	sys.path.insert(0, str(Path(__file__).resolve().parent))
	from _config_common import _data_dir

	return Path(_data_dir()) / "model_manifest.json"


def load_manifest(path: Path) -> dict:
	"""Load the manifest, returning an empty skeleton if it is absent or corrupt."""
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
	"""Write the manifest atomically (temp file + replace)."""
	path.parent.mkdir(parents=True, exist_ok=True)
	tmp = path.with_suffix(path.suffix + ".tmp")
	tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
	tmp.replace(path)  # atomic write


def record_model(data: dict, model_id: str, entry: dict) -> dict:
	"""Insert/update the entry for `model_id` in the manifest (returns data)."""
	data.setdefault("models", {})[model_id] = entry
	return data


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
	h = hashlib.sha256()
	with open(path, "rb") as f:
		for block in iter(lambda: f.read(chunk), b""):
			h.update(block)
	return h.hexdigest()


def local_components(specs: list) -> dict:
	"""`specs` = ["role=path", "path", …] → {role|basename: sha256}."""
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
	"""(commit_sha, {filename: oid/sha256}, license_id) from HF metadata. Requires network."""
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
	"""Parse args, build the provenance entry and persist it in the manifest."""
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
		entry = {
			"source": "hf",
			"repo": args.repo,
			"revision": commit,
			"license": license_id,
			"components": components,
			"approved_at": now,
			"note": args.note,
		}
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
