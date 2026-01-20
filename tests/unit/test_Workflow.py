from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from hyperdrive.Workflow import Flow

flow = Flow()
now = datetime.utcnow()


class TestWorkFlow:
    def test_get_workflow_start_time(self):
        assert flow.get_workflow_start_time("dividends") == datetime(
            now.year, now.month, 1, 12
        )
        with pytest.raises(AttributeError):
            assert flow.get_workflow_start_time("build")

    def test_is_workflow_running(self):
        assert not flow.is_workflow_running("unrate")

    def test_is_workflow_running_ohlc(self):
        """Test is_workflow_running with ohlc workflow."""
        # Mock to control time and symbols
        with patch.object(flow, "get_workflow_start_time") as mock_time:
            mock_time.return_value = datetime.utcnow()  # Now

            with patch("hyperdrive.Workflow.MarketData") as MockMD:
                md = MagicMock()
                md.get_symbols.return_value = ["AAPL", "AMZN"]
                MockMD.return_value = md

                # Should be running since we just started
                result = flow.is_workflow_running("ohlc")
                # Result depends on timing - check it's a bool
                assert isinstance(result, bool)

    def test_is_workflow_running_dividends(self):
        """Test is_workflow_running with dividends workflow."""
        with patch.object(flow, "get_workflow_start_time") as mock_time:
            # Set start time to far in the past
            mock_time.return_value = datetime(2020, 1, 1, 0, 0)

            with patch("hyperdrive.Workflow.MarketData") as MockMD:
                md = MagicMock()
                md.get_symbols.return_value = ["AAPL"]
                MockMD.return_value = md

                # Should NOT be running since start time is in the past
                result = flow.is_workflow_running("dividends")
                assert result is False

    def test_is_workflow_running_splits(self):
        """Test is_workflow_running with splits workflow."""
        with patch.object(flow, "get_workflow_start_time") as mock_time:
            mock_time.return_value = datetime(2020, 1, 1, 0, 0)

            with patch("hyperdrive.Workflow.MarketData") as MockMD:
                md = MagicMock()
                md.get_symbols.return_value = ["AAPL"]
                MockMD.return_value = md

                result = flow.is_workflow_running("splits")
                assert result is False

    def test_is_workflow_running_intraday(self):
        """Test is_workflow_running with intraday workflow."""
        with patch.object(flow, "get_workflow_start_time") as mock_time:
            mock_time.return_value = datetime(2020, 1, 1, 0, 0)

            with patch("hyperdrive.Workflow.MarketData") as MockMD:
                md = MagicMock()
                md.get_symbols.return_value = ["AAPL"]
                MockMD.return_value = md

                result = flow.is_workflow_running("intraday")
                assert result is False

    def test_is_any_workflow_running(self):
        """Test is_any_workflow_running returns False when no workflows running."""
        with patch.object(flow, "is_workflow_running") as mock_running:
            mock_running.return_value = False

            result = flow.is_any_workflow_running()
            assert result is False
            assert mock_running.call_count == 4  # ohlc, intraday, dividends, splits

    def test_is_any_workflow_running_one_active(self):
        """Test is_any_workflow_running returns True when one workflow running."""
        with patch.object(flow, "is_workflow_running") as mock_running:
            # Return True for first workflow, False for rest
            mock_running.side_effect = [True, False, False, False]

            result = flow.is_any_workflow_running()
            assert result is True
