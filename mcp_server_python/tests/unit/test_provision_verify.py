"""Unit tests for ``VerificationProbe`` and ``Idempotency`` (Requirements 8, 14; Task 11.1)."""

from __future__ import annotations

import io

from tests.unit._provision_loader import prov
from tests.unit._provision_fakes import make_target


def _logger(verbose=False):
    return prov.Logger(prov.SecretRedactor(), stream=io.StringIO(), verbose=verbose)


def _cfg(region="us-east-1", verbose=False):
    return prov.Config(
        runtime_arn=prov.DEFAULT_RUNTIME_ARN,
        region=region,
        proxy_path="/p/proxy.py",
        runtime_arn_source="default",
        region_source="default",
        proxy_path_source="default",
        mode="bulk",
        target_user=None,
        exclusions=frozenset(),
        verify=True,
        verbose=verbose,
        dry_run=False,
        output_format="table",
    )


class _ProbeOps(prov.Privileged):
    """Ops fake whose ``run_as`` returns scripted results keyed by command label."""

    def __init__(self, results):
        # results: list of RunResult, returned in call order
        self.results = list(results)
        self.calls = []

    def run_as(self, user, argv, env, timeout):
        self.calls.append((user, argv, dict(env), timeout))
        return self.results.pop(0)


def test_probe_success_returns_none():
    ops = _ProbeOps([
        prov.RunResult(0, False, '{"Account":"903050880929"}', ""),
        prov.RunResult(0, False, '{"agentRuntimes":[]}', ""),
    ])
    probe = prov.VerificationProbe(ops, _logger())
    assert probe.verify(make_target("alice"), _cfg()) is None
    # Both probes ran with timeout=30 and the agentcore-rag profile.
    assert all(c[3] == prov.PROBE_TIMEOUT for c in ops.calls)
    assert all(c[2]["AWS_PROFILE"] == "agentcore-rag" for c in ops.calls)
    assert all(c[2]["HOME"] == "/home/alice" for c in ops.calls)


def test_probe_sts_nonzero_exit():
    ops = _ProbeOps([prov.RunResult(255, False, "", "denied")])
    reason = prov.VerificationProbe(ops, _logger()).verify(make_target("alice"), _cfg())
    assert reason == "sts exit 255"


def test_probe_sts_timeout():
    ops = _ProbeOps([prov.RunResult(-1, True, "", "")])
    reason = prov.VerificationProbe(ops, _logger()).verify(make_target("alice"), _cfg())
    assert reason == f"sts timeout after {prov.PROBE_TIMEOUT}s"


def test_probe_agentcore_timeout_reported_distinctly():
    ops = _ProbeOps([
        prov.RunResult(0, False, "{}", ""),
        prov.RunResult(-1, True, "", ""),
    ])
    reason = prov.VerificationProbe(ops, _logger()).verify(make_target("alice"), _cfg())
    assert reason == f"agentcore timeout after {prov.PROBE_TIMEOUT}s"


def test_probe_agentcore_nonzero_exit():
    ops = _ProbeOps([
        prov.RunResult(0, False, "{}", ""),
        prov.RunResult(1, False, "", "boom"),
    ])
    reason = prov.VerificationProbe(ops, _logger()).verify(make_target("alice"), _cfg())
    assert reason == "agentcore exit 1"


def test_verbose_echoes_stdout_default_does_not():
    out_default = io.StringIO()
    ops = _ProbeOps([
        prov.RunResult(0, False, "CALLER-IDENTITY-BODY", ""),
        prov.RunResult(0, False, "RUNTIMES-BODY", ""),
    ])
    prov.VerificationProbe(ops, prov.Logger(prov.SecretRedactor(), stream=out_default, verbose=False)).verify(
        make_target("alice"), _cfg(verbose=False)
    )
    assert "CALLER-IDENTITY-BODY" not in out_default.getvalue()

    out_verbose = io.StringIO()
    ops2 = _ProbeOps([
        prov.RunResult(0, False, "CALLER-IDENTITY-BODY", ""),
        prov.RunResult(0, False, "RUNTIMES-BODY", ""),
    ])
    prov.VerificationProbe(ops2, prov.Logger(prov.SecretRedactor(), stream=out_verbose, verbose=True)).verify(
        make_target("alice"), _cfg(verbose=True)
    )
    assert "CALLER-IDENTITY-BODY" in out_verbose.getvalue()


# --- Idempotency cross-file check -----------------------------------------

def test_cross_file_check_match():
    assert prov.Idempotency.cross_file_check("agentcore-rag", "agentcore-rag") is None


def test_cross_file_check_strips_whitespace():
    assert prov.Idempotency.cross_file_check("agentcore-rag", "  agentcore-rag  ") is None


def test_cross_file_check_mismatch():
    reason = prov.Idempotency.cross_file_check("agentcore-rag", "other")
    assert reason and "mismatch" in reason


def test_cross_file_check_wrong_constant():
    reason = prov.Idempotency.cross_file_check("agentcore", "agentcore")
    assert reason and "required" in reason


# --- SudoPrivileged.run_as timeout honored --------------------------------

class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_sudo_run_as_passes_timeout_30_and_argv_shape(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["timeout"] = kwargs.get("timeout")
        return _FakeProc(0, "{}", "")

    monkeypatch.setattr(prov.subprocess, "run", fake_run)
    sp = prov.SudoPrivileged()
    res = sp.run_as("alice", ["aws", "sts", "get-caller-identity"],
                    {"AWS_PROFILE": "agentcore-rag", "HOME": "/home/alice"}, prov.PROBE_TIMEOUT)
    assert res.returncode == 0 and not res.timed_out
    assert captured["timeout"] == 30
    argv = captured["argv"]
    assert argv[0:5] == ["sudo", "-n", "-u", "alice", "-H"]
    assert argv[5] == "env"
    assert "AWS_PROFILE=agentcore-rag" in argv
    assert argv[-3:] == ["aws", "sts", "get-caller-identity"]


def test_sudo_run_as_timeout_returns_timed_out(monkeypatch):
    def fake_run(argv, **kwargs):
        raise prov.subprocess.TimeoutExpired(cmd=argv, timeout=kwargs.get("timeout", 30))

    monkeypatch.setattr(prov.subprocess, "run", fake_run)
    sp = prov.SudoPrivileged()
    res = sp.run_as("alice", ["aws", "sts", "get-caller-identity"], {}, prov.PROBE_TIMEOUT)
    assert res.timed_out is True
