"""Tests for hyperdrive.Staking."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import pytest
import responses

from hyperdrive import Constants as C
from hyperdrive.Staking import (
    BALANCE,
    EFFECTIVE,
    LEDGER_COLS,
    QUEUED,
    SLOT,
    BeaconNode,
    Etherscan,
    RelayIndex,
    StakingLedger,
    StakingRewards,
    market,
    to_naive_utc,
)

BEACON = "https://beacon.test"
PUBKEY = "0x" + "ab" * 48
VALIDATOR = "690345"
RECIPIENT = "0x75603aeb09ec1d9849ad31c7d660605999a46834"
GWEI = C.GWEI_PER_ETH


def slot_ts(slot: int) -> int:
    """Get the unix timestamp of a slot's start."""
    return C.GENESIS_TIME + slot * C.SECONDS_PER_SLOT


def slot_time(slot: int) -> datetime:
    """Get the naive UTC start time of a slot."""
    return to_naive_utc(slot_ts(slot))


def scan_json(result: Any, status: str = "1") -> dict[str, Any]:
    """Build an Etherscan style response body."""
    return {"status": status, "message": "OK", "result": result}


class FakeLedger:
    """Ledger stub returning a fixed snapshot pair."""

    def __init__(self, pair: tuple[pd.Series, pd.Series] | None) -> None:
        """Initialize the stub."""
        self.pair = pair

    def boundaries(self, start: datetime, end: datetime) -> Any:
        """Boundaries helper for these tests."""
        return self.pair


class FakeBeacon:
    """Beacon stub with a fixed proposer map."""

    def __init__(self, proposers: dict[int, int] | None = None) -> None:
        """Initialize the stub."""
        self.proposers = proposers or {}

    def slot_at(self, when: datetime) -> int:
        """Slot at helper for these tests."""
        seconds = int(when.replace(tzinfo=UTC).timestamp()) - C.GENESIS_TIME
        return seconds // C.SECONDS_PER_SLOT

    def proposer_at(self, slot: int) -> int | None:
        """Proposer at helper for these tests."""
        return self.proposers.get(slot)

    def validator(self, state_id: Any, validator_id: str) -> dict[str, Any]:
        """Validator helper for these tests."""
        return {"balance": 0, "effective_balance": 0, "pubkey": PUBKEY}


class FakeRelays:
    """Relay stub returning a fixed slot to value map."""

    def __init__(self, delivered: dict[int, int] | None = None) -> None:
        """Initialize the stub."""
        self.delivered = delivered or {}

    def payloads(self, pubkey: str) -> dict[int, int]:
        """Payloads helper for these tests."""
        return self.delivered


def make_snapshot(
    when: datetime, slot: int, balance: int, queued: bool = False
) -> pd.Series:
    """Build a ledger row."""
    return pd.Series(
        {
            C.TIME: pd.Timestamp(when),
            SLOT: slot,
            BALANCE: balance,
            EFFECTIVE: 132 * GWEI,
            QUEUED: queued,
        }
    )


def make_rewards(**kwargs: Any) -> StakingRewards:
    """Build a StakingRewards with stubbed collaborators."""
    defaults: dict[str, Any] = {
        "validator_id": VALIDATOR,
        "fee_recipient": RECIPIENT,
        "beacon": FakeBeacon(),
        "scan": Etherscan(key="k"),
        "relays": FakeRelays(),
        "ledger": FakeLedger(None),
    }
    defaults.update(kwargs)
    return StakingRewards(**defaults)


class TestEtherscanClassification:
    """Etherscan reports empty results and errors with the same status."""

    @responses.activate
    def test_empty_list_is_success(self) -> None:
        """Test empty list is success."""
        responses.add(
            responses.GET, C.ETHERSCAN_URL, json=scan_json([], status="0"), status=200
        )
        assert Etherscan(key="k").call(module="account", action="txlist") == []

    @responses.activate
    def test_string_result_is_failure(self) -> None:
        """Test string result is failure."""
        responses.add(
            responses.GET,
            C.ETHERSCAN_URL,
            json=scan_json("Missing/Invalid API Key", status="0"),
            status=200,
        )
        assert Etherscan(key="k").call(module="account", action="txlist") is None

    def test_missing_key_is_failure(self) -> None:
        """Test missing key is failure."""
        assert Etherscan(key="").call(module="account", action="txlist") is None

    @responses.activate
    def test_paged_consumes_every_page(self) -> None:
        """Test paged consumes every page."""
        full = [{"blockNumber": str(i)} for i in range(C.ETHERSCAN_PAGE_SIZE)]
        responses.add(responses.GET, C.ETHERSCAN_URL, json=scan_json(full), status=200)
        responses.add(
            responses.GET, C.ETHERSCAN_URL, json=scan_json([{"blockNumber": "x"}])
        )
        records = Etherscan(key="k").paged(module="account", action="txlist")
        assert records is not None
        assert len(records) == C.ETHERSCAN_PAGE_SIZE + 1

    @responses.activate
    def test_paged_fails_when_a_page_fails(self) -> None:
        """Test paged fails when a page fails."""
        full = [{"blockNumber": str(i)} for i in range(C.ETHERSCAN_PAGE_SIZE)]
        responses.add(responses.GET, C.ETHERSCAN_URL, json=scan_json(full), status=200)
        responses.add(
            responses.GET, C.ETHERSCAN_URL, json=scan_json("NOTOK", status="0")
        )
        assert Etherscan(key="k").paged(module="account", action="txlist") is None


class TestBeaconNode:
    """Slot arithmetic and state reads."""

    def test_slot_time_roundtrip(self) -> None:
        """Test slot time roundtrip."""
        node = BeaconNode(BEACON)
        assert node.slot_at(node.time_at(14909268)) == 14909268

    def test_time_at_matches_verified_slot(self) -> None:
        """Test time at matches verified slot."""
        # Slot 14909268 carries execution payload timestamp 1785735239.
        assert BeaconNode(BEACON).time_at(14909268) == to_naive_utc(1785735239)

    @responses.activate
    def test_validator_read(self) -> None:
        """Test validator read."""
        responses.add(
            responses.GET,
            f"{BEACON}/eth/v1/beacon/states/99/validators/{VALIDATOR}",
            json={
                "data": {
                    "balance": "133000000000",
                    "validator": {
                        "pubkey": PUBKEY,
                        "effective_balance": "132000000000",
                    },
                }
            },
        )
        state = BeaconNode(BEACON).validator(99, VALIDATOR)
        assert state == {
            "balance": 133000000000,
            "effective_balance": 132000000000,
            "pubkey": PUBKEY,
        }

    @responses.activate
    def test_proposer_none_on_missed_slot(self) -> None:
        """Test proposer none on missed slot."""
        responses.add(
            responses.GET, f"{BEACON}/eth/v1/beacon/headers/5", json={}, status=404
        )
        assert BeaconNode(BEACON).proposer_at(5) is None

    @responses.activate
    def test_queued_capital_detects_pubkey_in_deposits(self) -> None:
        """Test queued capital detects pubkey in deposits."""
        base = f"{BEACON}/eth/v1/beacon/states/head"
        responses.add(
            responses.GET,
            f"{base}/pending_deposits",
            json={"data": [{"pubkey": PUBKEY, "amount": "1"}]},
        )
        assert BeaconNode(BEACON).queued_capital(VALIDATOR, PUBKEY) is True

    @responses.activate
    def test_queued_capital_detects_consolidation(self) -> None:
        """Test queued capital detects consolidation."""
        base = f"{BEACON}/eth/v1/beacon/states/head"
        responses.add(responses.GET, f"{base}/pending_deposits", json={"data": []})
        responses.add(
            responses.GET,
            f"{base}/pending_consolidations",
            json={"data": [{"source_index": "1", "target_index": VALIDATOR}]},
        )
        assert BeaconNode(BEACON).queued_capital(VALIDATOR, PUBKEY) is True

    @responses.activate
    def test_queued_capital_clear(self) -> None:
        """Test queued capital clear."""
        base = f"{BEACON}/eth/v1/beacon/states/head"
        responses.add(responses.GET, f"{base}/pending_deposits", json={"data": []})
        responses.add(
            responses.GET, f"{base}/pending_consolidations", json={"data": []}
        )
        responses.add(
            responses.GET,
            f"{base}/pending_partial_withdrawals",
            json={"data": [{"validator_index": "1", "amount": "1"}]},
        )
        assert BeaconNode(BEACON).queued_capital(VALIDATOR, PUBKEY) is False


class TestRelayIndex:
    """Relays vary in whether they honor the proposer filter."""

    @responses.activate
    def test_ignores_unmatched_proposers_and_relay_errors(self) -> None:
        """Test ignores unmatched proposers and relay errors."""
        good = "https://good.relay"
        bad = "https://bad.relay"
        path = "/relay/v1/data/bidtraces/proposer_payload_delivered"
        responses.add(
            responses.GET,
            f"{good}{path}",
            json=[
                {"slot": "100", "proposer_pubkey": PUBKEY, "value": "5"},
                {"slot": "101", "proposer_pubkey": "0xdead", "value": "9"},
            ],
        )
        responses.add(responses.GET, f"{bad}{path}", json={}, status=400)
        delivered = RelayIndex([good, bad]).payloads(PUBKEY)
        assert delivered == {100: 5}


class TestLedgerBoundaries:
    """Row to snapshot mapping must be unambiguous."""

    def ledger_with(self, times: list[datetime]) -> StakingLedger:
        """Ledger with helper for these tests."""
        ledger = StakingLedger(VALIDATOR)
        rows = [
            {
                C.TIME: pd.Timestamp(t),
                SLOT: 1000 + i,
                BALANCE: 100 * GWEI + i,
                EFFECTIVE: 132 * GWEI,
                QUEUED: False,
            }
            for i, t in enumerate(times)
        ]
        frame = pd.DataFrame(rows, columns=pd.Index(LEDGER_COLS))
        ledger.load = lambda: frame  # type: ignore[method-assign]
        return ledger

    def test_selects_pair_around_row(self) -> None:
        """Test selects pair around row."""
        end = datetime(2026, 8, 10)
        start = end - timedelta(weeks=1)
        ledger = self.ledger_with(
            [start + timedelta(hours=21), end + timedelta(hours=21)]
        )
        pair = ledger.boundaries(start, end)
        assert pair is not None
        before, after = pair
        assert before[SLOT] == 1000
        assert after[SLOT] == 1001

    def test_rejects_dropped_run(self) -> None:
        """Test rejects dropped run."""
        # The run that should have closed this row never happened, so the next
        # snapshot is a week late and must not be borrowed.
        end = datetime(2026, 8, 10)
        start = end - timedelta(weeks=1)
        ledger = self.ledger_with([start, end + timedelta(days=7)])
        assert ledger.boundaries(start, end) is None

    def test_rejects_single_snapshot(self) -> None:
        """Test rejects single snapshot."""
        end = datetime(2026, 8, 10)
        ledger = self.ledger_with([end])
        assert ledger.boundaries(end - timedelta(weeks=1), end) is None


class TestConsensusRewards:
    """Balance delta with capital guards."""

    def pair(self, queued: bool = False) -> tuple[pd.Series, pd.Series]:
        """Pair helper for these tests."""
        end = datetime(2026, 8, 10, 21)
        start = end - timedelta(weeks=1)
        return (
            make_snapshot(start, 1000, 133_000_000_000),
            make_snapshot(end, 1001, 133_045_800_000, queued=queued),
        )

    def test_positive_delta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test positive delta."""
        rewards = make_rewards(ledger=FakeLedger(self.pair()))
        monkeypatch.setattr(rewards, "capital_moved", lambda *a: False)
        value = rewards.consensus_rewards(datetime(2026, 8, 3), datetime(2026, 8, 10))
        assert value == Decimal("0.0458")

    def test_negative_delta_is_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test negative delta is preserved."""
        end = datetime(2026, 8, 10, 21)
        start = end - timedelta(weeks=1)
        pair = (
            make_snapshot(start, 1000, 133_000_000_000),
            make_snapshot(end, 1001, 132_990_000_000),
        )
        rewards = make_rewards(ledger=FakeLedger(pair))
        monkeypatch.setattr(rewards, "capital_moved", lambda *a: False)
        value = rewards.consensus_rewards(datetime(2026, 8, 3), datetime(2026, 8, 10))
        assert value == Decimal("-0.01")

    def test_queued_capital_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test queued capital blocks."""
        rewards = make_rewards(ledger=FakeLedger(self.pair(queued=True)))
        monkeypatch.setattr(rewards, "capital_moved", lambda *a: False)
        assert (
            rewards.consensus_rewards(datetime(2026, 8, 3), datetime(2026, 8, 10))
            is None
        )

    def test_capital_move_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test capital move blocks."""
        rewards = make_rewards(ledger=FakeLedger(self.pair()))
        monkeypatch.setattr(rewards, "capital_moved", lambda *a: True)
        assert (
            rewards.consensus_rewards(datetime(2026, 8, 3), datetime(2026, 8, 10))
            is None
        )

    def test_unknown_capital_blocks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test unknown capital blocks."""
        rewards = make_rewards(ledger=FakeLedger(self.pair()))
        monkeypatch.setattr(rewards, "capital_moved", lambda *a: None)
        assert (
            rewards.consensus_rewards(datetime(2026, 8, 3), datetime(2026, 8, 10))
            is None
        )

    def test_missing_ledger_pair_blocks(self) -> None:
        """Test missing ledger pair blocks."""
        rewards = make_rewards(ledger=FakeLedger(None))
        assert (
            rewards.consensus_rewards(datetime(2026, 8, 3), datetime(2026, 8, 10))
            is None
        )


class TestExecutionRewards:
    """Attribution to blocks this validator actually proposed."""

    def window(self) -> tuple[datetime, datetime]:
        """Window helper for these tests."""
        return slot_time(1000), slot_time(2000)

    def test_no_payments_is_a_proven_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test no payments is a proven zero."""
        rewards = make_rewards()
        monkeypatch.setattr(rewards, "candidates", lambda s, e: ({}, {}))
        start, end = self.window()
        assert rewards.execution_rewards(start, end) == Decimal(0)

    def test_candidate_failure_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test candidate failure is unknown."""
        rewards = make_rewards()
        monkeypatch.setattr(rewards, "candidates", lambda s, e: None)
        start, end = self.window()
        assert rewards.execution_rewards(start, end) is None

    def test_relay_value_used_for_our_block(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test relay value used for our block."""
        slot = 1500
        transfers = {
            777: [
                {
                    "blockNumber": "777",
                    "to": RECIPIENT,
                    "value": "1",
                    "hash": "0xa",
                    "transactionIndex": "9",
                    "timeStamp": str(slot_ts(slot)),
                }
            ]
        }
        rewards = make_rewards(
            beacon=FakeBeacon({slot: int(VALIDATOR)}),
            relays=FakeRelays({slot: 10**17}),
        )
        monkeypatch.setattr(rewards, "candidates", lambda s, e: (transfers, {}))
        monkeypatch.setattr(rewards, "pubkey", lambda: PUBKEY)
        start, end = self.window()
        assert rewards.execution_rewards(start, end) == Decimal("0.1")

    def test_block_from_another_proposer_is_excluded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test block from another proposer is excluded."""
        slot = 1500
        transfers = {
            777: [
                {
                    "blockNumber": "777",
                    "to": RECIPIENT,
                    "value": str(10**18),
                    "hash": "0xa",
                    "transactionIndex": "9",
                    "timeStamp": str(slot_ts(slot)),
                }
            ]
        }
        rewards = make_rewards(beacon=FakeBeacon({slot: 111}))
        monkeypatch.setattr(rewards, "candidates", lambda s, e: (transfers, {}))
        monkeypatch.setattr(rewards, "pubkey", lambda: PUBKEY)
        start, end = self.window()
        assert rewards.execution_rewards(start, end) == Decimal(0)

    def test_self_built_block_uses_block_reward(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test self built block uses block reward."""
        slot = 1500
        coinbase = {
            777: {
                "blockNumber": "777",
                "blockReward": str(3 * 10**16),
                "timeStamp": str(slot_ts(slot)),
            }
        }
        rewards = make_rewards(beacon=FakeBeacon({slot: int(VALIDATOR)}))
        monkeypatch.setattr(rewards, "candidates", lambda s, e: ({}, coinbase))
        monkeypatch.setattr(rewards, "pubkey", lambda: PUBKEY)
        start, end = self.window()
        assert rewards.execution_rewards(start, end) == Decimal("0.03")

    def test_end_of_block_payment_when_no_relay_covers_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test end of block payment when no relay covers it."""
        # An unrelated transfer earlier in the block must not be counted.
        slot = 1500
        stamp = str(slot_ts(slot))
        transfers = {
            777: [
                {
                    "blockNumber": "777",
                    "to": RECIPIENT,
                    "value": str(10**18),
                    "hash": "0xearly",
                    "transactionIndex": "2",
                    "timeStamp": stamp,
                },
                {
                    "blockNumber": "777",
                    "to": RECIPIENT,
                    "value": str(2 * 10**16),
                    "hash": "0xlast",
                    "transactionIndex": "80",
                    "timeStamp": stamp,
                },
            ]
        }
        rewards = make_rewards(beacon=FakeBeacon({slot: int(VALIDATOR)}))
        monkeypatch.setattr(rewards, "candidates", lambda s, e: (transfers, {}))
        monkeypatch.setattr(rewards, "pubkey", lambda: PUBKEY)
        start, end = self.window()
        assert rewards.execution_rewards(start, end) == Decimal("0.02")

    def test_internal_transfer_shares_parent_transaction(self) -> None:
        """Test internal transfer shares parent transaction."""
        entries = [
            {"value": "5", "hash": "0xlast", "transactionIndex": "80"},
            {"value": "7", "hash": "0xlast", "transactionIndex": "80"},
            {"value": "99", "hash": "0xother", "transactionIndex": "3"},
        ]
        assert make_rewards().block_payment(entries) == 12

    def test_missing_fee_recipient_is_unknown(self) -> None:
        """Test missing fee recipient is unknown."""
        rewards = make_rewards(fee_recipient="")
        start, end = self.window()
        assert rewards.execution_rewards(start, end) is None


class TestCapitalMoved:
    """Capital detection over the measured interval."""

    def scan_sequence(self, *bodies: dict[str, Any]) -> None:
        """Scan sequence helper for these tests."""
        for body in bodies:
            responses.add(responses.GET, C.ETHERSCAN_URL, json=body, status=200)

    @responses.activate
    def test_deposit_matching_pubkey_detected(self) -> None:
        """Test deposit matching pubkey detected."""
        stripped = PUBKEY.removeprefix("0x")
        self.scan_sequence(
            scan_json("100"),
            scan_json("200"),
            scan_json([{"data": f"0x0000{stripped}0000"}]),
        )
        rewards = make_rewards()
        assert rewards.capital_moved(
            datetime(2026, 8, 3), datetime(2026, 8, 10), PUBKEY
        )

    @responses.activate
    def test_deposit_for_another_validator_ignored(self) -> None:
        """Test deposit for another validator ignored."""
        self.scan_sequence(
            scan_json("100"),
            scan_json("200"),
            scan_json([{"data": "0x" + "cd" * 48}]),
            scan_json([]),
        )
        rewards = make_rewards()
        moved = rewards.capital_moved(
            datetime(2026, 8, 3), datetime(2026, 8, 10), PUBKEY
        )
        assert moved is False

    @responses.activate
    def test_beacon_withdrawal_detected(self) -> None:
        """Test beacon withdrawal detected."""
        self.scan_sequence(
            scan_json("100"),
            scan_json("200"),
            scan_json([]),
            scan_json([{"validatorIndex": VALIDATOR, "amount": "1"}]),
        )
        rewards = make_rewards()
        assert rewards.capital_moved(
            datetime(2026, 8, 3), datetime(2026, 8, 10), PUBKEY
        )

    @responses.activate
    def test_scan_failure_is_unknown(self) -> None:
        """Test scan failure is unknown."""
        self.scan_sequence(scan_json("Max rate limit reached", status="0"))
        rewards = make_rewards()
        moved = rewards.capital_moved(
            datetime(2026, 8, 3), datetime(2026, 8, 10), PUBKEY
        )
        assert moved is None


class TestUnits:
    """Money stays exact."""

    def test_gwei_to_eth_is_exact(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test gwei to eth is exact."""
        end = datetime(2026, 8, 10, 21)
        start = end - timedelta(weeks=1)
        pair = (
            make_snapshot(start, 1000, 1),
            make_snapshot(end, 1001, 2),
        )
        rewards = make_rewards(ledger=FakeLedger(pair))
        monkeypatch.setattr(rewards, "capital_moved", lambda *a: False)
        value = rewards.consensus_rewards(start, end)
        assert value == Decimal(1) / Decimal(10**9)
        assert isinstance(value, Decimal)


class TestLedgerCaching:
    """The ledger is read once per run rather than per row."""

    def test_load_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test load is cached across repeated reads."""
        calls = {"n": 0}
        frame = pd.DataFrame(columns=pd.Index(LEDGER_COLS))

        def fake_load_csv(path: str) -> pd.DataFrame:
            calls["n"] += 1
            return frame

        ledger = StakingLedger(VALIDATOR)
        monkeypatch.setattr(market().reader, "load_csv", fake_load_csv)
        ledger.load()
        ledger.load()
        assert calls["n"] == 1


class TestCandidates:
    """On-chain enumeration of payments to the fee recipient."""

    def scan_sequence(self, *bodies: dict[str, Any]) -> None:
        """Queue Etherscan responses in call order."""
        for body in bodies:
            responses.add(responses.GET, C.ETHERSCAN_URL, json=body, status=200)

    @responses.activate
    def test_collects_inbound_transfers_and_mined_blocks(self) -> None:
        """Test collects inbound transfers and mined blocks."""
        stamp = str(slot_ts(1500))
        self.scan_sequence(
            scan_json("100"),  # block_by_time after
            scan_json("200"),  # block_by_time before
            scan_json(
                [
                    {
                        "blockNumber": "150",
                        "to": RECIPIENT,
                        "value": "5",
                        "hash": "0xa",
                        "transactionIndex": "1",
                        "timeStamp": stamp,
                    },
                    # Outbound spend from the same wallet must be ignored.
                    {
                        "blockNumber": "151",
                        "to": "0xsomeoneelse",
                        "value": "9",
                        "hash": "0xb",
                        "timeStamp": stamp,
                    },
                ]
            ),
            scan_json([]),  # txlistinternal
            scan_json([{"blockNumber": "160", "blockReward": "7", "timeStamp": stamp}]),
        )
        found = make_rewards().candidates(slot_time(1000), slot_time(2000))
        assert found is not None
        transfers, coinbase = found
        assert list(transfers) == [150]
        assert list(coinbase) == [160]

    @responses.activate
    def test_block_range_failure_is_unknown(self) -> None:
        """Test block range failure is unknown."""
        self.scan_sequence(scan_json("NOTOK", status="0"))
        assert make_rewards().candidates(slot_time(1000), slot_time(2000)) is None

    @responses.activate
    def test_mined_block_outside_window_dropped(self) -> None:
        """Test mined block outside window dropped."""
        self.scan_sequence(
            scan_json("100"),
            scan_json("200"),
            scan_json([]),
            scan_json([]),
            scan_json(
                [
                    {
                        "blockNumber": "160",
                        "blockReward": "7",
                        "timeStamp": str(slot_ts(5000)),
                    }
                ]
            ),
        )
        found = make_rewards().candidates(slot_time(1000), slot_time(2000))
        assert found == ({}, {})


class TestRecordSnapshot:
    """Snapshot capture writes one row per finalized slot."""

    def test_records_and_deduplicates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test records and deduplicates repeated runs."""
        saved: list[pd.DataFrame] = []
        ledger = StakingLedger(VALIDATOR)
        ledger.cached = pd.DataFrame(columns=pd.Index(LEDGER_COLS))
        monkeypatch.setattr(
            market().writer, "save_csv", lambda path, df: saved.append(df) or True
        )

        class Node(FakeBeacon):
            """Beacon stub returning a fixed finalized snapshot."""

            def finalized_slot(self) -> int:
                """Return a fixed finalized slot."""
                return 1500

            def time_at(self, slot: int) -> datetime:
                """Return the slot start time."""
                return slot_time(slot)

            def validator(self, state_id: Any, validator_id: str) -> dict[str, Any]:
                """Return a fixed validator state."""
                return {
                    "balance": 133 * GWEI,
                    "effective_balance": 132 * GWEI,
                    "pubkey": PUBKEY,
                }

            def queued_capital(self, validator_id: str, pubkey: str) -> bool:
                """Report no queued capital."""
                return False

        rewards = make_rewards(beacon=Node(), ledger=ledger)
        first = rewards.record_snapshot()
        assert len(first) == 1
        assert first.iloc[0][SLOT] == 1500
        # A second run at the same finalized slot must not duplicate the row.
        second = rewards.record_snapshot()
        assert len(second) == 1
        assert len(saved) == 1

    def test_pubkey_failure_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test pubkey failure is none."""

        class Broken(FakeBeacon):
            """Beacon stub whose validator read fails."""

            def validator(self, state_id: Any, validator_id: str) -> dict[str, Any]:
                """Raise to simulate an unreachable node."""
                raise ValueError("unreachable")

        assert make_rewards(beacon=Broken()).pubkey() is None


class TestUncoveredPaths:
    """Error branches and the real ledger persistence path."""

    def scan_sequence(self, *bodies: dict[str, Any]) -> None:
        """Queue Etherscan responses in call order."""
        for body in bodies:
            responses.add(responses.GET, C.ETHERSCAN_URL, json=body, status=200)

    @responses.activate
    def test_finalized_slot(self) -> None:
        """Test finalized slot is read from the header."""
        responses.add(
            responses.GET,
            f"{BEACON}/eth/v1/beacon/headers/finalized",
            json={"data": {"header": {"message": {"slot": "1500"}}}},
        )
        assert BeaconNode(BEACON).finalized_slot() == 1500

    @responses.activate
    def test_proposer_at_reads_index(self) -> None:
        """Test proposer at reads the index."""
        responses.add(
            responses.GET,
            f"{BEACON}/eth/v1/beacon/headers/7",
            json={"data": {"header": {"message": {"proposer_index": "42"}}}},
        )
        assert BeaconNode(BEACON).proposer_at(7) == 42

    @responses.activate
    def test_empty_validator_data_raises(self) -> None:
        """Test empty validator data raises."""
        responses.add(
            responses.GET,
            f"{BEACON}/eth/v1/beacon/states/9/validators/{VALIDATOR}",
            json={"data": {}},
        )
        with pytest.raises(ValueError, match="no validator data"):
            BeaconNode(BEACON).validator(9, VALIDATOR)

    @responses.activate
    def test_transport_error_is_failure(self) -> None:
        """Test transport error is failure."""
        responses.add(responses.GET, C.ETHERSCAN_URL, status=500)
        assert Etherscan(key="k").call(module="account", action="txlist") is None
        assert Etherscan(key="k").call_scalar(module="block", action="x") is None

    def test_scalar_without_key_is_failure(self) -> None:
        """Test scalar without key is failure."""
        assert Etherscan(key="").call_scalar(module="block", action="x") is None

    @responses.activate
    def test_scalar_non_success_status(self) -> None:
        """Test scalar non success status."""
        responses.add(
            responses.GET, C.ETHERSCAN_URL, json=scan_json("0", status="0"), status=200
        )
        assert Etherscan(key="k").call_scalar(module="block", action="x") is None

    def test_ledger_round_trip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ledger round trip parses stored times."""
        stored = pd.DataFrame(
            [
                {
                    C.TIME: "2026-08-03 21:00:00",
                    SLOT: 1000,
                    BALANCE: 1,
                    EFFECTIVE: 2,
                    QUEUED: False,
                },
                {
                    C.TIME: "2026-07-27 21:00:00",
                    SLOT: 999,
                    BALANCE: 0,
                    EFFECTIVE: 2,
                    QUEUED: False,
                },
            ]
        )
        monkeypatch.setattr(market().reader, "load_csv", lambda path: stored)
        ledger = StakingLedger(VALIDATOR)
        loaded = ledger.load()
        # Sorted ascending by time regardless of stored order.
        assert list(loaded[SLOT]) == [999, 1000]
        assert loaded[C.TIME].iloc[0] == pd.Timestamp("2026-07-27 21:00:00")

    def test_append_to_existing_ledger(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test append to existing ledger keeps order."""
        ledger = StakingLedger(VALIDATOR)
        ledger.cached = pd.DataFrame(
            [
                {
                    C.TIME: pd.Timestamp("2026-08-03 21:00:00"),
                    SLOT: 1000,
                    BALANCE: 1,
                    EFFECTIVE: 2,
                    QUEUED: False,
                }
            ]
        )
        monkeypatch.setattr(market().writer, "save_csv", lambda path, df: True)
        out = ledger.append(
            {
                C.TIME: pd.Timestamp("2026-08-10 21:00:00"),
                SLOT: 1001,
                BALANCE: 5,
                EFFECTIVE: 2,
                QUEUED: False,
            }
        )
        assert list(out[SLOT]) == [1000, 1001]

    def test_boundaries_rejects_first_snapshot(self) -> None:
        """Test boundaries rejects the first snapshot."""
        ledger = StakingLedger(VALIDATOR)
        end = datetime(2026, 8, 10)
        ledger.cached = pd.DataFrame(
            [
                {
                    C.TIME: pd.Timestamp(end),
                    SLOT: 1000,
                    BALANCE: 1,
                    EFFECTIVE: 2,
                    QUEUED: False,
                },
                {
                    C.TIME: pd.Timestamp(end + timedelta(days=7)),
                    SLOT: 1001,
                    BALANCE: 2,
                    EFFECTIVE: 2,
                    QUEUED: False,
                },
            ]
        )
        # The earliest qualifying snapshot is row zero, so it has no
        # predecessor to subtract from and there is no usable pair.
        assert ledger.boundaries(end - timedelta(weeks=1), end) is None
        assert (
            ledger.boundaries(end - timedelta(weeks=2), end - timedelta(weeks=1))
            is None
        )

    @responses.activate
    def test_controller_predeploy_call_detected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test controller predeploy call detected."""
        monkeypatch.setattr(C, "STAKING_CONTROLLERS", RECIPIENT)
        self.scan_sequence(
            scan_json("100"),
            scan_json("200"),
            scan_json([]),
            scan_json([]),
            scan_json([{"to": C.CONSOLIDATION_REQUEST_PREDEPLOY}]),
        )
        moved = make_rewards().capital_moved(
            datetime(2026, 8, 3), datetime(2026, 8, 10), PUBKEY
        )
        assert moved is True

    @responses.activate
    def test_controller_scan_failure_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test controller scan failure is unknown."""
        monkeypatch.setattr(C, "STAKING_CONTROLLERS", RECIPIENT)
        self.scan_sequence(
            scan_json("100"),
            scan_json("200"),
            scan_json([]),
            scan_json([]),
            scan_json("NOTOK", status="0"),
        )
        moved = make_rewards().capital_moved(
            datetime(2026, 8, 3), datetime(2026, 8, 10), PUBKEY
        )
        assert moved is None

    def test_measured_interval(self) -> None:
        """Test measured interval returns the snapshot timestamps."""
        end = datetime(2026, 8, 10, 21)
        start = end - timedelta(weeks=1)
        pair = (make_snapshot(start, 1000, 1), make_snapshot(end, 1001, 2))
        rewards = make_rewards(ledger=FakeLedger(pair))
        assert rewards.measured_interval(start, end) == (start, end)
        assert (
            make_rewards(ledger=FakeLedger(None)).measured_interval(start, end) is None
        )

    def test_block_payment_without_indices(self) -> None:
        """Test block payment without indices uses the parent hash."""
        entries = [
            {"value": "3", "hash": "0xa"},
            {"value": "4", "hash": "0xb"},
            {"value": "6", "hash": "0xb"},
        ]
        assert make_rewards().block_payment(entries) == 10
        assert make_rewards().block_payment([]) == 0

    def test_block_without_timestamp_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test block without timestamp is unknown."""
        transfers = {777: [{"blockNumber": "777", "to": RECIPIENT, "value": "1"}]}
        rewards = make_rewards()
        monkeypatch.setattr(rewards, "candidates", lambda s, e: (transfers, {}))
        monkeypatch.setattr(rewards, "pubkey", lambda: PUBKEY)
        assert rewards.execution_rewards(slot_time(1000), slot_time(2000)) is None

    def test_execution_pubkey_failure_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test execution pubkey failure is unknown."""
        transfers = {777: [{"blockNumber": "777", "to": RECIPIENT, "value": "1"}]}
        rewards = make_rewards()
        monkeypatch.setattr(rewards, "candidates", lambda s, e: (transfers, {}))
        monkeypatch.setattr(rewards, "pubkey", lambda: None)
        assert rewards.execution_rewards(slot_time(1000), slot_time(2000)) is None

    def test_consensus_pubkey_failure_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test consensus pubkey failure is unknown."""
        end = datetime(2026, 8, 10, 21)
        start = end - timedelta(weeks=1)
        pair = (make_snapshot(start, 1000, 1), make_snapshot(end, 1001, 2))
        rewards = make_rewards(ledger=FakeLedger(pair))
        monkeypatch.setattr(rewards, "pubkey", lambda: None)
        assert rewards.consensus_rewards(start, end) is None
