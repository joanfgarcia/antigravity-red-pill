import math
from abc import ABC, abstractmethod
from typing import Any, Dict


class MemoryEngine(ABC):
	"""Abstract base class for memory reinforcement and erosion engines."""

	@abstractmethod
	def calculate_lazy_decay(self, payload: Dict[str, Any], current_time: float) -> Dict[str, Any]:
		"""
		Calculates the decay of a memory given its payload and the current time.
		Returns a dictionary of the updated fields (e.g., reinforcement_score, utility_beta).
		If the memory is completely forgotten (score <= threshold), it should return {"_delete": True}.
		"""
		pass

	@abstractmethod
	def calculate_reinforcement(self, payload: Dict[str, Any], increment: float) -> Dict[str, Any]:
		"""
		Calculates the new state of a memory after it has been retrieved/reinforced.
		Returns a dictionary of the updated fields.
		"""
		pass


class FSRSEngine(MemoryEngine):
	"""
	Real FSRS Engine (Free Spaced Repetition Scheduler).
	Retrievability Formula: R = e^(ln(0.9) * t/S)
	where 't' is time in days and 'S' is stability in days.
	"""

	def __init__(self, deletion_threshold: float = 0.05):
		self.deletion_threshold = deletion_threshold
		# ln(0.9) is approximately -0.10536
		self.decay_constant = math.log(0.9)

	def _calculate_retrievability(self, stability_days: float, time_passed_days: float) -> float:
		if stability_days <= 0:
			return 0.0
		# R = e^(ln(0.9) * t/S)
		power = self.decay_constant * (time_passed_days / stability_days)
		# Clamp to avoid math domain errors
		power = max(min(power, 0), -20)
		return math.exp(power)

	def calculate_lazy_decay(self, payload: Dict[str, Any], current_time: float) -> Dict[str, Any]:
		last_recalled = float(payload.get("last_recalled_at", current_time))
		score = float(payload.get("reinforcement_score", 1.0))
		stability = float(payload.get("stability", 1.0))  # S in days

		time_passed_seconds = max(0.0, current_time - last_recalled)
		time_passed_days = time_passed_seconds / 86400.0

		retrievability = self._calculate_retrievability(stability, time_passed_days)
		new_score = round(score * retrievability, 3)

		if new_score <= self.deletion_threshold:
			return {"_delete": True, "score": new_score, "stability": stability}

		if new_score < score:
			return {"reinforcement_score": new_score}

		return {}

	def calculate_reinforcement(self, payload: Dict[str, Any], increment: float) -> Dict[str, Any]:
		# Advanced FSRS typically updates Stability based on Retrieval (R)
		# For now, we apply a simplistic stability increase based on the increment
		score = float(payload.get("reinforcement_score", 1.0))
		stability = float(payload.get("stability", 1.0))

		new_score = min(score + increment, 1.0)
		# Increase stability (S) slightly upon retrieval (this delays future decay)
		new_stability = stability * (1.0 + (increment * 2))

		return {"reinforcement_score": round(new_score, 3), "stability": round(new_stability, 3)}


class BayesianEngine(MemoryEngine):
	"""
	Beta Distribution Utility Engine for Technical Knowledge.
	E[θ] = α / (α + β)
	"""

	def __init__(self, deletion_threshold: float = 0.5):
		self.deletion_threshold = deletion_threshold

	def calculate_lazy_decay(self, payload: Dict[str, Any], current_time: float) -> Dict[str, Any]:
		alpha = float(payload.get("utility_alpha", 1.0))
		beta = float(payload.get("utility_beta", 1.0))
		last_recalled = float(payload.get("last_recalled_at", current_time))

		time_passed_seconds = max(0.0, current_time - last_recalled)
		time_passed_days = time_passed_seconds / 86400.0

		# Erosion: Uncertainty (Beta) grows logarithmically over time
		# β_new = β_old + ln(1 + t_days)
		new_beta = beta + math.log1p(time_passed_days)

		# Utility (Expected value): α / (α + β)
		utility = alpha / (alpha + new_beta)

		# Normalize utility (which converges to 0.0 as β -> ∞) to the reinforcement_score scale
		new_score = utility

		if new_score <= self.deletion_threshold:
			return {"_delete": True, "score": new_score, "alpha": alpha, "beta": new_beta}

		if new_beta != beta:
			return {"utility_beta": round(new_beta, 4), "reinforcement_score": round(new_score, 3)}

		return {}

	def calculate_reinforcement(self, payload: Dict[str, Any], increment: float) -> Dict[str, Any]:
		alpha = float(payload.get("utility_alpha", 1.0))
		beta = float(payload.get("utility_beta", 1.0))
		content = payload.get("content", "")

		# v6.3.8: Content Quality Gate (Anti-Noise Feedback Loop)
		# We only reinforce if the content is not classified as garbage/noise.
		if content:
			from red_pill.utils.telemetry_filter import calculate_entropy, is_garbage

			# Informational Density Gate: Repetitive logs/boilerplate should not be immortalized.
			entropy = calculate_entropy(content)
			if is_garbage(content) or entropy < 3.2:
				# Active Erosion: Technical noise increases uncertainty by 1.0 per recall
				# until it reaches BAYESIAN_MAX_BETA and gets purged during sleep.
				return {"utility_beta": round(beta + 1.0, 4)}

		# Retrieval strengthens confidence (reduces uncertainty and increases alpha)
		new_alpha = alpha + (increment * 5)
		# Pull beta back slightly towards 1.0 to clear uncertainty
		new_beta = max(1.0, beta - (increment * 2))

		utility = new_alpha / (new_alpha + new_beta)
		new_score = utility

		return {"utility_alpha": round(new_alpha, 4), "utility_beta": round(new_beta, 4), "reinforcement_score": round(new_score, 3)}


class RhizoDBEngine(MemoryEngine):
	"""
	RhizoDB Memory Dynamics Engine.
	Inspired by and adapted from Jorge Augusto Guberte's RhizoDB paper:
	"RhizoDB: A Bounded Activation-Flow Architecture for Graph-Based Memory Systems" (2026).
	DOI: 10.5281/zenodo.20695703
	License: CC BY 4.0

	Activation Formula: R = e^(-lambda * t/S)
	where 't' is time passed in days, 'S' is stability in days, and lambda is -ln(0.9).
	Activation Update (on reinforcement): a_v(t+1) = a_v(t) + (1 - a_v(t)) * alpha
	Stability Update (on reinforcement): s_v(t+1) = s_v(t) + eta * alpha * (S_max - s_v(t))
	"""

	def __init__(self, deletion_threshold: float = 0.05, S_max: float = 365.0, eta: float = 0.1):
		self.deletion_threshold = deletion_threshold
		self.S_max = S_max
		self.eta = eta
		# lambda = -ln(0.9) approx 0.10536
		self.lambda_constant = -math.log(0.9)

	def calculate_lazy_decay(self, payload: Dict[str, Any], current_time: float) -> Dict[str, Any]:
		last_recalled = float(payload.get("last_recalled_at", current_time))
		score = float(payload.get("reinforcement_score", 1.0))
		stability = float(payload.get("stability", 1.0))

		time_passed_seconds = max(0.0, current_time - last_recalled)
		time_passed_days = time_passed_seconds / 86400.0

		# a_v(t) = a_v(t_0) * e^(-lambda * dt / S)
		power = -self.lambda_constant * (time_passed_days / stability)
		power = max(min(power, 0), -20)
		decay_factor = math.exp(power)

		new_score = round(score * decay_factor, 3)

		if new_score <= self.deletion_threshold:
			return {"_delete": True, "score": new_score, "stability": stability}

		if new_score < score:
			return {"reinforcement_score": new_score}

		return {}

	def calculate_reinforcement(self, payload: Dict[str, Any], increment: float) -> Dict[str, Any]:
		score = float(payload.get("reinforcement_score", 1.0))
		stability = float(payload.get("stability", 1.0))

		# increment maps to alpha (external stimulation force)
		alpha = max(0.0, min(increment, 1.0))

		# 1. Asymptotic Saturated Activation Update
		new_score = score + (1.0 - score) * alpha

		# 2. Stability Update with maximum ceiling S_max
		new_stability = stability + self.eta * alpha * (self.S_max - stability)

		return {"reinforcement_score": round(new_score, 3), "stability": round(new_stability, 3)}


def get_memory_engine(engine_type: str) -> MemoryEngine:
	"""Factory to return the appropriate engine."""
	engine_type = engine_type.strip().lower()
	if engine_type == "bayesian":
		return BayesianEngine()
	elif engine_type in ["fsrs_real", "fsrs"]:
		return FSRSEngine()
	elif engine_type in ["rhizodb"]:
		return RhizoDBEngine()
	else:
		return FSRSEngine()  # Default fallback
