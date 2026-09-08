import socket

import pytest

import api_clients.network_transport as transport


@pytest.fixture(autouse=True)
def restore_transport_state(monkeypatch):
    original_hosts = set(transport._PREFERRED_HOSTS)
    original_installed = transport._INSTALLED
    original_socket_resolver = socket.getaddrinfo
    yield
    transport._PREFERRED_HOSTS.clear()
    transport._PREFERRED_HOSTS.update(original_hosts)
    transport._INSTALLED = original_installed
    socket.getaddrinfo = original_socket_resolver


def _address(family, value):
    if family == socket.AF_INET:
        sockaddr = (value, 8001)
    else:
        sockaddr = (value, 8001, 0, 0)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


def test_configured_hostname_orders_ipv4_before_unreachable_ipv6(monkeypatch):
    addresses = [
        _address(socket.AF_INET6, "2001:db8::10"),
        _address(socket.AF_INET6, "fe80::10"),
        _address(socket.AF_INET, "192.168.1.144"),
    ]
    monkeypatch.setattr(
        transport,
        "_SYSTEM_GETADDRINFO",
        lambda *args, **kwargs: list(addresses),
    )

    assert transport.prefer_ipv4_for_url("https://WIN-6C3OM845I7L:8001") is True

    resolved = socket.getaddrinfo("win-6c3om845i7l", 8001)

    assert [item[0] for item in resolved] == [
        socket.AF_INET,
        socket.AF_INET6,
        socket.AF_INET6,
    ]


def test_ipv6_remains_available_when_no_ipv4_result_exists(monkeypatch):
    addresses = [_address(socket.AF_INET6, "2001:db8::10")]
    monkeypatch.setattr(
        transport,
        "_SYSTEM_GETADDRINFO",
        lambda *args, **kwargs: list(addresses),
    )

    transport.prefer_ipv4_for_url("https://mto-server:8001")

    assert socket.getaddrinfo("MTO-SERVER", 8001) == addresses


def test_other_hosts_keep_system_address_order(monkeypatch):
    addresses = [
        _address(socket.AF_INET6, "2001:db8::10"),
        _address(socket.AF_INET, "192.0.2.10"),
    ]
    monkeypatch.setattr(
        transport,
        "_SYSTEM_GETADDRINFO",
        lambda *args, **kwargs: list(addresses),
    )

    transport.prefer_ipv4_for_url("https://mto-server:8001")

    assert socket.getaddrinfo("example.com", 443) == addresses


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:8001",
        "https://127.0.0.1:8001",
        "https://[::1]:8001",
        "https://192.168.1.144:8001",
    ],
)
def test_literal_and_loopback_hosts_do_not_install_resolver(url):
    before = socket.getaddrinfo

    assert transport.prefer_ipv4_for_url(url) is False
    assert socket.getaddrinfo is before


def test_explicit_address_family_is_not_reordered(monkeypatch):
    addresses = [
        _address(socket.AF_INET6, "2001:db8::10"),
        _address(socket.AF_INET, "192.0.2.10"),
    ]
    monkeypatch.setattr(
        transport,
        "_SYSTEM_GETADDRINFO",
        lambda *args, **kwargs: list(addresses),
    )
    transport.prefer_ipv4_for_url("https://mto-server:8001")

    resolved = socket.getaddrinfo(
        "mto-server", 8001, socket.AF_INET6, socket.SOCK_STREAM
    )

    assert resolved == addresses
