import ast
import asyncio
import pathlib
import re
import time
from typing import Any, Dict

from red_pill.swarm.base import Minion
from red_pill.telemetry import HardwareSentinel


class SmithMinion(Minion):
	"""
	Hardware-Accelerated Security Auditor.
	Migrated to Red Pill Kernel (v5.0-Pioneer).
	"""

	name: str = "Smith-01"
	specialization: str = "Deep Code Forensics & Security"

	async def execute(self, task: str, **kwargs) -> Dict[str, Any]:
		"""
		Perform a high-intensity audit on the current workspace.
		Integrates real-time hardware telemetry.
		"""
		start_time = time.time()
		results = {
			"status": "pass",
			"findings": [],
			"security_score": 100.0,
			"files_scanned": 0,
			"lines_analyzed": 0,
			"telemetry": HardwareSentinel.get_stats()
		}

		# Target: Current project root or specified path
		target_path = pathlib.Path(kwargs.get("path", pathlib.Path.cwd()))
		self.log(f"Iniciando auditoría profunda en: {target_path}")

		python_files = list(target_path.rglob("*.py"))

		# Precision Secret Discovery
		SECRETS_REGEX = re.compile(
			r'(?i)(password|passwd|api_key|token|secret|authorization|bearer)'
			r'[\s]*[:=][\s]*'
			r'(?!cfg\.|os\.environ|os\.getenv|settings\.|config\.)'
			r'[\'"][^\s\'"]{4,}[\'"]'
		)

		for py_file in python_files:
			# Skip noisy directories
			if any(x in str(py_file) for x in ["venv", ".git", "__pycache__", ".agent"]):
				continue

			try:
				with open(py_file, 'r', encoding='utf-8') as f:
					code = f.read()

				results["files_scanned"] += 1

				# 1. Structural Analysis (AST)
				tree = ast.parse(code)
				for node in ast.walk(tree):
					results["lines_analyzed"] += 1

					# Security: Sinkhole Analysis
					if isinstance(node, ast.Call):
						if isinstance(node.func, ast.Name) and node.func.id in ["eval", "exec"]:
							results["findings"].append({
								"severity": "CRITICAL",
								"file": str(py_file.relative_to(target_path)),
								"line": node.lineno,
								"msg": f"CWE-95 Detection: Use of '{node.func.id}' detected."
							})
							results["security_score"] -= 10.0

				# 2. Secret Extraction
				secrets = SECRETS_REGEX.findall(code)
				if secrets:
					results["findings"].append({
						"severity": "CRITICAL",
						"file": str(py_file.relative_to(target_path)),
						"line": "Global",
						"msg": f"POSSIBLE LEAK: {len(secrets)} hardcoded patterns found."
					})
					results["security_score"] -= 15.0

				# Async Yield
				await asyncio.sleep(0.001)

			except Exception as e:
				self.log(f"Error analizando {py_file}: {e}", level=30)

		# Thermal check from real hardware
		current_temp = 0
		if results["telemetry"]["gpu"]:
			current_temp = max([g.get("temp", 0) for g in results["telemetry"]["gpu"]])

		results["duration"] = round(time.time() - start_time, 2)
		results["peak_temp"] = current_temp

		self.log(f"Auditoría completada en {results['duration']}s. Score: {results['security_score']}")
		return results
