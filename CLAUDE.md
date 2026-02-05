# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RSU Selling Calculator - A Streamlit web app for estimating French taxes when selling Restricted Stock Units (RSUs). Supports three French tax regimes: Macron I (Aug 2015 - Dec 2016), Macron III (Jan 2018+), and Unrestricted (non-qualified plans).

## Commands

```bash
# Run the application
streamlit run rsu_calculator.py

# Run all tests (112 tests)
pytest test_calculations.py -v

# Run tests with coverage
pytest test_calculations.py --cov=calculations --cov-report=term-missing
```

## Architecture

**Two-file separation of concerns:**
- `calculations.py` - Pure calculation logic with no UI dependencies. All tax formulas, regime rules, and financial calculations live here. Fully testable.
- `rsu_calculator.py` - Streamlit UI layer. Imports from calculations.py. Handles data fetching (stock prices via yfinance, exchange rates via ExchangeRate-API), caching, and display.

**Data flow:**
```
UI Input → ScenarioInput dataclass → calculate_scenario() → RSUResult → display_results()
```

**Key patterns:**
- Enums for type-safe regime selection (`TaxRegime`)
- Dataclasses for structured input/output (`RSUInput`, `RSUResult`, `ScenarioInput`, `ScenarioResult`)
- Streamlit caching: `@st.cache_data(ttl=3600)` for exchange rates, `@st.cache_data(ttl=300)` for stock prices
- Session state with `on_click` callbacks for fetch button reliability

## Tax Calculation Pipeline

1. Calculate holding period (years between vesting and sell date)
2. Convert USD values to EUR
3. Calculate acquisition gain (shares × vesting value)
4. Apply taper relief based on regime (Macron I: time-based, Macron III: €300k threshold, Unrestricted: none)
5. Calculate capital gain (gross proceeds - acquisition gain)
6. Calculate taxes: social security, income tax, capital gains PFU (30%), salariale contribution (Macron III >€300k only)
7. Sum total taxes and compute net proceeds

## Key Constants (in calculations.py)

- `MACRON_III_THRESHOLD = 300_000` (euros)
- `CAPITAL_GAIN_PFU_RATE = 0.30` (30% flat rate)
- `SOCIAL_SECURITY_RATES = {"patrimony": 0.172, "activity": 0.097}`
- `FRENCH_TAX_BRACKETS_2025` - Progressive brackets: 0%, 11%, 30%, 41%, 45%
