# keon.md

Markdown 文件处理辅助函数。

## 功能

- `get_images()` - 提取 Markdown 文件中的所有图片链接

## 使用

### 获取图片链接

提取 Markdown 文件中所有以 `http://` 或 `https://` 开头的图片链接：

```python
from keon.md import get_images

# 获取 Markdown 文件中的所有在线图片
images = get_images('README.md')

for name, url in images:
    print(f"{name}: {url}")
# 输出示例：
# logo: https://example.com/logo.png
# screenshot: https://github.com/user/repo/raw/main/screenshot.jpg
```

**注意**：只返回 HTTP/HTTPS 开头的图片 URL，本地相对路径的图片会被跳过。

#### 参数说明

- `file`: Markdown 文件路径（字符串或 Path 对象）
- `encoding`: 文件编码，默认 `'utf-8'`

#### 返回值

返回 `list[tuple[str, str]]`，每个元组包含：
- 图片名称（alt text）
- 图片 URL

## 使用场景

- 检查 Markdown 文档中的外部图片链接
- 批量下载文档中的图片
- 验证图片链接是否有效
- 生成文档中使用的图片清单
