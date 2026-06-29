"""Conda 环境管理模块，提供环境的增删查以及在环境内安装包、执行命令/脚本的能力。"""
import os
import sys
import json
import shlex
import shutil
import tempfile
import threading
import subprocess
from typing import List, Dict, Optional, Sequence, Union

__all__ = ['Conda', 'CondaEnv', 'AsyncProcess']


# 包名 / 命令参数可以是字符串或字符串序列
StrOrList = Union[str, Sequence[str], None]


def _prefer_exe_over_bat(found: Optional[str], is_windows: bool) -> Optional[str]:
    """
    Windows 上若解析到的是 conda 的 .bat/.cmd 包装器，尽量改用同体系下的 conda.exe。

    经过 .bat 会多一层 cmd.exe 解析，含空格/换行的参数（如多行 `python -c` 代码）
    会被批处理拆断；直接用 conda.exe 走 CreateProcess 可原样传参。

    Args:
        found (str): 已解析到的 conda 路径。
        is_windows (bool): 当前是否为 Windows。

    Returns:
        str: 优先返回同目录体系的 conda.exe，否则原样返回。
    """
    if not found or not is_windows:
        return found
    if not found.lower().endswith(('.bat', '.cmd')):
        return found
    # 典型布局：<root>\condabin\conda.bat -> <root>\Scripts\conda.exe
    root = os.path.dirname(os.path.dirname(found))
    exe = os.path.join(root, 'Scripts', 'conda.exe')
    if os.path.isfile(exe):
        return exe
    return shutil.which('conda.exe') or found


def _resolve_conda(conda_exe: Optional[str] = None) -> str:
    """
    解析 conda 可执行文件路径。

    Args:
        conda_exe (str): 指定的 conda 可执行文件（如 'conda' / 'mamba' / 绝对路径），
                         为空时自动在 PATH 中查找。

    Returns:
        str: 可执行文件路径，找不到时退化为字面量 'conda'。
    """
    if conda_exe:
        return conda_exe
    found = _prefer_exe_over_bat(shutil.which('conda'), os.name == 'nt')
    return found or 'conda'


def _as_list(value: StrOrList) -> List[str]:
    """
    把字符串或序列规范化为字符串列表。

    Args:
        value: None、单个字符串（按空白切分）或字符串序列。

    Returns:
        list[str]: 规范化后的列表，None 返回空列表。
    """
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    return [str(v) for v in value]


def _strip_outer_quotes(arg: str) -> str:
    """去掉参数首尾成对的引号（Windows shlex posix=False 不会自动剥离）。"""
    if len(arg) >= 2 and arg[0] == arg[-1] and arg[0] in '"\'':
        return arg[1:-1]
    return arg


def _split_command(command: Union[str, Sequence[str]]) -> List[str]:
    """
    把命令规范化为参数列表。

    字符串会按 shell 规则切分（Windows 上 posix=False 以保留未加引号路径中的反斜杠），
    再剥离 Windows 下仍残留在参数上的外层引号。含空格路径更推荐直接传列表以避免歧义。

    Args:
        command: 命令字符串或参数序列。

    Returns:
        list[str]: 参数列表。
    """
    if isinstance(command, str):
        parts = shlex.split(command, posix=(os.name != 'nt'))
        if os.name == 'nt':
            parts = [_strip_outer_quotes(p) for p in parts]
        return parts
    return [str(c) for c in command]


def _channel_args(channels: StrOrList) -> List[str]:
    """
    把 channel 列表展开为 ['-c', ch, ...] 形式的参数。

    Args:
        channels: 单个 channel 字符串或 channel 序列。

    Returns:
        list[str]: 形如 ['-c', 'conda-forge'] 的参数列表。
    """
    args: List[str] = []
    for ch in _as_list(channels):
        args += ['-c', ch]
    return args


def _target_args(name: Optional[str], prefix: Optional[str]) -> List[str]:
    """
    生成定位某个环境的参数（按名称或按路径）。

    Args:
        name (str): 环境名称，对应 `-n`。
        prefix (str): 环境路径，对应 `-p`，优先级高于 name。

    Returns:
        list[str]: ['-p', prefix] 或 ['-n', name]。

    Raises:
        ValueError: name 与 prefix 均为空。
    """
    if prefix:
        return ['-p', str(prefix)]
    if name:
        return ['-n', name]
    raise ValueError("必须指定 name 或 prefix 之一")


def _norm_path(path: str) -> str:
    """
    规范化路径用于比较。

    `os.path.normpath` 不会统一盘符大小写（`C:\\` 与 `c:\\` 视为不同），
    Windows 文件系统却是大小写不敏感的；这里再叠加 `os.path.normcase`
    （Windows 上会转小写并统一分隔符）以得到可安全相等比较的形式。

    Args:
        path (str): 原始路径。

    Returns:
        str: 规范化后、可用于相等比较的路径。
    """
    return os.path.normcase(os.path.normpath(path))


def _same_path(a: Optional[str], b: Optional[str]) -> bool:
    """判断两个路径是否指向同一位置（大小写不敏感平台上忽略盘符等大小写）。"""
    if not a or not b:
        return False
    return _norm_path(a) == _norm_path(b)


def _env_name_from_prefix(prefix: str, root_prefix: Optional[str] = None) -> str:
    """
    从环境路径推断环境名称。

    Args:
        prefix (str): 环境的绝对路径。
        root_prefix (str): conda 根路径，与之相等时视为 base 环境。

    Returns:
        str: 环境名称，根环境返回 'base'，其余返回路径最后一段。
    """
    if root_prefix and _same_path(prefix, root_prefix):
        return 'base'
    return os.path.basename(os.path.normpath(prefix))


def _echo_cmd(cmd: Sequence[str]) -> str:
    """
    把命令拼成单行、便于阅读的回显字符串。

    含空白或换行的参数（如多行 `python -c` 代码）会被加引号并把换行转义为 `\\n`，
    避免回显时把参数内容铺成多行、看起来像“直接打印了代码”。
    """
    parts = []
    for a in cmd:
        s = str(a)
        if s == '' or any(ch.isspace() for ch in s):
            s = '"' + s.replace('\r', '').replace('\n', '\\n') + '"'
        parts.append(s)
    return ' '.join(parts)


def _no_window_flags(use_pipe: bool) -> int:
    """
    在 Windows 上让子进程脱离当前控制台（拥有独立的隐藏控制台）。

    当我们用管道接管子进程输出（capture / tee 模式）时，若子进程仍共享父进程
    控制台，它可以通过控制台 API（如 cls）直接清空用户当前终端——这与 stdout
    是否被重定向无关。给它一个独立控制台即可避免清屏。

    Args:
        use_pipe (bool): 是否以管道方式接管子进程输出。

    Returns:
        int: 传给 subprocess 的 creationflags，非 Windows 或非管道模式返回 0。
    """
    if use_pipe and os.name == 'nt':
        return getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    return 0


def _pump(pipe, sink, buf: List[str]) -> None:
    """逐行读取 pipe，实时写入 sink 并累积到 buf，读到 EOF 后关闭。"""
    try:
        for line in iter(pipe.readline, ''):
            sink.write(line)
            sink.flush()
            buf.append(line)
    finally:
        pipe.close()


def _run_tee(cmd, cwd, creationflags, encoding: Optional[str] = None) -> subprocess.CompletedProcess:
    """
    以 tee 方式执行：实时输出到当前终端，同时把 stdout/stderr 捕获到返回值。

    用两个线程分别泵 stdout / stderr，避免管道写满导致的死锁。
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        text=True,
        encoding=encoding,
        errors='replace' if encoding else None,
        bufsize=1,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
    )
    out_buf: List[str] = []
    err_buf: List[str] = []
    t_out = threading.Thread(target=_pump, args=(proc.stdout, sys.stdout, out_buf))
    t_err = threading.Thread(target=_pump, args=(proc.stderr, sys.stderr, err_buf))
    t_out.start()
    t_err.start()
    proc.wait()
    t_out.join()
    t_err.join()
    return subprocess.CompletedProcess(cmd, proc.returncode, ''.join(out_buf), ''.join(err_buf))


def _run(
        cmd: Sequence[str],
        capture: bool = False,
        tee: bool = False,
        check: bool = True,
        cwd: Optional[str] = None,
        echo: bool = False,
        encoding: Optional[str] = None,
        ) -> subprocess.CompletedProcess:
    """
    执行子进程命令。

    输出模式：
        - 默认（capture=False, tee=False）：继承当前终端实时输出，stdout/stderr 为 None。
        - capture=True：用管道捕获，结果带 stdout/stderr，不在终端实时显示。
        - tee=True：实时输出到终端，同时把 stdout/stderr 捕获到返回值（优先级高于 capture）。

    capture 或 tee 模式下，Windows 会让子进程脱离当前控制台，避免其清空终端。

    Args:
        cmd (Sequence[str]): 命令及参数列表。
        capture (bool): 是否仅捕获输出。
        tee (bool): 是否同时实时输出并捕获。
        check (bool): True 时命令返回非零会抛出 subprocess.CalledProcessError。
        cwd (str): 工作目录。
        echo (bool): True 时在执行前打印将要运行的命令。
        encoding (str): 解码子进程输出所用编码（如 'utf-8'、'gbk'）；为空时使用系统默认。
                        指定时以 errors='replace' 容错，避免非法字节导致 UnicodeDecodeError。

    Returns:
        subprocess.CompletedProcess: 执行结果。

    Raises:
        FileNotFoundError: 找不到可执行文件（通常是 conda 未安装或不在 PATH）。
        subprocess.CalledProcessError: check=True 且命令返回非零。
    """
    cmd = [str(c) for c in cmd]
    if echo:
        print(f"[conda] $ {_echo_cmd(cmd)}")

    creationflags = _no_window_flags(capture or tee)
    try:
        if tee:
            result = _run_tee(cmd, cwd=cwd, creationflags=creationflags, encoding=encoding)
        else:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                text=True,
                encoding=encoding,
                errors='replace' if encoding else None,
                capture_output=capture,
                creationflags=creationflags,
                # capture 模式下断开 stdin，避免子进程（如 conda 的错误上报、pip 等）
                # 在非交互场景下卡在输入提示上；默认实时模式则继承终端以支持交互。
                stdin=subprocess.DEVNULL if capture else None,
            )
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"无法执行 '{cmd[0]}'，请确认 conda 已正确安装并在 PATH 中。"
        ) from e

    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


class AsyncProcess:
    """
    异步执行的子进程句柄：进程在后台运行，可随时查询状态与已产生的输出。

    输出由两个后台线程分别从 stdout / stderr 持续读出，累积到带锁的缓冲区里。
    因此 :attr:`stdout` / :attr:`stderr` / :meth:`status` / :meth:`poll` 等查询都是
    非阻塞的——它们只读取已收集到的内容，绝不会等待进程结束，也不会因管道写满而死锁。

    Example:
        >>> p = env.run_async(['mineru', '-p', 'a.pdf', '-o', 'out'])
        >>> p.is_running          # 是否仍在运行
        True
        >>> p.status()            # 非阻塞地查询状态快照
        {'pid': 1234, 'running': True, 'returncode': None}
        >>> print(p.stdout)       # 非阻塞地查看当前已产生的输出
        ...
        >>> cp = p.result()       # 需要最终结果时再阻塞等待
        >>> cp.returncode
        0
    """

    def __init__(
            self,
            cmd: Sequence[str],
            cwd: Optional[str] = None,
            encoding: Optional[str] = None,
            tee: bool = False,
            creationflags: int = 0,
            ):
        """
        启动子进程并开始在后台泵取输出。

        Args:
            cmd (Sequence[str]): 命令及参数列表。
            cwd (str): 工作目录。
            encoding (str): 解码输出所用编码（如 'utf-8'、'gbk'）；为空时使用系统默认。
            tee (bool): True 时把输出实时转发到当前终端（同时仍会被捕获）。
            creationflags (int): 传给 subprocess 的 creationflags。

        Raises:
            FileNotFoundError: 找不到可执行文件（通常是 conda 未安装或不在 PATH）。
        """
        self.cmd: List[str] = [str(c) for c in cmd]
        self._tee = tee
        self._lock = threading.Lock()
        self._out: List[str] = []
        self._err: List[str] = []
        try:
            self._proc = subprocess.Popen(
                self.cmd,
                cwd=cwd,
                text=True,
                encoding=encoding,
                errors='replace' if encoding else None,
                bufsize=1,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
            )
        except FileNotFoundError as e:
            raise FileNotFoundError(
                f"无法执行 '{self.cmd[0]}'，请确认 conda 已正确安装并在 PATH 中。"
            ) from e
        self._t_out = threading.Thread(
            target=self._pump, args=(self._proc.stdout, sys.stdout, self._out), daemon=True)
        self._t_err = threading.Thread(
            target=self._pump, args=(self._proc.stderr, sys.stderr, self._err), daemon=True)
        self._t_out.start()
        self._t_err.start()

    def _pump(self, pipe, sink, buf: List[str]) -> None:
        """后台线程：逐行读取 pipe，累积到 buf（带锁），按需转发到 sink。"""
        try:
            for line in iter(pipe.readline, ''):
                if self._tee:
                    sink.write(line)
                    sink.flush()
                with self._lock:
                    buf.append(line)
        finally:
            pipe.close()

    @property
    def pid(self) -> int:
        """子进程 PID。"""
        return self._proc.pid

    @property
    def returncode(self) -> Optional[int]:
        """退出码；仍在运行时为 None（不会触发等待）。"""
        return self._proc.returncode

    @property
    def is_running(self) -> bool:
        """是否仍在运行（非阻塞）。"""
        return self._proc.poll() is None

    @property
    def stdout(self) -> str:
        """当前已收集到的 stdout（非阻塞，可在运行中反复读取）。"""
        with self._lock:
            return ''.join(self._out)

    @property
    def stderr(self) -> str:
        """当前已收集到的 stderr（非阻塞，可在运行中反复读取）。"""
        with self._lock:
            return ''.join(self._err)

    def poll(self) -> Optional[int]:
        """非阻塞地查询退出码：仍在运行返回 None，否则返回退出码。"""
        return self._proc.poll()

    def status(self) -> Dict:
        """
        非阻塞地返回状态快照。

        Returns:
            dict: `{'pid': int, 'running': bool, 'returncode': Optional[int]}`。
        """
        rc = self._proc.poll()
        return {'pid': self._proc.pid, 'running': rc is None, 'returncode': rc}

    def wait(self, timeout: Optional[float] = None) -> int:
        """
        阻塞等待进程结束。

        Args:
            timeout (float): 最长等待秒数，为空则一直等待。

        Returns:
            int: 退出码。

        Raises:
            subprocess.TimeoutExpired: 超时仍未结束。
        """
        rc = self._proc.wait(timeout=timeout)
        self._t_out.join()
        self._t_err.join()
        return rc

    def result(self, timeout: Optional[float] = None, check: bool = False) -> subprocess.CompletedProcess:
        """
        等待结束并返回完整结果。

        Args:
            timeout (float): 最长等待秒数，为空则一直等待。
            check (bool): True 且退出码非零时抛出 `subprocess.CalledProcessError`。

        Returns:
            subprocess.CompletedProcess: 含最终 stdout / stderr 的结果。

        Raises:
            subprocess.TimeoutExpired: 超时仍未结束。
            subprocess.CalledProcessError: check=True 且退出码非零。
        """
        self.wait(timeout=timeout)
        cp = subprocess.CompletedProcess(self.cmd, self._proc.returncode, self.stdout, self.stderr)
        if check and cp.returncode != 0:
            raise subprocess.CalledProcessError(
                cp.returncode, self.cmd, output=cp.stdout, stderr=cp.stderr)
        return cp

    def terminate(self) -> None:
        """请求终止进程（POSIX 上发送 SIGTERM）。"""
        self._proc.terminate()

    def kill(self) -> None:
        """强制杀死进程（POSIX 上发送 SIGKILL）。"""
        self._proc.kill()

    def __repr__(self) -> str:
        rc = self._proc.poll()
        state = 'running' if rc is None else f'exited({rc})'
        return f"AsyncProcess(pid={self._proc.pid}, {state})"


class Conda:
    """
    conda 管理器，负责环境层面的操作：列出、查询、创建、移除环境。

    Example:
        >>> import keon
        >>> conda = keon.conda.Conda()
        >>> conda.list_envs()
        ['base', 'py310']
        >>> env = conda.create('demo', python='3.10', packages=['numpy'])
        >>> conda.remove('demo')
    """

    def __init__(self, conda_exe: Optional[str] = None):
        """
        初始化 conda 管理器。

        Args:
            conda_exe (str): conda 可执行文件（如 'conda' / 'mamba' / 绝对路径），
                             为空时自动在 PATH 中查找。
        """
        self.conda_exe = _resolve_conda(conda_exe)

    def __repr__(self) -> str:
        return f"Conda(conda_exe={self.conda_exe!r})"

    def is_available(self) -> bool:
        """
        检测 conda 是否可用。

        Returns:
            bool: 能成功执行 `conda --version` 返回 True。
        """
        try:
            return _run([self.conda_exe, '--version'], capture=True, check=False).returncode == 0
        except FileNotFoundError:
            return False

    def info(self) -> Dict:
        """
        获取 `conda info --json` 的解析结果。

        Returns:
            dict: conda 的详细信息，包含 envs、root_prefix、conda_version 等。
        """
        result = _run([self.conda_exe, 'info', '--json'], capture=True, check=True)
        return json.loads(result.stdout)

    def version(self) -> str:
        """
        获取 conda 版本号。

        Returns:
            str: 版本号，如 '24.1.2'。
        """
        result = _run([self.conda_exe, '--version'], capture=True, check=True)
        out = result.stdout.strip()
        # 形如 'conda 24.1.2'
        return out.split()[-1] if out else out

    def env_paths(self) -> Dict[str, str]:
        """
        列出所有环境的「名称 -> 路径」映射。

        Returns:
            dict[str, str]: 环境名称到环境绝对路径的映射。
        """
        info = self.info()
        root = info.get('root_prefix')
        mapping: Dict[str, str] = {}
        for prefix in info.get('envs', []):
            name = _env_name_from_prefix(prefix, root)
            # 极少数重名（如自定义路径）时退化为完整路径作为键，避免互相覆盖
            if name in mapping and mapping[name] != prefix:
                mapping[prefix] = prefix
            else:
                mapping[name] = prefix
        return mapping

    def list_envs(self) -> List[str]:
        """
        列出所有 conda 环境名称。

        Returns:
            list[str]: 环境名称列表，base 环境名为 'base'。
        """
        return list(self.env_paths().keys())

    def exists(self, name: str) -> bool:
        """
        判断指定名称的环境是否存在。

        Args:
            name (str): 环境名称。

        Returns:
            bool: 存在返回 True。
        """
        return name in self.list_envs()

    def create(
            self,
            name: str,
            python: Optional[str] = None,
            packages: StrOrList = None,
            channels: StrOrList = None,
            yes: bool = True,
            verbose: bool = True,
            ) -> 'CondaEnv':
        """
        创建一个新的 conda 环境。

        Args:
            name (str): 环境名称。
            python (str): Python 版本，如 '3.10'，为空则不指定。
            packages: 创建时一并安装的包，字符串（空白分隔）或列表。
            channels: 额外的 channel，字符串或列表。
            yes (bool): 是否自动确认（附加 `-y`）。
            verbose (bool): 是否打印执行的命令。

        Returns:
            CondaEnv: 指向新环境的句柄。

        Raises:
            ValueError: 环境名称为空。
            subprocess.CalledProcessError: 创建失败。
        """
        if not name:
            raise ValueError("环境名称不能为空")

        cmd = [self.conda_exe, 'create', '-n', name]
        if python:
            cmd.append(f'python={python}')
        cmd += _as_list(packages)
        cmd += _channel_args(channels)
        if yes:
            cmd.append('-y')

        _run(cmd, capture=False, check=True, echo=verbose)
        return CondaEnv(name=name, conda_exe=self.conda_exe)

    def remove(self, name: str, yes: bool = True, verbose: bool = True) -> None:
        """
        移除一个 conda 环境。

        Args:
            name (str): 环境名称。
            yes (bool): 是否自动确认（附加 `-y`）。
            verbose (bool): 是否打印执行的命令。

        Raises:
            ValueError: 名称为空或试图移除 base 环境。
            subprocess.CalledProcessError: 移除失败。
        """
        if not name:
            raise ValueError("环境名称不能为空")
        if name == 'base':
            raise ValueError("拒绝移除 base 环境")

        cmd = [self.conda_exe, 'remove', '-n', name, '--all']
        if yes:
            cmd.append('-y')

        _run(cmd, capture=False, check=True, echo=verbose)

    def env(self, name: Optional[str] = None, prefix: Optional[str] = None) -> 'CondaEnv':
        """
        获取一个已存在环境的句柄（不校验是否真的存在）。

        Args:
            name (str): 环境名称，对应 `-n`。
            prefix (str): 环境路径，对应 `-p`。

        Returns:
            CondaEnv: 环境句柄。
        """
        return CondaEnv(name=name, prefix=prefix, conda_exe=self.conda_exe)

    def current(self, prefer_name: bool = True) -> 'CondaEnv':
        """
        获取当前 Python 解释器所在 conda 环境的句柄（适合在 Jupyter / 脚本里直接调用）。

        以 `sys.prefix`（当前解释器的环境根目录）为准，可靠且不受环境名是否已知影响。
        默认会尝试反查对应的环境名（如 'base'、'py310'），便于回显；查不到则退化为按
        路径定位。盘符大小写差异（`C:\\` 与 `c:\\`）已做归一化处理。

        Args:
            prefer_name (bool): True 时优先返回带环境名的句柄（需要调用 `conda info`），
                                False 或反查失败时按 `prefix` 定位。

        Returns:
            CondaEnv: 指向当前环境的句柄。
        """
        prefix = sys.prefix
        if prefer_name:
            try:
                for name, env_prefix in self.env_paths().items():
                    if _same_path(env_prefix, prefix):
                        return CondaEnv(name=name, conda_exe=self.conda_exe)
            except Exception:
                # 反查依赖 `conda info`，失败时不应阻塞：退化为按路径定位
                pass
        return CondaEnv(prefix=prefix, conda_exe=self.conda_exe)


class CondaEnv:
    """
    单个 conda 环境的句柄，支持在该环境内安装包、执行命令与脚本。

    Example:
        >>> import keon
        >>> env = keon.conda.CondaEnv('py310')
        >>> env.conda_install('numpy pandas', channels='conda-forge')
        >>> env.pip_install(['requests', 'rich'])
        >>> env.run('python --version')
        >>> env.run_script('main.py', args=['--debug'])
    """

    def __init__(
            self,
            name: Optional[str] = None,
            prefix: Optional[str] = None,
            conda_exe: Optional[str] = None,
            ):
        """
        初始化环境句柄。

        Args:
            name (str): 环境名称，对应 `-n`。
            prefix (str): 环境路径，对应 `-p`，优先级高于 name。
            conda_exe (str): conda 可执行文件，为空时自动查找。

        Raises:
            ValueError: name 与 prefix 均为空。
        """
        if not name and not prefix:
            raise ValueError("必须指定 name 或 prefix 之一")
        self.name = name
        self.prefix = prefix
        self.conda_exe = _resolve_conda(conda_exe)

    def __repr__(self) -> str:
        target = f"name={self.name!r}" if self.name else f"prefix={self.prefix!r}"
        return f"CondaEnv({target})"

    @property
    def target_args(self) -> List[str]:
        """定位本环境的参数（`-n name` 或 `-p prefix`）。"""
        return _target_args(self.name, self.prefix)

    def conda_install(
            self,
            packages: StrOrList,
            channels: StrOrList = None,
            yes: bool = True,
            capture: bool = False,
            tee: bool = False,
            check: bool = True,
            verbose: bool = True,
            encoding: Optional[str] = None,
            ) -> subprocess.CompletedProcess:
        """
        使用 conda 在本环境安装包。

        Args:
            packages: 要安装的包，字符串（空白分隔）或列表，如 'numpy pandas' 或 ['numpy', 'pandas']。
            channels: 额外的 channel，字符串或列表。
            yes (bool): 是否自动确认（附加 `-y`）。
            capture (bool): 仅捕获输出（不在终端实时显示）。
            tee (bool): 实时打印并同时捕获输出（耗时安装推荐）。
            check (bool): 失败时是否抛出异常。
            verbose (bool): 是否打印执行的命令。
            encoding (str): 解码子进程输出所用编码（如 'utf-8'、'gbk'）；为空时使用系统默认。

        Returns:
            subprocess.CompletedProcess: 执行结果。

        Raises:
            ValueError: 未指定任何包。
        """
        pkgs = _as_list(packages)
        if not pkgs:
            raise ValueError("未指定要安装的包")

        cmd = [self.conda_exe, 'install', *self.target_args, *pkgs, *_channel_args(channels)]
        if yes:
            cmd.append('-y')
        return _run(cmd, capture=capture, tee=tee, check=check, echo=verbose, encoding=encoding)

    def pip_install(
            self,
            packages: StrOrList,
            upgrade: bool = False,
            extra_args: StrOrList = None,
            capture: bool = False,
            tee: bool = False,
            check: bool = True,
            verbose: bool = True,
            encoding: Optional[str] = None,
            ) -> subprocess.CompletedProcess:
        """
        使用本环境内的 pip 安装包（通过 `conda run` 调用对应环境的 pip）。

        Args:
            packages: 要安装的包，字符串（空白分隔）或列表。
            upgrade (bool): 是否附加 `--upgrade`。
            extra_args: 传给 pip 的额外参数，字符串或列表，如 '--no-deps' 或 ['-i', '<url>']。
            capture (bool): 仅捕获输出（不在终端实时显示）。
            tee (bool): 实时打印并同时捕获输出（耗时安装推荐）。
            check (bool): 失败时是否抛出异常。
            verbose (bool): 是否打印执行的命令。
            encoding (str): 解码子进程输出所用编码（如 'utf-8'、'gbk'）；为空时使用系统默认。

        Returns:
            subprocess.CompletedProcess: 执行结果。

        Raises:
            ValueError: 未指定任何包。
        """
        pkgs = _as_list(packages)
        if not pkgs:
            raise ValueError("未指定要安装的包")

        pip_cmd = ['pip', 'install']
        if upgrade:
            pip_cmd.append('--upgrade')
        pip_cmd += pkgs
        pip_cmd += _as_list(extra_args)
        return self.run(pip_cmd, capture=capture, tee=tee, check=check, verbose=verbose, encoding=encoding)

    def install(self, packages: StrOrList, manager: str = 'conda', **kwargs) -> subprocess.CompletedProcess:
        """
        安装包，并根据 `manager` 参数选择 conda 或 pip。

        Args:
            packages: 要安装的包，字符串（空白分隔）或列表。
            manager (str): 包管理器，'conda' 或 'pip'。
            **kwargs: 透传给 :meth:`conda_install` 或 :meth:`pip_install` 的参数。

        Returns:
            subprocess.CompletedProcess: 执行结果。

        Raises:
            ValueError: manager 不是 'conda' 或 'pip'。
        """
        manager = (manager or '').lower()
        if manager == 'conda':
            return self.conda_install(packages, **kwargs)
        if manager == 'pip':
            return self.pip_install(packages, **kwargs)
        raise ValueError(f"不支持的包管理器: {manager!r}，可选 'conda' 或 'pip'")

    def run(
            self,
            command: Union[str, Sequence[str]],
            capture: bool = False,
            tee: bool = False,
            check: bool = True,
            cwd: Optional[str] = None,
            verbose: bool = True,
            encoding: Optional[str] = None,
            ) -> subprocess.CompletedProcess:
        """
        在本环境内执行任意命令（通过 `conda run`）。

        输出模式：
            - 默认：实时输出到终端，stdout/stderr 为 None。
            - capture=True：仅捕获，结果带 stdout/stderr，不在终端实时显示。
            - tee=True：实时输出并同时捕获到返回值（耗时命令推荐，优先级高于 capture）。

        capture / tee 模式下子进程不再占用当前终端，可避免被子进程清屏。

        Args:
            command: 命令字符串或参数列表，如 'python --version' 或 ['python', '--version']。
                     含空格或引号时建议传列表。
            capture (bool): 仅捕获输出。
            tee (bool): 实时输出并同时捕获。
            check (bool): 失败时是否抛出异常。
            cwd (str): 工作目录。
            verbose (bool): 是否打印执行的命令。
            encoding (str): 解码子进程输出所用编码（如 'utf-8'、'gbk'）；为空时使用系统默认。

        Returns:
            subprocess.CompletedProcess: 执行结果。

        Raises:
            ValueError: 命令为空。
        """
        cmd = self._build_run_cmd(command, no_capture=(tee or not capture))
        return _run(cmd, capture=capture, tee=tee, check=check, cwd=cwd, echo=verbose, encoding=encoding)

    def _build_run_cmd(self, command: Union[str, Sequence[str]], no_capture: bool) -> List[str]:
        """
        校验命令并拼出 `conda run` 完整参数列表。

        Args:
            command: 命令字符串或参数列表。
            no_capture (bool): 是否附加 `--no-capture-output`（让子进程输出实时直达管道/终端，
                               而非被 conda 缓冲到结束才吐出）。

        Returns:
            list[str]: `[conda, 'run', -n/-p, ('--no-capture-output'), *args]`。

        Raises:
            ValueError: 命令为空，或参数含换行（conda run 不支持）。
        """
        args = _split_command(command)
        if not args:
            raise ValueError("命令不能为空")
        # conda run 不支持参数中含换行（见 conda.utils.wrap_subprocess_call 的断言），
        # 否则会直接崩溃。提前拦截并给出可操作的提示。
        if any('\n' in a or '\r' in a for a in args):
            raise ValueError(
                "conda run 不支持参数中包含换行符（例如多行的 `python -c` 代码）。"
                "请改用 env.run_code(代码字符串)（自动写入临时文件），"
                "或把代码保存为 .py 文件后用 env.run_script(文件路径)。"
            )
        cmd = [self.conda_exe, 'run', *self.target_args]
        if no_capture:
            cmd.append('--no-capture-output')
        cmd += args
        return cmd

    def create_cmd(self, command: Union[str, Sequence[str]], capture: bool = True) -> str:
        """
        生成可在 PowerShell 中执行的 conda run 命令字符串。

        Args:
            command: 命令字符串或参数列表，如 'python --version' 或 ['python', '--version']。
            capture (bool): 是否捕获输出（False 时附加 `--no-capture-output` 实时输出）。

        Returns:
            str: 完整的命令字符串，可直接复制到 PowerShell 执行。

        Raises:
            ValueError: 命令为空或参数含换行。

        Example:
            >>> env = CondaEnv('myenv')
            >>> cmd = env.create_cmd('python script.py')
            >>> print(cmd)
            conda run -n myenv python script.py
            >>> cmd = env.create_cmd('python script.py', capture=False)
            >>> print(cmd)
            conda run -n myenv --no-capture-output python script.py
            >>> cmd = env.create_cmd(['mineru', '-p', 'C:\\Users\\a b\\file.pdf'], capture=False)
            >>> print(cmd)
            conda run -n myenv --no-capture-output mineru -p "C:\\Users\\a b\\file.pdf"
        """
        cmd_list = self._build_run_cmd(command, no_capture=not capture)
        
        # PowerShell 转义规则：含空格或特殊字符的参数需要用双引号包裹
        def quote_if_needed(arg: str) -> str:
            # 如果参数包含空格、引号或其他特殊字符，则用双引号包裹
            if ' ' in arg or '"' in arg or "'" in arg or any(c in arg for c in ['&', '|', '<', '>', '^', '(', ')']):
                # 转义内部的双引号和反斜杠
                escaped = arg.replace('\\', '\\\\').replace('"', '`"')
                return f'"{escaped}"'
            return arg
        
        return ' '.join(quote_if_needed(arg) for arg in cmd_list)

    def run_async(
            self,
            command: Union[str, Sequence[str]],
            tee: bool = False,
            cwd: Optional[str] = None,
            verbose: bool = True,
            encoding: Optional[str] = None,
            ) -> AsyncProcess:
        """
        在本环境内异步执行命令（通过 `conda run`），立即返回句柄，进程在后台运行。

        典型用于耗时任务（如 `mineru` 转换）：启动后可随时通过返回的 :class:`AsyncProcess`
        查询状态与已产生的输出，且查询不会阻塞、不会死锁。

        Example:
            >>> p = env.run_async(['mineru', '-p', file, '-o', folder])
            >>> while p.is_running:
            ...     print(p.stdout[-200:])   # 非阻塞查看最新输出
            ...     time.sleep(1)
            >>> cp = p.result()              # 拿最终结果

        Args:
            command: 命令字符串或参数列表，如 ['mineru', '-p', file, '-o', folder]。
                     含空格的路径建议直接传列表以避免引号歧义。
            tee (bool): True 时同时把输出实时转发到当前终端（输出始终会被捕获）。
            cwd (str): 工作目录。
            verbose (bool): 是否在启动前打印将要执行的命令。
            encoding (str): 解码输出所用编码（如 'utf-8'、'gbk'）；为空时使用系统默认。

        Returns:
            AsyncProcess: 异步进程句柄。

        Raises:
            ValueError: 命令为空，或参数含换行（conda run 不支持）。
        """
        # 异步模式始终用管道接管输出（写入后台缓冲区），故总是加 --no-capture-output 以保证实时性。
        cmd = self._build_run_cmd(command, no_capture=True)
        if verbose:
            print(f"[conda] $ {_echo_cmd(cmd)}")
        return AsyncProcess(
            cmd,
            cwd=cwd,
            encoding=encoding,
            tee=tee,
            creationflags=_no_window_flags(True),
        )

    def run_script(
            self,
            script: str,
            args: StrOrList = None,
            interpreter: str = 'python',
            capture: bool = False,
            tee: bool = False,
            check: bool = True,
            cwd: Optional[str] = None,
            verbose: bool = True,
            encoding: Optional[str] = None,
            ) -> subprocess.CompletedProcess:
        """
        在本环境内执行脚本。

        Args:
            script (str): 脚本路径。
            args: 传给脚本的参数，字符串或列表。
            interpreter (str): 解释器，默认 'python'，也可为 'bash' 等。
            capture (bool): 仅捕获输出。
            tee (bool): 实时输出并同时捕获（耗时脚本推荐）。
            check (bool): 失败时是否抛出异常。
            cwd (str): 工作目录。
            verbose (bool): 是否打印执行的命令。
            encoding (str): 解码子进程输出所用编码（如 'utf-8'、'gbk'）；为空时使用系统默认。

        Returns:
            subprocess.CompletedProcess: 执行结果。
        """
        cmd = [interpreter, str(script), *_as_list(args)]
        return self.run(cmd, capture=capture, tee=tee, check=check, cwd=cwd, verbose=verbose, encoding=encoding)

    def python(
            self,
            args: StrOrList = None,
            capture: bool = False,
            tee: bool = False,
            check: bool = True,
            cwd: Optional[str] = None,
            verbose: bool = True,
            encoding: Optional[str] = None,
            ) -> subprocess.CompletedProcess:
        """
        在本环境内执行 python（便捷封装），如 `python(['-c', 'print(1)'])`。

        注意：`conda run` 不支持含换行的参数，多行代码请改用 :meth:`run_code`。

        Args:
            args: 传给 python 的参数，字符串或列表。
            capture (bool): 仅捕获输出。
            tee (bool): 实时输出并同时捕获。
            check (bool): 失败时是否抛出异常。
            cwd (str): 工作目录。
            verbose (bool): 是否打印执行的命令。
            encoding (str): 解码子进程输出所用编码（如 'utf-8'、'gbk'）；为空时使用系统默认。

        Returns:
            subprocess.CompletedProcess: 执行结果。
        """
        cmd = ['python', *_as_list(args)]
        return self.run(cmd, capture=capture, tee=tee, check=check, cwd=cwd, verbose=verbose, encoding=encoding)

    def run_code(
            self,
            code: str,
            args: StrOrList = None,
            unbuffered: bool = True,
            capture: bool = False,
            tee: bool = False,
            check: bool = True,
            cwd: Optional[str] = None,
            verbose: bool = True,
            encoding: Optional[str] = None,
            ) -> subprocess.CompletedProcess:
        """
        在本环境内执行一段 Python 代码（可多行）。

        会先把代码写入临时 `.py` 文件再执行，以规避 `conda run` 不支持「参数含换行」
        的限制（多行代码用 `python -c` 会直接报错）。

        Args:
            code (str): Python 源码，允许多行。
            args: 传给脚本的命令行参数（即 `sys.argv[1:]`），字符串或列表。
            unbuffered (bool): 是否以 `python -u` 无缓冲运行（tee 实时输出时推荐 True）。
            capture (bool): 仅捕获输出。
            tee (bool): 实时输出并同时捕获。
            check (bool): 失败时是否抛出异常。
            cwd (str): 工作目录。
            verbose (bool): 是否打印执行的命令。
            encoding (str): 解码子进程输出所用编码（如 'utf-8'、'gbk'）；为空时使用系统默认。

        Returns:
            subprocess.CompletedProcess: 执行结果。
        """
        fd, path = tempfile.mkstemp(suffix='.py', text=True)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(code)
            cmd = ['python']
            if unbuffered:
                cmd.append('-u')
            cmd.append(path)
            cmd += _as_list(args)
            return self.run(cmd, capture=capture, tee=tee, check=check, cwd=cwd, verbose=verbose, encoding=encoding)
        finally:
            os.remove(path)

    def list_packages(self) -> List[Dict]:
        """
        列出本环境已安装的包。

        Returns:
            list[dict]: 每个包的信息（name、version、channel 等）。
        """
        cmd = [self.conda_exe, 'list', *self.target_args, '--json']
        result = _run(cmd, capture=True, check=True)
        return json.loads(result.stdout)
