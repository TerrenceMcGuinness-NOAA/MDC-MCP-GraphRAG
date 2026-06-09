"""Unit tests for ``Eligibility`` and ``UserDiscovery`` (Requirements 2, 9; Task 6.1)."""

from __future__ import annotations

import io
from collections import namedtuple

import pytest

from tests.unit._provision_loader import prov

PW = namedtuple("PW", "pw_name pw_uid pw_gid pw_dir pw_shell")


def _entry(name, uid=1001, gid=None, home=None, shell="/bin/bash"):
    return PW(name, uid, gid if gid is not None else uid, home or f"/home/{name}", shell)


def _logger():
    return prov.Logger(prov.SecretRedactor(), stream=io.StringIO())


# --- is_eligible ----------------------------------------------------------

def test_eligible_typical_user():
    ok, reason = prov.Eligibility.is_eligible(_entry("alice"), frozenset())
    assert ok and reason == ""


def test_uid_below_1000_rejected():
    ok, reason = prov.Eligibility.is_eligible(_entry("svc", uid=500), frozenset())
    assert not ok and "uid" in reason


@pytest.mark.parametrize("shell", ["/sbin/nologin", "/usr/sbin/nologin", "/bin/false"])
def test_nologin_shells_rejected(shell):
    ok, reason = prov.Eligibility.is_eligible(_entry("bot", shell=shell), frozenset())
    assert not ok and "shell" in reason


def test_mismatched_home_rejected():
    ok, reason = prov.Eligibility.is_eligible(_entry("alice", home="/opt/alice"), frozenset())
    assert not ok and "home" in reason


def test_builtin_exclusions_rejected():
    ok, _ = prov.Eligibility.is_eligible(_entry("ec2-user", uid=1000), frozenset())
    assert not ok
    ok2, _ = prov.Eligibility.is_eligible(_entry("root", uid=0), frozenset())
    assert not ok2


def test_custom_exclusion_rejected():
    ok, reason = prov.Eligibility.is_eligible(_entry("bob"), frozenset({"bob"}))
    assert not ok and reason == "excluded"


# --- check_or_die (single-user, R9) ---------------------------------------

def _pwnam(entries):
    table = {e.pw_name: e for e in entries}

    def _get(name):
        return table[name]  # raises KeyError if absent

    return _get


def test_check_or_die_missing_user():
    with pytest.raises(prov.ProvisioningError) as exc:
        prov.Eligibility.check_or_die("ghost", frozenset(), _logger(), getpwnam=_pwnam([]))
    assert exc.value.code != 0


def test_check_or_die_excluded_user():
    with pytest.raises(prov.ProvisioningError) as exc:
        prov.Eligibility.check_or_die(
            "ec2-user", frozenset(), _logger(), getpwnam=_pwnam([_entry("ec2-user", uid=1000)])
        )
    assert "excluded" in str(exc.value).lower()


def test_check_or_die_low_uid():
    with pytest.raises(prov.ProvisioningError) as exc:
        prov.Eligibility.check_or_die(
            "svc", frozenset(), _logger(), getpwnam=_pwnam([_entry("svc", uid=500)])
        )
    assert "threshold" in str(exc.value)


def test_check_or_die_nologin_shell():
    with pytest.raises(prov.ProvisioningError) as exc:
        prov.Eligibility.check_or_die(
            "bot", frozenset(), _logger(),
            getpwnam=_pwnam([_entry("bot", shell="/sbin/nologin")]),
        )
    assert "shell" in str(exc.value)


def test_check_or_die_bad_home():
    with pytest.raises(prov.ProvisioningError) as exc:
        prov.Eligibility.check_or_die(
            "alice", frozenset(), _logger(),
            getpwnam=_pwnam([_entry("alice", home="/opt/alice")]),
        )
    assert "home" in str(exc.value)


def test_check_or_die_valid_returns_target():
    target = prov.Eligibility.check_or_die(
        "alice", frozenset(), _logger(), getpwnam=_pwnam([_entry("alice", uid=1001, gid=1002)])
    )
    assert isinstance(target, prov.TargetUser)
    assert target.name == "alice" and target.uid == 1001 and target.gid == 1002


# --- UserDiscovery sort ----------------------------------------------------

def test_discovery_sorts_c_locale_and_filters():
    entries = [
        _entry("bob"),
        _entry("Alice", uid=1005),  # capital A sorts before lowercase in C-locale
        _entry("alice"),
        _entry("root", uid=0),
        _entry("svc", uid=200),
        _entry("nolog", shell="/sbin/nologin"),
        _entry("ec2-user", uid=1000),
    ]
    users = prov.UserDiscovery.eligible(frozenset(), _logger(), getpwall=lambda: entries)
    names = [u.name for u in users]
    assert names == ["Alice", "alice", "bob"]  # C-locale: 'A'(65) < 'a'(97) < 'b'
