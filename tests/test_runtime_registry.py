"""TST-RT-001: RuntimeRegistry — afinidad de runtime por modelo (RFC-HARNESS-003).

Piloto corte 1: carga del registro, resolución por perfil, y disponibilidad con
FALLO LIMPIO (nunca fallback silencioso al runtime stock). Tests herméticos:
sin GPU y sin tocar la config real del operador (se monkeypatchean
get_runtimes_path/get_bunker_root).
"""

import os

import pytest

BASE_YAML = """
default_runtime: llama_cpp_stock
runtimes:
  llama_cpp_stock:
    kind: llama_cpp
    binary: "3rdparty/llama_official/build/bin/llama-cli"
    capabilities: {quant_types: ["k_quants"]}
  llama_cpp_prism:
    kind: llama_cpp_fork
    binary: "bin/prism/llama-cli"
    capabilities: {quant_types: ["PTQ1_0"], reasoning_kwargs: true}
"""


@pytest.fixture(autouse=True)
def _reset_registry():
	import red_pill.core.runtime_registry as rr

	rr.RuntimeRegistry._runtimes_cache = None
	rr.RuntimeRegistry._default_runtime = None
	rr.RuntimeRegistry._runtimes_mtime = 0.0
	yield


def _patch_paths(monkeypatch, tmp_path, registry_path):
	import red_pill.core.runtime_registry as rr

	monkeypatch.setattr(rr, "get_runtimes_path", lambda: registry_path)
	monkeypatch.setattr(rr, "get_bunker_root", lambda: tmp_path)


def _write_registry(tmp_path, content: str):
	path = tmp_path / "runtimes.yaml"
	path.write_text(content, encoding="utf-8")
	return path


class TestLoading:
	def test_missing_registry_returns_empty(self, monkeypatch, tmp_path):
		import red_pill.core.runtime_registry as rr

		_patch_paths(monkeypatch, tmp_path, tmp_path / "does_not_exist.yaml")
		# Sin seed en el bunker fake → registro vacío, sin crash.
		assert rr.RuntimeRegistry.all() == {}
		assert rr.RuntimeRegistry.default_id() == rr.DEFAULT_RUNTIME_ID

	def test_loads_runtimes_and_default(self, monkeypatch, tmp_path):
		import red_pill.core.runtime_registry as rr

		_patch_paths(monkeypatch, tmp_path, _write_registry(tmp_path, BASE_YAML))
		assert set(rr.RuntimeRegistry.all()) == {"llama_cpp_stock", "llama_cpp_prism"}
		assert rr.RuntimeRegistry.default_id() == "llama_cpp_stock"

	def test_relative_binary_resolved_against_bunker_root(self, monkeypatch, tmp_path):
		import red_pill.core.runtime_registry as rr

		_patch_paths(monkeypatch, tmp_path, _write_registry(tmp_path, BASE_YAML))
		rt = rr.RuntimeRegistry.get("llama_cpp_prism")
		assert rt["binary"] == str(tmp_path / "bin" / "prism" / "llama-cli")


class TestForProfile:
	def test_explicit_runtime_wins(self, monkeypatch, tmp_path):
		import red_pill.core.runtime_registry as rr

		_patch_paths(monkeypatch, tmp_path, _write_registry(tmp_path, BASE_YAML))
		rt = rr.RuntimeRegistry.for_profile({"runtime": "llama_cpp_prism"})
		assert rt["id"] == "llama_cpp_prism"
		assert "PTQ1_0" in rt["capabilities"]["quant_types"]

	def test_default_runtime_when_profile_absent(self, monkeypatch, tmp_path):
		import red_pill.core.runtime_registry as rr

		_patch_paths(monkeypatch, tmp_path, _write_registry(tmp_path, BASE_YAML))
		rt = rr.RuntimeRegistry.for_profile({})
		assert rt["id"] == "llama_cpp_stock"

	def test_unknown_runtime_returns_empty_not_fallback(self, monkeypatch, tmp_path):
		import red_pill.core.runtime_registry as rr

		_patch_paths(monkeypatch, tmp_path, _write_registry(tmp_path, BASE_YAML))
		assert rr.RuntimeRegistry.for_profile({"runtime": "nope"}) == {}


class TestAvailability:
	def test_missing_binary_reports_reason(self, monkeypatch, tmp_path):
		import red_pill.core.runtime_registry as rr

		_patch_paths(monkeypatch, tmp_path, _write_registry(tmp_path, BASE_YAML))
		ok, reason = rr.RuntimeRegistry.check_available("llama_cpp_prism")
		assert not ok
		assert "no existe" in reason

	def test_existing_executable_is_available(self, monkeypatch, tmp_path):
		import red_pill.core.runtime_registry as rr

		_patch_paths(monkeypatch, tmp_path, _write_registry(tmp_path, BASE_YAML))
		binary = tmp_path / "bin" / "prism" / "llama-cli"
		binary.parent.mkdir(parents=True, exist_ok=True)
		binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
		os.chmod(binary, 0o755)
		ok, reason = rr.RuntimeRegistry.check_available("llama_cpp_prism")
		assert ok, reason

	def test_require_raises_clean_error(self, monkeypatch, tmp_path):
		import red_pill.core.runtime_registry as rr

		_patch_paths(monkeypatch, tmp_path, _write_registry(tmp_path, BASE_YAML))
		with pytest.raises(rr.RuntimeUnavailableError, match="no existe"):
			rr.RuntimeRegistry.require("llama_cpp_prism")

	def test_require_returns_runtime_when_available(self, monkeypatch, tmp_path):
		import red_pill.core.runtime_registry as rr

		_patch_paths(monkeypatch, tmp_path, _write_registry(tmp_path, BASE_YAML))
		binary = tmp_path / "bin" / "prism" / "llama-cli"
		binary.parent.mkdir(parents=True, exist_ok=True)
		binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
		os.chmod(binary, 0o755)
		rt = rr.RuntimeRegistry.require("llama_cpp_prism")
		assert rt["id"] == "llama_cpp_prism"
