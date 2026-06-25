"""
Tests for migrate_memory's MCP-config re-pointing — the step that keeps the
serving config coordinated with the memory move (.claude/memory → .red-pill/memory)
so no manual --update is needed after upgrade.

scripts/ isn't a package; import the modules by path.
"""

import importlib.util
import json
import os
import sys

_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, _SCRIPTS)  # so migrate_memory can `from inject_mcp import discover_targets`


def _load(name):
	path = os.path.join(_SCRIPTS, f"{name}.py")
	spec = importlib.util.spec_from_file_location(name, path)
	mod = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(mod)
	return mod


mm = _load("migrate_memory")
import inject_mcp  # noqa: E402  (scripts dir on sys.path above)


class TestDeepStrReplace:
	def test_replaces_in_nested_structure_and_counts(self):
		obj = {
			"mcpServers": {
				"workspace-memory": {"args": ["-y", "srv", "/ws/.claude/memory"]},
				"bridge": {"env": {"MEM": "/ws/.claude/memory/MEMORY.md", "OTHER": "/ws/keep"}},
			}
		}
		new, n = mm._deep_str_replace(obj, "/ws/.claude/memory", "/ws/.red-pill/memory")
		assert n == 2
		assert new["mcpServers"]["workspace-memory"]["args"][2] == "/ws/.red-pill/memory"
		assert new["mcpServers"]["bridge"]["env"]["MEM"] == "/ws/.red-pill/memory/MEMORY.md"
		assert new["mcpServers"]["bridge"]["env"]["OTHER"] == "/ws/keep"

	def test_no_match_is_noop(self):
		obj = {"a": ["b", "c"]}
		new, n = mm._deep_str_replace(obj, "/x", "/y")
		assert n == 0 and new == obj


class TestRepointMcpConfigs:
	def test_repoints_only_matching_paths_and_backs_up(self, tmp_path, monkeypatch):
		cfg = tmp_path / "mcp_config.json"
		cfg.write_text(
			json.dumps(
				{
					"mcpServers": {
						"workspace-memory": {"args": ["-y", "srv", str(tmp_path / ".claude" / "memory")]},
						"unrelated": {"args": ["-y", "srv", "/some/other/path"]},
					}
				}
			),
			encoding="utf-8",
		)
		monkeypatch.setattr(inject_mcp, "discover_targets", lambda ws=None: [str(cfg)])

		old = str(tmp_path / ".claude" / "memory")
		new = str(tmp_path / ".red-pill" / "memory")
		n = mm._repoint_mcp_configs(tmp_path, old, new, dry_run=False)

		assert n == 1
		data = json.loads(cfg.read_text(encoding="utf-8"))
		assert data["mcpServers"]["workspace-memory"]["args"][2] == new
		assert data["mcpServers"]["unrelated"]["args"][2] == "/some/other/path"
		assert (tmp_path / "mcp_config.json.bak").exists()

	def test_dry_run_does_not_write(self, tmp_path, monkeypatch):
		cfg = tmp_path / "mcp_config.json"
		original = json.dumps({"mcpServers": {"m": {"args": [str(tmp_path / ".claude" / "memory")]}}})
		cfg.write_text(original, encoding="utf-8")
		monkeypatch.setattr(inject_mcp, "discover_targets", lambda ws=None: [str(cfg)])

		n = mm._repoint_mcp_configs(tmp_path, str(tmp_path / ".claude" / "memory"), str(tmp_path / ".red-pill" / "memory"), dry_run=True)
		assert n == 1
		assert cfg.read_text(encoding="utf-8") == original  # untouched
		assert not (tmp_path / "mcp_config.json.bak").exists()
