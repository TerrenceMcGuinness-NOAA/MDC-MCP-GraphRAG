"""Unit tests for ``IdentityGate`` (Requirement 1, Task 3.1)."""

from __future__ import annotations

import io

import pytest

from tests.unit._provision_loader import prov


class _PW:
    def __init__(self, name):
        self.pw_name = name


def _logger():
    return prov.Logger(prov.SecretRedactor(), stream=io.StringIO())


def _gate(euid, euser, sudo_user):
    log = _logger()
    environ = {} if sudo_user is None else {"SUDO_USER": sudo_user}
    prov.IdentityGate.gate(
        log,
        geteuid=lambda: euid,
        getpwuid=lambda uid: _PW(euser),
        environ=environ,
    )
    return log


def test_ec2_user_direct_is_accepted():
    _gate(1000, "ec2-user", None)  # no raise


def test_root_with_sudo_user_ec2_user_is_accepted():
    _gate(0, "root", "ec2-user")  # no raise


def test_root_with_empty_sudo_user_is_refused():
    with pytest.raises(prov.ProvisioningError) as exc:
        _gate(0, "root", "")
    assert exc.value.code == prov.EXIT_IDENTITY


def test_root_with_unset_sudo_user_is_refused():
    with pytest.raises(prov.ProvisioningError) as exc:
        _gate(0, "root", None)
    assert exc.value.code == prov.EXIT_IDENTITY


def test_root_with_wrong_sudo_user_is_refused():
    with pytest.raises(prov.ProvisioningError) as exc:
        _gate(0, "root", "mallory")
    assert exc.value.code == prov.EXIT_IDENTITY


def test_other_nonroot_user_is_refused():
    with pytest.raises(prov.ProvisioningError) as exc:
        _gate(1001, "alice", None)
    assert exc.value.code == prov.EXIT_IDENTITY


def test_refusal_names_ec2_user():
    log = prov.Logger(prov.SecretRedactor(), stream=io.StringIO())
    with pytest.raises(prov.ProvisioningError):
        prov.IdentityGate.gate(
            log,
            geteuid=lambda: 1001,
            getpwuid=lambda uid: _PW("alice"),
            environ={},
        )
    assert "ec2-user" in log.stream.getvalue()
