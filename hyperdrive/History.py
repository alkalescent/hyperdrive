import numpy as np
import pandas as pd
import vectorbt as vbt
from scipy.signal import argrelextrema
from sklearn.model_selection import train_test_split
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPClassifier
from sklearn.neighbors import KNeighborsClassifier
from sklearn.svm import SVC
from sklearn.gaussian_process import GaussianProcessClassifier
from sklearn.gaussian_process.kernels import RBF
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, AdaBoostClassifier
from sklearn.naive_bayes import GaussianNB
from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis
from sklearn.metrics import classification_report
from imblearn.over_sampling import SMOTE
from Calculus import Calculator
import Constants as C


class Historian:
    def __init__(self):
        self.calc = Calculator()

    # add fx to perform calculations on columns
    # takes calc.fx, df, and column names as args, fx args

    def from_holding(self, close, init_cash=1000):
        # returns a portfolio based on buy and hold strategy
        portfolio = vbt.Portfolio.from_holding(
            close, init_cash=init_cash, freq='D')
        return portfolio

    def from_signals(self, close, signals, init_cash=1000, fee=0):
        # returns a portfolio based on signals
        portfolio = vbt.Portfolio.from_signals(
            close, signals, ~signals, init_cash=init_cash, freq='D', fees=fee
        )
        return portfolio

    def optimize_portfolio(
            self,
            close: pd.DataFrame,
            indicator: callable,
            top_n: int,
            period: str,
            init_cash: float,
            **kwargs: dict[str, any]
    ) -> vbt.Portfolio:
        if C.TIME in close.columns:
            close = close.set_index(C.TIME)
        signals = close.apply(indicator, **kwargs)
        close = close.dropna()
        positions = pd.DataFrame(
            0, index=close.index, columns=close.columns)
        holdings = {"cash": init_cash}
        prev_period = None
        prev_symbols = set()
        for day in close.index:
            curr_period = getattr(day, period)
            # if is first of the period
            if prev_period != curr_period:
                # Rank symbols by indicator and select top_n
                # filter signals by include/exclude param for each period
                top_symbols = set(signals.loc[day].nlargest(top_n).index)
                minus, plus = self.calc.get_difference(
                    prev_symbols, top_symbols)
                # Sell old positions for the top symbols
                for symbol in minus:
                    size = holdings[symbol]
                    positions.loc[day, symbol] = - size
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
            close=close,
            size=positions,
            freq='D',
            init_cash=0,
            group_by=True
        )
        return portfolio

    def from_orders(
            self,
            close: pd.DataFrame,
            size: pd.DataFrame,
            fee: float = 0
    ) -> vbt.Portfolio:
        portfolio = vbt.Portfolio.from_orders(
            close, size, freq='D', fees=fee, init_cash=0, group_by=True
        )
        return portfolio

    def fill(self, arr, method='ffill', type='bool'):
        # forward fills or nearest fills an array
        df = pd.DataFrame(arr)
        s = df.iloc[:, 0]
        if method == 'ffill':
            s = s.fillna(method='ffill')
        s = pd.to_numeric(s)
        s = s.interpolate(method='nearest').astype(type)
        out = s.to_numpy().flatten()
        return out

    def unfill(self, xs):
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

    def get_optimal_signals(self, close, n=10, method='ffill'):
        # finds the optimal signals for an array of prices
        close = np.array(close)
        mins = argrelextrema(close, np.less_equal,
                             order=n)[0]
        maxs = argrelextrema(close, np.greater_equal,
                             order=n)[0]

        signals = np.empty_like(close, dtype='object')
        signals[:] = np.nan
        signals[mins] = True
        signals[maxs] = False

        return self.fill(signals, method=method)

    def generate_random(self, close, num=10**4):
        # generate random strategies
        good_signals = []
        portfolios = []
        sortinos = []
        calmars = []
        num_strats = num
        top_n = 25
        prob = self.get_optimal_signals(close).mean()

        for _ in range(num_strats):
            signals = pd.DataFrame.vbt.signals.generate_random(
                (len(close), 1), prob=prob)[0]
            portfolio = vbt.Portfolio.from_signals(
                close, signals, ~signals, init_cash=1000, freq='D')
            sortinos.append(portfolio.sortino_ratio())
            calmars.append(portfolio.calmar_ratio())
            good_signals.append(signals)
            portfolios.append(portfolio)

        top_s = set(np.argpartition(sortinos, -top_n)[-top_n:])
        top_c = set(np.argpartition(calmars, -top_n)[-top_n:])
        top_idxs = top_s.intersection(top_c)

        portfolios = [portfolio for idx, portfolio in enumerate(
            portfolios) if idx in top_idxs]
        good_signals = [signal for idx, signal in enumerate(
            good_signals) if idx in top_idxs]
        return good_signals

    def oversample(self, X_train, y_train):
        sm = SMOTE()
        X_res, y_res = sm.fit_resample(X_train, y_train)
        return X_res, y_res

    def preprocess(self, X, y, num_pca=2):
        df = pd.DataFrame(X)
        df['y'] = y
        df = df.dropna()
        y = df['y'].to_numpy()
        X = df.drop('y', axis=1).to_numpy()
        X_train, X_test, y_train, y_test = \
            train_test_split(X, y, test_size=.2)
        X_train, y_train = self.oversample(X_train, y_train)
        X_train, X_test, scaler = self.standardize(X_train, X_test)
        if num_pca:
            X_train, X_test, pca = self.pca(X_train, num_pca, X_test)
        else:
            pca = None
        X, full_scaler = self.standardize(X)
        if num_pca:
            X, full_pca = self.pca(X, num_pca)
        else:
            full_pca = None

        return (
            X_train, X_test, y_train, y_test,
            X, y, scaler, pca, full_scaler, full_pca
        )

    def undersample(self, X, y, n=2):
        # undersample, split train / test data, and standardize
        df = pd.DataFrame(X)
        df['y'] = y
        df = df.dropna()
        y = df['y'].to_numpy()
        X = df.drop('y', axis=1).to_numpy()
        X_train, X_test, y_train, y_test = \
            train_test_split(X, y, test_size=.2)

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

        X_train, X_test, scaler = self.standardize(X_train, X_test)
        X_train, X_test, pca = self.pca(X_train, n, X_test)
        X, full_scaler = self.standardize(X)
        X, full_pca = self.pca(X, n)

        return (
            X_train, X_test, y_train, y_test,
            X, y, scaler, pca, full_scaler, full_pca
        )

    def standardize(self, X_train, X_test=None):
        scaler = StandardScaler().fit(X_train)
        X_train = scaler.transform(X_train)
        if isinstance(X_test, np.ndarray):
            X_test = scaler.transform(X_test)
            return X_train, X_test, scaler
        return X_train, scaler

    def pca(self, X_train, n, X_test=None):
        num_features = X_train.shape[1]
        n = n if n <= num_features else num_features
        pca = PCA(n_components=n).fit(X_train)
        X_train = pca.transform(X_train)
        if isinstance(X_test, np.ndarray):
            X_test = pca.transform(X_test)
            var = pca.explained_variance_ratio_.sum() * 100
            print(f'Explained variance (X_train): {round(var, 2)}%')
            return X_train, X_test, pca
        var = pca.explained_variance_ratio_.sum() * 100
        print(f'Explained variance (X): {round(var, 2)}%')
        return X_train, pca

    def run_classifiers(self, X_train, X_test, y_train, y_test):
        names = [
            "Nearest Neighbors", "Linear SVM", "RBF SVM", "Gaussian Process",
            "Decision Tree", "Random Forest", "Neural Net", "AdaBoost",
            "Naive Bayes", "QDA"]
        classifiers = [
            KNeighborsClassifier(3),
            SVC(kernel="linear", C=0.025),
            SVC(gamma=2, C=1),
            GaussianProcessClassifier(1.0 * RBF(1.0)),
            DecisionTreeClassifier(max_depth=5),
            RandomForestClassifier(
                max_depth=5, n_estimators=10, max_features=1),
            MLPClassifier(alpha=1, max_iter=1000),
            AdaBoostClassifier(),
            GaussianNB(),
            QuadraticDiscriminantAnalysis()]

        clfs = {}

        for name, clf in zip(names, classifiers):
            clf.fit(X_train, y_train)
            score = clf.score(X_test, y_test)
            report = classification_report(
                y_test, clf.predict(X_test), output_dict=True)
            ratio = clf.score(X_train, y_train) / score
            if ratio < 1.15:
                clfs[name] = {'score': score, 'report': report,
                              'ratio': ratio, 'clf': clf}
        clfs = sorted(clfs.items(), reverse=True,
                      key=lambda clf: clf[1]['score'])
        return clfs
