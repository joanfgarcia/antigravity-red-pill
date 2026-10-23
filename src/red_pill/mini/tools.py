"""Bounded workspace tools for Forge (the GPU executor).

No arbitrary shell, no network, no paths outside the workspace. `run_tests` is
the only command and it runs the project's test suite with a timeout and an
output cap. Tool outputs are data for the model, never instructions.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


class ToolError(RuntimeError):
	"""Invalid tool call or unsafe path."""


TOOL_SCHEMAS: List[dict] = [
	{
		"type": "function",
		"function": {
			"name": "list_files",
			"description": "List files under the workspace (max 200).",
			"parameters": {"type": "object", "properties": {}, "additionalProperties": False},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "read_file",
			"description": "Read a text file inside the workspace (max 8 KB returned).",
			"parameters": {
				"type": "object",
				"properties": {"path": {"type": "string", "description": "Workspace-relative path."}},
				"required": ["path"],
				"additionalProperties": False,
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "write_file",
			"description": "Overwrite a text file inside the workspace.",
			"parameters": {
				"type": "object",
				"properties": {
					"path": {"type": "string"},
					"content": {"type": "string"},
				},
				"required": ["path", "content"],
				"additionalProperties": False,
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "edit_file",
			"description": "Replace one exact occurrence of old_string with new_string in a file.",
			"parameters": {
				"type": "object",
				"properties": {
					"path": {"type": "string"},
					"old_string": {"type": "string"},
					"new_string": {"type": "string"},
				},
				"required": ["path", "old_string", "new_string"],
				"additionalProperties": False,
			},
		},
	},
	{
		"type": "function",
		"function": {
			"name": "run_tests",
			"description": "Run the workspace test suite (python -m pytest -q).",
			"parameters": {"type": "object", "properties": {}, "additionalProperties": False},
		},
	},
]


class WorkspaceTools:
	"""Execute the five bounded tools against a workspace jail."""

	def __init__(
		self,
		workspace: str,
		*,
		max_read: int = 8192,
		max_write: int = 65536,
		max_output: int = 8192,
		timeout: int = 60,
		tests_cmd: Optional[List[str]] = None,
	):
		self.root = Path(workspace).resolve()
		if not self.root.is_dir():
			raise ToolError(f"workspace does not exist: {workspace}")
		self.max_read = int(max_read)
		self.max_write = int(max_write)
		self.max_output = int(max_output)
		self.timeout = int(timeout)
		self.tests_cmd = list(tests_cmd or [sys.executable, "-m", "pytest", "-q"])

	def _resolve(self, path: str) -> Path:
		raw = Path(str(path or ""))
		candidate = raw if raw.is_absolute() else self.root / raw
		resolved = candidate.resolve()
		if resolved != self.root and self.root not in resolved.parents:
			raise ToolError(f"path escapes workspace: {path}")
		return resolved

	def _cap(self, text: str, cap: int) -> str:
		if len(text) <= cap:
			return text
		return text[:cap] + f"\n… [truncated {len(text) - cap} chars]"

	def list_files(self) -> Dict[str, Any]:
		files = []
		for item in sorted(self.root.rglob("*")):
			if not item.is_file() or ".git" in item.parts or "__pycache__" in item.parts:
				continue
			files.append(str(item.relative_to(self.root)))
			if len(files) >= 200:
				break
		return {"ok": True, "files": files}

	def read_file(self, path: str) -> Dict[str, Any]:
		target = self._resolve(path)
		if not target.is_file():
			raise ToolError(f"not a file: {path}")
		text = target.read_text(encoding="utf-8", errors="replace")
		return {"ok": True, "path": str(target.relative_to(self.root)), "content": self._cap(text, self.max_read), "chars": len(text)}

	def write_file(self, path: str, content: str) -> Dict[str, Any]:
		target = self._resolve(path)
		text = str(content)
		if len(text) > self.max_write:
			raise ToolError(f"content too large ({len(text)} > {self.max_write})")
		target.parent.mkdir(parents=True, exist_ok=True)
		target.write_text(text, encoding="utf-8")
		return {"ok": True, "path": str(target.relative_to(self.root)), "chars": len(text)}

	def edit_file(self, path: str, old_string: str, new_string: str) -> Dict[str, Any]:
		target = self._resolve(path)
		if not target.is_file():
			raise ToolError(f"not a file: {path}")
		text = target.read_text(encoding="utf-8")
		if not old_string:
			raise ToolError("old_string is empty")
		count = text.count(old_string)
		if count != 1:
			raise ToolError(f"old_string must appear exactly once (found {count})")
		updated = text.replace(old_string, new_string, 1)
		if len(updated) > self.max_write:
			raise ToolError(f"result too large ({len(updated)} > {self.max_write})")
		target.write_text(updated, encoding="utf-8")
		return {"ok": True, "path": str(target.relative_to(self.root)), "replacements": 1}

	def run_tests(self) -> Dict[str, Any]:
		try:
			proc = subprocess.run(
				self.tests_cmd,
				cwd=str(self.root),
				capture_output=True,
				text=True,
				timeout=self.timeout,
			)
		except subprocess.TimeoutExpired:
			return {"ok": False, "exit_code": -1, "output": f"tests timed out after {self.timeout}s"}
		output = (proc.stdout or "") + (proc.stderr or "")
		return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "output": self._cap(output.strip(), self.max_output)}

	def execute(self, name: str, arguments: Any) -> str:
		"""Dispatch a tool call; always returns a JSON string for `role=tool`."""
		args = arguments if isinstance(arguments, dict) else {}
		try:
			if name == "list_files":
				result = self.list_files()
			elif name == "read_file":
				result = self.read_file(str(args.get("path", "")))
			elif name == "write_file":
				result = self.write_file(str(args.get("path", "")), str(args.get("content", "")))
			elif name == "edit_file":
				result = self.edit_file(str(args.get("path", "")), str(args.get("old_string", "")), str(args.get("new_string", "")))
			elif name == "run_tests":
				result = self.run_tests()
			else:
				raise ToolError(f"unknown tool: {name}")
		except Exception as e:
			result = {"ok": False, "error": str(e)}
		return json.dumps(result, ensure_ascii=False)
