"""Tests for the History module."""

import numpy as np
import pandas as pd

from hyperdrive import Constants as C
from hyperdrive.History import Historian

hist = Historian()
ls = [np.nan, True, True, np.nan, False, np.nan, np.nan, np.nan, True]
fs = [True, True, True, True, False, False, False, False, True]
unfilled_fs = [True, None, None, None, False, None, None, None, True]
ns = [True, True, True, True, False, False, False, True, True]
unfilled_ns = [
    True,
    None,
    None,
    None,
    False,
    None,
    None,
    True,
    None,
]  # Last is None because unfill removes consecutive duplicates; index 8 repeats index 7 (True)
arr = np.array(ls)
test_ffill = np.array(fs)
test_nfill = np.array(ns)


close = pd.Series([3, 2, 5, 1, 100, 75, 50, 25, 1])
close_arr = np.array([3, 2, 5, 1, 100, 75, 50, 25, 1])

total = 100
majority = 80
minority = total - majority
data = np.arange(total)
X = np.column_stack([data, data])  # ndarray instead of DataFrame
y = np.array([True] * majority + [False] * minority)

orders_index = pd.to_datetime(pd.Series(["2025-01-01", "2025-01-02"], name=C.TIME))
orders_close = pd.DataFrame({"AAPL": [200, 100], "META": [25, 50]}, index=orders_index)


class TestHistorian:
    """Tests for the Historian backtesting and ML utility class."""

    def test_from_holding(self) -> None:
        """Test creating portfolio from holding strategy."""
        stats = hist.from_holding(close).stats()
        assert isinstance(stats, pd.Series)
        assert "Sortino Ratio" in stats

    def test_from_signals(self) -> None:
        """Test creating portfolio from trading signals."""
        stats = hist.from_signals(close, pd.Series(test_ffill)).stats()
        assert isinstance(stats, pd.Series)
        assert "Sortino Ratio" in stats

    def test_from_orders(self) -> None:
        """Test creating portfolio from order data."""
        size = pd.DataFrame({"AAPL": [1, 0], "META": [0, 1]}, index=orders_index)
        stats = hist.from_orders(orders_close, size).stats()
        assert isinstance(stats, pd.Series)
        assert "Sortino Ratio" in stats

    def test_optimize_portfolio(self) -> None:
        """Test portfolio optimization with indicator."""
        indicator = pd.Series.diff
        stats = hist.optimize_portfolio(orders_close, indicator, 1, "day", 225).stats()
        assert isinstance(stats, pd.Series)
        assert "Sortino Ratio" in stats

    def test_fill(self) -> None:
        """Test filling signal gaps with ffill and nearest methods."""
        ffill = hist.fill(arr)
        assert np.array_equal(ffill, test_ffill)
        nfill = hist.fill(arr, "nearest")
        assert np.array_equal(nfill, test_nfill)

    def test_unfill(self) -> None:
        """Test reversing filled signals back to sparse form."""
        result_fs = hist.unfill(fs)
        result_ns = hist.unfill(ns)
        # Check lengths match
        assert len(result_fs) == len(unfilled_fs)
        assert len(result_ns) == len(unfilled_ns)
        # Check first elements (always kept)
        assert result_fs[0] == unfilled_fs[0]
        assert result_ns[0] == unfilled_ns[0]
        # Check None positions match
        assert all(
            (r is None) == (e is None)
            for r, e in zip(result_fs, unfilled_fs, strict=True)
        )
        assert all(
            (r is None) == (e is None)
            for r, e in zip(result_ns, unfilled_ns, strict=True)
        )

    def test_get_optimal_signals(self) -> None:
        """Test generating optimal trading signals from prices."""
        f_signals = hist.get_optimal_signals(close, n=2, method="ffill")
        assert np.array_equal(f_signals, test_ffill)
        n_signals = hist.get_optimal_signals(close, n=2, method="nfill")
        assert np.array_equal(n_signals, test_nfill)

    def test_generate_random(self) -> None:
        """Test generating random trading strategies."""
        strats = hist.generate_random(close, num=100)
        assert 0 < len(strats) <= 25

    def test_preprocess(self) -> None:
        """Test preprocessing data for ML training."""
        X_train = hist.preprocess(X, y)[0]
        assert len(X_train) > (len(X) * 0.8)

    def test_undersample(self) -> None:
        """Test undersampling to balance class distribution."""
        y_train = hist.undersample(X, y)[2]
        assert np.mean(y_train) == 0.5

    def test_run_classifiers(self) -> None:
        """Test running multiple ML classifiers."""
        X_train, X_test, y_train, y_test = hist.undersample(X, y)[:4]
        clfs = hist.run_classifiers(X_train, X_test, y_train, y_test)
        for _, clf in clfs:
            assert "score" in clf

    def test_optimize_portfolio_with_time_column(self) -> None:
        """Test optimize_portfolio with TIME column in data (line 53)."""
        # Create data with TIME column instead of index
        close_with_time = pd.DataFrame(
            {
                C.TIME: pd.to_datetime(["2025-01-01", "2025-01-02"]),
                "AAPL": [200, 100],
                "META": [25, 50],
            }
        )
        indicator = pd.Series.diff
        stats = hist.optimize_portfolio(
            close_with_time, indicator, 1, "day", 225
        ).stats()
        assert isinstance(stats, pd.Series)
        assert "Sortino Ratio" in stats

    def test_unfill_empty(self) -> None:
        """Test unfill with empty list (line 115)."""
        result = hist.unfill([])
        assert result == []

    def test_preprocess_no_pca(self) -> None:
        """Test preprocess with num_pca=0 (lines 190, 195)."""
        result = hist.preprocess(X, y, num_pca=0)
        X_train = result[0]
        pca = result[7]  # pca should be None
        assert len(X_train) > 0
        assert pca is None
