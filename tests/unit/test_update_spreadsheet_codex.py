"""Tests for the alternate Dune-first spreadsheet updater."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import responses
from pytest_mock import MockerFixture

from scripts.update_spreadsheet_codex import (
    DuneRewardProvider,
    LocalNodeRewardProvider,
    RewardPeriod,
    RewardProviderError,
    RewardTotal,
    fetch_rewards,
)


@pytest.fixture
def period() -> RewardPeriod:
    """Return a representative UTC spreadsheet interval."""
    return RewardPeriod(
        datetime(2026, 7, 27, tzinfo=UTC), datetime(2026, 8, 3, tzinfo=UTC)
    )


def test_reward_total_preserves_integer_units() -> None:
    """Consensus and execution units combine without floating-point loss."""
    total = RewardTotal(1_000_000_001, 2_000_000_000_000_000_001)
    assert total.eth == Decimal("3.000000001000000001")


def test_dune_daily_rows_require_exact_coverage(period: RewardPeriod) -> None:
    """Dune must return every date, including zero-reward dates."""
    provider = DuneRewardProvider("key", 1, 690345, "0xfee")
    rows = [
        {
            "day": current.date().isoformat(),
            "consensus_reward_gwei": "0",
            "execution_reward_wei": "0",
            "capital_change_gwei": "0",
            "coverage_complete": True,
        }
        for current in (
            datetime(2026, 7, 27, tzinfo=UTC),
            datetime(2026, 7, 28, tzinfo=UTC),
            datetime(2026, 7, 29, tzinfo=UTC),
            datetime(2026, 7, 30, tzinfo=UTC),
            datetime(2026, 7, 31, tzinfo=UTC),
            datetime(2026, 8, 1, tzinfo=UTC),
            datetime(2026, 8, 2, tzinfo=UTC),
        )
    ]
    daily = provider._daily_rows(rows, period.start.date(), period.end.date())
    assert set(daily) == {
        date(2026, 7, 27),
        date(2026, 7, 28),
        date(2026, 7, 29),
        date(2026, 7, 30),
        date(2026, 7, 31),
        date(2026, 8, 1),
        date(2026, 8, 2),
    }


def test_dune_daily_rows_reject_partial_range(period: RewardPeriod) -> None:
    """A partial primary result must not be accepted."""
    provider = DuneRewardProvider("key", 1, 690345, "0xfee")
    with pytest.raises(RewardProviderError, match="coverage mismatch"):
        provider._daily_rows([], period.start.date(), period.end.date())


@responses.activate
def test_dune_fetch_executes_polls_and_reads_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Dune client follows the documented execute/status/results flow."""
    monkeypatch.setenv("DUNE_POLL_SECONDS", "0")
    provider = DuneRewardProvider("key", 7, 690345, "0xfee")
    period = RewardPeriod(
        datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 2, tzinfo=UTC)
    )
    responses.post(
        "https://api.dune.com/api/v1/query/7/execute",
        json={"execution_id": "execution-1", "state": "QUERY_STATE_PENDING"},
    )
    responses.get(
        "https://api.dune.com/api/v1/execution/execution-1/status",
        json={"state": "QUERY_STATE_COMPLETED"},
    )
    responses.get(
        "https://api.dune.com/api/v1/execution/execution-1/results",
        json={
            "state": "QUERY_STATE_COMPLETED",
            "result": {
                "rows": [
                    {
                        "day": "2026-08-01",
                        "consensus_reward_gwei": "11",
                        "execution_reward_wei": "12",
                        "capital_change_gwei": "-13",
                        "coverage_complete": True,
                    }
                ]
            },
        },
    )

    assert provider.fetch([period]) == {period: RewardTotal(11, 12, -13)}


@responses.activate
def test_dune_fetch_executes_raw_sql_without_query_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Dune client can execute the bundled SQL without a saved query."""
    monkeypatch.setenv("DUNE_POLL_SECONDS", "0")
    provider = DuneRewardProvider("key", None, 690345, "0xfee")
    period = RewardPeriod(
        datetime(2026, 8, 1, tzinfo=UTC), datetime(2026, 8, 2, tzinfo=UTC)
    )
    responses.post(
        "https://api.dune.com/api/v1/sql/execute",
        json={"execution_id": "execution-1", "state": "QUERY_STATE_PENDING"},
    )
    responses.get(
        "https://api.dune.com/api/v1/execution/execution-1/status",
        json={"state": "QUERY_STATE_COMPLETED"},
    )
    responses.get(
        "https://api.dune.com/api/v1/execution/execution-1/results",
        json={
            "state": "QUERY_STATE_COMPLETED",
            "result": {
                "rows": [
                    {
                        "day": "2026-08-01",
                        "consensus_reward_gwei": "11",
                        "execution_reward_wei": "12",
                        "capital_change_gwei": "0",
                        "coverage_complete": True,
                    }
                ]
            },
        },
    )

    assert provider.fetch([period]) == {period: RewardTotal(11, 12)}
    request = responses.calls[0].request
    assert isinstance(request.body, bytes)
    request_body = request.body.decode()
    assert '"sql"' in request_body
    assert "{{validator_index}}" not in request_body


def test_complete_dune_result_avoids_local_node(
    period: RewardPeriod, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """The secondary provider is not called after complete Dune success."""
    monkeypatch.setenv("DUNE_API_KEY", "key")
    monkeypatch.setenv("DUNE_QUERY_ID", "7")
    expected = {period: RewardTotal(10, 20)}
    dune = mocker.patch("scripts.update_spreadsheet_codex.DuneRewardProvider")
    dune.return_value.fetch.return_value = expected
    local = mocker.patch("scripts.update_spreadsheet_codex.LocalNodeRewardProvider")

    source, rewards = fetch_rewards([period], 690345, "0xfee")

    assert source == "dune"
    assert rewards == expected
    local.assert_not_called()


def test_repository_dotenv_names_select_dune(
    period: RewardPeriod, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """The repository's DUNE key works without a saved-query ID."""
    monkeypatch.delenv("DUNE_API_KEY", raising=False)
    monkeypatch.delenv("DUNE_QUERY_ID", raising=False)
    monkeypatch.setenv("DUNE", "key")
    expected = {period: RewardTotal(10, 20)}
    dune = mocker.patch("scripts.update_spreadsheet_codex.DuneRewardProvider")
    dune.return_value.fetch.return_value = expected
    local = mocker.patch("scripts.update_spreadsheet_codex.LocalNodeRewardProvider")

    source, rewards = fetch_rewards([period], 690345, "0xfee")

    assert source == "dune"
    assert rewards == expected
    dune.assert_called_once_with("key", None, 690345, "0xfee")
    local.assert_not_called()


def test_dune_failure_recomputes_with_local_node(
    period: RewardPeriod, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """Any primary failure switches the entire request to the node."""
    monkeypatch.setenv("DUNE_API_KEY", "key")
    monkeypatch.setenv("DUNE_QUERY_ID", "7")
    dune = mocker.patch("scripts.update_spreadsheet_codex.DuneRewardProvider")
    dune.return_value.fetch.side_effect = RewardProviderError("partial")
    expected = {period: RewardTotal(30, 40)}
    local = mocker.patch("scripts.update_spreadsheet_codex.LocalNodeRewardProvider")
    local.return_value.fetch.return_value = expected

    source, rewards = fetch_rewards([period], 690345, "0xfee")

    assert source == "local-node"
    assert rewards == expected
    local.return_value.fetch.assert_called_once_with([period])


def test_dual_provider_failure_returns_no_partial_result(
    period: RewardPeriod, monkeypatch: pytest.MonkeyPatch, mocker: MockerFixture
) -> None:
    """A failed secondary provider propagates instead of fabricating zero."""
    monkeypatch.setenv("DUNE_API_KEY", "key")
    monkeypatch.setenv("DUNE_QUERY_ID", "7")
    dune = mocker.patch("scripts.update_spreadsheet_codex.DuneRewardProvider")
    dune.return_value.fetch.side_effect = RewardProviderError("partial")
    local = mocker.patch("scripts.update_spreadsheet_codex.LocalNodeRewardProvider")
    local.return_value.fetch.side_effect = RewardProviderError("history unavailable")

    with pytest.raises(RewardProviderError, match="history unavailable"):
        fetch_rewards([period], 690345, "0xfee")


def test_local_execution_reward_uses_traces_and_priority_fees(
    mocker: MockerFixture,
) -> None:
    """A locally built block includes tips and traced inbound transfers."""
    recipient = "0x0000000000000000000000000000000000000fee"
    provider = LocalNodeRewardProvider(
        "http://beacon", "http://geth", 690345, recipient
    )
    mocker.patch.object(
        provider,
        "_rpc",
        side_effect=[
            {"baseFeePerGas": "0x5a"},
            [{"gasUsed": "0x5208", "effectiveGasPrice": "0x64"}],
            [
                {
                    "result": {
                        "type": "CALL",
                        "from": "0x0000000000000000000000000000000000000001",
                        "to": recipient,
                        "value": "0x5",
                        "calls": [],
                    }
                }
            ],
        ],
    )

    assert provider._execution_reward("0xblock", recipient) == 210_005


def test_mev_execution_reward_excludes_builder_priority_fees(
    mocker: MockerFixture,
) -> None:
    """An MEV-built block counts its traced proposer payment, not builder tips."""
    recipient = "0x0000000000000000000000000000000000000fee"
    provider = LocalNodeRewardProvider(
        "http://beacon", "http://geth", 690345, recipient
    )
    mocker.patch.object(
        provider,
        "_rpc",
        side_effect=[
            {"baseFeePerGas": "0x5a"},
            [{"gasUsed": "0x5208", "effectiveGasPrice": "0x64"}],
            [
                {
                    "result": {
                        "type": "CALL",
                        "from": "0x0000000000000000000000000000000000000001",
                        "to": recipient,
                        "value": "0x5",
                        "calls": [],
                    }
                }
            ],
        ],
    )

    assert provider._execution_reward("0xblock", "0xbuilder") == 5


def test_reverted_trace_transfers_are_excluded() -> None:
    """Transfers below a reverted call frame never become proposer income."""
    recipient = "0x0000000000000000000000000000000000000fee"
    provider = LocalNodeRewardProvider(
        "http://beacon", "http://geth", 690345, recipient
    )
    frame = {
        "type": "CALL",
        "from": "0x0000000000000000000000000000000000000001",
        "to": recipient,
        "value": "0x5",
        "error": "execution reverted",
        "calls": [
            {
                "type": "CALL",
                "from": "0x0000000000000000000000000000000000000002",
                "to": recipient,
                "value": "0x6",
            }
        ],
    }

    assert provider._inbound_value(frame) == 0
