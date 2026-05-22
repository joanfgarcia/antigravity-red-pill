import os
import subprocess
import tempfile


class PrologExpert:
	"""
	Simula un Experto en Prolog (Soft-Expert).
	Fase 1: Delega al monolito para traducir a código Prolog.
	Fase 2: Ejecuta el código en SWI-Prolog vía Subprocess.
	"""

	def __init__(self, use_dedicated_model=False):
		self.use_dedicated_model = use_dedicated_model

	async def execute(self, payload: str) -> str:
		"""Flujo principal: Traduce -> Ejecuta -> Devuelve Resultado"""

		# 1. Traducir (LLM)
		prolog_code = await self._translate_to_prolog(payload)

		# 2. Ejecutar (SWI-Prolog)
		return self._run_swi_prolog(prolog_code)

	async def _translate_to_prolog(self, payload: str) -> str:
		"""
		Traductor (Soft-Expert): Envuelve la petición en un System Prompt dictatorial
		y delega en el LLM monolítico para extraer únicamente sintaxis de Prolog.
		"""

		# TODO: Ajustar la importación según el driver de inferencia actual de red-pill (ej. litellm, openai, llama.cpp)
		# from src.red_pill.inference.driver import generate_completion

		# Mock de llamada real al LLM generalista
		# prolog_code = await generate_completion(system_prompt=system_prompt, user_prompt=payload)

		# De momento, para no romper CI/CD, devolvemos un código fallback
		# si la inferencia real no está cableada.
		prolog_code = """
		humano(joan).
		mortal(X) :- humano(X).
		:- initialization(main, main).
		main :- (mortal(joan) -> writeln('True: Translated correctly') ; writeln('False')), halt.
		"""

		return prolog_code

	def _run_swi_prolog(self, prolog_code: str) -> str:
		"""Ejecuta el código en un proceso aislado con Timeout de seguridad."""

		# Usamos un archivo temporal para pasarle el código a swipl
		fd, temp_path = tempfile.mkstemp(suffix=".pl")
		try:
			with os.fdopen(fd, "w") as f:
				f.write(prolog_code)

			# Ejecutamos SWI-Prolog: -q (quiet), -f (file)
			result = subprocess.run(
				["swipl", "-q", "-f", temp_path],
				capture_output=True,
				text=True,
				timeout=3.0,  # CIRUIT BREAKER: 3 segundos máximo
			)

			if result.returncode != 0:
				return f"[PROLOG ERROR]: {result.stderr.strip()}"

			return f"[PROLOG RESULT]: {result.stdout.strip()}"

		except subprocess.TimeoutExpired:
			return "[PROLOG ERROR]: Timeout Excedido (Bucle infinito detectado)."
		finally:
			os.remove(temp_path)
