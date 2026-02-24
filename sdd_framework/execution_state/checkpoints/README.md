# Checkpoints Directory

Checkpoint files are created by `checkpoint_state` (Phase 24H-3) and stored as individual JSON files.

Format: `<checkpoint_id>.json` (e.g., `chk_2026-02-24_a1b2c3.json`)

Each checkpoint contains a snapshot of `modifications[]`, `examined[]`, and step progress at the time of creation.
