"""Port knocking utilities.

Send an ordered TCP/UDP knock sequence to a host so that a firewall
(or knock daemon) can temporarily open a protected service.
"""

from __future__ import annotations

import socket
import time
from typing import Sequence, Union

KnockItem = Union[str, tuple[int, str]]

_SUPPORTED_PROTOCOLS = frozenset({"tcp", "udp"})


def port_knock(
    ip: str,
    sequence: Sequence[KnockItem],
    delay_ms: int = 100,
    tcp_wait_ms: int = 250,
    verbose: bool = True,
) -> None:
    """
    Send a port-knock sequence to ``ip``.

    Each knock is either a TCP connect attempt (the port is usually
    closed; only the SYN needs to leave the host) or a single UDP
    datagram.

    Args:
        ip: Target host or IP address.
        sequence: Ordered knocks. Each item is either ``"port:protocol"``
            (e.g. ``"42102:udp"``) or ``(port, protocol)``.
        delay_ms: Pause between knocks in milliseconds. Default 100.
        tcp_wait_ms: Max time to wait for a TCP connect attempt in
            milliseconds. Default 250.
        verbose: Whether to print progress. Default True.

    Raises:
        ValueError: If ``ip`` / ``sequence`` is empty, a knock item is
            malformed, a port is out of range, a protocol is unsupported,
            or a timing argument is negative.

    Example:
        >>> from keon import knock
        >>> knock.port_knock(
        ...     "203.0.113.10",
        ...     ["42102:udp", "42103:tcp", (42104, "udp")],
        ... )
    """
    if not isinstance(ip, str) or not ip.strip():
        raise ValueError("ip must be a non-empty string")
    ip = ip.strip()

    if not sequence:
        raise ValueError("sequence cannot be empty")

    if delay_ms < 0:
        raise ValueError(f"delay_ms must be >= 0, got {delay_ms}")
    if tcp_wait_ms < 0:
        raise ValueError(f"tcp_wait_ms must be >= 0, got {tcp_wait_ms}")

    for index, item in enumerate(sequence):
        port, protocol = _parse_item(item)
        if verbose:
            print(f"Knocking {ip} {port}/{protocol}")

        if protocol == "tcp":
            _knock_tcp(ip, port, tcp_wait_ms)
        else:
            _knock_udp(ip, port)

        # No sleep after the last knock.
        if index < len(sequence) - 1 and delay_ms > 0:
            time.sleep(delay_ms / 1000.0)

    if verbose:
        print("Knock sequence completed.")


def _parse_item(item: KnockItem) -> tuple[int, str]:
    """
    Parse one knock item into ``(port, protocol)``.

    Args:
        item: Either ``"port:protocol"`` or ``(port, protocol)``.

    Returns:
        tuple[int, str]: Normalized port and lowercase protocol.

    Raises:
        ValueError: If the item format, port, or protocol is invalid.
    """
    if isinstance(item, str):
        parts = item.split(":")
        if len(parts) != 2:
            raise ValueError(f"bad format: {item!r}, expected port:protocol")
        port_raw, protocol_raw = parts
        port = int(port_raw)
        protocol = protocol_raw.lower().strip()
    elif isinstance(item, tuple) and len(item) == 2:
        port = int(item[0])
        protocol = str(item[1]).lower().strip()
    else:
        raise ValueError(f"bad knock item: {item!r}")

    if not 1 <= port <= 65535:
        raise ValueError(f"port must be in 1-65535, got {port}")
    if protocol not in _SUPPORTED_PROTOCOLS:
        raise ValueError(f"unsupported protocol: {protocol}")

    return port, protocol


def _knock_tcp(ip: str, port: int, wait_ms: int) -> None:
    """Send a TCP SYN by attempting a short-lived connect."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(wait_ms / 1000.0)
        try:
            sock.connect((ip, port))
        except OSError:
            # Closed / filtered ports are expected for knocking.
            pass
    finally:
        sock.close()


def _knock_udp(ip: str, port: int) -> None:
    """Send a single UDP datagram as a knock."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(b"\x00", (ip, port))
    finally:
        sock.close()


__all__ = ["KnockItem", "port_knock"]
