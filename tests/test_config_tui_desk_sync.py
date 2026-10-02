"""config_tui: cambiar el desk actualiza también el registro (fuente del Janitor y las anclas)."""

from pathlib import Path

from red_pill.config_tui import sync_registry_desk
from red_pill.core import workspaces as ws


def test_desk_change_reaches_the_registry(tmp_path, monkeypatch):
	reg = tmp_path / "workspaces.yaml"
	monkeypatch.setattr(ws, "registry_path", lambda: reg)
	ws.save_registry(ws.WorkspaceRegistry(agent_core=tmp_path / "old-desk", workspaces=[]))

	sync_registry_desk(str(tmp_path / "new-desk"))

	assert ws.load_registry().agent_core == tmp_path / "new-desk"


def test_without_registry_nothing_is_created(tmp_path, monkeypatch):
	reg = tmp_path / "workspaces.yaml"
	monkeypatch.setattr(ws, "registry_path", lambda: reg)
	sync_registry_desk(str(tmp_path / "desk"))
	assert not reg.exists()
	assert not Path(tmp_path / "desk").exists()
