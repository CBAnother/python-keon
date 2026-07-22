"""Tests for knock module."""

from unittest.mock import MagicMock, patch

import pytest

from keon.knock import port_knock
from keon.knock import _parse_item


class TestParseItem:
    """Test cases for knock item parsing."""

    def test_string_format(self):
        assert _parse_item("42102:udp") == (42102, "udp")
        assert _parse_item("80:TCP") == (80, "tcp")

    def test_tuple_format(self):
        assert _parse_item((42103, "tcp")) == (42103, "tcp")
        assert _parse_item((9, "UDP")) == (9, "udp")

    def test_bad_string_format(self):
        with pytest.raises(ValueError, match="bad format"):
            _parse_item("42102")
        with pytest.raises(ValueError, match="bad format"):
            _parse_item("a:b:c")

    def test_bad_item_type(self):
        with pytest.raises(ValueError, match="bad knock item"):
            _parse_item([42102, "udp"])  # type: ignore[arg-type]

    def test_invalid_port(self):
        with pytest.raises(ValueError, match="port must be in 1-65535"):
            _parse_item("0:udp")
        with pytest.raises(ValueError, match="port must be in 1-65535"):
            _parse_item((65536, "tcp"))

    def test_unsupported_protocol(self):
        with pytest.raises(ValueError, match="unsupported protocol"):
            _parse_item("80:icmp")


class TestPortKnock:
    """Test cases for port_knock."""

    def test_empty_ip(self):
        with pytest.raises(ValueError, match="ip must be a non-empty string"):
            port_knock("", ["80:tcp"], verbose=False)
        with pytest.raises(ValueError, match="ip must be a non-empty string"):
            port_knock("   ", ["80:tcp"], verbose=False)

    def test_empty_sequence(self):
        with pytest.raises(ValueError, match="sequence cannot be empty"):
            port_knock("127.0.0.1", [], verbose=False)

    def test_negative_timings(self):
        with pytest.raises(ValueError, match="delay_ms"):
            port_knock("127.0.0.1", ["80:tcp"], delay_ms=-1, verbose=False)
        with pytest.raises(ValueError, match="tcp_wait_ms"):
            port_knock("127.0.0.1", ["80:tcp"], tcp_wait_ms=-1, verbose=False)

    @patch("keon.knock.time.sleep")
    @patch("keon.knock.socket.socket")
    def test_mixed_sequence(self, mock_socket_cls, mock_sleep):
        tcp_sock = MagicMock()
        udp_sock = MagicMock()
        # First knock UDP, second TCP, third UDP
        mock_socket_cls.side_effect = [udp_sock, tcp_sock, udp_sock]

        port_knock(
            "203.0.113.10",
            ["42102:udp", "42103:tcp", (42104, "udp")],
            delay_ms=100,
            tcp_wait_ms=250,
            verbose=False,
        )

        assert mock_socket_cls.call_count == 3
        udp_sock.sendto.assert_any_call(b"\x00", ("203.0.113.10", 42102))
        udp_sock.sendto.assert_any_call(b"\x00", ("203.0.113.10", 42104))
        tcp_sock.settimeout.assert_called_once_with(0.25)
        tcp_sock.connect.assert_called_once_with(("203.0.113.10", 42103))
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(0.1)

    @patch("keon.knock.time.sleep")
    @patch("keon.knock.socket.socket")
    def test_tcp_oserror_is_swallowed(self, mock_socket_cls, mock_sleep):
        sock = MagicMock()
        sock.connect.side_effect = OSError("connection refused")
        mock_socket_cls.return_value = sock

        port_knock("127.0.0.1", ["22:tcp"], delay_ms=0, verbose=False)

        sock.connect.assert_called_once_with(("127.0.0.1", 22))
        sock.close.assert_called_once()
        mock_sleep.assert_not_called()

    @patch("keon.knock.time.sleep")
    @patch("keon.knock.socket.socket")
    def test_verbose_prints(self, mock_socket_cls, mock_sleep, capsys):
        mock_socket_cls.return_value = MagicMock()

        port_knock("127.0.0.1", ["9:udp"], delay_ms=0, verbose=True)

        out = capsys.readouterr().out
        assert "Knocking 127.0.0.1 9/udp" in out
        assert "Knock sequence completed." in out
