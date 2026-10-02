import os


def test_isolation_gatekeeper():
	"""Verify that MemoryManager defaults to :memory: in test environment."""
	from red_pill import config as cfg
	from red_pill.memory import MemoryManager

	# Both module-level alias and singleton instance must match
	assert cfg.QDRANT_URL == ":memory:"
	assert cfg.get_config().QDRANT_URL == ":memory:"

	mm = MemoryManager()
	# Ensure the memory manager initializes pointing to :memory:
	assert mm.storage.cfg.QDRANT_URL == ":memory:"


def test_config_isolation(bunker_isolation):
	"""Verify that IA_DIR is properly redirected via Pydantic singleton rebuild."""
	from red_pill import config as cfg

	# Validate singleton alignment with environment
	singleton_dir = cfg.get_config().APP_ROOT
	module_dir = cfg.APP_ROOT

	assert "bunker_test_" in singleton_dir, f"Pydantic singleton leaked: {singleton_dir}"
	assert "bunker_test_" in module_dir, f"Module alias leaked: {module_dir}"
	assert singleton_dir == module_dir, "Singleton and module alias drift detected in APP_ROOT"

	# Validate isolation from host production paths
	prod_path = os.path.expanduser("~/Documents/IA/sharing")
	assert singleton_dir != prod_path


# ── Guardas de aislamiento ampliadas (config, state, desk, bunker root) ──────


def test_suite_never_resolves_operator_locations():
	"""conftest redirige TODAS las ubicaciones del operador antes de importar
	red_pill: config (.env real), state (logs), desk y bunker root."""
	from pathlib import Path

	from red_pill.core import paths

	home = Path.home()
	real = {
		"config": home / ".config" / "red-pill",
		"neon_config": home / ".config" / "neon-link",
		"state": home / ".local" / "state" / "red-pill",
	}
	assert not str(paths.get_config_dir()).startswith(str(real["config"]))
	assert not str(paths.get_neon_link_config_dir()).startswith(str(real["neon_config"]))
	assert not str(paths.get_log_dir()).startswith(str(real["state"]))
	assert not str(paths.get_agent_core_root()).startswith(str(home / "Documents"))
	assert not str(paths.get_bunker_root()).startswith(str(home / "Documents"))
	assert "NEON_LINK_DB_PATH" not in os.environ


def test_worker_does_not_load_operator_env():
	"""Importar el worker cargaba ~/.config/red-pill/.env (AGENT_CORE_DIR al desk
	real, NEON_LINK_DB_PATH al events.db real)."""
	from pathlib import Path

	import red_pill.core.agent_worker as aw

	assert not str(aw.DB_PATH).startswith(str(Path.home() / ".local" / "share" / "neon-link"))


# HOME de operador ficticio FUERA de tmp: los tests de la guarda no pueden depender
# del HOME real (bajo un HOME sandbox en /tmp el desk "del operador" parecía tmp).
_FAKE_OPERATOR_HOME = "/nonexistent-redpill-operator/home"


def test_guard_rejects_real_config_state_and_desk(monkeypatch, tmp_path):
	"""Sin la redirección, cada getter aborta en vez de tocar al operador."""
	from pathlib import Path

	import pytest

	from red_pill.core import paths

	monkeypatch.setenv("HOME", _FAKE_OPERATOR_HOME)
	home = Path.home()
	assert str(home) == _FAKE_OPERATOR_HOME
	for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME"):
		monkeypatch.delenv(name, raising=False)
	with pytest.raises(RuntimeError, match="TEST ISOLATION"):
		paths.get_config_dir()
	with pytest.raises(RuntimeError, match="TEST ISOLATION"):
		paths.get_neon_link_config_dir()
	with pytest.raises(RuntimeError, match="TEST ISOLATION"):
		paths.get_log_dir()

	monkeypatch.setenv("AGENT_CORE_DIR", str(home / "Documents" / "IA" / "SomeDesk"))
	with pytest.raises(RuntimeError, match="TEST ISOLATION"):
		paths.get_agent_core_root()

	monkeypatch.setenv("AGENT_CORE_DIR", str(tmp_path / "desk"))
	assert paths.get_agent_core_root() == tmp_path / "desk"


def test_legacy_migration_skips_operator_dirs_under_tests(monkeypatch, tmp_path):
	"""La migración legacy de import (~/.config/red_pill con vault.seed) no copia
	secretos del operador al tmp de los tests; con un HOME falso en tmp sí migra."""
	from pathlib import Path

	from red_pill.core import paths

	assert paths._legacy_source_allowed(Path(_FAKE_OPERATOR_HOME) / ".config" / "red_pill") is False
	fake_home = tmp_path / "home"
	(fake_home / ".config" / "red_pill").mkdir(parents=True)
	(fake_home / ".config" / "red_pill" / "vault.seed").write_text("seed")
	monkeypatch.setattr(Path, "home", lambda: fake_home)
	paths.migrate_legacy_xdg_config()
	assert (paths.get_config_dir() / "vault.seed").read_text() == "seed"
