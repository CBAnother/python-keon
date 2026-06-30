# PDF 模块

用于合并和操作 PDF 文件的工具函数。

## 函数

### `concat_pdf(pdf_files, output_file=None)`

将多个 PDF 文件合并为一个 PDF 文件。

**参数：**

- `pdf_files` (list[str]): 要合并的 PDF 文件路径列表
- `output_file` (str, 可选): 输出文件路径。如果为 None，则在第一个输入文件所在目录下创建 'merged.pdf'

**返回值：**
- `str`: 合并后的 PDF 文件路径

**异常：**
- `ValueError`: 如果 pdf_files 列表为空
- `FileNotFoundError`: 如果任何输入的 PDF 文件不存在

**示例：**

```python
from keon.pdf import concat_pdf

# 合并多个 PDF 文件
pdf_files = [
    r'E:\Documents\file1.pdf',
    r'E:\Documents\file2.pdf',
    r'E:\Documents\file3.pdf'
]

# 在第一个输入文件所在目录下创建合并后的 PDF
output = concat_pdf(pdf_files)
print(f"已创建合并的 PDF: {output}")  # 输出: E:\Documents\merged.pdf

# 或者指定自定义输出路径
output = concat_pdf(pdf_files, output_file=r'E:\Documents\custom_name.pdf')
```

## 依赖

```bash
pip install pypdf
```
