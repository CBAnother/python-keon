# PostgreSQL 备份/恢复

通过 Docker 运行 `pg_dump` / `psql`，生成可在终端执行的备份与恢复命令。适合本地没有安装 PostgreSQL 客户端、但已安装 Docker 的场景。

## 依赖

- Docker（需能拉取并运行 `postgres:18-alpine`，或通过 `image` 参数指定其他镜像）



## 函数说明

| 函数 | 说明 |
|------|------|
| `build_pg_backup_cmd(...)` | 生成 `pg_dump` 的 docker 命令 |
| `build_pg_restore_cmd(...)` | 生成 `psql` 恢复的 docker 命令 |
| `print_backup_cmd(...)` | 生成备份命令并打印、复制到剪贴板 |
| `print_restore_cmd(...)` | 生成恢复命令并打印、复制到剪贴板 |

## 参数

`build_pg_backup_cmd` / `build_pg_restore_cmd` / `print_*` 共用以下关键字参数：

| 参数 | 说明 |
|------|------|
| `username` | 数据库用户名 |
| `password` | 数据库密码 |
| `host` | 主机地址（容器内可访问，如 `host.docker.internal`） |
| `port` | 端口 |
| `db_name` | 数据库名 |
| `backup_name` | 备份文件名，默认与 `db_name` 相同并自动加 `.sql` |
| `image` | Docker 镜像，默认 `postgres:18-alpine` |

备份文件会写入**当前工作目录**（容器内挂载为 `/dump`）。

## 使用示例

### 仅生成命令

```python
import keon

cmd = keon.postgres.build_pg_backup_cmd(
    username="postgres",
    password="secret",
    host="host.docker.internal",
    port=5432,
    db_name="myapp",
)
print(cmd)
```

### 生成并复制到剪贴板

```python
import keon

keon.postgres.print_backup_cmd(
    username="postgres",
    password="secret",
    host="host.docker.internal",
    port=5432,
    db_name="myapp",
    backup_name="myapp_backup.sql",
)
```

### 恢复

```python
import keon

keon.postgres.print_restore_cmd(
    username="postgres",
    password="secret",
    host="host.docker.internal",
    port=5432,
    db_name="myapp",
)
```

在目标目录执行打印出的命令前，请确认 SQL 文件已存在于当前目录。
