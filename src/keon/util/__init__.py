# standard library import
import io
import sys
import warnings

# third party import
import pyperclip


def printcp(*objects, sep=" ", end="\n", file=None, flush=False):
    """
    行为与 print() 一致，额外将该次输出内容（不含 end）复制到剪贴板。
    """
    if file is None:
        file = sys.stdout

    buf = io.StringIO()
    print(*objects, sep=sep, end=end, file=buf, flush=False)
    text = buf.getvalue()

    file.write(text)
    if flush:
        file.flush()

    clipboard_text = text[: -len(end)] if end and text.endswith(end) else text
    try:
        pyperclip.copy(clipboard_text)
    except pyperclip.PyperclipException as exc:
        warnings.warn(f"Failed to copy to clipboard: {exc}", stacklevel=2)
