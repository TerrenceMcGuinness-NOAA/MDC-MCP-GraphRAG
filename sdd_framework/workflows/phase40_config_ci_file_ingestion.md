# Phase 40: Configuration and CI File Ingestion

**Version**: 1.3.0
**Status**: Planned (all steps executable locally on MCP development platform)
**Created**: 2026-03-06
**Updated**: 2026-03-11 — EXPDIR ported locally from Gaea C6 CI nightly pipeline; removed RDHPCS dependency for ingestion
**Author**: AI Assistant + Terry McGuinness
**Dependency**: Phase 38 (path normalization), Phase 39 (Fortran graph — for community re-detection)
**Downstream**: Phase 45 (EnKF esfc CTest — requires EXPDIR config data in GraphRAG)
**Gap Analysis**: [docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md](../../docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md) §3.2, §7-C

---

## 1. Executive Summary

Three categories of files are not ingested into any knowledge base collection:

| File Category | Location | Count | Why It Matters |
|--------------|----------|-------|---------------|
| **Configuration files** | `dev/parm/config/{gfs,gefs,gcafs,sfs}` | 146 | Define every experiment parameter — env vars, resolution, physics options |
| **CI test definitions** | `dev/ci/cases/pr/*.yaml` | 21 | Define all supported test cases, platforms, and expected configurations |
| **Jinja2 templates** | `dev/parm/*.j2`, `dev/scripts/*.j2` | 26 | Generate actual configs at runtime — the template logic is invisible |
| **Rocoto generators** | `dev/workflow/rocoto/*.py` | ~12 | Generate job dependency XML — the orchestration backbone (no static XML in repo) |
| **EXPDIR artifacts** | `supported_repos/EXPDIR/` (ported from Gaea C6 CI nightly) | 15 experiments | Resolved configs + generated XML from nightly CI — the ground truth |

These files are critical for answering questions like "What configs control ocean coupling?", "Which CI tests cover the C384 resolution?", and "What's the job dependency for post-processing?" — but the expert system currently cannot search or reason about them.

### Approach

- **Configs and YAML** → ChromaDB vectors (semantic search + env var extraction)
- **Configs** → Neo4j `ConfigFile` nodes with `SETS_ENV` edges to `EnvironmentVariable` nodes
- **Jinja2 templates** → ChromaDB vectors with template variable metadata
- **Rocoto XML** → Neo4j `RocotoTask` nodes with `DEPENDS_ON` edges (job dependency graph)

---

## 2. File Inventory

### 2.1 Configuration Files (`dev/parm/config/`)

```
dev/parm/config/gfs/   — 102 files (GFS operational configs)
dev/parm/config/gefs/  —  21 files (GEFS ensemble configs)
dev/parm/config/gcafs/ —  18 files (GCAFS coupled configs)
dev/parm/config/sfs/   —   5 files (SFS seasonal configs)
                          ───
                          146 total
```

Each `config.*` file is a POSIX shell fragment that exports environment variables:
```bash
#!/bin/bash
# config.fcst - Forecast configuration
export FHMAX_GFS=${FHMAX_GFS:-384}
export DELTIM=${DELTIM:-450}
export layout_x=${layout_x:-8}
export layout_y=${layout_y:-16}
export WRITE_GROUP=${WRITE_GROUP:-1}
export WRTTASK_PER_GROUP=${WRTTASK_PER_GROUP:-40}
```

### 2.2 CI Test YAML (`dev/ci/`)

```yaml
# Example: dev/ci/cases/pr/C48_S2SW.yaml
experiment:
  name: C48_S2SW
  resolution: C48
  mode: coupled
  components: [atm, ocn, ice, wav]
  FHMAX: 24
  CI_PLATFORM: [hera, orion]
```

These define the full matrix of CI test cases — resolution, coupling mode, component selection, platform.

### 2.3 Jinja2 Templates

Files like `dev/parm/config.base.j2` and `dev/scripts/exgfs_fcst.sh.j2` contain Jinja2 template syntax:
```
{% if DO_COUPLED == "YES" %}
export cpl_ocn=".true."
export cpl_wav=".true."
{% endif %}
```

### 2.4 Rocoto Workflow XML (Generated, not static)

The repo does **not** contain static Rocoto XML files. Instead, `dev/workflow/rocoto/*.py` generates XML programmatically at experiment creation time via `setup_workflow.py`:

```python
# dev/workflow/rocoto/rocoto_xml.py:159
xml_file = f"{self.expdir}/{self.pslot}.xml"   # writes to EXPDIR
```

Key Rocoto generator modules:
- `gfs_tasks.py` — GFS task definitions (forecast, analysis, post, etc.)
- `gefs_tasks.py` — GEFS ensemble tasks
- `gcafs_tasks.py` — GCAFS coupled tasks
- `rocoto_xml.py` — XML assembly + write to `{EXPDIR}/{PSLOT}.xml`
- `rocoto_xml_factory.py` — Factory for selecting the right XML builder

**Consequence**: To ingest the Rocoto job DAG, we must parse the **generated** XML from EXPDIRs (Step 40-6), not static files from the repo.

### 2.5 EXPDIR Artifacts (Ported from Gaea C6 CI Nightly)

The EXPDIR has been copied from a Gaea C6 CI nightly pipeline run and ported to the local MCP development platform at `supported_repos/EXPDIR/`. This is a snapshot of the resolved (fully materialized) configuration for all 15 experiment cases defined in `dev/ci/cases/pr/`. Because the ingestion scripts must run on the MCP development platform (where ChromaDB and Neo4j are hosted), we port the EXPDIR artifacts here rather than running ingestion on an RDHPCS system.

**Source**: Gaea C6 CI nightly pipeline (`/gpfs/f6/drsa-precip3/world-shared/global/CI/GITLAB/stable/RUNTESTS/EXPDIR/`)
**Local path**: `supported_repos/EXPDIR/`

Each experiment directory follows the naming convention `{CASE}_{COMMIT_HASH}/` and contains:

```
supported_repos/EXPDIR/{PSLOT}_{HASH}/
├── config.base         # Resolved: FHMAX, resolution, paths all filled in
├── config.fcst         # Resolved: layout_x, layout_y, DELTIM concrete values
├── config.resources    # Resolved: node counts, memory, walltime per task
├── config.resources.*  # Per-platform resource overrides (HERA, GAEAC6, etc.)
├── config.anal         # Resolved: analysis settings
├── config.*            # ... (mirrors dev/parm/config/gfs/ but with experiment values)
├── {PSLOT}.xml         # Generated Rocoto XML — full job DAG with concrete paths
├── {PSLOT}.crontab     # Cron schedule for the experiment
└── {PSLOT}.scron.sh    # Slurm cron launcher script
```

**15 ported experiments** (matching the Gaea C6 CI `pr` case matrix):

| Experiment | Type |
|------------|------|
| `C48_ATM` | Atmosphere-only |
| `C48_S2SW` | Coupled S2SW |
| `C48_S2SWA_gefs` | GEFS coupled |
| `C48_gsienkf_atmDA` | GSI EnKF DA |
| `C48_ufsenkf_atmDA` | UFS EnKF DA |
| `C48mx500_3DVarAOWCDA` | 3DVar ocean-coupled DA |
| `C48mx500_hybAOWCDA` | Hybrid ocean-coupled DA |
| `C96_atm3DVar` | C96 atm 3DVar |
| `C96_gcafs_cycled` | GCAFS cycled |
| `C96_gcafs_cycled_noDA` | GCAFS cycled no DA |
| `C96mx100_S2S` | C96 S2S |
| `C96C48_hybatmDA` | Hybrid atm DA |
| `C96C48_hybatmsnowDA` | Hybrid atm+snow DA |
| `C96C48_hybatmsoilDA` | Hybrid atm+soil DA |
| `C96C48mx500_S2SW_cyc_gfs` | Coupled cycled GFS |

#### Original Per-Platform EXPDIR Paths (Reference)

The ported EXPDIR was sourced from Gaea C6. For reference, the per-platform CI paths are:

| Platform | EXPDIR Base |
|----------|-------------|
| **Gaea C6** (source) | `/gpfs/f6/drsa-precip3/world-shared/global/CI/GITLAB/stable/RUNTESTS/EXPDIR/` |
| **Hera** | `${GFS_CI_ROOT}/BUILDS/GITLAB/stable/RUNTESTS/EXPDIR/` |
| **Hercules** | `${GFS_CI_ROOT}/BUILDS/GITLAB/stable/RUNTESTS/EXPDIR/` |

The 15 ported experiments match the Gaea C6 CI nightly `pr` case matrix. Hera runs 17 cases (adds `C96C48_ufsgsi_hybatmDA`, `C96C48_ufs_hybatmDA`); Hercules and Orion run fewer.

**Notable**: Orion and Hercules do **not** run `C48_gsienkf_atmDA` or `C48_ufsenkf_atmDA` — the EnKF cases where the esfc bug manifests (see Phase 45). These cases are skipped via `skip_ci_on_hosts` in the PR YAML but the matrix here shows they're also absent from the nightly host matrices.

---

## 3. Technical Specification

### Target Files

| File | Purpose | Database |
|------|---------|----------|
| `mcp_server_node/scripts/ingest_config_files.py` | **NEW** — config file ingestion | ChromaDB + Neo4j |
| `mcp_server_node/scripts/ingest_ci_test_cases.py` | **MODIFY** — already exists (1114 lines), enhance with Neo4j | ChromaDB + Neo4j |
| `mcp_server_node/scripts/ingest_jinja2_templates.py` | **NEW** — Jinja2 template ingestion | ChromaDB |
| `mcp_server_node/scripts/ingest_rocoto_xml.py` | **NEW** — Rocoto XML parser (job flow DAG + dependencies) | Neo4j + ChromaDB |
| `mcp_server_node/scripts/ingest_expdir_configs.py` | **NEW** — EXPDIR resolved config + XML ingestion | Neo4j + ChromaDB |

### Neo4j Schema Additions

```
# Config file nodes (Step 40-2)
(:ConfigFile {name, file_path, category})
(:ConfigFile)-[:SETS_ENV {value, is_default}]->(:EnvironmentVariable)
(:ConfigFile)-[:SOURCED_BY]->(:ShellScript)

# Rocoto job DAG (Step 40-5) — the core job flow and dependency graph
(:RocotoTask {name, command, cycledefs, maxtries, walltime, nodes_spec, cores,
              queue, memory, is_final, experiment, platform, dependency_tree_json})
(:RocotoTask)-[:DEPENDS_ON {dep_type, cycle_offset, condition}]->(:RocotoTask)
(:RocotoTask)-[:DEPENDS_ON_DATA {path_pattern, age}]->(:DataDependency)
(:RocotoTask)-[:RUNS_SCRIPT]->(:ShellScript)
(:RocotoTask)-[:USES_ENV]->(:EnvironmentVariable)
(:RocotoTask)-[:MEMBER_OF]->(:RocotoMetatask)
(:RocotoTask)-[:RUNS_ON]->(:RocotoCycledef)

(:RocotoMetatask {name, mode, variables, member_count})
(:RocotoCycledef {group, definition})

# CI test cases (Step 40-3)
(:CITestCase {name, resolution, mode, fhmax})
(:CITestCase)-[:TESTS_ON]->(:Platform {name})
(:CITestCase)-[:USES_CONFIG]->(:ConfigFile)

# EXPDIR resolved configs (Step 40-6)
(:EXPDIRConfig)-[:RESOLVES_FROM]->(:ConfigFile)
(:EXPDIRConfig)-[:SETS_ENV]->(:EnvironmentVariable)
(:EXPDIRConfig)-[:PART_OF]->(:Experiment {name, platform, resolution, date})
```

### ChromaDB Collections

- Config files → `code-with-context-v8-0-0` (with `file_type: 'config'` metadata)
- CI YAML → `code-with-context-v8-0-0` (with `file_type: 'ci-test'` metadata)
- Jinja2 → `code-with-context-v8-0-0` (with `file_type: 'jinja2-template'` metadata)

---

## 4. Implementation Steps

### Step 40-1: Audit Config File Structure
**Tag**: validate
**Target**: Terminal

Survey the actual config file formats and env var patterns:

```bash
cd supported_repos/global-workflow
# Count files by pattern
find dev/parm -name "config.*" -type f | wc -l
# Sample env var exports
grep -h "^export " dev/parm/config.base dev/parm/config.fcst | head -30
# Check for Jinja2 templates
find dev/parm dev/scripts -name "*.j2" -type f
# Check for XML
find dev -name "*.xml" -type f
```

**Acceptance**: File counts and format patterns documented for implementation.

---

### Step 40-2: Create Config File Ingestion Script
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_config_files.py`

Parse each `config.*` file to extract:
1. **Environment variables**: name, default value, description (from inline comments)
2. **Conditional logic**: `if/then/fi` blocks that set vars based on other vars
3. **Source chains**: other configs sourced by this one (`source config.base`)

Ingest into:
- **ChromaDB**: Full text chunk with metadata `{file_path, file_type: 'config', category, env_vars: [list]}`
- **Neo4j**: `ConfigFile` node → `SETS_ENV` → `EnvironmentVariable` edges

```python
ENV_PATTERN = re.compile(
    r'^(?:export\s+)?([A-Z_][A-Z0-9_]*)=(?:\$\{[^}]*:-)?([^}"\n]*)'
)

def parse_config_file(file_path: str) -> dict:
    """Extract environment variables and metadata from a config file."""
    env_vars = []
    sources = []
    with open(file_path) as f:
        for line in f:
            # Skip comments (but capture inline comments as descriptions)
            m = ENV_PATTERN.match(line.strip())
            if m:
                env_vars.append({
                    'name': m.group(1),
                    'default_value': m.group(2).strip('"\''),
                })
            if line.strip().startswith(('source ', '. ')):
                # Track sourced configs
                sources.append(line.strip().split()[-1])
    return {'env_vars': env_vars, 'sources': sources}
```

**Features**:
- `--dry-run` mode
- Category detection from filename (`config.fcst` → `forecast`, `config.anal` → `analysis`)
- Links to existing `EnvironmentVariable` nodes in Neo4j

**Acceptance**: 155 config files ingested. New `ConfigFile` nodes visible in Neo4j. Env var `FHMAX_GFS` traceable from config → env graph.

---

### Step 40-3: Enhance CI Test Case Ingestion
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_ci_test_cases.py`

If the existing script covers basic ingestion, enhance it to:
1. Parse the YAML structure for experiment metadata (resolution, coupling mode, components)
2. Create `CITestCase` nodes in Neo4j with search-friendly properties
3. Link test cases to platforms and configs

**Acceptance**: `MATCH (t:CITestCase) RETURN t.name, t.resolution, t.mode` returns all CI test definitions.

---

### Step 40-4: Create Jinja2 Template Ingestion Script
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_jinja2_templates.py`

Parse `.j2` files to extract:
1. Template variables (`{{ var_name }}`)
2. Conditional blocks (`{% if ... %}`)
3. Loop constructs (`{% for ... %}`)

Ingest as ChromaDB vectors with template metadata for semantic search.

```python
JINJA_VAR = re.compile(r'\{\{\s*(\w+)\s*\}\}')
JINJA_BLOCK = re.compile(r'\{%\s*(if|for|elif|else|endif|endfor)\s+(.+?)\s*%\}')
```

**Acceptance**: Jinja2 templates searchable via `search_documentation({ query: "ocean coupling template variables" })`.

---

### Step 40-5: Create Rocoto XML Ingestion Script (Job Flow & Dependency Parser)
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_rocoto_xml.py`
**Priority**: HIGH — this parser is the key to capturing the operational job DAG

#### 40-5a: XML Schema Reference

The generated Rocoto XML from `{EXPDIR}/{PSLOT}.xml` has this structure:

```xml
<?xml version="1.0"?>
<!DOCTYPE workflow [
    <!ENTITY PSLOT "C48_gsienkf_atmDA">
    <!ENTITY ROTDIR "/scratch1/.../ROTDIRS/C48_gsienkf_atmDA">
    <!ENTITY MAXTRIES "2">
]>
<workflow realtime="F" scheduler="slurm" cyclethrottle="5" taskthrottle="20">
    <log verbosity="10"><cyclestr>...</cyclestr></log>
    <cycledef group="gdas_half">...</cycledef>
    <cycledef group="gdas">...</cycledef>
    <cycledef group="gfs">...</cycledef>

    <!-- Tasks and metatasks (the job DAG) -->
    <task name="..." cycledefs="..." maxtries="&MAXTRIES;">...</task>
    <metatask name="..." mode="parallel|serial">
        <var name="member">001 002 ... 080</var>
        <task name="..._mem#member#" ...>...</task>
    </metatask>
</workflow>
```

#### 40-5b: Parser Design

The parser must handle these Rocoto-specific challenges:
1. **DOCTYPE entities** (`&PSLOT;`, `&MAXTRIES;`) — resolve before parsing (ET cannot handle unresolved entities)
2. **Metatask nesting** — metatasks can wrap other metatasks; must recurse
3. **Compound dependencies** — `<and>`, `<or>`, `<not>` can nest arbitrarily deep inside `<dependency>`
4. **`<cyclestr>` tokens** — `@Y@m@d@H` inside path strings (preserve as metadata, don't resolve)
5. **`#varname#`** — metatask variable substitution in task names and envars

```python
import re
import xml.etree.ElementTree as ET
from pathlib import Path


def resolve_entities(xml_text: str) -> tuple[str, dict]:
    """Resolve DOCTYPE entity definitions and return clean XML + entity map.

    Parameters
    ----------
    xml_text : str
        Raw XML text with DOCTYPE entity definitions.

    Returns
    -------
    tuple[str, dict]
        Cleaned XML string with entities resolved, and dict of entity names → values.
    """
    entities = {}
    for match in re.finditer(r'<!ENTITY\s+(\w+)\s+"([^"]*)">', xml_text):
        entities[match.group(1)] = match.group(2)

    # Strip the DOCTYPE block entirely (ET cannot parse it)
    clean = re.sub(r'<!DOCTYPE[^>]*\[.*?\]>', '', xml_text, flags=re.DOTALL)

    # Replace &ENTITY; references with resolved values
    for name, value in entities.items():
        clean = clean.replace(f'&{name};', value)

    return clean, entities


def parse_dependency_tree(dep_element) -> dict:
    """Recursively parse a <dependency> block into a structured dict.

    Handles: <and>, <or>, <not>, <taskdep>, <metataskdep>,
             <datadep>, <cycleexistdep>, <taskvalid>, <streq>,
             <strneq>, <sh>

    Parameters
    ----------
    dep_element : xml.etree.ElementTree.Element
        A dependency element or logical operator element.

    Returns
    -------
    dict
        Nested dict representing the dependency tree.
        Leaf nodes: {'type': 'task', 'name': '...', 'cycle_offset': '...'}
        Branch nodes: {'operator': 'and'|'or'|'not', 'children': [...]}
    """
    tag = dep_element.tag

    if tag in ('and', 'or'):
        return {
            'operator': tag,
            'children': [parse_dependency_tree(child) for child in dep_element]
        }
    elif tag == 'not':
        children = [parse_dependency_tree(child) for child in dep_element]
        return {'operator': 'not', 'children': children}
    elif tag == 'taskdep':
        return {
            'type': 'task',
            'name': dep_element.get('task'),
            'cycle_offset': dep_element.get('cycle_offset')
        }
    elif tag == 'metataskdep':
        return {
            'type': 'metatask',
            'name': dep_element.get('metatask'),
            'cycle_offset': dep_element.get('cycle_offset')
        }
    elif tag == 'datadep':
        cyclestr = dep_element.find('cyclestr')
        path = cyclestr.text if cyclestr is not None else (dep_element.text or '')
        offset = cyclestr.get('offset') if cyclestr is not None else None
        return {
            'type': 'data',
            'path': path.strip(),
            'offset': offset,
            'age': dep_element.get('age')
        }
    elif tag == 'cycleexistdep':
        return {
            'type': 'cycleexist',
            'cycle_offset': dep_element.get('cycle_offset')
        }
    elif tag == 'taskvalid':
        return {
            'type': 'taskvalid',
            'name': dep_element.get('task')
        }
    elif tag in ('streq', 'strneq'):
        left = dep_element.findtext('left', '')
        right = dep_element.findtext('right', '')
        return {'type': tag, 'left': left, 'right': right}
    elif tag == 'sh':
        cyclestr = dep_element.find('cyclestr')
        cmd = cyclestr.text if cyclestr is not None else (dep_element.text or '')
        return {
            'type': 'shell',
            'command': cmd.strip(),
            'shell': dep_element.get('shell', '/bin/sh')
        }
    elif tag == 'dependency':
        # <dependency> is just a wrapper — recurse into its single child
        children = list(dep_element)
        if len(children) == 1:
            return parse_dependency_tree(children[0])
        # Multiple children without operator = implicit AND
        return {
            'operator': 'and',
            'children': [parse_dependency_tree(c) for c in children]
        }
    else:
        return {'type': 'unknown', 'tag': tag, 'attrib': dep_element.attrib}


def extract_task_deps_flat(dep_tree: dict) -> list[str]:
    """Flatten a dependency tree to a list of task/metatask names.

    Parameters
    ----------
    dep_tree : dict
        Structured dependency tree from parse_dependency_tree().

    Returns
    -------
    list[str]
        Flat list of task/metatask names this task depends on.
    """
    names = []
    if 'operator' in dep_tree:
        for child in dep_tree.get('children', []):
            names.extend(extract_task_deps_flat(child))
    elif dep_tree.get('type') in ('task', 'metatask', 'taskvalid'):
        if dep_tree.get('name'):
            names.append(dep_tree['name'])
    return names


def parse_task_element(task_el) -> dict:
    """Parse a single <task> element into a structured dict.

    Parameters
    ----------
    task_el : xml.etree.ElementTree.Element
        A <task> XML element.

    Returns
    -------
    dict
        Task properties: name, cycledefs, command, resources, envars, dependencies.
    """
    name = task_el.get('name')
    cycledefs = task_el.get('cycledefs', '')
    maxtries = task_el.get('maxtries', '1')
    is_final = task_el.get('final', 'false') == 'true'

    command = task_el.findtext('command', '').strip()

    # Resources
    resources = {
        'walltime': task_el.findtext('walltime'),
        'queue': task_el.findtext('queue'),
        'account': task_el.findtext('account'),
        'partition': task_el.findtext('partition'),
        'memory': task_el.findtext('memory'),
        'native': task_el.findtext('native'),
    }
    nodes_el = task_el.findtext('nodes')
    cores_el = task_el.findtext('cores')
    if nodes_el:
        resources['nodes_spec'] = nodes_el  # e.g. "8:ppn=40:tpp=1"
    elif cores_el:
        resources['cores'] = int(cores_el)

    # Environment variables
    envars = {}
    for envar in task_el.findall('envar'):
        var_name = envar.findtext('name', '')
        val_el = envar.find('value')
        if val_el is not None:
            # Value may contain <cyclestr> children
            cyclestr = val_el.find('cyclestr')
            if cyclestr is not None:
                var_value = f'<cyclestr>{cyclestr.text or ""}</cyclestr>'
            else:
                var_value = val_el.text or ''
        else:
            var_value = ''
        envars[var_name] = var_value

    # Dependencies
    dep_el = task_el.find('dependency')
    dep_tree = parse_dependency_tree(dep_el) if dep_el is not None else {}
    dep_names = extract_task_deps_flat(dep_tree)

    # Log path
    join_el = task_el.find('join')
    log_path = None
    if join_el is not None:
        cyclestr = join_el.find('cyclestr')
        log_path = cyclestr.text if cyclestr is not None else join_el.text

    return {
        'name': name,
        'cycledefs': cycledefs,
        'maxtries': maxtries,
        'is_final': is_final,
        'command': command,
        'resources': {k: v for k, v in resources.items() if v is not None},
        'envars': envars,
        'dependency_tree': dep_tree,
        'dependency_names': dep_names,  # flat list for quick edge creation
        'log_path': log_path,
    }


def parse_metatask_element(metatask_el) -> dict:
    """Parse a <metatask> element (may contain nested metatasks).

    Parameters
    ----------
    metatask_el : xml.etree.ElementTree.Element
        A <metatask> XML element.

    Returns
    -------
    dict
        Metatask properties: name, mode, variables, and nested tasks/metatasks.
    """
    name = metatask_el.get('name')
    mode = metatask_el.get('mode', 'parallel')

    # Metatask variables (e.g., <var name="member">001 002 ...</var>)
    variables = {}
    for var_el in metatask_el.findall('var'):
        var_name = var_el.get('name')
        var_values = (var_el.text or '').split()
        variables[var_name] = var_values

    # Nested tasks and metatasks
    tasks = []
    nested_metatasks = []
    for child in metatask_el:
        if child.tag == 'task':
            tasks.append(parse_task_element(child))
        elif child.tag == 'metatask':
            nested_metatasks.append(parse_metatask_element(child))

    return {
        'name': name,
        'mode': mode,
        'variables': variables,
        'tasks': tasks,
        'nested_metatasks': nested_metatasks,
    }


def parse_rocoto_xml(xml_path: str) -> dict:
    """Parse a complete Rocoto workflow XML file.

    Parameters
    ----------
    xml_path : str
        Path to the Rocoto XML file (e.g., {EXPDIR}/{PSLOT}.xml).

    Returns
    -------
    dict
        Complete workflow structure: entities, cycledefs, tasks, metatasks.
    """
    raw_xml = Path(xml_path).read_text()
    clean_xml, entities = resolve_entities(raw_xml)
    root = ET.fromstring(clean_xml)

    # Workflow-level attributes
    workflow = {
        'scheduler': root.get('scheduler'),
        'realtime': root.get('realtime'),
        'cyclethrottle': root.get('cyclethrottle'),
        'taskthrottle': root.get('taskthrottle'),
    }

    # Cycle definitions
    cycledefs = []
    for cd in root.findall('cycledef'):
        cycledefs.append({
            'group': cd.get('group'),
            'definition': cd.text.strip() if cd.text else '',
        })

    # Top-level tasks and metatasks
    tasks = []
    metatasks = []
    for child in root:
        if child.tag == 'task':
            tasks.append(parse_task_element(child))
        elif child.tag == 'metatask':
            metatasks.append(parse_metatask_element(child))

    return {
        'source_file': xml_path,
        'entities': entities,
        'workflow': workflow,
        'cycledefs': cycledefs,
        'tasks': tasks,
        'metatasks': metatasks,
    }
```

#### 40-5c: Neo4j Schema for Job Flow Graph

```
# Task nodes — one per <task> in the XML
(:RocotoTask {
    name: str,              # e.g. "enkfgdas_esfc", "gdas_fcst_seg0"
    command: str,           # e.g. "/path/dev/job_cards/rocoto/esfc.sh"
    cycledefs: str,         # e.g. "gdas" or "gdas_half,gdas"
    maxtries: str,          # e.g. "2"
    walltime: str,          # e.g. "00:30:00"
    nodes_spec: str,        # e.g. "8:ppn=40:tpp=1" or null
    cores: int,             # e.g. 1 (if single-core task)
    queue: str,             # e.g. "batch"
    memory: str,            # e.g. "96GB" or null
    is_final: bool,         # true for workflow-finalize tasks
    experiment: str,        # e.g. "C48_gsienkf_atmDA" (from PSLOT entity)
    platform: str           # e.g. "hera" (from partition or native flags)
})

# Metatask grouping
(:RocotoMetatask {
    name: str,              # e.g. "enkfgdas_fcst"
    mode: str,              # "parallel" or "serial"
    variables: str,         # JSON: {"member": ["001","002",...,"080"]}
    member_count: int       # e.g. 80
})

# Cycle definitions
(:RocotoCycledef {
    group: str,             # e.g. "gdas", "gfs", "gdas_half"
    definition: str         # e.g. "202301010600 202312310000 06:00:00"
})

# Relationships — the core job DAG
(:RocotoTask)-[:DEPENDS_ON {
    dep_type: str,          # "task" | "metatask" | "data" | "cycleexist"
    cycle_offset: str,      # e.g. "-06:00:00" or null
    condition: str           # "and" | "or" | "not" (from parent operator)
}]->(:RocotoTask)

(:RocotoTask)-[:DEPENDS_ON_DATA {
    path_pattern: str,      # e.g. "/rotdir/gdas.t@Hz.atmf009.nc"
    age: str                # e.g. "00:05:00"
}]->(:DataDependency)      # virtual node for file-based deps

(:RocotoTask)-[:MEMBER_OF]->(:RocotoMetatask)
(:RocotoTask)-[:RUNS_ON]->(:RocotoCycledef)

# Cross-links to existing graph nodes
(:RocotoTask)-[:RUNS_SCRIPT]->(:ShellScript)    # command → ex-script match
(:RocotoTask)-[:USES_ENV]->(:EnvironmentVariable) # from <envar> elements
```

#### 40-5d: Dependency Flattening Strategy

The dependency tree can be deeply nested. For Neo4j edges, flatten to direct task→task edges with metadata:

| XML Pattern | Neo4j Edge |
|-------------|-----------|
| `<taskdep task="gdas_anal"/>` | `(esfc)-[:DEPENDS_ON {dep_type:"task"}]->(anal)` |
| `<metataskdep metatask="enkfgdas_epmn" cycle_offset="-06:00:00"/>` | `(efcs)-[:DEPENDS_ON {dep_type:"metatask", cycle_offset:"-06:00:00"}]->(epmn)` |
| `<datadep age="00:05:00"><cyclestr>/path/file.nc</cyclestr></datadep>` | `(post)-[:DEPENDS_ON_DATA {path_pattern:"/path/file.nc", age:"00:05:00"}]->(data_node)` |
| `<cycleexistdep cycle_offset="-06:00:00"/>` | Stored as task property `has_cycleexist_dep: true` |
| `<not><cycleexistdep .../></not>` | Stored as `has_not_cycleexist_dep: true` (cold-start branch) |

**The full dependency tree is also preserved** as a JSON property on the task node (`dependency_tree_json`) for tools that need the exact logical structure (`and`/`or`/`not` operators).

#### 40-5e: Script-to-Task Cross-Linking

The `<command>` element typically points to `{HOMEglobal}/dev/job_cards/rocoto/{task}.sh`, which in turn calls the JJOB `dev/jobs/JGDAS_{TASK}` or `dev/jobs/JGFS_{TASK}`. The parser creates `[:RUNS_SCRIPT]` edges by matching command paths to existing `ShellScript` nodes already in Neo4j from `ingest_shell_graph_v8.py`.

```python
def match_command_to_script(command: str, neo4j_session) -> str | None:
    """Match a Rocoto task command to an existing ShellScript node.

    Parameters
    ----------
    command : str
        The <command> value, e.g. "/path/dev/job_cards/rocoto/esfc.sh"
    neo4j_session
        Active Neo4j session.

    Returns
    -------
    str or None
        The matched ShellScript node path, or None if no match.
    """
    # Extract the script basename from the command path
    script_name = Path(command).name  # e.g. "esfc.sh"
    result = neo4j_session.run(
        "MATCH (s:ShellScript) WHERE s.path ENDS WITH $name RETURN s.path LIMIT 1",
        name=script_name
    )
    record = result.single()
    return record['s.path'] if record else None
```

#### 40-5f: Acceptance Criteria

- `MATCH (t:RocotoTask) RETURN COUNT(t)` → 30-80 tasks per experiment (varies by experiment type)
- `MATCH (t:RocotoTask)-[:DEPENDS_ON]->(d:RocotoTask) RETURN t.name, d.name` → complete job DAG
- `MATCH (t:RocotoTask)-[:RUNS_SCRIPT]->(s:ShellScript) RETURN t.name, s.path` → task↔script linkage
- `MATCH (t:RocotoTask {name: 'enkfgdas_esfc'}) RETURN t.dependency_names` → `["gdas_analcalc", "enkfgdas_eupd"]`
- `MATCH (m:RocotoMetatask {name: 'enkfgdas_fcst'})<-[:MEMBER_OF]-(t) RETURN m.member_count, COUNT(t)` → ensemble size verified
- `--dry-run` mode: parses XML, prints task/dependency summary, creates no database nodes

---

### Step 40-6: Create EXPDIR Config & XML Ingestion Script
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_expdir_configs.py`

Ingest experiment directory (EXPDIR) XML and config files from the ported Gaea C6 CI nightly artifacts at `supported_repos/EXPDIR/`. EXPDIRs contain the materialized configuration that drives a specific experiment — the resolved versions of template configs with experiment-specific values filled in.

The EXPDIR has been ported to the MCP development platform so all ingestion runs locally — no RDHPCS access required. The 15 experiment directories cover all `ci/cases/pr/` test cases as generated on Gaea C6.

**Local EXPDIR structure** (path: `supported_repos/EXPDIR/{CASE}_{HASH}/`):
```
supported_repos/EXPDIR/{PSLOT}_{HASH}/
├── config.*              # Resolved config files (config.fcst, config.anal, config.base, ...)
├── config.resources.*    # Per-platform resource overrides
├── {PSLOT}.xml           # Generated Rocoto XML (entities expanded, concrete job DAG)
├── {PSLOT}.crontab       # Cron schedule
└── {PSLOT}.scron.sh      # Slurm cron launcher
```

The script should:
1. **Scan local EXPDIR**: Accept `--expdir-base` argument defaulting to `supported_repos/EXPDIR/`, auto-discover all experiment directories
2. **Parse resolved configs**: Extract final variable values (no `${..}` references — these are the resolved values)
3. **Parse resolved Rocoto XML**: EXPDIR XML has all entities expanded — parse the concrete job DAG
4. **Create Neo4j nodes**: `(:EXPDIRConfig {name, experiment, platform, resolution})` linked to ConfigFile templates via `[:RESOLVES_FROM]`
5. **Diff template vs resolved**: Identify config deltas between the template (`parm/config/`) and experiment-specific values
6. **ChromaDB ingestion**: Ingest resolved configs with `file_type: 'expdir-config'` metadata and experiment name

```python
# Key relationships
# (:EXPDIRConfig)-[:RESOLVES_FROM]->(:ConfigFile)     # template origin
# (:EXPDIRConfig)-[:SETS_ENV]->(:EnvironmentVariable)  # resolved values
# (:EXPDIRConfig)-[:PART_OF]->(:Experiment)            # experiment grouping
# (:Experiment {name, platform, resolution, date})
```

**Acceptance**: Script runs with `--dry-run` locally. Full ingestion of all 15 experiments completes on the MCP development platform.

---

### Step 40-7: Run EXPDIR Ingestion Locally
**Tag**: execute
**Target**: MCP development platform terminal

The EXPDIR artifacts have been ported from Gaea C6 to `supported_repos/EXPDIR/`, so ingestion runs entirely on the MCP development platform where ChromaDB and Neo4j are hosted.

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node

# Step 1: Dry run (verify EXPDIR discovery and file counts)
python scripts/ingest_expdir_configs.py \
  --expdir-base ../supported_repos/EXPDIR/ \
  --dry-run 2>&1 | tee logs/phase40_expdir_dryrun.log

# Step 2: Full ingestion of all 15 experiments
python scripts/ingest_expdir_configs.py \
  --expdir-base ../supported_repos/EXPDIR/ \
  2>&1 | tee logs/phase40_expdir_ingest.log
```

**Note**: The 15 experiments were generated on Gaea C6 by the CI nightly pipeline for all cases in `ci/cases/pr/`. To refresh the EXPDIR snapshot, re-copy from Gaea C6's `GITLAB_BUILDS_DIR/stable/RUNTESTS/EXPDIR/` after a passing nightly run.

**Acceptance**: EXPDIRConfig nodes created in Neo4j for all 15 experiments. `[:RESOLVES_FROM]` edges link to template ConfigFile nodes from Step 40-2.

---

### Step 40-8: Run Config Ingestion
**Tag**: execute
**Target**: Terminal

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
python scripts/ingest_config_files.py 2>&1 | tee logs/phase40_config_ingest.log
```

**Acceptance**: 155 ConfigFile nodes in Neo4j. SETS_ENV edges link to EnvironmentVariable nodes.

---

### Step 40-9: Run CI + Jinja2 + XML Ingestion
**Tag**: execute
**Target**: Terminal

```bash
python scripts/ingest_ci_test_cases.py 2>&1 | tee logs/phase40_ci_ingest.log
python scripts/ingest_jinja2_templates.py 2>&1 | tee logs/phase40_jinja2_ingest.log
python scripts/ingest_rocoto_xml.py 2>&1 | tee logs/phase40_rocoto_ingest.log
```

**Acceptance**: All three scripts complete without error.

---

### Step 40-10: Validate Config-to-Script Tracing
**Tag**: validate
**Target**: Terminal (Cypher + MCP tools)

Test end-to-end traceability:

```cypher
-- Trace: config.fcst → FHMAX_GFS → exgfs_atmos_fcst.sh
MATCH (c:ConfigFile {name: 'config.fcst'})-[:SETS_ENV]->(e:EnvironmentVariable {name: 'FHMAX_GFS'})
MATCH (s:ShellScript)-[:DEPENDS_ON_ENV]->(e)
RETURN c.name, e.name, s.path;
```

Test via MCP:
```
find_env_dependencies({ variable_name: "FHMAX_GFS", show_exports: true })
explain_with_context({ topic: "forecast length configuration", detail_level: "detailed" })
```

**Acceptance**: Config→env var→script chain visible through both Cypher and MCP tools.

---

### Step 40-10a: Validate Rocoto Job DAG in Neo4j
**Tag**: validate
**Target**: Terminal (Cypher + MCP tools)

Test the Rocoto XML parser output — the job flow and dependency graph:

```cypher
-- 1. Full job DAG: which tasks depend on which
MATCH (t:RocotoTask)-[d:DEPENDS_ON]->(dep:RocotoTask)
RETURN t.name AS task, d.dep_type, dep.name AS depends_on
ORDER BY t.name;

-- 2. EnKF esfc dependency chain (Phase 45 context)
MATCH path = (t:RocotoTask {name: 'enkfgdas_esfc'})-[:DEPENDS_ON*1..3]->(ancestor)
RETURN [n IN nodes(path) | n.name] AS chain;

-- 3. Critical path: tasks with most dependents
MATCH (t:RocotoTask)<-[:DEPENDS_ON]-(dependent)
RETURN t.name, COUNT(dependent) AS num_dependents
ORDER BY num_dependents DESC LIMIT 10;

-- 4. Resource-heavy tasks (for capacity planning)
MATCH (t:RocotoTask)
WHERE t.nodes_spec IS NOT NULL
RETURN t.name, t.nodes_spec, t.walltime, t.memory
ORDER BY t.walltime DESC;

-- 5. Metatask → member tasks
MATCH (m:RocotoMetatask)<-[:MEMBER_OF]-(t:RocotoTask)
RETURN m.name, m.mode, m.member_count, COUNT(t) AS actual_tasks;

-- 6. Task→script cross-links (validates shell graph integration)
MATCH (t:RocotoTask)-[:RUNS_SCRIPT]->(s:ShellScript)
RETURN t.name, s.path
ORDER BY t.name;

-- 7. Tasks with cross-cycle dependencies
MATCH (t:RocotoTask)-[d:DEPENDS_ON]->(dep)
WHERE d.cycle_offset IS NOT NULL
RETURN t.name, d.cycle_offset, dep.name;

-- 8. Orphan tasks (no dependencies — typically stage_ic or initial tasks)
MATCH (t:RocotoTask)
WHERE NOT (t)-[:DEPENDS_ON]->()
RETURN t.name;
```

Test via MCP tools:
```
trace_execution_path({ start_node: "enkfgdas_esfc", direction: "upstream" })
find_callers_callees({ script_path: "dev/jobs/rocoto/esfc.sh" })
```

**Acceptance**: Job DAG complete — every task has correct dependencies, metatask membership, and script cross-links. The `enkfgdas_esfc` → `gdas_analcalc` + `enkfgdas_eupd` dependency chain matches the Python generators in `dev/workflow/rocoto/gfs_tasks.py`.

---

### Step 40-11: Update Gap Analysis Report
**Tag**: document
**Target**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md`

Update §3.2 (Orchestration Layer Coverage) to show configs, CI, and XML as ingested. Update §8 scorecard "Orchestration" from B+ to A-.

**Acceptance**: Report reflects Phase 40 completions.

---

## 5. Validation Criteria

| Criterion | Before | After | Method |
|-----------|--------|-------|--------|
| ConfigFile nodes | 0 | 146 | `MATCH (c:ConfigFile) RETURN COUNT(c)` |
| Config→env var edges | 0 | ~500+ | `MATCH ()-[:SETS_ENV]->() RETURN COUNT(*)` |
| CI test YAML in ChromaDB | 0 | 21 | Metadata query `file_type: 'ci-test'` |
| RocotoTask nodes | 0 | 30-80 per exp | `MATCH (t:RocotoTask) RETURN COUNT(t)` |
| RocotoTask→RocotoTask deps | 0 | 50-120 per exp | `MATCH ()-[:DEPENDS_ON]->() WHERE ... RETURN COUNT(*)` |
| RocotoTask→ShellScript links | 0 | 30-80 per exp | `MATCH ()-[:RUNS_SCRIPT]->() RETURN COUNT(*)` |
| RocotoMetatask nodes | 0 | 5-15 per exp | `MATCH (m:RocotoMetatask) RETURN COUNT(m)` |
| Jinja2 templates in ChromaDB | 0 | 26 | Metadata query `file_type: 'jinja2-template'` |
| EXPDIRConfig nodes | 0 | ~50-100 | `MATCH (e:EXPDIRConfig) RETURN COUNT(e)` |
| RESOLVES_FROM edges | 0 | ~50-100 | `MATCH ()-[:RESOLVES_FROM]->() RETURN COUNT(*)` |
| EXPDIR configs in ChromaDB | 0 | ~50-100 | Metadata query `file_type: 'expdir-config'` |

## 6. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Config files use complex bash (arrays, command substitution) | Regex parser extracts simple `export VAR=val` patterns — complex logic documented but not fully parsed |
| Rocoto XML has DOCTYPE entities (`&MAXTRIES;`, `&PSLOT;`) | `resolve_entities()` strips DOCTYPE block and substitutes entities before ET parsing |
| Metatasks nest recursively | `parse_metatask_element()` recurses into nested metatasks |
| Dependency trees use arbitrary `and`/`or`/`not` nesting | `parse_dependency_tree()` is fully recursive; flat dep list extracted separately for Neo4j edges |
| No static XML in repository — XML is generated at experiment creation time | Parser targets EXPDIR artifacts on RDHPCS (`{PSLOT}.xml`), not repo files |
| CI YAML structure varies across test cases | Parse with safe YAML loader, handle missing keys gracefully |
| EXPDIR snapshot may become stale | Re-copy from Gaea C6 CI nightly after passing runs; document snapshot date in commit message |
| EXPDIR directory naming includes commit hash | Parse experiment name from directory prefix (strip `_{HASH}` suffix); auto-discover all experiments in `--expdir-base` |
| Task→script matching may miss renamed scripts | Fuzzy match on basename + JJOB pattern (`JGDAS_`, `JGFS_`); log unmatched for manual review |

## 7. Cross-References

- **Gap Analysis**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md` §3.2, §7-C
- **Prerequisite**: Phase 38 (path normalization)
- **Related**: Phase 27B (shell graph — provides ShellScript nodes for linking), Phase 30 (experiment config documentation)
- **Downstream**: Config tracing enhances `find_env_dependencies` and `explain_workflow_component` tools
- **EXPDIR Source**: Ported from Gaea C6 CI nightly pipeline to `supported_repos/EXPDIR/` — all ingestion runs locally on the MCP development platform
