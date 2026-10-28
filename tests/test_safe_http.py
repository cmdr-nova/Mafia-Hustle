import pytest

from mafia_hustle.oauth import safe_http


@pytest.mark.parametrize(
    "url",
    [
        "https://mkultra.social/api/v1/apps",
        "https://bsky.social/.well-known/oauth-authorization-server",
    ],
)
def test_allows_public_https(url):
    assert safe_http.check_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://mkultra.social/",  # not https
        "https://127.0.0.1/",  # raw IP
        "https://[::1]/",
        "https://10.0.0.5/",
        "https://localhost/",
        "https://printer.local/",
        "https://mkultra.social:8443/",  # custom port
        "https://user:pw@mkultra.social/",
        "https://intranet/",  # no dot
        "file:///etc/passwd",
    ],
)
def test_blocks_unsafe_urls(url):
    with pytest.raises(safe_http.UnsafeURL):
        safe_http.check_url(url)
