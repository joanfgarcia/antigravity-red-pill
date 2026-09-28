"""SIP provider: el payload NO manda `model` si está vacío (fix 2026-09-28).

Un `model` inválido tiene prioridad sobre `task` en el selector (AD-030) y
tumbaba la síntesis de hubs con HTTP 500 (glob muerto `*Q4_K_M.gguf`).
"""

from red_pill.core.providers import SipInferenceProvider


def test_payload_omite_model_si_vacio():
	p = SipInferenceProvider(socket_path="/tmp/no.sock")
	pl = p._build_payload(task="conversation", messages=[{"role": "user", "content": "hi"}], temperature=0.3)
	assert "model" not in pl
	assert pl["task"] == "conversation"
	assert pl["temperature"] == 0.3


def test_payload_incluye_model_si_set():
	p = SipInferenceProvider(socket_path="/tmp/no.sock", model="granite_8b")
	pl = p._build_payload(task="conversation", messages=[], temperature=0.1)
	assert pl["model"] == "granite_8b"


def test_payload_extra_solo_si_presentes():
	p = SipInferenceProvider(socket_path="/tmp/no.sock")
	pl = p._build_payload(task="minion_tool", messages=[], temperature=0.2, max_tokens=8, stop=None, tools=[{"x": 1}])
	assert pl["max_tokens"] == 8
	assert "stop" not in pl
	assert pl["tools"] == [{"x": 1}]


def test_default_model_es_vacio():
	# No debe reaparecer el wildcard muerto.
	assert SipInferenceProvider(socket_path="/tmp/no.sock").model == ""
