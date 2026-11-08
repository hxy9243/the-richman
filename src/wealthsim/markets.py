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


def _positive_integer(value, name):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


def historical_replay(frame, *, source_name, source_start=None, months=None, start=None,
                      license_note="not supplied; redistribution rights must be checked"):
    """Replay supplied monthly history without inventing missing observations.

    ``source_name`` must identify the dataset/proxy (this function does not verify
    historical authenticity or licensing). ``source_start`` selects history;
    ``start`` optionally rebases it to a scenario calendar, independently of tax
    law. Returns retain ``source_month`` and metadata in ``DataFrame.attrs``.
    Inputs are price returns plus separate cash dividend yields, NOT adjusted
    total returns plus dividends (which would double-count distributions).
    """
    if not isinstance(source_name, str) or not source_name.strip():
        raise ValueError("source_name must identify the supplied historical dataset or proxy")
    if not isinstance(license_note, str) or not license_note.strip():
        raise ValueError("license_note must be a nonempty description")
    data = validate_market(frame)
    first = pd.Period(source_start, freq="M") if source_start is not None else data.month.min()
    if first not in set(data.month):
        raise ValueError("source_start is outside supplied history")
    available = pd.period_range(first, data.month.max(), freq="M")
    n = len(available) if months is None else _positive_integer(months, "months")
    if n > len(available):
        raise ValueError("requested replay exceeds supplied history; no extrapolation is performed")
    chosen = available[:n]
    output_start = pd.Period(start, freq="M") if start is not None else first
    output_months = pd.period_range(output_start, periods=n, freq="M")
    mapping = dict(zip(chosen, output_months))
    data = data[data.month.isin(chosen)].copy()
    data["source_month"] = data["month"].astype(str)
    data["month"] = data["month"].map(mapping)
    data = validate_market(data)
    data.attrs.update({"path_type": "historical_replay", "source_name": source_name,
                       "license_note": license_note, "source_start": str(first),
                       "source_end": str(chosen[-1]), "calendar_rebased": output_start != first,
                       "return_convention": "price return plus separate cash dividend yield"})
    return data


def stochastic_market(assets, *, months, start="2026-01", correlation=None, seed=0):
    """Generate correlated GBM monthly PRICE returns, with explicit assumptions.

    ``assets`` is an ordered mapping, e.g. {"SPY": {"annual_drift": .06,
    "annual_volatility": .18, "annual_dividend_yield": .015}}. annual_drift is
    the continuously compounded expectation parameter mu in dS/S=mu*dt+sigma*dW,
    NOT a forecast CAGR or historical estimate. Each monthly log return is
    (mu - sigma**2/2)/12 + sigma/sqrt(12)*Z. Expected one-year price return is
    exp(mu)-1; distributions are separate deterministic cash yields /12.

    Correlation order follows assets insertion order; identity is the default.
    No fat tails, volatility clustering, mean reversion or dividend uncertainty
    are modeled. Use historical/block-bootstrap/stress paths as complements.
    """
    n = _positive_integer(months, "months")
    if not isinstance(assets, dict) or not assets:
        raise ValueError("assets must be a nonempty symbol-to-assumptions mapping")
    names = list(assets)
    if any(not isinstance(s, str) or not s.strip() for s in names):
        raise ValueError("asset symbols must be nonempty strings")
    mu, sigma, dividend = [], [], []
    for name, spec in assets.items():
        if not isinstance(spec, dict) or set(spec) - {"annual_drift", "annual_volatility", "annual_dividend_yield"}:
            raise ValueError(f"invalid assumptions for {name}")
        if not {"annual_drift", "annual_volatility"}.issubset(spec):
            raise ValueError(f"annual_drift and annual_volatility required for {name}")
        drift = float(spec["annual_drift"])
        vol = float(spec["annual_volatility"])
        div = float(spec.get("annual_dividend_yield", 0))
        if not np.isfinite([drift, vol, div]).all() or vol < 0 or div < 0:
            raise ValueError("drift must be finite; volatility and dividend yield finite and nonnegative")
        mu.append(drift); sigma.append(vol); dividend.append(div)
    k = len(names)
    corr = np.eye(k) if correlation is None else np.asarray(correlation, dtype=float)
    if (corr.shape != (k, k) or not np.isfinite(corr).all()
            or not np.allclose(corr, corr.T, atol=1e-10, rtol=0)
            or not np.allclose(np.diag(corr), 1, atol=1e-10, rtol=0)
            or np.any(np.abs(corr) > 1 + 1e-10)):
        raise ValueError("correlation must be a finite symmetric square matrix with unit diagonal")
    eigenvalues, eigenvectors = np.linalg.eigh(corr)
    if eigenvalues.min() < -1e-10:
        raise ValueError("correlation must be positive semidefinite")
    factor = eigenvectors @ np.diag(np.sqrt(np.maximum(eigenvalues, 0)))
    draws = np.random.default_rng(seed).standard_normal((n, k)) @ factor.T
    mu, sigma, dividend = np.asarray(mu), np.asarray(sigma), np.asarray(dividend)
    log_returns = (mu - sigma ** 2 / 2) / 12 + draws * sigma / np.sqrt(12)
    with np.errstate(over="ignore", invalid="ignore"):
        returns = np.expm1(log_returns)
    # Catch numerically unusable assumptions, including underflow to a -100% return.
    if not np.isfinite(returns).all() or (returns <= -1).any():
        raise ValueError("assumptions generated numerically invalid returns")
    records = [{"month": m, "symbol": symbol, "price_return": float(returns[i, j]),
                "dividend_yield": float(dividend[j] / 12)}
               for i, m in enumerate(pd.period_range(start, periods=n, freq="M"))
               for j, symbol in enumerate(names)]
    result = validate_market(pd.DataFrame(records))
    result.attrs.update({"path_type": "stochastic_gbm", "seed": seed,
                         "asset_order": names, "correlation": corr.tolist(),
                         "assumptions": {name: dict(spec) for name, spec in assets.items()},
                         "warning": "Scenario assumptions, not forecasts; Gaussian log returns and fixed dividends"})
    return result
