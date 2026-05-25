import os
import fnmatch
import pyperclip


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