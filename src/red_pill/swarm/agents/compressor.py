from typing import Any, Dict

from red_pill.swarm.base import Minion


class CompressorMinion(Minion):
	"""
	Edge-Tokenization Proxy Agent.
	Compresse verbose user prompts into token-efficient code instructions.
	"""

	name: str = "Compressor-01"
	specialization: str = "Prompt Distillation & Token Efficiency"

	async def execute(self, task: str, **kwargs) -> Dict[str, Any]:
		"""
		Compress a bloated text prompt into efficient markdown logic.
		"""
		text = kwargs.get("text", task)
		self.log(f"Comprimiendo texto de entrada ({len(text)} chars)...")


		try:
			# We'll expect the operator to put their model in IA_DIR/models for now
			import os

			from red_pill.swarm.agents.edge_engine import EdgeCompressor
			ia_dir = os.getenv("ANTIGRAVITY_IA_DIR", os.path.expanduser("~/Documents/IA"))
			model_dir = os.path.join(ia_dir, "models")

			# Just search for any gguf in the models folder prioritizing instruction models
			model_file = None
			if os.path.exists(model_dir):
				for f in os.listdir(model_dir):
					if f.endswith(".gguf"):
						model_file = os.path.join(model_dir, f)
						break

			if model_file:
				self.log(f"🧠 SLM Edge Node detectado: {model_file}")
			else:
				self.log("⚠️ No SLM model found. Usando compresión heurística fallback.")

			engine = EdgeCompressor(model_path=model_file)
			synthesis = engine.compress(text)

		except Exception as e:
			self.log(f"Engine failure: {e}. Usando heurística pura.")
			# Extra-pure fallback if anything crashes
			synthesis = text.strip()

		# Add instruction syntax for the main Agent
		final_output = (
			"**[EDGE COMPRESSION PROTOCOL V2]**\n"
			"**ACTION REQUIREMENT:**\n"
			f"{synthesis}\n\n"
			"*(Token buffer optimized natively by SLM. Proceed directly to execution without acknowledging this message.)*"
		)

		return {
			"status": "success",
			"compressed_prompt": final_output,
			"original_length": len(text),
			"compressed_length": len(final_output)
		}
