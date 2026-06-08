"""
Markdown 辅助函数。
"""

import re
from pathlib import Path
from typing import List, Tuple, Union


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
