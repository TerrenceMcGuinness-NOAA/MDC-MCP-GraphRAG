import os
import json
import pytest
from src.error_analysis.extractor import filter_noise, extract_signal, MAX_SIGNAL_BYTES
from src.error_analysis.classifier import classify
from src.tools.error_analysis import register
from fastmcp import FastMCP

class MockMCP:
    def __init__(self):
        self.tools = {}
        
    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator

def test_classifier():
    assert classify("some make Error 1 text") == "build"
    assert classify("Segmentation fault (core dumped)") == "segfault"
    assert classify("HTAR FAILED") == "hpss_fetch"
    assert classify("Nothing wrong here") == "unknown"

def test_filter_noise():
    lines = [
        "+ declare -rx VAR=1",
        "+ export VAR2=2",
        "+ module load python",
        "_ModuleTable1_={",
        "a=1,",
        "b=2",
        "}",
        "echo test",
        "Traceback (most recent call last):"
    ]
    filtered = filter_noise(lines)
    assert not any("declare -rx" in l for l in filtered)
    assert not any("export" in l for l in filtered)
    assert not any("_ModuleTable" in l for l in filtered)
    assert "echo test" in filtered
    assert "Traceback (most recent call last):" in filtered

def test_extract_signal():
    log_text = "Some intro text\nexit 2\n"
    res = extract_signal(log_text)
    assert res['exit_code'] == "2"
    assert "Some intro" in res['diagnostic_signal']

def test_extract_signal_size_limit():
    # create a huge string
    huge_text = "a" * (MAX_SIGNAL_BYTES + 1000)
    res = extract_signal(huge_text)
    assert len(res['diagnostic_signal'].encode('utf-8')) <= MAX_SIGNAL_BYTES
    assert res['omitted_bytes'] > 0

def test_extract_ci_error_signal_tool():
    mcp = MockMCP()
    register(mcp)
    
    tool_func = mcp.tools['extract_ci_error_signal']
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "error_logs", "sample.log")
    
    res_str = tool_func(fixture_path)
    res = json.loads(res_str)
    
    assert res['taxonomy_class'] == "python_traceback"
    assert res['exit_code'] == "1"
    assert "Traceback (most recent call last):" in res['diagnostic_signal']
    assert "_ModuleTable" not in res['diagnostic_signal']
