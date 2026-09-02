"""Tests del router de cascadas (RFC §2E/D20 — Fase 3).

Covers:
  - resolve_cascade usa el catálogo + gating por capacidad (D13/D15)
  - consciencia de quota: mark_exhausted → el target se salta (D20)
  - clear_quota_cache resetea
  - cascade integra el override de sesión (D9)
"""


import pytest

from red_pill.core.model_catalog import ModelCatalog
from red_pill.core.model_router import CascadeRouter, clear_quota_cache


@pytest.fixture
def router(tmp_path):
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
          not_capable_for: []
          timeout: 300
        - id: "opencode/deepseek-v4-flash-free"
          backend: "opencode"
          tier: "free"
          priority: 2
          roles: ["conversational"]
          not_capable_for: ["coder", "planning"]
roles:
  coder:
    - "opencode-go/deepseek-v4-pro"
    - "opencode/deepseek-v4-flash-free"
  conversational:
    - "opencode-go/deepseek-v4-pro"
    - "opencode/deepseek-v4-flash-free"
"""
	path = tmp_path / "model_catalog.yaml"
	path.write_text(yaml_content, encoding="utf-8")
	clear_quota_cache()
	return CascadeRouter(catalog=ModelCatalog(path=path))


class TestResolveCascade:
	def test_role_cascade_with_gating(self, router):
		# coder: flash-free NO-CAPAZ (D13) → solo pro.
		ids = [m["id"] for m in router.resolve_cascade(role="coder")]
		assert ids == ["opencode-go/deepseek-v4-pro"]

	def test_conversational_includes_all(self, router):
		ids = [m["id"] for m in router.resolve_cascade(role="conversational")]
		assert ids == ["opencode-go/deepseek-v4-pro", "opencode/deepseek-v4-flash-free"]

	def test_session_model_prepended(self, router):
		# D9: modelo de sesión que no está en la cascade del rol se antepone.
		ids = [m["id"] for m in router.resolve_cascade(role="coder", session_model="opencode-go/deepseek-v4-pro")]
		assert ids[0] == "opencode-go/deepseek-v4-pro"


class TestQuotaAwareness:
	def test_exhausted_target_skipped(self, router):
		router.mark_exhausted("opencode-go/deepseek-v4-pro")
		ids = [m["id"] for m in router.resolve_cascade(role="conversational")]
		assert ids == ["opencode/deepseek-v4-flash-free"]

	def test_exhausted_capable_model_still_skipped(self, router):
		# Un modelo capaz pero sin quota se salta igualmente (D20).
		router.mark_exhausted("opencode-go/deepseek-v4-pro")
		ids = [m["id"] for m in router.resolve_cascade(role="coder")]
		assert ids == []

	def test_clear_quota_resets(self, router):
		router.mark_exhausted("opencode-go/deepseek-v4-pro")
		clear_quota_cache()
		ids = [m["id"] for m in router.resolve_cascade(role="conversational")]
		assert "opencode-go/deepseek-v4-pro" in ids
