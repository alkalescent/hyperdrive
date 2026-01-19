import re
from datetime import datetime, timedelta

from Constants import FEW, POLY_CRYPTO_SYMBOLS, POLY_FREE_DELAY
from DataSource import MarketData


class Flow:
    def get_workflow_start_time(self, workflow_name):
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

    def is_workflow_running(self, workflow_name, buffer_min=30):
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

    def is_any_workflow_running(self):
        workflows = ["ohlc", "intraday", "dividends", "splits"]
        return any(self.is_workflow_running(workflow) for workflow in workflows)
