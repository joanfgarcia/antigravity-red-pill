from red_pill.core.providers import BaseInferenceProvider, ProviderRegistry
from red_pill.metabolism.sleep import distill_engram


class MockBrokenProvider(BaseInferenceProvider):
	def generate(self, prompt: str, **kwargs) -> str:
		# Simulate corrupt output from a broken model (like BitNet malfunctioning)
		return "...\n\\emn...\n\\emn...n\\emn..."

	def stream(self, prompt: str, **kwargs):
		pass


class MockPerfectSamanthaProvider(BaseInferenceProvider):
	def generate(self, prompt: str, **kwargs) -> str:
		return '{"summary": "Test summary", "emotion": "joy", "intensity": 0.8, "category": "work"}'

	def stream(self, prompt: str, **kwargs):
		pass


def test_distill_engram_fallback_on_corrupt_model():
	"""Verify that the system seals the memory securely if the model returns garbage."""
	ProviderRegistry.reset()
	ProviderRegistry.register_inference_provider("sip", MockBrokenProvider(), default=True)

	raw_content = "This is a test interaction that should fail gracefully."
	result = distill_engram(raw_content, fallback_category="social")

	# Must fallback gracefully to defaults
	assert result["category"] == "social"
	assert result["emotion"] == "neutral"
	assert result["intensity"] == 0.5
	assert result["summary"].startswith(raw_content)


def test_distill_engram_success():
	"""Verify that a successful Samantha distillation extracts all JSON fields correctly."""
	ProviderRegistry.reset()
	ProviderRegistry.register_inference_provider("sip", MockPerfectSamanthaProvider(), default=True)

	raw_content = "Perfect interaction."
	result = distill_engram(raw_content, fallback_category="social")

	assert result["category"] == "work"
	assert result["emotion"] == "joy"
	assert result["intensity"] == 0.8
	assert result["summary"] == "Test summary"
