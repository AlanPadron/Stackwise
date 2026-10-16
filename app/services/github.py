"""GitHub REST access for the "import a repository" flow.

Every call uses the *user's own* OAuth token, never a service token, so the set
of repositories reachable here is exactly the one the user granted at consent
time. The token travels in an `Authorization` header and is never put in a URL,
logged, or returned to a client.

This is the only place the backend makes an outbound request built from a URL, so
it is also where the SSRF guards live: the base URL must be http(s) without
embedded credentials, and — unless `ANALYSIS_ALLOW_PRIVATE_GIT_HOSTS` is set for
a self-hosted GitHub Enterprise — it must not resolve to a loopback, private,
link-local, reserved or multicast address (cloud metadata endpoints included).
"""

import ipaddress
import os
import re
import socket
import tempfile
from typing import Any, Optional
from urllib.parse import quote, urlparse

import httpx

from app.core.config import settings

HTTP_TIMEOUT = 30.0
PER_PAGE = 100

_REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,198}$")
_BLOCKED_HOSTS = frozenset({"metadata.google.internal", "metadata.goog", "instance-data"})


class GitHubError(Exception):
    """A GitHub call that could not be completed with the stored token.

    `status_code` is GitHub's own status so callers can tell "not found" from
    "token no longer valid" without parsing the message.
    """

    def __init__(self, detail: str, status_code: Optional[int] = None):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _normalise(repo: dict[str, Any]) -> dict[str, Any]:
    """Trim GitHub's payload down to what the import screen renders."""
    return {
        "full_name": repo["full_name"],
        "name": repo["name"],
        "owner": repo["owner"]["login"],
        "private": repo["private"],
        "description": repo.get("description"),
        "default_branch": repo.get("default_branch"),
        "language": repo.get("language"),
        "updated_at": repo.get("updated_at"),
        "html_url": repo.get("html_url"),
    }


def validate_base_url(url: str, *, allow_private: Optional[bool] = None) -> str:
    """Validate the configured GitHub API base URL (SSRF guard). Returns it.

    This is a *configuration* check, not user input validation: the value comes
    from the environment. It is enforced anyway so that a misconfigured
    deployment cannot be pointed at the metadata service or an internal host.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise GitHubError(f"Unsupported GitHub base URL scheme: {parsed.scheme or '(none)'}")
    if parsed.username or parsed.password:
        raise GitHubError("Credentials must not be embedded in the GitHub base URL")
    host = parsed.hostname
    if not host:
        raise GitHubError("The GitHub base URL has no host")
    if allow_private is None:
        allow_private = settings.ANALYSIS_ALLOW_PRIVATE_GIT_HOSTS
    if allow_private:
        return url.rstrip("/")

    lowered = host.lower()
    if lowered in _BLOCKED_HOSTS or lowered.endswith((".localhost", ".internal", ".local")):
        raise GitHubError(f"The GitHub base URL host is not allowed: {host}")

    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise GitHubError(f"Could not resolve the GitHub base URL host: {host}") from exc
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise GitHubError(f"Unresolvable GitHub base URL host: {host}") from None
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise GitHubError(
                f"The GitHub base URL resolves to a non-public address ({address}); "
                "set ANALYSIS_ALLOW_PRIVATE_GIT_HOSTS=true for a self-hosted GitHub Enterprise"
            )
    return url.rstrip("/")


def validate_repository(full_name: str) -> str:
    """`owner/name` only: no traversal, no extra path segments, no scheme."""
    if not _REPOSITORY.match(full_name or "") or ".." in full_name:
        raise GitHubError("Invalid repository name", 404)
    return full_name


def validate_ref(ref: Optional[str]) -> Optional[str]:
    """A branch/tag/commit is URL-quoted and refused if it tries to climb."""
    if not ref:
        return None
    if not _REF.match(ref) or ".." in ref or "//" in ref:
        raise GitHubError("Invalid repository ref", 404)
    return "/".join(quote(segment, safe="") for segment in ref.split("/"))


async def list_repositories(token: str) -> list[dict[str, Any]]:
    """Repositories the token can read, most recently pushed first.

    Capped at one page: this feeds a picker, and paging the full list of an
    organisation with thousands of repositories is not worth the latency.
    """
    base_url = validate_base_url(settings.GITHUB_API_BASE_URL)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
        response = await client.get(
            f"{base_url}/user/repos",
            params={
                "per_page": PER_PAGE,
                "sort": "pushed",
                "affiliation": "owner,collaborator,organization_member",
            },
            headers=_headers(token),
        )

    if response.status_code != 200:
        raise GitHubError(
            f"GitHub rejected the repository list ({response.status_code})",
            response.status_code,
        )
    return [_normalise(repo) for repo in response.json()]


async def download_repository_zip(
    token: str, full_name: str, ref: Optional[str] = None
) -> str:
    """Download a repository snapshot as a ZIP into a fresh temp file.

    The response is streamed so the archive size limit can be enforced while the
    bytes arrive — a remote archive has no trusted Content-Length. Redirects are
    not followed: GitHub serves from its own host, and following a redirect would
    hand the token to whatever host the response names. The caller owns the
    returned path; the analysis pipeline deletes it when the run ends.
    """
    base_url = validate_base_url(settings.GITHUB_API_BASE_URL)
    repository = validate_repository(full_name)
    encoded_ref = validate_ref(ref)

    url = f"{base_url}/repos/{repository}/zipball"
    if encoded_ref:
        url = f"{url}/{encoded_ref}"

    limit = settings.ANALYSIS_MAX_ARCHIVE_SIZE_MB * 1024 * 1024
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
            async with client.stream("GET", url, headers=_headers(token)) as response:
                if response.status_code != 200:
                    raise GitHubError(
                        f"Could not download {repository} ({response.status_code})",
                        response.status_code,
                    )
                written = 0
                async for chunk in response.aiter_bytes():
                    written += len(chunk)
                    if written > limit:
                        raise GitHubError(
                            f"Repository archive exceeds the "
                            f"{settings.ANALYSIS_MAX_ARCHIVE_SIZE_MB}MB limit"
                        )
                    handle.write(chunk)
        handle.close()
        if written == 0:
            raise GitHubError(f"GitHub returned an empty archive for {repository}")
    except Exception:
        handle.close()
        try:
            os.remove(handle.name)
        except OSError:
            pass
        raise

    return handle.name
