"""A tiny fake of the parts of aiohttp.ClientSession the drivers use.

(aioresponses does not support aiohttp >= 3.13 yet, and this keeps tests explicit.)
Responses are consumed in the order they were added per matching URL, like aioresponses.
"""

from __future__ import annotations

import json as _json
import re
from typing import Any
from urllib.parse import urlencode

from multidict import CIMultiDict


class FakeResponse:
    def __init__(self, status: int, body: str, headers: dict[str, str] | None) -> None:
        self.status = status
        self._body = body
        self.headers = CIMultiDict(headers or {})

    async def text(self) -> str:
        return self._body


class _Ctx:
    def __init__(self, result: FakeResponse | BaseException) -> None:
        self._result = result

    async def __aenter__(self) -> FakeResponse:
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeSession:
    def __init__(self) -> None:
        self.routes: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def add(
        self,
        method: str,
        url: str | re.Pattern[str],
        *,
        status: int = 200,
        payload: Any = None,
        body: str = "",
        headers: dict[str, str] | None = None,
        exception: BaseException | None = None,
        repeat: bool = False,
    ) -> None:
        if payload is not None:
            body = _json.dumps(payload)
        self.routes.append(
            {
                "method": method,
                "url": url,
                "status": status,
                "body": body,
                "headers": headers,
                "exc": exception,
                "repeat": repeat,
            }
        )

    def get_(self, url, **kw):  # helpers for readability in tests
        self.add("GET", url, **kw)

    def post_(self, url, **kw):
        self.add("POST", url, **kw)

    def _handle(self, method: str, url: str, params: dict[str, Any] | None = None, **kw: Any) -> _Ctx:
        full = f"{url}?{urlencode(params)}" if params else url
        self.calls.append((method, full, kw))
        for route in self.routes:
            target = route["url"]
            hit = target.fullmatch(full) if isinstance(target, re.Pattern) else target == full
            if route["method"] == method and hit:
                if not route["repeat"]:
                    self.routes.remove(route)
                if route["exc"] is not None:
                    return _Ctx(route["exc"])
                return _Ctx(FakeResponse(route["status"], route["body"], route["headers"]))
        raise AssertionError(f"unexpected request {method} {full}")

    def get(self, url: str, **kw: Any) -> _Ctx:
        return self._handle("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> _Ctx:
        return self._handle("POST", url, **kw)

    def request(self, method: str, url: str, **kw: Any) -> _Ctx:
        return self._handle(method, url, **kw)
