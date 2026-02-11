# Global Workflow v17+ CONOPS Diagram Guide

**Generated**: 2025-02-11  
**Source**: `workflow_v17_conops.mmd` (Mermaid flowchart)  
**Exports**: SVG, PNG, PDF  
**Based on**: `gfs_cycled.py` task definitions at commit 2a679b4a  

---

## Diagram Structure

The diagram mirrors the v16 CONOPS layout with three major columns:

| Column | Subgraph | Background | Description |
|--------|----------|------------|-------------|
| Left | **gdas** | Green (#88CC44) | Analysis cycling (6-hourly DA cycle) |
| Center | **enkfgdas** | Teal (#66AA88) | Hybrid ensemble data assimilation |
| Right | **gfs** | Light green (#AADDAA) | Medium-range deterministic forecast |

### Nested Subgraphs (Analysis Paths)

| Subgraph | Background | Purpose |
|----------|------------|---------|
| GSI Analysis | Blue (#5599DD) | Legacy GSI analysis path (anal → analcalc/analdiag) |
| JEDI Atm Analysis | Green (#66CC99) | **NEW** JEDI variational analysis path |
| Marine DA | Blue (#77BBDD) | **NEW** Ocean data assimilation chain |
| GSI Hybrid EnKF | Blue (#5599DD) | Legacy ensemble observation/update path |
| JEDI Ensemble Analysis | Green (#66CC99) | **NEW** JEDI ensemble analysis (LETKF/3DVar) |

---

## Color Legend (Node Classes)

| Color | Class | Meaning |
|-------|-------|---------|
| Blue (#4488CC) | `core` | Existing/legacy tasks (present in v16) |
| Yellow (#FFDD44) | `forecast` | Forecast task (bold, prominent) |
| Light green (#98FB98) | `new` | **NEW in v17+** (green border, 3px) |
| Purple (#C8A2C8) | `wave` | Wave model tasks |
| Green (#88BB44) | `product` | Product generation / GEMPAK / AWIPS |
| Peach (#FFC896) | `verify` | Verification tasks |
| Pink (#FFB6C1) | `archive` | Archiving and cleanup |
| Sky blue (#87CEEB) | `stage` | Staging / fetch tasks |
| Blue dashed | `optional` | Optional tasks (dashed border) |
| Blue bold purple text | `metatask` | Metatasks (run N members) |

### Arrow Types

| Arrow | Meaning |
|-------|---------|
| Solid (`-->`) | Required dependency |
| Dashed (` -.->`) | Cross-run or optional dependency |
| Labeled dashed | Inter-cycle connection (e.g., "cycle +06h") |

---

## Gap Analysis: v16 → v17+

### Tasks Added (not in v16)

#### JEDI Atmosphere Data Assimilation
- `atmanlinit` — Initialize JEDI atmospheric analysis
- `atmanlvar` — JEDI variational minimization
- `atmanlfv3inc` — Generate FV3 increment from JEDI
- `atmanlfinal` — Finalize JEDI atmospheric analysis

#### JEDI Ensemble Data Assimilation
- `atmensanlinit` — Initialize JEDI ensemble analysis
- `atmensanlobs` — JEDI ensemble observation processing
- `atmensanlsol` — JEDI ensemble solver
- `atmensanlletkf` — JEDI LETKF solver (alternative to obs+sol)
- `atmensanlfv3inc` — Generate FV3 increment from JEDI ensemble
- `atmensanlfinal` — Finalize JEDI ensemble analysis
- `ecen_fv3jedi` — JEDI-based ensemble recentering

#### Marine/Ocean Data Assimilation
- `prepoceanobs` — Prepare ocean observations
- `marinebmatinit` — Initialize marine background error
- `marinebmat` — Compute marine background error covariance
- `marineanlinit` — Initialize marine analysis
- `marineanlvar` — Marine variational analysis
- `marineanlchkpt` — Marine analysis checkpoint
- `marineanlfinal` — Finalize marine analysis
- `marineanlletkf` — Marine ensemble LETKF
- `marineanlecen` — Marine ensemble recentering

#### Snow Data Assimilation
- `snowanl` — Snow analysis (deterministic)
- `esnowanl` — Snow analysis (ensemble)

#### Aerosol Analysis
- `aeroanlgenb` — Generate aerosol background error
- `aeroanlinit` — Initialize aerosol analysis
- `aeroanlvar` — Aerosol variational analysis
- `aeroanlfinal` — Finalize aerosol analysis

#### New Product Tasks
- `ocean_prod` — Ocean product generation
- `ice_prod` — Sea ice product generation
- `goesupp` — GOES UPP post-processing
- `atmanlupp` — Analysis UPP processing
- `atmanlprod` — Analysis product generation

#### New Verification
- `anlstat` — Analysis statistics monitoring
- `tracker` — Tropical cyclone tracker
- `genesis` — TC genesis detection
- `genesis_fsu` — FSU TC genesis algorithm
- `metp` — METplus verification (metatask)

#### Infrastructure
- `fetch` — Fetch external data
- `stage_ic` — Stage initial conditions
- `prep_sfc` — Surface data preparation

#### Archiving Restructured
- `arch` (v16) → split into `arch_vrfy` + `arch_tars`
- `earc` (v16) → split into `earc_vrfy` + `earc_tars`
- `globus_arch` — Globus transfer for deterministic archive
- `globus_earc` — Globus transfer for ensemble archive

#### Wave Expansion
- `wavegempak` — Wave GEMPAK products
- `waveawipsbulls` — Wave AWIPS bulletins
- `waveawipsgridded` — Wave AWIPS gridded products

#### Additional GEMPAK/Distribution
- `gempakmeta` — GEMPAK meta charts
- `gempakmetancdc` — GEMPAK meta NCDC
- `gempakncdcupapgif` — NCDC upper air GIF products
- `gempakpgrb2spec` — GEMPAK GRIB2 special products
- `npoess` — NPOESS/JPSS satellite products
- `postsnd` — Post sounding
- `fbwind` — FB wind products
- `awips_20km_1p0deg` — AWIPS grids

### Tasks Removed from v16
- `gldas` — Global Land Data Assimilation (removed in v17)
- `waveprep` — Merged into waveinit

### Tasks Renamed/Restructured
- `post` → `atmupp` + `atmos_prod` (split into UPP and product generation)
- `arch` → `arch_vrfy` + `arch_tars` (split archiving)
- `earc` → `earc_vrfy` + `earc_tars` (split ensemble archiving)

---

## Application Types Not Shown (Separate Diagrams Recommended)

| App Type | Config File | Notes |
|----------|-------------|-------|
| `gfs_forecast_only` | `gfs_forecast_only.py` | Free forecast, no DA cycle |
| `gefs` | `gefs.py` | Ensemble forecast (21 tasks) |
| `sfs` | `sfs.py` | Subseasonal Forecast System (18 tasks) |
| `gcafs` | `gcafs.py` | Global Coupled Assimilation Forecast System (30+ tasks) |

---

## Rendering

```bash
# SVG (primary)
npx mmdc -i workflow_v17_conops.mmd -o workflow_v17_conops.svg -w 4000 -H 6000 --backgroundColor transparent

# PNG (4000px wide)
rsvg-convert -f png -w 4000 workflow_v17_conops.svg -o workflow_v17_conops.png

# PDF
rsvg-convert -f pdf workflow_v17_conops.svg -o workflow_v17_conops.pdf
```
