"""Tests for Dune and QuickNode validator rewards."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import requests
import responses
from pytest_mock import MockerFixture

from hyperdrive import Constants as C
from hyperdrive.Staking import (
    BeaconNode,
    DuneRewardProvider,
    Etherscan,
    QuickNodeRewardProvider,
    RelayIndex,
    RewardProviderError,
    RewardTotal,
    RewardWindow,
    StakingRewards,
    to_utc,
)

BEACON = "https://beacon.test"
PUBKEY = "0x" + "ab" * 48
RECIPIENT = "0x75603aeb09ec1d9849ad31c7d660605999a46834"
VALIDATOR = 690345


@pytest.fixture
def window() -> RewardWindow:
    """Return one representative spreadsheet week."""
    return RewardWindow(
        datetime(2026, 8, 13, tzinfo=UTC), datetime(2026, 8, 20, tzinfo=UTC)
    )


def dune_row(day: date, consensus: int = 1) -> dict[str, Any]:
    """Build one complete Dune result row."""
    return {
        "day": day.isoformat(),
        "consensus_reward_gwei": str(consensus),
        "execution_reward_wei": "2",
        "capital_change_gwei": "0",
        "coverage_complete": True,
    }


class StubProvider:
    """Return configured provider results or raise an error."""

    def __init__(
        self,
        results: dict[RewardWindow, RewardTotal] | None = None,
        error: Exception | None = None,
    ) -> None:
        """Initialize the provider stub."""
        self.results = results or {}
        self.error = error
        self.windows: list[RewardWindow] = []

    def fetch(self, windows: list[RewardWindow]) -> dict[RewardWindow, RewardTotal]:
        """Record the windows and return the configured behavior."""
        self.windows = windows
        if self.error:
            raise self.error
        return self.results


class FakeBeacon:
    """Provide fixed historical states and proposer identities."""

    def __init__(
        self,
        states: dict[int, dict[str, Any]] | None = None,
        proposers: dict[int, int | None] | None = None,
    ) -> None:
        """Initialize the beacon stub."""
        self.states = states or {}
        self.proposers = proposers or {}
        self.state_calls: list[int] = []

    def boundary_slot(self, when: datetime) -> int:
        """Return the first slot on or after a boundary."""
        return BeaconNode.boundary_slot(when)

    def slot_at(self, when: datetime) -> int:
        """Return the slot containing a timestamp."""
        return BeaconNode.slot_at(when)

    def validator(self, slot: int, validator_index: int) -> dict[str, Any]:
        """Return a fixed state and record the requested slot."""
        self.state_calls.append(slot)
        if slot not in self.states:
            raise RewardProviderError("missing state")
        return self.states[slot]

    def proposer_at(self, slot: int) -> int | None:
        """Return the configured proposer."""
        return self.proposers.get(slot)


class FakeScan:
    """Provide fixed Etherscan block bounds and paged results."""

    def __init__(
        self,
        pages: list[list[Any] | None] | None = None,
        bounds: tuple[int | None, int | None] = (100, 200),
    ) -> None:
        """Initialize the scan stub."""
        self.pages = list(pages or [])
        self.bounds = list(bounds)
        self.block_calls: list[tuple[datetime, str]] = []
        self.page_calls: list[dict[str, Any]] = []

    def block_by_time(self, when: datetime, closest: str) -> int | None:
        """Return the next configured block bound."""
        self.block_calls.append((when, closest))
        return self.bounds.pop(0)

    def paged(self, **params: Any) -> list[Any] | None:
        """Return the next configured page."""
        self.page_calls.append(params)
        return self.pages.pop(0)


class FakeRelays:
    """Return fixed delivered-payload values."""

    def __init__(self, values: dict[int, int] | None = None) -> None:
        """Initialize the relay stub."""
        self.values = values or {}

    def payloads(self, pubkey: str) -> dict[int, int]:
        """Return configured values."""
        return self.values


def make_quick(
    beacon: FakeBeacon | None = None,
    scan: FakeScan | None = None,
    relays: FakeRelays | None = None,
) -> QuickNodeRewardProvider:
    """Build a QuickNode provider from test collaborators."""
    return QuickNodeRewardProvider(
        VALIDATOR,
        RECIPIENT,
        beacon=beacon or FakeBeacon(),
        scan=scan or FakeScan(),
        relays=relays or FakeRelays(),
    )


class TestRewardTypes:
    """Validate window and exact-unit behavior."""

    def test_window_requires_utc_midnights(self) -> None:
        """Reject naive, intraday, and reversed windows."""
        with pytest.raises(ValueError, match="UTC timezone"):
            RewardWindow(datetime(2026, 8, 1), datetime(2026, 8, 2))
        with pytest.raises(ValueError, match="UTC midnight"):
            RewardWindow(
                datetime(2026, 8, 1, 1, tzinfo=UTC),
                datetime(2026, 8, 2, tzinfo=UTC),
            )
        with pytest.raises(ValueError, match="precede"):
            RewardWindow(
                datetime(2026, 8, 2, tzinfo=UTC),
                datetime(2026, 8, 1, tzinfo=UTC),
            )

    def test_reward_total_is_exact(self) -> None:
        """Combine native units without floating-point loss."""
        first = RewardTotal(1_000_000_001, 2_000_000_000_000_000_001, 3)
        second = RewardTotal(4, 5, 6)
        assert first.eth == Decimal("3.000000001000000001")
        assert first + second == RewardTotal(
            1_000_000_005, 2_000_000_000_000_000_006, 9
        )


class TestDuneProvider:
    """Validate raw SQL execution and exact daily coverage."""

    @responses.activate
    def test_fetch_executes_polls_and_aggregates(
        self,
        window: RewardWindow,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Run the documented Dune execution flow."""
        monkeypatch.setenv("DUNE_POLL_SECONDS", "0")
        sql = tmp_path / "query.sql"
        sql.write_text(
            "SELECT {{validator_index}}, '{{fee_recipient}}', "
            "DATE '{{start_date}}', DATE '{{end_date}}'",
            encoding="utf-8",
        )
        responses.post(
            "https://api.dune.com/api/v1/sql/execute",
            json={"execution_id": "run-1"},
        )
        responses.get(
            "https://api.dune.com/api/v1/execution/run-1/status",
            json={"state": "QUERY_STATE_COMPLETED"},
        )
        rows = [dune_row(window.start.date() + timedelta(days=i)) for i in range(7)]
        responses.get(
            "https://api.dune.com/api/v1/execution/run-1/results",
            json={
                "state": "QUERY_STATE_COMPLETED",
                "result": {"rows": rows[:4]},
                "next_offset": 4,
            },
        )
        responses.get(
            "https://api.dune.com/api/v1/execution/run-1/results",
            json={"state": "QUERY_STATE_COMPLETED", "result": {"rows": rows[4:]}},
        )
        provider = DuneRewardProvider("key", VALIDATOR, RECIPIENT, sql_path=sql)

        assert provider.fetch([window]) == {window: RewardTotal(7, 14)}
        body = responses.calls[0].request.body
        assert isinstance(body, bytes)
        rendered = body.decode()
        assert "{{" not in rendered
        assert str(VALIDATOR) in rendered

    def test_daily_rows_reject_bad_coverage(
        self, window: RewardWindow, tmp_path: Path
    ) -> None:
        """Reject missing, duplicate, incomplete, and lossy rows."""
        provider = DuneRewardProvider(
            "key", VALIDATOR, RECIPIENT, sql_path=tmp_path / "unused"
        )
        with pytest.raises(RewardProviderError, match="coverage mismatch"):
            provider._daily_rows([], window.start.date(), window.end.date())
        row = dune_row(window.start.date())
        with pytest.raises(RewardProviderError, match="duplicate"):
            provider._daily_rows([row, row], window.start.date(), window.end.date())
        incomplete = {**row, "coverage_complete": False}
        with pytest.raises(RewardProviderError, match="incomplete"):
            provider._daily_rows(
                [incomplete], window.start.date(), window.start.date() + timedelta(1)
            )
        lossy = {**row, "consensus_reward_gwei": 1.5}
        with pytest.raises(RewardProviderError, match="exact integer"):
            provider._daily_rows(
                [lossy], window.start.date(), window.start.date() + timedelta(1)
            )

    @responses.activate
    def test_execution_failure_is_reported(
        self, window: RewardWindow, tmp_path: Path
    ) -> None:
        """Reject an HTTP failure before polling."""
        sql = tmp_path / "query.sql"
        sql.write_text("SELECT 1", encoding="utf-8")
        responses.post("https://api.dune.com/api/v1/sql/execute", status=400)
        provider = DuneRewardProvider("key", VALIDATOR, RECIPIENT, sql_path=sql)
        with pytest.raises(RewardProviderError, match="query execution failed"):
            provider.fetch([window])

    @responses.activate
    def test_execution_and_status_validation(
        self, window: RewardWindow, tmp_path: Path
    ) -> None:
        """Reject missing execution IDs, terminal states, and timeouts."""
        sql = tmp_path / "query.sql"
        sql.write_text("SELECT 1", encoding="utf-8")
        provider = DuneRewardProvider("key", VALIDATOR, RECIPIENT, sql_path=sql)
        responses.post("https://api.dune.com/api/v1/sql/execute", json={})
        with pytest.raises(RewardProviderError, match="execution ID"):
            provider.fetch([window])
        responses.get(
            "https://api.dune.com/api/v1/execution/bad/status",
            json={"state": "QUERY_STATE_FAILED"},
        )
        with pytest.raises(RewardProviderError, match="ended"):
            provider._wait("bad")
        provider.max_wait_seconds = 0
        with pytest.raises(RewardProviderError, match="timed out"):
            provider._wait("never")
        assert provider.fetch([]) == {}

    @responses.activate
    @pytest.mark.parametrize(
        ("payload", "message"),
        [
            ({"state": "QUERY_STATE_EXECUTING"}, "not complete"),
            ({"state": "QUERY_STATE_COMPLETED"}, "payload is missing"),
            (
                {"state": "QUERY_STATE_COMPLETED", "result": {"rows": "bad"}},
                "rows are malformed",
            ),
        ],
    )
    def test_result_payload_validation(
        self, payload: dict[str, Any], message: str, tmp_path: Path
    ) -> None:
        """Reject incomplete and malformed Dune result pages."""
        responses.get("https://api.dune.com/api/v1/execution/bad/results", json=payload)
        provider = DuneRewardProvider(
            "key", VALIDATOR, RECIPIENT, sql_path=tmp_path / "unused"
        )
        with pytest.raises(RewardProviderError, match=message):
            provider._results("bad")

    def test_scalar_and_date_validation(
        self, window: RewardWindow, tmp_path: Path
    ) -> None:
        """Reject nonintegral numbers and malformed Dune dates."""
        provider = DuneRewardProvider(
            "key", VALIDATOR, RECIPIENT, sql_path=tmp_path / "unused"
        )
        row = dune_row(window.start.date())
        for day in (None, "not-a-date"):
            with pytest.raises(RewardProviderError, match="day|date"):
                provider._daily_rows(
                    [{**row, "day": day}],
                    window.start.date(),
                    window.start.date() + timedelta(1),
                )
        for value in ("1.5", "not-a-number"):
            with pytest.raises(RewardProviderError, match="integer|numeric"):
                provider._daily_rows(
                    [{**row, "consensus_reward_gwei": value}],
                    window.start.date(),
                    window.start.date() + timedelta(1),
                )

    @responses.activate
    def test_non_object_json_is_rejected(self, tmp_path: Path) -> None:
        """Reject a successful HTTP response whose body is not an object."""
        responses.post("https://api.dune.com/api/v1/sql/execute", json=[])
        provider = DuneRewardProvider(
            "key", VALIDATOR, RECIPIENT, sql_path=tmp_path / "query.sql"
        )
        provider.sql_path.write_text("SELECT 1", encoding="utf-8")
        with pytest.raises(RewardProviderError, match="non-object"):
            provider.fetch(
                [
                    RewardWindow(
                        datetime(2026, 8, 1, tzinfo=UTC),
                        datetime(2026, 8, 2, tzinfo=UTC),
                    )
                ]
            )


class TestBeaconNode:
    """Validate QuickNode slot arithmetic and response checks."""

    def test_boundary_slot_uses_first_slot_after_midnight(self) -> None:
        """Map the verified August boundary to its 00:00:11 slot."""
        boundary = datetime(2026, 8, 13, tzinfo=UTC)
        slot = BeaconNode.boundary_slot(boundary)
        assert slot == 14_979_599
        assert BeaconNode.time_at(slot) == datetime(2026, 8, 13, 0, 0, 11, tzinfo=UTC)
        assert BeaconNode.slot_at(BeaconNode.time_at(slot)) == slot
        assert to_utc(C.GENESIS_TIME).tzinfo == UTC

    @responses.activate
    def test_validator_and_proposer_reads(self) -> None:
        """Parse finalized validator state and proposer headers."""
        responses.get(
            f"{BEACON}/eth/v1/beacon/states/99/validators/{VALIDATOR}",
            json={
                "finalized": True,
                "data": {
                    "index": str(VALIDATOR),
                    "balance": "133000000000",
                    "validator": {"pubkey": PUBKEY},
                },
            },
        )
        responses.get(
            f"{BEACON}/eth/v1/beacon/headers/99",
            json={"data": {"header": {"message": {"proposer_index": str(VALIDATOR)}}}},
        )
        node = BeaconNode(BEACON)
        assert node.validator(99, VALIDATOR)["balance"] == 133_000_000_000
        assert node.proposer_at(99) == VALIDATOR

    @responses.activate
    def test_rejects_unfinalized_and_missing_slots(self) -> None:
        """Distinguish an unusable state from a missed proposer slot."""
        responses.get(
            f"{BEACON}/eth/v1/beacon/states/1/validators/{VALIDATOR}",
            json={"finalized": False, "data": {}},
        )
        responses.get(f"{BEACON}/eth/v1/beacon/headers/1", status=404)
        node = BeaconNode(BEACON)
        with pytest.raises(RewardProviderError, match="not finalized"):
            node.validator(1, VALIDATOR)
        assert not node.proposer_at(1)

    @responses.activate
    @pytest.mark.parametrize(
        ("data", "message"),
        [
            (None, "no validator"),
            ({"index": "1"}, "another validator"),
            ({"index": str(VALIDATOR), "balance": "1"}, "malformed"),
            (
                {
                    "index": str(VALIDATOR),
                    "balance": "1",
                    "validator": {"pubkey": ""},
                },
                "no pubkey",
            ),
        ],
    )
    def test_validator_payload_validation(self, data: Any, message: str) -> None:
        """Reject malformed or mismatched validator state payloads."""
        responses.get(
            f"{BEACON}/eth/v1/beacon/states/2/validators/{VALIDATOR}",
            json={"finalized": True, "data": data},
        )
        with pytest.raises(RewardProviderError, match=message):
            BeaconNode(BEACON).validator(2, VALIDATOR)

    @responses.activate
    def test_transport_and_malformed_proposer_are_rejected(self) -> None:
        """Convert transport and header-shape failures to provider errors."""
        responses.get(
            f"{BEACON}/eth/v1/beacon/headers/3",
            body=requests.ConnectionError("offline"),
        )
        with pytest.raises(RewardProviderError, match="request failed"):
            BeaconNode(BEACON).proposer_at(3)
        responses.get(f"{BEACON}/eth/v1/beacon/headers/4", json={"data": {}})
        with pytest.raises(RewardProviderError, match="Malformed proposer"):
            BeaconNode(BEACON).proposer_at(4)


class TestEtherscan:
    """Validate Etherscan success classification and paging."""

    @responses.activate
    def test_list_scalar_and_paging(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Accept empty lists, page full lists, and parse scalar blocks."""
        monkeypatch.setattr(C, "ETHERSCAN_FREE_DELAY", 0)
        full = [{}] * C.ETHERSCAN_PAGE_SIZE
        responses.get(C.ETHERSCAN_URL, json={"status": "0", "result": []})
        responses.get(C.ETHERSCAN_URL, json={"status": "1", "result": full})
        responses.get(C.ETHERSCAN_URL, json={"status": "1", "result": [{}]})
        responses.get(C.ETHERSCAN_URL, json={"status": "1", "result": "123"})
        scan = Etherscan("key")
        assert scan.call(action="empty") == []
        assert len(scan.paged(action="pages") or []) == C.ETHERSCAN_PAGE_SIZE + 1
        assert scan.block_by_time(datetime(2026, 8, 13, tzinfo=UTC), "after") == 123

    @responses.activate
    def test_errors_and_missing_key_return_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Treat transport and API errors as unavailable."""
        monkeypatch.setattr(C, "ETHERSCAN_FREE_DELAY", 0)
        responses.get(C.ETHERSCAN_URL, json={"status": "0", "result": "NOTOK"})
        responses.get(C.ETHERSCAN_URL, status=500)
        scan = Etherscan("key")
        assert not scan.call(action="bad")
        assert not scan.call_scalar(action="bad")
        assert not Etherscan("").call(action="x")
        assert not Etherscan("").call_scalar(action="x")

    def test_failed_page_and_nonnumeric_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop paging on failure and reject a nonnumeric block result."""
        monkeypatch.setattr(C, "ETHERSCAN_FREE_DELAY", 0)
        scan = Etherscan("key")
        monkeypatch.setattr(scan, "call", lambda **params: None)
        assert not scan.paged(action="x")
        monkeypatch.setattr(scan, "call_scalar", lambda **params: "bad")
        assert not scan.block_by_time(datetime(2026, 8, 1), "after")


class TestRelayIndex:
    """Validate best-effort relay result filtering."""

    @responses.activate
    def test_filters_proposer_and_failed_relay(self) -> None:
        """Keep only matching proposer records from successful relays."""
        responses.get(
            "https://bad/relay/v1/data/bidtraces/proposer_payload_delivered", status=500
        )
        responses.get(
            "https://good/relay/v1/data/bidtraces/proposer_payload_delivered",
            json=[
                {"proposer_pubkey": "0xother", "slot": "1", "value": "2"},
                {"proposer_pubkey": PUBKEY, "slot": "3", "value": "4"},
            ],
        )
        assert RelayIndex(["https://bad", "https://good"]).payloads(PUBKEY) == {3: 4}

    @responses.activate
    def test_ignores_nonlist_and_nondict_payloads(self) -> None:
        """Ignore successful relay responses with unusable shapes."""
        responses.get(
            "https://one/relay/v1/data/bidtraces/proposer_payload_delivered",
            json={},
        )
        responses.get(
            "https://two/relay/v1/data/bidtraces/proposer_payload_delivered",
            json=["bad"],
        )
        assert RelayIndex(["https://one", "https://two"]).payloads(PUBKEY) == {}


class TestQuickNodeProvider:
    """Validate historical balances, capital checks, and execution rewards."""

    def test_balance_delta_and_shared_boundary_cache(
        self, window: RewardWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Use exact state deltas and read a shared boundary once."""
        prior = RewardWindow(window.start - timedelta(weeks=1), window.start)
        slots = [
            BeaconNode.boundary_slot(value)
            for value in (prior.start, window.start, window.end)
        ]
        beacon = FakeBeacon(
            {
                slots[0]: {"balance": 100, "pubkey": PUBKEY},
                slots[1]: {"balance": 110, "pubkey": PUBKEY},
                slots[2]: {"balance": 130, "pubkey": PUBKEY},
            }
        )
        provider = make_quick(beacon=beacon)
        monkeypatch.setattr(provider, "capital_moved", lambda *args: False)
        monkeypatch.setattr(provider, "execution_rewards", lambda *args: 7)

        assert provider.fetch([prior, window]) == {
            prior: RewardTotal(10, 7),
            window: RewardTotal(20, 7),
        }
        assert beacon.state_calls.count(slots[1]) == 1

    def test_capital_movement_or_unknown_omits_window(
        self, window: RewardWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Never treat an ambiguous balance delta as rewards."""
        slots = [
            BeaconNode.boundary_slot(value) for value in (window.start, window.end)
        ]
        beacon = FakeBeacon({slot: {"balance": 1, "pubkey": PUBKEY} for slot in slots})
        provider = make_quick(beacon=beacon)
        monkeypatch.setattr(provider, "capital_moved", lambda *args: True)
        assert provider.fetch([window]) == {}
        monkeypatch.setattr(provider, "capital_moved", lambda *args: None)
        assert provider.fetch([window]) == {}

    def test_pubkey_change_omits_window(self, window: RewardWindow) -> None:
        """Reject boundaries that resolve to different validator identities."""
        slots = [
            BeaconNode.boundary_slot(value) for value in (window.start, window.end)
        ]
        beacon = FakeBeacon(
            {
                slots[0]: {"balance": 1, "pubkey": PUBKEY},
                slots[1]: {"balance": 2, "pubkey": "0xother"},
            }
        )
        assert make_quick(beacon=beacon).fetch([window]) == {}

    def test_capital_checks_deposit_withdrawal_and_failure(
        self, window: RewardWindow
    ) -> None:
        """Detect validator deposits and withdrawals and propagate unknown scans."""
        deposit = [{"data": "0x" + PUBKEY.removeprefix("0x") + "00"}]
        assert (
            make_quick(scan=FakeScan([deposit])).capital_moved(window, PUBKEY) is True
        )
        withdrawal_scan = FakeScan([[], [{"validatorIndex": str(VALIDATOR)}]])
        assert make_quick(scan=withdrawal_scan).capital_moved(window, PUBKEY) is True
        assert not make_quick(scan=FakeScan([None])).capital_moved(window, PUBKEY)

    def test_capital_clear_controller_and_range_failure(
        self, window: RewardWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Prove a clear range, detect controller requests, and propagate failures."""
        monkeypatch.setattr(C, "STAKING_CONTROLLERS", "")
        provider = make_quick(scan=FakeScan([[], []]))
        assert provider.capital_moved(window, PUBKEY) is False
        assert provider._block_range(window) == (100, 200)
        monkeypatch.setattr(C, "STAKING_CONTROLLERS", RECIPIENT)
        pages = [[], [], [{"to": C.CONSOLIDATION_REQUEST_PREDEPLOY}]]
        assert make_quick(scan=FakeScan(pages)).capital_moved(window, PUBKEY) is True
        assert not make_quick(scan=FakeScan(bounds=(None, 2))).capital_moved(
            window, PUBKEY
        )

    def test_candidates_filter_direction_time_and_value(
        self, window: RewardWindow
    ) -> None:
        """Collect only positive inbound transfers within the window."""
        inside = str(int((window.start + timedelta(days=1)).timestamp()))
        outside = str(int((window.end + timedelta(days=1)).timestamp()))
        pages = [
            [
                {
                    "timeStamp": inside,
                    "to": RECIPIENT,
                    "value": "5",
                    "blockNumber": "10",
                },
                {
                    "timeStamp": inside,
                    "to": "0xother",
                    "value": "6",
                    "blockNumber": "11",
                },
                {
                    "timeStamp": outside,
                    "to": RECIPIENT,
                    "value": "7",
                    "blockNumber": "12",
                },
            ],
            [],
            [{"timeStamp": inside, "blockNumber": "20", "blockReward": "8"}],
        ]
        assert make_quick(scan=FakeScan(pages)).candidates(window) == (
            {10: [pages[0][0]]},
            {20: pages[2][0]},
        )

    def test_candidate_failures_are_unknown(self, window: RewardWindow) -> None:
        """Reject incomplete ranges, pages, and malformed records."""
        assert not make_quick(scan=FakeScan(bounds=(None, 2))).candidates(window)
        assert not make_quick(scan=FakeScan([None])).candidates(window)
        assert not make_quick(scan=FakeScan([["bad"]])).candidates(window)
        assert not make_quick(scan=FakeScan([[], [], None])).candidates(window)
        assert not make_quick(scan=FakeScan([[], [], ["bad"]])).candidates(window)

    def test_execution_uses_relay_coinbase_and_final_transfer(
        self, window: RewardWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Select each supported execution-payment source."""
        stamp = int((window.start + timedelta(days=1)).timestamp())
        slot = BeaconNode.slot_at(to_utc(stamp))
        transfers = {
            1: [
                {
                    "timeStamp": str(stamp),
                    "value": "3",
                    "hash": "a",
                    "transactionIndex": "1",
                }
            ],
            2: [
                {
                    "timeStamp": str(stamp),
                    "value": "5",
                    "hash": "b",
                    "transactionIndex": "2",
                }
            ],
            3: [
                {
                    "timeStamp": str(stamp),
                    "value": "7",
                    "hash": "early",
                    "transactionIndex": "1",
                },
                {
                    "timeStamp": str(stamp),
                    "value": "11",
                    "hash": "last",
                    "transactionIndex": "9",
                },
            ],
        }
        coinbase = {2: {"timeStamp": str(stamp), "blockReward": "13"}}
        beacon = FakeBeacon(proposers={slot: VALIDATOR})
        provider = make_quick(beacon=beacon, relays=FakeRelays({slot: 17}))
        monkeypatch.setattr(provider, "candidates", lambda value: (transfers, coinbase))
        assert provider.execution_rewards(window, PUBKEY) == 51

        provider = make_quick(beacon=beacon)
        monkeypatch.setattr(provider, "candidates", lambda value: (transfers, coinbase))
        assert provider.execution_rewards(window, PUBKEY) == 27

    def test_execution_zero_unrelated_and_missing_proposer(
        self, window: RewardWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Prove zero, exclude another proposer, and reject missing attribution."""
        provider = make_quick()
        monkeypatch.setattr(provider, "candidates", lambda value: ({}, {}))
        assert provider.execution_rewards(window, PUBKEY) == 0
        stamp = int((window.start + timedelta(days=1)).timestamp())
        slot = BeaconNode.slot_at(to_utc(stamp))
        transfers = {1: [{"timeStamp": str(stamp), "value": "3"}]}
        provider = make_quick(beacon=FakeBeacon(proposers={slot: 2}))
        monkeypatch.setattr(provider, "candidates", lambda value: (transfers, {}))
        assert provider.execution_rewards(window, PUBKEY) == 0
        provider = make_quick(beacon=FakeBeacon())
        monkeypatch.setattr(provider, "candidates", lambda value: (transfers, {}))
        with pytest.raises(RewardProviderError, match="Proposer unavailable"):
            provider.execution_rewards(window, PUBKEY)

    def test_execution_rejects_incomplete_candidates(
        self, window: RewardWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Treat failed payment enumeration as provider unavailability."""
        provider = make_quick()
        monkeypatch.setattr(provider, "candidates", lambda value: None)
        with pytest.raises(RewardProviderError, match="could not be enumerated"):
            provider.execution_rewards(window, PUBKEY)

    def test_coinbase_timestamp_is_used(
        self, window: RewardWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Use a mined-block timestamp when no transfer carries one."""
        stamp = int((window.start + timedelta(days=1)).timestamp())
        slot = BeaconNode.slot_at(to_utc(stamp))
        coinbase = {1: {"timeStamp": str(stamp), "blockReward": "9"}}
        provider = make_quick(beacon=FakeBeacon(proposers={slot: VALIDATOR}))
        monkeypatch.setattr(provider, "candidates", lambda value: ({}, coinbase))
        assert provider.execution_rewards(window, PUBKEY) == 9

    def test_block_payment_without_indices_and_timestamp_failure(
        self, window: RewardWindow, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Use parent hashes and reject records without block time."""
        entries = [
            {"value": "3", "hash": "a"},
            {"value": "4", "hash": "b"},
            {"value": "6", "hash": "b"},
        ]
        assert QuickNodeRewardProvider.block_payment(entries) == 10
        assert QuickNodeRewardProvider.block_payment([]) == 0
        provider = make_quick()
        monkeypatch.setattr(provider, "candidates", lambda value: ({1: entries}, {}))
        with pytest.raises(RewardProviderError, match="no timestamp"):
            provider.execution_rewards(window, PUBKEY)


class TestBlending:
    """Validate independent fallback and averaging behavior."""

    def test_average_and_same_window(self, window: RewardWindow) -> None:
        """Average complete providers that receive the identical window."""
        dune = StubProvider({window: RewardTotal(40_000_000)})
        quick = StubProvider({window: RewardTotal(42_000_000)})
        estimate = StakingRewards({"dune": dune, "quicknode": quick}).fetch([window])[
            window
        ]
        assert estimate.eth == Decimal("0.041")
        assert estimate.sources == ("dune", "quicknode")
        assert dune.windows == quick.windows == [window]

    def test_single_provider_and_dual_failure(self, window: RewardWindow) -> None:
        """Use one complete result and omit a window after dual failure."""
        failing = StubProvider(error=RewardProviderError("offline"))
        good = StubProvider({window: RewardTotal(5_000_000)})
        assert StakingRewards({"dune": failing, "quicknode": good}).fetch([window])[
            window
        ].eth == Decimal("0.005")
        assert (
            StakingRewards({"dune": failing, "quicknode": StubProvider()}).fetch(
                [window]
            )
            == {}
        )

    def test_positive_dune_ignores_zero_quicknode(
        self, window: RewardWindow, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Use positive Dune rewards without averaging in a QuickNode zero."""
        providers = {
            "dune": StubProvider({window: RewardTotal(40_000_000)}),
            "quicknode": StubProvider({window: RewardTotal(0)}),
        }
        with caplog.at_level(logging.WARNING):
            estimate = StakingRewards(providers).fetch([window])[window]
        assert estimate.eth == Decimal("0.04")
        assert estimate.source_values == (("dune", Decimal("0.04")),)
        assert "Ignoring zero QuickNode rewards" in caplog.text

    def test_material_disagreement_warns_but_averages(
        self, window: RewardWindow, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Log a material difference without discarding either value."""
        providers = {
            "dune": StubProvider({window: RewardTotal(10_000_000)}),
            "quicknode": StubProvider({window: RewardTotal(20_000_000)}),
        }
        with caplog.at_level(logging.WARNING):
            result = StakingRewards(providers).fetch([window])[window]
        assert result.eth == Decimal("0.015")
        assert "rewards differ" in caplog.text

    def test_capital_change_is_reported(
        self, window: RewardWindow, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Preserve valid Dune rewards while reporting excluded capital."""
        provider = StubProvider({window: RewardTotal(1, 0, 9)})
        with caplog.at_level(logging.WARNING):
            estimate = StakingRewards({"dune": provider}).fetch([window])[window]
        assert estimate.eth == Decimal("0.000000001")
        assert "capital change" in caplog.text

    def test_configured_provider_validation(
        self, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
    ) -> None:
        """Use the new environment-backed constants and validate them."""
        monkeypatch.setattr(C, "VALIDATOR", str(VALIDATOR))
        monkeypatch.setattr(C, "ETH_ADDR", RECIPIENT)
        monkeypatch.setattr(C, "DUNE", "key")
        dune = mocker.patch("hyperdrive.Staking.DuneRewardProvider")
        quick = mocker.patch("hyperdrive.Staking.QuickNodeRewardProvider")
        rewards = StakingRewards()
        assert list(rewards.providers) == ["dune", "quicknode"]
        dune.assert_called_once_with("key", VALIDATOR, RECIPIENT)
        quick.assert_called_once_with(VALIDATOR, RECIPIENT)
        monkeypatch.setattr(C, "VALIDATOR", "invalid")
        with pytest.raises(RewardProviderError, match="integer"):
            StakingRewards(validator_index=None, fee_recipient=RECIPIENT)

    def test_invalid_explicit_configuration(self) -> None:
        """Reject negative validators and malformed fee recipients."""
        with pytest.raises(RewardProviderError, match="non-negative"):
            StakingRewards(validator_index=-1, fee_recipient=RECIPIENT)
        with pytest.raises(RewardProviderError, match="ETH_ADDR"):
            StakingRewards(validator_index=VALIDATOR, fee_recipient="bad")
