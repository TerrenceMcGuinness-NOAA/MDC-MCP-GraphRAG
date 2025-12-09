#!/usr/bin/env python3
"""Limited code ingestion - scripts, ush, jobs only (skip sorc)"""
import os
os.environ['CODE_COLLECTION'] = 'code-with-context-v7-0-0'

# Monkey-patch CODE_DIRECTORIES before import
import ingest_code_v7
ingest_code_v7.CODE_DIRECTORIES = ['scripts', 'ush', 'jobs']

# Run ingestion
ingester = ingest_code_v7.CodeIngesterV7()
ingester.ingest_directory()
