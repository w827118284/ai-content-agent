import asyncio

import pytest

from app.services.provider_guard import (
    CircuitBreaker,
    ProviderCircuitOpenError,
    SlidingWindowRateLimiter,
    classify_provider_failure,
    is_breaker_failure,
)


def run(coroutine):
    return asyncio.run(coroutine)


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class StatusError(RuntimeError):
    def __init__(self, status_code: int) -> None:
        super().__init__("unit-test provider failure")
        self.status_code = status_code


@pytest.mark.parametrize(
    ("error", "category", "eligible"),
    [
        (TimeoutError("unit-test timeout"), "timeout", True),
        (ConnectionError("unit-test connection"), "connection", True),
        (StatusError(429), "rate_limit", True),
        (StatusError(503), "server_error", True),
        (StatusError(401), "authentication", False),
        (StatusError(403), "permission", False),
        (StatusError(400), "bad_request", False),
        (StatusError(404), "not_found", False),
        (RuntimeError("unit-test unknown"), "provider_error", False),
    ],
)
def test_provider_failure_classification(error, category, eligible):
    result = classify_provider_failure(error)

    assert result == category
    assert is_breaker_failure(result) is eligible


def test_rate_limiter_blocks_dispatch_until_window_has_capacity():
    async def exercise():
        clock = FakeClock()
        sleep_started = asyncio.Event()
        release_sleep = asyncio.Event()
        delays: list[float] = []
        dispatched: list[str] = []

        async def controlled_sleep(delay: float) -> None:
            delays.append(delay)
            sleep_started.set()
            await release_sleep.wait()
            clock.advance(delay)

        limiter = SlidingWindowRateLimiter(
            2,
            window_seconds=60,
            clock=clock,
            sleep=controlled_sleep,
        )

        async def dispatch(name: str) -> None:
            await limiter.acquire()
            dispatched.append(name)

        await dispatch("A")
        await dispatch("B")
        third = asyncio.create_task(dispatch("C"))
        await sleep_started.wait()

        assert dispatched == ["A", "B"]
        assert delays == [60]

        release_sleep.set()
        await third
        assert dispatched == ["A", "B", "C"]

    run(exercise())


def test_circuit_opens_after_threshold_and_fast_fails_without_dispatch():
    async def exercise():
        breaker = CircuitBreaker(3, 30)
        provider_calls = 0

        async def failed_operation() -> None:
            nonlocal provider_calls
            permit = await breaker.before_call()
            provider_calls += 1
            await breaker.record_failure(permit, eligible=True)

        for _ in range(3):
            await failed_operation()

        assert breaker.state == "open"
        assert breaker.consecutive_failures == 3
        with pytest.raises(ProviderCircuitOpenError):
            await breaker.before_call()
        assert provider_calls == 3

    run(exercise())


def test_permit_becomes_stale_when_another_operation_opens_circuit():
    async def exercise():
        breaker = CircuitBreaker(1, 30)
        queued_permit = await breaker.before_call()
        failing_permit = await breaker.before_call()

        await breaker.record_failure(failing_permit, eligible=True)

        assert breaker.state == "open"
        with pytest.raises(ProviderCircuitOpenError):
            await breaker.validate_before_dispatch(queued_permit)

    run(exercise())


def test_queued_admission_cannot_become_probe_after_circuit_opens():
    async def exercise():
        clock = FakeClock()
        breaker = CircuitBreaker(1, 30, clock=clock)
        queued_admission = await breaker.check_available()
        failing_permit = await breaker.before_call()
        await breaker.record_failure(failing_permit, eligible=True)
        clock.advance(30)

        with pytest.raises(ProviderCircuitOpenError):
            await breaker.before_call(queued_admission)

        fresh_admission = await breaker.check_available()
        probe = await breaker.before_call(fresh_admission)
        assert probe.half_open_probe is True

    run(exercise())


def test_half_open_allows_one_probe_and_success_closes_breaker():
    async def exercise():
        clock = FakeClock()
        breaker = CircuitBreaker(1, 30, clock=clock)
        initial = await breaker.before_call()
        await breaker.record_failure(initial, eligible=True)
        clock.advance(30)

        probe = await breaker.before_call()
        assert probe.half_open_probe is True
        assert breaker.state == "half_open"
        with pytest.raises(ProviderCircuitOpenError):
            await breaker.before_call()

        assert await breaker.record_success(probe) == "closed"
        assert breaker.consecutive_failures == 0
        assert (await breaker.before_call()).half_open_probe is False

    run(exercise())


def test_failed_half_open_probe_reopens_and_restarts_cooldown():
    async def exercise():
        clock = FakeClock()
        breaker = CircuitBreaker(1, 30, clock=clock)
        initial = await breaker.before_call()
        await breaker.record_failure(initial, eligible=True)
        clock.advance(30)

        probe = await breaker.before_call()
        await breaker.record_failure(probe, eligible=True)

        assert breaker.state == "open"
        clock.advance(29)
        with pytest.raises(ProviderCircuitOpenError):
            await breaker.before_call()
        clock.advance(1)
        assert (await breaker.before_call()).half_open_probe is True

    run(exercise())


def test_noneligible_failure_does_not_increment_or_reopen_breaker():
    async def exercise():
        clock = FakeClock()
        breaker = CircuitBreaker(2, 30, clock=clock)
        first = await breaker.before_call()
        await breaker.record_failure(first, eligible=True)
        noneligible = await breaker.before_call()
        await breaker.record_failure(noneligible, eligible=False)
        assert breaker.state == "closed"
        assert breaker.consecutive_failures == 1

        eligible = await breaker.before_call()
        await breaker.record_failure(eligible, eligible=True)
        clock.advance(30)
        probe = await breaker.before_call()
        await breaker.record_failure(probe, eligible=False)

        assert breaker.state == "closed"
        assert breaker.consecutive_failures == 0

    run(exercise())


def test_llm_and_image_breakers_are_independent():
    async def exercise():
        llm_breaker = CircuitBreaker(1, 30)
        image_breaker = CircuitBreaker(1, 30)
        llm_call = await llm_breaker.before_call()
        await llm_breaker.record_failure(llm_call, eligible=True)

        assert llm_breaker.state == "open"
        assert image_breaker.state == "closed"
        assert (await image_breaker.before_call()).half_open_probe is False

    run(exercise())
