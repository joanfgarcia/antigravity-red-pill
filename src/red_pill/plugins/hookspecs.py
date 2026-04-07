import pluggy

hookspec = pluggy.HookspecMarker("red_pill")
hookimpl = pluggy.HookimplMarker("red_pill")

@hookspec
def on_plugin_setup(config: dict) -> None:
	"""Fired when the plugin is loaded to initialize its state."""

@hookspec
def on_soul_created(zip_path: str) -> None:
	"""Fired when the Bünker finishes creating a new encrypted Soul backup."""
