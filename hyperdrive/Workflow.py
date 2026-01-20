"""Workflow scheduling utilities for GitHub Actions coordination."""

import re
from datetime import datetime, timedelta

from .Constants import FEW, POLY_CRYPTO_SYMBOLS, POLY_FREE_DELAY
from .DataSource import MarketData


class Flow:
    """GitHub Actions workflow scheduling coordinator.

    Provides methods to determine workflow timing and check if
    workflows are currently running based on cron schedules.
    """

    def get_workflow_start_time(self, workflow_name: str) -> datetime:
        """Parse the scheduled start time from a workflow file.

        Args:
            workflow_name: Name of the workflow file (without .yml extension).

        Returns:
            The datetime when the workflow is scheduled to start.

        Raises:
            AttributeError: If the workflow doesn't have a scheduled cron job.
        """
        with open(f".github/workflows/{workflow_name}.yml") as file:
            workflow_content = file.read()
        line_pattern = '- cron: "(.*)"'
        try:
            cron_line = re.search(line_pattern, workflow_content).group(1)
        except AttributeError:
            raise AttributeError(
                f"{workflow_name}.yml doesn't have a scheduled cron job"
            ) from None

        now = datetime.utcnow()
        default_times = [now.minute, now.hour, now.day, now.month]
        times = [
            default_times[idx] if time == "*" else int(time)
            for idx, time in enumerate(cron_line.split(" ")[:-1])
        ]

        minute, hour, day, month = times
        return datetime(now.year, month, day, hour, minute)

    def is_workflow_running(self, workflow_name: str, buffer_min: int = 30) -> bool:
        """Check if a workflow is currently running.

        Estimates workflow duration based on the number of symbols to process
        and checks if current time falls within the execution window.

        Args:
            workflow_name: Name of the workflow to check.
            buffer_min: Buffer time in minutes around the workflow window.

        Returns:
            True if the workflow is likely running, False otherwise.
        """
        md = MarketData()
        start_time = self.get_workflow_start_time(workflow_name)
        num_stock = len(md.get_symbols())
        num_crypto = len(POLY_CRYPTO_SYMBOLS)
        duration = timedelta(seconds=POLY_FREE_DELAY)
        now = datetime.utcnow()

        if workflow_name in {"ohlc", "intraday"}:
            duration *= (num_stock + num_crypto) * FEW
        elif workflow_name in {"dividends", "splits"}:
            duration *= num_stock
        else:
            return False

        buffer = timedelta(minutes=buffer_min)
        return now < start_time + duration + buffer and now > start_time - buffer

    def is_any_workflow_running(self) -> bool:
        """Check if any data collection workflow is currently running.

        Returns:
            True if any workflow (ohlc, intraday, dividends, splits) is running.
        """
        workflows = ["ohlc", "intraday", "dividends", "splits"]
        return any(self.is_workflow_running(workflow) for workflow in workflows)
