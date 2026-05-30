"""网络工具模块，提供端口扫描等功能。"""
from datetime import datetime, timedelta
from pathlib import Path
from queue import Queue
import ipaddress
import re
import socket
import threading

import pandas as pd

def _parse_ports(ports):
    """
    规范化端口入参，返回去重并升序排列的端口列表。
    
    支持的输入形式：
        123                            -> [123]
        '123-456'                      -> [123, 124, ..., 456]
        '80,443,8000-8100'             -> [80, 443, 8000, ..., 8100]
        ['123-456', '678-999']         -> 合并展开
        [123, 456, 789]                -> [123, 456, 789]
        [123, '200-210']               -> 混合也可
    """
    if isinstance(ports, (int, str)):
        items = [ports]
    else:
        items = list(ports)
    
    result = set()
    for item in items:
        if isinstance(item, int):
            result.add(item)
            continue
        
        if not isinstance(item, str):
            raise TypeError(f'不支持的端口类型: {type(item).__name__}')
        
        for piece in item.split(','):
            piece = piece.strip()
            if not piece:
                continue
            
            if '-' in piece:
                lo_s, hi_s = piece.split('-', 1)
                lo, hi = int(lo_s.strip()), int(hi_s.strip())
                if lo > hi:
                    lo, hi = hi, lo
                result.update(range(lo, hi + 1))
            else:
                result.add(int(piece))
    
    invalid = sorted(p for p in result if not 1 <= p <= 65535)
    if invalid:
        raise ValueError(f'端口号必须在 1-65535 之间，无效项: {invalid[:5]}')
    
    return sorted(result)


def _format_ports(ports):
    """
    把端口列表压成紧凑字符串。
    
    Args:
        ports (list): 端口号列表
        
    Returns:
        str: 紧凑格式的端口字符串，如 '22,80,8000-8100'
    """
    if not ports:
        return ''
    
    ports = sorted(set(ports))
    parts = []
    start = prev = ports[0]
    
    for p in ports[1:]:
        if p == prev + 1:
            prev = p
        else:
            parts.append(str(start) if start == prev else f'{start}-{prev}')
            start = prev = p
    
    parts.append(str(start) if start == prev else f'{start}-{prev}')
    return ','.join(parts)


class PortScanner:
    """
    多线程端口扫描器，扫描指定网段中开放指定端口的设备。
    """
    
    def __init__(self, network, ports, timeout=1, max_threads=100):
        """
        初始化端口扫描器。
        
        Args:
            network (str): 网段，例如 '192.168.1.0/24'
            ports: 要扫描的端口，可为：
                - int            例: 80
                - str            例: '80' / '80-100' / '80,443,8000-8100'
                - list/tuple     元素可以是 int 或上面的字符串
            timeout (float): 连接超时时间（秒）
            max_threads (int): 最大线程数
        """
        self.network = network
        self.ports = _parse_ports(ports)
        self.timeout = timeout
        self.max_threads = max_threads
        self.queue = Queue()
        self.lock = threading.Lock()
        # 命中的 (ip, port) 列表
        self.open_results = []
    
    def scan_host(self, ip, port):
        """
        扫描单个 (ip, port) 组合，开放则记录。
        
        Args:
            ip (str): IP 地址
            port (int): 端口号
            
        Returns:
            bool: 端口是否开放
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            result = sock.connect_ex((str(ip), port))
            sock.close()
            
            if result == 0:
                with self.lock:
                    self.open_results.append((str(ip), port))
                print(f"[+] {ip}:{port} 开放")
                return True
            return False
        except socket.error:
            return False
    
    def worker(self):
        """
        工作线程函数。
        """
        while True:
            item = self.queue.get()
            if item is None:
                break
            
            ip, port = item
            self.scan_host(ip, port)
            self.queue.task_done()
    
    def scan(self):
        """
        开始扫描。
        
        Returns:
            list: 开放的 (ip, port) 元组列表
        """
        print(f"\n{'='*60}")
        print(f"开始扫描网段: {self.network}")
        print(f"目标端口: {_format_ports(self.ports)} (共 {len(self.ports)} 个)")
        print(f"超时时间: {self.timeout}秒")
        print(f"线程数: {self.max_threads}")
        print(f"{'='*60}\n")
        
        start_time = datetime.now()
        
        try:
            network = ipaddress.ip_network(self.network, strict=False)
            ip_list = list(network.hosts())
            # /32 或 /31 时 hosts() 可能为空
            if not ip_list:
                ip_list = [network.network_address]
            
            total_hosts = len(ip_list)
            total_tasks = total_hosts * len(self.ports)
            print(f"总共需要扫描 {total_hosts} 个主机 × {len(self.ports)} 个端口 = {total_tasks} 个任务\n")
        except ValueError as e:
            print(f"错误: 无效的网段格式 - {e}")
            return []
        
        # 创建工作线程
        threads = []
        for _ in range(min(self.max_threads, total_tasks)):
            t = threading.Thread(target=self.worker)
            t.daemon = True
            t.start()
            threads.append(t)
        
        # 添加扫描任务
        for ip in ip_list:
            for port in self.ports:
                self.queue.put((ip, port))
        
        # 等待所有任务完成
        self.queue.join()
        
        # 停止工作线程
        for _ in range(len(threads)):
            self.queue.put(None)
        for t in threads:
            t.join()
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # 按主机聚合结果
        grouped = {}
        for ip, port in self.open_results:
            grouped.setdefault(ip, []).append(port)
        
        print(f"\n{'='*60}")
        print(f"扫描完成!")
        print(f"耗时: {duration:.2f}秒")
        print(f"发现 {len(grouped)} 个主机命中 (共 {len(self.open_results)} 个开放端口):")
        if grouped:
            for host in sorted(grouped, key=lambda x: ipaddress.ip_address(x)):
                print(f"  - {host}: {_format_ports(grouped[host])}")
        else:
            print("  未发现开放的主机")
        print(f"{'='*60}\n")
        
        return self.open_results



_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "May": 5, "Jun": 6, "Jul": 7, "Aug": 8,
    "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _parse_duration(duration_raw):
    if not duration_raw:
        return pd.NaT

    duration_raw = duration_raw.strip().strip("()")

    # 支持：
    # 01:01
    # 56+08:22
    m = re.fullmatch(r"(?:(\d+)\+)?(\d{1,2}):(\d{2})", duration_raw)
    if not m:
        return pd.NaT

    days = int(m.group(1) or 0)
    hours = int(m.group(2))
    minutes = int(m.group(3))

    return pd.Timedelta(days=days, hours=hours, minutes=minutes)


def _parse_date_tokens(tokens, idx):
    """
    兼容两种格式：

    短格式：
        Mon Nov 24 15:20

    完整格式：
        Mon Nov 24 15:20:53 2025
    """
    if idx + 3 >= len(tokens):
        return None, idx

    weekday = tokens[idx]
    month = tokens[idx + 1]
    day = int(tokens[idx + 2])
    time_raw = tokens[idx + 3]

    # 完整格式：Mon Nov 24 15:20:53 2025
    if idx + 4 < len(tokens) and re.fullmatch(r"\d{4}", tokens[idx + 4]):
        year = int(tokens[idx + 4])

        if re.fullmatch(r"\d{1,2}:\d{2}:\d{2}", time_raw):
            fmt = "%a %b %d %H:%M:%S %Y"
        else:
            fmt = "%a %b %d %H:%M %Y"

        dt = datetime.strptime(
            f"{weekday} {month} {day} {time_raw} {year}",
            fmt
        )

        return {
            "weekday": weekday,
            "month": month,
            "day": day,
            "time_raw": time_raw,
            "year": year,
            "dt": dt,
            "is_full_date": True,
        }, idx + 5

    # 短格式：Mon Nov 24 15:20
    return {
        "weekday": weekday,
        "month": month,
        "day": day,
        "time_raw": time_raw,
        "year": None,
        "dt": None,
        "is_full_date": False,
    }, idx + 4


def _parse_last_line(line):
    line = line.rstrip("\n")
    if not line.strip():
        return None

    # 取出最后的 duration，例如 (01:01)、(56+08:22)
    duration_raw = None
    duration_match = re.search(r"\(([^)]+)\)\s*$", line)
    if duration_match:
        duration_raw = duration_match.group(1)
        line_without_duration = line[:duration_match.start()].rstrip()
    else:
        line_without_duration = line

    tokens = line_without_duration.split()
    if len(tokens) < 7:
        return None

    user = tokens[0]

    # reboot 行：
    # reboot system boot 6.8.0-49-generic Mon Jan 20 18:49 still running
    if user == "reboot" and len(tokens) >= 8 and tokens[1] == "system" and tokens[2] == "boot":
        tty = "system boot"
        host = tokens[3]      # kernel version
        date_idx = 4
    else:
        tty = tokens[1]
        host = tokens[2]
        date_idx = 3

    start_info, next_idx = _parse_date_tokens(tokens, date_idx)
    if not start_info:
        return None

    rest_tokens = tokens[next_idx:]

    status = None
    logout_raw = None
    end_info = None

    if not rest_tokens:
        status = None

    elif rest_tokens[0] == "-":
        after_dash = rest_tokens[1:]

        # 完整结束时间：
        # - Mon Nov 24 16:21:53 2025
        possible_end, consumed_idx = _parse_date_tokens(after_dash, 0)

        if possible_end and possible_end["is_full_date"]:
            end_info = possible_end
            logout_raw = possible_end["time_raw"]
            status = "closed"

        elif after_dash:
            # 短结束时间：
            # - 16:21
            # - down
            logout_raw = after_dash[0]

            if re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", logout_raw):
                status = "closed"
            else:
                status = logout_raw

    elif rest_tokens[0] == "still":
        # still logged in / still running
        status = " ".join(rest_tokens)

    else:
        status = " ".join(rest_tokens)

    return {
        "user": user,
        "tty": tty,
        "host": host,

        "weekday": start_info["weekday"],
        "month": start_info["month"],
        "day": start_info["day"],
        "start_time_raw": start_info["time_raw"],
        "year": start_info["year"],
        "start_dt": start_info["dt"],
        "start_is_full_date": start_info["is_full_date"],

        "logout_raw": logout_raw,
        "end_dt": end_info["dt"] if end_info else None,
        "end_is_full_date": bool(end_info and end_info["is_full_date"]),

        "status": status,
        "duration_raw": duration_raw,
        "duration": _parse_duration(duration_raw),
        "raw": line,
    }


def _infer_missing_datetimes(df, newest_year=None):
    """
    对短格式补年份：

    如果行本身已经有完整年份，就直接使用。
    如果没有年份，则根据 last 输出的倒序特征推断年份。
    """
    if df.empty:
        return df

    if newest_year is None:
        newest_year = datetime.now().year

    result_rows = []
    prev_start_dt = None

    for _, row in df.iterrows():
        row = row.copy()

        # start_dt 已经完整，例如 last -F 输出
        if pd.notna(row["start_dt"]):
            start_dt = row["start_dt"].to_pydatetime() if hasattr(row["start_dt"], "to_pydatetime") else row["start_dt"]
            year = start_dt.year

        else:
            # 短格式，推断 year
            base_year = prev_start_dt.year if prev_start_dt is not None else newest_year

            month_num = _MONTHS[row["month"]]
            day = int(row["day"])

            time_parts = [int(x) for x in row["start_time_raw"].split(":")]
            hour = time_parts[0]
            minute = time_parts[1]
            second = time_parts[2] if len(time_parts) >= 3 else 0

            year = base_year

            while True:
                start_dt = datetime(year, month_num, day, hour, minute, second)

                # last 输出通常是从新到旧
                if prev_start_dt is None or start_dt <= prev_start_dt:
                    break

                year -= 1

            row["year"] = year
            row["start_dt"] = start_dt

        prev_start_dt = start_dt

        # 处理 end_dt
        if pd.notna(row["end_dt"]):
            # 完整结束时间已经解析好了
            pass

        elif isinstance(row["logout_raw"], str) and re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", row["logout_raw"]):
            # 短格式结束时间，例如 - 16:21
            time_parts = [int(x) for x in row["logout_raw"].split(":")]
            hour = time_parts[0]
            minute = time_parts[1]
            second = time_parts[2] if len(time_parts) >= 3 else 0

            if pd.notna(row["duration"]):
                # 用 duration 推断结束日期，再用 logout_raw 修正时分秒
                end_date = (start_dt + row["duration"]).date()
                row["end_dt"] = datetime.combine(end_date, datetime.min.time()).replace(
                    hour=hour,
                    minute=minute,
                    second=second,
                )
            else:
                end_dt = start_dt.replace(hour=hour, minute=minute, second=second)

                if end_dt < start_dt:
                    end_dt += timedelta(days=1)

                row["end_dt"] = end_dt

        elif pd.notna(row["duration"]):
            # 例如 - down (00:02)，没有具体结束时间，只能用 duration 推
            row["end_dt"] = start_dt + row["duration"]

        else:
            # still logged in / still running
            row["end_dt"] = pd.NaT

        result_rows.append(row)

    out = pd.DataFrame(result_rows)
    out["start_dt"] = pd.to_datetime(out["start_dt"], errors="coerce")
    out["end_dt"] = pd.to_datetime(out["end_dt"], errors="coerce")

    return out


def parse_last_output(text, newest_year=None):
    """
    Parse the output of the `last` command into a structured DataFrame.

    linux run: last -F > last.txt
    df = parse_last_output(Path("last.txt").read_text(encoding="utf-8"))
    """
    rows = []

    for line in text.splitlines():
        row = _parse_last_line(line)
        if row:
            rows.append(row)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    df = _infer_missing_datetimes(df, newest_year=newest_year)

    return df[
        [
            "user",
            "tty",
            "host",
            "year",
            "weekday",
            "month",
            "day",
            "start_time_raw",
            "logout_raw",
            "status",
            "duration_raw",
            "duration",
            "start_dt",
            "end_dt",
            "raw",
        ]
    ]




__all__ = ["PortScanner", "parse_last_output"]