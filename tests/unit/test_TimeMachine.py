"""Tests for the TimeMachine module."""

import re
from datetime import datetime, timedelta, timezone
from time import time

import pytest

from hyperdrive.Constants import PRECISE_TIME_FMT
from hyperdrive.TimeMachine import TimeTraveller

traveller = TimeTraveller()


class TestTimeTraveller:
    """Tests for the TimeTraveller time utility class."""

    def test_get_delta(self) -> None:
        """Test calculating time delta between two dates."""
        d1 = "2020-01-01"
        d2 = "2020-01-03"
        assert traveller.get_delta(d1, d2) == timedelta(days=2)

    def test_convert_delta(self) -> None:
        """Test converting timeframe strings to timedelta."""
        assert traveller.convert_delta("1d") == timedelta(days=1)
        assert traveller.convert_delta("3d") == timedelta(days=3)

        assert traveller.convert_delta("1w") == timedelta(days=7)
        assert traveller.convert_delta("3w") == timedelta(days=21)

        assert traveller.convert_delta("1m") == timedelta(days=30)
        assert traveller.convert_delta("3m") == timedelta(days=90)

        assert traveller.convert_delta("1y") == timedelta(days=365)
        assert traveller.convert_delta("3y") == timedelta(days=1095)

        with pytest.raises(ValueError):
            traveller.convert_delta("0")

    def test_convert_dates(self) -> None:
        """Test converting timeframe to date range strings."""
        pattern = "[0-9]{4}-[0-9]{2}-[0-9]{2}"
        start, end = traveller.convert_dates("7d")
        assert re.match(pattern, str(start))
        assert re.match(pattern, str(end))

    def test_dates_in_range(self) -> None:
        """Test getting list of dates in a timeframe."""
        assert len(traveller.dates_in_range("1m")) > 20

    def test_combine_date_time(self) -> None:
        """Test combining date and time strings into datetime."""
        dt = traveller.combine_date_time("2020-01-02", "09:30")
        assert dt == datetime(2020, 1, 2, 9, 30)

    def test_sleep_until(self) -> None:
        """Test sleeping until a scheduled time."""
        num_sec = 5
        tol = 1

        # sched > curr case
        start = time()
        curr = datetime.now(timezone.utc)
        sched = curr + timedelta(seconds=num_sec)
        traveller.sleep_until(sched.strftime(PRECISE_TIME_FMT))
        end = time()
        assert (end - start + tol) > num_sec

        # sched < curr case
        start = time()
        curr = datetime.now(timezone.utc)
        sched = curr - timedelta(seconds=num_sec)
        traveller.sleep_until(sched.strftime(PRECISE_TIME_FMT))
        end = time()
        assert (end - start) < num_sec

    def test_get_delta_with_datetime(self) -> None:
        """Test get_delta with datetime objects instead of strings."""
        d1 = datetime(2020, 1, 1)
        d2 = datetime(2020, 1, 5)
        assert traveller.get_delta(d1, d2) == timedelta(days=4)

    def test_get_delta_no_d2(self) -> None:
        """Test get_delta with d2 defaulting to now."""
        d1 = datetime.now() - timedelta(days=10)
        delta = traveller.get_delta(d1)
        # Should be approximately 10 days
        assert delta.days >= 9 and delta.days <= 11

    def test_convert_timeframe(self) -> None:
        """Test convert_timeframe returns days string."""
        d1 = "2020-01-01"
        d2 = "2020-01-10"
        result = traveller.convert_timeframe(d1, d2)
        assert result == "9d"

    def test_get_time(self) -> None:
        """Test get_time parsing."""
        time_obj = traveller.get_time("14:30")
        assert time_obj.hour == 14
        assert time_obj.minute == 30

    def test_get_time_precise(self) -> None:
        """Test get_time with seconds."""
        time_obj = traveller.get_time("14:30:45")
        assert time_obj.hour == 14
        assert time_obj.minute == 30
        assert time_obj.second == 45

    def test_get_diff(self) -> None:
        """Test get_diff between two datetimes."""
        t1 = datetime(2020, 1, 1, 0, 0, 0)
        t2 = datetime(2020, 1, 1, 0, 1, 0)  # 1 minute later
        diff = traveller.get_diff(t1, t2)
        assert diff == 60.0  # 60 seconds

    def test_convert_date_string(self) -> None:
        """Test convert_date with string input."""
        date_str = "2020-01-01"
        result = traveller.convert_date(date_str)
        assert result == "2020-01-01"

    def test_convert_date_datetime(self) -> None:
        """Test convert_date with datetime input."""
        date_obj = datetime(2020, 1, 15)
        result = traveller.convert_date(date_obj)
        assert result == "2020-01-15"
