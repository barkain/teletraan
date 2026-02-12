"""Statistical feature calculator for computing market analysis features.

This module provides a StatisticalFeatureCalculator class that computes
various statistical features for market symbols including momentum,
mean-reversion, volatility, seasonality, and cross-sectional metrics.
"""

import logging
from datetime import date as date_type

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.statistical_feature import StatisticalFeature, StatisticalFeatureType
from models.stock import Stock
from models.price import PriceHistory

logger = logging.getLogger(__name__)


class StatisticalFeatureCalculator:
    """Compute statistical features for market analysis.

    This calculator generates quantitative signals from price and volume data,
    including momentum metrics, z-scores, volatility regimes, seasonality effects,
    and cross-sectional rankings.
    """

    # Sector ETF mappings for relative strength calculations
    SECTOR_TO_ETF: dict[str, str] = {
        "Technology": "XLK",
        "Health Care": "XLV",
        "Financials": "XLF",
        "Consumer Discretionary": "XLY",
        "Consumer Staples": "XLP",
        "Energy": "XLE",
        "Industrials": "XLI",
        "Materials": "XLB",
        "Utilities": "XLU",
        "Real Estate": "XLRE",
        "Communication Services": "XLC",
    }

    def __init__(self, db_session: AsyncSession) -> None:
        """Initialize the calculator with a database session.

        Args:
            db_session: Async SQLAlchemy session for database operations.
        """
        self.db = db_session

    async def compute_all_features(
        self,
        symbols: list[str],
        calculation_date: date_type | None = None,
    ) -> list[StatisticalFeature]:
        """Compute all statistical features for the given symbols.

        This is the main entry point that orchestrates all feature calculations.

        Args:
            symbols: List of stock symbols to analyze.
            calculation_date: Date for calculations. Defaults to today.

        Returns:
            List of computed StatisticalFeature objects.
        """
        if calculation_date is None:
            calculation_date = date_type.today()

        all_features: list[StatisticalFeature] = []
        prices_dict: dict[str, pd.DataFrame] = {}

        # Fetch price data for all symbols
        for symbol in symbols:
            try:
                prices_df = await self._get_price_data(symbol, lookback_days=300)
                if prices_df is not None and len(prices_df) > 0:
                    prices_dict[symbol] = prices_df
            except Exception as e:
                logger.warning(f"Failed to fetch price data for {symbol}: {e}")

        # Compute features for each symbol
        for symbol, prices_df in prices_dict.items():
            try:
                # Momentum features
                momentum_features = await self._compute_momentum_features(
                    symbol, prices_df, calculation_date
                )
                all_features.extend(momentum_features)

                # Mean reversion features
                mean_reversion_features = await self._compute_mean_reversion_features(
                    symbol, prices_df, calculation_date
                )
                all_features.extend(mean_reversion_features)

                # Volatility regime features
                volatility_features = await self._compute_volatility_regime(
                    symbol, prices_df, calculation_date
                )
                all_features.extend(volatility_features)

                # Seasonality features
                seasonality_features = await self._compute_seasonality_features(
                    symbol, prices_df, calculation_date
                )
                all_features.extend(seasonality_features)

            except Exception as e:
                logger.error(f"Error computing features for {symbol}: {e}")

        # Cross-sectional features (require all symbols)
        try:
            cross_sectional_features = await self._compute_cross_sectional_ranks(
                symbols, prices_dict, calculation_date
            )
            all_features.extend(cross_sectional_features)
        except Exception as e:
            logger.error(f"Error computing cross-sectional features: {e}")

        # Save features to database
        await self._save_features(all_features)

        return all_features

    async def _compute_momentum_features(
        self,
        symbol: str,
        prices: pd.DataFrame,
        calculation_date: date_type,
    ) -> list[StatisticalFeature]:
        """Calculate momentum (Rate of Change) features.

        Computes ROC for 5, 10, and 20 day periods.
        ROC = (current - prior) / prior * 100

        Args:
            symbol: Stock symbol.
            prices: DataFrame with OHLCV data.
            calculation_date: Date for the calculation.

        Returns:
            List of momentum StatisticalFeature objects.
        """
        features: list[StatisticalFeature] = []

        if len(prices) < 21:
            return features

        closes = prices["close"].values
        current_price = closes[-1]

        periods = [
            (5, StatisticalFeatureType.MOMENTUM_ROC_5D),
            (10, StatisticalFeatureType.MOMENTUM_ROC_10D),
            (20, StatisticalFeatureType.MOMENTUM_ROC_20D),
        ]

        for days, feature_type in periods:
            if len(closes) > days:
                prior_price = closes[-(days + 1)]
                if prior_price != 0:
                    roc = ((current_price - prior_price) / prior_price) * 100
                    signal = "bullish" if roc > 0 else "bearish"

                    # Calculate percentile ranking across history
                    roc_series = pd.Series(closes).pct_change(periods=days) * 100
                    roc_series = roc_series.dropna()
                    percentile = (
                        (roc_series < roc).sum() / len(roc_series) * 100
                        if len(roc_series) > 0
                        else None
                    )

                    features.append(
                        StatisticalFeature(
                            symbol=symbol,
                            feature_type=feature_type.value,
                            value=round(roc, 4),
                            signal=signal,
                            percentile=round(percentile, 2) if percentile else None,
                            calculation_date=calculation_date,
                            metadata_json={
                                "period_days": days,
                                "current_price": round(current_price, 2),
                                "prior_price": round(prior_price, 2),
                            },
                        )
                    )

        return features

    async def _compute_mean_reversion_features(
        self,
        symbol: str,
        prices: pd.DataFrame,
        calculation_date: date_type,
    ) -> list[StatisticalFeature]:
        """Calculate mean reversion features.

        Computes Z-Score for 20D and 50D windows, and Bollinger deviation.
        Z-Score = (price - mean) / std
        Signal: <-2 = "oversold", >2 = "overbought", else "neutral"

        Args:
            symbol: Stock symbol.
            prices: DataFrame with OHLCV data.
            calculation_date: Date for the calculation.

        Returns:
            List of mean reversion StatisticalFeature objects.
        """
        features: list[StatisticalFeature] = []

        if len(prices) < 51:
            return features

        closes = prices["close"].values
        current_price = closes[-1]

        # Z-Score calculations
        zscore_configs = [
            (20, StatisticalFeatureType.ZSCORE_20D),
            (50, StatisticalFeatureType.ZSCORE_50D),
        ]

        for window, feature_type in zscore_configs:
            if len(closes) >= window:
                window_prices = closes[-window:]
                mean = np.mean(window_prices)
                std = np.std(window_prices, ddof=1)

                if std > 0:
                    zscore = (current_price - mean) / std

                    if zscore < -2:
                        signal = "oversold"
                    elif zscore > 2:
                        signal = "overbought"
                    else:
                        signal = "neutral"

                    # Calculate historical percentile
                    rolling_mean = pd.Series(closes).rolling(window=window).mean()
                    rolling_std = pd.Series(closes).rolling(window=window).std()
                    historical_zscore = (pd.Series(closes) - rolling_mean) / rolling_std
                    historical_zscore = historical_zscore.dropna()

                    percentile = (
                        (historical_zscore < zscore).sum() / len(historical_zscore) * 100
                        if len(historical_zscore) > 0
                        else None
                    )

                    features.append(
                        StatisticalFeature(
                            symbol=symbol,
                            feature_type=feature_type.value,
                            value=round(zscore, 4),
                            signal=signal,
                            percentile=round(percentile, 2) if percentile else None,
                            calculation_date=calculation_date,
                            metadata_json={
                                "window_days": window,
                                "mean": round(mean, 2),
                                "std": round(std, 4),
                                "current_price": round(current_price, 2),
                            },
                        )
                    )

        # Bollinger Band deviation
        if len(closes) >= 20:
            sma_20 = np.mean(closes[-20:])
            std_20 = np.std(closes[-20:], ddof=1)

            if sma_20 > 0 and std_20 > 0:
                # Calculate % distance from middle band (SMA)
                deviation_pct = ((current_price - sma_20) / sma_20) * 100

                # Band positions
                upper_band = sma_20 + 2 * std_20
                lower_band = sma_20 - 2 * std_20

                if current_price > upper_band:
                    signal = "overbought"
                elif current_price < lower_band:
                    signal = "oversold"
                else:
                    signal = "neutral"

                features.append(
                    StatisticalFeature(
                        symbol=symbol,
                        feature_type=StatisticalFeatureType.BOLLINGER_DEVIATION.value,
                        value=round(deviation_pct, 4),
                        signal=signal,
                        percentile=None,
                        calculation_date=calculation_date,
                        metadata_json={
                            "sma_20": round(sma_20, 2),
                            "std_20": round(std_20, 4),
                            "upper_band": round(upper_band, 2),
                            "lower_band": round(lower_band, 2),
                            "current_price": round(current_price, 2),
                        },
                    )
                )

        return features

    async def _compute_volatility_regime(
        self,
        symbol: str,
        prices: pd.DataFrame,
        calculation_date: date_type,
    ) -> list[StatisticalFeature]:
        """Calculate volatility regime features.

        Computes ATR percentile over 252 trading days and classifies regime:
        - <25%ile = "low"
        - 25-50 = "normal"
        - 50-75 = "elevated"
        - >75 = "crisis"

        Args:
            symbol: Stock symbol.
            prices: DataFrame with OHLCV data.
            calculation_date: Date for the calculation.

        Returns:
            List of volatility StatisticalFeature objects.
        """
        features: list[StatisticalFeature] = []

        if len(prices) < 15:
            return features

        highs = prices["high"].values
        lows = prices["low"].values
        closes = prices["close"].values

        # Calculate True Range
        true_ranges: list[float] = []
        true_ranges.append(highs[0] - lows[0])

        for i in range(1, len(highs)):
            high_low = highs[i] - lows[i]
            high_close = abs(highs[i] - closes[i - 1])
            low_close = abs(lows[i] - closes[i - 1])
            true_ranges.append(max(high_low, high_close, low_close))

        tr_series = pd.Series(true_ranges)

        # Calculate ATR (14-period)
        atr_series = tr_series.rolling(window=14).mean()
        atr_series = atr_series.dropna()

        if len(atr_series) == 0:
            return features

        current_atr = atr_series.iloc[-1]

        # Calculate percentile over available history (up to 252 days)
        lookback = min(252, len(atr_series))
        historical_atr = atr_series.tail(lookback)
        percentile = (historical_atr < current_atr).sum() / len(historical_atr) * 100

        # Determine regime
        if percentile < 25:
            regime = "low"
        elif percentile < 50:
            regime = "normal"
        elif percentile < 75:
            regime = "elevated"
        else:
            regime = "crisis"

        # Create volatility regime feature
        features.append(
            StatisticalFeature(
                symbol=symbol,
                feature_type=StatisticalFeatureType.VOLATILITY_REGIME.value,
                value=round(current_atr, 4),
                signal=regime,
                percentile=round(percentile, 2),
                calculation_date=calculation_date,
                metadata_json={
                    "atr_14": round(current_atr, 4),
                    "regime": regime,
                    "lookback_days": lookback,
                },
            )
        )

        # Create volatility percentile feature
        features.append(
            StatisticalFeature(
                symbol=symbol,
                feature_type=StatisticalFeatureType.VOLATILITY_PERCENTILE.value,
                value=round(percentile, 2),
                signal=regime,
                percentile=round(percentile, 2),
                calculation_date=calculation_date,
                metadata_json={
                    "current_atr": round(current_atr, 4),
                    "min_atr_lookback": round(historical_atr.min(), 4),
                    "max_atr_lookback": round(historical_atr.max(), 4),
                    "lookback_days": lookback,
                },
            )
        )

        return features

    async def _compute_seasonality_features(
        self,
        symbol: str,
        prices: pd.DataFrame,
        calculation_date: date_type,
    ) -> list[StatisticalFeature]:
        """Calculate seasonality effect features.

        Computes day-of-week and month effects based on historical patterns.
        Signal: "positive_bias" or "negative_bias" based on historical data.

        Args:
            symbol: Stock symbol.
            prices: DataFrame with OHLCV data.
            calculation_date: Date for the calculation.

        Returns:
            List of seasonality StatisticalFeature objects.
        """
        features: list[StatisticalFeature] = []

        if len(prices) < 50:
            return features

        closes = prices["close"].values
        dates = prices["date"].values

        # Calculate daily returns
        returns = pd.Series(closes).pct_change() * 100
        returns = returns.dropna()

        if len(returns) == 0:
            return features

        # Convert dates to pandas datetime for day/month extraction
        date_series = pd.to_datetime(dates[1:])  # Skip first due to pct_change

        # Day of week effect
        current_dow = calculation_date.weekday()
        dow_mask = date_series.dayofweek == current_dow
        dow_returns = returns.iloc[dow_mask.values] if dow_mask.any() else pd.Series()

        if len(dow_returns) > 5:
            avg_dow_return = dow_returns.mean()
            signal = "positive_bias" if avg_dow_return > 0 else "negative_bias"

            features.append(
                StatisticalFeature(
                    symbol=symbol,
                    feature_type=StatisticalFeatureType.DAY_OF_WEEK_EFFECT.value,
                    value=round(avg_dow_return, 4),
                    signal=signal,
                    percentile=None,
                    calculation_date=calculation_date,
                    metadata_json={
                        "day_of_week": current_dow,
                        "day_name": calculation_date.strftime("%A"),
                        "sample_count": len(dow_returns),
                        "std_return": round(dow_returns.std(), 4),
                    },
                )
            )

        # Month effect
        current_month = calculation_date.month
        month_mask = date_series.month == current_month
        month_returns = returns.iloc[month_mask.values] if month_mask.any() else pd.Series()

        if len(month_returns) > 5:
            avg_month_return = month_returns.mean()
            signal = "positive_bias" if avg_month_return > 0 else "negative_bias"

            features.append(
                StatisticalFeature(
                    symbol=symbol,
                    feature_type=StatisticalFeatureType.MONTH_EFFECT.value,
                    value=round(avg_month_return, 4),
                    signal=signal,
                    percentile=None,
                    calculation_date=calculation_date,
                    metadata_json={
                        "month": current_month,
                        "month_name": calculation_date.strftime("%B"),
                        "sample_count": len(month_returns),
                        "std_return": round(month_returns.std(), 4),
                    },
                )
            )

        return features

    async def _compute_cross_sectional_ranks(
        self,
        symbols: list[str],
        prices_dict: dict[str, pd.DataFrame],
        calculation_date: date_type,
    ) -> list[StatisticalFeature]:
        """Calculate cross-sectional ranking features.

        Computes:
        - Sector momentum rank (20D momentum within sector)
        - Relative strength vs sector ETF
        - Beta vs SPY

        Args:
            symbols: List of stock symbols.
            prices_dict: Dictionary mapping symbols to price DataFrames.
            calculation_date: Date for the calculation.

        Returns:
            List of cross-sectional StatisticalFeature objects.
        """
        features: list[StatisticalFeature] = []

        # Calculate 20D momentum for all symbols
        momentum_by_symbol: dict[str, float] = {}
        for symbol, prices_df in prices_dict.items():
            if len(prices_df) > 20:
                closes = prices_df["close"].values
                current = closes[-1]
                prior = closes[-21]
                if prior != 0:
                    momentum_by_symbol[symbol] = ((current - prior) / prior) * 100

        if not momentum_by_symbol:
            return features

        # Get sector information for each symbol
        symbol_sectors: dict[str, str | None] = {}
        for symbol in symbols:
            stock_query = select(Stock).where(Stock.symbol == symbol)
            result = await self.db.execute(stock_query)
            stock = result.scalar_one_or_none()
            symbol_sectors[symbol] = stock.sector if stock else None

        # Group symbols by sector
        sectors_to_symbols: dict[str, list[str]] = {}
        for symbol, sector in symbol_sectors.items():
            if sector:
                if sector not in sectors_to_symbols:
                    sectors_to_symbols[sector] = []
                sectors_to_symbols[sector].append(symbol)

        # Calculate sector momentum ranks
        for sector, sector_symbols in sectors_to_symbols.items():
            sector_momentum = [
                (s, momentum_by_symbol[s])
                for s in sector_symbols
                if s in momentum_by_symbol
            ]

            if len(sector_momentum) > 1:
                # Sort by momentum descending
                sector_momentum.sort(key=lambda x: x[1], reverse=True)
                total = len(sector_momentum)

                for rank, (symbol, momentum) in enumerate(sector_momentum, 1):
                    percentile_rank = ((total - rank + 1) / total) * 100

                    if percentile_rank >= 75:
                        signal = "leader"
                    elif percentile_rank >= 50:
                        signal = "above_average"
                    elif percentile_rank >= 25:
                        signal = "below_average"
                    else:
                        signal = "laggard"

                    features.append(
                        StatisticalFeature(
                            symbol=symbol,
                            feature_type=StatisticalFeatureType.SECTOR_MOMENTUM_RANK.value,
                            value=float(rank),
                            signal=signal,
                            percentile=round(percentile_rank, 2),
                            calculation_date=calculation_date,
                            metadata_json={
                                "sector": sector,
                                "momentum_20d": round(momentum, 4),
                                "rank": rank,
                                "sector_count": total,
                            },
                        )
                    )

        # Calculate relative strength vs sector ETF
        for symbol, sector in symbol_sectors.items():
            if symbol not in prices_dict or not sector:
                continue

            sector_etf = self.SECTOR_TO_ETF.get(sector, "SPY")
            etf_prices = prices_dict.get(sector_etf)

            if etf_prices is None or len(etf_prices) < 21:
                continue

            symbol_prices = prices_dict[symbol]
            if len(symbol_prices) < 21:
                continue

            # Calculate 20D returns
            symbol_closes = symbol_prices["close"].values
            etf_closes = etf_prices["close"].values

            symbol_return = (symbol_closes[-1] / symbol_closes[-21] - 1) * 100
            etf_return = (etf_closes[-1] / etf_closes[-21] - 1) * 100

            relative_strength = symbol_return - etf_return

            if relative_strength > 5:
                signal = "outperforming"
            elif relative_strength < -5:
                signal = "underperforming"
            else:
                signal = "neutral"

            features.append(
                StatisticalFeature(
                    symbol=symbol,
                    feature_type=StatisticalFeatureType.RELATIVE_STRENGTH_SECTOR.value,
                    value=round(relative_strength, 4),
                    signal=signal,
                    percentile=None,
                    calculation_date=calculation_date,
                    metadata_json={
                        "sector": sector,
                        "sector_etf": sector_etf,
                        "symbol_return_20d": round(symbol_return, 4),
                        "etf_return_20d": round(etf_return, 4),
                    },
                )
            )

        # Calculate Beta vs SPY
        spy_prices = prices_dict.get("SPY")
        if spy_prices is not None and len(spy_prices) >= 60:
            spy_returns = pd.Series(spy_prices["close"].values).pct_change().dropna()

            for symbol, prices_df in prices_dict.items():
                if symbol == "SPY" or len(prices_df) < 60:
                    continue

                symbol_returns = pd.Series(prices_df["close"].values).pct_change().dropna()

                # Align returns
                min_len = min(len(spy_returns), len(symbol_returns), 60)
                spy_ret = spy_returns.tail(min_len).values
                sym_ret = symbol_returns.tail(min_len).values

                # Calculate beta using covariance / variance
                covariance = np.cov(sym_ret, spy_ret)[0, 1]
                spy_variance = np.var(spy_ret)

                if spy_variance > 0:
                    beta = covariance / spy_variance

                    if beta > 1.2:
                        signal = "high_beta"
                    elif beta < 0.8:
                        signal = "low_beta"
                    else:
                        signal = "market_beta"

                    features.append(
                        StatisticalFeature(
                            symbol=symbol,
                            feature_type=StatisticalFeatureType.BETA_VS_SPY.value,
                            value=round(beta, 4),
                            signal=signal,
                            percentile=None,
                            calculation_date=calculation_date,
                            metadata_json={
                                "lookback_days": min_len,
                                "correlation": round(
                                    np.corrcoef(sym_ret, spy_ret)[0, 1], 4
                                ),
                            },
                        )
                    )

        return features

    async def _get_price_data(
        self,
        symbol: str,
        lookback_days: int = 300,
    ) -> pd.DataFrame | None:
        """Fetch OHLCV price data from the database.

        Args:
            symbol: Stock symbol.
            lookback_days: Number of historical days to fetch.

        Returns:
            DataFrame with date, open, high, low, close, volume columns,
            or None if no data found.
        """
        # Get stock by symbol
        stock_query = select(Stock).where(Stock.symbol == symbol)
        result = await self.db.execute(stock_query)
        stock = result.scalar_one_or_none()

        if not stock:
            return None

        # Get price history
        price_query = (
            select(PriceHistory)
            .where(PriceHistory.stock_id == stock.id)
            .order_by(PriceHistory.date.asc())
            .limit(lookback_days)
        )
        price_result = await self.db.execute(price_query)
        prices = price_result.scalars().all()

        if not prices:
            return None

        # Convert to DataFrame
        data = {
            "date": [p.date for p in prices],
            "open": [p.open for p in prices],
            "high": [p.high for p in prices],
            "low": [p.low for p in prices],
            "close": [p.close for p in prices],
            "volume": [p.volume for p in prices],
        }

        return pd.DataFrame(data)

    async def _save_features(
        self,
        features: list[StatisticalFeature],
    ) -> None:
        """Bulk save features to the database.

        Deletes existing features for the same symbol + calculation_date
        combinations before inserting, preventing duplicates on re-runs.

        Args:
            features: List of StatisticalFeature objects to save.
        """
        if not features:
            return

        try:
            from sqlalchemy import delete

            # Delete existing features for same symbol+date combos
            symbol_dates = {(f.symbol, f.calculation_date) for f in features}
            for symbol, calc_date in symbol_dates:
                await self.db.execute(
                    delete(StatisticalFeature)
                    .where(StatisticalFeature.symbol == symbol)
                    .where(StatisticalFeature.calculation_date == calc_date)
                )

            # Insert new features
            for feature in features:
                self.db.add(feature)
            await self.db.flush()
            logger.info(f"Saved {len(features)} statistical features to database")
        except Exception as e:
            logger.error(f"Error saving statistical features: {e}")
            raise


# Factory function for convenience
async def create_statistical_calculator(
    db_session: AsyncSession,
) -> StatisticalFeatureCalculator:
    """Create a StatisticalFeatureCalculator instance.

    Args:
        db_session: Async SQLAlchemy session.

    Returns:
        Configured StatisticalFeatureCalculator instance.
    """
    return StatisticalFeatureCalculator(db_session)
