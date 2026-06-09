"""Unit tests for ``CredentialsLoader`` (Requirement 3, Task 5.1)."""

from __future__ import annotations

import io
import os
import tempfile

import pytest

from tests.unit._provision_loader import prov

AKID = "AKIAIOSFODNN7EXAMPLE"
SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def _logger():
    return prov.Logger(prov.SecretRedactor(), stream=io.StringIO())


def _write(content):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "credentials")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(content)
    return p


def test_loads_plain_values():
    p = _write(f"[default]\naws_access_key_id = {AKID}\naws_secret_access_key = {SECRET}\n")
    creds = prov.CredentialsLoader.load(prov.SecretRedactor(), _logger(), path=p)
    assert creds.access_key_id == AKID
    assert creds.secret_access_key == SECRET
    assert creds.session_token is None


def test_strips_surrounding_quotes():
    p = _write(f'[default]\naws_access_key_id = "{AKID}"\naws_secret_access_key = \'{SECRET}\'\n')
    creds = prov.CredentialsLoader.load(prov.SecretRedactor(), _logger(), path=p)
    assert creds.access_key_id == AKID
    assert creds.secret_access_key == SECRET


def test_ignores_comment_lines():
    p = _write(
        "# a comment\n; another comment\n"
        f"[default]\naws_access_key_id = {AKID}\naws_secret_access_key = {SECRET}\n"
    )
    creds = prov.CredentialsLoader.load(prov.SecretRedactor(), _logger(), path=p)
    assert creds.access_key_id == AKID


def test_session_token_round_trip():
    token = "FQoGZXIvYXdzELL//////////wEXAMPLE"
    p = _write(
        f"[default]\naws_access_key_id = {AKID}\naws_secret_access_key = {SECRET}\n"
        f"aws_session_token = {token}\n"
    )
    creds = prov.CredentialsLoader.load(prov.SecretRedactor(), _logger(), path=p)
    assert creds.session_token == token


def test_missing_file_exits_creds():
    with pytest.raises(prov.ProvisioningError) as exc:
        prov.CredentialsLoader.load(prov.SecretRedactor(), _logger(), path="/no/such/creds")
    assert exc.value.code == prov.EXIT_CREDS


def test_missing_section_exits_creds():
    p = _write(f"[other]\naws_access_key_id = {AKID}\n")
    with pytest.raises(prov.ProvisioningError) as exc:
        prov.CredentialsLoader.load(prov.SecretRedactor(), _logger(), path=p)
    assert exc.value.code == prov.EXIT_CREDS


def test_missing_field_exits_creds():
    p = _write("[default]\naws_access_key_id = %s\n" % AKID)
    with pytest.raises(prov.ProvisioningError) as exc:
        prov.CredentialsLoader.load(prov.SecretRedactor(), _logger(), path=p)
    assert exc.value.code == prov.EXIT_CREDS


def test_empty_field_exits_creds():
    p = _write("[default]\naws_access_key_id =\naws_secret_access_key = %s\n" % SECRET)
    with pytest.raises(prov.ProvisioningError) as exc:
        prov.CredentialsLoader.load(prov.SecretRedactor(), _logger(), path=p)
    assert exc.value.code == prov.EXIT_CREDS


def test_error_message_never_contains_credential_value():
    p = _write("[default]\naws_access_key_id = %s\n" % AKID)  # missing secret
    log = _logger()
    with pytest.raises(prov.ProvisioningError):
        prov.CredentialsLoader.load(prov.SecretRedactor(), log, path=p)
    assert AKID not in log.stream.getvalue()


def test_redaction_registered_immediately_after_load():
    p = _write(f"[default]\naws_access_key_id = {AKID}\naws_secret_access_key = {SECRET}\n")
    redactor = prov.SecretRedactor()
    prov.CredentialsLoader.load(redactor, _logger(), path=p)
    assert AKID not in redactor.scrub(f"echo {AKID}")
    assert SECRET not in redactor.scrub(f"echo {SECRET}")
