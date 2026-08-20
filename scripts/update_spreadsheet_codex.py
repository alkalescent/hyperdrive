"""Update the FIRE spreadsheet with Dune-first validator rewards.

Create the saved Dune query from ``scripts/dune_validator_rewards.sql``. It is
expected to return one row for every UTC date in the requested half-open range
with these columns:

``day``, ``consensus_reward_gwei``, ``execution_reward_wei``,
``capital_change_gwei``, and ``coverage_complete``.

If Dune is unavailable or its result is incomplete, the whole requested range
is calculated again from Prysm and Geth. No partial provider results are mixed.
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

import gspread
import pandas as pd
import requests
from requests import Response, Session

from hyperdrive.Broker import Robinhood
from hyperdrive.Constants import CLOSE, DATE_FMT, TIME
from hyperdrive.DataSource import Polygon

LOGGER = logging.getLogger(__name__)

VALIDATOR_DEFAULT = 690345
ETHEREUM_GENESIS_TIMESTAMP = 1_606_824_023
SECONDS_PER_SLOT = 12
SLOTS_PER_EPOCH = 32
EPOCHS_PER_SYNC_COMMITTEE_PERIOD = 256
GWEI_PER_ETH = Decimal(10**9)
WEI_PER_ETH = Decimal(10**18)
ETH_USD_SYMBOL = "X%3AETHUSD"


class RewardProviderError(RuntimeError):
    """Raised when a reward provider cannot return a complete result."""


@dataclass(frozen=True, order=True)
class RewardPeriod:
    """A half-open UTC reward interval."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        """Validate UTC-midnight interval boundaries."""
        if self.start.tzinfo != UTC or self.end.tzinfo != UTC:
            raise ValueError("Reward periods must use the UTC timezone")
        if (
            self.start.time() != datetime.min.time()
            or self.end.time() != datetime.min.time()
        ):
            raise ValueError("Reward periods must start and end at UTC midnight")
        if self.start >= self.end:
            raise ValueError("Reward period start must precede end")


@dataclass(frozen=True)
class RewardTotal:
    """Consensus and execution rewards in their native integer units."""

    consensus_gwei: int = 0
    execution_wei: int = 0
    capital_change_gwei: int = 0

    @property
    def eth(self) -> Decimal:
        """Return total reward denominated in ETH."""
        return (
            Decimal(self.consensus_gwei) / GWEI_PER_ETH
            + Decimal(self.execution_wei) / WEI_PER_ETH
        )

    def __add__(self, other: RewardTotal) -> RewardTotal:
        """Add two reward totals without converting through floating point."""
        return RewardTotal(
            consensus_gwei=self.consensus_gwei + other.consensus_gwei,
            execution_wei=self.execution_wei + other.execution_wei,
            capital_change_gwei=(self.capital_change_gwei + other.capital_change_gwei),
        )


class RewardProvider(Protocol):
    """Interface shared by primary and secondary reward providers."""

    def fetch(self, periods: list[RewardPeriod]) -> dict[RewardPeriod, RewardTotal]:
        """Return complete totals for every requested period."""


def _integer(value: Any, field: str) -> int:
    """Parse an integer-valued API field without precision loss."""
    if isinstance(value, bool) or value is None:
        raise RewardProviderError(f"{field} is not an integer")
    if isinstance(value, float):
        raise RewardProviderError(f"{field} was returned as a lossy float")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as error:
        raise RewardProviderError(f"{field} is not numeric") from error
    if parsed != parsed.to_integral_value():
        raise RewardProviderError(f"{field} is not an integer")
    return int(parsed)


def _parse_day(value: Any) -> date:
    """Parse a Dune day value as a UTC calendar date."""
    if not isinstance(value, str):
        raise RewardProviderError("Dune day is not a string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return date.fromisoformat(value)
        except ValueError as error:
            raise RewardProviderError(f"Invalid Dune day: {value}") from error
    return parsed.date()


def _complete_flag(value: Any) -> bool:
    """Parse a strict coverage-complete flag."""
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
    """Fetch finalized daily rewards from a saved Dune query."""

    def __init__(
        self,
        api_key: str,
        query_id: int | None,
        validator_index: int,
        fee_recipient: str,
        session: Session | None = None,
    ) -> None:
        """Initialize the Dune API client."""
        self.api_key = api_key
        self.query_id = query_id
        self.validator_index = validator_index
        self.fee_recipient = fee_recipient.lower()
        self.session = session or requests.Session()
        self.base_url = "https://api.dune.com/api/v1"
        self.timeout = float(os.environ.get("DUNE_HTTP_TIMEOUT", "30"))
        self.poll_seconds = float(os.environ.get("DUNE_POLL_SECONDS", "2"))
        self.max_wait_seconds = float(os.environ.get("DUNE_MAX_WAIT_SECONDS", "600"))

    @property
    def headers(self) -> dict[str, str]:
        """Return authenticated Dune request headers."""
        return {
            "Content-Type": "application/json",
            "X-Dune-Api-Key": self.api_key,
        }

    def fetch(self, periods: list[RewardPeriod]) -> dict[RewardPeriod, RewardTotal]:
        """Execute Dune and aggregate complete daily rows into periods."""
        if not periods:
            return {}
        start = min(period.start for period in periods)
        end = max(period.end for period in periods)
        parameters: dict[str, Any] = {
            "validator_index": self.validator_index,
            "fee_recipient": self.fee_recipient,
            "start_date": start.date().isoformat(),
            "end_date": end.date().isoformat(),
        }
        body: dict[str, Any] = {"query_parameters": parameters}
        performance = os.environ.get("DUNE_PERFORMANCE")
        if performance:
            body["performance"] = performance

        if self.query_id is None:
            sql_path = Path(__file__).with_name("dune_validator_rewards.sql")
            sql = sql_path.read_text(encoding="utf-8")
            replacements = {
                "{{validator_index}}": str(self.validator_index),
                "{{fee_recipient}}": self.fee_recipient,
                "{{start_date}}": start.date().isoformat(),
                "{{end_date}}": end.date().isoformat(),
            }
            for placeholder, value in replacements.items():
                sql = sql.replace(placeholder, value)
            body = {"sql": sql, **({"performance": performance} if performance else {})}
            execute_url = f"{self.base_url}/sql/execute"
        else:
            execute_url = f"{self.base_url}/query/{self.query_id}/execute"

        execute = self.session.post(
            execute_url,
            headers=self.headers,
            json=body,
            timeout=self.timeout,
        )
        execution_id = _json(execute, "Dune query execution").get("execution_id")
        if not isinstance(execution_id, str) or not execution_id:
            raise RewardProviderError("Dune did not return an execution ID")

        self._wait(execution_id)
        rows = self._results(execution_id)
        daily = self._daily_rows(rows, start.date(), end.date())
        return {period: self._aggregate_period(period, daily) for period in periods}

    def _wait(self, execution_id: str) -> None:
        """Wait for a Dune execution to complete."""
        deadline = time.monotonic() + self.max_wait_seconds
        while time.monotonic() < deadline:
            response = self.session.get(
                f"{self.base_url}/execution/{execution_id}/status",
                headers=self.headers,
                timeout=self.timeout,
            )
            payload = _json(response, "Dune execution status")
            state = payload.get("state")
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
                break
            offset = next_offset
        return rows

    def _daily_rows(
        self, rows: list[dict[str, Any]], start: date, end: date
    ) -> dict[date, RewardTotal]:
        """Validate Dune's exact daily coverage contract."""
        daily: dict[date, RewardTotal] = {}
        for row in rows:
            day = _parse_day(row.get("day"))
            if day in daily:
                raise RewardProviderError(f"Dune returned duplicate day {day}")
            if not _complete_flag(row.get("coverage_complete")):
                raise RewardProviderError(f"Dune marked {day} incomplete")
            daily[day] = RewardTotal(
                consensus_gwei=_integer(
                    row.get("consensus_reward_gwei"), "consensus_reward_gwei"
                ),
                execution_wei=_integer(
                    row.get("execution_reward_wei"), "execution_reward_wei"
                ),
                capital_change_gwei=_integer(
                    row.get("capital_change_gwei"), "capital_change_gwei"
                ),
            )

        expected: set[date] = set()
        current = start
        while current < end:
            expected.add(current)
            current += timedelta(days=1)
        if set(daily) != expected:
            missing = sorted(expected - set(daily))
            extra = sorted(set(daily) - expected)
            raise RewardProviderError(
                f"Dune date coverage mismatch; missing={missing}, extra={extra}"
            )
        return daily

    @staticmethod
    def _aggregate_period(
        period: RewardPeriod, daily: dict[date, RewardTotal]
    ) -> RewardTotal:
        """Aggregate daily Dune rows into one spreadsheet interval."""
        total = RewardTotal()
        current = period.start.date()
        while current < period.end.date():
            total += daily[current]
            current += timedelta(days=1)
        return total


@dataclass(frozen=True)
class _EpochData:
    """Local consensus data needed for one epoch."""

    epoch: int
    attestation_gwei: int
    proposal_slots: tuple[int, ...]


class LocalNodeRewardProvider:
    """Calculate exact rewards from a Prysm and Geth node."""

    def __init__(
        self,
        beacon_url: str,
        geth_url: str,
        validator_index: int,
        fee_recipient: str,
        session: Session | None = None,
    ) -> None:
        """Initialize local node endpoints."""
        self.beacon_url = beacon_url.rstrip("/")
        self.geth_url = geth_url.rstrip("/")
        self.validator_index = validator_index
        self.validator_text = str(validator_index)
        self.fee_recipient = fee_recipient.lower()
        self.session = session or requests.Session()
        self.timeout = float(os.environ.get("NODE_HTTP_TIMEOUT", "30"))
        self.workers = int(os.environ.get("NODE_HTTP_WORKERS", "8"))

    def fetch(self, periods: list[RewardPeriod]) -> dict[RewardPeriod, RewardTotal]:
        """Return complete local-node totals for all periods."""
        if not periods:
            return {}
        self._preflight()
        return {period: self._fetch_period(period) for period in periods}

    def _preflight(self) -> None:
        """Verify that both endpoints are healthy Ethereum mainnet nodes."""
        try:
            health = self.session.get(
                f"{self.beacon_url}/eth/v1/node/health", timeout=self.timeout
            )
            if health.status_code not in {200, 206}:
                health.raise_for_status()
        except requests.RequestException as error:
            raise RewardProviderError(f"Prysm health check failed: {error}") from error
        if self._rpc("eth_chainId", []) != "0x1":
            raise RewardProviderError("Geth endpoint is not Ethereum mainnet")
        modules = self._rpc("rpc_modules", [])
        if not isinstance(modules, dict) or not {"eth", "debug"}.issubset(modules):
            raise RewardProviderError(
                "Geth endpoint must expose the eth and debug modules privately"
            )

    def _beacon(
        self,
        method: str,
        path: str,
        body: list[str] | None = None,
        allow_missing: bool = False,
    ) -> dict[str, Any] | None:
        """Call a Prysm Beacon API endpoint."""
        try:
            response = self.session.request(
                method,
                f"{self.beacon_url}{path}",
                json=body,
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise RewardProviderError(
                f"Prysm request failed for {path}: {error}"
            ) from error
        if allow_missing and response.status_code == 404:
            return None
        return _json(response, f"Prysm request for {path}")

    def _rpc(self, method: str, parameters: list[Any]) -> Any:
        """Call a Geth JSON-RPC method."""
        try:
            response = self.session.post(
                self.geth_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": method,
                    "params": parameters,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as error:
            raise RewardProviderError(
                f"Geth {method} request failed: {error}"
            ) from error
        payload = _json(response, f"Geth {method}")
        if payload.get("error") is not None:
            raise RewardProviderError(f"Geth {method} error: {payload['error']}")
        if "result" not in payload:
            raise RewardProviderError(f"Geth {method} did not return a result")
        return payload["result"]

    def _fetch_period(self, period: RewardPeriod) -> RewardTotal:
        """Calculate one complete period from node data."""
        epochs = self._epochs_touching(period)
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            epoch_data = list(pool.map(self._epoch_data, epochs))

        consensus = 0
        proposal_slots: set[int] = set()
        for item in epoch_data:
            reward_time = self._epoch_reward_time(item.epoch)
            if period.start <= reward_time < period.end:
                consensus += item.attestation_gwei
            proposal_slots.update(
                slot
                for slot in item.proposal_slots
                if period.start <= self._slot_time(slot) < period.end
            )

        execution = 0
        for slot in sorted(proposal_slots):
            block_consensus, block_execution = self._proposal_rewards(slot)
            consensus += block_consensus
            execution += block_execution

        consensus += self._sync_rewards(period)
        return RewardTotal(consensus_gwei=consensus, execution_wei=execution)

    def _epochs_touching(self, period: RewardPeriod) -> list[int]:
        """Return epochs whose duties or transition touch a period."""
        first_slot, end_slot = self._slot_bounds(period)
        first_epoch = max(0, first_slot // SLOTS_PER_EPOCH - 1)
        last_epoch = (end_slot - 1) // SLOTS_PER_EPOCH
        return list(range(first_epoch, last_epoch + 1))

    def _epoch_data(self, epoch: int) -> _EpochData:
        """Fetch attestation rewards and proposer duties for an epoch."""
        attestation = self._beacon(
            "POST",
            f"/eth/v1/beacon/rewards/attestations/{epoch}",
            [self.validator_text],
        )
        if attestation is None:
            raise RewardProviderError(f"Missing attestation rewards for epoch {epoch}")
        data = attestation.get("data")
        if not isinstance(data, dict) or not isinstance(
            data.get("total_rewards"), list
        ):
            raise RewardProviderError(
                f"Malformed attestation rewards for epoch {epoch}"
            )
        matching = [
            reward
            for reward in data["total_rewards"]
            if isinstance(reward, dict)
            and str(reward.get("validator_index")) == self.validator_text
        ]
        if len(matching) != 1:
            raise RewardProviderError(
                f"Expected one attestation reward for epoch {epoch}, got {len(matching)}"
            )
        attestation_gwei = sum(
            _integer(value, f"attestation {field}")
            for field, value in matching[0].items()
            if field != "validator_index"
        )

        duties = self._beacon("GET", f"/eth/v1/validator/duties/proposer/{epoch}")
        if duties is None or not isinstance(duties.get("data"), list):
            raise RewardProviderError(f"Malformed proposer duties for epoch {epoch}")
        slots = tuple(
            _integer(duty.get("slot"), "proposer slot")
            for duty in duties["data"]
            if isinstance(duty, dict)
            and str(duty.get("validator_index")) == self.validator_text
        )
        return _EpochData(epoch, attestation_gwei, slots)

    def _proposal_rewards(self, slot: int) -> tuple[int, int]:
        """Return consensus and execution rewards for an assigned proposal."""
        header = self._beacon(
            "GET", f"/eth/v1/beacon/headers/{slot}", allow_missing=True
        )
        if header is None:
            return 0, 0
        rewards = self._beacon("GET", f"/eth/v1/beacon/rewards/blocks/{slot}")
        if rewards is None or not isinstance(rewards.get("data"), dict):
            raise RewardProviderError(f"Missing block rewards for slot {slot}")
        reward_data = rewards["data"]
        if str(reward_data.get("proposer_index")) != self.validator_text:
            raise RewardProviderError(f"Unexpected proposer for slot {slot}")
        consensus = _integer(reward_data.get("total"), "block reward total")

        block = self._beacon("GET", f"/eth/v2/beacon/blocks/{slot}")
        if block is None:
            raise RewardProviderError(f"Missing beacon block for slot {slot}")
        try:
            payload = block["data"]["message"]["body"]["execution_payload"]
            block_hash = payload["block_hash"]
            payload_recipient = payload["fee_recipient"].lower()
        except (KeyError, TypeError, AttributeError) as error:
            raise RewardProviderError(
                f"Malformed execution payload for slot {slot}"
            ) from error
        execution = self._execution_reward(block_hash, payload_recipient)
        return consensus, execution

    def _execution_reward(self, block_hash: str, payload_recipient: str) -> int:
        """Calculate priority fees or builder payment for a proposed block."""
        block = self._rpc("eth_getBlockByHash", [block_hash, False])
        receipts = self._rpc("eth_getBlockReceipts", [block_hash])
        if not isinstance(block, dict) or not isinstance(receipts, list):
            raise RewardProviderError(f"Missing Geth block data for {block_hash}")
        try:
            base_fee = int(block.get("baseFeePerGas", "0x0"), 16)
            priority_fees = 0
            for receipt in receipts:
                if not isinstance(receipt, dict):
                    raise RewardProviderError(
                        f"Malformed receipt in block {block_hash}"
                    )
                gas_used = int(receipt["gasUsed"], 16)
                gas_price = int(receipt["effectiveGasPrice"], 16)
                priority_fees += gas_used * max(0, gas_price - base_fee)
        except (KeyError, TypeError, ValueError) as error:
            raise RewardProviderError(
                f"Malformed fee fields in block {block_hash}"
            ) from error

        traces = self._rpc(
            "debug_traceBlockByHash",
            [block_hash, {"tracer": "callTracer", "timeout": "30s"}],
        )
        if not isinstance(traces, list):
            raise RewardProviderError(f"Malformed traces for block {block_hash}")
        transfers = 0
        for trace in traces:
            if not isinstance(trace, dict) or trace.get("error"):
                raise RewardProviderError(f"Incomplete trace for block {block_hash}")
            frame = trace.get("result")
            if not isinstance(frame, dict):
                raise RewardProviderError(f"Missing call frame for block {block_hash}")
            transfers += self._inbound_value(frame)

        if payload_recipient == self.fee_recipient:
            return priority_fees + transfers
        if transfers <= 0:
            raise RewardProviderError(
                f"MEV block {block_hash} has no attributable fee-recipient payment"
            )
        return transfers

    def _inbound_value(self, frame: dict[str, Any]) -> int:
        """Recursively sum real ETH transfers into the configured recipient."""
        if frame.get("error"):
            return 0
        total = 0
        call_type = str(frame.get("type", "CALL")).upper()
        sender = str(frame.get("from", "")).lower()
        recipient = str(frame.get("to", frame.get("refundAddress", ""))).lower()
        if (
            call_type in {"CALL", "CREATE", "CREATE2", "SELFDESTRUCT"}
            and recipient == self.fee_recipient
            and sender != self.fee_recipient
        ):
            value = frame.get("value", frame.get("balance", "0x0"))
            try:
                total += (
                    int(value, 16)
                    if isinstance(value, str)
                    else _integer(value, "trace value")
                )
            except ValueError as error:
                raise RewardProviderError("Trace value is malformed") from error
        calls = frame.get("calls", [])
        if not isinstance(calls, list):
            raise RewardProviderError("Trace calls field is malformed")
        for child in calls:
            if not isinstance(child, dict):
                raise RewardProviderError("Trace child is malformed")
            total += self._inbound_value(child)
        return total

    def _sync_rewards(self, period: RewardPeriod) -> int:
        """Return sync-committee rewards for the validator in a period."""
        first_slot, end_slot = self._slot_bounds(period)
        first_period = (
            first_slot // SLOTS_PER_EPOCH
        ) // EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        last_period = (
            (end_slot - 1) // SLOTS_PER_EPOCH
        ) // EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        active_periods = [
            sync_period
            for sync_period in range(first_period, last_period + 1)
            if self._is_sync_member(sync_period)
        ]
        if not active_periods:
            return 0

        def reward_for_slot(slot: int) -> int:
            epoch = slot // SLOTS_PER_EPOCH
            sync_period = epoch // EPOCHS_PER_SYNC_COMMITTEE_PERIOD
            if sync_period not in active_periods:
                return 0
            response = self._beacon(
                "POST",
                f"/eth/v1/beacon/rewards/sync_committee/{slot}",
                [self.validator_text],
                allow_missing=True,
            )
            if response is None:
                return 0
            data = response.get("data")
            if not isinstance(data, list):
                raise RewardProviderError(f"Malformed sync rewards for slot {slot}")
            matching = [
                item
                for item in data
                if isinstance(item, dict)
                and str(item.get("validator_index")) == self.validator_text
            ]
            if len(matching) != 1:
                raise RewardProviderError(
                    f"Expected one sync reward for slot {slot}, got {len(matching)}"
                )
            return _integer(matching[0].get("reward"), "sync reward")

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return sum(pool.map(reward_for_slot, range(first_slot, end_slot)))

    def _is_sync_member(self, sync_period: int) -> bool:
        """Check membership using a historical state in the committee period."""
        epoch = sync_period * EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        state_slot = epoch * SLOTS_PER_EPOCH
        response = self._beacon(
            "GET",
            f"/eth/v1/beacon/states/{state_slot}/sync_committees?epoch={epoch}",
        )
        if response is None or not isinstance(response.get("data"), dict):
            raise RewardProviderError(
                f"Missing sync committee data for period {sync_period}"
            )
        validators = response["data"].get("validators")
        if not isinstance(validators, list):
            raise RewardProviderError(
                f"Malformed sync committee data for period {sync_period}"
            )
        return self.validator_text in {str(item) for item in validators}

    @staticmethod
    def _slot_time(slot: int) -> datetime:
        """Convert a slot to its scheduled UTC time."""
        return datetime.fromtimestamp(
            ETHEREUM_GENESIS_TIMESTAMP + slot * SECONDS_PER_SLOT, UTC
        )

    @staticmethod
    def _epoch_reward_time(epoch: int) -> datetime:
        """Return the transition time when an epoch's rewards are applied."""
        slot = (epoch + 1) * SLOTS_PER_EPOCH
        return LocalNodeRewardProvider._slot_time(slot)

    @staticmethod
    def _slot_bounds(period: RewardPeriod) -> tuple[int, int]:
        """Return inclusive/exclusive slots whose scheduled times are in a period."""
        start_seconds = int(period.start.timestamp()) - ETHEREUM_GENESIS_TIMESTAMP
        end_seconds = int(period.end.timestamp()) - ETHEREUM_GENESIS_TIMESTAMP
        first = -(-start_seconds // SECONDS_PER_SLOT)
        end = -(-end_seconds // SECONDS_PER_SLOT)
        return max(0, first), max(0, end)


def fetch_rewards(
    periods: list[RewardPeriod],
    validator_index: int,
    fee_recipient: str,
) -> tuple[str, dict[RewardPeriod, RewardTotal]]:
    """Use Dune first, then recompute all periods through the local node."""
    dune_key = os.environ.get("DUNE_API_KEY") or os.environ.get("DUNE")
    dune_query = os.environ.get("DUNE_QUERY_ID")
    if dune_key:
        try:
            provider = DuneRewardProvider(
                dune_key,
                int(dune_query) if dune_query else None,
                validator_index,
                fee_recipient,
            )
            return "dune", provider.fetch(periods)
        except (RewardProviderError, ValueError, requests.RequestException) as error:
            LOGGER.warning("Dune reward lookup failed; using local node: %s", error)
    else:
        LOGGER.warning("Dune is not configured; using local node")

    beacon_url = os.environ.get("PRYSM_BEACON_URL") or "http://127.0.0.1:3500"
    geth_url = os.environ.get("GETH_RPC_URL") or "http://127.0.0.1:8545"
    provider = LocalNodeRewardProvider(
        beacon_url,
        geth_url,
        validator_index,
        fee_recipient,
    )
    return "local-node", provider.fetch(periods)


def calculate_options_value(options: pd.DataFrame, start: str, end: str) -> float:
    """Calculate realized options value for a date range."""
    if options.empty:
        return 0.0
    mask = (options["updated_at"] >= start) & (options["updated_at"] < end)
    period_options = options[mask]
    net_value = 0.0
    for _, order in period_options.iterrows():
        premium = float(order["premium"])
        direction = order["direction"]
        if direction == "credit":
            order_date = pd.to_datetime(order["updated_at"])
            legs = order.get("legs", [])
            if legs:
                expiration = legs[0].get("expiration_date")
                if expiration and (pd.to_datetime(expiration) - order_date).days > 12:
                    continue
            net_value += premium
        else:
            net_value -= premium
    return net_value


def _price_periods(periods: list[RewardPeriod]) -> dict[RewardPeriod, Decimal]:
    """Fetch ETH/USD once and return an average close for every period."""
    if not periods:
        return {}
    earliest = min(period.start for period in periods)
    days = (datetime.now(UTC).date() - earliest.date()).days + 2
    prices = Polygon().get_ohlc(ETH_USD_SYMBOL, f"{max(days, 1)}d")
    if prices.empty:
        raise RuntimeError("Polygon returned no ETH/USD prices")
    timestamps = pd.to_datetime(prices[TIME], utc=True)
    result: dict[RewardPeriod, Decimal] = {}
    for period in periods:
        mask = (timestamps >= period.start) & (timestamps < period.end)
        closes = prices.loc[mask, CLOSE]
        expected_dates = {
            (period.start + timedelta(days=offset)).date()
            for offset in range((period.end - period.start).days)
        }
        actual_dates = set(timestamps.loc[mask].dt.date)
        if actual_dates != expected_dates or len(closes) != len(expected_dates):
            raise RuntimeError(f"Incomplete ETH/USD coverage for {period}")
        result[period] = sum(Decimal(str(value)) for value in closes) / Decimal(
            len(closes)
        )
    return result


def _is_blank(value: Any) -> bool:
    """Return whether a spreadsheet value is empty."""
    return value == "" or pd.isna(value)


def _write_cell(
    worksheet: Any, row: int, column: int, value: int, dry_run: bool
) -> None:
    """Write or log one spreadsheet cell update."""
    if dry_run:
        LOGGER.info("Dry run: row=%s column=%s value=%s", row, column, value)
    else:
        worksheet.update_cell(row, column, value)


def main() -> None:
    """Update all currently empty FIRE spreadsheet values."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    dry_run = os.environ.get("SPREADSHEET_DRY_RUN", "false").lower() == "true"
    skip_robinhood = (
        os.environ.get("SPREADSHEET_SKIP_ROBINHOOD", "false").lower() == "true"
    )
    worksheet = gspread.service_account().open("FIRE").get_worksheet(0)
    if worksheet is None:
        raise RuntimeError("FIRE worksheet 0 does not exist")
    frame = pd.DataFrame(worksheet.get_all_records())
    columns = list(frame.columns)
    total_index = columns.index("Total")
    editable_columns = columns[:total_index]
    frame["Date"] = pd.to_datetime(frame["Date"])
    today = datetime.now().date()
    targets = frame[
        (frame["Date"].dt.date < today)
        & frame[editable_columns].map(_is_blank).any(axis=1)
    ]
    if targets.empty:
        LOGGER.info("No spreadsheet cells need updating")
        return

    column_numbers = {name: index + 1 for index, name in enumerate(columns)}
    row_offset = 2

    dividends = pd.DataFrame()
    options = pd.DataFrame()
    robinhood_available = False
    needs_robinhood = not skip_robinhood and any(
        _is_blank(row[column])
        for _, row in targets.iterrows()
        for column in ("Dividends", "Options")
    )
    if skip_robinhood:
        LOGGER.info("Skipping Robinhood during Crypto-only validation")
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

    for frame_index, row in targets.iterrows():
        end = pd.Timestamp(row["Date"])
        start = end - timedelta(weeks=1)
        start_text = start.strftime(DATE_FMT)
        end_text = end.strftime(DATE_FMT)
        sheet_row = int(frame_index) + row_offset
        if _is_blank(row["Dividends"]) and robinhood_available:
            value = 0
            if not dividends.empty:
                selected = dividends[
                    (dividends["payable_date"] >= start_text)
                    & (dividends["payable_date"] < end_text)
                ]
                value = round(selected["amount"].astype(float).sum())
            _write_cell(
                worksheet,
                sheet_row,
                column_numbers["Dividends"],
                value,
                dry_run,
            )
        if _is_blank(row["Options"]) and robinhood_available:
            value = round(calculate_options_value(options, start_text, end_text))
            _write_cell(
                worksheet,
                sheet_row,
                column_numbers["Options"],
                value,
                dry_run,
            )

    crypto_rows = [
        (int(index), row)
        for index, row in targets.iterrows()
        if _is_blank(row["Crypto"])
    ]
    if not crypto_rows:
        return
    try:
        validator_index = int(os.environ.get("VALIDATOR_ID", str(VALIDATOR_DEFAULT)))
    except ValueError:
        LOGGER.error("Crypto cells remain empty: VALIDATOR_ID must be an integer")
        return
    if validator_index < 0:
        LOGGER.error("Crypto cells remain empty: VALIDATOR_ID must be non-negative")
        return
    fee_recipient = (
        os.environ.get("VALIDATOR_FEE_RECIPIENT") or os.environ.get("FEE_RECIPIENT", "")
    ).strip()
    if not fee_recipient:
        LOGGER.error("Crypto cells remain empty: VALIDATOR_FEE_RECIPIENT is required")
        return
    if re.fullmatch(r"0x[0-9a-fA-F]{40}", fee_recipient) is None:
        LOGGER.error(
            "Crypto cells remain empty: VALIDATOR_FEE_RECIPIENT is not an address"
        )
        return
    periods = [
        RewardPeriod(
            start=(pd.Timestamp(row["Date"]) - timedelta(weeks=1))
            .to_pydatetime()
            .replace(tzinfo=UTC),
            end=pd.Timestamp(row["Date"]).to_pydatetime().replace(tzinfo=UTC),
        )
        for _, row in crypto_rows
    ]
    try:
        provider_name, rewards = fetch_rewards(periods, validator_index, fee_recipient)
        for period, reward in rewards.items():
            if reward.capital_change_gwei:
                LOGGER.warning(
                    "Excluding a %s Gwei capital movement from %s through %s",
                    reward.capital_change_gwei,
                    period.start.date(),
                    period.end.date(),
                )
        prices = _price_periods(periods)
    except (RewardProviderError, RuntimeError, requests.RequestException) as error:
        LOGGER.error("Crypto cells remain empty: %s", error)
        return

    LOGGER.info("Using %s validator rewards", provider_name)
    for (frame_index, _), period in zip(crypto_rows, periods, strict=True):
        usd = (rewards[period].eth * prices[period]).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        _write_cell(
            worksheet,
            frame_index + row_offset,
            column_numbers["Crypto"],
            int(usd),
            dry_run,
        )


if __name__ == "__main__":
    main()
