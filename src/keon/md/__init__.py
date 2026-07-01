"""
Markdown 辅助函数。
"""

import re
from pathlib import Path
from typing import List, Optional, Tuple, Union

import pandas as pd


def get_images(file: Union[str, Path], encoding: str = 'utf-8') -> List[Tuple[str, str]]:
    """
    获取 Markdown 文件中的所有图片链接。

    仅返回以 http:// 或 https:// 开头的图片 URL（跳过本地相对路径）。

    Args:
        file: Markdown 文件路径。
        encoding: 文件编码，默认 'utf-8'。

    Returns:
        list[tuple[str, str]]: 图片信息列表，每项为 (图片名称, 图片URL) 元组。

    Example:
        >>> images = get_images('README.md')
        >>> for name, url in images:
        ...     print(f"{name}: {url}")
        logo: https://example.com/logo.png
        screenshot: https://example.com/screen.jpg
    """
    ptn = re.compile(r'!\[(.*?)\]\((.*?)\)')
    res = []
    
    with open(file, 'r', encoding=encoding) as f:
        lines = f.readlines()
    
    for line in lines:
        matches = ptn.findall(line)
        if matches:
            for name, url in matches:
                if url.startswith(('http://', 'https://')):
                    res.append((name, url))
    
    return res


def _parse_table_row(line: str) -> Optional[List[str]]:
    line = line.strip()
    if not line.startswith('|'):
        return None
    return [cell.strip() for cell in line.strip('|').split('|')]


def _is_separator_row(cells: List[str]) -> bool:
    return bool(cells) and all(re.match(r'^:?-+:?$', cell) for cell in cells)


def get_tables(file: Union[str, Path], encoding: str = 'utf-8') -> List[pd.DataFrame]:
    """
    获取 Markdown 文件中的所有表格。

    Args:
        file: Markdown 文件路径。
        encoding: 文件编码，默认 'utf-8'。

    Returns:
        list[pandas.DataFrame]: 表格列表，每个 DataFrame 对应文件中的一个 Markdown 表格。

    Example:
        >>> tables = get_tables('report.md')
        >>> for df in tables:
        ...     print(df)
           Name  path  status  note
        0  Alpha  run_001_baseline  ✅
    """
    tables: List[pd.DataFrame] = []
    block: List[str] = []

    def flush_block() -> None:
        nonlocal block
        if len(block) < 2:
            block = []
            return

        header = _parse_table_row(block[0])
        separator = _parse_table_row(block[1])
        if not header or not separator or not _is_separator_row(separator):
            block = []
            return

        n_cols = len(header)
        data_rows = []
        for line in block[2:]:
            row = _parse_table_row(line)
            if row is None:
                continue
            if len(row) < n_cols:
                row = row + [''] * (n_cols - len(row))
            else:
                row = row[:n_cols]
            data_rows.append(row)

        tables.append(pd.DataFrame(data_rows, columns=header))
        block = []

    with open(file, 'r', encoding=encoding) as f:
        for line in f:
            if line.strip().startswith('|'):
                block.append(line)
            else:
                flush_block()
    flush_block()

    return tables


__all__ = ['get_images', 'get_tables']
