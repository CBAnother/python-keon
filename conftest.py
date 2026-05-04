import sys
from pathlib import Path

# 将 src 目录添加到 sys.path，使 keon 包可以被导入
src_path = Path(__file__).parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
