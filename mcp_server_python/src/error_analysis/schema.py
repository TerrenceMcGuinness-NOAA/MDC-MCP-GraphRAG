from dataclasses import dataclass
from typing import Optional, List

@dataclass
class ErrorRecord:
    """
    Normalized representation of a distilled CI error log.
    
    Attributes:
        taxonomy_class: The classified failure type (e.g., 'oom', 'build', 'hpss_fetch').
        diagnostic_signal: The extracted error signal (capped at 8KB).
        omitted_bytes: Number of noise/excess bytes stripped from the original log.
        exit_code: The captured exit status, if found.
        extracted_symbols: Potential function names or scripts detected in the signal.
        recommended_next_steps: Suggested vectors for the LLM's next search.
    """
    taxonomy_class: str
    diagnostic_signal: str
    omitted_bytes: int
    exit_code: Optional[str] = None
    extracted_symbols: Optional[List[str]] = None
    recommended_next_steps: Optional[List[str]] = None
