import re
import asyncio
from typing import Dict, Any
from red_pill.swarm.base import Minion

class CompressorMinion(Minion):
	"""
	Edge-Tokenization Proxy Agent.
	Compresse verbose user prompts into token-efficient code instructions.
	"""
	
	name: str = "Compressor-01"
	specialization: str = "Prompt Distillation & Token Efficiency"

	async def execute(self, text: str, **kwargs) -> Dict[str, Any]:
		"""
		Compress a bloated text prompt into efficient markdown logic.
		Future enhancement: Intersect with a local Llama.cpp binary to perform true SLM extraction.
		"""
		self.log(f"Comprimiendo texto de entrada ({len(text)} chars)...")
		
		# Basic heuristic distillation (Simulating Edge-Tokenization)
		# 1. Strip formal greetings/closures
		clean_text = re.sub(r'^(hola|buenos\s+d[íi]as|oye|por\s+favor)[,\s]*', '', text, flags=re.IGNORECASE)
		clean_text = re.sub(r'[,\s]*(gracias|un\s+saludo|adi[óo]s)$', '', clean_text, flags=re.IGNORECASE)
		
		# 2. Extract key intents (Verbs + Nouns)
		# For demonstration, we break into bullet points and highlight keywords
		sentences = [s.strip() for s in re.split(r'[.!?\n]+', clean_text) if len(s.strip()) > 5]
		
		compressed_lines = []
		for s in sentences:
			# Remove fluff words
			fluff = [
				"necesito que", "me gustaría saber si", "podrías", "te importaría", 
				"estoy intentando", "creo que", "básicamente lo que pasa es que",
				"es decir", "bueno", "la verdad es que"
			]
			for f in fluff:
				s = re.sub(fr'\b{f}\b', '', s, flags=re.IGNORECASE)
			
			s = s.strip()
			if s:
				compressed_lines.append(f"- {s.capitalize()}")
		
		synthesis = "\n".join(compressed_lines)
		if not synthesis:
			synthesis = text.strip()
			
		# Add instruction syntax for the main Agent
		final_output = (
			"**[EDGE COMPRESSION PROTOCOL V1]**\n"
			"**ACTION REQUIREMENT:**\n"
			f"{synthesis}\n\n"
			"*(Token buffer optimized natively. Proceed directly to execution without acknowledging this message.)*"
		)
		
		return {
			"status": "success",
			"compressed_prompt": final_output,
			"original_length": len(text),
			"compressed_length": len(final_output)
		}
