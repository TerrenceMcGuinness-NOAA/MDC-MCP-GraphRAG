# Phase 40: Configuration and CI File Ingestion

**Version**: 1.0.0
**Status**: Planned
**Created**: 2026-03-06
**Author**: AI Assistant + Terry McGuinness
**Dependency**: Phase 38 (path normalization), Phase 39 (Fortran graph — for community re-detection)
**Gap Analysis**: [docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md](../../docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md) §3.2, §7-C

---

## 1. Executive Summary

Three categories of files are not ingested into any knowledge base collection:

| File Category | Location | Count | Why It Matters |
|--------------|----------|-------|---------------|
| **Configuration files** | `dev/parm/config.*` | 155 | Define every experiment parameter — env vars, resolution, physics options |
| **CI test definitions** | `dev/ci/*.yaml` | 78 | Define all supported test cases, platforms, and expected configurations |
| **Jinja2 templates** | `dev/parm/*.j2`, `dev/scripts/*.j2` | ~20 | Generate actual configs at runtime — the template logic is invisible |
| **Rocoto XML definitions** | `dev/*.xml`, `dev/rocoto/` | ~5 | Define job dependency graph — the orchestration backbone |

These files are critical for answering questions like "What configs control ocean coupling?", "Which CI tests cover the C384 resolution?", and "What's the job dependency for post-processing?" — but the expert system currently cannot search or reason about them.

### Approach

- **Configs and YAML** → ChromaDB vectors (semantic search + env var extraction)
- **Configs** → Neo4j `ConfigFile` nodes with `SETS_ENV` edges to `EnvironmentVariable` nodes
- **Jinja2 templates** → ChromaDB vectors with template variable metadata
- **Rocoto XML** → Neo4j `RocotoTask` nodes with `DEPENDS_ON` edges (job dependency graph)

---

## 2. File Inventory

### 2.1 Configuration Files (`dev/parm/`)

```
dev/parm/config.aero               dev/parm/config.ice
dev/parm/config.anal                dev/parm/config.metp
dev/parm/config.arch                dev/parm/config.nsst
dev/parm/config.atmanl              dev/parm/config.ocn
dev/parm/config.atmanlrun           dev/parm/config.ocnanal
dev/parm/config.base                dev/parm/config.post
dev/parm/config.coupled_ic          dev/parm/config.prep
dev/parm/config.efcs                dev/parm/config.resources
dev/parm/config.fcst                dev/parm/config.stage_ic
...                                 (155 total)
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

### 2.4 Rocoto XML Definitions

`dev/rocoto/gfs.xml` or similar define the job dependency DAG:
```xml
<task name="post_f006" maxtries="2">
  <dependency>
    <datadep age="00:05:00"><cyclestr>/path/to/gfs.t@Hz.atmf006.nc</cyclestr></datadep>
  </dependency>
  <command>&SCRIPTS;/exgfs_atmos_post.sh</command>
</task>
```

---

## 3. Technical Specification

### Target Files

| File | Purpose | Database |
|------|---------|----------|
| `mcp_server_node/scripts/ingest_config_files.py` | **NEW** — config file ingestion | ChromaDB + Neo4j |
| `mcp_server_node/scripts/ingest_ci_test_cases.py` | **MODIFY** — may already exist, enhance | ChromaDB |
| `mcp_server_node/scripts/ingest_jinja2_templates.py` | **NEW** — Jinja2 template ingestion | ChromaDB |
| `mcp_server_node/scripts/ingest_rocoto_xml.py` | **NEW** — Rocoto XML to graph | Neo4j |

### Neo4j Schema Additions

```
(:ConfigFile {name, file_path, category})
(:ConfigFile)-[:SETS_ENV {value, is_default}]->(:EnvironmentVariable)
(:ConfigFile)-[:SOURCED_BY]->(:ShellScript)

(:RocotoTask {name, command, maxtries, walltime})
(:RocotoTask)-[:DEPENDS_ON {type: 'data'|'task'}]->(:RocotoTask)
(:RocotoTask)-[:RUNS_SCRIPT]->(:ShellScript)

(:CITestCase {name, resolution, mode, fhmax})
(:CITestCase)-[:TESTS_ON]->(:Platform {name})
(:CITestCase)-[:USES_CONFIG]->(:ConfigFile)
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

### Step 40-5: Create Rocoto XML Ingestion Script
**Tag**: implement
**Target**: `mcp_server_node/scripts/ingest_rocoto_xml.py`

Parse Rocoto XML to extract the job dependency DAG:

```python
import xml.etree.ElementTree as ET

def parse_rocoto_xml(xml_path: str) -> dict:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    tasks = {}
    for task in root.iter('task'):
        name = task.get('name')
        deps = []
        for dep in task.iter('taskdep'):
            deps.append(dep.get('task'))
        for dep in task.iter('datadep'):
            deps.append({'type': 'data', 'path': dep.text})
        command = task.findtext('command', '')
        tasks[name] = {
            'command': command,
            'dependencies': deps,
            'maxtries': task.get('maxtries', '1'),
        }
    return tasks
```

Create Neo4j nodes:
- `(:RocotoTask {name, command})` for each `<task>`
- `(:RocotoTask)-[:DEPENDS_ON]->(:RocotoTask)` for task dependencies
- `(:RocotoTask)-[:RUNS_SCRIPT]->(:ShellScript)` linking to existing ex-script nodes

**Acceptance**: `MATCH (t:RocotoTask)-[:DEPENDS_ON]->(d:RocotoTask) RETURN t.name, d.name` shows the job DAG.

---

### Step 40-6: Run Config Ingestion
**Tag**: execute
**Target**: Terminal

```bash
cd /mcp_rag_eib/eib-mcp-rag-server/mcp_server_node
python scripts/ingest_config_files.py 2>&1 | tee logs/phase40_config_ingest.log
```

**Acceptance**: 155 ConfigFile nodes in Neo4j. SETS_ENV edges link to EnvironmentVariable nodes.

---

### Step 40-7: Run CI + Jinja2 + XML Ingestion
**Tag**: execute
**Target**: Terminal

```bash
python scripts/ingest_ci_test_cases.py 2>&1 | tee logs/phase40_ci_ingest.log
python scripts/ingest_jinja2_templates.py 2>&1 | tee logs/phase40_jinja2_ingest.log
python scripts/ingest_rocoto_xml.py 2>&1 | tee logs/phase40_rocoto_ingest.log
```

**Acceptance**: All three scripts complete without error.

---

### Step 40-8: Validate Config-to-Script Tracing
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

### Step 40-9: Update Gap Analysis Report
**Tag**: document
**Target**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md`

Update §3.2 (Orchestration Layer Coverage) to show configs, CI, and XML as ingested. Update §8 scorecard "Orchestration" from B+ to A-.

**Acceptance**: Report reflects Phase 40 completions.

---

## 5. Validation Criteria

| Criterion | Before | After | Method |
|-----------|--------|-------|--------|
| ConfigFile nodes | 0 | 155 | `MATCH (c:ConfigFile) RETURN COUNT(c)` |
| Config→env var edges | 0 | ~500+ | `MATCH ()-[:SETS_ENV]->() RETURN COUNT(*)` |
| CI test YAML in ChromaDB | 0 | 78 | Metadata query `file_type: 'ci-test'` |
| RocotoTask nodes | 0 | ~30-50 | `MATCH (t:RocotoTask) RETURN COUNT(t)` |
| Jinja2 templates in ChromaDB | 0 | ~20 | Metadata query `file_type: 'jinja2-template'` |

## 6. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Config files use complex bash (arrays, command substitution) | Regex parser extracts simple `export VAR=val` patterns — complex logic documented but not fully parsed |
| Rocoto XML has entity references (`&SCRIPTS;`) | Resolve entities before parsing or use regex fallback |
| CI YAML structure varies across test cases | Parse with safe YAML loader, handle missing keys gracefully |

## 7. Cross-References

- **Gap Analysis**: `docs/EIB_MCP_KNOWLEDGE_BASE_GAP_ANALYSIS.md` §3.2, §7-C
- **Prerequisite**: Phase 38 (path normalization)
- **Related**: Phase 27B (shell graph — provides ShellScript nodes for linking), Phase 30 (experiment config documentation)
- **Downstream**: Config tracing enhances `find_env_dependencies` and `explain_workflow_component` tools
