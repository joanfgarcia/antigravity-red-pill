"""SIP provisioning sentinel — validación de contenido del daemon generado.

El sentinel solo comprobaba la EXISTENCIA de `run_dual_bind.py`; un deploy a
medias lo deja presente pero roto (sin `ModelManager` → 500 en cada request).
Estos tests fijan la validación de contenido (`_check_dual_bind_content`)."""

from red_pill.metabolism.sentinel_plugins.check_sip_provisioning import SipProvisioningCheck

GOOD = '''\"\"\"generated daemon\"\"\"
import asyncio


class ModelManager:
	pass


manager = ModelManager()
'''

MISSING_MANAGER = '''\"\"\"generated daemon, truncated\"\"\"
import asyncio


def _proxy_to_worker(port, body):
	return None
'''

BROKEN_SYNTAX = "def oops(:\n\tpass\n"


def _check(tmp_path, content):
	p = tmp_path / "run_dual_bind.py"
	p.write_text(content, encoding="utf-8")
	return SipProvisioningCheck()._check_dual_bind_content(p)


def test_daemon_valido_sin_findings(tmp_path):
	assert _check(tmp_path, GOOD) is None


def test_daemon_sin_manager_es_corrupto(tmp_path):
	finding = _check(tmp_path, MISSING_MANAGER)
	assert finding is not None
	assert finding.type == "sip_corrupt_dual_bind"


def test_daemon_con_sintaxis_rota_es_corrupto(tmp_path):
	finding = _check(tmp_path, BROKEN_SYNTAX)
	assert finding is not None
	assert finding.type == "sip_corrupt_dual_bind"


def test_daemon_ilegible_es_corrupto(tmp_path):
	finding = SipProvisioningCheck()._check_dual_bind_content(tmp_path / "no_existe.py")
	assert finding is not None
	assert finding.type == "sip_corrupt_dual_bind"
