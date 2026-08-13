# Developer AWS Credentials Setup

**Purpose**: Configure your AWS CLI credentials on the EIB development instance
so that the MCP proxy (`agentcore-mcp-rag`) can authenticate as your IAM user
and call `InvokeAgentRuntime`.

Without credentials configured, the proxy falls back to the EC2 instance's SSM
role, which does not have `bedrock-agentcore:InvokeAgentRuntime` permission.

---

## Prerequisites

- You have an IAM user in AWS account `903050880929` (your NOAA email address)
- You are a member of the **PowerUser** group (ask Terry to verify if unsure)
- You can sign in to the AWS Console

---

## Step 1 — Create an Access Key in the AWS Console

1. Open the AWS Console: https://903050880929.signin.aws.amazon.com/console
2. Sign in with your IAM user (`firstname.lastname@noaa.gov`)
3. Click your username in the **top-right corner** → select **Security credentials**
4. Scroll down to the **Access keys** section
5. Click **Create access key**
6. Select use case: **Command Line Interface (CLI)**
7. Check the acknowledgment box, click **Next**, then **Create access key**
8. **Copy both values** — you will not be able to see the Secret again:
   - `Access key ID` (looks like `AKIA...`)
   - `Secret access key` (a long random string)

> Keep these values private. Never commit them to git or share them in chat.

---

## Step 2 — Configure credentials on the development instance

SSH into the instance and edit your credentials file:

```bash
vi ~/.aws/credentials
```

Replace the placeholder values with your real keys:

```ini
[agentcore-rag]
aws_access_key_id = AKIA...YOUR_KEY_ID...
aws_secret_access_key = YOUR_SECRET_KEY_HERE
```

Save and close. The file permissions should already be `600` (owner-only read).
Verify:

```bash
ls -la ~/.aws/credentials
# Should show: -rw------- 1 your.name your.name ...
```

---

## Step 3 — Verify it works

```bash
AWS_PROFILE=agentcore-rag aws sts get-caller-identity
```

You should see your IAM user ARN:
```json
{
    "UserId": "...",
    "Account": "903050880929",
    "Arn": "arn:aws:iam::903050880929:user/your.name@noaa.gov"
}
```

If it still shows `assumed-role/SSMrole/...`, the credentials file isn't being
read — check the path, permissions, and that the profile header is `[agentcore-rag]`.

---

## Step 4 — Reload the MCP server in Kiro

In your Kiro IDE:
- **Ctrl+Shift+P** → "Reload Window"

Or from the MCP panel, click the reconnect button on `agentcore-mcp-rag`.

The MCP proxy will now authenticate as your IAM user and
`InvokeAgentRuntime` will succeed.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `AccessDeniedException: InvokeAgentRuntime` | Credentials not configured or expired — repeat Steps 1-3 |
| `NoCredentialsError` | `~/.aws/credentials` file missing or empty |
| `InvalidClientTokenId` | Access key was deleted or deactivated in the Console |
| Still shows `SSMrole` in `get-caller-identity` | Check that `~/.aws/credentials` has `[default]` section header |

---

## Security Notes

- Access keys do **not** expire automatically but can be rotated in the Console
- If you suspect a key is compromised, immediately deactivate it in the Console
  under Security credentials → Access keys → Actions → Deactivate
- The `~/.aws/credentials` file is `chmod 600` — only your account can read it
- Never set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` as environment
  variables in shared configs (`.bashrc`, mcp.json env blocks, etc.)
