"""Ethereum validator staking rewards from free, keyless data sources.

Replaces the retired beaconcha.in paid API. Consensus rewards come from a
snapshot ledger of validator balances; execution rewards come from MEV relay
payload data with an Etherscan fallback for locally built blocks.

Coverage limits, stated plainly because the caller depends on them:

- The keyless beacon endpoint retains roughly 64 slots of state, about 13
  minutes. Balances must therefore be snapshotted as they are observed. There
  is no way to read a historical balance, so rows predating the ledger cannot
  be valued.
- A returned ``Decimal(0)`` for execution rewards means every relay and the
  Etherscan block index were queried successfully and no payment attributable
  to this validator was found. It does not prove the validator had no proposer
  duty; duty enumeration needs beacon state that the keyless endpoint prunes.
  The gap is economically empty, since a proposal that paid nothing contributes
  zero either way.
- Capital operations are detected from deposit logs matched on the validator
  pubkey, applied beacon withdrawals matched on validator index, queue
  membership recorded at both snapshot boundaries, and optionally transactions
  from configured controller addresses to the request predeploys. A withdrawal
  or consolidation request both submitted and applied strictly inside one
  interval by an unconfigured address is not detected.

Every public reward method returns ``Decimal | None`` where ``None`` means the
value is not determinable. Callers must not substitute zero.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from time import sleep
from typing import Any

import pandas as pd
import requests

from . import Constants as C
from .DataSource import MarketData

# Ledger columns
SLOT = "Slot"
BALANCE = "Balance"
EFFECTIVE = "EffectiveBalance"
QUEUED = "QueuedCapital"
LEDGER_COLS: list[str] = [C.TIME, SLOT, BALANCE, EFFECTIVE, QUEUED]

_market: MarketData | None = None


def market() -> MarketData:
    """Get the shared MarketData instance used for retries and file access.

    Constructed lazily so importing this module does not require credentials.

    Returns:
        A process-wide MarketData instance.
    """
    global _market
    if _market is None:
        _market = MarketData()
    return _market


def to_naive_utc(timestamp: int | float) -> datetime:
    """Convert a unix timestamp to a timezone-naive UTC datetime.

    The spreadsheet parses its dates with ``pd.to_datetime`` and gets naive
    values, so everything here stays naive UTC to avoid mixed-awareness
    comparisons.

    Args:
        timestamp: Unix timestamp in seconds.

    Returns:
        Timezone-naive datetime in UTC.
    """
    return datetime.fromtimestamp(timestamp, UTC).replace(tzinfo=None)


class BeaconNode:
    """Client for the standard beacon REST API.

    Attributes:
        url: Base URL of the beacon node.
    """

    def __init__(self, url: str | None = None) -> None:
        """Initialize the beacon client.

        Args:
            url: Base URL. Defaults to C.BEACON_URL.
        """
        self.url = (url or C.BEACON_URL).rstrip("/")

    def get(self, path: str) -> Any:
        """Perform a retried GET against the beacon node.

        Args:
            path: Path beginning with a slash.

        Returns:
            The parsed ``data`` field of the response.
        """

        def _get(path: str) -> Any:
            response = requests.get(f"{self.url}{path}", timeout=C.API_TIMEOUT)
            response.raise_for_status()
            return response.json()["data"]

        return market().try_again(_get, path=path)

    def slot_at(self, when: datetime) -> int:
        """Get the slot containing a point in time.

        Args:
            when: Naive UTC datetime.

        Returns:
            Beacon slot number.
        """
        seconds = int(when.replace(tzinfo=UTC).timestamp()) - C.GENESIS_TIME
        return seconds // C.SECONDS_PER_SLOT

    def time_at(self, slot: int) -> datetime:
        """Get the start time of a slot.

        Args:
            slot: Beacon slot number.

        Returns:
            Naive UTC datetime for the slot.
        """
        return to_naive_utc(C.GENESIS_TIME + slot * C.SECONDS_PER_SLOT)

    def finalized_slot(self) -> int:
        """Get the most recent finalized slot.

        Returns:
            Slot number of the finalized head.
        """
        data = self.get("/eth/v1/beacon/headers/finalized")
        return int(data["header"]["message"]["slot"])

    def validator(self, state_id: str | int, validator_id: str) -> dict[str, Any]:
        """Get a validator's balance and identity at a state.

        Args:
            state_id: Slot number or state alias such as ``finalized``.
            validator_id: Validator index.

        Returns:
            Dict with ``balance``, ``effective_balance`` (Gwei) and ``pubkey``.

        Raises:
            ValueError: If the response contains no validator data.
        """
        data = self.get(f"/eth/v1/beacon/states/{state_id}/validators/{validator_id}")
        if not data:
            raise ValueError(f"no validator data for {validator_id} at {state_id}")
        return {
            "balance": int(data["balance"]),
            "effective_balance": int(data["validator"]["effective_balance"]),
            "pubkey": data["validator"]["pubkey"],
        }

    def proposer_at(self, slot: int) -> int | None:
        """Get the validator index that proposed a slot.

        Args:
            slot: Beacon slot number.

        Returns:
            Proposer index, or None if the slot was missed.
        """
        try:
            data = self.get(f"/eth/v1/beacon/headers/{slot}")
        except Exception:
            return None
        return int(data["header"]["message"]["proposer_index"])

    def queued_capital(self, validator_id: str, pubkey: str) -> bool:
        """Check whether any capital operation is queued for this validator.

        Covers pending deposits, pending consolidations in either direction,
        and pending partial withdrawals. Recorded at snapshot time so an
        operation straddling an interval boundary is visible later.

        Args:
            validator_id: Validator index.
            pubkey: Validator public key, ``0x`` prefixed.

        Returns:
            True if any queue references this validator.
        """
        base = "/eth/v1/beacon/states/head"

        def _deposits() -> bool:
            # The queue holds tens of thousands of entries and offers no server
            # side filter, so scan the raw body for the pubkey instead of
            # parsing every record.
            response = requests.get(
                f"{self.url}{base}/pending_deposits", timeout=C.API_TIMEOUT
            )
            response.raise_for_status()
            return pubkey.lower() in response.text.lower()

        if market().try_again(_deposits):
            return True

        index = int(validator_id)
        consolidations = self.get(f"{base}/pending_consolidations")
        for entry in consolidations:
            if index in (int(entry["source_index"]), int(entry["target_index"])):
                return True

        withdrawals = self.get(f"{base}/pending_partial_withdrawals")
        return any(int(entry["validator_index"]) == index for entry in withdrawals)


class Etherscan:
    """Client for the Etherscan v2 API with explicit success semantics.

    Etherscan reports both genuine errors and successful empty queries with
    ``status`` of ``"0"``. They are distinguished by the type of ``result``: a
    list means the query succeeded, a string means it failed. Treating an empty
    result as failure would make every ordinary week undeterminable.

    Attributes:
        key: API key, or empty when unconfigured.
    """

    def __init__(self, key: str | None = None) -> None:
        """Initialize the Etherscan client.

        Args:
            key: API key. Defaults to the ETHERSCAN environment variable.
        """
        self.key = key if key is not None else os.environ.get("ETHERSCAN", "")

    def call(self, **params: Any) -> list[Any] | None:
        """Perform one retried API call.

        Args:
            **params: Query parameters excluding ``chainid`` and ``apikey``.

        Returns:
            The result list on success, or None on failure.
        """
        if not self.key:
            return None
        query = {"chainid": 1, "apikey": self.key, **params}

        def _call() -> list[Any] | None:
            response = requests.get(
                C.ETHERSCAN_URL, params=query, timeout=C.API_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()
            result = payload.get("result")
            # A list is a successful query, empty or not. A string is an error
            # message such as "Missing/Invalid API Key" or a rate limit notice.
            return result if isinstance(result, list) else None

        try:
            result = market().try_again(_call)
        except Exception:
            return None
        finally:
            sleep(C.ETHERSCAN_FREE_DELAY)
        return result

    def paged(self, **params: Any) -> list[Any] | None:
        """Page through a list endpoint until exhausted.

        Args:
            **params: Query parameters excluding paging.

        Returns:
            All records on success, or None if any page failed.
        """
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
        """Resolve a timestamp to a block number.

        Args:
            when: Naive UTC datetime.
            closest: Either ``before`` or ``after``.

        Returns:
            Block number, or None on failure.
        """
        timestamp = int(when.replace(tzinfo=UTC).timestamp())
        # This endpoint returns a bare string block number rather than a list,
        # so the list based success test does not apply.
        result = self.call_scalar(
            module="block",
            action="getblocknobytime",
            timestamp=timestamp,
            closest=closest,
        )
        return int(result) if result and result.isdigit() else None

    def call_scalar(self, **params: Any) -> str | None:
        """Perform a call whose successful result is a scalar string.

        ``getblocknobytime`` returns a block number as a string, so the list
        based success test does not apply. Success is decided by ``status``.

        Args:
            **params: Query parameters excluding ``chainid`` and ``apikey``.

        Returns:
            The result string on success, or None on failure.
        """
        if not self.key:
            return None
        query = {"chainid": 1, "apikey": self.key, **params}

        def _call() -> str | None:
            response = requests.get(
                C.ETHERSCAN_URL, params=query, timeout=C.API_TIMEOUT
            )
            response.raise_for_status()
            payload = response.json()
            if str(payload.get("status")) != "1":
                return None
            result = payload.get("result")
            return str(result) if result is not None else None

        try:
            return market().try_again(_call)
        except Exception:
            return None
        finally:
            sleep(C.ETHERSCAN_FREE_DELAY)


class RelayIndex:
    """Reads delivered payload data from the validator's MEV-Boost relays.

    Relay data is per relay, so a block is only visible on the relay that
    delivered it and all configured relays must be queried. Some relays ignore
    the ``proposer_pubkey`` filter and return unrelated proposers, so every
    record is verified locally.

    Attributes:
        relays: Relay base URLs.
    """

    def __init__(self, relays: list[str] | None = None) -> None:
        """Initialize the relay index.

        Args:
            relays: Relay base URLs. Defaults to C.MEV_RELAYS.
        """
        self.relays = relays if relays is not None else list(C.MEV_RELAYS)

    def payloads(self, pubkey: str) -> dict[int, int]:
        """Get delivered payload values for a proposer, keyed by slot.

        Relay coverage is best effort. A relay that errors or that ignores the
        proposer filter simply contributes nothing, because relays supply
        payment values rather than deciding which blocks exist. Enumeration is
        done on chain, where every payment must appear regardless of which
        relay delivered it.

        Args:
            pubkey: Validator public key, ``0x`` prefixed.

        Returns:
            Mapping of slot to payment value in Wei, deduplicated by slot.
        """
        delivered: dict[int, int] = {}
        wanted = pubkey.lower()

        for relay in self.relays:
            url = (
                f"{relay.rstrip('/')}"
                "/relay/v1/data/bidtraces/proposer_payload_delivered"
            )

            def _get(url: str = url) -> list[dict[str, Any]]:
                response = requests.get(
                    url,
                    params={"proposer_pubkey": pubkey, "limit": C.RELAY_PAGE_SIZE},
                    timeout=C.API_TIMEOUT,
                )
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, list) else []

            try:
                records = market().try_again(_get)
            except Exception:
                continue

            for record in records:
                # Relays that ignore the filter return other proposers.
                if str(record.get("proposer_pubkey", "")).lower() != wanted:
                    continue
                delivered[int(record["slot"])] = int(record["value"])

        return delivered


class StakingLedger:
    """Append-only ledger of observed validator balances, persisted to S3.

    Attributes:
        validator_id: Validator index the ledger tracks.
        path: Local path of the ledger CSV.
    """

    def __init__(self, validator_id: str | None = None) -> None:
        """Initialize the ledger.

        Args:
            validator_id: Validator index. Defaults to C.VALIDATOR_ID.
        """
        self.validator_id = validator_id or C.VALIDATOR_ID
        self.path = market().finder.get_staking_path(self.validator_id)
        self.cached: pd.DataFrame | None = None

    def load(self) -> pd.DataFrame:
        """Load the ledger, downloading from S3 when stale or absent.

        Cached per instance, since every row valued in a run reads the same
        ledger and an uncached read can re-download from S3 each time.

        Returns:
            Ledger sorted by time, or an empty frame with the ledger columns.
        """
        if self.cached is not None:
            return self.cached
        df = market().reader.load_csv(self.path)
        if df.empty:
            df = pd.DataFrame(columns=pd.Index(LEDGER_COLS))
        else:
            df[C.TIME] = pd.to_datetime(df[C.TIME])
            df = df.sort_values(C.TIME).reset_index(drop=True)
        self.cached = df
        return df

    def append(self, row: dict[str, Any]) -> pd.DataFrame:
        """Append a snapshot row and persist the ledger.

        A snapshot for a slot already recorded is ignored, so a repeated run
        cannot create a duplicate boundary.

        Args:
            row: Snapshot with the ledger columns.

        Returns:
            The ledger including the new row.
        """
        df = self.load()
        added = pd.DataFrame([row], columns=pd.Index(LEDGER_COLS))
        if df.empty:
            df = added
        else:
            if int(row[SLOT]) in set(df[SLOT].astype(int)):
                return df
            df = pd.concat([df, added], ignore_index=True)
        df = df.sort_values(C.TIME).reset_index(drop=True)
        market().writer.save_csv(self.path, df)
        self.cached = df
        return df

    def boundaries(
        self, start: datetime, end: datetime
    ) -> tuple[pd.Series, pd.Series] | None:
        """Select the snapshot pair that measures a spreadsheet row.

        The later snapshot is the first at or after the row's end date; the
        earlier one is the snapshot immediately before it. Both must fall
        within C.MAX_BOUNDARY_DRIFT days of the boundary they represent, which
        stops a dropped weekly run from letting two rows claim one pair.

        Args:
            start: Row window start, naive UTC.
            end: Row window end, naive UTC.

        Returns:
            The (earlier, later) snapshot rows, or None if no valid pair
            exists.
        """
        df = self.load()
        if len(df) < 2:
            return None

        drift = pd.Timedelta(days=C.MAX_BOUNDARY_DRIFT)
        later = df[df[C.TIME] >= end]
        if later.empty:
            return None
        position = int(later.index[0])
        if position == 0:
            return None

        after = df.loc[position]
        before = df.loc[position - 1]
        if after[C.TIME] - end > drift:
            return None
        if abs(before[C.TIME] - start) > drift:
            return None
        return before, after


class StakingRewards:
    """Computes consensus and execution staking rewards for one validator.

    Attributes:
        validator_id: Validator index.
        fee_recipient: Address that receives execution layer payments.
        beacon: Beacon node client.
        scan: Etherscan client.
        relays: MEV relay index.
        ledger: Balance snapshot ledger.
    """

    def __init__(
        self,
        validator_id: str | None = None,
        fee_recipient: str | None = None,
        beacon: BeaconNode | None = None,
        scan: Etherscan | None = None,
        relays: RelayIndex | None = None,
        ledger: StakingLedger | None = None,
    ) -> None:
        """Initialize the reward calculator.

        Args:
            validator_id: Validator index. Defaults to C.VALIDATOR_ID.
            fee_recipient: Fee recipient address. Defaults to C.FEE_RECIPIENT.
            beacon: Beacon client override.
            scan: Etherscan client override.
            relays: Relay index override.
            ledger: Ledger override.
        """
        self.validator_id = validator_id or C.VALIDATOR_ID
        self.fee_recipient = (
            fee_recipient if fee_recipient is not None else C.FEE_RECIPIENT
        )
        self.beacon = beacon or BeaconNode()
        self.scan = scan or Etherscan()
        self.relays = relays or RelayIndex()
        self.ledger = ledger or StakingLedger(self.validator_id)

    def record_snapshot(self) -> pd.DataFrame:
        """Read the finalized balance and append it to the ledger.

        Returns:
            The ledger including the new snapshot.
        """
        slot = self.beacon.finalized_slot()
        # Read the state by alias. Public beacon providers serve named states
        # only and reject an explicit slot number, and the slot is used solely
        # as an interval label, where a one epoch skew cancels between the row
        # it ends and the row it starts.
        state = self.beacon.validator("finalized", self.validator_id)
        queued = self.beacon.queued_capital(self.validator_id, state["pubkey"])
        row = {
            C.TIME: self.beacon.time_at(slot),
            SLOT: slot,
            BALANCE: state["balance"],
            EFFECTIVE: state["effective_balance"],
            QUEUED: bool(queued),
        }
        return self.ledger.append(row)

    def pubkey(self) -> str | None:
        """Get the validator's public key from the beacon node.

        Returns:
            The pubkey, or None if it cannot be read.
        """
        try:
            return self.beacon.validator("finalized", self.validator_id)["pubkey"]
        except Exception:
            return None

    def capital_moved(self, start: datetime, end: datetime, pubkey: str) -> bool | None:
        """Check whether principal entered or left the validator in a window.

        Args:
            start: Window start, naive UTC.
            end: Window end, naive UTC.
            pubkey: Validator public key.

        Returns:
            True if a capital operation was found, False if none was found, or
            None if the check could not be completed.
        """
        first = self.scan.block_by_time(start, "after")
        last = self.scan.block_by_time(end, "before")
        if first is None or last is None:
            return None

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
            str(row.get("validatorIndex")) == str(self.validator_id)
            for row in withdrawals
        ):
            return True

        predeploys = {
            C.WITHDRAWAL_REQUEST_PREDEPLOY.lower(),
            C.CONSOLIDATION_REQUEST_PREDEPLOY.lower(),
            C.DEPOSIT_CONTRACT.lower(),
        }
        controllers = [a.strip() for a in C.STAKING_CONTROLLERS.split(",") if a.strip()]
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

    def consensus_rewards(self, start: datetime, end: datetime) -> Decimal | None:
        """Get net consensus rewards for a spreadsheet row.

        Args:
            start: Row window start, naive UTC.
            end: Row window end, naive UTC.

        Returns:
            Rewards in ETH over the measured snapshot interval, or None. The
            value may be negative when the validator was penalized.
        """
        pair = self.ledger.boundaries(start, end)
        if pair is None:
            return None
        before, after = pair
        if bool(before[QUEUED]) or bool(after[QUEUED]):
            return None

        pubkey = self.pubkey()
        if pubkey is None:
            return None
        moved = self.capital_moved(before[C.TIME], after[C.TIME], pubkey)
        if moved is None or moved:
            return None

        delta = int(after[BALANCE]) - int(before[BALANCE])
        return Decimal(delta) / Decimal(C.GWEI_PER_ETH)

    def measured_interval(
        self, start: datetime, end: datetime
    ) -> tuple[datetime, datetime] | None:
        """Get the actual interval the ledger measures for a row.

        Execution rewards and pricing must use this interval so all three
        components of the Crypto value describe the same period.

        Args:
            start: Row window start, naive UTC.
            end: Row window end, naive UTC.

        Returns:
            The (start, end) timestamps of the snapshot pair, or None.
        """
        pair = self.ledger.boundaries(start, end)
        if pair is None:
            return None
        before, after = pair
        return before[C.TIME].to_pydatetime(), after[C.TIME].to_pydatetime()

    def candidates(
        self, start: datetime, end: datetime
    ) -> tuple[dict[int, list[dict[str, Any]]], dict[int, dict[str, Any]]] | None:
        """Enumerate on-chain payments to the fee recipient within a window.

        Every proposer payment lands on chain, whether the fee recipient was
        the block's coinbase or a builder paid it at the end of the block, so
        this is the complete enumeration. Relay data cannot serve that role:
        one configured relay rejects the proposer filter outright, and a block
        is only visible on the relay that delivered it.

        Args:
            start: Interval start, naive UTC.
            end: Interval end, naive UTC.

        Returns:
            A tuple of transfers keyed by block number and coinbase block
            rewards keyed by block number, or None if a source failed.
        """
        first = self.scan.block_by_time(start, "after")
        last = self.scan.block_by_time(end, "before")
        if first is None or last is None:
            return None

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
                if str(entry.get("to", "")).lower() != self.fee_recipient.lower():
                    continue
                if int(entry.get("value", 0)) <= 0:
                    continue
                transfers.setdefault(int(entry["blockNumber"]), []).append(entry)

        mined = self.scan.paged(
            module="account",
            action="getminedblocks",
            address=self.fee_recipient,
            blocktype="blocks",
        )
        if mined is None:
            return None
        rewards: dict[int, dict[str, Any]] = {}
        for block in mined:
            when = to_naive_utc(int(block["timeStamp"]))
            if start <= when < end:
                rewards[int(block["blockNumber"])] = block

        return transfers, rewards

    def block_payment(self, entries: list[dict[str, Any]]) -> int:
        """Sum the end-of-block payment among transfers within one block.

        The builder payment is the final transaction of the block, so the
        transfers belonging to it are those sharing the highest transaction
        index. Summing every inbound transfer instead would count unrelated
        income that happened to land in a block this validator proposed.

        Args:
            entries: Inbound transfers within a single block.

        Returns:
            Payment value in Wei.
        """
        if not entries:
            return 0
        indexed = [e for e in entries if str(e.get("transactionIndex", "")).isdigit()]
        if not indexed:
            # Internal transfers without an index still carry a parent hash.
            last_hash = entries[-1].get("hash")
            return sum(int(e["value"]) for e in entries if e.get("hash") == last_hash)
        final = max(int(e["transactionIndex"]) for e in indexed)
        hashes = {e["hash"] for e in indexed if int(e["transactionIndex"]) == final}
        return sum(int(e["value"]) for e in entries if e.get("hash") in hashes)

    def execution_rewards(self, start: datetime, end: datetime) -> Decimal | None:
        """Get execution layer rewards over a measured interval.

        Payments are enumerated on chain and attributed only to blocks this
        validator proposed. Relay delivered payload data supplies the value
        where available, since it states the agreed payment directly.

        Args:
            start: Interval start, naive UTC.
            end: Interval end, naive UTC.

        Returns:
            Rewards in ETH, or None if a source could not be exhausted.
        """
        if not self.fee_recipient:
            return None

        found = self.candidates(start, end)
        if found is None:
            return None
        transfers, coinbase = found

        blocks = set(transfers) | set(coinbase)
        if not blocks:
            # Nothing was paid to the fee recipient in this window, so there is
            # nothing to attribute. This is a proven zero.
            return Decimal(0)

        pubkey = self.pubkey()
        if pubkey is None:
            return None
        delivered = self.relays.payloads(pubkey)

        total = 0
        for block in blocks:
            when = self.block_time(block, transfers, coinbase)
            if when is None:
                return None
            slot = self.beacon.slot_at(when)
            if self.beacon.proposer_at(slot) != int(self.validator_id):
                continue
            if slot in delivered:
                total += delivered[slot]
            elif block in coinbase:
                total += int(coinbase[block]["blockReward"])
            else:
                total += self.block_payment(transfers.get(block, []))

        return Decimal(total) / Decimal(C.WEI_PER_ETH)

    def block_time(
        self,
        block: int,
        transfers: dict[int, list[dict[str, Any]]],
        coinbase: dict[int, dict[str, Any]],
    ) -> datetime | None:
        """Get a block's timestamp from the records that referenced it.

        Args:
            block: Execution block number.
            transfers: Inbound transfers keyed by block number.
            coinbase: Validated block records keyed by block number.

        Returns:
            Naive UTC datetime, or None when no record carried a timestamp.
        """
        for entry in transfers.get(block, []):
            stamp = entry.get("timeStamp")
            if stamp:
                return to_naive_utc(int(stamp))
        record = coinbase.get(block)
        if record and record.get("timeStamp"):
            return to_naive_utc(int(record["timeStamp"]))
        return None
