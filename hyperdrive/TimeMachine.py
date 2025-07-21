from time import sleep
from typing import Union
from datetime import datetime, timedelta
from Constants import TZ, UTC, DATE_FMT, TIME_FMT, PRECISE_TIME_FMT

FlexibleDate = Union[datetime, str]


class TimeTraveller:
    def get_delta(
        self,
        d1: FlexibleDate,
        d2: FlexibleDate = datetime.now(),
        format: str = DATE_FMT
    ) -> timedelta:
        """Calculate the difference between two dates."""
        if isinstance(d1, str):
            d1 = datetime.strptime(d1, format)
        if isinstance(d2, str):
            d2 = datetime.strptime(d2, format)

        return abs(d2 - d1)

    def convert_timeframe(self, d1: FlexibleDate, d2: FlexibleDate) -> str:
        """Convert two datetime objects to a string representation of the timeframe."""
        delta = self.get_delta(d1, d2)
        days = delta.days
        return f'{days}d'

    def convert_delta(self, timeframe: str) -> timedelta:
        """Convert a timeframe string to a timedelta object."""
        if timeframe == 'max':
            return timedelta(days=36500)

        periods = {'y': 365, 'm': 30, 'w': 7, 'd': 1}
        period = 'y'
        idx = -1

        for curr_period in periods:
            idx = timeframe.find(curr_period)
            if idx != -1:
                period = curr_period
                break

        if idx == -1:
            supported = ', '.join(list(periods))
            error_msg = f'Only certain suffixes ({supported}) are supported.'
            raise ValueError(error_msg)

        num = int(timeframe[:idx])
        days = periods[period] * num
        delta = timedelta(days=days)

        return delta

    def convert_dates(
            self, timeframe: str, format: str = DATE_FMT) -> FlexibleDate:
        """Convert a timeframe to a start and end date."""
        # if timeframe='max': timeframe = '25y'
        end = datetime.now(TZ) - self.convert_delta('1d')
        delta = self.convert_delta(timeframe) - self.convert_delta('1d')
        start = end - delta
        if format:
            start = start.strftime(format)
            end = end.strftime(format)
        return start, end

    def dates_in_range(self, timeframe: str, format: str = DATE_FMT
                       ) -> list[FlexibleDate]:
        """Get a list of dates in the specified timeframe."""
        start, end = self.convert_dates(timeframe, None)
        dates = [start + timedelta(days=x)
                 for x in range(0, (end - start).days + 1)]
        if format:
            dates = [date.strftime(format) for date in dates]
        return dates

    def get_time(self, time):
        """Converts time string to a time object."""
        return datetime.strptime(
            time, TIME_FMT if len(time.split(':')) == 2 else PRECISE_TIME_FMT
        ).time()

    def combine_date_time(self, date, time):
        """Combines date and time into a datetime object."""
        date = datetime.strptime(date, DATE_FMT)
        time = self.get_time(time)
        return date.combine(date, time)

    def get_diff(self, t1, t2):
        """Get the difference in seconds between two datetime objects."""
        return abs((t1 - t2).total_seconds())

    def sleep_until(self, time, tz=UTC):
        """Sleep until the specified time in the given timezone."""
        # time could be "00:00"
        curr = datetime.now(tz)
        prev_sched = datetime.combine(curr.date(), self.get_time(time), tz)
        next_sched = prev_sched + timedelta(days=1)

        prev_diff = self.get_diff(curr, prev_sched)
        next_diff = self.get_diff(curr, next_sched)

        sched = next_sched if next_diff < prev_diff else prev_sched
        diff = self.get_diff(curr, sched) if sched > curr else 0

        while diff > 0:
            curr = datetime.now(tz)
            diff = self.get_diff(curr, sched) if sched > curr else 0
            sleep(diff)

    def convert_date(self, date):
        """Convert a date to a string in the specified format."""
        return date if isinstance(date, str) else date.strftime(DATE_FMT)
