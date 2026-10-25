"""Backup completo del Bünker (`scripts/cloud_backup.py`) con Qdrant/Drive mockeados."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "cloud_backup.py"


def _load():
	spec = importlib.util.spec_from_file_location("cloud_backup_under_test", SCRIPT)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


class FakeSoul:
	def __init__(self, ws: Path):
		self.ia_dir = str(ws)
		self.backup_root = str(ws / "backups")
		(Path(self.backup_root) / "qdrant").mkdir(parents=True, exist_ok=True)

	def backup_qdrant(self, ts):
		(Path(self.backup_root) / "qdrant" / f"work_memories_{ts}.snapshot").write_bytes(b"snap")
		(Path(self.backup_root) / "qdrant" / f"memento_{ts}.snapshot").write_bytes(b"snap2")

	def create_manifest(self, ts):
		(Path(self.backup_root) / "qdrant" / f"manifest_{ts}.json").write_text("{}", encoding="utf-8")


class FakeCrypto:
	def encrypt_kit(self, tar_path):
		out = Path(tar_path).with_suffix(".mls")
		out.write_bytes(Path(tar_path).read_bytes())
		return str(out)


class FakePlugin:
	enabled = True
	service = object()

	async def init(self):
		return None

	def upload_kit(self, path):
		return "drive-file-1"

	def prune_cloud_kits(self, **kwargs):
		return 2


def _paths(tmp_path):
	ws = tmp_path / "workspace"
	data = tmp_path / "data"
	queue = data / "queue"
	config = tmp_path / "config"
	neon_config = tmp_path / "neon-config"
	neon_db = data / "neon" / "events.db"
	state = data / "state"
	memento = data / "memento"
	for p in (ws, queue, config, neon_config, neon_db.parent, state, memento):
		p.mkdir(parents=True, exist_ok=True)
	(queue / "bunker_queue.db").write_text("", encoding="utf-8")
	(queue / "minion_inbox.db").write_text("", encoding="utf-8")
	sqlite3.connect(queue / "bunker_queue.db").execute("create table if not exists x (a int)").connection.commit()
	sqlite3.connect(queue / "minion_inbox.db").execute("create table if not exists x (a int)").connection.commit()
	neon_db.write_text("", encoding="utf-8")
	(config / ".env").write_text("SECRET=1\n", encoding="utf-8")
	(neon_config / ".env").write_text("NEON=1\n", encoding="utf-8")
	(memento / "2026-08").mkdir()
	(memento / "2026-08" / "entry.md").write_text("# memento\n", encoding="utf-8")
	return SimpleNamespace(ws=ws, data=data, queue=queue, config=config, neon_config=neon_config, neon_db=neon_db, state=state, memento=memento)


def _patch(monkeypatch, mod, p):
	monkeypatch.setattr(mod, "get_data_dir", lambda: p.data)
	monkeypatch.setattr(mod, "get_queue_dir", lambda: p.queue)
	monkeypatch.setattr(mod, "get_config_dir", lambda: p.config)
	monkeypatch.setattr(mod, "get_neon_link_config_dir", lambda: p.neon_config)
	monkeypatch.setattr(mod, "get_neon_link_db_path", lambda: p.neon_db)
	monkeypatch.setattr(mod, "get_state_dir", lambda: p.state)
	monkeypatch.setattr(mod, "SoulManager", lambda: FakeSoul(p.ws))
	monkeypatch.setattr(mod, "SoulCryptographer", FakeCrypto)


def test_create_incluye_qdrant_memento_db_y_env(tmp_path, monkeypatch):
	mod = _load()
	p = _paths(tmp_path)
	_patch(monkeypatch, mod, p)
	meta = mod.create()
	kit = Path(meta["kit_path"])
	assert kit.is_file() and kit.suffix == ".mls"
	assert meta["sha256"] == hashlib.sha256(kit.read_bytes()).hexdigest()
	assert meta["contents"] == ["qdrant", "memento", "db", "config"]
	last = json.loads((p.state / "cloud_backup" / "last_kit.json").read_text())
	assert last["kit_path"] == str(kit)
	with tarfile.open(kit) as tar:
		names = tar.getnames()
	for expected in ("qdrant/manifest_", "qdrant/work_memories_", "qdrant/memento_", "memento/2026-08/entry.md", "db/bunker_queue.db", "db/minion_inbox.db", "config/red_pill.env"):
		assert any(name.startswith(expected) or name == expected for name in names), (expected, names)


def test_upload_verifica_sha_y_aplica_retencion(tmp_path, monkeypatch):
	mod = _load()
	p = _paths(tmp_path)
	_patch(monkeypatch, mod, p)
	mod.create()
	monkeypatch.setattr(mod, "CloudSyncPlugin", FakePlugin)
	result = mod.upload(keep=3)
	assert result["file_id"] == "drive-file-1"
	assert result["keep"] == 3
	assert result["pruned"] == 2
	last = json.loads((p.state / "cloud_backup" / "last_upload.json").read_text())
	assert last["file_id"] == "drive-file-1"


def test_upload_rechaza_kit_manipulado(tmp_path, monkeypatch):
	mod = _load()
	p = _paths(tmp_path)
	_patch(monkeypatch, mod, p)
	meta = mod.create()
	Path(meta["kit_path"]).write_bytes(b"tampered")
	monkeypatch.setattr(mod, "CloudSyncPlugin", FakePlugin)
	with pytest.raises(RuntimeError, match="sha256"):
		mod.upload()
