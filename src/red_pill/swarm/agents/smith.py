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

	async def execute(self, task: str, **kwargs: Any) -> Dict[str, Any]:
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

		# 3. Super-Deep Granular Forensics (Line-by-Line Resolution)
		is_super_deep = kwargs.get("super_deep", False) or task == "super_deep_audit"
		is_deep = kwargs.get("deep_forensics", False) or task == "industrial_audit" or is_super_deep
		
		from red_pill.swarm.agents.edge_engine import EdgeEngine
		engine = EdgeEngine()

		if is_deep and engine.llm:
			mode_label = "SOLO GRANULAR (QUIRÚRGICO)" if is_super_deep else "INDUSTRIAL (BLOQUES)"
			self.log(f"☢️ MODO {mode_label} ACTIVADO: Auditoría con {os.path.basename(engine.model_path) if engine.model_path else 'No model path'}")
			
			for py_file in python_files:
				if any(x in str(py_file) for x in ["venv", ".git", "__pycache__", ".agent"]):
					continue
				
				try:
					with open(py_file, 'r', encoding='utf-8') as f:
						file_content = f.read()
						lines = file_content.splitlines()
					
					# Granular Scan: Small overlapping windows for 'line-by-line' sensation
					chunk_size = 15 if is_super_deep else 40
					step_size = 5 if is_super_deep else 40
					
					for i in range(0, len(lines), step_size):
						window = lines[i : i + chunk_size]
						block_text = "\n".join([f"{i+j+1}: {line}" for j, line in enumerate(window)])
						
						# Quick heuristic check to avoid flooding the GPU with empty lines
						if not any(kw in block_text.lower() for kw in ["def ", "class ", "token", "auth", "secret", "path", "os.", "sys.", "eval", "exec", "subprocess"]):
							if is_super_deep: # In super deep we scan more but still skip obvious noise
								if len(block_text.strip()) < 50: continue
							else:
								continue

						prompt = (
							f"SURGICAL SECURITY AUDIT (RESOLUTION: {'LINE' if is_super_deep else 'BLOCK'}):\n"
							"Inspect these lines for vulnerabilities, leaks, or architectural anti-patterns. "
							"If you find something, specify the line number. Be extremely direct. "
							"If clean, reply with 'CLEAN'."
						)
						
						analysis = engine.synthesize(block_text, prompt)
						
						if "CLEAN" not in analysis.upper():
							results["findings"].append({
								"severity": "CRITICAL" if is_super_deep else "WARNING",
								"file": str(py_file.relative_to(target_path)),
								"line": f"{i+1}-{i+chunk_size}",
								"msg": f"FORENSIC ALERT: {analysis[:300]}..."
							})
							results["security_score"] -= 5.0 if is_super_deep else 2.0
							
				except Exception as e:
					self.log(f"Deep scan error on {py_file}: {e}")


		elif results["findings"] and engine.llm:
			self.log(f"🔍 Validando hallazgos previos con {os.path.basename(engine.model_path) if engine.model_path else 'No model path'}...")
			for finding in results["findings"][:5]: # Limit to top 5 for speed
				snippet = finding.get("context", finding["msg"])
				prompt = f"Security Analysis Request: Code snippet '{snippet}' was flagged as '{finding['msg']}'. Is this a genuine security risk (True Positive) or a safe usage (False Positive)? Explain briefly."
				analysis = engine.synthesize(snippet, prompt)
				finding["slm_validation"] = analysis

		# Thermal check from real hardware
		current_temp = 0.0
		telemetry = results["telemetry"]
		if isinstance(telemetry, dict) and telemetry.get("gpu"):
			current_temp = float(max([g.get("temp", 0) for g in telemetry["gpu"]]))

		results["duration"] = round(time.time() - start_time, 2)
		results["peak_temp"] = current_temp

		self.log(f"Auditoría completada en {results['duration']}s. Score: {results['security_score']}")
		return results
