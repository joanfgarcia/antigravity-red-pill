from typing import Iterator

import pytest

from red_pill.core.providers import BaseInferenceProvider, ProviderRegistry


class MockInferenceProvider(BaseInferenceProvider):
	def generate(self, prompt: str, **kwargs) -> str:
		return f"Mock response to: {prompt}"

	def stream(self, prompt: str, **kwargs) -> Iterator[str]:
		yield f"Mock chunk for: {prompt}"


@pytest.fixture(autouse=True)
def reset_registry():
	ProviderRegistry.reset()
	yield


def test_inference_provider_registration():
	provider = MockInferenceProvider()
	ProviderRegistry.register_inference_provider("mock", provider)

	assert ProviderRegistry.get_inference_provider("mock") == provider
	assert "mock" in ProviderRegistry.list_inference_providers()


def test_default_inference_provider():
	provider1 = MockInferenceProvider()
	provider2 = MockInferenceProvider()

	# First one becomes default
	ProviderRegistry.register_inference_provider("p1", provider1)
	assert ProviderRegistry.get_inference_provider() == provider1

	# Second one can be marked default
	ProviderRegistry.register_inference_provider("p2", provider2, default=True)
	assert ProviderRegistry.get_inference_provider() == provider2


def test_missing_inference_provider():
	# Clear registry for pure test (not strictly necessary but good)
	ProviderRegistry._inference_providers = {}
	ProviderRegistry._default_inference_key = None

	with pytest.raises(RuntimeError, match="No inference provider registered"):
		ProviderRegistry.get_inference_provider("non_existent")


def test_base_provider_behavior():
	provider = MockInferenceProvider()
	assert provider.generate("test") == "Mock response to: test"
	chunks = list(provider.stream("test"))
	assert chunks == ["Mock chunk for: test"]
