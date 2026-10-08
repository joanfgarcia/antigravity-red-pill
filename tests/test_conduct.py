"""TST-CO-001: capa de conducta unificada (RFC-HARNESS-003 corte 4).

Herméticos: sin GPU ni config real — ResolvedModel construidos a mano y
monkeypatch de ModelRegistry para la propagación del resolve.
"""

from red_pill.core.model_runtime import ResolvedModel


def _resolved(**kw):
	base = dict(profile_name="x", model_path="/x.gguf")
	base.update(kw)
	return ResolvedModel(**base)


class TestSamplingKwargs:
	def test_uses_model_recipe(self):
		from red_pill.inference import conduct

		r = _resolved(temperature=1.0, sampling={"top_p": 0.95, "top_k": 20, "min_p": 0.05})
		kw = conduct.sampling_kwargs(r)
		assert kw == {"temperature": 1.0, "top_p": 0.95, "top_k": 20, "min_p": 0.05}

	def test_caller_override_wins(self):
		from red_pill.inference import conduct

		r = _resolved(temperature=1.0, sampling={"top_p": 0.95})
		kw = conduct.sampling_kwargs(r, temperature=0.2)
		assert kw["temperature"] == 0.2
		assert kw["top_p"] == 0.95

	def test_ignores_unknown_sampler_keys(self):
		from red_pill.inference import conduct

		r = _resolved(sampling={"inventado": 7})
		assert "inventado" not in conduct.sampling_kwargs(r)


class TestChatTemplateKwargs:
	def test_thinking_off_disables(self):
		from red_pill.inference import conduct

		assert conduct.chat_template_kwargs(_resolved(thinking="off")) == {"enable_thinking": False}

	def test_reasoning_effort_passthrough(self):
		from red_pill.inference import conduct

		assert conduct.chat_template_kwargs(_resolved(thinking="on", reasoning_effort="medium")) == {
			"reasoning_effort": "medium"
		}

	def test_no_conduct_no_kwargs(self):
		from red_pill.inference import conduct

		assert conduct.chat_template_kwargs(None) == {}


class TestRequestKwargs:
	def test_full_body(self):
		from red_pill.inference import conduct

		r = _resolved(temperature=1.0, max_tokens=8192, thinking="on", reasoning_effort="medium", sampling={"top_p": 0.95})
		kw = conduct.request_kwargs(r, max_tokens=2048)
		assert kw["max_tokens"] == 2048
		assert kw["temperature"] == 1.0
		assert kw["top_p"] == 0.95
		assert kw["chat_template_kwargs"] == {"reasoning_effort": "medium"}

	def test_thinking_off_request(self):
		from red_pill.inference import conduct

		r = _resolved(thinking="off", max_tokens=None)
		kw = conduct.request_kwargs(r)
		assert kw["chat_template_kwargs"] == {"enable_thinking": False}
		assert "max_tokens" not in kw


class TestApplyPython:
	def test_sets_chat_format_on_llm(self):
		from types import SimpleNamespace

		from red_pill.inference import conduct

		llm = SimpleNamespace()
		kw = conduct.apply_python(llm, _resolved(thinking="off"))
		assert llm.chat_format == "llama-2"  # sin handlers registrados → default llama_cpp
		assert kw["temperature"] == 0.3


class TestFileTemplate:
	def test_register_and_apply(self, monkeypatch, tmp_path):
		from types import SimpleNamespace

		import llama_cpp.llama_chat_format as lcf

		from red_pill.inference import runtime as ir

		registered = {}

		def fake_register(name):
			def deco(fn):
				registered[name] = fn
				return fn

			return deco

		monkeypatch.setattr(lcf, "register_chat_format", fake_register)
		tpl = tmp_path / "simple.jinja"
		tpl.write_text("{{ messages[0]['content'] }}", encoding="utf-8")
		llm = SimpleNamespace(token_eos=lambda: 2, _model=SimpleNamespace(token_get_text=lambda i: "<|im_end|>"))
		resolved = _resolved(chat_template_file=str(tpl))

		name = ir.register_file_template(llm, resolved)
		assert name == "profile-template-x"
		assert name in registered

		ir.apply_chat_handler(llm, resolved, {})
		assert llm.chat_format == name

		ir.apply_chat_handler(llm, resolved, {"chat_format": "chatml"})
		assert llm.chat_format == "chatml"

	def test_no_template_file_noop(self):
		from types import SimpleNamespace

		from red_pill.inference import runtime as ir

		llm = SimpleNamespace()
		assert ir.register_file_template(llm, _resolved()) is None


class TestResolvePropagation:
	def _setup(self, monkeypatch):
		import red_pill.core.model_runtime as mr
		from red_pill.core.model_registry import ModelRegistry

		monkeypatch.setattr(ModelRegistry, "reload", classmethod(lambda cls: None))
		monkeypatch.setattr(
			ModelRegistry,
			"_profiles_cache",
			{
				"probe_model": {
					"model_path": "/tmp/probe.gguf",
					"temperature": 1.0,
					"thinking": "on",
					"reasoning_effort": "medium",
					"sampling": {"top_p": 0.95},
					"chat_template_file": "configs/chat_templates/probe.jinja",
					"license": {
						"id": "apache-2.0",
						"commercial_ok": True,
						"redistribution_ok": True,
						"attribution_required": False,
						"share_alike": False,
					},
					"hardware_affinity": {"n_ctx": 4096},
				}
			},
		)
		return mr

	def test_profile_conduct_propagates(self, monkeypatch):
		mr = self._setup(monkeypatch)
		resolved = mr.resolve({"model": "probe_model"})
		assert resolved.reasoning_effort == "medium"
		assert resolved.sampling == {"top_p": 0.95}
		assert resolved.chat_template_file == "configs/chat_templates/probe.jinja"

	def test_body_overrides_merge(self, monkeypatch):
		mr = self._setup(monkeypatch)
		resolved = mr.resolve({"model": "probe_model", "reasoning_effort": "xhigh", "sampling": {"min_p": 0.05}})
		assert resolved.reasoning_effort == "xhigh"
		assert resolved.sampling == {"top_p": 0.95, "min_p": 0.05}
