"""
YAML 辅助函数，用于处理 yml/yaml 相关操作。
"""

# third party module
import yaml

# official module
import os
from typing import Any, List


def safe_load(
        filepath: str,
        encoding: str = 'utf-8',
        extra_matches: List[str] = [
            'user',
        ],
        match_format: str = '{filename}.{extra_matches}.{ext}',
) -> Any:
    """
    Load a YAML file and return the parsed data.

    Automatically detects extra files such as config.user.yaml. If found, their
    contents are recursively merged into the original file (i.e. the user file
    overrides the corresponding entries in the original file).

    Args:
        filepath: Path to the YAML file to load.
        encoding: Encoding used when reading the file, defaults to 'utf-8'.
        extra_matches: List of extra identifiers used to match and override the
            original file, defaults to ['user'].
        match_format: Format of the extra file name. Available placeholders are
            {filename}, {extra_matches} and {ext} (where {ext} has no leading dot).
            Option 1 (default): '{filename}.{extra_matches}.{ext}' (matches config.user.yaml)
            Option 2          : '{filename}.{ext}.{extra_matches}' (matches config.yaml.user).

    Returns:
        The parsed and merged data.

    Example:
        >>> # config.yaml and config.user.yaml in the same directory are merged
        >>> data = safe_load('config.yaml')
    """

    basename = os.path.basename(filepath)
    dirname = os.path.dirname(filepath)
    filename, ext = os.path.splitext(basename)
    # os.path.splitext 返回的扩展名带前导点（如 .yaml），去掉点便于在 match_format 中自由排列
    ext = ext.lstrip('.')

    with open(filepath, 'r', encoding=encoding) as f:
        original_data = yaml.safe_load(f)

    # merge user data into original data recursively
    def update_dict(original, user):
        for key, value in user.items():
            if key in original:
                if isinstance(original[key], dict) and isinstance(value, dict):
                    update_dict(original[key], value)
                else:
                    original[key] = value

    for m in extra_matches:
        user_basename = match_format.format(filename=filename, extra_matches=m, ext=ext)
        user_filename = os.path.join(dirname, user_basename)

        if os.path.exists(user_filename):
            with open(user_filename, 'r', encoding=encoding) as f:
                user_data = yaml.safe_load(f)
            if isinstance(original_data, dict) and isinstance(user_data, dict):
                update_dict(original_data, user_data)

    return original_data


__all__ = ['safe_load']
