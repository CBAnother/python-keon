import os
import sys
import subprocess
from types import SimpleNamespace

import pytest

import keon.conda as kc
from keon.conda import Conda, CondaEnv


# ── 测试辅助函数 ────────────────────────────────────────────────────────────────

def test_resolve_conda_explicit():
    """显式指定时原样返回"""
    assert kc._resolve_conda('mamba') == 'mamba'
    assert kc._resolve_conda(r'C:\tools\conda.exe') == r'C:\tools\conda.exe'


def test_prefer_exe_over_bat(tmp_path):
    """Windows 上 .bat 优先替换为同体系的 conda.exe"""
    (tmp_path / 'condabin').mkdir()
    (tmp_path / 'Scripts').mkdir()
    bat = tmp_path / 'condabin' / 'conda.bat'
    exe = tmp_path / 'Scripts' / 'conda.exe'
    bat.write_text('')
    exe.write_text('')
    assert kc._prefer_exe_over_bat(str(bat), is_windows=True) == str(exe)


def test_prefer_exe_over_bat_keeps_exe(tmp_path):
    """本身就是 .exe 时原样返回"""
    exe = tmp_path / 'conda.exe'
    exe.write_text('')
    assert kc._prefer_exe_over_bat(str(exe), is_windows=True) == str(exe)


def test_prefer_exe_over_bat_non_windows(tmp_path):
    """非 Windows 不改动"""
    bat = tmp_path / 'conda.bat'
    bat.write_text('')
    assert kc._prefer_exe_over_bat(str(bat), is_windows=False) == str(bat)


def test_echo_cmd_collapses_multiline_arg():
    """含换行的参数回显为单行并加引号"""
    out = kc._echo_cmd(['conda', 'run', 'python', '-c', 'import time\nprint(1)'])
    assert '\n' not in out
    assert '"import time\\nprint(1)"' in out
    # 普通参数不加引号
    assert out.startswith('conda run python -c ')


def test_as_list_none():
    assert kc._as_list(None) == []


def test_as_list_string_splits_on_whitespace():
    assert kc._as_list('numpy pandas') == ['numpy', 'pandas']
    assert kc._as_list('numpy') == ['numpy']


def test_as_list_sequence():
    assert kc._as_list(['numpy', 'pandas']) == ['numpy', 'pandas']
    assert kc._as_list(('a', 'b')) == ['a', 'b']


def test_split_command_list_kept_as_is():
    assert kc._split_command(['python', '-c', 'print(1)']) == ['python', '-c', 'print(1)']


def test_split_command_string():
    assert kc._split_command('python --version') == ['python', '--version']


def test_split_command_windows_quoted_path_with_backslashes(monkeypatch):
    """Windows：带空格且用引号包裹的路径不应把引号当作参数内容。"""
    monkeypatch.setattr(os, 'name', 'nt')
    cmd = r'mineru -p "C:\Users\a b\file.pdf" -o "C:\Users\a b\out"'
    assert kc._split_command(cmd) == [
        'mineru', '-p', r'C:\Users\a b\file.pdf', '-o', r'C:\Users\a b\out',
    ]


def test_split_command_windows_unquoted_backslash_path(monkeypatch):
    """Windows：未加引号的路径仍保留反斜杠。"""
    monkeypatch.setattr(os, 'name', 'nt')
    assert kc._split_command(r'python C:\foo\bar.py') == ['python', r'C:\foo\bar.py']


def test_channel_args():
    assert kc._channel_args(None) == []
    assert kc._channel_args('conda-forge') == ['-c', 'conda-forge']
    assert kc._channel_args(['conda-forge', 'defaults']) == ['-c', 'conda-forge', '-c', 'defaults']


def test_target_args_by_name():
    assert kc._target_args('py310', None) == ['-n', 'py310']


def test_target_args_by_prefix_takes_priority():
    assert kc._target_args('py310', '/opt/envs/foo') == ['-p', '/opt/envs/foo']


def test_target_args_requires_one():
    with pytest.raises(ValueError, match='name 或 prefix'):
        kc._target_args(None, None)


def test_env_name_from_prefix_base():
    assert kc._env_name_from_prefix('/home/u/miniconda3', '/home/u/miniconda3') == 'base'


def test_env_name_from_prefix_named():
    assert kc._env_name_from_prefix('/home/u/miniconda3/envs/py310', '/home/u/miniconda3') == 'py310'


# ── 测试夹具：拦截 _run ──────────────────────────────────────────────────────────

@pytest.fixture
def rec(monkeypatch):
    """拦截 keon.conda._run，记录命令而不真正执行 conda。"""
    calls = []

    def fake_run(cmd, capture=False, tee=False, check=True, cwd=None, echo=False, encoding=None):
        calls.append(SimpleNamespace(cmd=list(cmd), capture=capture, tee=tee, check=check, cwd=cwd, echo=echo, encoding=encoding))
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(kc, '_run', fake_run)
    return calls


# ── 测试 CondaEnv 初始化 ────────────────────────────────────────────────────────

def test_env_requires_name_or_prefix():
    with pytest.raises(ValueError, match='name 或 prefix'):
        CondaEnv()


def test_env_repr():
    assert repr(CondaEnv(name='py310', conda_exe='conda')) == "CondaEnv(name='py310')"
    assert repr(CondaEnv(prefix='/p', conda_exe='conda')) == "CondaEnv(prefix='/p')"


def test_env_target_args_prefix():
    env = CondaEnv(prefix='/opt/envs/foo', conda_exe='conda')
    assert env.target_args == ['-p', '/opt/envs/foo']


# ── 测试 conda install ─────────────────────────────────────────────────────────

def test_conda_install_builds_command(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    env.conda_install('numpy pandas', channels='conda-forge')
    assert rec[-1].cmd == ['conda', 'install', '-n', 'py310', 'numpy', 'pandas', '-c', 'conda-forge', '-y']


def test_conda_install_without_yes(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    env.conda_install(['numpy'], yes=False)
    assert rec[-1].cmd == ['conda', 'install', '-n', 'py310', 'numpy']


def test_conda_install_empty_packages_raises(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    with pytest.raises(ValueError, match='未指定要安装的包'):
        env.conda_install('')


# ── 测试 pip install ───────────────────────────────────────────────────────────

def test_pip_install_builds_command(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    env.pip_install('requests', upgrade=True)
    assert rec[-1].cmd == [
        'conda', 'run', '-n', 'py310', '--no-capture-output',
        'pip', 'install', '--upgrade', 'requests',
    ]


def test_pip_install_extra_args(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    env.pip_install(['rich'], extra_args='--no-deps')
    assert rec[-1].cmd == [
        'conda', 'run', '-n', 'py310', '--no-capture-output',
        'pip', 'install', 'rich', '--no-deps',
    ]


# ── 测试 install 按参数选择 ─────────────────────────────────────────────────────

def test_install_dispatch_conda(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    env.install('numpy', manager='conda')
    assert rec[-1].cmd[:2] == ['conda', 'install']


def test_install_dispatch_pip(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    env.install('numpy', manager='pip')
    assert rec[-1].cmd[:2] == ['conda', 'run']
    assert rec[-1].cmd[-3:] == ['pip', 'install', 'numpy']


def test_install_invalid_manager(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    with pytest.raises(ValueError, match='不支持的包管理器'):
        env.install('numpy', manager='poetry')


# ── 测试 run / run_script ──────────────────────────────────────────────────────

def test_run_adds_no_capture_when_streaming(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    env.run(['python', '--version'])
    assert rec[-1].cmd == ['conda', 'run', '-n', 'py310', '--no-capture-output', 'python', '--version']


def test_run_omits_no_capture_when_capturing(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    env.run(['python', '--version'], capture=True)
    assert '--no-capture-output' not in rec[-1].cmd
    assert rec[-1].cmd == ['conda', 'run', '-n', 'py310', 'python', '--version']
    assert rec[-1].capture is True


def test_run_tee_adds_no_capture_for_realtime(rec):
    """tee 需要 --no-capture-output 让子进程直接写管道，才能实时转发"""
    env = CondaEnv(name='py310', conda_exe='conda')
    env.run(['python', '--version'], tee=True)
    assert rec[-1].cmd == ['conda', 'run', '-n', 'py310', '--no-capture-output', 'python', '--version']
    assert rec[-1].tee is True


def test_run_empty_command_raises(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    with pytest.raises(ValueError, match='命令不能为空'):
        env.run('')


def test_run_script_builds_command(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    env.run_script('main.py', args=['--debug'])
    assert rec[-1].cmd == [
        'conda', 'run', '-n', 'py310', '--no-capture-output',
        'python', 'main.py', '--debug',
    ]


def test_create_cmd_simple():
    """测试生成简单命令字符串（默认 capture=True，不添加 --no-capture-output）"""
    env = CondaEnv(name='py310', conda_exe='conda')
    cmd = env.create_cmd('python --version')
    assert cmd == 'conda run -n py310 python --version'


def test_create_cmd_with_space_in_path():
    """测试带空格的路径会被正确引号包裹"""
    env = CondaEnv(name='py310', conda_exe='conda')
    cmd = env.create_cmd(['mineru', '-p', r'C:\Users\a b\file.pdf', '-o', r'C:\Users\a b\out'], capture=False)
    assert 'mineru -p' in cmd
    assert r'"C:\\Users\\a b\\file.pdf"' in cmd
    assert r'"C:\\Users\\a b\\out"' in cmd
    assert '--no-capture-output' in cmd


def test_create_cmd_capture_false():
    """测试 capture=False 时添加 --no-capture-output"""
    env = CondaEnv(prefix='/opt/envs/foo', conda_exe='conda')
    cmd = env.create_cmd('python script.py', capture=False)
    assert '--no-capture-output' in cmd
    assert cmd == 'conda run -p /opt/envs/foo --no-capture-output python script.py'


def test_create_cmd_list_input():
    """测试列表输入"""
    env = CondaEnv(name='test', conda_exe='mamba')
    cmd = env.create_cmd(['pip', 'install', 'numpy'])
    assert cmd == 'mamba run -n test pip install numpy'


def test_python_helper(rec):
    env = CondaEnv(name='py310', conda_exe='conda')
    env.python(['-c', 'print(1)'])
    assert rec[-1].cmd == [
        'conda', 'run', '-n', 'py310', '--no-capture-output',
        'python', '-c', 'print(1)',
    ]


def test_run_rejects_newline_arg(rec):
    """conda run 不支持换行参数，应提前拦截而不是让 conda 崩溃"""
    env = CondaEnv(name='py310', conda_exe='conda')
    with pytest.raises(ValueError, match='换行'):
        env.run(['python', '-c', 'import time\nprint(1)'])


def test_run_code_writes_temp_file_and_runs(rec):
    """run_code 把多行代码写入临时 .py 再执行（不含换行参数）"""
    env = CondaEnv(name='py310', conda_exe='conda')
    env.run_code("import time\nprint(1)", tee=True)
    cmd = rec[-1].cmd
    assert cmd[:5] == ['conda', 'run', '-n', 'py310', '--no-capture-output']
    assert cmd[5] == 'python'
    assert cmd[6] == '-u'
    assert cmd[7].endswith('.py')
    # 真正执行的参数里不应再有换行
    assert all('\n' not in part for part in cmd)
    assert rec[-1].tee is True


def test_run_code_cleans_up_temp_file(rec):
    """run_code 执行后应删除临时文件"""
    env = CondaEnv(name='py310', conda_exe='conda')
    env.run_code("print(1)")
    temp_path = rec[-1].cmd[-1]
    assert temp_path.endswith('.py')
    assert not os.path.exists(temp_path)


# ── 测试 Conda 管理器 ──────────────────────────────────────────────────────────

def test_create_builds_command_and_returns_env(rec):
    conda = Conda(conda_exe='conda')
    env = conda.create('demo', python='3.10', packages=['numpy'], channels='conda-forge')
    assert rec[-1].cmd == ['conda', 'create', '-n', 'demo', 'python=3.10', 'numpy', '-c', 'conda-forge', '-y']
    assert isinstance(env, CondaEnv)
    assert env.name == 'demo'


def test_create_empty_name_raises(rec):
    conda = Conda(conda_exe='conda')
    with pytest.raises(ValueError, match='环境名称不能为空'):
        conda.create('')


def test_remove_builds_command(rec):
    conda = Conda(conda_exe='conda')
    conda.remove('demo')
    assert rec[-1].cmd == ['conda', 'remove', '-n', 'demo', '--all', '-y']


def test_remove_base_refused(rec):
    conda = Conda(conda_exe='conda')
    with pytest.raises(ValueError, match='base'):
        conda.remove('base')


def test_list_envs_parses_info(monkeypatch):
    conda = Conda(conda_exe='conda')
    info = {
        'root_prefix': '/home/u/miniconda3',
        'envs': ['/home/u/miniconda3', '/home/u/miniconda3/envs/py310'],
    }
    monkeypatch.setattr(conda, 'info', lambda: info)
    assert conda.list_envs() == ['base', 'py310']
    assert conda.exists('py310') is True
    assert conda.exists('nope') is False


# ── 测试 _run 错误处理 ─────────────────────────────────────────────────────────

def test_run_missing_executable(monkeypatch):
    """可执行文件不存在时给出友好错误"""
    def boom(*args, **kwargs):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, 'run', boom)
    with pytest.raises(FileNotFoundError, match='conda'):
        kc._run(['conda', '--version'])


def test_run_check_raises_on_nonzero(monkeypatch):
    monkeypatch.setattr(
        subprocess, 'run',
        lambda *a, **k: SimpleNamespace(returncode=1, stdout='', stderr='boom'),
    )
    with pytest.raises(subprocess.CalledProcessError):
        kc._run(['conda', 'install', 'x'], check=True)


def test_run_capture_closes_stdin(monkeypatch):
    """capture 模式断开 stdin，避免子进程卡在输入提示上"""
    captured = {}

    def fake(*a, **k):
        captured.update(k)
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(subprocess, 'run', fake)
    kc._run(['conda', '--version'], capture=True)
    assert captured.get('stdin') == subprocess.DEVNULL


def test_run_live_inherits_stdin(monkeypatch):
    """默认实时模式继承 stdin，保留交互能力"""
    captured = {}

    def fake(*a, **k):
        captured.update(k)
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    monkeypatch.setattr(subprocess, 'run', fake)
    kc._run(['conda', '--version'], capture=False)
    assert captured.get('stdin') is None


# ── 测试 tee / 控制台隔离 ──────────────────────────────────────────────────────

def test_no_window_flags_non_pipe_is_zero():
    assert kc._no_window_flags(False) == 0


def test_no_window_flags_pipe():
    flags = kc._no_window_flags(True)
    if os.name == 'nt':
        assert flags == subprocess.CREATE_NO_WINDOW
    else:
        assert flags == 0


def test_run_tee_streams_and_captures(capsys):
    """tee 模式：返回值带 stdout，同时实时输出到终端"""
    result = kc._run([sys.executable, '-c', "print('hello-tee')"], tee=True, check=True)
    assert result.returncode == 0
    assert 'hello-tee' in result.stdout

    captured = capsys.readouterr()
    assert 'hello-tee' in captured.out
