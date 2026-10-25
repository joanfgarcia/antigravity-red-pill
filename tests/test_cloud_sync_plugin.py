"""CloudSync: upload_kit público y retención del prefijo nuevo."""
from __future__ import annotations

from red_pill.plugins.cloud_sync.plugin import CloudSyncPlugin


class FakeFiles:
	def __init__(self, files):
		self._files = files
		self.deleted = []
		self._created = False
		self._listed = False

	def list(self, **kwargs):
		self._listed = True
		self._list_kwargs = kwargs
		return self

	def create(self, **kwargs):
		self._created = True
		self._create_kwargs = kwargs
		return self

	def delete(self, fileId, **kwargs):
		self.deleted.append(fileId)
		self._created = False
		self._listed = False
		return self

	def execute(self):
		if self._created:
			return {"id": "new-file"}
		if self._listed:
			return {"files": self._files}
		return {}


class FakeService:
	def __init__(self, files):
		self._files = files

	def files(self):
		return self._files


def _plugin(files):
	plugin = object.__new__(CloudSyncPlugin)
	plugin.enabled = True
	plugin.service = FakeService(files)
	plugin.folder_id = "folder-1"
	plugin.quota_mb = 100
	plugin.reserve_count = 3
	plugin.name = "cloud_sync"
	plugin._emit_pain = lambda *args, **kwargs: None
	return plugin


def test_upload_kit_devuelve_file_id(tmp_path):
	kit = tmp_path / "CLOUD_BACKUP_20261026.tar.gz.mls"
	kit.write_bytes(b"x" * 1024)
	files = FakeFiles([])
	plugin = _plugin(files)
	assert plugin.upload_kit(str(kit)) == "new-file"
	assert files._create_kwargs["body"]["name"] == kit.name
	assert files._create_kwargs["body"]["parents"] == ["folder-1"]


def test_prune_solo_toca_el_prefijo_y_conserva_keep(tmp_path):
	kits = [{"id": f"id{i}", "name": f"CLOUD_BACKUP_{i}", "modifiedTime": str(i)} for i in range(5)]
	files = FakeFiles(kits)
	plugin = _plugin(files)
	assert plugin.prune_cloud_kits(prefix="CLOUD_BACKUP_", keep=3) == 2
	assert files.deleted == ["id3", "id4"]
	assert "CLOUD_BACKUP_" in files._list_kwargs["q"]


def test_upload_kit_inexistente_no_revienta(tmp_path):
	files = FakeFiles([])
	plugin = _plugin(files)
	assert plugin.upload_kit(str(tmp_path / "missing.mls")) is None
