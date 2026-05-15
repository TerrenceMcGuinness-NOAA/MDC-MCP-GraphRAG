#!/usr/bin/env python3
"""AgentCore Kiro Proxy — stdio MCP bridge to AWS Bedrock AgentCore Runtime.

Reads JSON-RPC messages from stdin, forwards them to the AgentCore Runtime
via boto3 invoke_agent_runtime, parses SSE responses, and writes JSON-RPC
results to stdout. All diagnostics go to stderr.

Usage:
  python3 tools/agentcore-kiro-proxy.py --runtime-id mdc_mcp_rag_server-TMXDllG2Wi
  python3 tools/agentcore-kiro-proxy.py --runtime-id ID --region us-east-1 --verbose

Configuration (Kiro mcp.json):
  {
    "mcpServers": {
      "agentcore-mcp-rag": {
        "type": "command",
        "command": "python3",
        "args": ["tools/agentcore-kiro-proxy.py", "--runtime-id", "RUNTIME_ID"],
        "env": {"AWS_REGION": "us-east-1"}
      }
    }
  }

Arguments:
  --runtime-id ID   AgentCore Runtime ID (or env AGENTCORE_RUNTIME_ID)
  --region REGION   AWS region (default: us-east-1, or env AWS_REGION)
  --verbose         Enable DEBUG logging (or env LOG_LEVEL=DEBUG)

Troubleshooting:
  - "AWS credentials not found" — ensure IAM role is attached to the EC2
    instance, or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.
  - "ThrottlingException" — proxy retries 3x automatically; if persistent,
    check AgentCore Runtime quotas.
  - "Session expired" — proxy auto-recovers with a new session ID.
  - No output — check stderr for diagnostics (Kiro captures stderr).
  - Run with --verbose to see per-request method names and response times.

Requirements: Python 3.9+, boto3 (no other dependencies).
"""

__version__ = "1.1.0"

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
import uuid

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

logger = logging.getLogger("agentcore-kiro-proxy")

# Retry configuration
RETRYABLE_EXCEPTIONS = (
    "ThrottlingException",
    "ServiceUnavailableException",
    "InternalServerException",
    "RequestTimeoutException",
)
MAX_RETRIES = 3
BASE_DELAY = 0.5

# Keepalive interval (seconds) — prevents AgentCore cold starts
KEEPALIVE_INTERVAL = 45

# Shutdown flag
_shutdown = False


def generate_session_id():
    """Generate a unique session ID (43 chars, exceeds 33 minimum)."""
    return f"kiro-proxy-{uuid.uuid4().hex}"


def make_error_response(request_id, code, message, data=None):
    """Construct a JSON-RPC error response."""
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def parse_args(argv=None):
    """Parse CLI arguments with env var fallbacks."""
    parser = argparse.ArgumentParser(description="AgentCore Kiro Proxy")
    parser.add_argument(
        "--runtime-id",
        default=os.environ.get("AGENTCORE_RUNTIME_ID"),
        help="AgentCore Runtime ID (env: AGENTCORE_RUNTIME_ID)",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS region (default: us-east-1, env: AWS_REGION)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=os.environ.get("LOG_LEVEL", "").upper() == "DEBUG",
        help="Enable debug logging (env: LOG_LEVEL=DEBUG)",
    )
    args = parser.parse_args(argv)
    if not args.runtime_id:
        parser.error("--runtime-id is required (or set AGENTCORE_RUNTIME_ID)")
    return args


def configure_logging(verbose=False):
    """Configure logging to stderr only."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)


# -- StdinReader --

def read_message():
    """Read one JSON-RPC message from stdin. Returns None on EOF."""
    while True:
        try:
            line = sys.stdin.readline()
        except (IOError, OSError):
            return None
        if not line:
            return None
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            logger.warning("Malformed JSON on stdin, skipping: %s", exc)
            continue


# -- AgentCoreClient --

class AgentCoreClient:
    """Manages communication with AgentCore Runtime via boto3."""

    def __init__(self, agent_runtime_id, region, session_id):
        from botocore.config import Config
        self.client = boto3.client(
            "bedrock-agentcore",
            region_name=region,
            config=Config(read_timeout=300, connect_timeout=10, retries={"max_attempts": 0}),
        )
        self.agent_runtime_id = agent_runtime_id
        self.session_id = session_id

    def invoke(self, payload):
        """Send JSON-RPC payload to AgentCore, return raw SSE response body.

        Retries up to 3 times on transient errors with exponential backoff.
        Regenerates session ID on session-expired errors.
        """
        last_exc = None
        for attempt in range(1 + MAX_RETRIES):
            try:
                return self._call(payload)
            except ClientError as exc:
                error_code = exc.response["Error"]["Code"]
                # Session expired — regenerate and retry once
                if "session" in error_code.lower() or "session" in str(exc).lower():
                    old = self.session_id
                    self.session_id = generate_session_id()
                    logger.warning(
                        "Session expired (%s), new session: %s", old, self.session_id
                    )
                    return self._call(payload)
                if error_code in RETRYABLE_EXCEPTIONS and attempt < MAX_RETRIES:
                    delay = BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Retryable error %s (attempt %d/%d), retrying in %.1fs",
                        error_code, attempt + 1, 1 + MAX_RETRIES, delay,
                    )
                    time.sleep(delay)
                    last_exc = exc
                    continue
                raise
        raise last_exc

    def _call(self, payload):
        """Execute a single invoke_agent_runtime call."""
        logger.debug(
            "Invoking AgentCore: method=%s id=%s session=%s",
            payload.get("method"), payload.get("id"), self.session_id,
        )
        t0 = time.monotonic()
        response = self.client.invoke_agent_runtime(
            agentRuntimeArn=self.agent_runtime_id,
            runtimeSessionId=self.session_id,
            contentType="application/json",
            accept="application/json, text/event-stream",
            payload=json.dumps(payload).encode("utf-8"),
            qualifier="DEFAULT",
        )
        body = response["response"].read().decode("utf-8")
        elapsed = time.monotonic() - t0
        logger.debug("Response received in %.3fs", elapsed)
        return body

    def stop_session(self):
        """Stop the AgentCore runtime session to release the microVM.

        Phase 56 fix: without this, every Kiro restart/disconnect leaves a
        live AgentCore microVM for the full 900s idle timeout, each holding
        Neptune Bolt connections and OpenSearch HTTPS sockets. Under
        reconnect storms these accumulate toward the 1000-connection limit.

        Safe to call repeatedly or when no session has been opened — errors
        are logged but do not propagate.
        """
        try:
            self.client.stop_runtime_session(
                agentRuntimeArn=self.agent_runtime_id,
                runtimeSessionId=self.session_id,
                qualifier="DEFAULT",
            )
            logger.info("AgentCore session stopped: %s", self.session_id)
        except Exception as exc:
            logger.warning("stop_runtime_session failed: %s", exc)


# -- SSEParser --

def parse_sse(raw_body):
    """Parse SSE frames and extract JSON-RPC payloads.

    SSE format: event: message\\ndata: {json}\\n\\n
    Returns list of parsed JSON-RPC response dicts.
    """
    results = []
    frames = raw_body.split("\n\n")
    for frame in frames:
        frame = frame.strip()
        if not frame:
            continue
        data_lines = []
        for line in frame.split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif line.startswith("event:"):
                continue
            elif data_lines:
                # Continuation line for multi-line data
                data_lines.append(line.strip())
        if not data_lines:
            continue
        data_str = "".join(data_lines)
        try:
            results.append(json.loads(data_str))
        except json.JSONDecodeError:
            logger.error("Malformed JSON in SSE frame: %s", frame)
            results.append(
                make_error_response(None, -32603, "Malformed SSE data", {"raw": frame})
            )
    return results


# -- Signal handling --

def _signal_handler(signum, _frame):
    """Set shutdown flag on SIGTERM/SIGINT."""
    global _shutdown
    _shutdown = True
    sig_name = signal.Signals(signum).name
    logger.info("Received %s, shutting down", sig_name)


def install_signal_handlers():
    """Register SIGTERM and SIGINT handlers."""
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)


# -- Main loop --

def write_response(obj):
    """Write a JSON-RPC response to stdout, one line, flushed."""
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


# -- Local initialize --

# Cached server capabilities from the first successful remote initialize
_server_info_cache = None
_server_info_lock = threading.Lock()

# Default capabilities to return immediately while warming up
_DEFAULT_SERVER_INFO = {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
    "serverInfo": {"name": "agentcore-kiro-proxy", "version": __version__},
}


def handle_initialize_locally(request_id):
    """Answer initialize immediately with cached or default server info."""
    with _server_info_lock:
        info = _server_info_cache if _server_info_cache else _DEFAULT_SERVER_INFO
    write_response({"jsonrpc": "2.0", "id": request_id, "result": info})


def warm_remote(client):
    """Send initialize to AgentCore in background to warm the container.

    Caches the real server info for future initialize calls.
    """
    global _server_info_cache
    try:
        warmup_msg = {
            "jsonrpc": "2.0", "method": "initialize", "id": str(uuid.uuid4()),
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "agentcore-kiro-proxy-warmup", "version": __version__},
            },
        }
        raw = client.invoke(warmup_msg)
        responses = parse_sse(raw)
        if responses and "result" in responses[0]:
            with _server_info_lock:
                _server_info_cache = responses[0]["result"]
            logger.info("Remote warmup complete, cached server info")
        else:
            logger.warning("Remote warmup got unexpected response")
    except Exception as exc:
        logger.warning("Remote warmup failed (non-fatal): %s", exc)


# -- Keepalive --

def keepalive_loop(client):
    """Periodically ping AgentCore to keep the container warm."""
    while not _shutdown:
        time.sleep(KEEPALIVE_INTERVAL)
        if _shutdown:
            break
        try:
            ping = {
                "jsonrpc": "2.0", "method": "ping", "id": str(uuid.uuid4()),
            }
            client.invoke(ping)
            logger.debug("Keepalive ping sent")
        except Exception as exc:
            logger.debug("Keepalive ping failed (non-fatal): %s", exc)


def main(argv=None):
    """Entry point: parse args, create components, run message loop."""
    args = parse_args(argv)
    configure_logging(args.verbose)
    install_signal_handlers()

    session_id = generate_session_id()
    logger.info(
        "AgentCore Kiro Proxy v%s starting — runtime=%s region=%s session=%s",
        __version__, args.runtime_id, args.region, session_id,
    )

    try:
        client = AgentCoreClient(args.runtime_id, args.region, session_id)
    except NoCredentialsError:
        logger.error(
            "AWS credentials not found. Ensure IAM role is attached or "
            "AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY are set."
        )
        return 1

    # Start background warmup immediately so AgentCore is hot by the time
    # Kiro sends tools/list (which must arrive within 60s).
    warmup_thread = threading.Thread(target=warm_remote, args=(client,), daemon=True)
    warmup_thread.start()

    # Start keepalive thread to prevent cold starts between calls
    keepalive_thread = threading.Thread(target=keepalive_loop, args=(client,), daemon=True)
    keepalive_thread.start()

    exit_code = 0
    try:
        while not _shutdown:
            msg = read_message()
            if msg is None:
                logger.info("EOF on stdin, shutting down (session=%s)", client.session_id)
                break

            request_id = msg.get("id")
            method = msg.get("method", "")
            is_notification = request_id is None

            # Handle initialize locally for instant response
            if method == "initialize":
                handle_initialize_locally(request_id)
                continue

            # Skip notifications that don't need forwarding
            if method == "notifications/initialized":
                continue

            try:
                raw_sse = client.invoke(msg)
                responses = parse_sse(raw_sse)
                if is_notification:
                    # Notifications don't expect a response to Kiro, but log if
                    # AgentCore sent something back.
                    if responses:
                        logger.debug("AgentCore replied to notification: %s", msg.get("method"))
                    continue
                for resp in responses:
                    write_response(resp)
                if not responses and not is_notification:
                    write_response(
                        make_error_response(request_id, -32603, "Empty SSE response")
                    )
            except NoCredentialsError:
                logger.error("AWS credentials lost during operation")
                if not is_notification:
                    write_response(
                        make_error_response(request_id, -32603, "AWS credentials not available")
                    )
            except ClientError as exc:
                logger.error("AgentCore invocation failed: %s", exc)
                if not is_notification:
                    error_code = exc.response["Error"]["Code"]
                    write_response(
                        make_error_response(
                            request_id, -32603,
                            f"AgentCore invocation failed after {MAX_RETRIES} retries",
                            {"exception": error_code, "detail": str(exc)},
                        )
                    )
            except Exception as exc:
                logger.exception("Unhandled exception processing message")
                if not is_notification:
                    write_response(
                        make_error_response(
                            request_id, -32603, f"Internal proxy error: {exc}"
                        )
                    )
    finally:
        # Phase 56 fix: always release the AgentCore microVM session on exit
        # so the proxy does not leak live microVMs (each holding Neptune +
        # OpenSearch connections) for the full 900s idle timeout on every
        # Kiro restart / disconnect.
        client.stop_session()

    logger.info("Proxy exiting (code=%d, session=%s)", exit_code, client.session_id)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
