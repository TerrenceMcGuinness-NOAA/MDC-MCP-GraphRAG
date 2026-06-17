#!/usr/bin/env python3
"""Cross-account S3 copy: streams objects from source bucket to destination
bucket using two different credential sets. No local disk staging needed.

Reads from source using the default AWS profile, writes to destination
using the Parallel Works session credentials from parallel_works_bucket.txt.
"""
import boto3
import sys
import time

# ── Source (our account, default profile) ──────────────────────────────
SOURCE_BUCKET = "mdc-mcp-rag-snapshots-903050880929"
SOURCE_PREFIX = "portable-export/dev/20260616-174650-df73fe6a/"
SOURCE_REGION = "us-east-1"

# ── Destination (Parallel Works account, session creds) ────────────────
DEST_BUCKET = "omdmcpdata"
DEST_PREFIX = "portable-export/dev/20260616-174650-df73fe6a/"
DEST_REGION = "us-east-1"
DEST_ACCESS_KEY = "ASIAYJVSFTGOWZTD75YX"
DEST_SECRET_KEY = "HadJXvoJ041B8ggtRJWsUb1grvfl5fG9+Rzg1+K0"
DEST_SESSION_TOKEN = "FwoGZXIvYXdzENr//////////wEaDAvJlu5/wFVR026LxiKQAjihzAkqTTMyGuDFzi8jUmGyGzzF8jmxBWIWcQ1e+vDNxKGngs7aiatqU1/im8nBiIgqBYHq4H9ZR8CxMoq08xScNPNrNNtFS4YYbdv77UDjyvwpodk91CBLhPWVOLJYn3R/fx+2VSrQSIfMu8C8FnTed/PAD6c4osoQqgNibJfZex2DSpxeI9U1h8JbvBxjXIzKs0QtkabBlCYie9j5I8PeEpp8fGmO7Jf2r/D+6ctcz25OmBiDKqF9VRb3a9SPvyvNupe9Y4rAhwkJjecNYrAKM0mPmYhYS+OhyCrIXddvAFlsYkr6MygwMEbVOPF05XNugx4mg5Dv5nXBEjqo9l6eQYylTuaC1hckPaBm7VBQKJqhy9EGMikOmynbNBMV3hSzf0589nwcCjQs9HSHtnGIL+zO40rDynY93vjNgBWbAg=="


def main():
    print("[INFO] Cross-account S3 copy (streaming, no local disk)")
    print(f"[INFO]   Source: s3://{SOURCE_BUCKET}/{SOURCE_PREFIX}")
    print(f"[INFO]   Dest:   s3://{DEST_BUCKET}/{DEST_PREFIX}")
    print()

    # Build source session (default profile)
    src_session = boto3.Session(profile_name="default", region_name=SOURCE_REGION)
    src_s3 = src_session.client("s3")

    # Build destination session (PW creds)
    dst_session = boto3.Session(
        aws_access_key_id=DEST_ACCESS_KEY,
        aws_secret_access_key=DEST_SECRET_KEY,
        aws_session_token=DEST_SESSION_TOKEN,
        region_name=DEST_REGION,
    )
    dst_s3 = dst_session.client("s3")

    # Verify destination access
    print("[INFO] Verifying destination bucket access...")
    try:
        dst_s3.head_bucket(Bucket=DEST_BUCKET)
        print("[OK]  Destination bucket accessible")
    except Exception as e:
        print(f"[ERROR] Cannot access destination bucket: {e}", file=sys.stderr)
        return 1

    # List all source objects
    print("[INFO] Listing source objects...")
    paginator = src_s3.get_paginator("list_objects_v2")
    objects = []
    for page in paginator.paginate(Bucket=SOURCE_BUCKET, Prefix=SOURCE_PREFIX):
        for obj in page.get("Contents", []):
            objects.append(obj)

    total_objects = len(objects)
    total_bytes = sum(o["Size"] for o in objects)
    print(f"[OK]  Found {total_objects} objects ({total_bytes / (1024**3):.2f} GiB)")
    print()

    # Stream each object from source to destination
    copied = 0
    copied_bytes = 0
    errors = 0
    t0 = time.time()

    for i, obj in enumerate(objects, 1):
        src_key = obj["Key"]
        # Map source key to destination key (same relative path)
        relative = src_key[len(SOURCE_PREFIX):]
        dst_key = DEST_PREFIX + relative
        size_mb = obj["Size"] / (1024 * 1024)

        try:
            # Stream: get from source, put to destination
            response = src_s3.get_object(Bucket=SOURCE_BUCKET, Key=src_key)
            body = response["Body"]

            # Use upload_fileobj for streaming (doesn't buffer entire object in memory)
            dst_s3.upload_fileobj(
                body,
                DEST_BUCKET,
                dst_key,
                ExtraArgs={"ContentType": response.get("ContentType", "application/octet-stream")},
            )

            copied += 1
            copied_bytes += obj["Size"]
            elapsed = time.time() - t0
            rate = copied_bytes / (1024**2) / elapsed if elapsed > 0 else 0
            print(f"[OK]  [{i}/{total_objects}] {relative} ({size_mb:.1f} MB) "
                  f"[{copied_bytes/(1024**3):.2f}/{total_bytes/(1024**3):.2f} GiB, {rate:.1f} MB/s]")

        except Exception as e:
            errors += 1
            print(f"[ERROR] [{i}/{total_objects}] {relative}: {e}", file=sys.stderr)

    # Summary
    elapsed = time.time() - t0
    print()
    print("=" * 60)
    print(f"[OK]  Copy complete in {elapsed:.1f}s")
    print(f"       copied: {copied}/{total_objects} objects")
    print(f"       bytes:  {copied_bytes/(1024**3):.2f} GiB")
    print(f"       errors: {errors}")
    print(f"       rate:   {copied_bytes/(1024**2)/elapsed:.1f} MB/s avg")
    print(f"       dest:   s3://{DEST_BUCKET}/{DEST_PREFIX}")
    print("=" * 60)

    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
