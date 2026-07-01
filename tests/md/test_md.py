import tempfile
from pathlib import Path

import pytest

from keon.md import get_images, get_tables


def test_get_images_with_http_urls(tmp_path):
    """测试提取 HTTP/HTTPS 图片链接"""
    md_file = tmp_path / 'test.md'
    content = """
# Title

Some text with an image:

![logo](https://example.com/logo.png)

Another image ![screenshot](https://github.com/user/repo/screenshot.jpg)

Local image (should be skipped):
![local](./images/local.png)
![relative](../assets/image.jpg)
"""
    md_file.write_text(content, encoding='utf-8')
    
    images = get_images(md_file)
    
    assert len(images) == 2
    assert ('logo', 'https://example.com/logo.png') in images
    assert ('screenshot', 'https://github.com/user/repo/screenshot.jpg') in images


def test_get_images_skips_local_paths(tmp_path):
    """测试跳过本地相对路径"""
    md_file = tmp_path / 'test.md'
    content = """
![local1](./images/pic.png)
![local2](../assets/image.jpg)
![local3](images/test.png)
![absolute](/home/user/pic.png)
"""
    md_file.write_text(content, encoding='utf-8')
    
    images = get_images(md_file)
    
    assert len(images) == 0


def test_get_images_empty_alt_text(tmp_path):
    """测试空的 alt text"""
    md_file = tmp_path / 'test.md'
    content = """
![](https://example.com/no-alt.png)
![with-alt](https://example.com/with-alt.png)
"""
    md_file.write_text(content, encoding='utf-8')
    
    images = get_images(md_file)
    
    assert len(images) == 2
    assert ('', 'https://example.com/no-alt.png') in images
    assert ('with-alt', 'https://example.com/with-alt.png') in images


def test_get_images_multiple_images_same_line(tmp_path):
    """测试同一行有多个图片"""
    md_file = tmp_path / 'test.md'
    content = "![img1](https://example.com/1.png) text ![img2](https://example.com/2.png)\n"
    md_file.write_text(content, encoding='utf-8')
    
    images = get_images(md_file)
    
    assert len(images) == 2
    assert ('img1', 'https://example.com/1.png') in images
    assert ('img2', 'https://example.com/2.png') in images


def test_get_images_empty_file(tmp_path):
    """测试空文件"""
    md_file = tmp_path / 'empty.md'
    md_file.write_text('', encoding='utf-8')
    
    images = get_images(md_file)
    
    assert images == []


def test_get_images_no_images(tmp_path):
    """测试没有图片的 Markdown 文件"""
    md_file = tmp_path / 'no-images.md'
    content = """
# Title

Just some text with [links](https://example.com) but no images.

- List item 1
- List item 2
"""
    md_file.write_text(content, encoding='utf-8')
    
    images = get_images(md_file)
    
    assert images == []


def test_get_images_with_special_chars_in_url(tmp_path):
    """测试 URL 中包含特殊字符"""
    md_file = tmp_path / 'test.md'
    content = """
![image](https://example.com/image.png?size=large&format=webp)
![encoded](https://example.com/path%20with%20spaces/image.png)
"""
    md_file.write_text(content, encoding='utf-8')
    
    images = get_images(md_file)
    
    assert len(images) == 2
    assert ('image', 'https://example.com/image.png?size=large&format=webp') in images
    assert ('encoded', 'https://example.com/path%20with%20spaces/image.png') in images


def test_get_images_with_string_path(tmp_path):
    """测试传入字符串路径"""
    md_file = tmp_path / 'test.md'
    content = "![test](https://example.com/test.png)"
    md_file.write_text(content, encoding='utf-8')
    
    # 传入字符串路径而非 Path 对象
    images = get_images(str(md_file))
    
    assert len(images) == 1
    assert ('test', 'https://example.com/test.png') in images


def test_get_images_with_different_encoding(tmp_path):
    """测试不同编码"""
    md_file = tmp_path / 'test.md'
    content = "![测试图片](https://example.com/中文.png)"
    md_file.write_text(content, encoding='gbk')
    
    images = get_images(md_file, encoding='gbk')
    
    assert len(images) == 1
    assert ('测试图片', 'https://example.com/中文.png') in images


def test_get_images_http_vs_https(tmp_path):
    """测试同时包含 HTTP 和 HTTPS"""
    md_file = tmp_path / 'test.md'
    content = """
![http](http://example.com/http.png)
![https](https://example.com/https.png)
"""
    md_file.write_text(content, encoding='utf-8')
    
    images = get_images(md_file)
    
    assert len(images) == 2
    assert ('http', 'http://example.com/http.png') in images
    assert ('https', 'https://example.com/https.png') in images


def test_get_tables_single_table(tmp_path):
    """测试提取单个 Markdown 表格"""
    md_file = tmp_path / 'test.md'
    content = """\
| Name     | path              | status | note |
| -------- | ----------------- | ------ | ---- |
| Alpha    | run_001_baseline  | ✅      |      |
| Beta     | run_002_variant   | ✅      |      |
| Gamma    | run_003_variant   | ✅      | done |
"""
    md_file.write_text(content, encoding='utf-8')

    tables = get_tables(md_file)

    assert len(tables) == 1
    df = tables[0]
    assert list(df.columns) == ['Name', 'path', 'status', 'note']
    assert len(df) == 3
    assert df.iloc[0]['Name'] == 'Alpha'
    assert df.iloc[0]['path'] == 'run_001_baseline'
    assert df.iloc[0]['status'] == '✅'
    assert df.iloc[0]['note'] == ''
    assert df.iloc[2]['Name'] == 'Gamma'
    assert df.iloc[2]['note'] == 'done'


def test_get_tables_multiple_tables(tmp_path):
    """测试提取多个表格"""
    md_file = tmp_path / 'test.md'
    content = """\
# Report

| A | B |
| - | - |
| 1 | 2 |

Some text between tables.

| X | Y |
| - | - |
| foo | bar |
"""
    md_file.write_text(content, encoding='utf-8')

    tables = get_tables(md_file)

    assert len(tables) == 2
    assert list(tables[0].columns) == ['A', 'B']
    assert tables[0].iloc[0].tolist() == ['1', '2']
    assert list(tables[1].columns) == ['X', 'Y']
    assert tables[1].iloc[0].tolist() == ['foo', 'bar']


def test_get_tables_empty_file(tmp_path):
    """测试空文件"""
    md_file = tmp_path / 'empty.md'
    md_file.write_text('', encoding='utf-8')

    assert get_tables(md_file) == []


def test_get_tables_no_tables(tmp_path):
    """测试没有表格的 Markdown 文件"""
    md_file = tmp_path / 'no-tables.md'
    content = """
# Title

Just some text with [links](https://example.com).
"""
    md_file.write_text(content, encoding='utf-8')

    assert get_tables(md_file) == []


def test_get_tables_header_only(tmp_path):
    """测试仅有表头和分隔行的空表格"""
    md_file = tmp_path / 'test.md'
    content = """\
| Col1 | Col2 |
| ---- | ---- |
"""
    md_file.write_text(content, encoding='utf-8')

    tables = get_tables(md_file)

    assert len(tables) == 1
    assert list(tables[0].columns) == ['Col1', 'Col2']
    assert len(tables[0]) == 0


def test_get_tables_with_string_path(tmp_path):
    """测试传入字符串路径"""
    md_file = tmp_path / 'test.md'
    content = """\
| name |
| ---- |
| test |
"""
    md_file.write_text(content, encoding='utf-8')

    tables = get_tables(str(md_file))

    assert len(tables) == 1
    assert tables[0].iloc[0]['name'] == 'test'
