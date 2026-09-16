"""TST-ML-001: Model license policy — normalization, context gate and audit.

Covers `red_pill.core.model_license` plus its integration in `ModelRegistry`
and `ModelCatalog`:
  - normalize_license: dict / SPDX shorthand / unknown (fail-closed) / None
  - assert_commercial_ok: personal (no-op) vs commercial (blocks NC)
  - ModelRegistry.get_profile_by_capability(commercial_only=True)
  - ModelCatalog.cascade_for(commercial_only=True) + license_for

All tests are hermetic: no GPU, no real config files, no filesystem side-effects
(catalog tests use a tmp_path YAML).
"""

import pytest

import red_pill.core.model_registry as mr
from red_pill.core.model_catalog import ModelCatalog
from red_pill.core.model_license import (
	ModelLicenseError,
	assert_commercial_ok,
	commercial_ok,
	normalize_license,
)

# ── normalize_license ─────────────────────────────────────────────────────────


class TestNormalizeLicense:
	def test_spdx_shorthand_permissive(self):
		pol = normalize_license("apache-2.0")
		assert pol["id"] == "apache-2.0"
		assert pol["commercial_ok"] is True
		assert pol["known"] is True

	def test_spdx_shorthand_noncommercial(self):
		pol = normalize_license("cc-by-nc-4.0")
		assert pol["commercial_ok"] is False
		assert pol["share_alike"] is True
		assert pol["known"] is True

	def test_unknown_shorthand_fails_closed(self):
		pol = normalize_license("proprietary-weird-1.0", model_name="x")
		assert pol["commercial_ok"] is False
		assert pol["known"] is False

	def test_structured_block_is_authoritative(self):
		pol = normalize_license({"id": "custom", "commercial_ok": True, "redistribution_ok": False, "attribution_required": True})
		assert pol["commercial_ok"] is True
		assert pol["redistribution_ok"] is False
		assert pol["known"] is True

	def test_absent_license_fails_closed(self):
		pol = normalize_license(None)
		assert pol["id"] == "undeclared"
		assert pol["commercial_ok"] is False
		assert pol["known"] is False

	def test_commercial_ok_helper(self):
		assert commercial_ok("mit") is True
		assert commercial_ok("cc-by-nc-4.0") is False

	def test_data_privacy_flags_default_closed(self):
		pol = normalize_license(None)
		assert pol["prompts_used_for_training"] is False
		assert pol["confidential_ok"] is False

	def test_data_privacy_flags_from_block(self):
		pol = normalize_license(
			{
				"id": "opencode-big-pickle-promo",
				"commercial_ok": True,
				"redistribution_ok": False,
				"prompts_used_for_training": True,
				"confidential_ok": False,
			}
		)
		assert pol["commercial_ok"] is True
		assert pol["prompts_used_for_training"] is True
		assert pol["confidential_ok"] is False


# ── assert_commercial_ok gate ─────────────────────────────────────────────────


class TestCommercialGate:
	def test_personal_context_is_noop(self):
		# NC model + personal context → no raise.
		assert_commercial_ok("cc-by-nc-4.0", model_name="tiny_aya", context="personal")

	def test_commercial_context_blocks_nc(self):
		with pytest.raises(ModelLicenseError):
			assert_commercial_ok("cc-by-nc-4.0", model_name="tiny_aya", context="commercial")

	def test_commercial_context_allows_permissive(self):
		assert_commercial_ok("apache-2.0", model_name="granite", context="commercial")

	def test_context_from_env(self, monkeypatch):
		monkeypatch.setenv("REDPILL_LICENSE_CONTEXT", "commercial")
		with pytest.raises(ModelLicenseError):
			assert_commercial_ok("cc-by-nc-4.0", model_name="tiny_aya")

	def test_unknown_license_blocked_commercially(self):
		with pytest.raises(ModelLicenseError):
			assert_commercial_ok(None, model_name="mystery", context="commercial")


# ── ModelRegistry integration ─────────────────────────────────────────────────


class TestModelRegistryLicense:
	def setup_method(self):
		mr.ModelRegistry._profiles_cache = None

	def _setup(self):
		mr.ModelRegistry._profiles_cache = {
			"nc_distiller": {"capabilities": ["distillation"], "license": "cc-by-nc-4.0"},
			"free_distiller": {"capabilities": ["distillation"], "license": "apache-2.0"},
			"logic_only": {"capabilities": ["logic"], "license": "mit"},
		}

	def test_get_license_normalizes(self):
		self._setup()
		assert mr.ModelRegistry.get_license("nc_distiller")["commercial_ok"] is False
		assert mr.ModelRegistry.get_license("free_distiller")["commercial_ok"] is True

	def test_assert_commercial_ok_missing_profile_is_noop(self):
		self._setup()
		# Unknown profile must not fabricate a license block.
		mr.ModelRegistry.assert_commercial_ok("does_not_exist", context="commercial")

	def test_capability_personal_picks_first_match(self):
		self._setup()
		name, _ = mr.ModelRegistry.get_profile_by_capability("distillation", commercial_only=False)
		assert name == "nc_distiller"

	def test_capability_commercial_skips_nc(self):
		self._setup()
		name, _ = mr.ModelRegistry.get_profile_by_capability("distillation", commercial_only=True, context="commercial")
		assert name == "free_distiller"

	def test_capability_commercial_raises_when_all_blocked(self):
		mr.ModelRegistry._profiles_cache = {
			"nc_a": {"capabilities": ["distillation"], "license": "cc-by-nc-4.0"},
			"nc_b": {"capabilities": ["distillation"], "license": "cc-by-nc-4.0"},
		}
		with pytest.raises(ModelLicenseError):
			mr.ModelRegistry.get_profile_by_capability("distillation", commercial_only=True, context="commercial")


# ── ModelCatalog integration ──────────────────────────────────────────────────

_CATALOG_YAML = """
catalog:
  providers:
    local:
      models:
        - id: "local/nc"
          backend: "local"
          tier: "local"
          priority: 1
          roles: ["conversational"]
          capabilities: ["distillation"]
          not_capable_for: []
          license: "cc-by-nc-4.0"
        - id: "local/free"
          backend: "local"
          tier: "local"
          priority: 2
          roles: ["conversational"]
          capabilities: ["distillation"]
          not_capable_for: []
          license: "apache-2.0"
roles:
  conversational:
    - "local/nc"
    - "local/free"
"""


class TestModelCatalogLicense:
	def _catalog(self, tmp_path):
		p = tmp_path / "model_catalog.yaml"
		p.write_text(_CATALOG_YAML, encoding="utf-8")
		return ModelCatalog(path=p)

	def test_license_for(self, tmp_path):
		cat = self._catalog(tmp_path)
		assert cat.license_for("local/nc")["commercial_ok"] is False
		assert cat.license_for("local/free")["commercial_ok"] is True

	def test_cascade_personal_keeps_nc(self, tmp_path):
		cat = self._catalog(tmp_path)
		ids = [m["id"] for m in cat.cascade_for(role="conversational", allow_local=True)]
		assert ids == ["local/nc", "local/free"]

	def test_cascade_commercial_filters_nc(self, tmp_path):
		cat = self._catalog(tmp_path)
		ids = [m["id"] for m in cat.cascade_for(role="conversational", allow_local=True, commercial_only=True, context="commercial")]
		assert ids == ["local/free"]

	def test_cascade_commercial_raises_when_all_blocked(self, tmp_path):
		cat = self._catalog(tmp_path)
		cat._ensure_loaded()
		cat._data["roles"]["conversational"] = ["local/nc"]
		cat._models = [m for m in cat._models if m["id"] != "local/free"]
		with pytest.raises(ModelLicenseError):
			cat.cascade_for(role="conversational", allow_local=True, commercial_only=True, context="commercial")

	def test_assert_commercial_ok(self, tmp_path):
		cat = self._catalog(tmp_path)
		with pytest.raises(ModelLicenseError):
			cat.assert_commercial_ok("local/nc", context="commercial")
		cat.assert_commercial_ok("local/nc", context="personal")
