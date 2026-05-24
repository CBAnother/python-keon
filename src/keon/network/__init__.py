"""网络工具模块，提供端口扫描等功能。"""
import socket
import threading
import ipaddress
from queue import Queue
from datetime import datetime


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
