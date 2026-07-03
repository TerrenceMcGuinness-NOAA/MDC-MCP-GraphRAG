# Design: Retire the Static Node MCP Container

## Context

Post-Phase-63b topology on the COTS Parallel Works host:

```
Devtunnel :18888 ─▶ mcp-gateway.service (docker mcp gateway run --long-lived)
                     └─▶ per-session: eib-mcp-rag-python:latest (5 tenants, 53 tools)

(no traffic)      ── mcp-rag.service ── eib-mcp-rag-static (Node, 1 tenant, no ports)
```

The lower path is vestigial. This design shuts it down.

## Runtime actions (operator-run, sudo)

Five commands, all reversible:

```bash
sudo systemctl restart mcp-gateway.service        # picks up dep change
sudo systemctl stop mcp-rag.service               # first stop
sudo systemctl disable mcp-rag.service            # no boot restart
sudo rm /etc/cron.d/mcp-health                    # disarm the 5-min cron
                                                  #   NOTE: mv-to-.disabled
                                                  #   was tried first but
                                                  #   Rocky crond reads
                                                  #   dotted files too;
                                                  #   rm is required.
sudo systemctl stop mcp-rag.service               # final stop after cron gone
```

The final `stop` is required because the cron may have already fired between
the first `stop` and the `rm`. After it, `mcp-rag.service` stays inactive
across cron windows.

Rollback for the cron file: `sudo cp $REPO/SETUP/cron.d/mcp-health
/etc/cron.d/` after stripping the DEPRECATED header from the repo SPOT.

## Source-side edits (repo, no execution)

Six files gain deprecation markers; two executable files also short-circuit
with `exit 0` unless `MCP_ALLOW_STATIC_MODE_ROLLBACK=1` is set:

| File | Header comment | Runtime guard |
|---|---|---|
| `SETUP/systemd/mcp-rag.service` | yes | n/a (unit is disabled) |
| `SETUP/systemd/mcp-rag.service.template` | yes | n/a |
| `SETUP/provisioning/12-static-mode-gateway.sh` | yes | `exit 0` unless opt-in |
| `SETUP/cron.d/mcp-health` | yes | n/a (data file) |
| `SETUP/bin/health-check.sh` | yes | n/a (chained under the cron) |
| `SETUP/bin/deploy-static-gateway.sh` | yes | `exit 0` unless opt-in |

`SETUP/provisioning/provision.sh` `SCRIPTS[]` entry retitled so `--list`
surfaces the retirement.

## Verification

Three probes, all pre-existing tools; no new script needed:

1. `docker ps` — must not list `eib-mcp-rag-static`.
2. `systemctl is-active mcp-gateway.service` → `active`.
3. `mcp_docker_ai_mcp_get_server_info` (via the Devtunnel gateway path) →
   `Tenants: 5 (default: gw)`, `Total Tools: 53`, `Active Modules: 9 of 10`.

## Rollback

```bash
sudo systemctl enable --now mcp-rag.service
```

The `Node_Image` remains local (Requirement 2) so no `docker pull` is needed.

## Out-of-scope follow-ons (tracked, not done here)

- Deleting the deprecated files entirely (deferred until at least one full
  release cycle has passed and no rollback has been needed).
- Reclaiming the 8 GB / 4 CPU reservation is automatic once the container
  exits — no cgroup or Docker-daemon change required.
