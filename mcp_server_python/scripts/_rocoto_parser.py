"""Rocoto workflow XML parser.

Ported verbatim from mcp_server_node/scripts/ingest_rocoto_xml.py::RocotoXMLParser.
Handles DOCTYPE entity resolution, recursive metatask expansion, and compound
dependency trees. Parsing logic is battle-tested against real GFS XML.

Implements: R6.1–R6.6 of graph-port-workflow-structure.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple


class RocotoXMLParser:
    """Parse Rocoto workflow XML files into structured dicts."""

    @staticmethod
    def resolve_entities(xml_text: str) -> Tuple[str, dict]:
        """Resolve DOCTYPE entity definitions; return clean XML + entity map."""
        entities = {}
        for match in re.finditer(r'<!ENTITY\s+(\w+)\s+"([^"]*)">', xml_text):
            entities[match.group(1)] = match.group(2)

        # Strip the DOCTYPE block entirely (ET cannot parse it)
        clean = re.sub(r'<!DOCTYPE[^>]*\[.*?\]>', '', xml_text, flags=re.DOTALL)

        for name, value in entities.items():
            clean = clean.replace(f'&{name};', value)

        return clean, entities

    @staticmethod
    def parse_dependency_tree(dep_element) -> dict:
        """Recursively parse a <dependency> block into a structured dict."""
        tag = dep_element.tag

        if tag in ('and', 'or'):
            return {'operator': tag,
                    'children': [RocotoXMLParser.parse_dependency_tree(c)
                                 for c in dep_element]}
        elif tag == 'not':
            return {'operator': 'not',
                    'children': [RocotoXMLParser.parse_dependency_tree(c)
                                 for c in dep_element]}
        elif tag == 'taskdep':
            return {'type': 'task', 'name': dep_element.get('task'),
                    'cycle_offset': dep_element.get('cycle_offset')}
        elif tag == 'metataskdep':
            return {'type': 'metatask', 'name': dep_element.get('metatask'),
                    'cycle_offset': dep_element.get('cycle_offset')}
        elif tag == 'datadep':
            cyclestr = dep_element.find('cyclestr')
            path = cyclestr.text if cyclestr is not None else (dep_element.text or '')
            offset = cyclestr.get('offset') if cyclestr is not None else None
            return {'type': 'data', 'path': path.strip(),
                    'offset': offset, 'age': dep_element.get('age')}
        elif tag == 'cycleexistdep':
            return {'type': 'cycleexist',
                    'cycle_offset': dep_element.get('cycle_offset')}
        elif tag == 'taskvalid':
            return {'type': 'taskvalid', 'name': dep_element.get('task')}
        elif tag in ('streq', 'strneq'):
            return {'type': tag,
                    'left': dep_element.findtext('left', ''),
                    'right': dep_element.findtext('right', '')}
        elif tag == 'sh':
            cyclestr = dep_element.find('cyclestr')
            cmd = cyclestr.text if cyclestr is not None else (dep_element.text or '')
            return {'type': 'shell', 'command': cmd.strip(),
                    'shell': dep_element.get('shell', '/bin/sh')}
        elif tag == 'dependency':
            children = list(dep_element)
            if len(children) == 1:
                return RocotoXMLParser.parse_dependency_tree(children[0])
            return {'operator': 'and',
                    'children': [RocotoXMLParser.parse_dependency_tree(c)
                                 for c in children]}
        else:
            return {'type': 'unknown', 'tag': tag, 'attrib': dep_element.attrib}

    @staticmethod
    def extract_task_deps_flat(dep_tree: dict) -> List[str]:
        """Flatten dependency tree to task/metatask names."""
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
        """Flatten dependency tree to data dependency dicts."""
        deps = []
        if 'operator' in dep_tree:
            for child in dep_tree.get('children', []):
                deps.extend(RocotoXMLParser.extract_data_deps_flat(child))
        elif dep_tree.get('type') == 'data':
            deps.append({'path': dep_tree.get('path', ''),
                         'age': dep_tree.get('age'),
                         'offset': dep_tree.get('offset')})
        return deps

    @staticmethod
    def parse_task_element(task_el) -> dict:
        """Parse a single <task> element into a structured dict."""
        name = task_el.get('name')
        cycledefs = task_el.get('cycledefs', '')
        maxtries = task_el.get('maxtries', '1')
        is_final = task_el.get('final', 'false') == 'true'

        command = task_el.findtext('command', '').strip()

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

        dep_el = task_el.find('dependency')
        dep_tree = RocotoXMLParser.parse_dependency_tree(dep_el) if dep_el is not None else {}
        dep_names = RocotoXMLParser.extract_task_deps_flat(dep_tree)
        data_deps = RocotoXMLParser.extract_data_deps_flat(dep_tree)

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
        """Parse a <metatask> element (may contain nested metatasks)."""
        name = metatask_el.get('name')
        mode = metatask_el.get('mode', 'parallel')

        variables = {}
        for var_el in metatask_el.findall('var'):
            var_name = var_el.get('name')
            var_values = (var_el.text or '').split()
            variables[var_name] = var_values

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
        """Parse a complete Rocoto workflow XML file."""
        raw_xml = Path(xml_path).read_text()
        clean_xml, entities = RocotoXMLParser.resolve_entities(raw_xml)
        root = ET.fromstring(clean_xml)

        workflow = {
            'scheduler': root.get('scheduler'),
            'realtime': root.get('realtime'),
            'cyclethrottle': root.get('cyclethrottle'),
            'taskthrottle': root.get('taskthrottle'),
        }

        cycledefs = [{'group': cd.get('group'),
                      'definition': cd.text.strip() if cd.text else ''}
                     for cd in root.findall('cycledef')]

        tasks = [RocotoXMLParser.parse_task_element(c)
                 for c in root if c.tag == 'task']
        metatasks = [RocotoXMLParser.parse_metatask_element(c)
                     for c in root if c.tag == 'metatask']

        return {
            'source_file': xml_path,
            'entities': entities,
            'workflow': workflow,
            'cycledefs': cycledefs,
            'tasks': tasks,
            'metatasks': metatasks,
        }
