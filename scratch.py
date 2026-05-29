from unittest.mock import MagicMock, patch

from red_pill.metabolism.auditor import SentinelAuditor

mock_vram = MagicMock()
mock_vram.returncode = 0
mock_vram.stdout = "1024,8192"
mock_dmesg = MagicMock()
mock_dmesg.returncode = 0
mock_dmesg.stdout = "System functioning normally"

auditor = SentinelAuditor(force=True)

with patch("subprocess.run", side_effect=[mock_vram, mock_dmesg]):
	with patch("urllib.request.urlopen"), patch("pathlib.Path.exists", return_value=False):
		report = auditor.audit_vitals()
		print("REPORT FINDINGS:", report.findings)
