import re
import sys
import pytest
from time import time
from datetime import datetime, timedelta
sys.path.append('hyperdrive')
from TimeMachine import TimeTraveller  # noqa autopep8
from Constants import PRECISE_TIME_FMT  # noqa autopep8

traveller = TimeTraveller()


class TestTimeTraveller:
    def test_get_delta(self):
        d1 = '2020-01-01'
        d2 = '2020-01-03'
        assert traveller.get_delta(d1, d2) == timedelta(days=2)

    def test_convert_delta(self):
        assert traveller.convert_delta('1d') == timedelta(days=1)
        assert traveller.convert_delta('3d') == timedelta(days=3)

        assert traveller.convert_delta('1w') == timedelta(days=7)
        assert traveller.convert_delta('3w') == timedelta(days=21)

        assert traveller.convert_delta('1m') == timedelta(days=30)
        assert traveller.convert_delta('3m') == timedelta(days=90)

        assert traveller.convert_delta('1y') == timedelta(days=365)
        assert traveller.convert_delta('3y') == timedelta(days=1095)

        with pytest.raises(ValueError):
            traveller.convert_delta('0')

    def test_convert_dates(self):
        pattern = '[0-9]{4}-[0-9]{2}-[0-9]{2}'
        start, end = traveller.convert_dates('7d')
        assert re.match(pattern, start)
        assert re.match(pattern, end)

    def test_dates_in_range(self):
        assert len(traveller.dates_in_range('1m')) > 20

    def test_combine_date_time(self):
        dt = traveller.combine_date_time('2020-01-02', '09:30')
        assert dt == datetime(2020, 1, 2, 9, 30)

    def test_sleep_until(self):
        num_sec = 5
        tol = 1

        # sched > curr case
        start = time()
        curr = datetime.utcnow()
        sched = curr + timedelta(seconds=num_sec)
        traveller.sleep_until(sched.strftime(PRECISE_TIME_FMT))
        end = time()
        assert (end - start + tol) > num_sec

        # sched < curr case
        start = time()
        curr = datetime.utcnow()
        sched = curr - timedelta(seconds=num_sec)
        traveller.sleep_until(sched.strftime(PRECISE_TIME_FMT))
        end = time()
        assert (end - start) < num_sec
