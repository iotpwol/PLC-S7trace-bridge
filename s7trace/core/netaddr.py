"""Live validation of the PLC address typed by the user: IPv4 with optional :port.

S7comm (ISO-on-TCP, port 102) works over IPv4 only, so IPv6 and host names are rejected.
Leading zeros in octets are rejected too (inet_aton would read them as octal).
"""
from __future__ import annotations

INVALID, INTERMEDIATE, ACCEPTABLE = 0, 1, 2
_ALLOWED = set("0123456789.:")


def ipv4_state(text: str) -> int:
    if any(c not in _ALLOWED for c in text):
        return INVALID
    if text.count(":") > 1:
        return INVALID
    host, colon, port = text.partition(":")
    parts = host.split(".")
    if len(parts) > 4:
        return INVALID
    for i, p in enumerate(parts):
        if p == "":
            if i < len(parts) - 1 or (i == 0 and len(parts) > 1):
                return INVALID          # '..' or leading '.'
            continue
        if len(p) > 3 or (len(p) > 1 and p[0] == "0") or int(p) > 255:
            return INVALID
    complete = len(parts) == 4 and all(parts)
    if colon:
        if not complete:
            return INVALID              # ':' only after a full address
        if len(port) > 5 or (len(port) > 1 and port[0] == "0") or (port and int(port) > 65535):
            return INVALID
        return ACCEPTABLE if port and int(port) >= 1 else INTERMEDIATE
    return ACCEPTABLE if complete else INTERMEDIATE
