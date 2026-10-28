"""HTTP helpers for talking to servers the player picked.

Logging in means our server makes requests to whatever instance or PDS the player typed in.
Without care, someone could type an internal address and use the game to poke at your private
network (SSRF). So every outbound request goes through here:

- https only, no custom ports, no usernames in URLs, no raw IP addresses
- requests_hardened refuses to connect to private, loopback, or link-local IPs, even when a
  public-looking hostname resolves to one
- no redirects, short timeouts, and a cap on how much we read
"""

import ipaddress
import json
import re
from urllib.parse import urlsplit

import requests_hardened

MAX_RESPONSE_BYTES = 1_000_000

HOSTNAME_RE = re.compile(
    r"^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$", re.IGNORECASE
)
BLOCKED_TLDS = {"local", "localhost", "internal", "arpa", "invalid", "test", "example", "onion"}


class UnsafeURL(ValueError):
    pass


_manager = requests_hardened.Manager(
    requests_hardened.Config(
        default_timeout=(3, 10),
        never_redirect=True,
        ip_filter_enable=True,
        ip_filter_allow_loopback_ips=False,
        user_agent_override="MafiaHustle (+https://github.com/cmdr-nova/Mafia-Hustle)",
    )
)


def is_public_hostname(hostname):
    if not hostname or len(hostname) > 253 or not HOSTNAME_RE.match(hostname):
        return False
    try:
        ipaddress.ip_address(hostname)
        return False
    except ValueError:
        pass
    return hostname.rsplit(".", 1)[-1].lower() not in BLOCKED_TLDS


def check_url(url):
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.username
        or parts.password
        or parts.port is not None
        or not is_public_hostname(parts.hostname)
    ):
        raise UnsafeURL(f"Refusing to contact {url!r}")
    return url


def request(method, url, **kwargs):
    check_url(url)
    with _manager.get_session() as session:
        response = session.request(method, url, stream=True, **kwargs)
        body = bytearray()
        for chunk in response.iter_content(65536):
            body += chunk
            if len(body) > MAX_RESPONSE_BYTES:
                response.close()
                raise ValueError(f"Response from {url} is too large")
        response._content = bytes(body)
        return response


def get_json(url, **kwargs):
    response = request("GET", url, **kwargs)
    response.raise_for_status()
    return parse_json(response)


def parse_json(response):
    try:
        data = json.loads(response.content)
    except ValueError as err:
        raise ValueError(f"{response.url} did not return JSON") from err
    if not isinstance(data, dict):
        raise ValueError(f"{response.url} returned unexpected JSON")
    return data
