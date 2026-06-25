# 获取 Github Release 信息

由于 Github 存在 REST API 调用速率限制，因此在获取版本时，最好自己提供一个 Github Token，避免获取不了的情况



## 获取版本号

```python
keon.github.get_latest_version('https://github.com/jgm/pandoc/releases', token='xxx')
```



## 获取下载链接

```python
release = keon.github.get_latest_release('https://github.com/jgm/pandoc/releases', token='xxx')
release.download_urls('*windows*.zip')
```

