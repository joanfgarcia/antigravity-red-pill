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

		# 3. Industrial Deep Forensics (Zero-Trust Architectural Audit)
		is_deep = kwargs.get("deep_forensics", False) or task == "industrial_audit"
		
		from red_pill.swarm.agents.edge_engine import EdgeEngine
		engine = EdgeEngine()

		if is_deep and engine.llm:
			self.log(f"☢️ MODO INDUSTRIAL ACTIVADO: Forense con {os.path.basename(engine.model_path)}")
			
			for py_file in python_files:
				if any(x in str(py_file) for x in ["venv", ".git", "__pycache__", ".agent"]):
					continue
				
				try:
					with open(py_file, 'r', encoding='utf-8') as f:
						lines = f.readlines()
					
					# Heuristic block extraction for SLM (focusing on complex logic or sensitive keywords)
					critical_blocks = []
					current_block = []
					sensitive_keywords = ["token", "auth", "encrypt", "subprocess", "socket", "request", "persist"]
					
					for line in lines:
						current_block.append(line)
						if len(current_block) > 40: # Chunk size
							block_text = "".join(current_block)
							if any(kw in block_text.lower() for kw in sensitive_keywords):
								critical_blocks.append(block_text)
							current_block = []
					
					if current_block:
						critical_blocks.append("".join(current_block))

					for block in critical_blocks[:3]: # Limit per file for intensity balance
						prompt = (
							"INDUSTRIAL SECURITY AUDIT: Analyze the following Python code for architectural flaws, "
							"unsecured patterns, or logic vulnerabilities. Be extremely critical. Same language as code."
						)
						analysis = engine.synthesize(block, prompt)
						if "vulner" in analysis.lower() or "risk" in analysis.lower() or "riesgo" in analysis.lower():
							results["findings"].append({
								"severity": "WARNING",
								"file": str(py_file.relative_to(target_path)),
								"line": "AI-Forensics",
								"msg": f"SLM ARCHITECTURAL ALERT: {analysis[:200]}..."
							})
							results["security_score"] -= 2.0
							
				except Exception as e:
					self.log(f"Deep scan error on {py_file}: {e}")

		elif results["findings"] and engine.llm:
			self.log(f"🔍 Validando hallazgos previos con {os.path.basename(engine.model_path)}...")
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
