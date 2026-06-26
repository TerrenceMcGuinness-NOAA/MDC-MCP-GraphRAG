import os
import json
import dataclasses
from fastmcp import FastMCP
from typing import Any

from src.error_analysis.extractor import extract_signal
from src.error_analysis.classifier import classify
from src.error_analysis.schema import ErrorRecord

def register(mcp: FastMCP, data: Any = None) -> None:
    """
    Registers the error analysis tool with the FastMCP instance.
    """
    
    @mcp.tool()
    def extract_ci_error_signal(log_path: str) -> str:
        """
        Distill a CI error log into a high-entropy ErrorRecord.
        
        This tool reads a large raw log file, filters out noise, caps the output at 8KB 
        to fit LLM context limits, and classifies the failure according to the CI taxonomy.
        
        Parameters
        ----------
        log_path : str
            Absolute path to the raw log file.
            
        Returns
        -------
        str
            JSON string representation of the ErrorRecord.
        """
        if not os.path.exists(log_path):
            return json.dumps({"error": f"File not found: {log_path}"})
            
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                log_text = f.read()
                
            extracted = extract_signal(log_text)
            diagnostic_signal = extracted['diagnostic_signal']
            omitted_bytes = extracted['omitted_bytes']
            exit_code = extracted['exit_code']
            
            taxonomy_class = classify(diagnostic_signal)
            if taxonomy_class == "unknown":
                # Try classifying on the full log just in case signal truncated the marker
                full_class = classify(log_text)
                if full_class != "unknown":
                    taxonomy_class = full_class
                    
            record = ErrorRecord(
                taxonomy_class=taxonomy_class,
                diagnostic_signal=diagnostic_signal,
                omitted_bytes=omitted_bytes,
                exit_code=exit_code
            )
            
            return json.dumps(dataclasses.asdict(record), indent=2)
            
        except Exception as e:
            return json.dumps({"error": f"Failed to process log: {str(e)}"})
