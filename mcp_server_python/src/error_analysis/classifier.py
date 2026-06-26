import re

# Ordered failure taxonomy
TAXONOMY_RULES = [
    ("hpss_fetch", [r"HTAR FAILED", r"Connection refused.*HPSS", r"htar returned non-zero"]),
    ("build", [r"cmake", r"make", r"undefined reference", r"Error 1"]),
    ("forecast_model", [r"fcst.*abort", r"MPI_ABORT", r"forrtl:", r"FATAL"]),
    ("timeout", [r"DUE TO TIME LIMIT", r"CANCELLED", r"walltime exceeded"]),
    ("oom", [r"Out of memory", r"oom-kill", r"Killed"]),
    ("segfault", [r"Segmentation fault", r"signal 11"]),
    ("missing_file", [r"No such file or directory", r"cannot stat"]),
    ("rocoto", [r"rocotostat", r"rocoto.*dryrun"]),
    ("python_traceback", [r"Traceback \(most recent call last\)"]),
]

def classify(log_text: str) -> str:
    """
    Scans log text and returns the first matching taxonomy class.
    
    Parameters
    ----------
    log_text : str
        The distilled diagnostic signal or full log text to classify.
        
    Returns
    -------
    str
        The taxonomy class or 'unknown' if no match is found.
    """
    for class_name, patterns in TAXONOMY_RULES:
        for pattern in patterns:
            if re.search(pattern, log_text, re.IGNORECASE):
                return class_name
    return "unknown"
