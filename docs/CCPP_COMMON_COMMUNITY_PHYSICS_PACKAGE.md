# Common Community Physics Package (CCPP)

**Date**: December 29, 2025  
**Context**: NOAA Global Workflow / UFS Weather Model  
**Status**: Reference Documentation

---

## What is CCPP?

The **Common Community Physics Package (CCPP)** is a forecast-model agnostic framework that provides:

1. **A framework** (ccpp-framework) - Infrastructure to connect physics schemes with host models
2. **A physics library** (ccpp-physics) - Collection of vetted atmospheric physical parameterizations

### Key Components

| Component | Repository | Purpose |
|-----------|------------|---------|
| **CCPP Framework** | [github.com/NCAR/ccpp-framework](https://github.com/NCAR/ccpp-framework) | Connects physics library to host models like FV3 |
| **CCPP Physics** | [github.com/NCAR/ccpp-physics](https://github.com/NCAR/ccpp-physics) | Library of physics schemes (parameterizations) |

---

## What Does CCPP Do?

CCPP provides **parameterizations** - numerical methods that approximate small-scale atmospheric processes that can't be explicitly resolved by the model:

- **Clouds** - microphysics (mp_thompson)
- **Turbulence** - planetary boundary layer (satmedmfvdifq)
- **Radiation** - shortwave/longwave (rrtmg_sw, rrtmg_lw)
- **Convection** - deep and shallow (samfdeepcnv, samfshalcnv)
- **Surface processes** - land, sea ice, ocean (noahmpdrv, sfc_sice, sfc_nst)
- **Gravity wave drag** - orographic and non-orographic (ugwpv1_gsldrag)

---

## CCPP Suites in Global Workflow

A **suite** is a specific combination of physics schemes configured for a particular application. The Global Workflow uses these suites:

| Suite | Use Case |
|-------|----------|
| `FV3_GFS_v17_p8_ugwpv1` | Default GFS/GEFS standalone atmospheric runs |
| `FV3_GFS_v17_coupled_p8_ugwpv1` | Coupled runs (ATM + ocean/ice) |
| `FV3_global_nest_v1` | Nested grid configurations |
| `FV3_HAFS_v*` | Hurricane Analysis and Forecast System |

---

## Suite Definition Files (SDF)

**Location**: `sorc/ufs_model.fd/UFSATM/ccpp/suites/`

These XML files define which physics schemes run and in what order. For example, the `FV3_GFS_v17_p8_ugwpv1` suite includes:

```
┌─────────────────────────────────────────────────────────────┐
│ CCPP Physics Groups (execution order)                       │
├─────────────────────────────────────────────────────────────┤
│ 1. time_vary     │ Setup, time-varying parameters           │
│ 2. radiation     │ RRTMG shortwave/longwave radiation       │
│ 3. phys_ps       │ Surface physics, PBL, gravity wave drag  │
│ 4. phys_ts       │ Convection, microphysics, photochemistry │
│ 5. stochastics   │ Stochastic physics perturbations         │
└─────────────────────────────────────────────────────────────┘
```

### Example Suite XML Structure

From `suite_FV3_GFS_v17_p8_ugwpv1.xml`:

```xml
<suite name="FV3_GFS_v17_p8_ugwpv1" version="1">
  <group name="time_vary">
    <subcycle loop="1">
      <scheme>GFS_time_vary_pre</scheme>
      <scheme>GFS_rrtmg_setup</scheme>
      <scheme>GFS_rad_time_vary</scheme>
      <scheme>GFS_phys_time_vary</scheme>
    </subcycle>
  </group>
  <group name="radiation">
    <subcycle loop="1">
      <scheme>GFS_rrtmg_pre</scheme>
      <scheme>rrtmg_sw</scheme>
      <scheme>rrtmg_lw</scheme>
      <!-- ... more schemes ... -->
    </subcycle>
  </group>
  <!-- ... additional groups ... -->
</suite>
```

---

## Configuration in Global Workflow

From `config.ufs`:

```bash
# Standalone atmosphere
export CCPP_SUITE="${CCPP_SUITE:-FV3_GFS_v17_p8_ugwpv1}"

# Coupled with ocean/ice (mediator enabled)
export CCPP_SUITE="FV3_GFS_v17_coupled_p8_ugwpv1"

# Nested grids
export CCPP_SUITE="${CCPP_SUITE:-FV3_global_nest_v1}"
```

---

## Key Physics Schemes in GFS v17

| Scheme | Function |
|--------|----------|
| `mp_thompson` | Thompson microphysics (clouds, precipitation) |
| `rrtmg_sw/lw` | RRTMG radiation (heating rates) |
| `satmedmfvdifq` | Scale-aware TKE-based PBL scheme |
| `samfdeepcnv` | Scale-aware mass-flux deep convection |
| `samfshalcnv` | Scale-aware mass-flux shallow convection |
| `noahmpdrv` | Noah-MP land surface model |
| `ugwpv1_gsldrag` | Unified gravity wave physics v1 |

---

## Available Suites (Full List)

Located in `sorc/ufs_model.fd/UFSATM/ccpp/suites/`:

```
suite_FV3_coupled_lowres.xml
suite_FV3_GFS_v15p2.xml
suite_FV3_GFS_v15_thompson_mynn_lam3km.xml
suite_FV3_GFS_v16_csawmg.xml
suite_FV3_GFS_v16_flake.xml
suite_FV3_GFS_v16_fv3wam.xml
suite_FV3_GFS_v16_gfdlmpv3.xml
suite_FV3_GFS_v16_ras.xml
suite_FV3_GFS_v16.xml
suite_FV3_GFS_v17_coupled_p8_c3.xml
suite_FV3_GFS_v17_coupled_p8_sfcocn.xml
suite_FV3_GFS_v17_coupled_p8_ugwpv1.xml
suite_FV3_GFS_v17_coupled_p8.xml
suite_FV3_GFS_v17_p8_c3.xml
suite_FV3_GFS_v17_p8_mynn.xml
suite_FV3_GFS_v17_p8_rrtmgp.xml
suite_FV3_GFS_v17_p8_ugwpv1_tempo.xml
suite_FV3_GFS_v17_p8_ugwpv1.xml          ← Default for GFS/GEFS
suite_FV3_GFS_v17_p8.xml
suite_FV3_global_nest_v1.xml             ← For nested grids
suite_FV3_HAFS_v1_gfdlmp_tedmf_nonsst.xml
suite_FV3_HAFS_v1_gfdlmp_tedmf.xml
suite_FV3_HAFS_v1_gfdlmpv3_tedmf.xml
suite_FV3_HAFS_v1_thompson_nonsst.xml
suite_FV3_HAFS_v1_thompson_tedmf_gfdlsf.xml
suite_FV3_HAFS_v1_thompson.xml
suite_FV3_HRRR_c3.xml
```

---

## Related Documentation

- **UFS Weather Model Users Guide**: https://ufs-weather-model.readthedocs.io/
- **CCPP Documentation**: https://ccpp-techdoc.readthedocs.io/
- **CCPP Physics Documentation**: https://dtcenter.ucar.edu/GMTB/v7.0.0/sci_doc/

---

## Future Exploration Topics

Would you like me to dive deeper into any specific aspect of CCPP, such as:

1. **How a particular physics scheme works** - e.g., Thompson microphysics, RRTMG radiation, or the scale-aware convection schemes
2. **How to modify suite configurations** - Adding/removing schemes, changing execution order
3. **Stochastic physics** - SKEB, SPPT, SHUM, SPP schemes and how they add ensemble spread
4. **Comparing GFS v16 vs v17 physics** - What changed between versions
5. **CCPP for HAFS** - Hurricane-specific physics configurations
6. **Creating a custom physics suite** - Steps to define and test a new suite
7. **Physics tendencies output** - How to diagnose which schemes are contributing to forecast changes

---

*Document generated from EIB MCP-RAG Server conversation, December 29, 2025*
