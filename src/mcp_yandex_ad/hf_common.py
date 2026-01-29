"""Human-friendly (HF) helpers shared across Direct and Metrica."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Iterable


class HFError(RuntimeError):
    """Human-friendly layer error (actionable)."""


@dataclass(frozen=True)
class ResolveResult:
    ids: list[int]
    matches: list[dict[str, Any]]
    ambiguous: bool


def ensure_hf_enabled(config: Any) -> None:
    if not getattr(config, "hf_enabled", True):
        raise HFError("HF tools are disabled (HF_ENABLED=false).")


def ensure_hf_write_enabled(config: Any) -> None:
    if not getattr(config, "hf_write_enabled", False):
        raise HFError("HF write tools are disabled (HF_WRITE_ENABLED=false).")


def ensure_hf_destructive_enabled(config: Any) -> None:
    if not getattr(config, "hf_destructive_enabled", False):
        raise HFError("HF destructive tools are disabled (HF_DESTRUCTIVE_ENABLED=false).")


def should_apply(args: dict[str, Any]) -> bool:
    return bool(args.get("apply", False))


def hf_payload(
    *,
    tool: str,
    status: str,
    preview: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    message: str | None = None,
    choices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"tool": tool, "status": status}
    if message:
        payload["message"] = message
    if preview is not None:
        payload["preview"] = preview
    if result is not None:
        payload["result"] = result
    if choices is not None:
        payload["choices"] = choices
    return payload


def today_plus(days: int) -> str:
    return str(dt.date.today() + dt.timedelta(days=days))


def micros_from_rub(value: float | int) -> int:
    return int(round(float(value) * 1_000_000))


def dedupe_ints(values: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(int(v) for v in values))

