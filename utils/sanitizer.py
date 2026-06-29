import html
import re
from typing import Any, Optional


def decode_html_entities(value: Any, max_passes: int = 5) -> Optional[str]:
    """Decode single- or repeatedly-encoded HTML entities into plain text."""
    if value is None:
        return None

    text = str(value)
    for _ in range(max(1, int(max_passes))):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text.replace("\xa0", " ")

def sanitize_string(value: Any) -> Optional[str]:
    """
    Canonicalizes stored strings without turning ordinary names into HTML.
    - Trims whitespace
    - Decodes repeated HTML entities such as ``&amp;amp;``
    - Removes HTML tags (output layers still perform their own escaping)
    - Removes non-printable control characters
    """
    if value is None:
        return None
        
    # Ensure it's a string
    text = (decode_html_entities(value) or "").strip()
    
    # 1. Remove non-printable control characters (except common ones like newline/tab)
    # This prevents UI layout breaks and invisible character injections
    text = "".join(char for char in text if char.isprintable() or char in "\n\r\t")
    
    # Stored values are plain text. Escaping belongs at the HTML output layer;
    # storing escaped text is what produced literal &amp; and &#x27; owner names.
    text = re.sub(r"<[^>]*>", "", text)
    
    return text

def sanitize_numeric_string(value: Any) -> Optional[str]:
    """
    Specifically for numeric fields stored as strings (like TD numbers or PINs).
    Removes common exploit characters but keeps common municipal ID separators.
    """
    if value is None:
        return None
    
    text = str(value).strip()
    # Keep digits, hyphens, periods, slashes, spaces, and alphanumeric chars for municipal IDs
    return re.sub(r"[^0-9a-zA-Z\-\./ #:]", "", text)


def csv_safe_cell(value: Any) -> str:
    """
    Neutralises CSV/spreadsheet formula injection.

    Spreadsheet apps (Excel, LibreOffice, Google Sheets) interpret a cell whose
    value begins with '=', '+', '-', '@', a tab, or a carriage return as a
    formula. A malicious value like '=HYPERLINK(...)' or '=cmd|...' in an
    exported report can execute when the file is opened. We prefix such values
    with a single quote so they are treated as literal text.

    Safe values are returned unchanged (stringified). None becomes an empty
    string so it serialises cleanly into a CSV cell.
    """
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text
