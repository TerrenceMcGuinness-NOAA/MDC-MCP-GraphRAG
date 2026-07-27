"""Unit tests for the Token_Broker handler (design §4, R3.6/R3.10/R3.11/R9.10).

Run: python3 -m unittest infrastructure/cdk/lambda/token_broker/test_index.py
Requires boto3 importable (patched here so no AWS calls are made).
"""

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

# Configure env + stub boto3 BEFORE importing the handler module.
os.environ["ALLOWED_SUB_PATTERNS_JSON"] = json.dumps(
    ["^repo:NOAA-EMC/global-workflow:ref:refs/heads/.*$"]
)
os.environ["COGNITO_TOKEN_ENDPOINT"] = "https://example.auth.us-east-1.amazoncognito.com/oauth2/token"
os.environ["CI_CLIENT_SECRET_ARN"] = "arn:aws:secretsmanager:us-east-1:903050880929:secret:mdc-mcp-external-access-alt/ci-app-client-abc"

_fake_secrets = mock.MagicMock()
_fake_secrets.get_secret_value.return_value = {
    "SecretString": json.dumps({"client_id": "ci123", "client_secret": "shh"})
}
_boto3 = mock.MagicMock()
_boto3.client.return_value = _fake_secrets
sys.modules["boto3"] = _boto3

sys.path.insert(0, os.path.dirname(__file__))
import index  # noqa: E402


class _Ctx:
    aws_request_id = "req-abc-123"


class TokenBrokerTests(unittest.TestCase):
    def _run(self, event):
        buf = io.StringIO()
        with redirect_stdout(buf):
            resp = index.handler(event, _Ctx())
        return resp, buf.getvalue()

    def test_happy_path_returns_token_and_request_id(self):
        with mock.patch.object(index.urllib.request, "urlopen") as m:
            m.return_value.__enter__.return_value.read.return_value = json.dumps(
                {"access_token": "JWT", "expires_in": 3600, "token_type": "Bearer"}
            ).encode()
            resp, logs = self._run(
                {"github_claims": {"sub": "repo:NOAA-EMC/global-workflow:ref:refs/heads/main",
                                   "run_id": "42", "repository": "NOAA-EMC/global-workflow",
                                   "ref": "refs/heads/main"}}
            )
        self.assertEqual(resp["statusCode"], 200)
        body = json.loads(resp["body"])
        self.assertEqual(body["access_token"], "JWT")
        self.assertEqual(body["request_id"], "req-abc-123")
        # R3.6/R13.3: attribution line present, keyed by request_id, token NEVER logged.
        self.assertIn('"event": "token_issued"', logs)
        self.assertIn('"request_id": "req-abc-123"', logs)
        self.assertNotIn("JWT", logs)

    def test_forbidden_repository_never_calls_cognito(self):
        with mock.patch.object(index.urllib.request, "urlopen") as m:
            resp, logs = self._run(
                {"github_claims": {"sub": "repo:attacker/fork:ref:refs/heads/main",
                                   "run_id": "1", "repository": "attacker/fork", "ref": "refs/heads/main"}}
            )
            m.assert_not_called()  # R3.10 — no Cognito call on allowlist miss
        self.assertEqual(resp["statusCode"], 403)
        self.assertIn('"event": "forbidden_repository"', logs)

    def test_upstream_failure_returns_502_no_token(self):
        with mock.patch.object(index.urllib.request, "urlopen", side_effect=OSError("boom")):
            resp, logs = self._run(
                {"github_claims": {"sub": "repo:NOAA-EMC/global-workflow:ref:refs/heads/main"}}
            )
        self.assertEqual(resp["statusCode"], 502)
        body = json.loads(resp["body"])
        self.assertNotIn("access_token", body)
        self.assertIn('"event": "upstream_failure"', logs)

    def test_no_dynamodb_client_instantiated(self):
        # AD-3/R9.10 — handler only ever creates a secretsmanager client.
        for call in _boto3.client.call_args_list:
            self.assertNotIn("dynamodb", [str(a).lower() for a in call.args])


if __name__ == "__main__":
    unittest.main()
