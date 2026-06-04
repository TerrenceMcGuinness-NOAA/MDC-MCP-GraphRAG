"""Unit tests for RocotoXMLParser.

Validates: R6.1–R6.6 (entity resolution, dependency trees, metatask recursion,
task element extraction, end-to-end parse).
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from scripts._rocoto_parser import RocotoXMLParser


class TestResolveEntities:
    """R6.1: DOCTYPE entity resolution before parse."""

    def test_entities_resolved_and_doctype_stripped(self):
        xml = (
            '<!DOCTYPE workflow [\n'
            '  <!ENTITY PSLOT "C48_ATM">\n'
            '  <!ENTITY EXPDIR "/exp/dir">\n'
            ']>\n'
            '<workflow><task name="&PSLOT;"><command>&EXPDIR;/run</command>'
            '</task></workflow>'
        )
        clean, entities = RocotoXMLParser.resolve_entities(xml)
        assert entities == {'PSLOT': 'C48_ATM', 'EXPDIR': '/exp/dir'}
        assert '<!DOCTYPE' not in clean
        assert 'C48_ATM' in clean
        assert '/exp/dir/run' in clean
        # parses cleanly now
        ET.fromstring(clean)


class TestDependencyTree:
    """R6.5/R6.6: compound dependency trees + cycle_offset."""

    def test_and_with_taskdeps(self):
        dep = ET.fromstring(
            '<dependency><and>'
            '<taskdep task="prep"/>'
            '<taskdep task="anal" cycle_offset="-06:00:00"/>'
            '</and></dependency>'
        )
        tree = RocotoXMLParser.parse_dependency_tree(dep)
        # <dependency> with single <and> child unwraps to the and node
        assert tree['operator'] == 'and'
        names = RocotoXMLParser.extract_task_deps_flat(tree)
        assert names == ['prep', 'anal']
        # cycle_offset preserved on the second child
        assert tree['children'][1]['cycle_offset'] == '-06:00:00'

    def test_not_and_datadep(self):
        dep = ET.fromstring(
            '<or><not><taskdep task="x"/></not>'
            '<datadep age="120"><cyclestr>/path/@Y</cyclestr></datadep></or>'
        )
        tree = RocotoXMLParser.parse_dependency_tree(dep)
        assert tree['operator'] == 'or'
        data = RocotoXMLParser.extract_data_deps_flat(tree)
        assert data == [{'path': '/path/@Y', 'age': '120', 'offset': None}]

    def test_metataskdep(self):
        dep = ET.fromstring('<metataskdep metatask="efcs"/>')
        tree = RocotoXMLParser.parse_dependency_tree(dep)
        assert tree == {'type': 'metatask', 'name': 'efcs', 'cycle_offset': None}


class TestTaskElement:
    """R6.3: task extraction — resources, envars, deps, log."""

    def test_full_task(self):
        task_el = ET.fromstring(
            '<task name="fcst" cycledefs="gfs" maxtries="2" final="true">'
            '<command>/run/exfcst.sh</command>'
            '<walltime>01:00:00</walltime>'
            '<queue>batch</queue>'
            '<cores>240</cores>'
            '<memory>4G</memory>'
            '<envar><name>CDATE</name><value>2024010100</value></envar>'
            '<join><cyclestr>/log/fcst.log</cyclestr></join>'
            '<dependency><taskdep task="prep"/></dependency>'
            '</task>'
        )
        t = RocotoXMLParser.parse_task_element(task_el)
        assert t['name'] == 'fcst'
        assert t['cycledefs'] == 'gfs'
        assert t['maxtries'] == '2'
        assert t['is_final'] is True
        assert t['command'] == '/run/exfcst.sh'
        assert t['resources']['walltime'] == '01:00:00'
        assert t['resources']['cores'] == 240
        assert t['resources']['memory'] == '4G'
        assert t['envars'] == {'CDATE': '2024010100'}
        assert t['log_path'] == '/log/fcst.log'
        assert t['dependency_names'] == ['prep']

    def test_task_no_deps_no_envars(self):
        task_el = ET.fromstring('<task name="x"><command>c</command></task>')
        t = RocotoXMLParser.parse_task_element(task_el)
        assert t['envars'] == {}
        assert t['dependency_tree'] == {}
        assert t['dependency_names'] == []


class TestMetatask:
    """R6.4: recursive metatask parsing (depth 3)."""

    def test_nested_depth_3(self):
        mt_el = ET.fromstring(
            '<metatask name="lvl1" mode="parallel">'
            '<var name="mem">001 002 003</var>'
            '<task name="t1"><command>c1</command></task>'
            '<metatask name="lvl2">'
            '<task name="t2"><command>c2</command></task>'
            '<metatask name="lvl3">'
            '<task name="t3"><command>c3</command></task>'
            '</metatask>'
            '</metatask>'
            '</metatask>'
        )
        mt = RocotoXMLParser.parse_metatask_element(mt_el)
        assert mt['name'] == 'lvl1'
        assert mt['mode'] == 'parallel'
        assert mt['variables'] == {'mem': ['001', '002', '003']}
        assert [t['name'] for t in mt['tasks']] == ['t1']
        lvl2 = mt['nested_metatasks'][0]
        assert lvl2['name'] == 'lvl2'
        lvl3 = lvl2['nested_metatasks'][0]
        assert lvl3['name'] == 'lvl3'
        assert [t['name'] for t in lvl3['tasks']] == ['t3']


class TestParseRocotoXML:
    """R6.2: end-to-end parse of a minimal workflow."""

    def test_minimal_workflow(self, tmp_path):
        xml = (
            '<!DOCTYPE workflow [<!ENTITY EXP "myexp">]>\n'
            '<workflow scheduler="slurm" realtime="F">'
            '<cycledef group="gfs">202401010000 202401020000 06:00:00</cycledef>'
            '<task name="&EXP;_prep"><command>/p.sh</command></task>'
            '<metatask name="efcs"><var name="m">1 2</var>'
            '<task name="efcs_t"><command>/e.sh</command>'
            '<dependency><taskdep task="myexp_prep"/></dependency></task>'
            '</metatask>'
            '</workflow>'
        )
        p = tmp_path / "myexp.xml"
        p.write_text(xml)
        parsed = RocotoXMLParser.parse_rocoto_xml(str(p))
        assert parsed['entities'] == {'EXP': 'myexp'}
        assert parsed['workflow']['scheduler'] == 'slurm'
        assert parsed['cycledefs'][0]['group'] == 'gfs'
        assert parsed['tasks'][0]['name'] == 'myexp_prep'
        assert parsed['metatasks'][0]['name'] == 'efcs'
        assert parsed['metatasks'][0]['tasks'][0]['dependency_names'] == ['myexp_prep']
