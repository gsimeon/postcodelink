"""Network and trusted reverse-proxy IP extraction utilities."""
import ipaddress
from typing import List, Optional
from fastapi import Request
from backend.app.config import settings


def is_ip_in_trusted_proxy(ip_str: str, trusted_spec: str) -> bool:
    """Check if an IP address string matches a trusted proxy spec (IP, CIDR, or hostname)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if "/" in trusted_spec:
            return ip in ipaddress.ip_network(trusted_spec, strict=False)
        return ip == ipaddress.ip_address(trusted_spec)
    except ValueError:
        return ip_str.lower() == trusted_spec.lower()


def get_trusted_client_ip(request: Request, trusted_proxies: Optional[List[str]] = None) -> str:
    """Extract real client IP only trusting X-Forwarded-For when direct request arrives via a configured trusted proxy.
    
    If the direct peer (request.client.host) is NOT in TRUSTED_PROXIES, X-Forwarded-For is completely
    ignored to defeat header spoofing.
    """
    direct_ip = request.client.host if request.client else "127.0.0.1"
    trusted_list = (
        trusted_proxies
        if trusted_proxies is not None
        else getattr(settings, "TRUSTED_PROXIES", ["127.0.0.1", "::1", "localhost", "testclient"])
    )

    # If direct peer is not in trusted proxies, ignore X-Forwarded-For completely
    is_trusted = any(is_ip_in_trusted_proxy(direct_ip, proxy) for proxy in trusted_list)
    if not is_trusted:
        return direct_ip

    # Peer is a trusted proxy: parse X-Forwarded-For chain from right to left
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ips = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
        for ip in reversed(ips):
            if not any(is_ip_in_trusted_proxy(ip, proxy) for proxy in trusted_list):
                try:
                    ipaddress.ip_address(ip)
                    return ip
                except ValueError:
                    pass
        if ips:
            try:
                ipaddress.ip_address(ips[0])
                return ips[0]
            except ValueError:
                pass

    return direct_ip
