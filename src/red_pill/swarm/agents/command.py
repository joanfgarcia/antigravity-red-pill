import asyncio
import os
import shlex
import time
from typing import Any, Dict, List, Union

from red_pill.swarm.base import Minion


class CommandMinion(Minion):
	"""
	Minion that executes shell commands.
	Useful for Ruff, Pytest, and other CLI tools.
	"""

	name: str = "Command-Runner"
	specialization: str = "CLI Tool Execution"

	async def execute(self, task: str, **kwargs: Any) -> Dict[str, Any]:
		"""
		Run a command and capture output.
		'command' should be provided in kwargs.
		"""
		cmd: Union[str, List[str]] = kwargs.get("command", task)
		cwd = kwargs.get("cwd", os.getcwd())
		env = kwargs.get("env", os.environ.copy())
		timeout = kwargs.get("timeout")

		# Run via exec (argv) rather than a shell: removes shell-injection surface if a
		# command ever originates from a payload. Accept a pre-split list, or split a string
		# with shlex (covers all built-in commands: `ruff check .`, `pytest`, `git log …`).
		argv = cmd if isinstance(cmd, list) else shlex.split(cmd)

		self.log(f"Ejecutando comando: {cmd} en {cwd}")
		start_time = time.time()

		try:
			process = await asyncio.create_subprocess_exec(*argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd, env=env)

			if timeout:
				try:
					stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=float(timeout))
				except asyncio.TimeoutError:
					# Sin esto el timeout era decorativo: un comando colgado
					# bloqueaba al runner indefinidamente (run-lock R6 incluido).
					# rc 124 = convención de timeout (coherente con ScriptJobDriver).
					process.kill()
					try:
						await asyncio.wait_for(process.communicate(), timeout=5)
					except (asyncio.TimeoutError, ProcessLookupError):
						pass
					duration = time.time() - start_time
					self.log(f"Comando abatido por timeout ({timeout}s): {cmd}")
					return {
						"status": "failed",
						"returncode": 124,
						"stdout": "",
						"stderr": f"command timed out after {timeout}s",
						"timed_out": True,
						"duration": round(duration, 3),
					}
			else:
				stdout, stderr = await process.communicate()
			duration = time.time() - start_time

			return {
				"status": "success" if process.returncode == 0 else "failed",
				"returncode": process.returncode,
				"stdout": stdout.decode().strip(),
				"stderr": stderr.decode().strip(),
				"duration": round(duration, 3),
			}
		except Exception as e:
			return {"status": "error", "error": str(e), "duration": round(time.time() - start_time, 3)}
