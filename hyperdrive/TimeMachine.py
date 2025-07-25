from time import sleep
from typing import Union
from datetime import datetime, timedelta, tzinfo
from Constants import TZ, UTC, DATE_FMT, TIME_FMT, PRECISE_TIME_FMT

FlexibleDate = Union[datetime, str]


class TimeTraveller:
    """
    A class to handle time-related operations, such as calculating deltas,
    converting timeframes, and managing sleep intervals.
    """

    def get_delta(
        self,
        d1: FlexibleDate,
        d2: FlexibleDate = datetime.now(),
        format: str = DATE_FMT
    ) -> timedelta:
        """
        Calculate the difference between two dates.

        Args:
            d1 (FlexibleDate):
                The first date, can be a datetime object or a string.
            d2 (FlexibleDate):
                The second date, defaults to the current time.
            format (str):
                The format to parse the date strings, defaults to DATE_FMT.

        Returns:
            timedelta: The absolute difference between the two dates.
        """
        if isinstance(d1, str):
            d1 = datetime.strptime(d1, format)
        if isinstance(d2, str):
            d2 = datetime.strptime(d2, format)

        return abs(d2 - d1)

    def convert_timeframe(self, d1: FlexibleDate, d2: FlexibleDate) -> str:
        """
        Convert two datetime objects
        to a string representation of the timeframe.

        Args:
            d1 (FlexibleDate):
                The first date, can be a datetime object or a string.
            d2 (FlexibleDate):
                The second date, can be a datetime object or a string.

        Returns:
            str: A string representation of the timeframe in days.
        """
        delta = self.get_delta(d1, d2)
        days = delta.days
        return f'{days}d'

    def convert_delta(self, timeframe: str) -> timedelta:
        """
        Convert a timeframe string to a timedelta object.

        Args:
            timeframe (str):
                A string representing the timeframe,
                e.g., '1d', '2w', '3m', '1y'.

        Returns:
            timedelta: A timedelta object representing the specified timeframe.

        Raises:
            ValueError: If the timeframe string is not in a supported format.
        """
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
        self,
        timeframe: str,
        format: str = DATE_FMT
    ) -> tuple[FlexibleDate, FlexibleDate]:
        """
        Convert a timeframe to a start and end date.

        Args:
            timeframe (str):
                A string representing the timeframe,
                e.g., '1d', '2w', '3m', '1y'.
            format (str):
                The format to return the dates in, defaults to DATE_FMT.

        Returns:
            tuple[FlexibleDate, FlexibleDate]:
                A tuple containing the start and end dates as strings.
        """
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
        """
        Get a list of dates in the specified timeframe.
        Args:
            timeframe (str):
                A string representing the timeframe,
                e.g., '1d', '2w', '3m', '1y'.
            format (str):
                The format to return the dates in, defaults to DATE_FMT.

        Returns:
            list[FlexibleDate]: A list of dates in the specified timeframe.
        """
        start, end = self.convert_dates(timeframe, None)
        dates = [start + timedelta(days=x)
                 for x in range(0, (end - start).days + 1)]
        if format:
            dates = [date.strftime(format) for date in dates]
        return dates

    def get_time(self, time: str) -> datetime.time:
        """
        Converts time string to a time object.

        Args:
            time (str):
                A string representing the time, e.g., '14:30', '14:30:00'.

        Returns:
            datetime.time: A time object representing the specified time.
        """
        return datetime.strptime(
            time, TIME_FMT if len(time.split(':')) == 2 else PRECISE_TIME_FMT
        ).time()

    def combine_date_time(self, date: str, time: str) -> datetime:
        """
        Combines date and time into a datetime object.

        Args:
            date (str):
                A string representing the date, e.g., '2025-01-01'.
            time (str):
                A string representing the time, e.g., '14:30', '14:30:00'.

        Returns:
            datetime: A datetime object combining the specified date and time.
        """
        date = datetime.strptime(date, DATE_FMT)
        time = self.get_time(time)
        return date.combine(date, time)

    def get_diff(self, t1: datetime, t2: datetime) -> float:
        """
        Get the difference in seconds between two datetime objects.

        Args:
            t1 (datetime):
                The first datetime object.
            t2 (datetime):
                The second datetime object.

        Returns:
            float: The absolute difference in seconds
            between the two datetimes.
        """
        return abs((t1 - t2).total_seconds())

    def sleep_until(self, time: str, tz: tzinfo = UTC) -> None:
        """
        Sleep until the specified time in the given timezone.

        Args:
            time (str):
                A string representing the time to sleep until, e.g., '14:30'.
            tz (tzinfo):
                The timezone to use for the time, defaults to UTC.

        Returns:
            None: This function does not return anything.
        """
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

    def convert_date(self, date: FlexibleDate) -> str:
        """
        Convert a date to a string in the specified format.

        Args:
            date (FlexibleDate):
                A date that can be a datetime object or a string.

        Returns:
            str: A string representation of the date in the specified format.
        """
        return date if isinstance(date, str) else date.strftime(DATE_FMT)
