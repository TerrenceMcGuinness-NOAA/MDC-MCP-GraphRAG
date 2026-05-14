#!/usr/bin/env python3
"""
Documentation parser registry for Phase 48 local-first ingestion.

Each parser converts raw on-disk content into a list of plain-text chunks
suitable for MPNet embedding. Chunk size matches the URL crawler default
(1000 chars, 200 overlap) so local and URL chunks are comparable.

Parsers expose a single signature: parser(text: str) -> List[str].

The roff_man parser is the one exception: it takes a Path because it
shells out to `groff(1)` for rendering.

Used by ingest_local_docs_v8.py via PARSER_REGISTRY[name](...).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, Dict, List

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
MIN_CHUNK_CHARS = 100


# ---------------------------------------------------------------------------
# Base chunker
# ---------------------------------------------------------------------------

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    """Sliding-window chunker. Drops chunks shorter than MIN_CHUNK_CHARS."""
    text = text.strip()
    if not text:
        return []
    chunks: List[str] = []
    step = max(1, size - overlap)
    for start in range(0, len(text), step):
        chunk = text[start:start + size].strip()
        if len(chunk) >= MIN_CHUNK_CHARS:
            chunks.append(chunk)
        if start + size >= len(text):
            break
    return chunks


# ---------------------------------------------------------------------------
# Sphinx RST
# ---------------------------------------------------------------------------

# Strip `.. directive::` blocks that produce no useful prose
# (autodoc/automodule produce import-driven content we don't have on disk;
# raw::/image::/figure:: are presentation-only).
_RST_NOISE_DIRECTIVE = re.compile(
    r'^\.\.\s+(autoclass|automodule|autofunction|autosummary|raw|image|figure|toctree|index|only|graphviz|youtube)::.*?(?=^\S|\Z)',
    re.MULTILINE | re.DOTALL,
)
# Strip RST hyperlink targets and substitution defs (.. _label: ... / .. |sub| replace::)
_RST_REF_TARGET = re.compile(r'^\.\.\s+_[^:]+:\s*$', re.MULTILINE)
_RST_SUB_DEF = re.compile(r'^\.\.\s+\|[^|]+\|.*$', re.MULTILINE)
# Collapse runs of blank lines
_BLANK_RUN = re.compile(r'\n{3,}')


def parse_sphinx_rst(text: str) -> List[str]:
    """Strip presentation-only directives, then chunk."""
    cleaned = _RST_NOISE_DIRECTIVE.sub('', text)
    cleaned = _RST_REF_TARGET.sub('', cleaned)
    cleaned = _RST_SUB_DEF.sub('', cleaned)
    cleaned = _BLANK_RUN.sub('\n\n', cleaned)
    return chunk_text(cleaned)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

# Strip HTML comments (often hide TODO notes)
_HTML_COMMENT = re.compile(r'<!--.*?-->', re.DOTALL)


def parse_markdown(text: str) -> List[str]:
    cleaned = _HTML_COMMENT.sub('', text)
    cleaned = _BLANK_RUN.sub('\n\n', cleaned)
    return chunk_text(cleaned)


# ---------------------------------------------------------------------------
# GitHub Wiki Markdown
# ---------------------------------------------------------------------------

# Wiki link forms:
#   [[Page-Name]]                  -> Page-Name
#   [[Display Text|Page-Name]]     -> Display Text (Page-Name)
_WIKI_LINK_DISPLAY = re.compile(r'\[\[([^\]|]+)\|([^\]]+)\]\]')
_WIKI_LINK_BARE = re.compile(r'\[\[([^\]|]+)\]\]')


def parse_wiki_markdown(text: str) -> List[str]:
    """Normalize MediaWiki-style links so chunks remain self-describing."""
    text = _WIKI_LINK_DISPLAY.sub(lambda m: f'{m.group(1)} ({m.group(2)})', text)
    text = _WIKI_LINK_BARE.sub(lambda m: m.group(1).replace('-', ' '), text)
    return parse_markdown(text)


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------

def parse_plain_text(text: str) -> List[str]:
    return chunk_text(text)


# ---------------------------------------------------------------------------
# YAML (config-as-doc)
# ---------------------------------------------------------------------------

def parse_yaml(text: str) -> List[str]:
    """Treat YAML as text; preserve structure via plain chunking."""
    return chunk_text(text)


# ---------------------------------------------------------------------------
# roff manpages (file-level — needs subprocess)
# ---------------------------------------------------------------------------

def parse_roff_man_file(path: Path) -> List[str]:
    """Render a *.1 / *.5 / etc. manpage to plain text via groff, then chunk.

    Returns [] if groff is missing or fails.
    """
    try:
        proc = subprocess.run(
            ['groff', '-mandoc', '-Tutf8', '-P-c', str(path)],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return []
        # Strip terminal control chars groff sometimes leaves in
        rendered = re.sub(r'\x1b\[[0-9;]*m', '', proc.stdout)
        rendered = re.sub(r'.\x08', '', rendered)  # backspace overstrike
        return chunk_text(rendered)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PARSER_REGISTRY: Dict[str, Callable[[str], List[str]]] = {
    'sphinx_rst': parse_sphinx_rst,
    'markdown': parse_markdown,
    'wiki_markdown': parse_wiki_markdown,
    'plain_text': parse_plain_text,
    'yaml': parse_yaml,
}


def get_parser(name: str) -> Callable[[str], List[str]]:
    if name not in PARSER_REGISTRY:
        raise KeyError(f"Unknown parser '{name}'. Known: {sorted(PARSER_REGISTRY)}")
    return PARSER_REGISTRY[name]


# Extension-level overrides (dispatched before the source's `parser` key).
# Used by ingest_local_docs_v8.py to special-case manpages.
EXTENSION_OVERRIDES = {
    '.1': 'roff_man',
    '.2': 'roff_man',
    '.3': 'roff_man',
    '.5': 'roff_man',
    '.7': 'roff_man',
    '.8': 'roff_man',
}
