def safe_csv_cell(value):
    """Keep untrusted text from being interpreted as a spreadsheet formula."""
    if isinstance(value, str):
        stripped = value.lstrip()
        if value.startswith(("\t", "\r", "\n")) or stripped.startswith(("=", "+", "-", "@")):
            return "'" + value
    return value
