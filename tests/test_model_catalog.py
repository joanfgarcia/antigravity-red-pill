"""Tests del catálogo curado de modelos (RFC_TELEGRAM_RESILIENCE §2A/D6-D9).

Covers:
  - carga desde YAML (models ordenados por priority)
  - get() / backend_for() (D8: backend del catálogo, no por prefijo)
  - cascade_for() con rol (D13 gating por capacidad + D5 guard local)
  - cascade_for() con modelo de sesión (D9: antepone sin duplicar)
  - rechazo de modelo no curado (D7)
  - catálogo ausente → ModelCatalogError
"""

import pytest

from red_pill.core.model_catalog import ModelCatalog, ModelCatalogError


@pytest.fixture
def catalog(tmp_path):
	yaml_content = """
catalog:
  providers:
    opencode:
      models:
        - id: "opencode-go/deepseek-v4-pro"
          backend: "opencode"
          tier: "subscription"
          priority: 1
          roles: ["planning", "coder", "conversational"]
          capabilities: ["code", "planning"]
          not_capable_for: []
          timeout: 300
        - id: "opencode/deepseek-v4-flash-free"
          backend: "opencode"
          tier: "free"
          priority: 2
          roles: ["conversational"]
          not_capable_for: ["coder", "planning"]
        - id: "opencode/big-pickle"
          backend: "opencode"
          tier: "free"
          priority: 3
          roles: ["scout"]
          not_capable_for: ["coder", "planning"]
        - id: "local/granite-8b"
          backend: "local"
          tier: "local"
          priority: 9
          not_capable_for: ["coder", "planning", "scout"]
roles:
  coder:
    - "opencode-go/deepseek-v4-pro"
    - "opencode/deepseek-v4-flash-free"
  conversational:
    - "opencode-go/deepseek-v4-pro"
    - "opencode/deepseek-v4-flash-free"
    - "local/granite-8b"
"""
	path = tmp_path / "model_catalog.yaml"
	path.write_text(yaml_content, encoding="utf-8")
	return ModelCatalog(path=path)


class TestLoad:
	def test_models_sorted_by_priority(self, catalog):
		ids = [m["id"] for m in catalog.models()]
		assert ids == [
			"opencode-go/deepseek-v4-pro",
			"opencode/deepseek-v4-flash-free",
			"opencode/big-pickle",
			"local/granite-8b",
		]

	def test_models_filter_by_backend(self, catalog):
		ids = [m["id"] for m in catalog.models(backend="opencode")]
		assert ids == ["opencode-go/deepseek-v4-pro", "opencode/deepseek-v4-flash-free", "opencode/big-pickle"]

	def test_models_filter_by_tier(self, catalog):
		ids = [m["id"] for m in catalog.models(tier="free")]
		assert ids == ["opencode/deepseek-v4-flash-free", "opencode/big-pickle"]


class TestLookup:
	def test_get_existing(self, catalog):
		entry = catalog.get("opencode-go/deepseek-v4-pro")
		assert entry is not None and entry["tier"] == "subscription"

	def test_get_missing_returns_none(self, catalog):
		assert catalog.get("opencode/nonexistent") is None

	def test_backend_from_catalog(self, catalog):
		# D8: backend viene del catálogo, no se infiere del prefijo del id.
		assert catalog.backend_for("opencode-go/deepseek-v4-pro") == "opencode"
		assert catalog.backend_for("local/granite-8b") == "local"


class TestCascadeFor:
	def test_role_cascade_respects_gating(self, catalog):
		# coder: flash-free es NO-CAPAZ (D13) → solo pro; local filtrado (D5).
		ids = [m["id"] for m in catalog.cascade_for(role="coder")]
		assert ids == ["opencode-go/deepseek-v4-pro"]

	def test_local_only_with_allow_local(self, catalog):
		ids = [m["id"] for m in catalog.cascade_for(role="conversational", allow_local=True)]
		assert "local/granite-8b" in ids

	def test_local_filtered_by_default(self, catalog):
		ids = [m["id"] for m in catalog.cascade_for(role="conversational")]
		assert "local/granite-8b" not in ids

	def test_session_model_prepended_not_duplicated(self, catalog):
		# D9: modelo de sesión que ya está en la cascade NO se duplica.
		ids = [m["id"] for m in catalog.cascade_for(role="conversational", model_id="opencode/deepseek-v4-flash-free")]
		assert ids == ["opencode-go/deepseek-v4-pro", "opencode/deepseek-v4-flash-free"]

	def test_session_model_prepended_when_not_in_cascade(self, catalog):
		# D9: modelo de sesión de otro rol se antepone a la cascade, PERO el
		# gating por capacidad (D13) lo filtra si el modelo es NO-CAPAZ para el
		# rol (big-pickle no es capaz de coder).
		ids = [m["id"] for m in catalog.cascade_for(role="coder", model_id="opencode/big-pickle")]
		assert ids == ["opencode-go/deepseek-v4-pro"]

	def test_session_model_prepended_when_capable(self, catalog):
		# Modelo de sesión capaz y no en la cascade del rol → se antepone.
		ids = [m["id"] for m in catalog.cascade_for(role="scout", model_id="opencode-go/deepseek-v4-pro")]
		assert ids[0] == "opencode-go/deepseek-v4-pro"


class TestErrors:
	def test_missing_file_raises(self, tmp_path):
		catalog = ModelCatalog(path=tmp_path / "nope.yaml")
		with pytest.raises(ModelCatalogError):
			catalog.models()
