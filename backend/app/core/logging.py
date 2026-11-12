"""Structured JSON logging with secret redaction.

Every log record passes through :class:`RedactingFilter`, which masks values of
sensitive keys (tokens, api keys, passwords, account identifiers) and any
string that looks like a bearer token.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any

SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "access_token",
    "accesstoken",
    "authorization",
    "trading_id",
    "tradingid",
    "investor_code",
    "account_code",
    "mobile",
    "email",
}
_BEARER_RE = re.compile(r"(?i)bearer\s+[a-z0-9\-\._~\+/]+=*")
_JWT_RE = re.compile(r"eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("***" if str(k).lower() in SENSITIVE_KEYS else redact(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = _BEARER_RE.sub("Bearer ***", value)
        return _JWT_RE.sub("***", value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            record.args = tuple(redact(a) for a in record.args) if isinstance(
                record.args, tuple
            ) else redact(record.args)
        extra = getattr(record, "ctx", None)
        if extra is not None:
            record.ctx = redact(extra)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        ctx = getattr(record, "ctx", None)
        if ctx:
            payload["ctx"] = ctx
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    # Quiet noisy libraries
    logging.getLogger("uvicorn.access").setLevel("WARNING")
    logging.getLogger("httpx").setLevel("WARNING")


def get_logger(name: str) -> logging.LoggerAdapter[logging.Logger]:
    class _Adapter(logging.LoggerAdapter[logging.Logger]):
        def process(self, msg: Any, kwargs: Any) -> tuple[Any, Any]:
            ctx = {k: kwargs.pop(k) for k in list(kwargs) if k not in ("exc_info", "stack_info", "extra")}
            if ctx:
                kwargs.setdefault("extra", {})["ctx"] = redact(ctx)
            return msg, kwargs

    return _Adapter(logging.getLogger(name), {})
