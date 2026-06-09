"""Unit tests for ``SecretRedactor``, ``Logger``, excepthook, and signals.

Validates Requirements 12.1, 12.4, 12.5, 12.6 (Task 2.1).
"""

from __future__ import annotations

import io
import signal

import pytest

from tests.unit._provision_loader import prov

AKID = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def test_scrub_replaces_registered_values():
    r = prov.SecretRedactor()
    r.register(AKID, "aws_access_key_id")
    r.register(SECRET, "aws_secret_access_key")
    text = f"key={AKID} secret={SECRET}"
    out = r.scrub(text)
    assert AKID not in out
    assert SECRET not in out
    assert "<aws_access_key_id redacted>" in out
    assert "<aws_secret_access_key redacted>" in out


def test_scrub_handles_json_ini_and_traceback_formats():
    r = prov.SecretRedactor()
    r.register(SECRET, "aws_secret_access_key")
    json_blob = '{"aws_secret_access_key": "%s"}' % SECRET
    ini_blob = "aws_secret_access_key = %s\n" % SECRET
    tb_blob = 'ValueError: bad value %s in line\n' % SECRET
    for blob in (json_blob, ini_blob, tb_blob):
        assert SECRET not in r.scrub(blob)


def test_secret_with_json_significant_characters_is_scrubbed():
    nasty = 'a"b\\c\nd\te'
    r = prov.SecretRedactor()
    r.register(nasty, "aws_secret_access_key")
    assert nasty not in r.scrub(f"value={nasty}!")


def test_empty_value_is_not_registered():
    r = prov.SecretRedactor()
    r.register("", "aws_secret_access_key")
    r.register(None, "aws_session_token")
    assert r.registered_count == 0
    # An empty registration must not blank-replace arbitrary text.
    assert r.scrub("hello world") == "hello world"


def test_duplicate_registration_is_deduplicated():
    r = prov.SecretRedactor()
    r.register(AKID, "aws_access_key_id")
    r.register(AKID, "aws_access_key_id")
    assert r.registered_count == 1


def test_scrub_when_no_tokens_returns_input_unchanged():
    r = prov.SecretRedactor()
    assert r.scrub("nothing to do") == "nothing to do"


def test_logger_scrubs_every_write():
    r = prov.SecretRedactor()
    r.register(SECRET, "aws_secret_access_key")
    buf = io.StringIO()
    log = prov.Logger(r, stream=buf)
    log.error(f"failed with {SECRET}")
    log.info(f"value {SECRET}")
    out = buf.getvalue()
    assert SECRET not in out
    assert "[ERROR]" in out and "[INFO]" in out


def test_logger_debug_only_when_verbose():
    r = prov.SecretRedactor()
    buf = io.StringIO()
    log = prov.Logger(r, stream=buf, verbose=False)
    log.debug("hidden")
    assert "hidden" not in buf.getvalue()
    log.verbose = True
    log.debug("shown")
    assert "shown" in buf.getvalue()


def test_logger_scrubs_subprocess_argv_echo():
    # Requirement 12.5: a subprocess argv echo routed through Logger is scrubbed.
    r = prov.SecretRedactor()
    r.register(SECRET, "aws_secret_access_key")
    buf = io.StringIO()
    log = prov.Logger(r, stream=buf)
    argv = ["aws", "configure", "set", "aws_secret_access_key", SECRET]
    log.debug("argv: %r" % argv)  # debug suppressed when not verbose
    log.verbose = True
    log.debug("argv: %r" % argv)
    assert SECRET not in buf.getvalue()


def test_excepthook_redacts_traceback():
    r = prov.SecretRedactor()
    r.register(SECRET, "aws_secret_access_key")
    buf = io.StringIO()
    log = prov.Logger(r, stream=buf)
    original = __import__("sys").excepthook
    try:
        prov.install_excepthook(log)
        import sys as _sys

        try:
            raise ValueError(f"leaked {SECRET} here")
        except ValueError:
            _sys.excepthook(*_sys.exc_info())
    finally:
        __import__("sys").excepthook = original
    out = buf.getvalue()
    assert SECRET not in out
    assert "ValueError" in out


def test_signal_handler_flushes_and_exits_nonzero():
    r = prov.SecretRedactor()
    r.register(SECRET, "aws_secret_access_key")
    buf = io.StringIO()
    log = prov.Logger(r, stream=buf)
    flushed = {"called": False}

    def flush(logger):
        flushed["called"] = True
        logger.raw(f"partial summary with {SECRET}\n")

    original_int = signal.getsignal(signal.SIGINT)
    original_term = signal.getsignal(signal.SIGTERM)
    try:
        prov.install_signal_handlers(log, flush)
        handler = signal.getsignal(signal.SIGINT)
        with pytest.raises(SystemExit) as exc:
            handler(signal.SIGINT, None)
        assert exc.value.code != 0
    finally:
        signal.signal(signal.SIGINT, original_int)
        signal.signal(signal.SIGTERM, original_term)
    assert flushed["called"] is True
    assert SECRET not in buf.getvalue()
