"""
Tests for the workspace registry (red_pill.core.workspaces) after the move to
pydantic-validated models. Covers validation, ~-expansion, immutability via
model_copy, serialize round-trip, and skip-malformed loading.
"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from red_pill.core import workspaces as ws
from red_pill.core.workspaces import Workspace, WorkspaceRegistry, serialize_registry


class TestWorkspaceModel:
	def test_paths_are_expanded(self):
		w = Workspace(name="demo", root="~/projects/demo")
		assert w.root == Path.home() / "projects" / "demo"

	def test_atlas_empty_becomes_none(self):
		assert Workspace(name="demo", root="/tmp/x", atlas="").atlas is None
		assert Workspace(name="demo", root="/tmp/x", atlas=None).atlas is None

	def test_atlas_expanded_when_set(self):
		w = Workspace(name="demo", root="/tmp/x", atlas="~/std")
		assert w.atlas == Path.home() / "std"

	def test_flags_coerced(self):
		w = Workspace(name="demo", root="/tmp/x", graphify=True, access=True)
		assert w.graphify is True and w.access is True

	def test_memory_defaults_and_resolution(self):
		w = Workspace(name="demo", root="/tmp/x")
		assert w.memory is False
		assert w.get_memory_path is None

		w_bool = Workspace(name="demo", root="/tmp/x", memory=True)
		assert w_bool.memory is True
		assert w_bool.get_memory_path == Path("/tmp/x/.red-pill/memory")

		w_custom = Workspace(name="demo", root="/tmp/x", memory="custom_mem")
		assert w_custom.get_memory_path == Path("/tmp/x/custom_mem").resolve()

	def test_name_must_be_nonempty(self):
		with pytest.raises(ValidationError):
			Workspace(name="  ", root="/tmp/x")

	def test_missing_root_rejected(self):
		with pytest.raises(ValidationError):
			Workspace(name="demo")

	def test_is_immutable(self):
		w = Workspace(name="demo", root="/tmp/x")
		with pytest.raises(ValidationError):
			w.access = True


class TestWorkspaceRegistry:
	def test_defaults(self):
		reg = WorkspaceRegistry(agent_core="~/Agent_Core")
		assert reg.version == 1
		assert reg.workspaces == []
		assert reg.agent_core == Path.home() / "Agent_Core"

	def test_get_by_name(self):
		reg = WorkspaceRegistry(agent_core="~/Agent_Core", workspaces=[Workspace(name="a", root="/tmp/a")])
		assert reg.get("a").root == Path("/tmp/a")
		assert reg.get("missing") is None

	def test_model_copy_flips_access_without_mutating_original(self):
		w = Workspace(name="a", root="/tmp/a", access=False)
		w2 = w.model_copy(update={"access": True})
		assert w.access is False and w2.access is True


class TestSerializeRoundTrip:
	def test_roundtrip(self):
		reg = WorkspaceRegistry(
			agent_core="~/Agent_Core",
			workspaces=[
				Workspace(name="proj", root="~/code/proj", graphify=True, access=True, memory=True),
				Workspace(name="proj2", root="~/code/proj2", memory="~/custom_mem"),
			],
		)
		text = serialize_registry(reg)
		raw = yaml.safe_load(text)
		assert raw["version"] == 1
		assert raw["workspaces"][0]["name"] == "proj"
		# re-validate the emitted entry back into a model
		w1 = Workspace.model_validate(raw["workspaces"][0])
		assert w1.graphify is True and w1.access is True and w1.memory is True

		w2 = Workspace.model_validate(raw["workspaces"][1])
		assert w2.memory == Path.home() / "custom_mem"

	def test_empty_workspaces_serialize(self):
		reg = WorkspaceRegistry(agent_core="~/Agent_Core")
		assert "workspaces: []" in serialize_registry(reg)


class TestLoadRegistry:
	def test_skips_malformed_entries(self, tmp_path, monkeypatch):
		reg_file = tmp_path / "workspaces.yaml"
		reg_file.write_text(
			"version: 1\n"
			"agent_core: ~/Agent_Core\n"
			"workspaces:\n"
			"  - { name: good, root: ~/code/good, atlas: null, graphify: false, access: true }\n"
			"  - { root: ~/code/nameless }\n",  # malformed: missing name
			encoding="utf-8",
		)
		monkeypatch.setattr(ws, "registry_path", lambda: reg_file)
		reg = ws.load_registry()
		assert [w.name for w in reg.workspaces] == ["good"]
		assert reg.get("good").access is True

	def test_absent_registry_is_back_compat(self, tmp_path, monkeypatch):
		monkeypatch.setattr(ws, "registry_path", lambda: tmp_path / "nope.yaml")
		reg = ws.load_registry()
		assert reg.workspaces == []
		assert isinstance(reg.agent_core, Path)


class TestRegistryCRUD:
	"""Exercises the install/update-critical path: `manage_workspaces enable` →
	add_or_enable_workspace → save_registry → serialize → reload."""

	@pytest.fixture
	def reg_file(self, tmp_path, monkeypatch):
		f = tmp_path / "workspaces.yaml"
		f.write_text("version: 1\nagent_core: ~/Agent_Core\nworkspaces: []\n", encoding="utf-8")
		monkeypatch.setattr(ws, "registry_path", lambda: f)
		return f

	def test_add_new_workspace_persists(self, reg_file, tmp_path):
		proj = tmp_path / "proj"
		proj.mkdir()
		_registry, w, was_new = ws.add_or_enable_workspace(str(proj))
		assert was_new is True and w.access is True and w.name == "proj"
		# round-trips through serialize + reload
		assert ws.find_workspace("proj").access is True

	def test_add_existing_flips_access_not_new(self, reg_file, tmp_path):
		proj = tmp_path / "proj"
		proj.mkdir()
		ws.add_or_enable_workspace(str(proj))
		ws.set_access("proj", False)
		assert ws.find_workspace("proj").access is False
		_registry, w, was_new = ws.add_or_enable_workspace(str(proj))
		assert was_new is False and w.access is True

	def test_set_access_not_found(self, reg_file):
		assert ws.set_access("ghost", True) is None

	def test_remove_workspace(self, reg_file, tmp_path):
		proj = tmp_path / "proj"
		proj.mkdir()
		ws.add_or_enable_workspace(str(proj))
		assert ws.remove_workspace("proj") is not None
		assert ws.find_workspace("proj") is None

	def test_remove_not_found(self, reg_file):
		assert ws.remove_workspace("ghost") is None

	def test_find_by_resolved_path(self, reg_file, tmp_path):
		proj = tmp_path / "proj"
		proj.mkdir()
		ws.add_or_enable_workspace(str(proj), name="myproj")
		assert ws.find_workspace(str(proj)).name == "myproj"


class TestStandardsResolution:
	def test_resolve_uses_atlas_when_set(self, tmp_path):
		w = Workspace(name="a", root=str(tmp_path), atlas=str(tmp_path / "std"))
		assert ws.resolve_standards(w) == tmp_path / "std"

	def test_find_closest_agent_walks_up(self, tmp_path):
		(tmp_path / ".agent").mkdir()
		sub = tmp_path / "a" / "b"
		sub.mkdir(parents=True)
		assert ws.find_closest_agent(sub) == (tmp_path / ".agent").resolve()


class TestPathOwnershipInference:
	"""`owning_workspace` / `infer_workspaces` — RFC-DESPERTAR-001 P1b: el
	proyecto se infiere por las rutas tocadas, no por el cwd."""

	def _registry(self, monkeypatch, tmp_path):
		ws_list = [
			Workspace(name="a", root=str(tmp_path / "a")),
			Workspace(name="ab", root=str(tmp_path / "a" / "b")),
			Workspace(name="z", root=str(tmp_path / "z")),
		]
		monkeypatch.setattr(ws, "list_workspaces", lambda: ws_list)
		return tmp_path

	def test_most_specific_wins(self, tmp_path, monkeypatch):
		base = self._registry(monkeypatch, tmp_path)
		(base / "a" / "b" / "c").mkdir(parents=True)
		assert ws.owning_workspace(base / "a" / "b" / "c") == "ab"
		assert ws.owning_workspace(base / "a" / "c") == "a"

	def test_linked_worktree_resolves_to_main_repo(self, tmp_path, monkeypatch):
		"""Un `git worktree` fuera de toda raíz se atribuye a su repo principal."""
		base = self._registry(monkeypatch, tmp_path)
		main = base / "z"
		(main / ".git" / "worktrees" / "feat").mkdir(parents=True)
		wt = tmp_path / "worktrees" / "z" / "feat"
		(wt / "src").mkdir(parents=True)
		(wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'feat'}\n", encoding="utf-8")
		(wt / "src" / "m.py").write_text("x", encoding="utf-8")
		assert ws.owning_workspace(wt / "src" / "m.py") == "z"
		assert ws.infer_workspaces([str(wt / "src" / "m.py")]) == ["z"]

	def test_plain_repo_is_not_a_worktree(self, tmp_path, monkeypatch):
		self._registry(monkeypatch, tmp_path)
		other = tmp_path / "other"
		(other / ".git").mkdir(parents=True)
		assert ws.owning_workspace(other) is None

	def test_infer_loads_registry_once(self, tmp_path, monkeypatch):
		base = self._registry(monkeypatch, tmp_path)
		calls = {"n": 0}
		real = ws.list_workspaces

		def _counting():
			calls["n"] += 1
			return real()

		monkeypatch.setattr(ws, "list_workspaces", _counting)
		ws.infer_workspaces([str(base / "a" / f"f{i}.py") for i in range(200)])
		assert calls["n"] == 1

	def test_file_resolves_against_parent(self, tmp_path, monkeypatch):
		base = self._registry(monkeypatch, tmp_path)
		(base / "a" / "b").mkdir(parents=True)
		(base / "a" / "b" / "f.txt").write_text("x", encoding="utf-8")
		assert ws.owning_workspace(base / "a" / "b" / "f.txt") == "ab"

	def test_outside_registry_is_none(self, tmp_path, monkeypatch):
		self._registry(monkeypatch, tmp_path)
		assert ws.owning_workspace(tmp_path / "other") is None

	def test_none_input_is_none(self, tmp_path, monkeypatch):
		self._registry(monkeypatch, tmp_path)
		assert ws.owning_workspace(None) is None

	def test_infer_workspaces_order_and_dedup(self, tmp_path, monkeypatch):
		base = self._registry(monkeypatch, tmp_path)
		(base / "a" / "b").mkdir(parents=True)
		(base / "z").mkdir(parents=True)
		paths = [
			base / "a" / "b" / "f",
			base / "z" / "g",
			base / "a" / "b" / "h",
			None,
			base / "outside",
		]
		assert ws.infer_workspaces(paths) == ["ab", "z"]

	def test_infer_workspaces_empty(self, tmp_path, monkeypatch):
		self._registry(monkeypatch, tmp_path)
		assert ws.infer_workspaces([]) == []
