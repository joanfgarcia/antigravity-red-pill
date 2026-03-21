import asyncio
import os
import subprocess
import time
from typing import Any, Dict

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
        cmd = kwargs.get("command", task)
        cwd = kwargs.get("cwd", os.getcwd())
        env = kwargs.get("env", os.environ.copy())

        self.log(f"Ejecutando comando: {cmd} en {cwd}")
        start_time = time.time()

        try:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env
            )

            stdout, stderr = await process.communicate()
            duration = time.time() - start_time

            return {
                "status": "success" if process.returncode == 0 else "failed",
                "returncode": process.returncode,
                "stdout": stdout.decode().strip(),
                "stderr": stderr.decode().strip(),
                "duration": round(duration, 3)
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "duration": round(time.time() - start_time, 3)
            }
