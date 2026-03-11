#!/usr/bin/env python3
"""
CI Test Case Documentation Ingestion Script

Discovers, analyzes, and documents all CI test case YAML files from the
global-workflow repository, generating expert-level documentation and
ingesting into ChromaDB for semantic search.

Features:
- YAML parsing and structure extraction
- Automatic documentation generation from templates
- ChromaDB collection management
- Progress reporting and dry-run mode
- Metadata enrichment with test categories

Usage:
    # Discovery only
    python3 ingest_ci_test_cases.py --discover

    # Generate docs without ingestion
    python3 ingest_ci_test_cases.py --generate-docs --dry-run

    # Full ingestion pipeline
    python3 ingest_ci_test_cases.py --full

    # Update existing collection
    python3 ingest_ci_test_cases.py --update

Author: MCP RAG Development Team
Version: 1.0.0
Date: November 15, 2025
"""

import os
import sys
import yaml
import argparse
import re
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

# Phase 40: Neo4j integration for CITestCase graph nodes
try:
    from neo4j import GraphDatabase as Neo4jDriver
    NEO4J_AVAILABLE = True
except ImportError:
    print("[WARN] neo4j package not found. Neo4j graph ingestion disabled.")
    Neo4jDriver = None
    NEO4J_AVAILABLE = False

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

# Add parent directory to path for ingestion_base import
sys.path.insert(0, str(Path(__file__).parent))

try:
    from ingestion_base import (
        setup_chromadb,
        create_collection,
        add_documents_to_collection,
        ChromaIngestor
    )
    print("[OK] Imported ingestion_base modules")
except ImportError as e:
    print(f"[ERROR] Failed to import ingestion_base: {e}")
    print("[INFO] Falling back to direct ChromaDB client")
    import chromadb
    from chromadb.config import Settings


class CITestCaseAnalyzer:
    """Analyzes CI test case YAML files and generates documentation."""

    def __init__(self, workflow_root: str):
        self.workflow_root = Path(workflow_root)
        self.ci_cases_dir = self.workflow_root / "dev" / "ci" / "cases"
        self.test_cases = []

    def discover_test_cases(self) -> List[Path]:
        """Discover all CI test case YAML files (recursive)."""
        if not self.ci_cases_dir.exists():
            print(f"[ERROR] CI cases directory not found: {self.ci_cases_dir}")
            return []

        # Search recursively for all YAML files
        yaml_files = list(self.ci_cases_dir.glob("**/*.yaml"))
        print(f"[OK] Discovered {len(yaml_files)} CI test case files")
        
        # Show breakdown by subdirectory
        by_dir = {}
        for f in yaml_files:
            subdir = f.parent.name
            by_dir[subdir] = by_dir.get(subdir, 0) + 1
        
        for subdir, count in sorted(by_dir.items()):
            print(f"  - {subdir}/: {count} files")
        
        return yaml_files

    def _get_category_purpose(self, category: str) -> str:
        """Get human-readable purpose for each CI test category."""
        purposes = {
            'pr': 'Pull Request - fast CI tests',
            'gfsv17': 'GFS v17 operational configs',
            'gcafsv1': 'GCAFS coupled system tests',
            'sfs': 'Subseasonal Forecast System',
            'weekly': 'Weekly high-resolution tests',
            'hires': 'Very high resolution tests',
            'yamls': 'Base configuration templates',
        }
        return purposes.get(category, 'Unknown category')

    def parse_yaml_file(self, filepath: Path) -> Dict[str, Any]:
        """Parse a YAML test case file using text extraction (handles Jinja2 and !INC)."""
        try:
            # Read raw content
            with open(filepath, 'r') as f:
                raw_content = f.read()
            
            # Extract key information via regex (more robust than YAML parsing for templates)
            parsed = {
                'filename': filepath.name,
                'filepath': str(filepath),
                'category': filepath.parent.name,
                'raw_content': raw_content,
            }
            
            # Extract experiment config (first preference: experiment: block)
            if match := re.search(r'experiment:\s*\n((?:  .*\n)*)', raw_content):
                exp_block = match.group(1)
                
                # Extract fields from experiment block
                if app_match := re.search(r'^\s*app:\s*(\w+)', exp_block, re.M):
                    parsed['app'] = app_match.group(1)
                if mode_match := re.search(r'^\s*mode:\s*(\w+)', exp_block, re.M):
                    parsed['mode'] = mode_match.group(1)
                if net_match := re.search(r'^\s*net:\s*(\w+)', exp_block, re.M):
                    parsed['net'] = net_match.group(1)
                if idate_match := re.search(r'^\s*idate:\s*(\d+)', exp_block, re.M):
                    parsed['idate'] = idate_match.group(1)
                if edate_match := re.search(r'^\s*edate:\s*(\d+)', exp_block, re.M):
                    parsed['edate'] = edate_match.group(1)
                    
                # Extract resolutions
                if res_match := re.search(r'^\s*resdetatmos:\s*(\d+)', exp_block, re.M):
                    parsed['atmos_res'] = f"C{res_match.group(1)}"
                if res_match := re.search(r'^\s*resdetocean:\s*([\d.]+)', exp_block, re.M):
                    ocean_val = res_match.group(1).replace('.', '')[:3]
                    parsed['ocean_res'] = f"mx{ocean_val}"
                if res_match := re.search(r'^\s*resensatmos:\s*(\d+)', exp_block, re.M):
                    parsed['ensemble_res'] = f"C{res_match.group(1)}"
            
            # Extract skip hosts
            if skip_match := re.search(r'skip_ci_on_hosts:\s*\n((?:  - .*\n)*)', raw_content):
                hosts_block = skip_match.group(1)
                hosts = re.findall(r'^\s*-\s*(\w+)', hosts_block, re.M)
                parsed['skip'] = hosts
            else:
                parsed['skip'] = []
            
            # Set defaults for missing fields
            parsed.setdefault('app', 'unknown')
            parsed.setdefault('mode', 'unknown')
            parsed.setdefault('net', 'unknown')
            parsed.setdefault('idate', 'unknown')
            parsed.setdefault('edate', 'unknown')
            parsed.setdefault('atmos_res', 'unknown')
            
            return parsed

        except Exception as e:
            print(f"[WARN] Failed to parse {filepath.name}: {e}")
            return None

    def categorize_test_case(self, parsed: Dict[str, Any]) -> Dict[str, str]:
        """Categorize test case by application, mode, resolution, and CI category."""
        category = parsed.get('category', 'unknown')
        
        categories = {
            'ci_category': category,
            'category_purpose': self._get_category_purpose(category),
            'application': self._categorize_app(parsed.get('app', '')),
            'mode': self._categorize_mode(parsed.get('mode', '')),
            'resolution_tier': self._categorize_resolution(parsed.get('atmos_res', '')),
            'duration': self._categorize_duration(parsed, category),
            'test_type': self._categorize_test_type(category),
        }
        return categories

    def _categorize_app(self, app: str) -> str:
        """Categorize application type."""
        app_lower = app.lower()
        if 's2sw' in app_lower:
            return 'Subseasonal-to-Seasonal Weather'
        elif 's2s' in app_lower:
            return 'Subseasonal-to-Seasonal'
        elif 'atm' in app_lower:
            return 'Atmosphere Only'
        else:
            return app

    def _categorize_mode(self, mode: str) -> str:
        """Categorize run mode."""
        mode_lower = mode.lower()
        if 'cycled' in mode_lower or 'cyc' in mode_lower:
            return 'Cycled (Data Assimilation)'
        elif 'forecast' in mode_lower:
            return 'Forecast Only'
        else:
            return mode

    def _categorize_resolution(self, res: str) -> str:
        """Categorize atmospheric resolution tier."""
        res_str = str(res).upper()
        if 'C768' in res_str:
            return 'High (~13km)'
        elif 'C384' in res_str:
            return 'Medium-High (~25km)'
        elif 'C192' in res_str:
            return 'Medium (~50km)'
        elif 'C96' in res_str:
            return 'Medium-Low (~100km)'
        elif 'C48' in res_str:
            return 'Low (~200km)'
        else:
            return 'Custom'

    def _categorize_duration(self, parsed: Dict[str, Any], category: str) -> str:
        """Estimate test duration category based on CI category."""
        duration_map = {
            'pr': 'Short (minutes to 1 hour)',
            'gfsv17': 'Medium to Long (hours)',
            'gcafsv1': 'Medium (1-3 hours)',
            'sfs': 'Long (multiple hours)',
            'weekly': 'Long (multiple hours)',
            'hires': 'Very Long (many hours)',
            'yamls': 'N/A (template)',
        }
        return duration_map.get(category, 'Unknown')
    
    def _categorize_test_type(self, category: str) -> str:
        """Categorize test type by CI category."""
        type_map = {
            'pr': 'Continuous Integration',
            'gfsv17': 'Operational Validation',
            'gcafsv1': 'Application Validation',
            'sfs': 'Application Validation',
            'weekly': 'Weekly Regression',
            'hires': 'High-Resolution Validation',
            'yamls': 'Configuration Template',
        }
        return type_map.get(category, 'Unknown')

    def _get_meteorological_context(self, parsed: Dict[str, Any], categories: Dict[str, str]) -> str:
        """Generate comprehensive GFS system context - meteorological, scientific, and operational."""
        app = parsed.get('app', '').upper()
        mode = parsed.get('mode', '').lower()
        category = parsed.get('category', '')
        atmos_res = parsed.get('atmos_res', '')
        ocean_res = parsed.get('ocean_res', '')
        
        context = "\n## GFS System Context\n\n"
        
        # Add GFS system overview first
        context += """### Global Forecast System (GFS) Overview

**Mission-Critical NOAA System:**
- Primary operational global NWP (Numerical Weather Prediction) model for NOAA/NCEP
- Produces 16-day global forecasts 4 times daily (00Z, 06Z, 12Z, 18Z)
- Serves as backbone for US weather forecasting, aviation, marine, severe weather warnings
- Provides boundary conditions for regional models (NAM, HRRR, hurricanes)
- Distributed to 180+ countries via World Meteorological Organization
- Powers weather.gov forecasts seen by millions daily

**GFS v17 Current Operational Status (2024-present):**
- Replaced GFS v16 with major upgrades in physics, resolution, and data assimilation
- Unified Forecast System (UFS) framework - community-based, extensible
- FV3 (Finite Volume Cubed-sphere) dynamical core
- CCPP (Common Community Physics Package) for modular physics
- Supports multiple applications: atmosphere-only, coupled S2S, hurricane, air quality

"""
        
        # Application-specific context
        if 'S2SW' in app or 'S2S' in app:
            context += """### Subseasonal-to-Seasonal (S2S/S2SW) Application

**Scientific Foundation:**
- Addresses the "predictability desert" between weather (1-10 days) and seasonal (3-12 months)
- Leverages slow-varying climate signals: SST, soil moisture, snow cover, sea ice
- Key phenomena: Madden-Julian Oscillation (MJO), El Niño/La Niña, Arctic Oscillation
- Probabilistic forecasts for weeks 3-4 temperature/precipitation anomalies

**Coupled System Rationale:**
- Ocean memory provides predictability beyond atmospheric chaos (~2 weeks limit)
- SST evolution drives teleconnections (e.g., tropical heating → Rossby waves → US weather)
- Ocean-atmosphere coupling prevents SST drift, maintains realistic feedback
- Sea ice extent influences polar vortex, stratospheric sudden warmings

**Operational Products:**
- NOAA Climate Prediction Center (CPC) Week 3-4 Outlooks
- Monthly and seasonal outlooks initialization
- Tropical cyclone extended-range guidance
- Drought and flood early warning (soil moisture persistence)

**GFS v17 S2SW Configuration:**
- MOM6 ocean model (1/4° to 1° resolution, 75 vertical levels)
- CICE6 sea ice model (thermodynamic + dynamic)
- GOCART aerosols (dust, smoke impact on radiation)
- Wave model (WW3) for ocean surface roughness
- 45-day forecast length (extended from 16-day atmosphere-only)
- Ensemble forecasts critical for probabilistic guidance

**Real-World Impact:**
- Agricultural planning (planting decisions based on 2-4 week precip outlook)
- Water resource management (reservoir operations, drought planning)
- Energy sector (heating/cooling demand forecasts)
- Wildfire risk assessment (dry/wet pattern persistence)

"""
        elif 'GCAFS' in app or 'GCAFS' in parsed.get('filename', '').upper():
            context += """### Global Coupled Atmosphere Forecast System (GCAFS)

**Experimental Research Application:**
- Tests ocean-atmosphere coupling for 0-10 day forecasts (not yet operational)
- Hypothesis: Coupling improves tropical cyclone intensity, marine forecasts
- May replace atmosphere-only GFS for short-range in future versions

**Scientific Motivation:**
- Prescribed SST in GFS can drift from reality over 7-10 day forecast
- Ocean mixed layer responds to wind stress, heat flux on synoptic timescales
- Tropical cyclone-induced ocean cooling (upwelling) missing in uncoupled runs
- Coupled boundary layer processes more realistic over ocean

**Key Differences from S2SW:**
- Shorter forecast length (10 days vs 45 days)
- Focus on synoptic timescales, not subseasonal
- Higher ocean resolution for mesoscale eddies
- No data assimilation vs. cycled DA in S2SW

**Research Questions:**
- Does coupling improve 3-7 day tropical cyclone intensity forecasts?
- Better MJO propagation and amplitude?
- Reduced biases in marine boundary layer temperature/moisture?
- Computational cost vs. accuracy trade-off justified?

**Path to Operations:**
- Validation against atmosphere-only GFS control
- Verification metrics: tropical cyclone errors, marine obs fit, ENSO teleconnections
- Community feedback via UFS testbed experiments

"""
        elif 'ATM' in app or app == 'UNKNOWN':
            context += """### Atmosphere-Only Configuration

**Current GFS Operational Baseline (0-16 days):**
- Standard deterministic forecast mode at NCEP
- Prescribed SST/sea ice from RTG (Real-Time Global) analysis
- Fastest configuration: ~2 hours for 16-day forecast on WCOSS2
- Provides boundary conditions for CONUS models (NAM, HRRR, etc.)

**Physical Parameterizations (GFS v17):**
- Microphysics: GFDL 6-class (cloud water, ice, rain, snow, graupel, hail)
- Convection: Simplified Arakawa-Schubert (SAS) with momentum transport
- PBL: TKE-EDMF (Turbulent Kinetic Energy + Eddy Diffusivity Mass Flux)
- Radiation: RRTMG (shortwave + longwave, aerosol/cloud interactions)
- Land surface: Noah-MP (multi-physics, snow/soil/vegetation)
- Gravity wave drag: Orographic + non-orographic for stratosphere

**Forecast Products Generated:**
- 3-hourly global grids (0.25° resolution) out to 10 days
- 6-hourly grids days 10-16
- 384 vertical levels (model top ~80km, 64 output levels)
- Standard meteorological fields: T, winds, humidity, precip, clouds, etc.
- Derived products: jet stream, freezing level, lifted index, helicity

**Downstream Applications:**
- NWS Weather Forecast Offices (WFOs) use GFS for days 3-7 guidance
- Aviation: Turbulence, icing, winds aloft for flight planning (AWC)
- Marine: Wave forecasts (from GFS winds), offshore weather
- Fire weather: RH, winds, stability indices
- Air quality: Transport winds for smoke/ozone forecasts

"""
        
        # Mode-specific context
        if 'cycled' in mode:
            context += """### Data Assimilation Cycling - The Heart of GFS

**Operational Architecture:**
- 6-hourly cycles: 00Z, 06Z, 12Z, 18Z synchronized globally
- GDAS (Global Data Assimilation System) generates analysis
- Each cycle ingests ~10 million observations (satellites, radiosondes, aircraft, surface, buoys)
- 6-hour forecast from previous cycle provides background (first guess)
- Analysis = optimal blend of background + observations via data assimilation

**GFS v17 Hybrid 4D-EnVar System:**
- **Ensemble component**: 80-member GDAS ensemble at C192 resolution
  - Provides flow-dependent background error covariances
  - Captures storm structure, fronts, jet streams in error correlations
- **Variational component**: GSI (Gridpoint Statistical Interpolation)
  - Iterative minimization of cost function (background + observation terms)
  - Quality control, bias correction of satellite radiances
- **Hybrid weighting**: ~50% ensemble, ~50% static covariances
- **4D capability**: Uses 6-hour forecast trajectory for observation timing

**Observation Types Assimilated:**
- **Satellite radiances** (~6M obs/cycle): ATMS, CrIS, IASI, AMSU-A (temperature sounding)
- **Satellite winds** (~1M obs): AMVs from geostationary satellites, scatterometer winds
- **Conventional obs** (~500K): Radiosondes, aircraft (AMDAR, TAMDAR), surface stations, ships, buoys
- **GPS radio occultation**: COSMIC-2, refractivity for temperature/moisture
- **Aircraft AMDAR**: Critical for jet stream analysis over data-sparse oceans/poles

**Marine Data Assimilation (SOCA):**
- Ocean: In-situ (Argo floats, moorings), satellite altimetry (sea level), SST
- Sea ice: Concentration (AMSR-2, SSMIS), thickness (limited)
- 3D-Var or hybrid-LETKF (Local Ensemble Transform Kalman Filter)
- Ice-ocean coupled background error covariances

**Land Surface DA:**
- Snow depth/cover: SNODAS, IMS (interactive multi-sensor) snow/ice
- Soil moisture: SMAP satellite, screen-level observations
- Vegetation: VIIRS green vegetation fraction

**Quality Control is Mission-Critical:**
- Gross error checks, buddy checks, background departure thresholds
- Satellite bias correction (adaptive, variational)
- Thinning of dense satellite data to reduce correlations
- One bad observation can contaminate large area in analysis

**Why Cycled Tests Matter:**
- Validates entire DA workflow: obs ingest, QC, minimization, analysis output
- Detects degradation: "spinup" from cold start vs. cycled warmstart
- Ensures analysis-forecast consistency across cycle boundaries
- Tests reproducibility (bitwise identical results for operational reliability)

**Impact of DA on Forecast Skill:**
- Accurate initial conditions dominate forecast error for days 1-5
- 10% improvement in analysis → 5-7% improvement in 5-day forecast skill
- Polar regions most sensitive (sparse obs, large background errors)
- Hurricane initial position error directly affects landfall timing/location

"""
        
        # Resolution context with full GFS perspective
        if 'C96' in atmos_res:
            context += """### C96 Resolution (~100km) in GFS Hierarchy

**Role in GFS Operational Suite:**
- **GDAS Ensemble**: 80 members at C192 (~50km) provide spread for DA
- **GEFS Ensemble**: 30 members at C96 for 16-day probabilistic forecasts
- **Development/Testing**: Fast turnaround for CI, prototyping, research

**Scientific Capability & Limitations:**
- ✅ **Resolves**: Synoptic-scale systems (lows, highs, fronts, jet stream)
- ✅ **Captures**: Large-scale tropical convection (MJO, monsoon)
- ✅ **Adequate for**: Ensemble spread generation, large-scale circulation
- ❌ **Misses**: Mesoscale convective systems, frontal detail, orographic precip
- ❌ **Underestimates**: Hurricane intensity, small-scale jets, coastal effects

**Computational Efficiency:**
- ~8x faster than C384 (operational deterministic resolution)
- Enables 30-80 member ensembles where C384 would be prohibitive
- 6-hour forecast: ~15 minutes on WCOSS2 (vs. 2 hours for C384 16-day)

**Appropriate Use Cases:**
- Probabilistic forecasts (GEFS): Spread more important than individual member accuracy
- Subseasonal forecasts: Large-scale flow dominates, mesoscale detail less critical
- CI testing: Workflow validation without full computational cost
- Research: Parameter sensitivity studies, physics testing

**Limitations for Deterministic Forecasts:**
- Not suitable for high-impact weather (severe storms, heavy precip details)
- Hurricane intensity forecasts unreliable (eyewall not resolved)
- Orographic precipitation too smooth (Rockies, Appalachians)

"""
        elif 'C384' in atmos_res:
            context += """### C384 Resolution (~25km) - Operational GFS Standard

**Current Operational Configuration (2024):**
- GFS v17 deterministic forecast: 4x daily (00Z, 06Z, 12Z, 18Z)
- 16-day forecast length (extended from 10 days in v16)
- 0.25° output grids distributed globally
- Serves as "gold standard" for global medium-range forecasting

**What C384 Resolves:**
- ✅ **Synoptic systems**: Extratropical cyclones, jet streams, fronts, blocks
- ✅ **Tropical cyclones**: Track skill excellent (150-200km errors at day 5)
- ✅ **Orographic effects**: Major mountain ranges (Rockies, Andes, Himalayas)
- ✅ **Large MCS**: Mesoscale convective systems barely resolved
- ⚠️ **Hurricane intensity**: Structure emerging but eyewall still coarse
- ❌ **Convective detail**: Individual thunderstorms parameterized, not explicit

**Forecast Skill Benchmarks (GFS v17):**
- Day 3: 500mb height AC ~0.97 (excellent)
- Day 5: AC ~0.92 (very good, comparable to ECMWF)
- Day 7: AC ~0.85 (useful guidance)
- Day 10: AC ~0.75 (lower confidence, ensemble spread increases)
- Hurricane track (day 5): ~250km average error, improving annually

**Why 25km is Operational Sweet Spot:**
- **Computational cost**: ~2 hours for 16-day forecast on WCOSS2 (meets 4x/day schedule)
- **Data volume**: ~50GB per forecast (manageable for distribution/archiving)
- **Skill vs. cost**: Doubling resolution to C768 gains <10% skill, costs 8x compute
- **Physics validity**: Convection parameterization still appropriate at 25km

**Operational Products from C384 Forecasts:**
- **Aviation**: Winds aloft, turbulence, icing for flight planning (AWC)
- **Marine**: Wave model forcing, offshore forecasts (OPC)
- **Fire weather**: Red flag warnings (SPC/local WFOs)
- **Hydrology**: QPF for river forecasts (NWS RFCs)
- **Severe weather**: Day 3-7 outlooks (SPC)
- **Winter weather**: Heavy snow, blizzard warnings 3-5 days out

**International Role:**
- WMO mandatory data exchange: GFS distributed to 180+ countries
- Many nations use GFS as primary model (no domestic NWP capability)
- Tropical cyclone forecasts critical for Pacific islands, Caribbean
- GFS performance affects global forecast quality (coupling to regional models)

"""
        elif 'C768' in atmos_res or 'C1152' in atmos_res:
            context += """### High Resolution (C768: ~13km, C1152: ~9km) - Research Frontier

**Experimental/Research Status:**
- Not operationally feasible for 4x/day global forecasts (yet)
- C768: 8x computational cost vs. C384
- C1152: 27x cost vs. C384
- Used for retrospective case studies, model development, hurricane forecasting research

**Scientific Benefits at High Resolution:**
- ✅ **Tropical cyclones**: Eyewall, rainbands, rapid intensification better captured
- ✅ **Mesoscale features**: Frontal detail, mesovortices, outflow boundaries
- ✅ **Orographic precipitation**: Fine-scale mountain wave effects, valley winds
- ✅ **Coastal meteorology**: Sea breeze fronts, lake effect snow bands
- ⚠️ **Convection**: Approaching "gray zone" (partially resolved, partially parameterized)

**Hurricane Forecasting Applications:**
- C768 used for experimental HWRF-like high-res GFS nests
- Better intensity forecasts (vs. C384) for rapidly intensifying storms
- Improved storm structure: wind field, rain distribution critical for impacts
- Research question: Is global high-res better than nested regional models?

**Convection Parameterization Challenges:**
- At 10-15km, convective clouds partially resolved by grid
- Traditional parameterizations (SAS) assume subgrid convection → breaks down
- Need scale-aware schemes or move to convection-permitting (≤4km)
- "Gray zone" is active research area in global modeling

**Path to Future Operations:**
- Awaiting next-generation supercomputers (2026-2028 timeframe)
- Potential C768 operational by 2030 if compute/storage advances
- May skip to convection-permitting (~3km) if breakthroughs in AI/ML acceleration
- Ensemble forecasts will lag (C384 ensemble likely through 2030)

**Current Use Cases:**
- Case studies of high-impact events (hurricanes, winter storms, floods)
- Model physics testing (how do schemes behave at higher resolution?)
- Validating future operational configurations
- International model comparison projects (S2S, WCRP)

"""
        elif 'C384' in str(parsed.get('atmos_res', '')):
            context += """### C384 Resolution (~25km)

**Operational Context:**
- Current operational GFS deterministic resolution
- Standard for 0-10 day global forecasts
- Resolves synoptic-scale weather systems
- Used in GFS v16/v17 operations at NCEP

**Scientific Capability:**
- Captures jet stream, frontal systems, tropical cyclones
- Approaching mesoscale (but not convection-permitting)
- Balance between resolution and computational cost
- Supports operational 4x/day forecast cycle

"""
        elif 'C768' in str(parsed.get('atmos_res', '')) or 'C1152' in str(parsed.get('atmos_res', '')):
            context += """### High Resolution (C768/C1152: ~13-9km)

**Research/Development Context:**
- Experimental high-resolution configurations
- Used for case studies and model development
- Not yet operationally feasible for global 4x/day cycles
- Helps understand model behavior at higher resolution

**Scientific Benefits:**
- Better representation of mesoscale features
- Improved tropical cyclone structure
- More realistic orographic effects
- Transition toward convection-permitting scales

"""
        
        # Ocean resolution context for coupled runs
        if ocean_res and ocean_res != 'unknown':
            context += f"""### Ocean Component: {ocean_res} Resolution

**MOM6 (Modular Ocean Model version 6):**
- Developed by GFDL (Geophysical Fluid Dynamics Laboratory)
- Tripolar grid: Fine resolution at poles, coarser at equator
- Vertical: 75 levels (surface to abyssal ocean ~6000m)
- Z-coordinate (fixed depth levels) with partial cells at bottom

**Resolution Hierarchy:**
"""
            if 'mx100' in ocean_res or '1.0' in ocean_res:
                context += """- **mx100 (1.0°)**: Coarse ocean for fast prototyping, S2S testing
  - Resolves basin-scale gyres, major currents (Gulf Stream, Kuroshio)
  - Does NOT resolve mesoscale eddies (~100km at mid-latitudes)
  - Sufficient for large-scale SST evolution, ENSO dynamics
  - Used in GEFS ensemble (computational efficiency)
"""
            elif 'mx050' in ocean_res or 'mx50' in ocean_res or '0.5' in ocean_res:
                context += """- **mx050 (0.5°)**: Medium resolution for S2SW operational
  - Partially resolves mesoscale eddies at low latitudes
  - Improved western boundary currents (Gulf Stream separation, rings)
  - Better tropical instability waves (equatorial Pacific)
  - Reasonable balance: skill vs. computational cost
"""
            elif 'mx025' in ocean_res or '0.25' in ocean_res:
                context += """- **mx025 (0.25°)**: High-resolution "eddy-resolving" ocean
  - Explicitly resolves mesoscale eddies (50-200km)
  - Critical for hurricane intensity (ocean heat content, cooling)
  - Realistic major current systems, coastal upwelling
  - Used in GFS v17 retrospective validation, research
  - Computationally expensive (limits forecast length, ensemble size)
"""
            
            context += """
**Why Ocean Resolution Matters:**
- **SST evolution**: Eddy heat transport affects SST patterns (MJO, ENSO)
- **Hurricane intensity**: Ocean cooling from storm mixing (1-3°C) reduces intensity
  - Coarse ocean underestimates cooling → overestimates intensity
- **Upwelling**: Coastal ocean dynamics affect land weather (California, Peru)
- **Mixed layer depth**: Critical for correct heat/momentum exchange with atmosphere

**CICE6 Sea Ice Model:**
- Ice thickness, concentration, velocity
- Thermodynamics: Growth/melt, snow on ice
- Dynamics: Ice advection, ridging, lead formation
- Critical for Arctic/Antarctic forecasts, polar vortex teleconnections

"""
        
        # Category-specific operational context
        if category == 'pr':
            context += """### Pull Request CI Testing - Protecting Operational Reliability

**Mission-Critical Quality Gate:**
- GFS runs 4x/day in operations - downtime costs millions (aviation, emergency response)
- Every code change could break operational workflow → must test before merge
- PR tests are last line of defense before code reaches production systems

**What PR Tests Validate:**
- **Workflow integrity**: All jobs execute in correct order, dependencies satisfied
- **Bitwise reproducibility**: Same code + same data = identical results (critical for operations)
- **File I/O**: Output files created, formatted correctly, readable by downstream systems
- **Error handling**: Graceful failures, meaningful error messages for operators
- **Resource limits**: Jobs complete within wallclock/memory limits on HPC systems

**Speed vs. Coverage Trade-off:**
- Short runtime (1 hour) enables fast developer feedback
- Lower resolution (C96) tests workflow without full computational cost
- Focus on functional correctness, not forecast skill
- Assumes higher-resolution tests (weekly, v17 validation) catch physics/skill issues

**Developer Workflow Impact:**
- Failed PR test blocks merge → forces fix before contaminating develop branch
- Fast turnaround (1-2 hours) enables iterative debugging
- Multiple platforms (Hera, Orion) catch platform-specific bugs early

"""
        elif category == 'gfsv17':
            context += """### GFS v17 Operational Validation - Production Configurations

**Operational Readiness Testing:**
- Tests exact configurations running in NCEP production (WCOSS2)
- "Retrospective" runs: Historical cases with known outcomes
- Validates GFS v17 improvements vs. v16 baseline

**GFS v17 Major Upgrades (2024 Implementation):**
1. **Marine DA**: SOCA 3D-Var for ocean/ice (vs. no ocean DA in v16)
2. **Hybrid DA**: 80-member ensemble at C192 (vs. static covariances only)
3. **Extended forecast**: 16 days (vs. 10 days in v16)
4. **Physics updates**: Noah-MP land surface, updated microphysics, improved PBL
5. **Coupled S2SW**: Operational subseasonal forecasts (45 days)

**Validation Approach:**
- **Streams**: Different time periods (realtime, stream1-4) test various regimes
  - Winter storms, hurricanes, MJO events, ENSO phases
- **Metrics**: 500mb AC, hurricane track/intensity, tropical precipitation, SST biases
- **Comparison**: v17 vs. v16 vs. ECMWF (international benchmark)

**Stakes for NOAA:**
- Model upgrade affects every weather forecast in US
- Degraded performance → congressional inquiries, public trust erosion
- Hurricane track errors →evacuation decisions, lives at risk
- Agricultural forecasts → billions in economic impacts

**Why These Tests Run Weekly/Monthly (not every PR):**
- Long forecast length (days to weeks)
- High resolution (C384, coupled ocean)
- Comprehensive validation suite
- Resource-intensive (days of compute time)

"""
        elif category == 'weekly':
            context += """### Weekly High-Resolution Regression Testing

**Catching What PR Tests Miss:**
- Resolution-dependent bugs: Physics behave differently at C384 vs. C96
- Numerical stability: Higher resolution more prone to CFL violations, noise
- Scalability: Parallel performance, load balancing at operational scales
- I/O bandwidth: Large file writes stress file systems differently

**Operational Acceptance Criteria:**
- No significant degradation in forecast skill metrics
- Reproducibility across platforms (Hera, WCOSS2, Gaea)
- Performance within operational wallclock limits (2 hours for 16-day forecast)
- No memory leaks or resource exhaustion over long forecasts

**Historical Context:**
- GFS v15→v16 upgrade delayed 6 months due to high-res issues found in weekly tests
- Prevented operational failures that PR tests wouldn't catch
- Balance: Comprehensive testing vs. development velocity

"""
        elif category == 'hires':
            context += """### High-Resolution Testing - Future Operational Readiness

**Research-to-Operations Pipeline:**
- Tests configurations 5-10 years ahead of operational timeline
- Identifies physics issues before they become operational problems
- Validates assumptions in parameterizations at higher resolution

**C768/C1152 Specific Concerns:**
- **Noise**: Higher resolution amplifies numerical instabilities
- **Computational modes**: Grid-scale oscillations in winds, temperature
- **Spectral blocking**: Energy piling up at small scales (needs filtering)
- **Physics-dynamics imbalance**: Convection scheme assumes subgrid, but clouds resolved

**Strategic Importance:**
- Next-generation supercomputers (2026-2028) enable C768 operations
- Testing now prevents repeating v15→v16 upgrade delays
- Informs procurement specs (compute, memory, I/O requirements)

"""
        elif category == 'yamls':
            context += """### Base Configuration Templates - YAML Inheritance System

**Workflow Configuration Philosophy:**
- **DRY principle**: Don't repeat configuration across test cases
- **Inheritance**: Test cases include (`!INC`) base YAML templates
- **Override**: Test-specific settings override template defaults

**Template Categories:**
- `gfs_defaults_ci.yaml`: Standard GFS atmosphere-only settings
- `gfs_cyc_defaults_ci.yaml`: Cycled DA specific settings
- `soca_*.yaml`: Marine DA configurations
- `gefs_defaults_ci.yaml`: Ensemble forecast settings
- `gcafs_*.yaml`: Coupled system configurations

**Why Templates Matter for Operational Consistency:**
- Changes to base template propagate to all derived tests
- Ensures consistency across CI, weekly, v17 validation tests
- Mirrors operational workflow: NCEP uses template system for prod configs
- Reduces human error: One source of truth for standard settings

"""

        # Final GFS ecosystem context
        context += """

## GFS in NOAA's Forecast System Hierarchy

**Upstream Dependencies (GFS depends on):**
- **Observations**: NOAA satellites (GOES, JPSS), international data sharing (WMO)
- **HPC Infrastructure**: NOAA RDHPCS (Hera, Jet), NCEP WCOSS2 (operations)
- **Initial conditions**: GDAS analysis (every 6 hours)

**Downstream Users (who depends on GFS):**
- **Regional models**: NAM, HRRR, RAP (use GFS for boundary conditions)
- **Hurricane models**: HWRF, HAFS (nested in GFS or use GFS ICs)
- **Wave models**: WaveWatch III (forced by GFS winds)
- **Air quality**: CMAQ, HYSPLIT (transport driven by GFS winds)
- **NWS WFOs**: 122 forecast offices use GFS for days 3-16 guidance
- **Private sector**: Airlines, energy companies, agriculture (GFS is public data)
- **International**: 180+ countries, often primary model for small nations

**GFS Failure Impact Scenario:**
- Loss of GFS → no boundary conditions for CONUS models → aviation ground stops
- Hurricane forecasts degraded (HWRF depends on GFS)
- Medium-range forecasts revert to persistence or foreign models
- Economic impact: $500M+/day (conservative estimate)

**Why CI/Testing is Mission-Critical:**
- Every test failure prevented is potential operational outage avoided
- GFS reliability underpins US weather infrastructure
- Testing investment pays for itself many times over in prevented failures

"""
        
        return context

    def generate_documentation(self, parsed: Dict[str, Any]) -> str:
        """Generate markdown documentation for a test case."""
        categories = self.categorize_test_case(parsed)

        doc = f"""# CI Test Case: {parsed['filename']}

## Test Category: {categories['ci_category'].upper()}

**{categories['category_purpose']}**  
**Test Type**: {categories['test_type']}  
**Expected Duration**: {categories['duration']}

## Configuration Overview

- **Test Name**: `{parsed['filename'].replace('.yaml', '')}`
- **Application**: {parsed.get('app', 'unknown')} ({categories['application']})
- **Mode**: {parsed.get('mode', 'unknown')} ({categories['mode']})
- **Network**: {parsed.get('net', 'unknown')}
- **Resolution Tier**: {categories['resolution_tier']}

### Resolutions
"""

        if 'atmos_res' in parsed:
            doc += f"- **Atmosphere**: {parsed['atmos_res']}\n"
        if 'ocean_res' in parsed:
            doc += f"- **Ocean**: {parsed['ocean_res']}\n"
        if 'ice_res' in parsed:
            doc += f"- **Ice**: {parsed['ice_res']}\n"

        doc += f"""
### Experiment Period
- **Start Date**: {parsed.get('idate', 'unknown')}
- **End Date**: {parsed.get('edate', 'unknown')}
- **Duration Category**: {categories['duration']}

## Platform Configuration

"""

        if parsed.get('skip'):
            doc += f"""**Skip Conditions**:
- Platforms to skip: {', '.join(parsed['skip'])}
- Runs on: All other NOAA HPC platforms
"""
        else:
            doc += "- Runs on: All NOAA HPC platforms (hera, orion, hercules, wcoss2, gaea)\n"

        doc += """
## Purpose and Validation

This CI test case validates:
"""

        # Infer validation points from configuration and category
        validations = []
        category = parsed.get('category', '')
        
        # Category-specific validations
        if category == 'pr':
            validations.append("- Fast CI validation for pull requests")
            validations.append("- Basic workflow execution and job completion")
        elif category == 'gfsv17':
            validations.append("- GFS v17 operational configuration compliance")
            validations.append("- Retrospective validation accuracy")
        elif category == 'gcafsv1':
            validations.append("- GCAFS coupled system stability")
        elif category in ['weekly', 'hires']:
            validations.append("- High-resolution model performance")
            validations.append("- Computational efficiency at scale")
        
        # Configuration-specific validations
        if 'cycled' in parsed.get('mode', '').lower():
            validations.append("- Data assimilation cycle completion")
            validations.append("- Analysis and background field generation")
        if parsed.get('app', '').lower() in ['s2s', 's2sw']:
            validations.append("- Coupled atmosphere-ocean-ice system")
            validations.append("- Ocean-atmosphere coupling stability")
        if 'C96' in str(parsed.get('atmos_res', '')):
            validations.append("- Medium resolution atmosphere dynamics")

        doc += '\n'.join(validations) if validations else "- General workflow execution\n"

        # Add meteorological and operational context
        doc += self._get_meteorological_context(parsed, categories)

        doc += f"""

## Configuration Details

```yaml
Application: {parsed.get('app', 'unknown')}
Mode: {parsed.get('mode', 'unknown')}
Network: {parsed.get('net', 'unknown')}
Start: {parsed.get('idate', 'unknown')}
End: {parsed.get('edate', 'unknown')}
```

## Related Information

**Source File**: `{parsed['filepath']}`  
**Repository**: global-workflow  
**Directory**: dev/ci/cases/  
**Documentation Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

*This documentation was automatically generated from CI test case YAML configuration.*
"""

        return doc


class CITestCaseIngestor:
    """Handles ChromaDB ingestion of CI test case documentation."""

    def __init__(self, collection_name: str = "ci-test-cases-v1-0-0"):
        self.collection_name = collection_name
        self.client = None
        self.collection = None

    def connect(self, chromadb_host: str = "127.0.0.1", chromadb_port: int = 8080):
        """Connect to ChromaDB server."""
        try:
            self.client = chromadb.HttpClient(
                host=chromadb_host,
                port=chromadb_port,
                settings=Settings(anonymized_telemetry=False)
            )
            # Test connection
            self.client.heartbeat()
            print(f"[OK] Connected to ChromaDB at {chromadb_host}:{chromadb_port}")
            return True
        except Exception as e:
            print(f"[ERROR] Failed to connect to ChromaDB: {e}")
            return False

    def create_collection(self):
        """Create or get CI test cases collection."""
        try:
            # Try to get existing collection
            self.collection = self.client.get_collection(name=self.collection_name)
            print(f"[OK] Using existing collection: {self.collection_name}")
        except Exception:
            # Create new collection
            self.collection = self.client.create_collection(
                name=self.collection_name,
                metadata={
                    "description": "CI test case documentation",
                    "version": "1.0.0",
                    "created": datetime.now().isoformat(),
                }
            )
            print(f"[OK] Created new collection: {self.collection_name}")

    def ingest_documents(self, documents: List[Dict[str, Any]], dry_run: bool = False):
        """Ingest generated documentation into ChromaDB."""
        if dry_run:
            print(f"[DRY-RUN] Would ingest {len(documents)} documents")
            return

        if not self.collection:
            print("[ERROR] Collection not initialized")
            return

        # Prepare documents for ingestion
        ids = [f"ci-test-{i:03d}" for i in range(len(documents))]
        texts = [doc['content'] for doc in documents]
        metadatas = [doc['metadata'] for doc in documents]

        try:
            self.collection.add(
                ids=ids,
                documents=texts,
                metadatas=metadatas
            )
            print(f"[OK] Ingested {len(documents)} CI test case documents")
        except Exception as e:
            print(f"[ERROR] Ingestion failed: {e}")


class CITestCaseGraphIngestor:
    """Phase 40: Creates CITestCase nodes in Neo4j with platform and config links."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.driver = None
        self.stats = {'nodes': 0, 'platform_edges': 0, 'config_edges': 0}

    def connect(self) -> bool:
        """Connect to Neo4j."""
        if not NEO4J_AVAILABLE:
            print("[WARN] Neo4j driver not available, skipping graph ingestion")
            return False
        try:
            self.driver = Neo4jDriver.driver(
                NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD),
                max_connection_lifetime=3600)
            with self.driver.session() as session:
                session.run("RETURN 1")
            print(f"[OK] Connected to Neo4j: {NEO4J_URI}")
            return True
        except Exception as e:
            print(f"[ERROR] Neo4j connection failed: {e}")
            return False

    def close(self):
        if self.driver:
            self.driver.close()

    def create_indexes(self):
        """Create Neo4j indexes for CITestCase and Platform."""
        indexes = [
            "CREATE INDEX ci_test_name IF NOT EXISTS FOR (t:CITestCase) ON (t.name)",
            "CREATE INDEX platform_name IF NOT EXISTS FOR (p:Platform) ON (p.name)",
        ]
        with self.driver.session() as session:
            for idx in indexes:
                try:
                    session.run(idx)
                except Exception:
                    pass
        print("[OK] Created CITestCase Neo4j indexes")

    def ingest_test_case(self, parsed: Dict, categories: Dict):
        """Create CITestCase node from parsed YAML data."""
        name = parsed.get('filename', '').replace('.yaml', '')
        if not name:
            return

        # Create CITestCase node
        query = """
        MERGE (t:CITestCase {name: $name})
        SET t.resolution = $resolution,
            t.mode = $mode,
            t.app = $app,
            t.net = $net,
            t.idate = $idate,
            t.edate = $edate,
            t.category = $category,
            t.test_type = $test_type,
            t.resolution_tier = $resolution_tier,
            t.skip_hosts = $skip_hosts,
            t.yaml_path = $yaml_path,
            t.version = '40.1.0',
            t.updated_at = $updated_at
        """
        with self.driver.session() as session:
            session.run(query,
                        name=name,
                        resolution=parsed.get('atmos_res', 'unknown'),
                        mode=parsed.get('mode', 'unknown'),
                        app=parsed.get('app', 'unknown'),
                        net=parsed.get('net', 'unknown'),
                        idate=parsed.get('idate', ''),
                        edate=parsed.get('edate', ''),
                        category=parsed.get('category', 'pr'),
                        test_type=categories.get('test_type', 'unknown'),
                        resolution_tier=categories.get('resolution_tier', 'unknown'),
                        skip_hosts=parsed.get('skip', []),
                        yaml_path=parsed.get('filepath', ''),
                        updated_at=datetime.now().isoformat())
        self.stats['nodes'] += 1

        # Create Platform nodes and TESTS_ON edges
        # All HPC platforms that are NOT in skip_hosts
        all_platforms = ['hera', 'hercules', 'orion', 'gaeac5', 'gaeac6', 'wcoss2']
        skip_hosts = [h.lower() for h in parsed.get('skip', [])]
        for platform in all_platforms:
            if platform not in skip_hosts:
                query = """
                MATCH (t:CITestCase {name: $name})
                MERGE (p:Platform {name: $platform})
                MERGE (t)-[:TESTS_ON]->(p)
                """
                with self.driver.session() as session:
                    session.run(query, name=name, platform=platform)
                self.stats['platform_edges'] += 1

    def get_statistics(self) -> dict:
        return self.stats


def main():
    parser = argparse.ArgumentParser(
        description="Ingest CI test case documentation into ChromaDB"
    )
    parser.add_argument(
        '--workflow-root',
        default='/mcp_rag_eib/eib-mcp-rag-server/supported_repos/global-workflow',
        help='Path to global-workflow repository'
    )
    parser.add_argument(
        '--chromadb-host',
        default='127.0.0.1',
        help='ChromaDB server host'
    )
    parser.add_argument(
        '--chromadb-port',
        type=int,
        default=8080,
        help='ChromaDB server port'
    )
    parser.add_argument(
        '--collection',
        default='ci-test-cases-v1-0-0',
        help='ChromaDB collection name'
    )
    parser.add_argument(
        '--discover',
        action='store_true',
        help='Discover test cases only (no processing)'
    )
    parser.add_argument(
        '--generate-docs',
        action='store_true',
        help='Generate documentation only (no ingestion)'
    )
    parser.add_argument(
        '--full',
        action='store_true',
        help='Full pipeline: discover, generate, ingest'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry-run mode (no database writes)'
    )
    parser.add_argument(
        '--output-dir',
        help='Output directory for generated docs (optional)'
    )
    parser.add_argument(
        '--skip-neo4j',
        action='store_true',
        help='Skip Neo4j graph ingestion (ChromaDB only)'
    )

    args = parser.parse_args()

    print("[INIT] CI Test Case Documentation Ingestion v1.0.0")
    print(f"[INFO] Workflow root: {args.workflow_root}")

    # Initialize analyzer
    analyzer = CITestCaseAnalyzer(args.workflow_root)

    # Step 1: Discovery
    print("\n[STEP 1] Discovering CI test cases...")
    test_files = analyzer.discover_test_cases()
    if not test_files:
        print("[ERROR] No test cases found")
        return 1

    if args.discover:
        print(f"\n[OK] Discovery complete: {len(test_files)} files")
        for f in test_files:
            print(f"  - {f.name}")
        return 0

    # Step 2: Parse and generate documentation
    print("\n[STEP 2] Parsing YAML and generating documentation...")
    documents = []
    for filepath in test_files:
        parsed = analyzer.parse_yaml_file(filepath)
        if not parsed:
            continue

        doc_content = analyzer.generate_documentation(parsed)
        categories = analyzer.categorize_test_case(parsed)

        documents.append({
            'content': doc_content,
            'parsed': parsed,
            'categories': categories,
            'metadata': {
                'filename': parsed['filename'],
                'category': parsed.get('category', 'unknown'),
                'category_purpose': categories['category_purpose'],
                'test_type': categories['test_type'],
                'app': parsed.get('app', 'unknown'),
                'mode': parsed.get('mode', 'unknown'),
                'resolution_tier': categories['resolution_tier'],
                'duration': categories['duration'],
                'source': 'ci_test_case',
                'generated_at': datetime.now().isoformat(),
            }
        })

    print(f"[OK] Generated documentation for {len(documents)} test cases")

    # Optionally save to files
    if args.output_dir:
        output_path = Path(args.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        for doc in documents:
            filename = doc['metadata']['filename'].replace('.yaml', '.md')
            with open(output_path / filename, 'w') as f:
                f.write(doc['content'])
        print(f"[OK] Saved documentation to {args.output_dir}")

    if args.generate_docs and not args.full:
        print(f"\n[OK] Documentation generation complete")
        return 0

    # Step 3: Ingest into ChromaDB
    if args.full or not (args.discover or args.generate_docs):
        print("\n[STEP 3] Ingesting into ChromaDB...")
        ingestor = CITestCaseIngestor(collection_name=args.collection)

        if not ingestor.connect(args.chromadb_host, args.chromadb_port):
            print("[ERROR] ChromaDB connection failed")
            return 1

        ingestor.create_collection()
        ingestor.ingest_documents(documents, dry_run=args.dry_run)

        if args.dry_run:
            print("\n[OK] Dry-run complete - no changes made")
        else:
            print("\n[OK] Full ingestion pipeline complete")

    # Step 4: Neo4j graph ingestion (Phase 40)
    if not args.skip_neo4j and not args.discover and not args.generate_docs:
        if not NEO4J_AVAILABLE:
            print("\n[SKIP] Neo4j driver not installed, skipping graph ingestion")
        elif args.dry_run:
            print(f"\n[STEP 4] Neo4j Graph Ingestion (dry-run)")
            print(f"[DRY-RUN] Would create {len(documents)} CITestCase nodes")
            print(f"[DRY-RUN] Would create Platform nodes + TESTS_ON edges")
        else:
            print(f"\n[STEP 4] Ingesting CITestCase nodes into Neo4j...")
            graph_ingestor = CITestCaseGraphIngestor()
            if graph_ingestor.connect():
                graph_ingestor.create_indexes()
                for doc in documents:
                    graph_ingestor.ingest_test_case(
                        doc['parsed'], doc['categories'])
                stats = graph_ingestor.get_statistics()
                print(f"[OK] Neo4j: {stats['nodes']} CITestCase nodes, "
                      f"{stats['platform_edges']} TESTS_ON edges")
                graph_ingestor.close()
            else:
                print("[WARN] Neo4j unavailable, skipping graph ingestion")

    return 0


if __name__ == "__main__":
    sys.exit(main())
