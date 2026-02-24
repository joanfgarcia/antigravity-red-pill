import ast
import os
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
								"msg": f"CWE-95 Detection: Use of '{node.func.id}' detected.",
								"context": code.splitlines()[node.lineno-1] if node.lineno <= len(code.splitlines()) else ""
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

		# 3. Deep SLM Forensics (if findings exist and model available)
		if results["findings"]:
			from red_pill.swarm.agents.edge_engine import EdgeEngine
			ia_dir = os.getenv("ANTIGRAVITY_IA_DIR", os.path.expanduser("~/Documents/IA"))
			model_dir = os.path.join(ia_dir, "models")
			model_file = next((os.path.join(model_dir, f) for f in os.listdir(model_dir) if f.endswith(".gguf")), None) if os.path.exists(model_dir) else None

			if model_file:
				self.log("🔍 Desplegando forense SLM para validar hallazgos...")
				engine = EdgeEngine(model_path=model_file)
				for finding in results["findings"][:5]: # Limit to top 5 for speed
					snippet = finding.get("context", finding["msg"])
					prompt = f"Security Analysis Request: Code snippet '{snippet}' was flagged as '{finding['msg']}'. Is this a genuine security risk (True Positive) or a safe usage (False Positive)? Explain briefly."
					analysis = engine.synthesize(snippet, prompt)
					finding["slm_validation"] = analysis


		# Thermal check from real hardware
		current_temp = 0
		if results["telemetry"]["gpu"]:
			current_temp = max([g.get("temp", 0) for g in results["telemetry"]["gpu"]])

		results["duration"] = round(time.time() - start_time, 2)
		results["peak_temp"] = current_temp

		self.log(f"Auditoría completada en {results['duration']}s. Score: {results['security_score']}")
		return results
