"""
JSON utilities for parsing non-standard JSON formats.
"""

import re
import json
from typing import Any, Dict


def parse(text: str, strict: bool = False) -> Dict[str, Any]:
    """
    Parse a JSON string into a Python dictionary.

    By default, handles non-standard JSON-like text with:
    - Unquoted keys
    - Single-quoted strings
    - Emoji and Unicode characters
    - Nested objects

    Set strict=True to use standard JSON parsing only.

    Args:
        text: JSON string to parse
        strict: If True, use standard json.loads (default: False)

    Returns:
        Dictionary representation of the JSON

    Example:
        >>> text = "{ name: '🇺🇸美国01', type: vless, port: 443 }"
        >>> result = parse(text)
        >>> print(result['name'])
        🇺🇸美国01
    """
    if strict:
        return json.loads(text)

    # Remove leading/trailing whitespace
    text = text.strip()

    # Ensure the text starts with { and ends with }
    if not (text.startswith('{') and text.endswith('}')):
        raise ValueError("Input must be a JSON object starting with { and ending with }")
    
    # Step 1: Quote unquoted keys
    # Match pattern: word characters (including hyphens) followed by colon
    # But avoid matching keys that are already quoted
    def quote_keys(match):
        key = match.group(1)
        return f'"{key}":'
    
    # Pattern to find unquoted keys: word at start or after comma/brace, followed by colon
    text = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_-]*)\s*:', r'\1"\2":', text)
    
    # Step 2: Quote unquoted string values (but not booleans, numbers, or null)
    # This is tricky - we need to identify unquoted values that aren't numbers/booleans
    def quote_unquoted_values(text):
        result = []
        i = 0
        in_string = False
        string_char = None
        
        while i < len(text):
            char = text[i]
            
            # Track if we're inside a string
            if char in ('"', "'") and (i == 0 or text[i-1] != '\\'):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
            
            # If we find a colon outside a string, check the value after it
            if char == ':' and not in_string:
                result.append(char)
                i += 1
                
                # Skip whitespace after colon
                while i < len(text) and text[i].isspace():
                    result.append(text[i])
                    i += 1
                
                if i >= len(text):
                    break
                
                # Check if value is already quoted or is a special value
                if text[i] in ('"', "'", '{', '['):
                    # Already quoted or is an object/array
                    continue
                elif text[i:i+4] == 'true' or text[i:i+5] == 'false' or text[i:i+4] == 'null':
                    # Boolean or null
                    continue
                elif text[i].isdigit() or (text[i] == '-' and i+1 < len(text) and text[i+1].isdigit()):
                    # Number (integer or negative number)
                    # Check if it's a pure number (not a UUID or other string with numbers)
                    temp_i = i
                    if text[temp_i] == '-':
                        temp_i += 1
                    
                    # Check for integer or float
                    is_number = True
                    has_dot = False
                    while temp_i < len(text) and text[temp_i] not in (',', '}', ']', '\n', ' '):
                        if text[temp_i].isdigit():
                            temp_i += 1
                        elif text[temp_i] == '.' and not has_dot:
                            has_dot = True
                            temp_i += 1
                        else:
                            # Contains non-numeric characters (like hyphens in UUID)
                            is_number = False
                            break
                    
                    if is_number:
                        # It's a valid number, don't quote it
                        continue
                    # Otherwise fall through to quote it as a string
                
                # Unquoted string value - need to quote it
                value_start = i
                value_chars = []
                
                # Collect characters until we hit a delimiter
                # Allow hyphens in values (for UUIDs, domain names, etc.)
                while i < len(text) and text[i] not in (',', '}', ']', '\n'):
                    value_chars.append(text[i])
                    i += 1
                
                value = ''.join(value_chars).strip()
                if value:
                    result.append(f'"{value}"')
                continue
            
            result.append(char)
            i += 1
        
        return ''.join(result)
    
    text = quote_unquoted_values(text)
    
    # Step 3: Replace single quotes with double quotes (but be careful with escaped quotes)
    # We need to handle single-quoted strings properly
    def replace_single_quotes(text):
        result = []
        i = 0
        
        while i < len(text):
            if text[i] == "'":
                # Start of single-quoted string
                result.append('"')
                i += 1
                
                # Copy content until closing single quote
                while i < len(text):
                    if text[i] == '\\' and i + 1 < len(text):
                        # Escaped character
                        result.append(text[i])
                        result.append(text[i + 1])
                        i += 2
                    elif text[i] == "'":
                        # End of single-quoted string
                        result.append('"')
                        i += 1
                        break
                    else:
                        # Handle double quotes inside single-quoted strings
                        if text[i] == '"':
                            result.append('\\"')
                        else:
                            result.append(text[i])
                        i += 1
            else:
                result.append(text[i])
                i += 1
        
        return ''.join(result)
    
    text = replace_single_quotes(text)
    
    # Step 4: Parse the now-standard JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON: {e}\nProcessed text: {text}")


__all__ = ['parse']
