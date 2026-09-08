"""Process-local address selection for the desktop API connection.

Windows name resolution can return unreachable IPv6 addresses before the
server's working IPv4 address. urllib3 tries those addresses in order, so a
new HTTPS connection can lose several seconds before falling back to IPv4.

This module keeps the configured hostname in the URL (and therefore preserves
TLS SNI and hostname verification) while ordering IPv4 results first for that
one API hostname. IPv6 remains available as a fallback.
"""

from __future__ import annotations

import ipaddress
import socket
import threading
from typing import Any
from urllib.parse import urlparse


_SYSTEM_GETADDRINFO = socket.getaddrinfo
_PREFERRED_HOSTS: set[str] = set()
_INSTALL_LOCK = threading.Lock()
_INSTALLED = False


def _normalize_host(host: Any) -> str:
    if isinstance(host, bytes):
        try:
            host = host.decode("idna")
        except UnicodeError:
            return ""
    return str(host or "").strip().strip("[]").rstrip(".").casefold()


def _ipv4_first_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    """Delegate to Windows, then prefer IPv4 for configured API hosts only."""
    results = _SYSTEM_GETADDRINFO(host, port, family, type, proto, flags)
    normalized = _normalize_host(host)
    if family not in (0, socket.AF_UNSPEC) or normalized not in _PREFERRED_HOSTS:
        return results

    # Python's sort is stable, so Windows' order is retained within each family.
    return sorted(
        results,
        key=lambda item: (
            0 if item[0] == socket.AF_INET else 1 if item[0] == socket.AF_INET6 else 2
        ),
    )


def prefer_ipv4_for_url(url: str) -> bool:
    """Prefer IPv4 for one API hostname without weakening TLS checks.

    Returns ``True`` when hostname ordering was installed. Literal IP
    addresses and localhost do not need reordering and return ``False``.
    """
    host = _normalize_host(urlparse(url).hostname)
    if not host or host == "localhost":
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass

    global _INSTALLED
    with _INSTALL_LOCK:
        _PREFERRED_HOSTS.add(host)
        if not _INSTALLED:
            socket.getaddrinfo = _ipv4_first_getaddrinfo
            _INSTALLED = True
    return True
