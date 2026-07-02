#!/usr/bin/env bash
#
# update-kiro-cli-musl.sh — install/upgrade Kiro CLI to the latest release on
# Amazon Linux 2023 (glibc 2.34) using the musl build.
#
# WHY: AL2023 is pinned to glibc 2.34 for its entire release lifecycle, but the
# glibc "latest" Kiro CLI build (what `kiro-cli update` pulls) is linked against
# glibc 2.39 and fails on AL2023 with "GLIBC_2.38/2.39 not found". The musl build
# is statically linked, has NO glibc dependency, and is the SAME release served
# under /latest/ — full feature and version parity with the glibc build.
#
# Re-run this any time to stay on the latest release.
# Do NOT run `kiro-cli update` on AL2023 — it re-pulls the glibc build and breaks.
#
set -euo pipefail

command -v curl  >/dev/null || { echo "ERROR: curl not found"  >&2; exit 1; }
command -v unzip >/dev/null || { echo "ERROR: unzip not found" >&2; exit 1; }

arch="$(uname -m)"
case "$arch" in
  aarch64|arm64) pkg="kirocli-aarch64-linux-musl.zip" ;;
  x86_64|amd64)  pkg="kirocli-x86_64-linux-musl.zip"  ;;
  *) echo "ERROR: unsupported architecture: $arch" >&2; exit 1 ;;
esac
url="https://desktop-release.q.us-east-1.amazonaws.com/latest/${pkg}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

echo "[*] Downloading latest Kiro CLI (musl, ${arch}) ..."
curl --proto '=https' --tlsv1.2 -sSf "$url" -o "$tmp/kirocli.zip"

echo "[*] Extracting ..."
unzip -oq "$tmp/kirocli.zip" -d "$tmp"

echo "[*] Installing (non-interactive) ..."
bash "$tmp/kirocli/install.sh" --no-confirm

echo "[*] Installed. Verifying version ..."
timeout 15 "${HOME}/.local/bin/kiro-cli" --version 2>/dev/null \
  || echo "    (run 'kiro-cli --version' to confirm; 'kiro-cli login' if prompted)"

echo "[OK] Kiro CLI is on the latest musl release. Do NOT run 'kiro-cli update' on AL2023."
