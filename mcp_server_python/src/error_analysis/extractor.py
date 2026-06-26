import re

MAX_SIGNAL_BYTES = 8192

def filter_noise(lines: list[str]) -> list[str]:
    """
    Strips low-entropy noise lines from the log.
    
    Parameters
    ----------
    lines : list[str]
        Raw log lines.
        
    Returns
    -------
    list[str]
        Filtered log lines.
    """
    filtered = []
    in_module_table = False
    
    noise_patterns = [
        re.compile(r"^\+* *declare -rx"),
        re.compile(r"^\+* *export "),
        re.compile(r"^\+* *module (load|unload|use)"),
    ]
    
    for line in lines:
        if "_ModuleTable" in line and "=" in line:
            in_module_table = True
            continue
        if in_module_table:
            # Module tables usually end when a new prompt or normal command starts.
            if re.match(r"^[^a-zA-Z0-9+/= ]", line) or " " in line:
                in_module_table = False
            else:
                continue
                
        if any(p.search(line) for p in noise_patterns):
            continue
            
        filtered.append(line)
        
    return filtered

def extract_signal(log_text: str) -> dict:
    """
    Extracts the high-entropy signal from a raw log.
    
    Parameters
    ----------
    log_text : str
        The raw log text.
        
    Returns
    -------
    dict
        Dictionary containing 'diagnostic_signal', 'omitted_bytes', and 'exit_code'.
    """
    original_size = len(log_text.encode('utf-8'))
    lines = log_text.splitlines()
    
    # 1. Filter noise
    filtered_lines = filter_noise(lines)
    
    # 2. Reconstruct
    filtered_text = "\n".join(filtered_lines)
    
    # 3. Extract exit code if present near the end
    exit_code = None
    exit_patterns = [
        r"exit\s+(\d+)",
        r"status=(\d+)",
        r"RETURN CODE\s*(\d+)",
        r"error code\s*(\d+)"
    ]
    tail_text = "\n".join(filtered_lines[-50:]) # Check last 50 lines
    for pattern in exit_patterns:
        match = re.search(pattern, tail_text, re.IGNORECASE)
        if match:
            exit_code = match.group(1)
            break
            
    # 4. Enforce 8KB Cap
    # To preserve the tail (where errors usually are), we keep the end of the log
    signal_bytes = filtered_text.encode('utf-8')
    if len(signal_bytes) > MAX_SIGNAL_BYTES:
        signal_bytes = signal_bytes[-MAX_SIGNAL_BYTES:]
        # Try to align to a clean newline if we truncated from the middle
        try:
            signal_text = signal_bytes.decode('utf-8', errors='ignore')
            first_newline = signal_text.find('\n')
            if first_newline != -1 and first_newline < 500:
                signal_text = signal_text[first_newline + 1:]
        except UnicodeDecodeError:
            signal_text = signal_bytes.decode('utf-8', errors='ignore')
    else:
        signal_text = filtered_text
        
    omitted_bytes = original_size - len(signal_text.encode('utf-8'))
    
    return {
        "diagnostic_signal": signal_text,
        "omitted_bytes": max(0, omitted_bytes),
        "exit_code": exit_code
    }
