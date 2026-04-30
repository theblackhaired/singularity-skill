"""Low-level HTTP client for singularity skill."""

import json
import ssl
import sys
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
import re as _re

__all__ = ["SingularityClient"]


class SingularityClient:
    """Low-level HTTP client with Bearer auth, SSL context and retry."""

    RETRYABLE_CODES = {429, 500, 502, 503, 504}

    def __init__(self, base_url: str, token: str,
                 max_retries: int = 3, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.max_retries = max_retries
        self.timeout = timeout

        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        self._ssl_ctx = ssl.create_default_context()

    # -- internal ----------------------------------------------------------

    def _request(self, method: str, path: str, params: dict = None,
                 body: dict = None):
        url = self.base_url + path
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url += "?" + urlencode(clean)

        data = json.dumps(body).encode("utf-8") if body is not None else None

        for attempt in range(1, self.max_retries + 1):
            try:
                req = Request(url, data=data, headers=self._headers,
                              method=method)
                with urlopen(req, context=self._ssl_ctx,
                             timeout=self.timeout) as resp:
                    raw = resp.read()
                    if not raw:
                        return {}
                    return json.loads(raw.decode("utf-8"))
            except HTTPError as exc:
                if exc.code in self.RETRYABLE_CODES and attempt < self.max_retries:
                    delay = 2 ** (attempt - 1)
                    print(f"HTTP {exc.code}, retry in {delay}s "
                          f"({attempt}/{self.max_retries})...",
                          file=sys.stderr)
                    time.sleep(delay)
                    continue
                err_body = ""
                try:
                    err_body = exc.read().decode("utf-8", errors="replace")
                except (OSError, AttributeError, UnicodeDecodeError):
                    pass
                # Security: truncate + redact (security-review MEDIUM finding).
                # Defends against backend that echoes Authorization header in error
                # bodies вЂ” without this guard, the token would propagate into
                # warnings -> cache JSON -> stderr.
                err_body = err_body[:500]
                import re as _re
                err_body = _re.sub(
                    r"(?i)(bearer\s+)\S+", r"\1***", err_body
                )
                err_body = _re.sub(
                    r"(?i)(authorization[\"'\s:=]+)[^\s\"',}]+",
                    r"\1***", err_body
                )
                # Try to parse Singularity error format {errors:[{code,message}]}
                try:
                    err_json = json.loads(err_body)
                    errors = err_json.get("errors", [])
                    if errors:
                        msgs = "; ".join(
                            f"[{e.get('code','')}] {e.get('message','')}"
                            for e in errors
                        )
                        raise RuntimeError(
                            f"HTTP {exc.code} on {method} {url}: {msgs}"
                        ) from exc
                except (json.JSONDecodeError, AttributeError):
                    pass
                raise RuntimeError(
                    f"HTTP {exc.code} {exc.reason} on {method} {url}\n"
                    f"{err_body}"
                ) from exc
            except URLError as exc:
                if attempt < self.max_retries:
                    delay = 2 ** (attempt - 1)
                    print(f"Network error, retry in {delay}s "
                          f"({attempt}/{self.max_retries})...",
                          file=sys.stderr)
                    time.sleep(delay)
                    continue
                raise

        # T8.1 вЂ” explicit guard against silent None return when max_retries < 1.
        # If the for-loop exits without success / raise (only possible at
        # max_retries=0 with retryable HTTP), raise instead of returning None.
        raise RuntimeError(
            f"_request exited without success: {method} {url} "
            f"(max_retries={self.max_retries})"
        )

    # -- public verbs -------------------------------------------------------

    def get(self, path: str, params: dict = None):
        return self._request("GET", path, params=params)

    def post(self, path: str, data: dict = None):
        return self._request("POST", path, body=data)

    def patch(self, path: str, data: dict = None):
        return self._request("PATCH", path, body=data)

    def delete(self, path: str, params: dict = None):
        return self._request("DELETE", path, params=params)
