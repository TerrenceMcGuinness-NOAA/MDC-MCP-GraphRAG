#!/usr/bin/env python3
"""
Phase 40 Step 40-5: Rocoto XML Ingestion for Neo4j

Parses generated Rocoto workflow XML files from EXPDIR artifacts and creates
a complete job dependency graph (DAG) in Neo4j. Handles DOCTYPE entity
resolution, metatask recursion, compound dependencies, and cross-links to
existing ShellScript nodes.

Neo4j Schema:
  (:RocotoTask {name, experiment, command, cycledefs, maxtries, walltime,
                nodes_spec, cores, queue, memory, is_final, platform,
                dependency_tree_json, log_path})
  (:RocotoMetatask {name, experiment, mode, variables, member_count})
  (:RocotoCycledef {group, experiment, definition})
  (:DataDependency {path_pattern})

  (task)-[:DEPENDS_ON {dep_type, cycle_offset, condition}]->(task)
  (task)-[:DEPENDS_ON_DATA {path_pattern, age}]->(data_dep)
  (task)-[:MEMBER_OF]->(metatask)
  (task)-[:RUNS_ON]->(cycledef)
  (task)-[:RUNS_SCRIPT]->(ShellScript)
  (task)-[:USES_ENV]->(EnvironmentVariable)

Author: NOAA EMC Global Workflow MCP Team
Version: 40.1.0
"""

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from neo4j import GraphDatabase
except ImportError:
    print("[ERROR] neo4j package not found. Install: pip install neo4j")
    sys.exit(1)


# ============================================================================
# CONFIGURATION
# ============================================================================

VERSION = "40.1.0"
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "gfsworkflow2025")

DEFAULT_EXPDIR_BASE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "supported_repos", "EXPDIR"
)


# ============================================================================
# ROCOTO XML PARSER
# ============================================================================

class RocotoXMLParser:
    """Parse Rocoto workflow XML files into structured dicts."""

    @staticmethod
    def resolve_entities(xml_text: str) -> Tuple[str, dict]:
        """Resolve DOCTYPE entity definitions and return clean XML + entity map.

        Parameters
        ----------
        xml_text : str
            Raw XML text with DOCTYPE entity definitions.

        Returns
        -------
        tuple[str, dict]
            Cleaned XML string with entities resolved, and dict of entity
            names to values.
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

    @staticmethod
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
        """
        tag = dep_element.tag

        if tag in ('and', 'or'):
            return {
                'operator': tag,
                'children': [RocotoXMLParser.parse_dependency_tree(child)
                             for child in dep_element]
            }
        elif tag == 'not':
            children = [RocotoXMLParser.parse_dependency_tree(child)
                        for child in dep_element]
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
            # <dependency> is just a wrapper -- recurse into its single child
            children = list(dep_element)
            if len(children) == 1:
                return RocotoXMLParser.parse_dependency_tree(children[0])
            # Multiple children without operator = implicit AND
            return {
                'operator': 'and',
                'children': [RocotoXMLParser.parse_dependency_tree(c)
                             for c in children]
            }
        else:
            return {'type': 'unknown', 'tag': tag, 'attrib': dep_element.attrib}

    @staticmethod
    def extract_task_deps_flat(dep_tree: dict) -> List[str]:
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
                names.extend(RocotoXMLParser.extract_task_deps_flat(child))
        elif dep_tree.get('type') in ('task', 'metatask', 'taskvalid'):
            if dep_tree.get('name'):
                names.append(dep_tree['name'])
        return names

    @staticmethod
    def extract_data_deps_flat(dep_tree: dict) -> List[dict]:
        """Flatten a dependency tree to a list of data dependency dicts.

        Parameters
        ----------
        dep_tree : dict
            Structured dependency tree from parse_dependency_tree().

        Returns
        -------
        list[dict]
            Data dependency entries with path, age, offset.
        """
        deps = []
        if 'operator' in dep_tree:
            for child in dep_tree.get('children', []):
                deps.extend(RocotoXMLParser.extract_data_deps_flat(child))
        elif dep_tree.get('type') == 'data':
            deps.append({
                'path': dep_tree.get('path', ''),
                'age': dep_tree.get('age'),
                'offset': dep_tree.get('offset'),
            })
        return deps

    @staticmethod
    def parse_task_element(task_el) -> dict:
        """Parse a single <task> element into a structured dict.

        Parameters
        ----------
        task_el : xml.etree.ElementTree.Element
            A <task> XML element.

        Returns
        -------
        dict
            Task properties: name, cycledefs, command, resources, envars,
            dependencies.
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
            resources['nodes_spec'] = nodes_el
        elif cores_el:
            resources['cores'] = int(cores_el)

        # Environment variables
        envars = {}
        for envar in task_el.findall('envar'):
            var_name = envar.findtext('name', '')
            val_el = envar.find('value')
            if val_el is not None:
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
        dep_tree = RocotoXMLParser.parse_dependency_tree(dep_el) if dep_el is not None else {}
        dep_names = RocotoXMLParser.extract_task_deps_flat(dep_tree)
        data_deps = RocotoXMLParser.extract_data_deps_flat(dep_tree)

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
            'dependency_names': dep_names,
            'data_dependencies': data_deps,
            'log_path': log_path,
        }

    @staticmethod
    def parse_metatask_element(metatask_el) -> dict:
        """Parse a <metatask> element (may contain nested metatasks).

        Parameters
        ----------
        metatask_el : xml.etree.ElementTree.Element
            A <metatask> XML element.

        Returns
        -------
        dict
            Metatask properties: name, mode, variables, and nested
            tasks/metatasks.
        """
        name = metatask_el.get('name')
        mode = metatask_el.get('mode', 'parallel')

        # Metatask variables
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
                tasks.append(RocotoXMLParser.parse_task_element(child))
            elif child.tag == 'metatask':
                nested_metatasks.append(
                    RocotoXMLParser.parse_metatask_element(child))

        return {
            'name': name,
            'mode': mode,
            'variables': variables,
            'tasks': tasks,
            'nested_metatasks': nested_metatasks,
        }

    @staticmethod
    def parse_rocoto_xml(xml_path: str) -> dict:
        """Parse a complete Rocoto workflow XML file.

        Parameters
        ----------
        xml_path : str
            Path to the Rocoto XML file.

        Returns
        -------
        dict
            Complete workflow structure: entities, cycledefs, tasks,
            metatasks.
        """
        raw_xml = Path(xml_path).read_text()
        clean_xml, entities = RocotoXMLParser.resolve_entities(raw_xml)
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
                tasks.append(RocotoXMLParser.parse_task_element(child))
            elif child.tag == 'metatask':
                metatasks.append(
                    RocotoXMLParser.parse_metatask_element(child))

        return {
            'source_file': xml_path,
            'entities': entities,
            'workflow': workflow,
            'cycledefs': cycledefs,
            'tasks': tasks,
            'metatasks': metatasks,
        }


# ============================================================================
# NEO4J GRAPH INGESTOR
# ============================================================================

class RocotoGraphIngestor:
    """Ingest parsed Rocoto XML into Neo4j as a job dependency graph."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.driver = None
        self.stats = defaultdict(int)
        self.errors = []
        self.unmatched_commands = []

    def connect(self):
        """Connect to Neo4j."""
        try:
            self.driver = GraphDatabase.driver(
                NEO4J_URI,
                auth=(NEO4J_USER, NEO4J_PASSWORD),
                max_connection_lifetime=3600
            )
            with self.driver.session() as session:
                session.run("RETURN 1")
            print(f"[OK] Connected to Neo4j: {NEO4J_URI}")
        except Exception as e:
            print(f"[ERROR] Neo4j connection failed: {e}")
            sys.exit(1)

    def close(self):
        """Close Neo4j driver."""
        if self.driver:
            self.driver.close()

    def create_indexes(self):
        """Create Neo4j indexes for Rocoto node types."""
        indexes = [
            "CREATE INDEX rocoto_task_name IF NOT EXISTS FOR (t:RocotoTask) ON (t.name)",
            "CREATE INDEX rocoto_task_experiment IF NOT EXISTS FOR (t:RocotoTask) ON (t.experiment)",
            "CREATE INDEX rocoto_metatask_name IF NOT EXISTS FOR (m:RocotoMetatask) ON (m.name)",
            "CREATE INDEX rocoto_cycledef_group IF NOT EXISTS FOR (c:RocotoCycledef) ON (c.group)",
            "CREATE INDEX data_dep_path IF NOT EXISTS FOR (d:DataDependency) ON (d.path_pattern)",
        ]
        with self.driver.session() as session:
            for idx in indexes:
                try:
                    session.run(idx)
                except Exception:
                    pass
        print("[OK] Created Rocoto Neo4j indexes")

    def ingest_workflow(self, parsed: dict, experiment: str):
        """Ingest a complete parsed Rocoto workflow into Neo4j.

        Parameters
        ----------
        parsed : dict
            Output of RocotoXMLParser.parse_rocoto_xml().
        experiment : str
            Experiment name (PSLOT) for scoping nodes.
        """
        # Cycledefs
        for cd in parsed['cycledefs']:
            self._create_cycledef(cd, experiment)

        # Top-level tasks
        for task in parsed['tasks']:
            self._create_task(task, experiment)

        # Metatasks (recursive)
        for mt in parsed['metatasks']:
            self._create_metatask(mt, experiment)

        # Create inter-task dependency edges (second pass)
        all_tasks = self._collect_all_tasks(parsed)
        for task in all_tasks:
            self._create_task_dependencies(task, experiment)
            self._create_data_dependencies(task, experiment)
            self._create_script_cross_link(task, experiment)
            self._create_env_var_links(task, experiment)
            self._create_cycledef_links(task, experiment)

    def _create_cycledef(self, cd: dict, experiment: str):
        """Create a RocotoCycledef node."""
        query = """
        MERGE (c:RocotoCycledef {group: $group, experiment: $experiment})
        SET c.definition = $definition,
            c.version = $version,
            c.updated_at = $updated_at
        """
        with self.driver.session() as session:
            session.run(query,
                        group=cd['group'],
                        experiment=experiment,
                        definition=cd['definition'],
                        version=VERSION,
                        updated_at=datetime.now().isoformat())
        self.stats['cycledefs'] += 1

    def _create_task(self, task: dict, experiment: str):
        """Create a RocotoTask node."""
        resources = task.get('resources', {})
        dep_json = json.dumps(task.get('dependency_tree', {}))

        query = """
        MERGE (t:RocotoTask {name: $name, experiment: $experiment})
        SET t.command = $command,
            t.cycledefs = $cycledefs,
            t.maxtries = $maxtries,
            t.walltime = $walltime,
            t.nodes_spec = $nodes_spec,
            t.cores = $cores,
            t.queue = $queue,
            t.memory = $memory,
            t.is_final = $is_final,
            t.dependency_tree_json = $dep_json,
            t.dependency_names = $dep_names,
            t.log_path = $log_path,
            t.version = $version,
            t.updated_at = $updated_at
        """
        with self.driver.session() as session:
            session.run(query,
                        name=task['name'],
                        experiment=experiment,
                        command=task['command'],
                        cycledefs=task['cycledefs'],
                        maxtries=task['maxtries'],
                        walltime=resources.get('walltime'),
                        nodes_spec=resources.get('nodes_spec'),
                        cores=resources.get('cores'),
                        queue=resources.get('queue'),
                        memory=resources.get('memory'),
                        is_final=task['is_final'],
                        dep_json=dep_json,
                        dep_names=task.get('dependency_names', []),
                        log_path=task.get('log_path'),
                        version=VERSION,
                        updated_at=datetime.now().isoformat())
        self.stats['tasks'] += 1

    def _create_metatask(self, mt: dict, experiment: str):
        """Create RocotoMetatask node and recurse into children."""
        # Calculate total member count from variables
        member_count = 1
        for values in mt['variables'].values():
            member_count *= len(values)

        query = """
        MERGE (m:RocotoMetatask {name: $name, experiment: $experiment})
        SET m.mode = $mode,
            m.variables = $variables,
            m.member_count = $member_count,
            m.version = $version,
            m.updated_at = $updated_at
        """
        with self.driver.session() as session:
            session.run(query,
                        name=mt['name'],
                        experiment=experiment,
                        mode=mt['mode'],
                        variables=json.dumps(mt['variables']),
                        member_count=member_count,
                        version=VERSION,
                        updated_at=datetime.now().isoformat())
        self.stats['metatasks'] += 1

        # Create child tasks and link to metatask
        for task in mt['tasks']:
            self._create_task(task, experiment)
            self._link_task_to_metatask(task['name'], mt['name'], experiment)

        # Recurse into nested metatasks
        for nested_mt in mt['nested_metatasks']:
            self._create_metatask(nested_mt, experiment)

    def _link_task_to_metatask(self, task_name: str, metatask_name: str,
                               experiment: str):
        """Create MEMBER_OF edge from task to metatask."""
        query = """
        MATCH (t:RocotoTask {name: $task_name, experiment: $experiment})
        MATCH (m:RocotoMetatask {name: $mt_name, experiment: $experiment})
        MERGE (t)-[:MEMBER_OF]->(m)
        """
        with self.driver.session() as session:
            session.run(query,
                        task_name=task_name,
                        mt_name=metatask_name,
                        experiment=experiment)
        self.stats['member_of_edges'] += 1

    def _create_task_dependencies(self, task: dict, experiment: str):
        """Create DEPENDS_ON edges between tasks."""
        dep_tree = task.get('dependency_tree', {})
        if not dep_tree:
            return
        self._walk_deps_for_edges(task['name'], dep_tree, experiment)

    def _walk_deps_for_edges(self, task_name: str, dep_node: dict,
                             experiment: str, condition: str = None):
        """Walk dependency tree and create DEPENDS_ON edges for task/metatask deps."""
        if 'operator' in dep_node:
            op = dep_node['operator']
            for child in dep_node.get('children', []):
                self._walk_deps_for_edges(task_name, child, experiment,
                                          condition=op)
        elif dep_node.get('type') in ('task', 'metatask', 'taskvalid'):
            dep_name = dep_node.get('name')
            if not dep_name:
                return
            cycle_offset = dep_node.get('cycle_offset')
            dep_type = dep_node.get('type')

            query = """
            MATCH (t:RocotoTask {name: $task_name, experiment: $experiment})
            MERGE (d:RocotoTask {name: $dep_name, experiment: $experiment})
            MERGE (t)-[r:DEPENDS_ON]->(d)
            SET r.dep_type = $dep_type,
                r.cycle_offset = $cycle_offset,
                r.condition = $condition
            """
            try:
                with self.driver.session() as session:
                    session.run(query,
                                task_name=task_name,
                                experiment=experiment,
                                dep_name=dep_name,
                                dep_type=dep_type,
                                cycle_offset=cycle_offset,
                                condition=condition)
                self.stats['depends_on_edges'] += 1
            except Exception as e:
                self.errors.append({
                    'task': task_name,
                    'dep': dep_name,
                    'error': str(e)
                })

    def _create_data_dependencies(self, task: dict, experiment: str):
        """Create DEPENDS_ON_DATA edges for file-based dependencies."""
        for data_dep in task.get('data_dependencies', []):
            path_pattern = data_dep.get('path', '')
            if not path_pattern:
                continue

            query = """
            MATCH (t:RocotoTask {name: $task_name, experiment: $experiment})
            MERGE (d:DataDependency {path_pattern: $path_pattern})
            MERGE (t)-[r:DEPENDS_ON_DATA]->(d)
            SET r.age = $age
            """
            try:
                with self.driver.session() as session:
                    session.run(query,
                                task_name=task['name'],
                                experiment=experiment,
                                path_pattern=path_pattern,
                                age=data_dep.get('age'))
                self.stats['data_dep_edges'] += 1
            except Exception as e:
                self.errors.append({
                    'task': task['name'],
                    'data_dep': path_pattern,
                    'error': str(e)
                })

    def _create_script_cross_link(self, task: dict, experiment: str):
        """Create RUNS_SCRIPT edge by matching command to ShellScript nodes."""
        command = task.get('command', '')
        if not command:
            return

        script_basename = Path(command).name
        if not script_basename:
            return

        query = """
        MATCH (t:RocotoTask {name: $task_name, experiment: $experiment})
        MATCH (s:ShellScript) WHERE s.path ENDS WITH $basename
        MERGE (t)-[:RUNS_SCRIPT]->(s)
        """
        try:
            with self.driver.session() as session:
                result = session.run(query,
                                     task_name=task['name'],
                                     experiment=experiment,
                                     basename=script_basename)
                summary = result.consume()
                if summary.counters.relationships_created > 0:
                    self.stats['runs_script_edges'] += 1
                else:
                    self.unmatched_commands.append({
                        'task': task['name'],
                        'command': command,
                        'basename': script_basename
                    })
        except Exception as e:
            self.errors.append({
                'task': task['name'],
                'command': command,
                'error': str(e)
            })

    def _create_env_var_links(self, task: dict, experiment: str):
        """Create USES_ENV edges from task envars to EnvironmentVariable nodes."""
        envars = task.get('envars', {})
        for var_name in envars:
            if not var_name:
                continue
            query = """
            MATCH (t:RocotoTask {name: $task_name, experiment: $experiment})
            MERGE (e:EnvironmentVariable {name: $var_name})
            MERGE (t)-[:USES_ENV]->(e)
            """
            with self.driver.session() as session:
                session.run(query,
                            task_name=task['name'],
                            experiment=experiment,
                            var_name=var_name)
            self.stats['uses_env_edges'] += 1

    def _create_cycledef_links(self, task: dict, experiment: str):
        """Create RUNS_ON edges from task to its cycle definitions."""
        cycledefs_str = task.get('cycledefs', '')
        if not cycledefs_str:
            return
        for group in cycledefs_str.split(','):
            group = group.strip()
            if not group:
                continue
            query = """
            MATCH (t:RocotoTask {name: $task_name, experiment: $experiment})
            MERGE (c:RocotoCycledef {group: $group, experiment: $experiment})
            MERGE (t)-[:RUNS_ON]->(c)
            """
            with self.driver.session() as session:
                session.run(query,
                            task_name=task['name'],
                            experiment=experiment,
                            group=group)
            self.stats['runs_on_edges'] += 1

    def _collect_all_tasks(self, parsed: dict) -> List[dict]:
        """Collect all tasks from top-level and nested metatasks."""
        tasks = list(parsed['tasks'])
        for mt in parsed['metatasks']:
            tasks.extend(self._collect_metatask_tasks(mt))
        return tasks

    def _collect_metatask_tasks(self, mt: dict) -> List[dict]:
        """Recursively collect tasks from a metatask."""
        tasks = list(mt['tasks'])
        for nested_mt in mt['nested_metatasks']:
            tasks.extend(self._collect_metatask_tasks(nested_mt))
        return tasks

    def get_statistics(self) -> dict:
        """Return ingestion statistics."""
        return dict(self.stats)


# ============================================================================
# XML DISCOVERY
# ============================================================================

def discover_xml_files(expdir_base: str) -> List[dict]:
    """Discover Rocoto XML files in EXPDIR subdirectories.

    Parameters
    ----------
    expdir_base : str
        Base directory containing experiment subdirectories.

    Returns
    -------
    list[dict]
        List of dicts with 'xml_path', 'experiment', 'experiment_short'.
    """
    HASH_PATTERN = re.compile(r'_[0-9a-f]{6,10}-[0-9a-f]{3,5}$')

    experiments = []
    base = Path(expdir_base)
    if not base.is_dir():
        print(f"[ERROR] EXPDIR base not found: {expdir_base}")
        return experiments

    for exp_dir in sorted(base.iterdir()):
        if not exp_dir.is_dir():
            continue
        xml_files = list(exp_dir.glob("*.xml"))
        if not xml_files:
            print(f"[WARN] No XML found in {exp_dir.name}")
            continue

        pslot = exp_dir.name
        short_name = HASH_PATTERN.sub('', pslot)

        experiments.append({
            'xml_path': str(xml_files[0]),
            'experiment': pslot,
            'experiment_short': short_name,
            'exp_dir': str(exp_dir),
        })

    return experiments


# ============================================================================
# DRY-RUN SUMMARY
# ============================================================================

def dry_run_summary(experiments: List[dict], verbose: bool = False):
    """Parse all XMLs and print statistics without writing to Neo4j."""
    print("\n" + "=" * 70)
    print("  DRY-RUN SUMMARY (no database writes)")
    print("=" * 70)

    total_tasks = 0
    total_metatasks = 0
    total_deps = 0
    total_data_deps = 0
    total_cycledefs = 0

    for exp in experiments:
        try:
            parsed = RocotoXMLParser.parse_rocoto_xml(exp['xml_path'])
        except Exception as e:
            print(f"[ERROR] Failed to parse {exp['experiment']}: {e}")
            continue

        all_tasks = []
        all_tasks.extend(parsed['tasks'])
        for mt in parsed['metatasks']:
            all_tasks.extend(_collect_mt_tasks(mt))

        task_count = len(all_tasks)
        metatask_count = len(parsed['metatasks'])
        dep_count = sum(len(t.get('dependency_names', []))
                        for t in all_tasks)
        data_dep_count = sum(len(t.get('data_dependencies', []))
                             for t in all_tasks)
        cycledef_count = len(parsed['cycledefs'])

        total_tasks += task_count
        total_metatasks += metatask_count
        total_deps += dep_count
        total_data_deps += data_dep_count
        total_cycledefs += cycledef_count

        print(f"\n  {exp['experiment_short']}")
        print(f"    Tasks: {task_count}  Metatasks: {metatask_count}  "
              f"Deps: {dep_count}  DataDeps: {data_dep_count}  "
              f"CycleDefs: {cycledef_count}")

        if verbose:
            for task in all_tasks:
                deps_str = ', '.join(task.get('dependency_names', [])[:5])
                if len(task.get('dependency_names', [])) > 5:
                    deps_str += ', ...'
                print(f"      {task['name']}: depends=[{deps_str}]")

    print(f"\n{'=' * 70}")
    print(f"  TOTALS: {len(experiments)} experiments")
    print(f"    Tasks:     {total_tasks}")
    print(f"    Metatasks: {total_metatasks}")
    print(f"    Deps:      {total_deps}")
    print(f"    DataDeps:  {total_data_deps}")
    print(f"    CycleDefs: {total_cycledefs}")
    print(f"{'=' * 70}")
    print("\n  Re-run without --dry-run to write to Neo4j.")


def _collect_mt_tasks(mt: dict) -> List[dict]:
    """Helper: collect all tasks from a metatask recursively."""
    tasks = list(mt['tasks'])
    for nested in mt['nested_metatasks']:
        tasks.extend(_collect_mt_tasks(nested))
    return tasks


# ============================================================================
# MAIN
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Phase 40-5: Rocoto XML Ingestion for Neo4j",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ingest_rocoto_xml.py --dry-run
  python ingest_rocoto_xml.py --xml-path /path/to/experiment.xml
  python ingest_rocoto_xml.py --expdir-base ../supported_repos/EXPDIR/
  python ingest_rocoto_xml.py --expdir-base ../supported_repos/EXPDIR/ --verbose
        """
    )
    parser.add_argument('--xml-path', metavar='FILE',
                        help='Parse a single XML file')
    parser.add_argument('--expdir-base', metavar='DIR',
                        default=DEFAULT_EXPDIR_BASE,
                        help='Base directory for EXPDIR experiments '
                             f'(default: {DEFAULT_EXPDIR_BASE})')
    parser.add_argument('--dry-run', '-n', action='store_true',
                        help='Parse and count without writing to Neo4j')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show per-task details')
    parser.add_argument('--version', action='version',
                        version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    print(f"[STEP 1] Rocoto XML Ingestion v{VERSION}")
    print(f"  EXPDIR base: {args.expdir_base}")

    # Discover experiments
    if args.xml_path:
        xml_path = args.xml_path
        pslot = Path(xml_path).stem
        experiments = [{
            'xml_path': xml_path,
            'experiment': pslot,
            'experiment_short': pslot,
            'exp_dir': str(Path(xml_path).parent),
        }]
    else:
        experiments = discover_xml_files(args.expdir_base)

    print(f"[SCAN] Found {len(experiments)} experiments with XML files")

    if not experiments:
        print("[WARN] No experiments found. Exiting.")
        return

    # Dry-run mode
    if args.dry_run:
        dry_run_summary(experiments, verbose=args.verbose)
        return

    # Live mode
    print("\n[STEP 2] Connecting to Neo4j...")
    ingestor = RocotoGraphIngestor()
    ingestor.connect()
    ingestor.create_indexes()

    print(f"\n[STEP 3] Ingesting {len(experiments)} experiments...")
    for i, exp in enumerate(experiments, 1):
        print(f"\n  [{i}/{len(experiments)}] {exp['experiment_short']}")
        try:
            parsed = RocotoXMLParser.parse_rocoto_xml(exp['xml_path'])
            ingestor.ingest_workflow(parsed, exp['experiment'])

            all_tasks = ingestor._collect_all_tasks(parsed)
            print(f"    [OK] {len(all_tasks)} tasks, "
                  f"{len(parsed['metatasks'])} metatasks, "
                  f"{len(parsed['cycledefs'])} cycledefs")
        except Exception as e:
            print(f"    [ERROR] {e}")
            ingestor.errors.append({
                'experiment': exp['experiment'],
                'error': str(e)
            })

    # Summary
    stats = ingestor.get_statistics()
    print(f"\n{'=' * 70}")
    print(f"  INGESTION COMPLETE")
    print(f"{'=' * 70}")
    print(f"  Experiments:       {len(experiments)}")
    print(f"  Tasks:             {stats.get('tasks', 0)}")
    print(f"  Metatasks:         {stats.get('metatasks', 0)}")
    print(f"  CycleDefs:         {stats.get('cycledefs', 0)}")
    print(f"  DEPENDS_ON edges:  {stats.get('depends_on_edges', 0)}")
    print(f"  DATA_DEP edges:    {stats.get('data_dep_edges', 0)}")
    print(f"  RUNS_SCRIPT edges: {stats.get('runs_script_edges', 0)}")
    print(f"  USES_ENV edges:    {stats.get('uses_env_edges', 0)}")
    print(f"  MEMBER_OF edges:   {stats.get('member_of_edges', 0)}")
    print(f"  RUNS_ON edges:     {stats.get('runs_on_edges', 0)}")
    print(f"  Errors:            {len(ingestor.errors)}")
    print(f"  Unmatched scripts: {len(ingestor.unmatched_commands)}")
    print(f"{'=' * 70}")

    if ingestor.unmatched_commands:
        print("\n[WARN] Unmatched command -> script mappings:")
        for uc in ingestor.unmatched_commands[:20]:
            print(f"  {uc['task']}: {uc['basename']}")

    if ingestor.errors:
        print(f"\n[WARN] {len(ingestor.errors)} errors during ingestion")
        for err in ingestor.errors[:10]:
            print(f"  {err}")

    ingestor.close()
    print("\n[OK] Done.")


if __name__ == '__main__':
    main()
