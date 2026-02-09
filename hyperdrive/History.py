"""Backtesting and machine learning utilities for trading strategies."""

from collections.abc import Callable
from typing import Any, cast

import numpy as np
import pandas as pd
import vectorbt as vbt
from imblearn.over_sampling import SMOTE
from scipy.signal import argrelextrema
from sklearn.decomposition import PCA
from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis
from sklearn.ensemble import AdaBoostClassifier, RandomForestClassifier
from sklearn.gaussian_process import GaussianProcessClassifier
from sklearn.gaussian_process.kernels import RBF
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import GaussianNB
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.tree import DecisionTreeClassifier

from . import Constants as C
from .Calculus import Calculator


class Historian:
    """Backtesting and ML utility for trading strategy development.

    Provides methods for portfolio creation, signal generation,
    feature preprocessing, and classifier evaluation.

    Attributes:
        calc: Calculator instance for mathematical operations.
    """

    def __init__(self) -> None:
        """Initialize the Historian with a Calculator instance."""
        self.calc = Calculator()

    def from_holding(self, close: pd.Series, init_cash: float = 1000) -> vbt.Portfolio:
        """Create a portfolio based on buy-and-hold strategy.

        Args:
            close: Series of closing prices.
            init_cash: Initial cash amount.

        Returns:
            A vectorbt Portfolio object.
        """
        portfolio = vbt.Portfolio.from_holding(close, init_cash=init_cash, freq="D")
        return portfolio

    def from_signals(
        self,
        close: pd.Series,
        signals: pd.Series,
        init_cash: float = 1000,
        fee: float = 0,
    ) -> vbt.Portfolio:
        """Create a portfolio based on trading signals.

        Args:
            close: Series of closing prices.
            signals: Boolean series indicating buy signals.
            init_cash: Initial cash amount.
            fee: Trading fee as a decimal.

        Returns:
            A vectorbt Portfolio object.
        """
        portfolio = vbt.Portfolio.from_signals(
            close, signals, ~signals, init_cash=init_cash, freq="D", fees=fee
        )
        return portfolio

    def optimize_portfolio(
        self,
        close: pd.DataFrame,
        indicator: Callable[..., pd.Series],
        top_n: int,
        period: str,
        init_cash: float,
        **kwargs: Any,
    ) -> vbt.Portfolio:
        """Optimize a portfolio by rotating into top-ranked assets.

        Args:
            close: DataFrame of closing prices with symbols as columns.
            indicator: Function to compute ranking indicator.
            top_n: Number of top assets to hold.
            period: Rebalancing period attribute (e.g., 'month', 'week').
            init_cash: Initial cash amount.
            **kwargs: Additional arguments passed to indicator function.

        Returns:
            A vectorbt Portfolio object.
        """
        if C.TIME in close.columns:
            close = close.set_index(C.TIME)
        signals = close.apply(indicator, **kwargs)
        close = close.dropna()
        positions = pd.DataFrame(0, index=close.index, columns=close.columns)
        holdings: dict[str, float] = {"cash": init_cash}
        prev_period = None
        prev_symbols: set[str] = set()
        for day in close.index:
            curr_period = getattr(day, period)
            # if is first of the period
            if prev_period != curr_period:
                # Rank symbols by indicator and select top_n
                # filter signals by include/exclude param for each period
                top_symbols = set(signals.loc[day].nlargest(top_n).index)
                minus, plus = self.calc.get_difference(prev_symbols, top_symbols)
                # Sell old positions for the top symbols
                for symbol in minus:
                    size = holdings[symbol]
                    positions.loc[day, symbol] = -size
                    holdings["cash"] += close.loc[day][symbol] * size
                    del holdings[symbol]
                # Buy new positions for the top symbols
                notional = holdings["cash"] / len(plus)
                for symbol in plus:
                    size = notional / close.loc[day][symbol]
                    positions.loc[day, symbol] = size
                    holdings[symbol] = size
                    holdings["cash"] -= notional
                # Update prev values
                prev_period = curr_period
                prev_symbols = top_symbols

        # Forward fill positions to maintain holdings
        positions = positions.ffill().fillna(0)

        # Convert to orders format
        portfolio = vbt.Portfolio.from_orders(
            close=close, size=positions, freq="D", init_cash=0, group_by=True
        )
        return portfolio

    def from_orders(
        self, close: pd.DataFrame, size: pd.DataFrame, fee: float = 0
    ) -> vbt.Portfolio:
        """Create a portfolio from order sizes.

        Args:
            close: DataFrame of closing prices.
            size: DataFrame of order sizes.
            fee: Trading fee as a decimal.

        Returns:
            A vectorbt Portfolio object.
        """
        portfolio = vbt.Portfolio.from_orders(
            close, size, freq="D", fees=fee, init_cash=0, group_by=True
        )
        return portfolio

    def fill(
        self, arr: np.ndarray, method: str = "ffill", type: str = "bool"
    ) -> np.ndarray:
        """Fill missing values in an array.

        Args:
            arr: Array with missing values.
            method: Fill method ('ffill' for forward fill).
            type: Output dtype.

        Returns:
            Filled array.
        """
        df = pd.DataFrame(arr)
        s = df.iloc[:, 0]
        if method == "ffill":
            s = s.fillna(method="ffill")
        s = pd.to_numeric(s)
        s = s.interpolate(method="nearest").astype(type)
        out = s.to_numpy().flatten()
        return out

    def unfill(self, xs: list[Any]) -> list[Any]:
        """Remove consecutive duplicates from a list.

        Args:
            xs: Input list with potential duplicates.

        Returns:
            List with consecutive duplicates replaced by None.
        """
        if not len(xs):
            return xs
        curr = xs[0]
        new = [curr]
        for x in xs[1:]:
            if curr != x:
                new.append(x)
                curr = x
            else:
                new.append(None)
        return new

    def get_optimal_signals(
        self, close: np.ndarray | pd.Series, n: int = 10, method: str = "ffill"
    ) -> np.ndarray:
        """Find optimal buy/sell signals based on local extrema.

        Args:
            close: Array of closing prices.
            n: Order parameter for extrema detection.
            method: Fill method for missing signals.

        Returns:
            Boolean array of buy signals.
        """
        close_arr = np.array(close)
        mins = argrelextrema(close_arr, np.less_equal, order=n)[0]
        maxs = argrelextrema(close_arr, np.greater_equal, order=n)[0]

        signals = np.empty_like(close_arr, dtype="object")
        signals[:] = np.nan
        signals[mins] = True
        signals[maxs] = False

        return self.fill(signals, method=method)

    def generate_random(self, close: pd.Series, num: int = 10**4) -> list[pd.Series]:
        """Generate random trading strategies and return top performers.

        Args:
            close: Series of closing prices.
            num: Number of random strategies to generate.

        Returns:
            List of signal series for top-performing strategies.
        """
        good_signals = []
        portfolios = []
        sortinos = []
        calmars = []
        num_strats = num
        top_n = 25
        prob = self.get_optimal_signals(close).mean()

        for _ in range(num_strats):
            signals = pd.DataFrame.vbt.signals.generate_random(  # type: ignore[attr-defined]
                (len(close), 1), prob=prob
            )[0]
            portfolio = vbt.Portfolio.from_signals(
                close, signals, ~signals, init_cash=1000, freq="D"
            )
            sortinos.append(portfolio.sortino_ratio())  # type: ignore[attr-defined]
            calmars.append(portfolio.calmar_ratio())  # type: ignore[attr-defined]
            good_signals.append(signals)
            portfolios.append(portfolio)

        top_s = set(np.argpartition(sortinos, -top_n)[-top_n:])
        top_c = set(np.argpartition(calmars, -top_n)[-top_n:])
        top_idxs = top_s.intersection(top_c)

        portfolios = [
            portfolio for idx, portfolio in enumerate(portfolios) if idx in top_idxs
        ]
        good_signals = [
            signal for idx, signal in enumerate(good_signals) if idx in top_idxs
        ]
        return good_signals

    def oversample(
        self, X_train: np.ndarray, y_train: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Oversample minority class using SMOTE.

        Args:
            X_train: Training features.
            y_train: Training labels.

        Returns:
            Tuple of resampled features and labels.
        """
        sm = SMOTE()
        X_res, y_res = sm.fit_resample(X_train, y_train)
        return X_res, y_res

    def preprocess(
        self, X: np.ndarray, y: np.ndarray, num_pca: int = 2
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        StandardScaler,
        PCA | None,
        StandardScaler,
        PCA | None,
    ]:
        """Preprocess data with train/test split, scaling, and PCA.

        Args:
            X: Feature matrix.
            y: Target labels.
            num_pca: Number of PCA components (0 to skip PCA).

        Returns:
            Tuple of processed data and fitted transformers.
        """
        df = pd.DataFrame(X)
        df["y"] = y
        df = df.dropna()
        y = df["y"].to_numpy()
        X = df.drop("y", axis=1).to_numpy()
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)
        X_train, y_train = self.oversample(X_train, y_train)
        X_train, X_test, scaler = cast(
            tuple[np.ndarray, np.ndarray, StandardScaler],
            self.standardize(X_train, X_test),
        )
        if num_pca:
            X_train, X_test, pca = cast(
                tuple[np.ndarray, np.ndarray, PCA],
                self.pca(X_train, num_pca, X_test),
            )
        else:
            pca = None
        X, full_scaler = cast(
            tuple[np.ndarray, StandardScaler],
            self.standardize(X),
        )
        if num_pca:
            X, full_pca = cast(tuple[np.ndarray, PCA], self.pca(X, num_pca))
        else:
            full_pca = None

        return (
            X_train,
            X_test,
            y_train,
            y_test,
            X,
            y,
            scaler,
            pca,
            full_scaler,
            full_pca,
        )

    def undersample(
        self, X: np.ndarray, y: np.ndarray, n: int = 2
    ) -> tuple[
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        np.ndarray,
        StandardScaler,
        PCA,
        StandardScaler,
        PCA,
    ]:
        """Undersample majority class and preprocess data.

        Args:
            X: Feature matrix.
            y: Target labels.
            n: Number of PCA components.

        Returns:
            Tuple of processed data and fitted transformers.
        """
        df = pd.DataFrame(X)
        df["y"] = y
        df = df.dropna()
        y = df["y"].to_numpy()
        X = df.drop("y", axis=1).to_numpy()
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)

        train_true = 0
        train_false = 0
        X_train_new = []
        y_train_new = []
        train_num = len(y_train) - sum(y_train)
        # use arr[mask]all[:num] instead to get
        for idx, signal in enumerate(y_train):
            if signal and train_true < train_num:
                train_true += 1
            elif not signal and train_false < train_num:
                train_false += 1
            else:
                continue
            X_train_new.append(X_train[idx])
            y_train_new.append(y_train[idx])
        X_train = np.array(X_train_new)
        y_train = np.array(y_train_new)

        X_train, X_test, scaler = cast(
            tuple[np.ndarray, np.ndarray, StandardScaler],
            self.standardize(X_train, X_test),
        )
        X_train, X_test, pca = cast(
            tuple[np.ndarray, np.ndarray, PCA],
            self.pca(X_train, n, X_test),
        )
        X, full_scaler = cast(tuple[np.ndarray, StandardScaler], self.standardize(X))
        X, full_pca = cast(tuple[np.ndarray, PCA], self.pca(X, n))

        return (
            X_train,
            X_test,
            y_train,
            y_test,
            X,
            y,
            scaler,
            pca,
            full_scaler,
            full_pca,
        )

    def standardize(
        self, X_train: np.ndarray, X_test: np.ndarray | None = None
    ) -> (
        tuple[np.ndarray, StandardScaler]
        | tuple[np.ndarray, np.ndarray, StandardScaler]
    ):
        """Standardize features using StandardScaler.

        Args:
            X_train: Training features to fit and transform.
            X_test: Optional test features to transform.

        Returns:
            Transformed features and fitted scaler.
        """
        scaler = StandardScaler().fit(X_train)
        X_train = scaler.transform(X_train)
        if isinstance(X_test, np.ndarray):
            X_test = scaler.transform(X_test)
            return X_train, X_test, scaler
        return X_train, scaler

    def pca(
        self, X_train: np.ndarray, n: int, X_test: np.ndarray | None = None
    ) -> tuple[np.ndarray, PCA] | tuple[np.ndarray, np.ndarray, PCA]:
        """Apply PCA dimensionality reduction.

        Args:
            X_train: Training features to fit and transform.
            n: Number of components.
            X_test: Optional test features to transform.

        Returns:
            Transformed features and fitted PCA object.
        """
        num_features = X_train.shape[1]
        n = n if n <= num_features else num_features
        pca = PCA(n_components=n).fit(X_train)
        X_train = pca.transform(X_train)
        if isinstance(X_test, np.ndarray):
            X_test = pca.transform(X_test)
            var = pca.explained_variance_ratio_.sum() * 100
            print(f"Explained variance (X_train): {round(var, 2)}%")
            return X_train, X_test, pca
        var = pca.explained_variance_ratio_.sum() * 100
        print(f"Explained variance (X): {round(var, 2)}%")
        return X_train, pca

    def run_classifiers(
        self,
        X_train: np.ndarray,
        X_test: np.ndarray,
        y_train: np.ndarray,
        y_test: np.ndarray,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Evaluate multiple classifiers on the data.

        Args:
            X_train: Training features.
            X_test: Test features.
            y_train: Training labels.
            y_test: Test labels.

        Returns:
            Sorted list of (name, results) tuples for non-overfitting classifiers.
        """
        names = [
            "Nearest Neighbors",
            "Linear SVM",
            "RBF SVM",
            "Gaussian Process",
            "Decision Tree",
            "Random Forest",
            "Neural Net",
            "AdaBoost",
            "Naive Bayes",
            "QDA",
        ]
        classifiers = [
            KNeighborsClassifier(3),
            SVC(kernel="linear", C=0.025),
            SVC(gamma=2, C=1),
            GaussianProcessClassifier(1.0 * RBF(1.0)),
            DecisionTreeClassifier(max_depth=5),
            RandomForestClassifier(max_depth=5, n_estimators=10, max_features=1),
            MLPClassifier(alpha=1, max_iter=1000),
            AdaBoostClassifier(),
            GaussianNB(),
            QuadraticDiscriminantAnalysis(),
        ]

        clfs: dict[str, dict[str, Any]] = {}

        for name, clf in zip(names, classifiers, strict=True):
            clf.fit(X_train, y_train)
            score = clf.score(X_test, y_test)
            report = classification_report(
                y_test, clf.predict(X_test), output_dict=True
            )
            ratio = clf.score(X_train, y_train) / score
            if ratio < 1.15:
                clfs[name] = {
                    "score": score,
                    "report": report,
                    "ratio": ratio,
                    "clf": clf,
                }
        clfs_sorted = sorted(
            clfs.items(), reverse=True, key=lambda clf: clf[1]["score"]
        )
        return clfs_sorted
