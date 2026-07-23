import os

try:
	for root, dirs, files in os.walk(os.path.dirname(os.path.abspath(__file__))):
		for file in files:
			if file.endswith(".pyc"):
				try:
					os.remove(os.path.join(root, file))
				except Exception:
					pass
except Exception:
	pass

"""Red Pill Protocol - Bünker Back Core System."""

__version__ = "7.9.2"
CORE_VERSION = __version__
__model__ = "Gemini 1.5 Flash"
