# C48_ATM CTests Path Mapping

_Updated:_ 2025-11-18

This note captures the resolved source and destination paths for the three new
C48_ATM CTests so they line up with the COMROOT layout used by the nightly
staged runs.  It mirrors the templating pattern documented in `dev/ctests/README.md`
(`SRC_DIR = ${STAGED_CTESTS}/COMROOT/${PSLOT}` and `DST_DIR = ${RUNTESTS}/COMROOT/${TEST_NAME}`)
so the YAML cases can resolve to full absolute paths at configure time.

## Path overview

| Test | Stage focus | Baseline source (under `{{ SRC_DIR }}`) | Test destination (under `{{ DST_DIR }}`) | Key files / notes |
|------|-------------|-----------------------------------------|------------------------------------------|-------------------|
| `C48_ATM-gfs_stage_ic` | Initial condition staging (JGFS_ATMOS_STAGE_IC) | `gfs.{{ PDY }}/{{ cyc }}/analysis/atmos` | `gfs.{{ PDY }}/{{ cyc }}/analysis/atmos` | Verifies analysis bundles (`gfs.t{{ cyc }}z.atmanl.nc`, `sfcanl`, `atmf000/f006`, `nstanl`, etc.). The Stage task also touches `model/atmos/input`/`restart`; expand coverage as future data are staged. |
| `C48_ATM-gfs_tracker` | Tropical cyclone tracker (JGFS_ATMOS_CYCLONE_TRACKER) | `gfs.{{ PDY }}/{{ cyc }}/model/atmos/history` | `gfs.{{ PDY }}/{{ cyc }}/products/atmos/cyclone/tracks` | Consumes the full 0–120 h forecast history at 0.25°. Outputs include adeck/bdeck pairs (and INVEST variants) placed in the COM-standard tracks directory. |
| `C48_ATM-gfs_genesis` | Tropical cyclone genesis detector (JGFS_ATMOS_CYCLONE_GENESIS) | `gfs.{{ PDY }}/{{ cyc }}/model/atmos/history` | `gfs.{{ PDY }}/{{ cyc }}/products/atmos/cyclone/genesis_vital` | Shares the same forecast history inputs as tracker but emits basin/east/west `.bs` and `.grb2` genesis probability datasets. |

## Implementation notes

- Each YAML case declares `PDY`, `cyc`, `SRC_DIR`, and `DST_DIR` using the
  standard templating filters so the paths resolve automatically from
  `TEST_DATE`, `STAGED_CTESTS`, and `RUNTESTS`.
- The staged nightly snapshot must contain the full COMROOT tree for the
  reference PSLOT (e.g., `.../COMROOT/C48_ATM/gfs.20210323/12/...`).  The
  tracker/genesis jobs additionally expect the tracker package tree defined
  in `config.tropcy` to be available.
- Validation scripts now compare outputs directly against the COMROOT baseline,
  leveraging the resolved destination paths instead of ad-hoc `atmos_ic`
  directories.
- When expanding coverage (e.g., adding `model/atmos/input` checkpoints for
  the stage_ic test), follow the same pattern: reference files relative to
  `SRC_DIR`/`DST_DIR` so they stay portable across machines and nightly runs.

These mappings should be kept alongside the YAML cases so future contributors
understand which COMROOT branches are exercised by each ATM regression test.

## Future templated examples

The following snippet captures the more readable templated style that uses
`SRC_DIR`, `DST_DIR`, and `TEST_DATE` to resolve COMROOT paths. Keep it handy
ahead of the proposed PR that will teach `stage.py` to consume the new
structure.

```yaml
{% set cyc = TEST_DATE | strftime('%H') %}
{% set PDY = TEST_DATE | to_YMD %}
{% set SRC_DIR = STAGED_CTESTS + '/COMROOT/' + PSLOT %}
{% set DST_DIR = RUNTESTS + '/COMROOT/' + TEST_NAME %}

input:
  source_cycle: {{ PDY }}{{ cyc }}
  source_dir: {{ SRC_DIR }}/gfs.{{ PDY }}/{{ cyc }}/model/atmos/history
  files:
    - gfs.t{{ cyc }}z.atmf000.nc
    - gfs.t{{ cyc }}z.atmf006.nc
    - gfs.t{{ cyc }}z.atmf012.nc
output:
  target_dir: {{ DST_DIR }}/gfs.{{ PDY }}/{{ cyc }}/products/atmos/cyclone/tracks
  files:
    - gfs.t{{ cyc }}z.adeck
    - gfs.t{{ cyc }}z.bdeck
```

Reuse this pattern for stage_ic and genesis by swapping the `source_dir`
and `target_dir` paths per the table above.
