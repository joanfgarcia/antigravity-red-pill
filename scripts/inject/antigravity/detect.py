"""Detect Antigravity (Gemini Code Assist) installation."""
import os


def detect(workspace: str | None = None) -> bool:
	return os.path.isdir(os.path.expanduser("~/.gemini"))
