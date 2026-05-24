import pytest
from keon.network import PortScanner, _parse_ports, _format_ports


# ── 测试端口解析 ───────────────────────────────────────────────────────────────

def test_parse_ports_single_int():
    assert _parse_ports(80) == [80]


def test_parse_ports_single_str():
    assert _parse_ports('80') == [80]


def test_parse_ports_range():
    assert _parse_ports('80-83') == [80, 81, 82, 83]


def test_parse_ports_range_reversed():
    """范围反向时自动调整"""
    assert _parse_ports('83-80') == [80, 81, 82, 83]


def test_parse_ports_comma_separated():
    assert _parse_ports('80,443,8080') == [80, 443, 8080]


def test_parse_ports_mixed():
    assert _parse_ports('22,80-82,443') == [22, 80, 81, 82, 443]


def test_parse_ports_list_of_ints():
    assert _parse_ports([80, 443, 22]) == [22, 80, 443]


def test_parse_ports_list_of_strings():
    assert _parse_ports(['80-82', '443']) == [80, 81, 82, 443]


def test_parse_ports_mixed_list():
    assert _parse_ports([22, '80-82', 443]) == [22, 80, 81, 82, 443]


def test_parse_ports_deduplication():
    """自动去重"""
    assert _parse_ports('80,80,80') == [80]
    assert _parse_ports('80-82,81-83') == [80, 81, 82, 83]


def test_parse_ports_with_spaces():
    """支持空格"""
    assert _parse_ports(' 80 , 443 , 8080 ') == [80, 443, 8080]
    assert _parse_ports(' 80 - 82 ') == [80, 81, 82]


def test_parse_ports_invalid_range():
    """超出范围的端口"""
    with pytest.raises(ValueError, match='端口号必须在 1-65535 之间'):
        _parse_ports('0')
    
    with pytest.raises(ValueError, match='端口号必须在 1-65535 之间'):
        _parse_ports('65536')
    
    with pytest.raises(ValueError, match='端口号必须在 1-65535 之间'):
        _parse_ports('80,99999')


def test_parse_ports_invalid_type():
    """不支持的类型"""
    with pytest.raises(TypeError, match='不支持的端口类型'):
        _parse_ports([80, 3.14])


def test_parse_ports_empty_string():
    """空字符串"""
    assert _parse_ports('') == []


def test_parse_ports_empty_list():
    """空列表"""
    assert _parse_ports([]) == []


# ── 测试端口格式化 ─────────────────────────────────────────────────────────────

def test_format_ports_single():
    assert _format_ports([80]) == '80'


def test_format_ports_multiple():
    assert _format_ports([22, 80, 443]) == '22,80,443'


def test_format_ports_range():
    assert _format_ports([80, 81, 82, 83]) == '80-83'


def test_format_ports_mixed():
    assert _format_ports([22, 80, 81, 82, 443, 8000, 8001]) == '22,80-82,443,8000-8001'


def test_format_ports_unsorted():
    """自动排序"""
    assert _format_ports([443, 22, 80]) == '22,80,443'


def test_format_ports_duplicates():
    """自动去重"""
    assert _format_ports([80, 80, 80]) == '80'


def test_format_ports_empty():
    assert _format_ports([]) == ''


# ── 测试 PortScanner 初始化 ────────────────────────────────────────────────────

def test_scanner_init_with_int_port():
    scanner = PortScanner('192.168.1.0/24', 80)
    assert scanner.network == '192.168.1.0/24'
    assert scanner.ports == [80]
    assert scanner.timeout == 1
    assert scanner.max_threads == 100


def test_scanner_init_with_string_ports():
    scanner = PortScanner('10.0.0.0/24', '22,80,443')
    assert scanner.ports == [22, 80, 443]


def test_scanner_init_with_port_range():
    scanner = PortScanner('192.168.1.0/24', '8000-8003')
    assert scanner.ports == [8000, 8001, 8002, 8003]


def test_scanner_init_with_custom_timeout():
    scanner = PortScanner('192.168.1.0/24', 80, timeout=0.5)
    assert scanner.timeout == 0.5


def test_scanner_init_with_custom_threads():
    scanner = PortScanner('192.168.1.0/24', 80, max_threads=50)
    assert scanner.max_threads == 50


# ── 测试 PortScanner.scan_host ─────────────────────────────────────────────────

def test_scan_host_closed_port():
    """扫描一个肯定关闭的端口"""
    scanner = PortScanner('127.0.0.1/32', 65432, timeout=0.1)
    result = scanner.scan_host('127.0.0.1', 65432)
    assert result is False
    assert len(scanner.open_results) == 0


def test_scan_host_invalid_ip():
    """扫描无效 IP"""
    scanner = PortScanner('192.168.1.0/24', 80, timeout=0.1)
    result = scanner.scan_host('999.999.999.999', 80)
    assert result is False


# ── 测试 PortScanner.scan ──────────────────────────────────────────────────────

def test_scan_invalid_network():
    """无效的网段格式"""
    scanner = PortScanner('invalid-network', 80)
    results = scanner.scan()
    assert results == []


def test_scan_single_host(capsys):
    """扫描单个主机（/32）"""
    scanner = PortScanner('127.0.0.1/32', 65432, timeout=0.1, max_threads=1)
    results = scanner.scan()
    
    captured = capsys.readouterr()
    assert '开始扫描网段: 127.0.0.1/32' in captured.out
    assert '扫描完成!' in captured.out
    assert isinstance(results, list)


def test_scan_small_network(capsys):
    """扫描小网段"""
    scanner = PortScanner('192.168.1.0/30', 65432, timeout=0.1, max_threads=5)
    results = scanner.scan()
    
    captured = capsys.readouterr()
    assert '开始扫描网段' in captured.out
    assert '扫描完成!' in captured.out


# ── 集成测试 ───────────────────────────────────────────────────────────────────

def test_full_workflow():
    """完整工作流测试"""
    scanner = PortScanner(
        network='127.0.0.1/32',
        ports='65430-65432',
        timeout=0.1,
        max_threads=2
    )
    
    assert scanner.network == '127.0.0.1/32'
    assert scanner.ports == [65430, 65431, 65432]
    assert scanner.timeout == 0.1
    assert scanner.max_threads == 2
    
    results = scanner.scan()
    assert isinstance(results, list)
