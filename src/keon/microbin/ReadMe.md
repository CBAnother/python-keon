# MicroBin 模块

用于向 [MicroBin](https://github.com/szabodanika/microbin) 实例上传文本和文件附件。

## 配置

通过参数或环境变量指定服务器与认证信息：

| 环境变量 | 说明 |
| --- | --- |
| `MICROBIN_SERVER` | 服务器地址，例如 `https://paste.example.com` |
| `MICROBIN_UPLOADER_PASSWORD` | 服务端要求的上传密码 |
| `MICROBIN_AUTH` | HTTP Basic 认证，格式 `username:password` |

## 上传选项

| 参数 | 表单字段 | 说明 |
| --- | --- | --- |
| `expiration` | `expiration` | `1min`、`1hour`、`24hour`、`1week`、`never` 等 |
| `burn_after` | `burn_after` | 阅读次数上限：`1`、`10`、`100`、`1000`、`10000` |
| `syntax` | `syntax_highlight` | 语法高亮，如 `py`、`yaml`、`none`，默认 `auto` |
| `privacy` | `privacy` | `public`、`unlisted`、`readonly`、`private`、`secret` |
| `password` | `plain_key` | 访问密码（private/readonly/secret 时使用） |
| `content` | `content` | 文本内容 |
| `files` | `file` | 单个或多个文件附件 |

## 上传选项枚举

```python
from keon.microbin import Expiration, Privacy, BurnAfter, upload_text

url = upload_text(
    "hello",
    server="https://paste.example.com",
    expiration=Expiration.NEVER,
    privacy=Privacy.PUBLIC,
    burn_after=BurnAfter.TEN,
)
```

| 枚举 | 成员示例 |
| --- | --- |
| `Expiration` | `MIN_1`, `HOUR_1`, `WEEK_1`, `NEVER` |
| `Privacy` | `PUBLIC`, `UNLISTED`, `PRIVATE`, `SECRET` |
| `BurnAfter` | `ONCE`, `TEN`, `HUNDRED`, `THOUSAND` |

仍可直接传入字符串或整数，例如 `expiration="never"`、`privacy="public"`。

## 删除 paste

```python
from keon.microbin import remove

# 按 slug 删除
remove("cat-dog-fox", server="https://paste.example.com")

# 也支持完整 URL；受密码保护的 paste 需传入 password
remove(
    "https://paste.example.com/upload/cat-dog-fox",
    server="https://paste.example.com",
    password="my-secret",
)
```

## 上传文本

```python
from keon.microbin import upload_text

url = upload_text(
    "print('hello')",
    server="https://paste.example.com",
    syntax="py",
    privacy="public",
    expiration="never",
)
print(url)
```

## 上传文件

```python
from keon.microbin import upload

result = upload(
    files=r"E:\Documents\report.pdf",
    server="https://paste.example.com",
    expiration="1week",
    privacy="unlisted",
)
print(result.url, result.slug)
```

## 文本 + 附件 + 高级选项

```python
from keon.microbin import upload

result = upload(
    content="见附件",
    files=["debug.log", "screenshot.png"],
    server="https://paste.example.com",
    syntax="none",
    privacy="private",
    password="my-secret",
    burn_after=10,
    expiration="24hour",
)
```

## 依赖

项目已包含 `requests`，无需额外安装。
