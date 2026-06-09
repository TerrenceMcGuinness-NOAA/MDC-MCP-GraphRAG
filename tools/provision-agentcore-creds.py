#!/usr/bin/env python3.12
"""Provision per-user AWS credentials and Kiro MCP config for agentcore-mcp-rag.

This is the ``Provisioning_Script`` defined by the
``agentcore-creds-provisioning`` Kiro spec. It runs once (or on demand) as the
operator account ``ec2-user`` on the shared EC2 host and brings every eligible
per-user OS account up to spec for the ``agentcore-mcp-rag`` MCP server:

* a ``[agentcore-rag]`` profile in each target user's ``~/.aws/credentials``,
  sourced from the master IAM keys in ``/home/ec2-user/.aws/credentials``
  ``[default]``; and
* an ``agentcore-mcp-rag`` server entry in each target user's
  ``~/.kiro/settings/mcp.json`` whose ``env`` references ``AWS_PROFILE`` =
  ``agentcore-rag`` and ``AWS_REGION`` = the configured region.

Design guarantees:

* **Identity-gated** -- refuses to run as anyone but ``ec2-user`` before any
  filesystem read of source creds or any target home directory.
* **Idempotent** -- re-running with the same source keys leaves every file
  byte-equal; users are classified ``created`` / ``updated`` / ``skipped`` /
  ``failed``.
* **Atomic** -- every target file is written via a temp-file-then-rename
  protocol with an ``fsync`` of the parent directory; readers never observe a
  torn file.
* **Secret-safe** -- the master keys are registered with the
  :class:`SecretRedactor` immediately after load and never appear in any log,
  traceback, or subprocess echo.
* **Least-privilege** -- the script process runs as ``ec2-user`` and escalates
  via ``sudo`` only for the specific per-target filesystem operations; it never
  opens another user's home directory from its own UID.

Stdlib only -- no third-party dependencies -- so master-key rotation is a
single file copy plus a re-run with no ``pip`` step.

Usage::

    sudo -u ec2-user python3.12 tools/provision-agentcore-creds.py --all --verify
    sudo -u ec2-user python3.12 tools/provision-agentcore-creds.py --user alice
    sudo -u ec2-user python3.12 tools/provision-agentcore-creds.py --all --dry-run --format json

See ``SETUP_AWS/provisioning/RUNBOOK_agentcore_creds.md`` for the operator
runbook and ``SETUP_AWS/provisioning/sudoers-agentcore-creds.example`` for the
minimal sudoers allow-list.
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import pwd
import re
import signal
import subprocess
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from typing import Literal, Optional

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: The only OS account permitted to run this script (Requirement 1).
OPERATOR = "ec2-user"

#: Fixed source of the master IAM keys (Requirement 3).
SOURCE_CREDENTIALS_FILE = "/home/ec2-user/.aws/credentials"
SOURCE_PROFILE_NAME = "default"

#: Fixed profile-section name written into every target file (Requirement 14).
#: This is NOT configurable.
AWS_PROFILE_NAME = "agentcore-rag"

#: Fixed MCP server-entry key managed in each target's mcp.json (Requirement 6).
MCP_SERVER_KEY = "agentcore-mcp-rag"

#: Eligibility predicate constants (Requirement 2).
MIN_UID = 1000
NOLOGIN_SHELLS = frozenset({"/sbin/nologin", "/usr/sbin/nologin", "/bin/false"})
BUILTIN_EXCLUSIONS = frozenset({"ec2-user", "root"})

#: Configurable-parameter defaults (Requirement 13 glossary).
DEFAULT_RUNTIME_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:903050880929:runtime/"
    "mdc_mcp_rag_server_python-v5K2F8BGrN"
)
DEFAULT_REGION = "us-east-1"
DEFAULT_PROXY_PATH = "/mdc-mcp-rag/eib-mcp-rag-server/tools/agentcore-kiro-proxy.py"

#: The command the MCP server entry launches (Requirement 6.4).
MCP_COMMAND = "python3.12"

#: Validation regexes (Requirements 13.6, 13.7). These are the authoritative
#: forms from requirements.md (the dot is allowed in the ARN runtime segment).
ARN_RE = re.compile(
    r"^arn:aws:bedrock-agentcore:[a-z0-9-]+:[0-9]{12}:runtime/[A-Za-z0-9_.-]+$"
)
REGION_RE = re.compile(r"^[a-z]{2}-[a-z]+-[0-9]+$")

#: Verification-probe timeout in seconds (Requirement 8).
PROBE_TIMEOUT = 30

#: Maximum reason-string length in the Run_Summary (Requirement 11.2).
MAX_REASON_LEN = 200

#: Exit codes (design "Exit codes"). Distinct so callers can tell argument
#: errors from provisioning errors (Requirement 10.7).
EXIT_OK = 0
EXIT_ARG = 2
EXIT_IDENTITY = 3
EXIT_CREDS = 4
EXIT_CONFIG = 5
EXIT_FAILED = 6


# --------------------------------------------------------------------------- #
# Data models (design "Data Models")
# --------------------------------------------------------------------------- #

Disposition = Literal["created", "updated", "skipped", "failed"]
ParamSource = Literal["cli", "env", "default"]


@dataclass(frozen=True)
class Config:
    """Resolved runtime configuration for a single invocation."""

    runtime_arn: str
    region: str
    proxy_path: str  # already symlink-resolved and existence-checked
    runtime_arn_source: ParamSource
    region_source: ParamSource
    proxy_path_source: ParamSource
    mode: Literal["bulk", "single"]
    target_user: Optional[str]  # only set in single mode
    exclusions: frozenset
    verify: bool
    verbose: bool
    dry_run: bool
    output_format: Literal["table", "json"]


@dataclass(frozen=True)
class IamCreds:
    """Master IAM credentials loaded from the Source_Credentials_File."""

    access_key_id: str
    secret_access_key: str
    session_token: Optional[str]


@dataclass(frozen=True)
class TargetUser:
    """A single per-user OS account to provision."""

    name: str
    uid: int
    gid: int
    home: str
    shell: str


@dataclass
class RunRecord:
    """Per-user outcome row for the Run_Summary."""

    user: str
    disposition: Disposition
    reason: str = ""


@dataclass
class FileChange:
    """Result of a single file write attempt."""

    path: str
    disposition: Disposition
    reason: str = ""
    profile: str = ""  # profile name guaranteed by the writer (cross-file check)


@dataclass
class Section:
    """One section of an INI-style credentials file with raw lines preserved."""

    header: Optional[str]  # None for the leading anonymous block
    raw_lines: list = field(default_factory=list)  # original lines incl. comments


# --------------------------------------------------------------------------- #
# Secret redaction and logging (Requirement 12)
# --------------------------------------------------------------------------- #


class SecretRedactor:
    """Substitute registered secret values with literal redaction strings.

    Values are registered once (at credential-load time) and every text routed
    through :class:`Logger`, every subprocess argv echo, and the installed
    ``sys.excepthook`` is scrubbed before it reaches any sink. Empty values are
    never registered so an empty secret can never blank-replace arbitrary text.
    """

    def __init__(self) -> None:
        # (raw_value, replacement) pairs, longest raw first so overlapping
        # values (e.g. a secret that contains the access key) are masked fully.
        self._tokens: list = []

    def register(self, value: Optional[str], label: str) -> None:
        """Register ``value`` to be replaced by ``<label redacted>``.

        No-op when ``value`` is falsy (empty or ``None``).
        """
        if not value:
            return
        replacement = f"<{label} redacted>"
        if (value, replacement) in self._tokens:
            return
        self._tokens.append((value, replacement))
        # Keep the longest raw values first.
        self._tokens.sort(key=lambda pair: len(pair[0]), reverse=True)

    def scrub(self, text: str) -> str:
        """Return ``text`` with every registered secret replaced."""
        if not text:
            return text
        for raw, replacement in self._tokens:
            if raw and raw in text:
                text = text.replace(raw, replacement)
        return text

    @property
    def registered_count(self) -> int:
        return len(self._tokens)


class Logger:
    """Single diagnostic sink (stderr) that scrubs every write (Requirement 12)."""

    def __init__(
        self,
        redactor: SecretRedactor,
        stream=None,
        verbose: bool = False,
    ) -> None:
        self.redactor = redactor
        self.stream = stream if stream is not None else sys.stderr
        self.verbose = verbose

    def raw(self, text: str) -> None:
        """Write pre-formatted ``text`` (scrubbed) to the stream."""
        self.stream.write(self.redactor.scrub(text))
        self.stream.flush()

    def error(self, message: str) -> None:
        self.raw(f"[ERROR] {message}\n")

    def warn(self, message: str) -> None:
        self.raw(f"[WARN] {message}\n")

    def info(self, message: str) -> None:
        self.raw(f"[INFO] {message}\n")

    def debug(self, message: str) -> None:
        if self.verbose:
            self.raw(f"[DEBUG] {message}\n")


class ProvisioningError(Exception):
    """Raised for a global, non-recoverable failure with an explicit exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def die(logger: Logger, message: str, code: int) -> "ProvisioningError":
    """Log ``message`` as an error and return a :class:`ProvisioningError`.

    The caller raises the returned exception so control flow is explicit at the
    call site (``raise die(log, ..., EXIT_X)``).
    """
    logger.error(message)
    return ProvisioningError(message, code)


def install_excepthook(logger: Logger) -> None:
    """Replace ``sys.excepthook`` so unhandled tracebacks are redacted (R12.4)."""

    def _hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logger.raw(text)

    sys.excepthook = _hook


def install_signal_handlers(logger: Logger, flush_callback) -> None:
    """Install SIGINT/SIGTERM handlers that flush a partial summary (R12.7).

    ``flush_callback`` is invoked with the :class:`Logger`; it must emit any
    in-progress Run_Summary through the (scrubbing) logger. After flushing the
    handler exits with a non-zero status.
    """

    def _handler(signum, frame) -> None:
        try:
            flush_callback(logger)
        finally:
            # Non-zero exit on signal per R12.7.
            raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


# --------------------------------------------------------------------------- #
# Identity gate (Requirement 1)
# --------------------------------------------------------------------------- #


class IdentityGate:
    """Refuse to run as anyone other than ``ec2-user`` (Requirement 1).

    Dependencies are injectable so the gate can be exercised in tests without
    actually being root.
    """

    @staticmethod
    def gate(logger: Logger, *, geteuid=None, getpwuid=None, environ=None) -> None:
        geteuid = geteuid or os.geteuid
        getpwuid = getpwuid or pwd.getpwuid
        environ = environ if environ is not None else os.environ

        euid = geteuid()
        euser = getpwuid(euid).pw_name
        sudo_user = environ.get("SUDO_USER", "")

        if euid == 0:
            if sudo_user != OPERATOR:
                raise die(
                    logger,
                    f"Operator must be {OPERATOR} "
                    f"(refusing root with SUDO_USER={sudo_user!r})",
                    EXIT_IDENTITY,
                )
        elif euser != OPERATOR:
            raise die(
                logger,
                f"Operator must be {OPERATOR} (running as {euser!r})",
                EXIT_IDENTITY,
            )
        # No filesystem read/write occurs before this point.


# --------------------------------------------------------------------------- #
# Configuration resolution (Requirement 13) and argument parsing (R10, R2)
# --------------------------------------------------------------------------- #


def _dequote(value: str) -> str:
    """Strip surrounding whitespace and a single matching pair of quotes."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value


def _resolve_param(cli_value, env_value, default_value):
    """Resolve one parameter with CLI > env (if non-empty) > default precedence."""
    if cli_value is not None:
        return cli_value, "cli"
    if env_value:
        return env_value, "env"
    return default_value, "default"


def _read_exclude_file(path: str, logger: Logger) -> set:
    """Read an exclusion-list file (Requirement 2.4, 2.5)."""
    if not os.path.isfile(path) or not os.access(path, os.R_OK):
        raise die(logger, f"--exclude-file path not readable: {path}", EXIT_CONFIG)
    out: set = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped[0] == "#":
                continue
            out.add(stripped)
    return out


class ConfigResolver:
    """Parse arguments and resolve runtime configuration (Requirements 2, 10, 13)."""

    @staticmethod
    def build_parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="provision-agentcore-creds.py",
            description=(
                "Provision per-user AWS credentials and Kiro MCP config for the "
                "agentcore-mcp-rag MCP server. Run as ec2-user."
            ),
        )
        parser.add_argument("--all", action="store_true", help="Bulk mode: provision every eligible user.")
        parser.add_argument("--user", metavar="NAME", help="Single-user mode: provision exactly NAME.")
        parser.add_argument("--exclude-file", metavar="PATH", help="Path to a newline-delimited exclusion list.")
        parser.add_argument("--verify", action="store_true", help="Run the AWS verification probe per user.")
        parser.add_argument("--verbose", action="store_true", help="Echo (redacted) probe output and debug logs.")
        parser.add_argument("--dry-run", action="store_true", help="Plan only; make no filesystem changes.")
        parser.add_argument("--format", choices=["table", "json"], default="table", help="Run_Summary output form.")
        parser.add_argument("--runtime-arn", metavar="ARN", help="AgentCore runtime ARN (else env/default).")
        parser.add_argument("--region", metavar="NAME", help="AWS region (else env/default).")
        parser.add_argument("--proxy-path", metavar="PATH", help="Absolute path to the MCP stdio proxy (else env/default).")
        return parser

    @staticmethod
    def resolve(
        args: argparse.Namespace,
        logger: Logger,
        *,
        environ=None,
        isfile=None,
        access=None,
        realpath=None,
    ) -> Config:
        environ = environ if environ is not None else os.environ
        isfile = isfile or os.path.isfile
        access = access or os.access
        realpath = realpath or os.path.realpath

        # Mode mutual-exclusion (Requirements 10.4, 10.5).
        if args.all and args.user:
            raise die(logger, "--all and --user are mutually exclusive", EXIT_ARG)
        if not args.all and not args.user:
            raise die(logger, "exactly one of --all or --user is required", EXIT_ARG)

        runtime_arn, arn_src = _resolve_param(
            args.runtime_arn, environ.get("AGENTCORE_RUNTIME_ARN"), DEFAULT_RUNTIME_ARN
        )
        region, region_src = _resolve_param(
            args.region, environ.get("AWS_REGION"), DEFAULT_REGION
        )
        proxy_path, proxy_src = _resolve_param(
            args.proxy_path, environ.get("AGENTCORE_PROXY_PATH"), DEFAULT_PROXY_PATH
        )

        if not ARN_RE.match(runtime_arn):
            raise die(
                logger,
                f"malformed AgentCore runtime ARN {runtime_arn!r} (resolved from {arn_src})",
                EXIT_CONFIG,
            )
        if not REGION_RE.match(region):
            raise die(
                logger,
                f"malformed AWS region {region!r} (resolved from {region_src})",
                EXIT_CONFIG,
            )

        resolved_proxy = realpath(proxy_path)
        if not isfile(resolved_proxy) or not access(resolved_proxy, os.R_OK):
            raise die(
                logger,
                f"proxy path not an existing readable file: {proxy_path!r} "
                f"(resolved to {resolved_proxy!r}, from {proxy_src})",
                EXIT_CONFIG,
            )

        exclusions: set = set()
        if args.exclude_file:
            exclusions = _read_exclude_file(args.exclude_file, logger)

        return Config(
            runtime_arn=runtime_arn,
            region=region,
            proxy_path=resolved_proxy,
            runtime_arn_source=arn_src,
            region_source=region_src,
            proxy_path_source=proxy_src,
            mode="single" if args.user else "bulk",
            target_user=args.user,
            exclusions=frozenset(exclusions),
            verify=args.verify,
            verbose=args.verbose,
            dry_run=args.dry_run,
            output_format=args.format,
        )


# --------------------------------------------------------------------------- #
# Source credential loading (Requirement 3)
# --------------------------------------------------------------------------- #


class CredentialsLoader:
    """Load the master IAM keys from the Source_Credentials_File (Requirement 3)."""

    @staticmethod
    def load(
        redactor: SecretRedactor,
        logger: Logger,
        *,
        path: str = SOURCE_CREDENTIALS_FILE,
        section: str = SOURCE_PROFILE_NAME,
    ) -> IamCreds:
        if not os.path.isfile(path) or not os.access(path, os.R_OK):
            raise die(logger, f"source credentials file not readable: {path}", EXIT_CREDS)

        parser = configparser.ConfigParser(
            interpolation=None, comment_prefixes=("#", ";")
        )
        try:
            with open(path, "r", encoding="utf-8") as fh:
                parser.read_file(fh)
        except (configparser.Error, OSError) as exc:
            # Do not include any credential value; the parse error text from
            # configparser references only structure, never our keys.
            raise die(
                logger,
                f"source credentials file could not be parsed: {path} ({exc.__class__.__name__})",
                EXIT_CREDS,
            )

        if not parser.has_section(section):
            raise die(
                logger,
                f"source credentials file {path} has no [{section}] section",
                EXIT_CREDS,
            )

        def _field(key: str, required: bool) -> Optional[str]:
            if not parser.has_option(section, key):
                if required:
                    raise die(
                        logger,
                        f"source credentials file {path} [{section}] is missing {key}",
                        EXIT_CREDS,
                    )
                return None
            value = _dequote(parser.get(section, key))
            if required and not value:
                raise die(
                    logger,
                    f"source credentials file {path} [{section}] has an empty {key}",
                    EXIT_CREDS,
                )
            return value or None

        access_key_id = _field("aws_access_key_id", required=True)
        secret_access_key = _field("aws_secret_access_key", required=True)
        session_token = _field("aws_session_token", required=False)

        # Register secrets with the redactor BEFORE returning so every later
        # log/print/raise is scrubbed (Requirement 3.4, 12.1).
        redactor.register(access_key_id, "aws_access_key_id")
        redactor.register(secret_access_key, "aws_secret_access_key")
        redactor.register(session_token, "aws_session_token")

        return IamCreds(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
        )


# --------------------------------------------------------------------------- #
# Eligibility predicate and user discovery (Requirements 2, 9)
# --------------------------------------------------------------------------- #


class Eligibility:
    """Pure eligibility predicate and single-user validation (Requirements 2, 9)."""

    @staticmethod
    def is_eligible(entry, exclusions: frozenset):
        """Return ``(eligible, reason)`` for an NSS passwd entry."""
        if entry.pw_uid < MIN_UID:
            return False, f"uid {entry.pw_uid} < {MIN_UID}"
        if entry.pw_shell in NOLOGIN_SHELLS:
            return False, f"non-interactive shell {entry.pw_shell}"
        if entry.pw_dir != f"/home/{entry.pw_name}":
            return False, f"home {entry.pw_dir} != /home/{entry.pw_name}"
        if entry.pw_name in BUILTIN_EXCLUSIONS or entry.pw_name in exclusions:
            return False, "excluded"
        return True, ""

    @staticmethod
    def check_or_die(
        name: str,
        exclusions: frozenset,
        logger: Logger,
        *,
        getpwnam=None,
    ) -> TargetUser:
        """Validate a single named user for Single_User_Mode (Requirement 9)."""
        getpwnam = getpwnam or pwd.getpwnam
        try:
            entry = getpwnam(name)
        except KeyError:
            raise die(logger, f"user {name!r} does not exist in the passwd database", EXIT_ARG)

        if name in BUILTIN_EXCLUSIONS or name in exclusions:
            raise die(
                logger,
                f"user {name!r} is excluded (ec2-user, root, or in the exclusion list)",
                EXIT_ARG,
            )
        if entry.pw_uid < MIN_UID:
            raise die(
                logger,
                f"user {name!r} has uid {entry.pw_uid} below the eligibility threshold {MIN_UID}",
                EXIT_ARG,
            )
        if entry.pw_shell in NOLOGIN_SHELLS:
            raise die(
                logger,
                f"user {name!r} has a non-interactive login shell {entry.pw_shell}",
                EXIT_ARG,
            )
        if entry.pw_dir != f"/home/{name}":
            raise die(
                logger,
                f"user {name!r} has home directory {entry.pw_dir} which is not /home/{name}",
                EXIT_ARG,
            )
        return TargetUser(name, entry.pw_uid, entry.pw_gid, entry.pw_dir, entry.pw_shell)


class UserDiscovery:
    """Enumerate the Eligible_User_Set from the NSS passwd database (Requirement 2)."""

    @staticmethod
    def eligible(
        exclusions: frozenset,
        logger: Logger,
        *,
        getpwall=None,
    ) -> list:
        getpwall = getpwall or pwd.getpwall
        out: list = []
        for entry in getpwall():
            ok, _reason = Eligibility.is_eligible(entry, exclusions)
            if ok:
                out.append(
                    TargetUser(
                        entry.pw_name,
                        entry.pw_uid,
                        entry.pw_gid,
                        entry.pw_dir,
                        entry.pw_shell,
                    )
                )
        # Ascending byte-wise (C-locale) order (Requirement 2.6, 10.2).
        out.sort(key=lambda u: u.name.encode("utf-8"))
        logger.info(
            "Eligible users (%d): %s"
            % (len(out), ", ".join(u.name for u in out) if out else "(none)")
        )
        return out


# --------------------------------------------------------------------------- #
# Privileged filesystem operations (design "Sudo strategy")
# --------------------------------------------------------------------------- #

#: Coreutils binaries (stable absolute paths on Amazon Linux 2023).
INSTALL_BIN = "/usr/bin/install"
CHMOD_BIN = "/usr/bin/chmod"
CHOWN_BIN = "/usr/bin/chown"

#: Embedded one-liners run under sudo. None contains a credential value; the
#: secret bytes travel only inside a staged file, never on a command line.
_INSPECT_PY = (
    "import os,sys,stat\n"
    "p=sys.argv[1]\n"
    "try:\n"
    "    ls=os.lstat(p)\n"
    "except FileNotFoundError:\n"
    "    print('absent');sys.exit(0)\n"
    "if stat.S_ISLNK(ls.st_mode):\n"
    "    k='symlink'\n"
    "elif stat.S_ISDIR(ls.st_mode):\n"
    "    k='dir'\n"
    "elif stat.S_ISREG(ls.st_mode):\n"
    "    k='file'\n"
    "else:\n"
    "    k='other'\n"
    "try:\n"
    "    s=os.stat(p)\n"
    "    print(k,s.st_uid,s.st_gid,s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)\n"
    "except OSError:\n"
    "    print(k,-1,-1,-1,-1,-1,-1)\n"
)

_READ_PY = (
    "import os,sys\n"
    "p=sys.argv[1]\n"
    "try:\n"
    "    f=open(p,'rb')\n"
    "except FileNotFoundError:\n"
    "    sys.exit(3)\n"
    "sys.stdout.buffer.write(f.read());f.close()\n"
)

_RENAME_PY = (
    "import os,sys\n"
    "s,d=sys.argv[1],sys.argv[2]\n"
    "os.rename(s,d)\n"
    "fd=os.open(os.path.dirname(d) or '.',os.O_RDONLY)\n"
    "try:\n"
    "    os.fsync(fd)\n"
    "finally:\n"
    "    os.close(fd)\n"
)


@dataclass
class StatInfo:
    """lstat kind plus a stat (follow) signature for a path."""

    kind: str  # absent | dir | file | symlink | other
    uid: int
    gid: int
    dev: int
    ino: int
    size: int
    mtime_ns: int

    @property
    def absent(self) -> bool:
        return self.kind == "absent"

    @property
    def signature(self):
        """Tuple used for concurrent-modification detection (Requirement 14.3)."""
        return (self.dev, self.ino, self.size, self.mtime_ns)


@dataclass
class RunResult:
    returncode: int
    timed_out: bool
    stdout: str
    stderr: str


class PrivilegedError(Exception):
    """Raised when a privileged (sudo) operation fails for one target."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class Privileged:
    """Abstract privileged-filesystem operations.

    The production implementation (:class:`SudoPrivileged`) escalates via
    ``sudo`` for every operation that touches a target user's home directory;
    the script process itself never opens another user's home from its own UID.
    Tests inject a fake/local implementation.
    """

    def inspect(self, path: str) -> StatInfo:  # pragma: no cover - interface
        raise NotImplementedError

    def read_bytes(self, path: str):  # pragma: no cover - interface
        raise NotImplementedError

    def ensure_dir(self, path: str, mode: int, uid: int, gid: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def reassert(self, path: str, mode: int, uid: int, gid: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def atomic_write(self, path: str, data: bytes, mode: int, uid: int, gid: int) -> None:  # pragma: no cover
        raise NotImplementedError

    def run_as(self, user: str, argv: list, env: dict, timeout: int) -> RunResult:  # pragma: no cover
        raise NotImplementedError


class SudoPrivileged(Privileged):
    """Production privileged operations via ``sudo -n`` subprocesses."""

    def __init__(self, python_bin: Optional[str] = None) -> None:
        self.python_bin = python_bin or sys.executable or "python3.12"

    @staticmethod
    def _mode(mode: int) -> str:
        return f"{mode:04o}"

    @staticmethod
    def _scrub_temp(text: str, *paths: str) -> str:
        for p in paths:
            if p:
                text = text.replace(p, "<temp redacted>")
        return text

    def _run(self, argv: list) -> RunResult:
        full = ["sudo", "-n", *argv]
        proc = subprocess.run(full, capture_output=True, text=True)
        return RunResult(proc.returncode, False, proc.stdout, proc.stderr)

    def inspect(self, path: str) -> StatInfo:
        res = self._run([self.python_bin, "-c", _INSPECT_PY, path])
        if res.returncode != 0:
            raise PrivilegedError(f"could not inspect {path} (rc={res.returncode})")
        line = res.stdout.strip()
        if line == "absent":
            return StatInfo("absent", -1, -1, -1, -1, -1, -1)
        parts = line.split()
        kind = parts[0]
        nums = [int(x) for x in parts[1:]]
        return StatInfo(kind, *nums)

    def read_bytes(self, path: str):
        full = ["sudo", "-n", self.python_bin, "-c", _READ_PY, path]
        proc = subprocess.run(full, capture_output=True)
        if proc.returncode == 3:
            return None
        if proc.returncode != 0:
            raise PrivilegedError(f"could not read {path} (rc={proc.returncode})")
        return proc.stdout

    def ensure_dir(self, path: str, mode: int, uid: int, gid: int) -> None:
        res = self._run(
            [INSTALL_BIN, "-d", "-m", self._mode(mode), "-o", str(uid), "-g", str(gid), path]
        )
        if res.returncode != 0:
            raise PrivilegedError(
                f"could not create/own directory {path} (rc={res.returncode}): {res.stderr.strip()}"
            )

    def reassert(self, path: str, mode: int, uid: int, gid: int) -> None:
        r1 = self._run([CHMOD_BIN, self._mode(mode), path])
        if r1.returncode != 0:
            raise PrivilegedError(f"could not chmod {path} (rc={r1.returncode})")
        r2 = self._run([CHOWN_BIN, f"{uid}:{gid}", path])
        if r2.returncode != 0:
            raise PrivilegedError(f"could not chown {path} (rc={r2.returncode})")

    def atomic_write(self, path: str, data: bytes, mode: int, uid: int, gid: int) -> None:
        staged = None
        dsttmp = f"{path}.tmp.{os.getpid()}"
        try:
            fd, staged = tempfile.mkstemp(prefix="provision-acreds-", dir="/tmp")
            os.write(fd, data)
            os.close(fd)
            os.chmod(staged, 0o600)
            r1 = self._run(
                [INSTALL_BIN, "-m", self._mode(mode), "-o", str(uid), "-g", str(gid), staged, dsttmp]
            )
            if r1.returncode != 0:
                raise PrivilegedError(
                    self._scrub_temp(
                        f"staging write failed for {path} (rc={r1.returncode}): {r1.stderr.strip()}",
                        staged,
                        dsttmp,
                    )
                )
            r2 = self._run([self.python_bin, "-c", _RENAME_PY, dsttmp, path])
            if r2.returncode != 0:
                raise PrivilegedError(
                    self._scrub_temp(
                        f"atomic rename failed for {path} (rc={r2.returncode}): {r2.stderr.strip()}",
                        staged,
                        dsttmp,
                    )
                )
        finally:
            if staged and os.path.exists(staged):
                try:
                    os.unlink(staged)
                except OSError:
                    pass

    def run_as(self, user: str, argv: list, env: dict, timeout: int) -> RunResult:
        env_pairs = [f"{k}={v}" for k, v in env.items()]
        full = ["sudo", "-n", "-u", user, "-H", "env", *env_pairs, *argv]
        try:
            proc = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            return RunResult(-1, True, exc.stdout or "", exc.stderr or "")
        return RunResult(proc.returncode, False, proc.stdout, proc.stderr)


# --------------------------------------------------------------------------- #
# AWS config / settings directory provisioning (Requirements 4, 6.1)
# --------------------------------------------------------------------------- #


class AwsConfigDir:
    """Ensure a per-user directory exists with mode 0700 and correct ownership."""

    def __init__(self, ops: Privileged, logger: Logger) -> None:
        self.ops = ops
        self.logger = logger

    def check_home(self, target: TargetUser) -> Optional[str]:
        """Validate the target's home directory (Requirement 4.6). Returns a
        failure reason or ``None`` when the home directory is acceptable."""
        info = self.ops.inspect(target.home)
        if info.absent:
            return f"home directory {target.home} does not exist"
        if info.kind != "dir":
            return f"home directory {target.home} is not a directory (is {info.kind})"
        if info.uid != target.uid:
            return (
                f"home directory {target.home} is owned by uid {info.uid}, "
                f"not the target uid {target.uid}"
            )
        return None

    def ensure(self, target: TargetUser, dir_path: str, dry_run: bool) -> Optional[str]:
        """Create/own ``dir_path`` at mode 0700 (Requirement 4.1-4.4). Returns a
        failure reason or ``None`` on success."""
        info = self.ops.inspect(dir_path)
        if info.kind in ("symlink", "file", "other"):
            return f"{dir_path} exists and is a {info.kind}, not a regular directory"
        if dry_run:
            return None
        self.ops.ensure_dir(dir_path, 0o700, target.uid, target.gid)
        return None


# --------------------------------------------------------------------------- #
# Credentials file writer -- section-aware INI editor (Requirements 5, 7, 14)
# --------------------------------------------------------------------------- #


def _tokenize_ini(text: str) -> list:
    """Split INI text into ordered :class:`Section` objects, preserving every
    line (comments and blanks) byte-for-byte."""
    sections: list = []
    current = Section(header=None, raw_lines=[])
    sections.append(current)
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            current = Section(header=stripped[1:-1], raw_lines=[line])
            sections.append(current)
        else:
            current.raw_lines.append(line)
    if sections and sections[0].header is None and not sections[0].raw_lines:
        sections.pop(0)
    return sections


def _serialize_ini(sections: list) -> str:
    return "".join(line for sec in sections for line in sec.raw_lines)


def _agentcore_lines(access: str, secret: str) -> list:
    return [
        f"[{AWS_PROFILE_NAME}]\n",
        f"aws_access_key_id = {access}\n",
        f"aws_secret_access_key = {secret}\n",
    ]


def _parse_section_fields(section: Section) -> dict:
    fields: dict = {}
    for line in section.raw_lines[1:]:  # skip the header line
        stripped = line.strip()
        if not stripped or stripped[0] in "#;":
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            fields[key.strip().lower()] = _dequote(value)
    return fields


def _render_creds(old_text: str, access: str, secret: str) -> str:
    """Return the credentials text with exactly one ``[agentcore-rag]`` section
    set to the two managed fields, all other content preserved (R5)."""
    sections = _tokenize_ini(old_text)
    new_lines = _agentcore_lines(access, secret)
    idxs = [i for i, sec in enumerate(sections) if sec.header == AWS_PROFILE_NAME]
    if idxs:
        sections[idxs[0]].raw_lines = new_lines
        for i in reversed(idxs[1:]):  # collapse any pathological duplicates
            del sections[i]
    else:
        text_so_far = _serialize_ini(sections)
        prefix = ["\n"] if (text_so_far and not text_so_far.endswith("\n")) else []
        sections.append(Section(AWS_PROFILE_NAME, prefix + new_lines))
    return _serialize_ini(sections)


def _creds_satisfied(old_text: str, access: str, secret: str) -> bool:
    """True when an ``[agentcore-rag]`` section already holds the two managed
    field values byte-equal to ``access`` / ``secret`` (Requirement 7.1)."""
    for sec in _tokenize_ini(old_text):
        if sec.header == AWS_PROFILE_NAME:
            fields = _parse_section_fields(sec)
            return (
                fields.get("aws_access_key_id") == access
                and fields.get("aws_secret_access_key") == secret
            )
    return False


class AwsCredsWriter:
    """Write the ``[agentcore-rag]`` profile into ``~/.aws/credentials`` (R5, R7, R14)."""

    def __init__(self, ops: Privileged, logger: Logger) -> None:
        self.ops = ops
        self.logger = logger

    def write(self, target: TargetUser, creds: IamCreds, dry_run: bool) -> FileChange:
        path = f"{target.home}/.aws/credentials"
        info = self.ops.inspect(path)
        existed = not info.absent
        if existed and info.kind != "file":
            return FileChange(path, "failed", f"{path} exists and is a {info.kind}, not a file")
        sig_before = info.signature
        old = self.ops.read_bytes(path) if existed else None
        existed = old is not None
        old_text = old.decode("utf-8", errors="surrogateescape") if existed else ""

        if existed and _creds_satisfied(old_text, creds.access_key_id, creds.secret_access_key):
            if not dry_run:
                self.ops.reassert(path, 0o600, target.uid, target.gid)
            return FileChange(path, "skipped", profile=AWS_PROFILE_NAME)

        new_text = _render_creds(old_text, creds.access_key_id, creds.secret_access_key)
        new_bytes = new_text.encode("utf-8", errors="surrogateescape")

        if existed and new_bytes == old:
            if not dry_run:
                self.ops.reassert(path, 0o600, target.uid, target.gid)
            return FileChange(path, "skipped", profile=AWS_PROFILE_NAME)

        disposition: Disposition = "created" if not existed else "updated"
        if dry_run:
            return FileChange(path, disposition, profile=AWS_PROFILE_NAME)

        if existed and self.ops.inspect(path).signature != sig_before:
            return FileChange(path, "failed", "concurrent modification detected")

        self.ops.atomic_write(path, new_bytes, 0o600, target.uid, target.gid)
        return FileChange(path, disposition, profile=AWS_PROFILE_NAME)


# --------------------------------------------------------------------------- #
# MCP config file writer -- order-preserving JSON editor (Requirements 6, 7, 14)
# --------------------------------------------------------------------------- #


def _render_mcp(old_text: Optional[str], cfg: Config) -> str:
    """Return mcp.json text with the four Managed_Keys set on the
    ``agentcore-mcp-rag`` entry; all other content/order preserved (R6)."""
    obj = json.loads(old_text) if old_text is not None else {}

    servers = obj.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
        obj["mcpServers"] = servers

    entry = servers.get(MCP_SERVER_KEY)
    if not isinstance(entry, dict):
        entry = {}
        servers[MCP_SERVER_KEY] = entry

    entry["command"] = MCP_COMMAND
    entry["args"] = [cfg.proxy_path, "--runtime-id", cfg.runtime_arn]

    env = entry.get("env")
    if not isinstance(env, dict):
        env = {}
        entry["env"] = env
    env["AWS_REGION"] = cfg.region
    env["AWS_PROFILE"] = AWS_PROFILE_NAME

    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def _mcp_satisfied(obj, cfg: Config) -> bool:
    """True when the parsed mcp.json already holds all four Managed_Keys equal
    (structurally) to what would be written (Requirement 7.2)."""
    if not isinstance(obj, dict):
        return False
    servers = obj.get("mcpServers")
    if not isinstance(servers, dict):
        return False
    entry = servers.get(MCP_SERVER_KEY)
    if not isinstance(entry, dict):
        return False
    if entry.get("command") != MCP_COMMAND:
        return False
    if entry.get("args") != [cfg.proxy_path, "--runtime-id", cfg.runtime_arn]:
        return False
    env = entry.get("env")
    if not isinstance(env, dict):
        return False
    if env.get("AWS_REGION") != cfg.region:
        return False
    if env.get("AWS_PROFILE") != AWS_PROFILE_NAME:
        return False
    return True


class McpConfigWriter:
    """Write the ``agentcore-mcp-rag`` server entry into mcp.json (R6, R7, R14)."""

    def __init__(self, ops: Privileged, logger: Logger) -> None:
        self.ops = ops
        self.logger = logger

    def write(self, target: TargetUser, cfg: Config, dry_run: bool) -> FileChange:
        path = f"{target.home}/.kiro/settings/mcp.json"
        info = self.ops.inspect(path)
        existed = not info.absent
        if existed and info.kind != "file":
            return FileChange(path, "failed", f"{path} exists and is a {info.kind}, not a file")
        sig_before = info.signature
        old = self.ops.read_bytes(path) if existed else None
        existed = old is not None
        old_text = old.decode("utf-8") if existed else None

        old_obj = None
        if old_text is not None:
            try:
                old_obj = json.loads(old_text)
            except json.JSONDecodeError:
                return FileChange(path, "failed", "existing mcp.json is not valid JSON")
            if not isinstance(old_obj, dict):
                return FileChange(path, "failed", "existing mcp.json top-level is not a JSON object")
            if "mcpServers" in old_obj and not isinstance(old_obj["mcpServers"], dict):
                return FileChange(path, "failed", "existing mcp.json mcpServers is not a JSON object")

        if old_obj is not None and _mcp_satisfied(old_obj, cfg):
            if not dry_run:
                self.ops.reassert(path, 0o600, target.uid, target.gid)
            return FileChange(path, "skipped", profile=AWS_PROFILE_NAME)

        new_text = _render_mcp(old_text, cfg)
        new_bytes = new_text.encode("utf-8")

        if existed and old is not None and new_bytes == old:
            if not dry_run:
                self.ops.reassert(path, 0o600, target.uid, target.gid)
            return FileChange(path, "skipped", profile=AWS_PROFILE_NAME)

        disposition: Disposition = "created" if not existed else "updated"
        if dry_run:
            return FileChange(path, disposition, profile=AWS_PROFILE_NAME)

        if existed and self.ops.inspect(path).signature != sig_before:
            return FileChange(path, "failed", "concurrent modification detected")

        self.ops.atomic_write(path, new_bytes, 0o600, target.uid, target.gid)
        return FileChange(path, disposition, profile=AWS_PROFILE_NAME)


# --------------------------------------------------------------------------- #
# Cross-file invariant and verification probe (Requirements 8, 14)
# --------------------------------------------------------------------------- #


class Idempotency:
    """Cross-file profile-name invariant check (Requirements 14.1, 14.2)."""

    @staticmethod
    def cross_file_check(creds_profile: str, mcp_profile: str) -> Optional[str]:
        """Return a failure reason if the credentials profile-section name and
        the mcp.json ``AWS_PROFILE`` value disagree, else ``None``."""
        c = (creds_profile or "").strip()
        m = (mcp_profile or "").strip()
        if c != m:
            return f"cross-file profile name mismatch: credentials [{c}] vs mcp AWS_PROFILE {m!r}"
        if c != AWS_PROFILE_NAME:
            return f"profile name {c!r} is not the required {AWS_PROFILE_NAME!r}"
        return None


class VerificationProbe:
    """Run the AWS Verification_Probe under each target user (Requirement 8)."""

    def __init__(self, ops: Privileged, logger: Logger) -> None:
        self.ops = ops
        self.logger = logger

    def verify(self, target: TargetUser, cfg: Config) -> Optional[str]:
        """Return a failure reason string, or ``None`` if both probes pass."""
        env = {
            "AWS_PROFILE": AWS_PROFILE_NAME,
            "AWS_REGION": cfg.region,
            "HOME": target.home,
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        }
        checks = [
            (["aws", "sts", "get-caller-identity"], "sts"),
            (
                ["aws", "bedrock-agentcore-control", "list-agent-runtimes", "--region", cfg.region],
                "agentcore",
            ),
        ]
        for argv, label in checks:
            res = self.ops.run_as(target.name, argv, env, PROBE_TIMEOUT)
            if res.timed_out:
                return f"{label} timeout after {PROBE_TIMEOUT}s"
            if res.returncode != 0:
                return f"{label} exit {res.returncode}"
            if cfg.verbose and res.stdout:
                # Routed through the (scrubbing) logger per R8.5 / R12.
                self.logger.debug(f"[{target.name}] {label}: {res.stdout.strip()}")
        return None


# --------------------------------------------------------------------------- #
# Per-user provisioning driver (Requirements 4-7, 14)
# --------------------------------------------------------------------------- #

#: Disposition precedence: failed > created > updated > skipped (Requirement 7.4).
_DISPOSITION_RANK = {"skipped": 0, "updated": 1, "created": 2, "failed": 3}


def _merge_disposition(a: str, b: str) -> str:
    return a if _DISPOSITION_RANK[a] >= _DISPOSITION_RANK[b] else b


class UserProvisioner:
    """Drive provisioning for a single Target_User (design "UserProvisioner")."""

    def __init__(self, ops: Privileged, logger: Logger, cfg: Config) -> None:
        self.ops = ops
        self.logger = logger
        self.cfg = cfg
        self.config_dir = AwsConfigDir(ops, logger)
        self.creds_writer = AwsCredsWriter(ops, logger)
        self.mcp_writer = McpConfigWriter(ops, logger)

    def provision(self, target: TargetUser, creds: IamCreds) -> RunRecord:
        dry = self.cfg.dry_run

        # Home directory validity (Requirement 4.6).
        reason = self.config_dir.check_home(target)
        if reason:
            return RunRecord(target.name, "failed", reason)

        # All ~/.aws/ directory operations complete before the creds write (R4.5).
        reason = self.config_dir.ensure(target, f"{target.home}/.aws", dry)
        if reason:
            return RunRecord(target.name, "failed", reason)

        creds_fc = self.creds_writer.write(target, creds, dry)
        if creds_fc.disposition == "failed":
            return RunRecord(target.name, "failed", creds_fc.reason)

        # ~/.kiro/settings/ directory (Requirement 6.1).
        reason = self.config_dir.ensure(target, f"{target.home}/.kiro/settings", dry)
        if reason:
            return RunRecord(target.name, "failed", reason)

        mcp_fc = self.mcp_writer.write(target, self.cfg, dry)
        if mcp_fc.disposition == "failed":
            return RunRecord(target.name, "failed", mcp_fc.reason)

        # Cross-file profile-name invariant (Requirements 14.1, 14.2).
        xreason = Idempotency.cross_file_check(creds_fc.profile, mcp_fc.profile)
        if xreason:
            return RunRecord(target.name, "failed", xreason)

        disposition = _merge_disposition(creds_fc.disposition, mcp_fc.disposition)
        return RunRecord(target.name, disposition)


# --------------------------------------------------------------------------- #
# Run summary and exit-code mapping (Requirement 11)
# --------------------------------------------------------------------------- #


class RunSummary:
    """Collect :class:`RunRecord` instances; render table or JSON (Requirement 11)."""

    def __init__(self, records: list, output_format: str = "table") -> None:
        self.records = records
        self.output_format = output_format

    @staticmethod
    def _truncate(reason: str) -> str:
        if len(reason) <= MAX_REASON_LEN:
            return reason
        return reason[: MAX_REASON_LEN - 3] + "..."

    def aggregate(self) -> dict:
        counts = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
        for record in self.records:
            counts[record.disposition] += 1
        return counts

    def exit_code(self) -> int:
        if any(r.disposition == "failed" for r in self.records):
            return EXIT_FAILED
        return EXIT_OK

    def _render_table(self) -> str:
        name_width = max([len("USER")] + [len(r.user) for r in self.records] + [20])
        out = ["agentcore-creds-provisioning summary", "=" * 36]
        out.append(f"{'USER':<{name_width}}  {'DISPOSITION':<11}  REASON")
        for record in self.records:
            row = (
                f"{record.user:<{name_width}}  "
                f"{record.disposition:<11}  "
                f"{self._truncate(record.reason)}"
            )
            out.append(row.rstrip())
        counts = self.aggregate()
        out.append("")
        out.append(
            "aggregate: created=%d updated=%d skipped=%d failed=%d"
            % (counts["created"], counts["updated"], counts["skipped"], counts["failed"])
        )
        out.append(f"exit: {self.exit_code()}")
        return "\n".join(out) + "\n"

    def _render_json(self) -> str:
        obj = {
            "version": 1,
            "users": [
                {"name": r.user, "disposition": r.disposition, "reason": self._truncate(r.reason)}
                for r in self.records
            ],
            "aggregate": self.aggregate(),
            "exit_code": self.exit_code(),
        }
        return json.dumps(obj, indent=2) + "\n"

    def render(self) -> str:
        if self.output_format == "json":
            return self._render_json()
        return self._render_table()


# --------------------------------------------------------------------------- #
# Main dispatch (Requirements 9, 10)
# --------------------------------------------------------------------------- #


def main(
    argv: list,
    *,
    ops: Optional[Privileged] = None,
    redactor: Optional[SecretRedactor] = None,
    stdout=None,
    stderr=None,
    environ=None,
    geteuid=None,
    getpwuid=None,
    getpwall=None,
    getpwnam=None,
    source_path: Optional[str] = None,
) -> int:
    """Entry point. Returns a process exit code (design "Exit codes").

    The keyword-only seams (``ops``, ``getpwall`` ...) allow the full flow to be
    exercised in tests without root or ``sudo``; in production all default to
    the real implementations.
    """
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr
    environ = environ if environ is not None else os.environ
    source_path = source_path or SOURCE_CREDENTIALS_FILE
    redactor = redactor if redactor is not None else SecretRedactor()

    parser = ConfigResolver.build_parser()
    args = parser.parse_args(argv)  # SystemExit(2) on a usage error == EXIT_ARG

    logger = Logger(redactor, stream=stderr, verbose=args.verbose)
    records: list = []

    # Only mutate global excepthook/signal state for a real CLI run (ops is
    # None). Tests inject ops and exercise those installers directly.
    if ops is None:
        install_excepthook(logger)
        install_signal_handlers(
            logger, lambda lg: lg.raw(RunSummary(records, args.format).render())
        )

    try:
        IdentityGate.gate(logger, geteuid=geteuid, getpwuid=getpwuid, environ=environ)
        cfg = ConfigResolver.resolve(args, logger, environ=environ)
        creds = CredentialsLoader.load(redactor, logger, path=source_path)

        privileged = ops if ops is not None else SudoPrivileged()
        provisioner = UserProvisioner(privileged, logger, cfg)
        probe = VerificationProbe(privileged, logger)

        if cfg.mode == "single":
            targets = [Eligibility.check_or_die(cfg.target_user, cfg.exclusions, logger, getpwnam=getpwnam)]
        else:
            targets = UserDiscovery.eligible(cfg.exclusions, logger, getpwall=getpwall)

        for target in targets:
            record = provisioner.provision(target, creds)
            if cfg.verify and record.disposition != "failed":
                vreason = probe.verify(target, cfg)
                if vreason:
                    record.disposition = "failed"
                    record.reason = vreason
            records.append(record)

        summary = RunSummary(records, cfg.output_format)
        stdout.write(summary.render())
        return summary.exit_code()
    except ProvisioningError as exc:
        return exc.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
