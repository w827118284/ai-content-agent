import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

import httpx
from openai import APIConnectionError, APITimeoutError


ProviderFailureCategory = Literal[
    "timeout",
    "connection",
    "rate_limit",
    "server_error",
    "authentication",
    "permission",
    "bad_request",
    "not_found",
    "provider_error",
    "circuit_open",
]
CircuitState = Literal["closed", "open", "half_open"]
MonotonicClock = Callable[[], float]
AsyncSleep = Callable[[float], Awaitable[None]]

BREAKER_FAILURE_CATEGORIES = frozenset(
    {"timeout", "connection", "rate_limit", "server_error"}
)


def classify_provider_failure(exc: Exception) -> ProviderFailureCategory:
    if isinstance(exc, (APITimeoutError, httpx.TimeoutException, TimeoutError)):
        return "timeout"
    if isinstance(
        exc,
        (APIConnectionError, httpx.NetworkError, ConnectionError),
    ):
        return "connection"

    status_code = getattr(exc, "status_code", None)
    if not isinstance(status_code, int):
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    if status_code == 429:
        return "rate_limit"
    if isinstance(status_code, int) and 500 <= status_code <= 599:
        return "server_error"
    if status_code == 401:
        return "authentication"
    if status_code == 403:
        return "permission"
    if status_code == 404:
        return "not_found"
    if isinstance(status_code, int) and 400 <= status_code <= 499:
        return "bad_request"
    return "provider_error"


def is_breaker_failure(category: ProviderFailureCategory) -> bool:
    return category in BREAKER_FAILURE_CATEGORIES


class SlidingWindowRateLimiter:
    def __init__(
        self,
        requests_per_window: int,
        *,
        window_seconds: float = 60.0,
        clock: MonotonicClock = time.monotonic,
        sleep: AsyncSleep = asyncio.sleep,
    ) -> None:
        if requests_per_window < 1:
            raise ValueError("requests_per_window must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.requests_per_window = requests_per_window
        self.window_seconds = window_seconds
        self._clock = clock
        self._sleep = sleep
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = self._clock()
                cutoff = now - self.window_seconds
                while self._timestamps and self._timestamps[0] <= cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) < self.requests_per_window:
                    self._timestamps.append(now)
                    return
                delay = max(
                    self._timestamps[0] + self.window_seconds - now,
                    0.0,
                )
            await self._sleep(delay)


class ProviderCircuitOpenError(RuntimeError):
    """Raised when a provider operation is rejected before dispatch."""


@dataclass(frozen=True, slots=True)
class CircuitPermit:
    half_open_probe: bool
    generation: int


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int,
        cooldown_seconds: float,
        *,
        clock: MonotonicClock = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._state: CircuitState = "closed"
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False
        self._generation = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    async def check_available(self) -> int:
        """Fast-fail an operation without reserving a HALF_OPEN probe."""
        async with self._lock:
            if self._state == "closed":
                return self._generation
            if self._state == "open":
                assert self._opened_at is not None
                if self._clock() - self._opened_at >= self.cooldown_seconds:
                    return self._generation
            raise ProviderCircuitOpenError("provider circuit is unavailable")

    async def before_call(
        self,
        admission_generation: int | None = None,
    ) -> CircuitPermit:
        """Reserve permission immediately before a provider dispatch."""
        async with self._lock:
            if (
                admission_generation is not None
                and admission_generation != self._generation
            ):
                raise ProviderCircuitOpenError(
                    "provider circuit admission is stale"
                )
            if self._state == "closed":
                return CircuitPermit(
                    half_open_probe=False,
                    generation=self._generation,
                )

            if self._state == "open":
                assert self._opened_at is not None
                if self._clock() - self._opened_at < self.cooldown_seconds:
                    raise ProviderCircuitOpenError("provider circuit is open")
                self._state = "half_open"
                self._half_open_in_flight = True
                return CircuitPermit(
                    half_open_probe=True,
                    generation=self._generation,
                )

            raise ProviderCircuitOpenError("provider circuit probe is in progress")

    async def validate_before_dispatch(self, permit: CircuitPermit) -> None:
        """Reject a permit made stale while waiting or backing off."""
        async with self._lock:
            if permit.half_open_probe:
                if (
                    self._state == "half_open"
                    and self._half_open_in_flight
                    and permit.generation == self._generation
                ):
                    return
            elif (
                self._state == "closed"
                and permit.generation == self._generation
            ):
                return
            raise ProviderCircuitOpenError("provider circuit permit is stale")

    async def record_success(self, permit: CircuitPermit) -> CircuitState:
        async with self._lock:
            if permit.half_open_probe:
                if (
                    self._state == "half_open"
                    and self._half_open_in_flight
                    and permit.generation == self._generation
                ):
                    self._close()
            elif (
                self._state == "closed"
                and permit.generation == self._generation
            ):
                self._consecutive_failures = 0
            return self._state

    async def record_failure(
        self,
        permit: CircuitPermit,
        *,
        eligible: bool,
    ) -> CircuitState:
        async with self._lock:
            if permit.half_open_probe:
                if (
                    self._state == "half_open"
                    and self._half_open_in_flight
                    and permit.generation == self._generation
                ):
                    if eligible:
                        self._open()
                    else:
                        self._close()
                return self._state

            if (
                eligible
                and self._state == "closed"
                and permit.generation == self._generation
            ):
                self._consecutive_failures += 1
                if self._consecutive_failures >= self.failure_threshold:
                    self._open()
            return self._state

    async def cancel_call(self, permit: CircuitPermit) -> CircuitState:
        async with self._lock:
            if (
                permit.half_open_probe
                and self._state == "half_open"
                and self._half_open_in_flight
                and permit.generation == self._generation
            ):
                self._open()
            return self._state

    def _open(self) -> None:
        self._generation += 1
        self._state = "open"
        self._opened_at = self._clock()
        self._half_open_in_flight = False

    def _close(self) -> None:
        self._state = "closed"
        self._opened_at = None
        self._half_open_in_flight = False
        self._consecutive_failures = 0
