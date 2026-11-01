"""Bounded retry helper with exponential backoff and jitter."""

from __future__ import annotations

import random
import time
from typing import Callable, Iterable, TypeVar

from .logging import log_warning

T = TypeVar("T")


def with_retries(
    fn: Callable[[], T],
    *,
    tool: str,
    attempts: int = 3,
    base_delay: float = 0.8,
    max_delay: float = 8.0,
    retry_on: Iterable[type[BaseException]] = (Exception,),
) -> T:
    last: BaseException | None = None
    retry_types = tuple(retry_on)
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except retry_types as exc:
            last = exc
            if attempt >= attempts:
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * 0.25)
            log_warning(tool, "retrying after failure", attempt=attempt, delay_round=round(delay, 2))
            time.sleep(delay)
    assert last is not None
    raise last
