"""Monthly price-return paths, separate cash dividends, no downloaded datasets."""
import numpy as np
import pandas as pd


def validate_market(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"month", "symbol", "price_return", "dividend_yield"}
    if not required.issubset(frame.columns):
        raise ValueError(f"market requires {sorted(required)}")
    frame = frame.copy()
    if isinstance(frame.month.dtype, pd.PeriodDtype):
        frame["month"] = frame.month.dt.asfreq("M")
    else:
        frame["month"] = pd.to_datetime(frame.month, errors="raise").dt.to_period("M")
    if frame.month.isna().any():
        raise ValueError("missing market month")
    for column in ("price_return", "dividend_yield"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    if frame.empty or frame.duplicated(["month", "symbol"]).any():
        raise ValueError("empty or duplicate market rows")
    if frame.symbol.isna().any() or (frame.symbol.astype(str).str.len() == 0).any():
        raise ValueError("invalid symbol")
    values = frame[["price_return", "dividend_yield"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values[:, 0] <= -1).any() or (values[:, 1] < 0).any():
        raise ValueError("invalid returns or dividends")
    months = pd.period_range(frame.month.min(), frame.month.max(), freq="M")
    if len(frame) != len(months) * frame.symbol.nunique():
        raise ValueError("market must have every symbol in every consecutive month")
    return frame.sort_values(["month", "symbol"]).reset_index(drop=True)


def bootstrap_blocks(frame, years, seed=0, block_months=12, start="2026-01"):
    """Sample shared monthly blocks to preserve cross-asset correlation."""
    frame = validate_market(frame)
    if years <= 0 or int(years) != years or block_months <= 0:
        raise ValueError("positive integer years and block_months required")
    months = frame.month.unique()
    if block_months > len(months):
        raise ValueError("block exceeds available history")
    rng = np.random.default_rng(seed)
    selected = []
    while len(selected) < years * 12:
        i = int(rng.integers(0, len(months) - block_months + 1))
        selected.extend(months[i:i + block_months])
    result = []
    for out_month, source in zip(pd.period_range(start, periods=years * 12, freq="M"), selected):
        chunk = frame[frame.month == source].copy()
        chunk["source_month"] = str(source)
        chunk["month"] = str(out_month)
        result.append(chunk)
    return pd.concat(result, ignore_index=True)
