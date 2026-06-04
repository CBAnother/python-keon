# keon.conda

管理 conda 环境，并在指定环境内安装包、执行命令或脚本。

## 功能

- `Conda` 类：列出、查询、创建、移除环境
- `CondaEnv` 类：在某个环境内 conda install / pip install、执行命令与脚本

## 管理环境

```python
import keon

conda = keon.conda.Conda()

conda.list_envs()          # ['base', 'py310', ...]
conda.exists('py310')      # True / False

# 创建环境（可指定 Python 版本、初始包、channel），返回环境句柄
env = conda.create('demo', python='3.10', packages=['numpy'], channels='conda-forge')

# 移除环境
conda.remove('demo')
```

## 在环境内安装包

```python
env = keon.conda.CondaEnv('py310')

# conda install
env.conda_install('numpy pandas', channels='conda-forge')

# pip install（通过该环境的 pip）
env.pip_install(['requests', 'rich'], upgrade=True)

# 按参数选择包管理器
env.install('scipy', manager='conda')
env.install('flask', manager='pip')
```

## 在环境内执行命令 / 脚本

```python
env = keon.conda.CondaEnv('py310')

# 任意命令（含空格或引号时建议传列表）
env.run('python --version')
env.run(['python', '-c', 'print("hello")'])

# 执行脚本
env.run_script('main.py', args=['--debug'])

# 执行一段（可多行的）Python 代码
env.run_code("import sys\nprint(sys.version)")

# 列出已安装的包
env.list_packages()
```

> `conda run` 不支持「参数中含换行」，所以多行代码**不能**用 `python -c` / `run(['python','-c', 多行代码])`，
> 否则 conda 会直接报错。请用 `run_code(代码字符串)`（自动写入临时 `.py` 文件再执行），
> 或先把代码存成 `.py` 文件再 `run_script(文件路径)`。

### 输出模式

`run` / `run_script` / `python` / `conda_install` / `pip_install` 都支持三种输出模式：

```python
# 1) 默认：实时打印到终端，但 result.stdout 为 None
env.run('python --version')

# 2) capture=True：仅捕获，result.stdout / result.stderr 拿得到文本，终端不实时显示
r = env.run('python --version', capture=True)
print(r.stdout, r.stderr)

# 3) tee=True：既实时打印、又把输出捕获到 result.stdout（耗时命令最实用）
r = env.run_script('train.py', tee=True)
print(r.stdout)
```

> Windows 提示：默认模式下子进程直接占用当前终端，某些程序（如带进度条/日志 UI 的工具）
> 会清空你的屏幕。`capture=True` 或 `tee=True` 时子进程会脱离当前控制台，既能拿到输出、
> 也不会再清屏。

> 实时性提示：`tee` 是否“逐行实时”取决于子进程是否**及时刷新缓冲**。输出被重定向到管道时，
> 很多程序（包括 Python）会从行缓冲切换为块缓冲，导致看起来“最后才一次性输出”。
> `run_code` 默认以 `python -u` 无缓冲运行，配合 `tee` 即可逐行实时：
>
> ```python
> code = "import time\nfor i in range(5):\n    print(i, flush=True)\n    time.sleep(1)"
> env.run_code(code, tee=True)   # 每秒输出一个数字
> ```



## 执行多条指令

默认不支持，可以用 shell 的方式支持，例如

```python
env.run(['powershell', '-NoProfile', '-Command', 'mineru --version; echo 完成'], tee=True)
```

