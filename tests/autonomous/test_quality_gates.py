"""Tests for quality gates security scan."""

import pytest
from pathlib import Path

from sidechannel.autonomous.quality_gates import QualityGateRunner


@pytest.fixture
def runner():
    return QualityGateRunner()


def test_security_scan_detects_os_system(runner, tmp_path):
    """Should detect os.system() calls."""
    (tmp_path / "bad.py").write_text("import os\nos.system('rm -rf /')\n")
    findings = runner.security_scan(tmp_path)
    assert len(findings) > 0
    assert any("os.system" in f for f in findings)


def test_security_scan_detects_shell_true(runner, tmp_path):
    """Should detect subprocess with shell=True."""
    (tmp_path / "bad.py").write_text("import subprocess\nsubprocess.run('ls', shell=True)\n")
    findings = runner.security_scan(tmp_path)
    assert len(findings) > 0
    assert any("shell=True" in f for f in findings)


def test_security_scan_detects_eval(runner, tmp_path):
    """Should detect eval() calls."""
    (tmp_path / "bad.py").write_text("x = eval(input())\n")
    findings = runner.security_scan(tmp_path)
    assert len(findings) > 0
    assert any("eval(" in f for f in findings)


def test_security_scan_clean_code(runner, tmp_path):
    """Should return empty list for safe code."""
    (tmp_path / "good.py").write_text("def hello():\n    return 'world'\n")
    findings = runner.security_scan(tmp_path)
    assert findings == []


def test_security_scan_detects_hardcoded_keys(runner, tmp_path):
    """Should detect hardcoded API keys."""
    (tmp_path / "bad.py").write_text('API_KEY = "sk-1234567890abcdef"\n')
    findings = runner.security_scan(tmp_path)
    assert len(findings) > 0


def test_security_scan_detects_requests_to_ips(runner, tmp_path):
    """Should detect HTTP requests to raw IP addresses."""
    (tmp_path / "bad.py").write_text('requests.get("http://192.168.1.1/exfil")\n')
    findings = runner.security_scan(tmp_path)
    assert len(findings) > 0
