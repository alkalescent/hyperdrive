"""Fill empty FIRE spreadsheet cells, including blended validator rewards."""

from __future__ import annotations

import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import gspread
import pandas as pd
import requests

from hyperdrive.Broker import Robinhood
from hyperdrive.Constants import CLOSE, DATE_FMT, ETH_USD, TIME
from hyperdrive.DataSource import Polygon
from hyperdrive.Staking import (
    RewardProviderError,
    RewardWindow,
    StakingRewards,
)

LOGGER = logging.getLogger(__name__)


def calculate_options_value(options: pd.DataFrame, start: str, end: str) -> float:
    """Calculate realized options value for a half-open date range."""
    if options.empty:
        return 0.0
    selected = options[(options["updated_at"] >= start) & (options["updated_at"] < end)]
    value = 0.0
    for _, order in selected.iterrows():
        premium = float(order["premium"])
        if order["direction"] == "debit":
            value -= premium
            continue
        legs = order.get("legs", [])
        expiration = legs[0].get("expiration_date") if legs else None
        if expiration:
            order_date = pd.to_datetime(order["updated_at"])
            if (pd.to_datetime(expiration) - order_date).days > 12:
                continue
        value += premium
    return value


def _is_blank(value: Any) -> bool:
    """Return whether a spreadsheet cell is empty."""
    return value == "" or pd.isna(value)


def _price_periods(windows: list[RewardWindow]) -> dict[RewardWindow, Decimal]:
    """Return complete average ETH/USD closes for each reward window."""
    if not windows:
        return {}
    earliest = min(window.start for window in windows)
    days = (datetime.now(UTC).date() - earliest.date()).days + 2
    prices = Polygon().get_ohlc(ETH_USD, f"{max(days, 1)}d")
    if prices.empty:
        raise RuntimeError("Polygon returned no ETH/USD prices")
    timestamps = pd.to_datetime(prices[TIME], utc=True)
    averages: dict[RewardWindow, Decimal] = {}
    for window in windows:
        mask = (timestamps >= window.start) & (timestamps < window.end)
        closes = prices.loc[mask, CLOSE]
        expected = {
            (window.start + timedelta(days=offset)).date()
            for offset in range((window.end - window.start).days)
        }
        if set(timestamps.loc[mask].dt.date) != expected or len(closes) != len(
            expected
        ):
            raise RuntimeError(f"Incomplete ETH/USD coverage for {window}")
        averages[window] = sum(
            (Decimal(str(value)) for value in closes), Decimal(0)
        ) / Decimal(len(closes))
    return averages


def _window(end: pd.Timestamp) -> RewardWindow:
    """Build the seven-day UTC window ending on a spreadsheet date."""
    end_utc = end.to_pydatetime().replace(tzinfo=UTC)
    return RewardWindow(end_utc - timedelta(weeks=1), end_utc)


def main() -> None:
    """Compute every resolved value, then update the spreadsheet."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    dry_run = (
        "--dry-run" in sys.argv
        or os.environ.get("SPREADSHEET_DRY_RUN", "false").lower() == "true"
    )

    worksheet = gspread.service_account().open("FIRE").get_worksheet(0)
    if worksheet:
        frame = pd.DataFrame(worksheet.get_all_records())
    else:
        raise RuntimeError("FIRE worksheet 0 does not exist")
    columns = list(frame.columns)
    editable = columns[: columns.index("Total")]
    frame["Date"] = pd.to_datetime(frame["Date"])
    today = datetime.now(UTC).date()
    targets = frame[
        (frame["Date"].dt.date < today) & frame[editable].map(_is_blank).any(axis=1)
    ]
    if targets.empty:
        LOGGER.info("No spreadsheet cells need updating")
        return

    column_numbers = {name: index + 1 for index, name in enumerate(columns)}
    writes: list[tuple[int, int, int]] = []
    row_offset = 2

    dividends = pd.DataFrame()
    options = pd.DataFrame()
    needs_robinhood = any(
        _is_blank(row[column])
        for _, row in targets.iterrows()
        for column in ("Dividends", "Options")
    )
    robinhood_available = False
    if needs_robinhood:
        try:
            robinhood = Robinhood()
            dividends = pd.DataFrame(robinhood.get_dividends())
            options = pd.DataFrame(robinhood.get_options())
            if not options.empty:
                options = options[options["state"] == "filled"].copy()
                options["updated_at"] = pd.to_datetime(
                    options["updated_at"]
                ).dt.strftime(DATE_FMT)
            robinhood_available = True
        except Exception as error:
            LOGGER.error("Robinhood data is unavailable: %s", error)

    for index, row in targets.iterrows():
        end = pd.Timestamp(row["Date"])
        start = end - timedelta(weeks=1)
        start_text = start.strftime(DATE_FMT)
        end_text = end.strftime(DATE_FMT)
        sheet_row = int(index) + row_offset
        if _is_blank(row["Dividends"]) and robinhood_available:
            value = 0
            if not dividends.empty:
                selected = dividends[
                    (dividends["payable_date"] >= start_text)
                    & (dividends["payable_date"] < end_text)
                ]
                value = round(selected["amount"].astype(float).sum())
            writes.append((sheet_row, column_numbers["Dividends"], value))
        if _is_blank(row["Options"]) and robinhood_available:
            value = round(calculate_options_value(options, start_text, end_text))
            writes.append((sheet_row, column_numbers["Options"], value))

    crypto_rows = [
        (int(index), _window(pd.Timestamp(row["Date"])))
        for index, row in targets.iterrows()
        if _is_blank(row["Crypto"])
    ]
    if crypto_rows:
        windows = [window for _, window in crypto_rows]
        try:
            estimates = StakingRewards().fetch(windows)
            prices = _price_periods(list(estimates))
        except (RewardProviderError, RuntimeError, requests.RequestException) as error:
            LOGGER.error("Crypto cells remain empty: %s", error)
            estimates = {}
            prices = {}
        for index, window in crypto_rows:
            estimate = estimates.get(window)
            price = prices.get(window)
            if estimate and price:
                usd = (estimate.eth * price).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
                LOGGER.info(
                    "Crypto %s: %s ETH from %s, %s USD",
                    window.end.date(),
                    estimate.eth,
                    ", ".join(estimate.sources),
                    usd,
                )
                writes.append((index + row_offset, column_numbers["Crypto"], int(usd)))
            else:
                LOGGER.warning("Crypto remains empty for %s", window.end.date())

    for row, column, value in writes:
        if dry_run:
            LOGGER.info("Dry run: row=%s column=%s value=%s", row, column, value)
        else:
            worksheet.update_cell(row, column, value)
    LOGGER.info("%s %s cells", "Would write" if dry_run else "Wrote", len(writes))


if __name__ == "__main__":
    main()
