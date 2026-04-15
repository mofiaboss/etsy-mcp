"""Unit tests for etsy_core.rate_limiter (token bucket + daily counter)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from etsy_core.rate_limiter import DailyBudgetExceeded, DailyCounter, _TokenBucket


class TestTokenBucket:
    @pytest.mark.asyncio
    async def test_acquire_within_capacity_is_immediate(self):
        bucket = _TokenBucket(capacity=10, refill_rate=10.0)
        loop = asyncio.get_event_loop()
        start = loop.time()
        for _ in range(10):
            await bucket.acquire()
        elapsed = loop.time() - start
        # 10 immediate acquisitions should take well under 100ms
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_acquire_beyond_capacity_waits(self):
        bucket = _TokenBucket(capacity=2, refill_rate=10.0)
        await bucket.acquire()
        await bucket.acquire()  # bucket empty
        loop = asyncio.get_event_loop()
        start = loop.time()
        await bucket.acquire()  # must wait ~0.1s
        elapsed = loop.time() - start
        assert elapsed >= 0.05  # at least 50ms wait

    @pytest.mark.asyncio
    async def test_concurrent_acquire_serializes(self):
        bucket = _TokenBucket(capacity=3, refill_rate=10.0)
        # Fire 6 concurrent acquires — first 3 immediate, next 3 paced
        results = await asyncio.gather(*[bucket.acquire() for _ in range(6)])
        assert len(results) == 6  # all completed without exception


class TestDailyCounter:
    @pytest.mark.asyncio
    async def test_increment_basic(self, tmp_path: Path):
        counter = DailyCounter(budget=100, persist_path=tmp_path / "c.json")
        await counter.increment()
        assert counter.remaining() == 99

    @pytest.mark.asyncio
    async def test_persist_and_load(self, tmp_path: Path):
        path = tmp_path / "counter.json"
        c1 = DailyCounter(budget=100, persist_path=path)
        for _ in range(10):
            await c1.increment()
        # _persist runs every 10 increments
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["count"] == 10

        # New instance loads existing count
        c2 = DailyCounter(budget=100, persist_path=path)
        assert c2.remaining() == 90

    @pytest.mark.asyncio
    async def test_load_resets_on_prior_day(self, tmp_path: Path):
        path = tmp_path / "counter.json"
        # Write a counter file dated to a prior day
        path.write_text(json.dumps({"date": "1999-01-01", "count": 50}))
        counter = DailyCounter(budget=100, persist_path=path)
        # Should reset to 0 because the date doesn't match today
        assert counter.remaining() == 100

    @pytest.mark.asyncio
    async def test_warns_at_80_percent(self, tmp_path: Path, caplog):
        counter = DailyCounter(budget=10, persist_path=tmp_path / "c.json")
        import logging

        caplog.set_level(logging.WARNING)
        for _ in range(8):
            await counter.increment()
        warned = [r for r in caplog.records if "80%" in r.message or "budget" in r.message.lower()]
        assert warned, "Expected a warning at 80% threshold"

    @pytest.mark.asyncio
    async def test_refuses_at_95_percent(self, tmp_path: Path):
        counter = DailyCounter(budget=20, persist_path=tmp_path / "c.json")
        for _ in range(18):
            await counter.increment()
        # Next increment hits 95% → refuse
        with pytest.raises(DailyBudgetExceeded):
            await counter.increment()

    @pytest.mark.asyncio
    async def test_corrupt_persist_file_resets_to_zero(self, tmp_path: Path):
        path = tmp_path / "c.json"
        path.write_text("not json {{")
        counter = DailyCounter(budget=100, persist_path=path)
        assert counter.remaining() == 100

    def test_reset_at_utc_returns_iso(self, tmp_path: Path):
        counter = DailyCounter(budget=100, persist_path=tmp_path / "c.json")
        result = counter.reset_at_utc()
        assert "T00:00:00" in result
        assert result.endswith("Z")
