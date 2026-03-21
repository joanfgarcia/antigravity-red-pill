"""
Tests for Phase 3 CLI EntryPoints plugin discovery.
Verifies that load_plugins() and _dispatch_plugins() work correctly
with mock EntryPoints — no actual package installation needed.
"""

import argparse
from unittest.mock import MagicMock, patch

from red_pill.cli import _PLUGIN_REGISTRY, _dispatch_plugins, load_plugins

# ---------------------------------------------------------------------------
# Helpers: mock EntryPoint & Plugin
# ---------------------------------------------------------------------------


def _make_ep(name: str, plugin_cls):
	"""Create a fake importlib.metadata.EntryPoint."""
	ep = MagicMock()
	ep.name = name
	ep.value = f"fake_{name}:FakePlugin"
	ep.load.return_value = plugin_cls
	return ep


class _NoOpPlugin:
	"""Plugin that registers a 'noop' command but never handles it."""

	def register(self, subparsers):
		subparsers.add_parser("noop", help="A no-op test command")

	def handle(self, args):
		return False  # Let dispatch chain continue


class _HandlerPlugin:
	"""Plugin that claims command 'enterprise_cmd'."""

	def register(self, subparsers):
		subparsers.add_parser("enterprise_cmd", help="Enterprise test command")

	def handle(self, args):
		return args.command == "enterprise_cmd"


class _BadPlugin:
	"""Plugin whose handle() raises an exception."""

	def register(self, subparsers):
		pass

	def handle(self, args):
		raise RuntimeError("Plugin exploded")


# ---------------------------------------------------------------------------
# load_plugins() tests
# ---------------------------------------------------------------------------


class TestLoadPlugins:
	def setup_method(self):
		_PLUGIN_REGISTRY.clear()

	def teardown_method(self):
		_PLUGIN_REGISTRY.clear()

	def test_load_plugins_registers_plugin(self):
		"""load_plugins() discovers EntryPoints and adds them to _PLUGIN_REGISTRY."""
		ep = _make_ep("noop_plugin", _NoOpPlugin)
		parser = argparse.ArgumentParser()
		subparsers = parser.add_subparsers(dest="command")

		with patch("importlib.metadata.entry_points", return_value=[ep]):
			load_plugins(subparsers)

		assert "noop_plugin" in _PLUGIN_REGISTRY

	def test_load_plugins_registers_subcommand(self):
		"""Plugin.register() is called, adding its subcommand to argparse."""
		ep = _make_ep("noop_plugin", _NoOpPlugin)
		parser = argparse.ArgumentParser()
		subparsers = parser.add_subparsers(dest="command")

		with patch("importlib.metadata.entry_points", return_value=[ep]):
			load_plugins(subparsers)

		args = parser.parse_args(["noop"])
		assert args.command == "noop"

	def test_load_plugins_survives_bad_plugin(self):
		"""A plugin that fails to load does not crash the whole CLI."""

		class _CrashyPlugin:
			def register(self, subparsers):
				raise RuntimeError("I am broken")

		ep = _make_ep("crashy", _CrashyPlugin)
		ep.load.side_effect = RuntimeError("Load failed")
		parser = argparse.ArgumentParser()
		subparsers = parser.add_subparsers(dest="command")

		with patch("importlib.metadata.entry_points", return_value=[ep]):
			load_plugins(subparsers)  # Must not raise

		assert "crashy" not in _PLUGIN_REGISTRY

	def test_load_plugins_no_eps_is_silent(self):
		"""If no EntryPoints are registered, load_plugins is a no-op."""
		parser = argparse.ArgumentParser()
		subparsers = parser.add_subparsers(dest="command")

		with patch("importlib.metadata.entry_points", return_value=[]):
			load_plugins(subparsers)

		assert _PLUGIN_REGISTRY == {}


# ---------------------------------------------------------------------------
# _dispatch_plugins() tests
# ---------------------------------------------------------------------------


class TestDispatchPlugins:
	def setup_method(self):
		_PLUGIN_REGISTRY.clear()

	def teardown_method(self):
		_PLUGIN_REGISTRY.clear()

	def test_dispatch_returns_false_when_no_plugins(self):
		"""With no plugins, _dispatch_plugins always returns False."""
		args = argparse.Namespace(command="enterprise_cmd")
		assert _dispatch_plugins(args) is False

	def test_dispatch_returns_true_when_plugin_handles(self):
		"""A plugin that returns True from handle() stops the chain."""
		_PLUGIN_REGISTRY["handler"] = _HandlerPlugin()
		args = argparse.Namespace(command="enterprise_cmd")
		assert _dispatch_plugins(args) is True

	def test_dispatch_returns_false_when_plugin_passes(self):
		"""A plugin that returns False from handle() lets the chain continue."""
		_PLUGIN_REGISTRY["noop"] = _NoOpPlugin()
		args = argparse.Namespace(command="unknown")
		assert _dispatch_plugins(args) is False

	def test_dispatch_isolates_plugin_exceptions(self):
		"""A plugin that raises does not prevent other plugins from running."""
		good_plugin = MagicMock()
		good_plugin.handle.return_value = True
		_PLUGIN_REGISTRY["bad"] = _BadPlugin()
		_PLUGIN_REGISTRY["good"] = good_plugin
		args = argparse.Namespace(command="enterprise_cmd")
		result = _dispatch_plugins(args)
		# good_plugin should still run; its return value should propagate
		good_plugin.handle.assert_called_once_with(args)
		assert result is True
