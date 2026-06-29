import os
import fnmatch
import logging
import time
import pyperclip

log = logging.getLogger(__name__)


def __is_ignore_ptn(ignore_ptns, entry):
    if ignore_ptns:
        for ptn in ignore_ptns:
            if fnmatch.fnmatch(entry, ptn):
                return True
    return False


def list_dir_tree(
        path, 
        prefix="", 
        root_full_path=False, 
        ignore_ptns=None,
        recursive=False,
        dir_style=None,
        dirs_first=True,
        ):
    """
    生成目录树

    Args:
        path (str): 目录路径
        prefix (str): 前缀字符串，用于缩进
        root_full_path (bool): 是否在根目录时显示完整路径
        ignore_ptns (list): 忽略的文件或目录模式列表
        recursive (bool): 是否递归子目录
        dir_style (str): 文件夹显示样式，None 或 'plain' 表示无修饰（xxx），
                         'backslash' 表示反斜杠结尾（xxx\\），
                         'bracket' 表示方括号包含（[xxx]）
        dirs_first (bool): True 表示文件夹排在文件前面，False 表示文件排在文件夹前面，默认为 True

    Returns:
        list[str]: 目录树的字符串列表
    """
    res = []
    if prefix == "": 
        if root_full_path:
            res.append(path)
        else:
            res.append(os.path.basename(path))

    all_entries = os.listdir(path)
    all_entries.sort()
    all_entries = [e for e in all_entries if not __is_ignore_ptn(ignore_ptns, e)]

    if dirs_first:
        entries = [e for e in all_entries if os.path.isdir(os.path.join(path, e))] + \
                  [e for e in all_entries if not os.path.isdir(os.path.join(path, e))]
    else:
        entries = [e for e in all_entries if not os.path.isdir(os.path.join(path, e))] + \
                  [e for e in all_entries if os.path.isdir(os.path.join(path, e))]

    for index, entry in enumerate(entries):
        full_path = os.path.join(path, entry)
        is_dir = os.path.isdir(full_path)

        is_last = index == len(entries) - 1
        symbol = "└── " if is_last else "├── "
        
        line = f"{prefix}{symbol}"
        if is_dir:
            if dir_style == 'backslash':
                line += f"{entry}\\"
            elif dir_style == 'bracket':
                line += f"[{entry}]"
            else:
                line += entry
        else:
            line += entry
        res.append(line)

        if not recursive and is_dir:
            continue

        # subdirectory
        if is_dir:
            # print(f'find sub dir: {full_path}')
            new_prefix = prefix + ("    " if is_last else "│   ")
            res.extend(list_dir_tree(full_path, new_prefix, ignore_ptns=ignore_ptns, recursive=recursive, dir_style=dir_style, dirs_first=dirs_first))
        else:
            # print(f'find file: {full_path}')
            pass

    return res


def print_dir_tree(
    path, 
    root_full_path=False, 
    ignore_ptns=None,
    copy_to_clipboard=False,
    recursive=False,
    dir_style='bracket',
    dirs_first=True,
    ):
    """
    打印目录树

    Args:
        path (str): 目录路径
        root_full_path (bool): 是否在根目录时显示完整路径
        ignore_ptns (list): 忽略的文件或目录模式列表
        copy_to_clipboard (bool): 是否将结果复制到剪贴板
        recursive (bool): 是否递归子目录
        dir_style (str): 文件夹显示样式，None 或 'plain' 表示无修饰（xxx），
                         'backslash' 表示反斜杠结尾（xxx\\），
                         'bracket' 表示方括号包含（[xxx]），默认为 'bracket'
        dirs_first (bool): True 表示文件夹排在文件前面，False 表示文件排在文件夹前面，默认为 True
    """
    lines = list_dir_tree(path=path, root_full_path=root_full_path, ignore_ptns=ignore_ptns, recursive=recursive, dir_style=dir_style, dirs_first=dirs_first)
    text = '\n'.join(lines)
    if copy_to_clipboard:
        pyperclip.copy(text)
    
    print(text)


def rel_path(path, start=None, as_posix=False):
    """
    生成相对路径

    Args:
        path (str): 路径
        start (str): 起始路径
        as_posix (bool): 是否返回 POSIX 风格的路径
    """
    res = os.path.relpath(path, start)
    if as_posix:
        res = res.replace('\\', '/')
    return res


# Windows 注册表中存放环境变量的位置
_ENV_REG_LOCATIONS = {
    # 当前用户级别
    'user': ('HKEY_CURRENT_USER', r'Environment'),
    # 系统级别
    'system': ('HKEY_LOCAL_MACHINE',
               r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
}


def list_env_vars(scope='user', expand=False):
    """
    列出环境变量，支持 USER 级别和 SYSTEM 级别（Windows）。

    与 os.environ 不同，本函数直接读取 Windows 注册表，因此能区分
    用户级别和系统级别，且能拿到当前进程启动后被新增/修改的值。

    Args:
        scope (str): 环境变量级别。
            'user'    -> 当前用户 (HKEY_CURRENT_USER\\Environment)
            'system'  -> 系统     (HKEY_LOCAL_MACHINE\\...\\Session Manager\\Environment)
            'process' -> 当前进程已生效的环境变量 (os.environ)
        expand (bool): 是否展开形如 %USERPROFILE% 的变量引用，默认 False。

    Returns:
        dict: 环境变量名到值的字典（按读取顺序）。
    """
    scope = (scope or '').lower()

    # 进程级别直接返回 os.environ 的副本
    if scope in ('process', 'proc', 'p'):
        items = os.environ.items()
        if expand:
            return {name: os.path.expandvars(value) for name, value in items}
        return dict(items)

    alias = {'u': 'user', 'machine': 'system', 's': 'system'}
    scope = alias.get(scope, scope)
    if scope not in _ENV_REG_LOCATIONS:
        raise ValueError(f"不支持的 scope: {scope!r}，应为 'user' / 'system' / 'process'")

    import winreg

    root_name, sub_key = _ENV_REG_LOCATIONS[scope]
    root = getattr(winreg, root_name)

    result = {}
    with winreg.OpenKey(root, sub_key) as key:
        value_count = winreg.QueryInfoKey(key)[1]
        for i in range(value_count):
            name, value, value_type = winreg.EnumValue(key, i)
            if expand and value_type == winreg.REG_EXPAND_SZ:
                value = os.path.expandvars(value)
            result[name] = value

    return result


def get_env_var(name, scope='user', expand=False, default=None):
    """
    获取指定名称的环境变量值。

    变量名按不区分大小写匹配（与 Windows 环境变量的行为一致）。

    Args:
        name (str): 变量名。
        scope (str): 环境变量级别，见 list_env_vars。
            'user' / 'system' / 'process'，默认 'user'。
        expand (bool): 是否展开形如 %USERPROFILE% 的变量引用，默认 False。
        default: 变量不存在时返回的默认值，默认 None。

    Returns:
        str: 变量值；不存在时返回 default。
    """
    env = list_env_vars(scope=scope, expand=expand)

    if name in env:
        return env[name]

    lowered = name.lower()
    for key, value in env.items():
        if key.lower() == lowered:
            return value

    return default


def print_env_vars(scope='user', expand=False, copy_to_clipboard=False):
    """
    打印环境变量，支持 USER 级别和 SYSTEM 级别（Windows）。

    Args:
        scope (str): 环境变量级别，见 list_env_vars，'user' / 'system' / 'process'。
        expand (bool): 是否展开形如 %USERPROFILE% 的变量引用，默认 False。
        copy_to_clipboard (bool): 是否将结果复制到剪贴板。
    """
    env = list_env_vars(scope=scope, expand=expand)
    lines = [f'{name}={value}' for name, value in env.items()]
    text = '\n'.join(lines)
    if copy_to_clipboard:
        pyperclip.copy(text)

    print(text)


def get_path(scope='user', expand=True, dedup=False):
    """
    获取 PATH 环境变量，并按分隔符拆分成列表。

    Args:
        scope (str): 环境变量级别，见 list_env_vars。
            'user'    -> 仅当前用户级别的 PATH
            'system'  -> 仅系统级别的 PATH
            'process' -> 当前进程已生效的 PATH (os.environ)
            'all'     -> 系统 + 用户（按 Windows 实际生效顺序：系统在前，用户在后）
        expand (bool): 是否展开形如 %SystemRoot% 的变量引用，默认 True。
        dedup (bool): 是否去重（不区分大小写），保留首次出现顺序，默认 False。

    Returns:
        list[str]: PATH 中的各个路径，已去掉空项和首尾空白。
    """
    scope = (scope or '').lower()

    def _read_path(one_scope):
        env = list_env_vars(scope=one_scope, expand=expand)
        # PATH 的键名大小写不固定，做一次不区分大小写的查找
        for name, value in env.items():
            if name.lower() == 'path':
                return value
        return ''

    if scope == 'all':
        raw = os.pathsep.join(p for p in (_read_path('system'), _read_path('user')) if p)
    else:
        raw = _read_path(scope)

    entries = [p.strip() for p in raw.split(os.pathsep)]
    entries = [p for p in entries if p]

    if dedup:
        seen = set()
        unique = []
        for p in entries:
            key = p.lower()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        entries = unique

    return entries


_PROCESS_SCOPES = ('process', 'proc', 'p')


def _normalize_write_scope(scope):
    """
    规范化「写入」场景的 scope，返回 'process' / 'user' / 'system'。

    Args:
        scope (str): 用户传入的 scope。

    Returns:
        str: 规范化后的 scope。
    """
    scope = (scope or '').lower()
    if scope in _PROCESS_SCOPES:
        return 'process'

    alias = {'u': 'user', 'machine': 'system', 's': 'system'}
    scope = alias.get(scope, scope)
    if scope not in _ENV_REG_LOCATIONS:
        raise ValueError(f"不支持的 scope: {scope!r}，应为 'user' / 'system' / 'process'")
    return scope


def _broadcast_env_change(timeout_ms=5000):
    """
    广播 WM_SETTINGCHANGE，让资源管理器等已运行的进程感知环境变量变化。

    注意：本进程自身不会因此刷新，新值只对之后新启动的进程生效。

    Args:
        timeout_ms (int): SendMessageTimeoutW 对每个窗口的等待上限（毫秒）。
            HWND_BROADCAST 会把消息发给所有顶层窗口，若有窗口迟迟不响应，
            最坏情况会阻塞到该超时；调小可缩短耗时，但通知可能不够彻底。
    """
    try:
        import ctypes
        from ctypes import wintypes

        send = ctypes.windll.user32.SendMessageTimeoutW
        send.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPCWSTR,
            wintypes.UINT,
            wintypes.UINT,
            ctypes.POINTER(wintypes.DWORD),
        ]
        result = wintypes.DWORD()

        t0 = time.perf_counter()
        ret = send(
            0xFFFF,        # HWND_BROADCAST
            0x001A,        # WM_SETTINGCHANGE
            0,
            "Environment",
            0x0002,        # SMTO_ABORTIFHUNG
            timeout_ms,
            ctypes.byref(result),
        )
        elapsed = time.perf_counter() - t0

        # ret == 0 通常表示某个窗口未在 timeout_ms 内响应（超时）或调用失败
        log.debug(
            "广播 WM_SETTINGCHANGE 耗时 %.3fs (timeout=%dms, 返回值=%s, 0 通常代表超时/失败)",
            elapsed, timeout_ms, ret,
        )
        if elapsed * 1000 >= timeout_ms * 0.9:
            log.warning(
                "广播 WM_SETTINGCHANGE 耗时 %.3fs，接近超时上限 %dms，"
                "说明有窗口响应缓慢；可设为 broadcast=False 跳过，或调小 broadcast_timeout_ms。",
                elapsed, timeout_ms,
            )
    except Exception as e:
        # 广播失败不影响实际写入，忽略即可
        log.debug("广播 WM_SETTINGCHANGE 失败（忽略）: %r", e)


def set_env_var(name, value, scope='user', expandable=None, broadcast=False,
                broadcast_timeout_ms=5000):
    """
    设置（新增或修改）一个环境变量。

    'user' / 'system' 会写入 Windows 注册表并持久化；其中 'system' 通常需要
    管理员权限。'process' 只修改当前进程的 os.environ，进程退出即失效。

    Args:
        name (str): 变量名。
        value (str): 变量值。
        scope (str): 'user' / 'system' / 'process'，默认 'user'。
        expandable (bool | None): 是否以 REG_EXPAND_SZ 类型写入（值中含 %VAR% 时
            应为 True，例如 PATH）。None 表示自动判断：值中包含 '%' 时用
            REG_EXPAND_SZ，否则用 REG_SZ。仅对注册表级别有效。
        broadcast (bool): 写入注册表后是否广播 WM_SETTINGCHANGE 通知已运行进程，默认 False。
            新启动的进程无需广播即可读到新值；设为 True 时可能因等待顶层窗口响应而耗时数秒。
        broadcast_timeout_ms (int): 广播时对每个窗口的等待上限（毫秒），默认 5000。

    Returns:
        str: 实际写入的值。
    """
    value = str(value)
    scope = _normalize_write_scope(scope)

    if scope == 'process':
        os.environ[name] = value
        return value

    import winreg

    if expandable is None:
        expandable = '%' in value
    reg_type = winreg.REG_EXPAND_SZ if expandable else winreg.REG_SZ

    root_name, sub_key = _ENV_REG_LOCATIONS[scope]
    root = getattr(winreg, root_name)

    t0 = time.perf_counter()
    with winreg.OpenKey(root, sub_key, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, reg_type, value)
    log.debug("写注册表 %s\\%s 耗时 %.3fs", scope, name, time.perf_counter() - t0)

    if broadcast:
        _broadcast_env_change(timeout_ms=broadcast_timeout_ms)

    return value


def delete_env_var(name, scope='user', broadcast=False):
    """
    删除一个环境变量。

    Args:
        name (str): 变量名。
        scope (str): 'user' / 'system' / 'process'，默认 'user'。
        broadcast (bool): 写入注册表后是否广播 WM_SETTINGCHANGE 通知已运行进程，默认 False。

    Returns:
        bool: 变量原先存在并被删除返回 True；原本就不存在返回 False。
    """
    scope = _normalize_write_scope(scope)

    if scope == 'process':
        return os.environ.pop(name, None) is not None

    import winreg

    root_name, sub_key = _ENV_REG_LOCATIONS[scope]
    root = getattr(winreg, root_name)

    deleted = True
    with winreg.OpenKey(root, sub_key, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, name)
        except FileNotFoundError:
            deleted = False

    if deleted and broadcast:
        _broadcast_env_change()

    return deleted


def _existing_path_name(scope):
    """
    找出指定 scope 中 PATH 变量实际使用的键名（大小写），不存在则返回 'Path'。

    复用已有键名可避免在注册表/环境中产生大小写不同的重复 PATH 项。

    Args:
        scope (str): 规范化后的 scope。

    Returns:
        str: PATH 的键名。
    """
    env = list_env_vars(scope=scope, expand=False)
    for name in env:
        if name.lower() == 'path':
            return name
    return 'Path'


def set_path(paths, scope='user', expandable=True, dedup=True, broadcast=False):
    """
    设置（整体替换）PATH 环境变量。

    Args:
        paths (list[str] | str): 路径列表，或用分隔符（Windows 下为 ';'）连接的字符串。
        scope (str): 'user' / 'system' / 'process'，默认 'user'。
        expandable (bool): 是否以 REG_EXPAND_SZ 类型写入，默认 True
            （PATH 常含 %SystemRoot% 等引用，应保持可展开）。
        dedup (bool): 是否去重（不区分大小写，保留首次出现顺序），默认 True。
        broadcast (bool): 写入注册表后是否广播 WM_SETTINGCHANGE，默认 False。

    Returns:
        str: 实际写入的 PATH 字符串。
    """
    scope = _normalize_write_scope(scope)

    if isinstance(paths, str):
        items = paths.split(os.pathsep)
    else:
        items = list(paths)

    items = [str(p).strip() for p in items]
    items = [p for p in items if p]

    if dedup:
        seen = set()
        unique = []
        for p in items:
            key = p.lower()
            if key not in seen:
                seen.add(key)
                unique.append(p)
        items = unique

    value = os.pathsep.join(items)
    name = _existing_path_name(scope)

    return set_env_var(name, value, scope=scope, expandable=expandable, broadcast=broadcast)


def add_to_path(entry, scope='user', prepend=False, expandable=True, broadcast=False):
    """
    向 PATH 添加一个路径。若该路径已存在（不区分大小写）则不重复添加。

    Args:
        entry (str): 要添加的路径。
        scope (str): 'user' / 'system' / 'process'，默认 'user'。
        prepend (bool): True 添加到最前面，False 追加到末尾，默认 False。
        expandable (bool): 是否以 REG_EXPAND_SZ 类型写入，默认 True。
        broadcast (bool): 写入注册表后是否广播 WM_SETTINGCHANGE，默认 False。

    Returns:
        bool: 实际添加返回 True；已存在、未改动返回 False。
    """
    scope = _normalize_write_scope(scope)

    entry = str(entry).strip()
    if not entry:
        raise ValueError('要添加的路径不能为空')

    # 用未展开的原始值，避免把 %SystemRoot% 这类引用固化成绝对路径
    current = get_path(scope=scope, expand=False)

    if entry.lower() in {p.lower() for p in current}:
        return False

    new_list = [entry] + current if prepend else current + [entry]
    set_path(new_list, scope=scope, expandable=expandable, dedup=False, broadcast=broadcast)
    return True


def remove_from_path(entry, scope='user', expandable=True, broadcast=False):
    """
    从 PATH 中移除一个路径（不区分大小写，移除所有匹配项）。

    Args:
        entry (str): 要移除的路径。
        scope (str): 'user' / 'system' / 'process'，默认 'user'。
        expandable (bool): 是否以 REG_EXPAND_SZ 类型写入，默认 True。
        broadcast (bool): 写入注册表后是否广播 WM_SETTINGCHANGE，默认 False。

    Returns:
        bool: 有匹配项被移除返回 True；没有匹配项、未改动返回 False。
    """
    scope = _normalize_write_scope(scope)

    entry = str(entry).strip()
    current = get_path(scope=scope, expand=False)
    new_list = [p for p in current if p.lower() != entry.lower()]

    if len(new_list) == len(current):
        return False

    set_path(new_list, scope=scope, expandable=expandable, dedup=False, broadcast=broadcast)
    return True