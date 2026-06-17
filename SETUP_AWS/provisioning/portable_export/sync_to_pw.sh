#!/bin/bash
# Sync portable export from source S3 bucket to Parallel Works omdmcpdata bucket.
# Uses default profile for source reads, PW session creds for destination writes.
#
# Strategy: download from source locally, then upload to destination.
# This avoids cross-account S3-to-S3 copy permission issues.

set -euo pipefail

SOURCE_BUCKET="mdc-mcp-rag-snapshots-903050880929"
SOURCE_PREFIX="portable-export/dev/20260616-174650-df73fe6a"
DEST_BUCKET="omdmcpdata"
DEST_PREFIX="portable-export/dev/20260616-174650-df73fe6a"
STAGING_DIR="/tmp/portable-export-staging"

# Parallel Works credentials (fresh session token)
PW_ACCESS_KEY="ASIAYJVSFTGOWZTD75YX"
PW_SECRET_KEY="HadJXvoJ041B8ggtRJWsUb1grvfl5fG9+Rzg1+K0"
PW_SESSION_TOKEN="FwoGZXIvYXdzENr//////////wEaDAvJlu5/wFVR026LxiKQAjihzAkqTTMyGuDFzi8jUmGyGzzF8jmxBWIWcQ1e+vDNxKGngs7aiatqU1/im8nBiIgqBYHq4H9ZR8CxMoq08xScNPNrNNtFS4YYbdv77UDjyvwpodk91CBLhPWVOLJYn3R/fx+2VSrQSIfMu8C8FnTed/PAD6c4osoQqgNibJfZex2DSpxeI9U1h8JbvBxjXIzKs0QtkabBlCYie9j5I8PeEpp8fGmO7Jf2r/D+6ctcz25OmBiDKqF9VRb3a9SPvyvNupe9Y4rAhwkJjecNYrAKM0mPmYhYS+OhyCrIXddvAFlsYkr6MygwMEbVOPF05XNugx4mg5Dv5nXBEjqo9l6eQYylTuaC1hckPaBm7VBQKJqhy9EGMikOmynbNBMV3hSzf0589nwcCjQs9HSHtnGIL+zO40rDynY93vjNgBWbAg=="
PW_REGION="us-east-1"

echo "[INFO] ===== Portable Export S3 Sync ====="
echo "[INFO] Source: s3://${SOURCE_BUCKET}/${SOURCE_PREFIX}/"
echo "[INFO] Dest:   s3://${DEST_BUCKET}/${DEST_PREFIX}/"
echo

# Step 1: Download from source using default profile
echo "[INFO] Step 1/2: Downloading from source bucket..."
mkdir -p "${STAGING_DIR}"
AWS_PROFILE=default aws s3 sync \
    "s3://${SOURCE_BUCKET}/${SOURCE_PREFIX}/" \
    "${STAGING_DIR}/" \
    --region us-east-1 \
    --quiet
DL_COUNT=$(find "${STAGING_DIR}" -type f | wc -l)
DL_SIZE=$(du -sh "${STAGING_DIR}" | cut -f1)
echo "[OK]  Downloaded ${DL_COUNT} files (${DL_SIZE})"
echo

# Step 2: Upload to destination using PW credentials
echo "[INFO] Step 2/2: Uploading to destination bucket..."
AWS_ACCESS_KEY_ID="${PW_ACCESS_KEY}" \
AWS_SECRET_ACCESS_KEY="${PW_SECRET_KEY}" \
AWS_SESSION_TOKEN="${PW_SESSION_TOKEN}" \
aws s3 sync \
    "${STAGING_DIR}/" \
    "s3://${DEST_BUCKET}/${DEST_PREFIX}/" \
    --region "${PW_REGION}" \
    --quiet
echo "[OK]  Upload complete"
echo

# Step 3: Verify
echo "[INFO] Verifying destination..."
DEST_COUNT=$(AWS_ACCESS_KEY_ID="${PW_ACCESS_KEY}" \
AWS_SECRET_ACCESS_KEY="${PW_SECRET_KEY}" \
AWS_SESSION_TOKEN="${PW_SESSION_TOKEN}" \
aws s3 ls "s3://${DEST_BUCKET}/${DEST_PREFIX}/" --recursive --region "${PW_REGION}" | wc -l)
echo "[OK]  Destination has ${DEST_COUNT} objects"
echo

# Cleanup staging
echo "[INFO] Cleaning up staging directory..."
rm -rf "${STAGING_DIR}"
echo "[OK]  Done"
echo
echo "===== Sync complete ====="
