"""Ethereum validator rewards from Dune and QuickNode.

Both providers evaluate the same half-open UTC calendar windows. Dune returns
daily reward summaries. QuickNode subtracts finalized validator balances at
the first beacon slot on or after each boundary, then adds execution payments
enumerated through Etherscan and verified against beacon proposers.

Provider failures remain distinct from a proven zero. A window is omitted when
neither provider can determine a complete value.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import sleep
from typing import Any, Protocol

import requests
from requests import Response, Session

from . import Constants as C
from .DataSource import MarketData

LOGGER = logging.getLogger(__name__)
GWEI_PER_ETH = Decimal(10**9)
WEI_PER_ETH = Decimal(10**18)
DISAGREEMENT_ABSOLUTE_ETH = Decimal("0.001")
DISAGREEMENT_RELATIVE = Decimal("0.05")

_market: MarketData | None = None


def market() -> MarketData:
    """Return the shared market-data helper used for retries."""
    global _market
    if _market is None:
        _market = MarketData()
    return _market


class RewardProviderError(RuntimeError):
    """Raised when a provider cannot determine a complete reward value."""


@dataclass(frozen=True, order=True)
class RewardWindow:
    """A half-open UTC reward interval with midnight boundaries."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        """Validate the calendar window required by the Dune query."""
        if self.start.tzinfo != UTC or self.end.tzinfo != UTC:
            raise ValueError("Reward windows must use the UTC timezone")
        if (
            self.start.time() != datetime.min.time()
            or self.end.time() != datetime.min.time()
        ):
            raise ValueError("Reward windows must start and end at UTC midnight")
        if self.start >= self.end:
            raise ValueError("Reward window start must precede end")


@dataclass(frozen=True)
class RewardTotal:
    """Consensus and execution rewards in exact native units."""

    consensus_gwei: int = 0
    execution_wei: int = 0
    capital_change_gwei: int = 0

    @property
    def eth(self) -> Decimal:
        """Return rewards in ETH, excluding reported capital movements."""
        return (
            Decimal(self.consensus_gwei) / GWEI_PER_ETH
            + Decimal(self.execution_wei) / WEI_PER_ETH
        )

    def __add__(self, other: RewardTotal) -> RewardTotal:
        """Add totals without converting through floating point."""
        return RewardTotal(
            self.consensus_gwei + other.consensus_gwei,
            self.execution_wei + other.execution_wei,
            self.capital_change_gwei + other.capital_change_gwei,
        )


@dataclass(frozen=True)
class RewardEstimate:
    """A blended ETH value and the complete provider values behind it."""

    eth: Decimal
    source_values: tuple[tuple[str, Decimal], ...]

    @property
    def sources(self) -> tuple[str, ...]:
        """Return provider names in deterministic order."""
        return tuple(name for name, _ in self.source_values)


class RewardProvider(Protocol):
    """Interface implemented by complete reward providers."""

    def fetch(self, windows: list[RewardWindow]) -> dict[RewardWindow, RewardTotal]:
        """Return complete totals for the windows the provider can determine."""


class BeaconReader(Protocol):
    """Beacon operations required by the QuickNode provider."""

    def boundary_slot(self, when: datetime) -> int:
        """Return the first slot on or after a boundary."""

    def slot_at(self, when: datetime) -> int:
        """Return the slot containing a timestamp."""

    def validator(self, slot: int, validator_index: int) -> dict[str, Any]:
        """Return a finalized historical validator state."""

    def proposer_at(self, slot: int) -> int | None:
        """Return a slot's proposer index."""


class ScanReader(Protocol):
    """Etherscan operations required by the QuickNode provider."""

    def block_by_time(self, when: datetime, closest: str) -> int | None:
        """Resolve a timestamp to a block."""

    def paged(self, **params: Any) -> list[Any] | None:
        """Return a complete paged result."""


class RelayReader(Protocol):
    """MEV relay operation required by the QuickNode provider."""

    def payloads(self, pubkey: str) -> dict[int, int]:
        """Return delivered payload values by slot."""


def _integer(value: Any, field: str) -> int:
    """Parse an integer-valued API field without precision loss."""
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise RewardProviderError(f"{field} is not an exact integer")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise RewardProviderError(f"{field} is not numeric") from error
    if parsed != parsed.to_integral_value():
        raise RewardProviderError(f"{field} is not an integer")
    return int(parsed)


def _parse_day(value: Any) -> date:
    """Parse a Dune date or timestamp as a calendar date."""
    if not isinstance(value, str):
        raise RewardProviderError("Dune day is not a string")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise RewardProviderError(f"Invalid Dune day: {value}") from error


def _complete_flag(value: Any) -> bool:
    """Parse Dune's strict coverage flag."""
    return (
        value is True
        or value == 1
        or (isinstance(value, str) and value.lower() in {"true", "1"})
    )


def _json(response: Response, context: str) -> dict[str, Any]:
    """Validate an HTTP response and decode a JSON object."""
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as error:
        raise RewardProviderError(f"{context} failed: {error}") from error
    if not isinstance(payload, dict):
        raise RewardProviderError(f"{context} returned a non-object response")
    return payload


class DuneRewardProvider:
    """Fetch finalized daily rewards through Dune's raw-SQL API."""

    def __init__(
        self,
        api_key: str,
        validator_index: int,
        fee_recipient: str,
        session: Session | None = None,
        sql_path: Path | None = None,
    ) -> None:
        """Initialize the Dune client."""
        self.api_key = api_key
        self.validator_index = validator_index
        self.fee_recipient = fee_recipient.lower()
        self.session = session or requests.Session()
        self.sql_path = sql_path or (
            Path(__file__).resolve().parent.parent
            / "scripts"
            / "dune_validator_rewards.sql"
        )
        self.base_url = "https://api.dune.com/api/v1"
        self.timeout = float(os.environ.get("DUNE_HTTP_TIMEOUT", "30"))
        self.poll_seconds = float(os.environ.get("DUNE_POLL_SECONDS", "2"))
        self.max_wait_seconds = float(os.environ.get("DUNE_MAX_WAIT_SECONDS", "600"))

    @property
    def headers(self) -> dict[str, str]:
        """Return authenticated Dune headers."""
        return {
            "Content-Type": "application/json",
            "X-Dune-Api-Key": self.api_key,
        }

    def fetch(self, windows: list[RewardWindow]) -> dict[RewardWindow, RewardTotal]:
        """Execute one query and aggregate its daily rows by window."""
        if not windows:
            return {}
        start = min(window.start for window in windows)
        end = max(window.end for window in windows)
        response = self.session.post(
            f"{self.base_url}/sql/execute",
            headers=self.headers,
            json={"sql": self._render_sql(start.date(), end.date())},
            timeout=self.timeout,
        )
        execution_id = _json(response, "Dune query execution").get("execution_id")
        if not isinstance(execution_id, str) or not execution_id:
            raise RewardProviderError("Dune did not return an execution ID")
        self._wait(execution_id)
        daily = self._daily_rows(self._results(execution_id), start.date(), end.date())
        return {window: self._aggregate(window, daily) for window in windows}

    def _render_sql(self, start: date, end: date) -> str:
        """Render validated parameters into the bundled SQL."""
        sql = self.sql_path.read_text(encoding="utf-8")
        replacements = {
            "{{validator_index}}": str(self.validator_index),
            "{{fee_recipient}}": self.fee_recipient,
            "{{start_date}}": start.isoformat(),
            "{{end_date}}": end.isoformat(),
        }
        for placeholder, value in replacements.items():
            sql = sql.replace(placeholder, value)
        return sql

    def _wait(self, execution_id: str) -> None:
        """Poll until Dune completes or rejects the execution."""
        deadline = time.monotonic() + self.max_wait_seconds
        while time.monotonic() < deadline:
            response = self.session.get(
                f"{self.base_url}/execution/{execution_id}/status",
                headers=self.headers,
                timeout=self.timeout,
            )
            state = _json(response, "Dune execution status").get("state")
            if state == "QUERY_STATE_COMPLETED":
                return
            if state in {
                "QUERY_STATE_FAILED",
                "QUERY_STATE_CANCELLED",
                "QUERY_STATE_EXPIRED",
            }:
                raise RewardProviderError(f"Dune execution ended in {state}")
            time.sleep(self.poll_seconds)
        raise RewardProviderError("Dune execution timed out")

    def _results(self, execution_id: str) -> list[dict[str, Any]]:
        """Retrieve every page of a completed Dune result."""
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            response = self.session.get(
                f"{self.base_url}/execution/{execution_id}/results",
                headers=self.headers,
                params={"limit": 1000, "offset": offset},
                timeout=self.timeout,
            )
            payload = _json(response, "Dune execution results")
            if payload.get("state") != "QUERY_STATE_COMPLETED":
                raise RewardProviderError("Dune results are not complete")
            result = payload.get("result")
            if not isinstance(result, dict):
                raise RewardProviderError("Dune result payload is missing")
            page = result.get("rows")
            if not isinstance(page, list) or not all(
                isinstance(row, dict) for row in page
            ):
                raise RewardProviderError("Dune result rows are malformed")
            rows.extend(page)
            next_offset = payload.get("next_offset")
            if not isinstance(next_offset, int):
                return rows
            offset = next_offset

    def _daily_rows(
        self, rows: list[dict[str, Any]], start: date, end: date
    ) -> dict[date, RewardTotal]:
        """Validate exact, complete daily coverage."""
        daily: dict[date, RewardTotal] = {}
        for row in rows:
            day = _parse_day(row.get("day"))
            if day in daily:
                raise RewardProviderError(f"Dune returned duplicate day {day}")
            if not _complete_flag(row.get("coverage_complete")):
                raise RewardProviderError(f"Dune marked {day} incomplete")
            daily[day] = RewardTotal(
                _integer(row.get("consensus_reward_gwei"), "consensus reward"),
                _integer(row.get("execution_reward_wei"), "execution reward"),
                _integer(row.get("capital_change_gwei"), "capital change"),
            )
        expected = {
            start + timedelta(days=offset) for offset in range((end - start).days)
        }
        if set(daily) != expected:
            raise RewardProviderError(
                "Dune date coverage mismatch; "
                f"missing={sorted(expected - set(daily))}, "
                f"extra={sorted(set(daily) - expected)}"
            )
        return daily

    @staticmethod
    def _aggregate(window: RewardWindow, daily: dict[date, RewardTotal]) -> RewardTotal:
        """Aggregate daily rows into one requested window."""
        total = RewardTotal()
        current = window.start.date()
        while current < window.end.date():
            total += daily[current]
            current += timedelta(days=1)
        return total


def _utc_timestamp(when: datetime) -> int:
    """Return a Unix timestamp while treating naive values as UTC."""
    aware = when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
    return int(aware.timestamp())


def to_utc(timestamp: int | float) -> datetime:
    """Convert a Unix timestamp to an aware UTC datetime."""
    return datetime.fromtimestamp(timestamp, UTC)


class BeaconNode:
    """Client for QuickNode's standard beacon REST API."""

    def __init__(self, url: str | None = None, session: Session | None = None) -> None:
        """Initialize the beacon client."""
        self.url = (url or C.QUICKNODE_URL).rstrip("/")
        self.session = session or requests.Session()

    def _payload(self, path: str, allow_missing: bool = False) -> dict[str, Any] | None:
        """Get one beacon response object."""
        try:
            response = self.session.get(f"{self.url}{path}", timeout=C.API_TIMEOUT)
        except requests.RequestException as error:
            raise RewardProviderError(f"QuickNode request failed: {error}") from error
        if allow_missing and response.status_code == 404:
            return None
        return _json(response, f"QuickNode request for {path}")

    @staticmethod
    def slot_at(when: datetime) -> int:
        """Return the slot containing a timestamp."""
        seconds = _utc_timestamp(when) - C.GENESIS_TIME
        return max(0, seconds // C.SECONDS_PER_SLOT)

    @staticmethod
    def boundary_slot(when: datetime) -> int:
        """Return the first slot scheduled on or after a boundary."""
        seconds = _utc_timestamp(when) - C.GENESIS_TIME
        return max(0, -(-seconds // C.SECONDS_PER_SLOT))

    @staticmethod
    def time_at(slot: int) -> datetime:
        """Return a slot's scheduled UTC time."""
        return to_utc(C.GENESIS_TIME + slot * C.SECONDS_PER_SLOT)

    def validator(self, slot: int, validator_index: int) -> dict[str, Any]:
        """Read one finalized historical validator state."""
        payload = self._payload(
            f"/eth/v1/beacon/states/{slot}/validators/{validator_index}"
        )
        if payload is None or payload.get("finalized") is not True:
            raise RewardProviderError(f"QuickNode state {slot} is not finalized")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RewardProviderError(f"QuickNode state {slot} has no validator")
        if str(data.get("index", validator_index)) != str(validator_index):
            raise RewardProviderError(
                f"QuickNode state {slot} returned another validator"
            )
        validator = data.get("validator")
        if not isinstance(validator, dict):
            raise RewardProviderError(f"QuickNode state {slot} is malformed")
        pubkey = validator.get("pubkey")
        if not isinstance(pubkey, str) or not pubkey:
            raise RewardProviderError(f"QuickNode state {slot} has no pubkey")
        return {
            "balance": _integer(data.get("balance"), "validator balance"),
            "pubkey": pubkey,
        }

    def proposer_at(self, slot: int) -> int | None:
        """Return the proposer index, or None for a missed slot."""
        payload = self._payload(f"/eth/v1/beacon/headers/{slot}", allow_missing=True)
        if payload is None:
            return None
        try:
            return int(payload["data"]["header"]["message"]["proposer_index"])
        except (KeyError, TypeError, ValueError) as error:
            raise RewardProviderError(
                f"Malformed proposer header for slot {slot}"
            ) from error


class Etherscan:
    """Client for Etherscan v2 list and scalar endpoints."""

    def __init__(self, key: str | None = None, session: Session | None = None) -> None:
        """Initialize the Etherscan client."""
        self.key = key if key is not None else C.ETHERSCAN
        self.session = session or requests.Session()

    def call(self, **params: Any) -> list[Any] | None:
        """Return a successful list result, including an empty list."""
        if not self.key:
            return None
        query = {"chainid": 1, "apikey": self.key, **params}

        def _call() -> list[Any] | None:
            response = self.session.get(
                C.ETHERSCAN_URL, params=query, timeout=C.API_TIMEOUT
            )
            response.raise_for_status()
            result = response.json().get("result")
            if isinstance(result, list):
                return result
            raise RewardProviderError(f"Etherscan returned {result}")

        try:
            return market().try_again(_call)
        except Exception:
            return None
        finally:
            sleep(C.ETHERSCAN_FREE_DELAY)

    def call_scalar(self, **params: Any) -> str | None:
        """Return a successful scalar result."""
        if not self.key:
            return None
        query = {"chainid": 1, "apikey": self.key, **params}

        def _call() -> str | None:
            response = self.session.get(
                C.ETHERSCAN_URL, params=query, timeout=C.API_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("status")) != "1":
                raise RewardProviderError(f"Etherscan returned {payload.get('result')}")
            result = payload.get("result")
            return str(result) if result is not None else None

        try:
            return market().try_again(_call)
        except Exception:
            return None
        finally:
            sleep(C.ETHERSCAN_FREE_DELAY)

    def paged(self, **params: Any) -> list[Any] | None:
        """Retrieve every page of an Etherscan list endpoint."""
        records: list[Any] = []
        page = 1
        while True:
            batch = self.call(page=page, offset=C.ETHERSCAN_PAGE_SIZE, **params)
            if batch is None:
                return None
            records.extend(batch)
            if len(batch) < C.ETHERSCAN_PAGE_SIZE:
                return records
            page += 1

    def block_by_time(self, when: datetime, closest: str) -> int | None:
        """Resolve a UTC timestamp to an execution block number."""
        result = self.call_scalar(
            module="block",
            action="getblocknobytime",
            timestamp=_utc_timestamp(when),
            closest=closest,
        )
        return int(result) if result and result.isdigit() else None


class RelayIndex:
    """Read delivered payload values from public MEV-Boost relays."""

    def __init__(
        self, relays: list[str] | None = None, session: Session | None = None
    ) -> None:
        """Initialize the relay index."""
        self.relays = relays if relays is not None else list(C.MEV_RELAYS)
        self.session = session or requests.Session()

    def payloads(self, pubkey: str) -> dict[int, int]:
        """Return payload values keyed by slot, ignoring failed relays."""
        delivered: dict[int, int] = {}
        wanted = pubkey.lower()
        for relay in self.relays:
            try:
                response = self.session.get(
                    f"{relay.rstrip('/')}/relay/v1/data/bidtraces/"
                    "proposer_payload_delivered",
                    params={"proposer_pubkey": pubkey, "limit": C.RELAY_PAGE_SIZE},
                    timeout=C.API_TIMEOUT,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError):
                continue
            if not isinstance(payload, list):
                continue
            for record in payload:
                if not isinstance(record, dict):
                    continue
                if str(record.get("proposer_pubkey", "")).lower() != wanted:
                    continue
                delivered[_integer(record.get("slot"), "relay slot")] = _integer(
                    record.get("value"), "relay value"
                )
        return delivered


class QuickNodeRewardProvider:
    """Calculate rewards from historical QuickNode states and Etherscan."""

    def __init__(
        self,
        validator_index: int,
        fee_recipient: str,
        beacon: BeaconReader | None = None,
        scan: ScanReader | None = None,
        relays: RelayReader | None = None,
    ) -> None:
        """Initialize the QuickNode reward calculator."""
        self.validator_index = validator_index
        self.fee_recipient = fee_recipient.lower()
        self.beacon = beacon or BeaconNode()
        self.scan = scan or Etherscan()
        self.relays = relays or RelayIndex()
        self._states: dict[int, dict[str, Any]] = {}
        self._block_ranges: dict[RewardWindow, tuple[int, int]] = {}

    def fetch(self, windows: list[RewardWindow]) -> dict[RewardWindow, RewardTotal]:
        """Return each complete window and omit independently failed windows."""
        totals: dict[RewardWindow, RewardTotal] = {}
        for window in windows:
            try:
                totals[window] = self._fetch_window(window)
            except (
                RewardProviderError,
                requests.RequestException,
                ValueError,
            ) as error:
                LOGGER.warning(
                    "QuickNode rewards unavailable for %s: %s", window, error
                )
        return totals

    def _fetch_window(self, window: RewardWindow) -> RewardTotal:
        """Calculate one complete consensus and execution reward value."""
        start = self._state(self.beacon.boundary_slot(window.start))
        end = self._state(self.beacon.boundary_slot(window.end))
        if start["pubkey"].lower() != end["pubkey"].lower():
            raise RewardProviderError("Validator pubkey changed between boundaries")
        moved = self.capital_moved(window, start["pubkey"])
        if moved is None:
            raise RewardProviderError("Capital movement could not be checked")
        if moved:
            raise RewardProviderError("Capital movement makes balance delta ambiguous")
        return RewardTotal(
            consensus_gwei=int(end["balance"]) - int(start["balance"]),
            execution_wei=self.execution_rewards(window, start["pubkey"]),
        )

    def _state(self, slot: int) -> dict[str, Any]:
        """Read and cache a historical boundary state."""
        if slot not in self._states:
            self._states[slot] = self.beacon.validator(slot, self.validator_index)
        return self._states[slot]

    def _block_range(self, window: RewardWindow) -> tuple[int, int] | None:
        """Return inclusive execution block bounds for a half-open window."""
        if window in self._block_ranges:
            return self._block_ranges[window]
        first = self.scan.block_by_time(window.start, "after")
        last = self.scan.block_by_time(window.end - timedelta(seconds=1), "before")
        if first is None or last is None:
            return None
        self._block_ranges[window] = (first, last)
        return first, last

    def capital_moved(self, window: RewardWindow, pubkey: str) -> bool | None:
        """Detect deposits, withdrawals, and configured capital requests."""
        bounds = self._block_range(window)
        if bounds is None:
            return None
        first, last = bounds
        logs = self.scan.paged(
            module="logs",
            action="getLogs",
            address=C.DEPOSIT_CONTRACT,
            topic0=C.DEPOSIT_EVENT_TOPIC,
            fromBlock=first,
            toBlock=last,
        )
        if logs is None:
            return None
        stripped = pubkey.lower().removeprefix("0x")
        if any(stripped in str(log.get("data", "")).lower() for log in logs):
            return True
        withdrawals = self.scan.paged(
            module="account",
            action="txsBeaconWithdrawal",
            address=self.fee_recipient,
            startblock=first,
            endblock=last,
        )
        if withdrawals is None:
            return None
        if any(
            str(row.get("validatorIndex")) == str(self.validator_index)
            for row in withdrawals
        ):
            return True
        predeploys = {
            C.WITHDRAWAL_REQUEST_PREDEPLOY.lower(),
            C.CONSOLIDATION_REQUEST_PREDEPLOY.lower(),
            C.DEPOSIT_CONTRACT.lower(),
        }
        controllers = [
            address.strip()
            for address in C.STAKING_CONTROLLERS.split(",")
            if address.strip()
        ]
        for controller in controllers:
            for action in ("txlist", "txlistinternal"):
                entries = self.scan.paged(
                    module="account",
                    action=action,
                    address=controller,
                    startblock=first,
                    endblock=last,
                )
                if entries is None:
                    return None
                if any(
                    str(entry.get("to", "")).lower() in predeploys for entry in entries
                ):
                    return True
        return False

    def candidates(
        self, window: RewardWindow
    ) -> tuple[dict[int, list[dict[str, Any]]], dict[int, dict[str, Any]]] | None:
        """Enumerate inbound payments and coinbase blocks in a window."""
        bounds = self._block_range(window)
        if bounds is None:
            return None
        first, last = bounds
        transfers: dict[int, list[dict[str, Any]]] = {}
        for action in ("txlist", "txlistinternal"):
            entries = self.scan.paged(
                module="account",
                action=action,
                address=self.fee_recipient,
                startblock=first,
                endblock=last,
            )
            if entries is None:
                return None
            for entry in entries:
                if not isinstance(entry, dict):
                    return None
                stamp = entry.get("timeStamp")
                if stamp and not (window.start <= to_utc(int(stamp)) < window.end):
                    continue
                if str(entry.get("to", "")).lower() != self.fee_recipient:
                    continue
                if _integer(entry.get("value", 0), "transfer value") <= 0:
                    continue
                block = _integer(entry.get("blockNumber"), "transfer block")
                transfers.setdefault(block, []).append(entry)
        mined = self.scan.paged(
            module="account",
            action="getminedblocks",
            address=self.fee_recipient,
            blocktype="blocks",
        )
        if mined is None:
            return None
        coinbase: dict[int, dict[str, Any]] = {}
        for record in mined:
            if not isinstance(record, dict):
                return None
            stamp = record.get("timeStamp")
            if stamp and window.start <= to_utc(int(stamp)) < window.end:
                block = _integer(record.get("blockNumber"), "mined block")
                coinbase[block] = record
        return transfers, coinbase

    @staticmethod
    def block_payment(entries: list[dict[str, Any]]) -> int:
        """Sum the final transaction's inbound transfers in one block."""
        if not entries:
            return 0
        indexed = [
            entry
            for entry in entries
            if str(entry.get("transactionIndex", "")).isdigit()
        ]
        if not indexed:
            last_hash = entries[-1].get("hash")
            return sum(
                _integer(entry.get("value"), "transfer value")
                for entry in entries
                if entry.get("hash") == last_hash
            )
        final_index = max(int(entry["transactionIndex"]) for entry in indexed)
        hashes = {
            entry.get("hash")
            for entry in indexed
            if int(entry["transactionIndex"]) == final_index
        }
        return sum(
            _integer(entry.get("value"), "transfer value")
            for entry in entries
            if entry.get("hash") in hashes
        )

    def execution_rewards(self, window: RewardWindow, pubkey: str) -> int:
        """Return verified execution rewards in Wei."""
        found = self.candidates(window)
        if found is None:
            raise RewardProviderError("Execution payments could not be enumerated")
        transfers, coinbase = found
        blocks = set(transfers) | set(coinbase)
        if not blocks:
            return 0
        delivered = self.relays.payloads(pubkey)
        total = 0
        for block in blocks:
            when = self._block_time(block, transfers, coinbase)
            slot = self.beacon.slot_at(when)
            proposer = self.beacon.proposer_at(slot)
            if proposer is None:
                raise RewardProviderError(
                    f"Proposer unavailable for paid block {block}"
                )
            if proposer != self.validator_index:
                continue
            if slot in delivered:
                total += delivered[slot]
            elif block in coinbase:
                total += _integer(coinbase[block].get("blockReward"), "block reward")
            else:
                total += self.block_payment(transfers.get(block, []))
        return total

    @staticmethod
    def _block_time(
        block: int,
        transfers: dict[int, list[dict[str, Any]]],
        coinbase: dict[int, dict[str, Any]],
    ) -> datetime:
        """Return the timestamp carried by records for an execution block."""
        for entry in transfers.get(block, []):
            stamp = entry.get("timeStamp")
            if stamp:
                return to_utc(int(stamp))
        record = coinbase.get(block)
        if record and record.get("timeStamp"):
            return to_utc(int(record["timeStamp"]))
        raise RewardProviderError(f"Paid block {block} has no timestamp")


class StakingRewards:
    """Blend complete Dune and QuickNode reward values by UTC window."""

    def __init__(
        self,
        providers: dict[str, RewardProvider] | None = None,
        validator_index: int | None = None,
        fee_recipient: str | None = None,
    ) -> None:
        """Initialize configured providers or use injected test providers."""
        if providers is not None:
            self.providers = providers
            return
        validator = validator_index
        if validator is None:
            try:
                validator = int(C.VALIDATOR)
            except ValueError as error:
                raise RewardProviderError("VALIDATOR must be an integer") from error
        recipient = fee_recipient if fee_recipient is not None else C.ETH_ADDR
        if validator < 0:
            raise RewardProviderError("VALIDATOR must be non-negative")
        if re.fullmatch(r"0x[0-9a-fA-F]{40}", recipient) is None:
            raise RewardProviderError("ETH_ADDR must be a 0x-prefixed address")
        configured: dict[str, RewardProvider] = {}
        if C.DUNE:
            configured["dune"] = DuneRewardProvider(C.DUNE, validator, recipient)
        configured["quicknode"] = QuickNodeRewardProvider(validator, recipient)
        self.providers = configured

    def fetch(self, windows: list[RewardWindow]) -> dict[RewardWindow, RewardEstimate]:
        """Fetch providers independently and blend complete values per window."""
        results: dict[str, dict[RewardWindow, RewardTotal]] = {}
        for name, provider in self.providers.items():
            try:
                results[name] = provider.fetch(windows)
            except (
                RewardProviderError,
                requests.RequestException,
                ValueError,
            ) as error:
                LOGGER.warning("%s rewards unavailable: %s", name, error)
                results[name] = {}
        estimates: dict[RewardWindow, RewardEstimate] = {}
        for window in windows:
            values: list[tuple[str, Decimal]] = []
            for name in self.providers:
                total = results[name].get(window)
                if total is None:
                    continue
                if total.capital_change_gwei:
                    LOGGER.warning(
                        "%s reported a %s Gwei capital change for %s",
                        name,
                        total.capital_change_gwei,
                        window,
                    )
                values.append((name, total.eth))
            if not values:
                continue
            source_values = dict(values)
            # QuickNode's multi-service calculation can produce a false zero, so a
            # positive Dune result takes precedence instead of being halved.
            if (
                source_values.get("dune", Decimal(0)) > 0
                and source_values.get("quicknode") == 0
            ):
                LOGGER.warning(
                    "Ignoring zero QuickNode rewards for %s because Dune reported "
                    "%s ETH",
                    window,
                    source_values["dune"],
                )
                values = [value for value in values if value[0] != "quicknode"]
            if len(values) > 1:
                self._warn_disagreement(window, values)
            average = sum((value for _, value in values), Decimal(0)) / Decimal(
                len(values)
            )
            estimates[window] = RewardEstimate(average, tuple(values))
        return estimates

    @staticmethod
    def _warn_disagreement(
        window: RewardWindow, values: list[tuple[str, Decimal]]
    ) -> None:
        """Warn when two complete provider values differ materially."""
        amounts = [value for _, value in values]
        difference = max(amounts) - min(amounts)
        relative = DISAGREEMENT_RELATIVE * max(abs(value) for value in amounts)
        threshold = max(DISAGREEMENT_ABSOLUTE_ETH, relative)
        if difference > threshold:
            LOGGER.warning(
                "Validator rewards differ for %s: values=%s difference=%s ETH",
                window,
                values,
                difference,
            )
