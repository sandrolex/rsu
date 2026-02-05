import streamlit as st
from datetime import date, timedelta
from dataclasses import dataclass
from typing import Optional
from dateutil.relativedelta import relativedelta
import yfinance as yf
import requests

from calculations import (
    TaxRegime,
    SOCIAL_SECURITY_RATES,
    MACRON_III_THRESHOLD,
    MACRON_III_SALARIALE_CONTRIBUTION,
    CAPITAL_GAIN_PFU_RATE,
    FRENCH_TAX_BRACKETS_2025,
    get_marginal_tax_rate,
    calculate_tax_on_additional_income,
)

st.set_page_config(page_title="RSU Selling Calculator", page_icon="💰", layout="wide")
st.title("RSU Selling Calculator")


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ScenarioInput:
    """Input parameters for a scenario."""
    name: str
    stock_ticker: str
    vesting_date: date
    sell_date: date
    num_shares: int
    vesting_value_usd: float
    current_value_usd: float
    usd_to_eur: float
    regime: TaxRegime
    use_progressive_tax: bool
    annual_income: Optional[float]
    tax_rate: float


@dataclass
class ScenarioResult:
    """Calculated results for a scenario."""
    # Input reference
    input: ScenarioInput

    # Holding period
    years_held: float
    has_taper_relief: bool
    taper_relief_rate: float
    relief_description: str

    # Values in EUR
    vesting_value_eur: float
    current_value_eur: float
    gross_proceed: float

    # Gains
    acquisition_gain: float
    acquisition_gain_after_relief: float
    capital_gain: float

    # Taxes
    effective_social_rate: float
    acquisition_social_security: float
    acquisition_income_tax: float
    capital_gain_tax: float
    salariale_contribution: float
    total_taxes: float

    # Final
    net_in_pocket: float
    effective_tax_rate: float


# =============================================================================
# Cached Data Fetching Functions
# =============================================================================

@st.cache_data(ttl=3600)
def fetch_usd_eur_rate():
    """Fetch current USD to EUR conversion rate."""
    try:
        response = requests.get(
            "https://api.exchangerate-api.com/v4/latest/USD",
            timeout=5
        )
        if response.status_code == 200:
            data = response.json()
            return data["rates"]["EUR"]
    except Exception:
        pass
    return None


@st.cache_data(ttl=300)  # 5 min cache
def fetch_stock_price(ticker: str, target_date: date):
    """Fetch stock price for a given ticker and date."""
    try:
        stock = yf.Ticker(ticker)
        # Fetch more days to ensure we get data even if target_date has none
        start_date = target_date - timedelta(days=10)
        end_date = date.today() + timedelta(days=1)
        hist = stock.history(start=start_date, end=end_date)

        if hist.empty:
            return None

        hist.index = hist.index.date

        # First try exact date
        if target_date in hist.index:
            return float(hist.loc[target_date]["Close"])

        # Fallback to closest date before or on target
        available_dates = [d for d in hist.index if d <= target_date]
        if available_dates:
            closest_date = max(available_dates)
            return float(hist.loc[closest_date]["Close"])

        # If target is in the future, get the most recent available
        if hist.index.size > 0:
            return float(hist.iloc[-1]["Close"])

    except Exception:
        pass
    return None


def fetch_stock_price_no_cache(ticker: str, target_date: date):
    """Fetch stock price without caching (for fresh data)."""
    try:
        stock = yf.Ticker(ticker)
        start_date = target_date - timedelta(days=10)
        end_date = date.today() + timedelta(days=1)
        hist = stock.history(start=start_date, end=end_date)

        if hist.empty:
            return None

        hist.index = hist.index.date

        if target_date in hist.index:
            return float(hist.loc[target_date]["Close"])

        available_dates = [d for d in hist.index if d <= target_date]
        if available_dates:
            closest_date = max(available_dates)
            return float(hist.loc[closest_date]["Close"])

        if hist.index.size > 0:
            return float(hist.iloc[-1]["Close"])

    except Exception:
        pass
    return None


@st.cache_data(ttl=3600)
def get_stock_name(ticker: str) -> str:
    """Get the company name for a ticker symbol."""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        return info.get("shortName", ticker)
    except Exception:
        return ticker


# =============================================================================
# Calculation Functions
# =============================================================================

def calculate_scenario(input_data: ScenarioInput) -> ScenarioResult:
    """Calculate all results for a scenario."""
    # Holding period
    holding_delta = relativedelta(input_data.sell_date, input_data.vesting_date)
    years_held = holding_delta.years + holding_delta.months / 12 + holding_delta.days / 365

    # Convert to EUR
    current_value_eur = input_data.current_value_usd * input_data.usd_to_eur
    vesting_value_eur = input_data.vesting_value_usd * input_data.usd_to_eur

    # Gains
    gross_proceed = input_data.num_shares * current_value_eur
    acquisition_gain = input_data.num_shares * vesting_value_eur
    capital_gain = gross_proceed - acquisition_gain

    # Taper relief
    if input_data.regime == TaxRegime.MACRON_I:
        if years_held >= 8:
            has_taper_relief, taper_relief_rate = True, 0.65
            relief_description = "65% (held 8+ years)"
        elif years_held >= 2:
            has_taper_relief, taper_relief_rate = True, 0.50
            relief_description = "50% (held 2-8 years)"
        else:
            has_taper_relief, taper_relief_rate = False, 0.0
            relief_description = "None (need 2+ years)"
    elif input_data.regime == TaxRegime.MACRON_III:
        if acquisition_gain <= MACRON_III_THRESHOLD:
            has_taper_relief, taper_relief_rate = True, 0.50
            relief_description = f"50% (under €{MACRON_III_THRESHOLD:,})"
        else:
            has_taper_relief, taper_relief_rate = False, 0.0
            relief_description = f"None (over €{MACRON_III_THRESHOLD:,})"
    else:
        has_taper_relief, taper_relief_rate = False, 0.0
        relief_description = "None (unrestricted)"

    acquisition_gain_after_relief = acquisition_gain * (1 - taper_relief_rate)

    # Social security rate
    if input_data.regime == TaxRegime.MACRON_III and acquisition_gain > MACRON_III_THRESHOLD:
        effective_social_rate = 0.097
    else:
        effective_social_rate = SOCIAL_SECURITY_RATES.get(input_data.regime, 0.172)

    # Taxes
    acquisition_social_security = acquisition_gain_after_relief * effective_social_rate

    if input_data.use_progressive_tax and input_data.annual_income is not None:
        acquisition_income_tax = calculate_tax_on_additional_income(
            input_data.annual_income, acquisition_gain_after_relief
        )
    else:
        acquisition_income_tax = acquisition_gain_after_relief * input_data.tax_rate

    capital_gain_tax = capital_gain * CAPITAL_GAIN_PFU_RATE if capital_gain > 0 else 0.0

    if input_data.regime == TaxRegime.MACRON_III and acquisition_gain > MACRON_III_THRESHOLD:
        salariale_contribution = acquisition_gain * MACRON_III_SALARIALE_CONTRIBUTION
    else:
        salariale_contribution = 0.0

    total_taxes = acquisition_social_security + acquisition_income_tax + capital_gain_tax + salariale_contribution
    net_in_pocket = gross_proceed - total_taxes
    effective_tax_rate = (total_taxes / gross_proceed * 100) if gross_proceed > 0 else 0

    return ScenarioResult(
        input=input_data,
        years_held=years_held,
        has_taper_relief=has_taper_relief,
        taper_relief_rate=taper_relief_rate,
        relief_description=relief_description,
        vesting_value_eur=vesting_value_eur,
        current_value_eur=current_value_eur,
        gross_proceed=gross_proceed,
        acquisition_gain=acquisition_gain,
        acquisition_gain_after_relief=acquisition_gain_after_relief,
        capital_gain=capital_gain,
        effective_social_rate=effective_social_rate,
        acquisition_social_security=acquisition_social_security,
        acquisition_income_tax=acquisition_income_tax,
        capital_gain_tax=capital_gain_tax,
        salariale_contribution=salariale_contribution,
        total_taxes=total_taxes,
        net_in_pocket=net_in_pocket,
        effective_tax_rate=effective_tax_rate,
    )


# =============================================================================
# Display Functions
# =============================================================================

REGIME_OPTIONS = {
    "Macron III (Jan 2018 - present)": TaxRegime.MACRON_III,
    "Macron I (Aug 2015 - Dec 2016)": TaxRegime.MACRON_I,
    "Unrestricted (Non-qualified)": TaxRegime.UNRESTRICTED,
}

REGIME_NAMES = {v: k for k, v in REGIME_OPTIONS.items()}


def display_results(result: ScenarioResult, show_details: bool = True):
    """Display calculation results for a scenario."""
    inp = result.input
    regime_name = REGIME_NAMES.get(inp.regime, str(inp.regime))

    # Effective income tax rate
    if inp.use_progressive_tax and inp.annual_income is not None:
        eff_rate = (result.acquisition_income_tax / result.acquisition_gain_after_relief * 100) if result.acquisition_gain_after_relief > 0 else 0
        tax_method = f"Progressive ({eff_rate:.1f}%)"
    else:
        tax_method = f"{inp.tax_rate*100:.0f}%"

    # Header info
    st.info(f"**Regime:** {regime_name} | **Taper Relief:** {result.relief_description} | **Income Tax:** {tax_method}")

    # Key metrics
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Years Held", f"{result.years_held:.2f}")
    with col2:
        relief_display = f"{result.taper_relief_rate*100:.0f}% ✅" if result.has_taper_relief else "No ❌"
        st.metric("Taper Relief", relief_display)

    if show_details:
        st.divider()

        # Value breakdown
        st.subheader("💵 Values")
        col_v1, col_v2, col_v3 = st.columns(3)
        with col_v1:
            st.metric("Current Value (€)", f"€{result.current_value_eur:,.2f}")
        with col_v2:
            st.metric("Vesting Value (€)", f"€{result.vesting_value_eur:,.2f}")
        with col_v3:
            st.metric("Gross Proceed", f"€{result.gross_proceed:,.2f}")

        # Gains
        st.subheader("📊 Gains")
        col_g1, col_g2, col_g3 = st.columns(3)
        with col_g1:
            st.metric("Acquisition Gain", f"€{result.acquisition_gain:,.2f}")
        with col_g2:
            delta = f"{-result.acquisition_gain * result.taper_relief_rate:,.2f}" if result.has_taper_relief else None
            st.metric("After Relief", f"€{result.acquisition_gain_after_relief:,.2f}", delta=delta, delta_color="inverse")
        with col_g3:
            st.metric("Capital Gain", f"€{result.capital_gain:,.2f}")

        # Taxes
        st.subheader("🏛️ Taxes")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.metric(f"Social Security ({result.effective_social_rate*100:.1f}%)", f"€{result.acquisition_social_security:,.2f}")
        with col_t2:
            st.metric(f"Income Tax ({tax_method})", f"€{result.acquisition_income_tax:,.2f}")

        col_t3, col_t4 = st.columns(2)
        with col_t3:
            st.metric(f"Capital Gain PFU (30%)", f"€{result.capital_gain_tax:,.2f}")
        with col_t4:
            if result.salariale_contribution > 0:
                st.metric("Salariale (10%)", f"€{result.salariale_contribution:,.2f}")

    st.divider()

    # Final results
    st.subheader("💰 Final Results")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        st.metric("Total Taxes", f"€{result.total_taxes:,.2f}", delta=f"-{result.effective_tax_rate:.1f}%", delta_color="inverse")
    with col_f2:
        st.metric("Net in Pocket", f"€{result.net_in_pocket:,.2f}", delta=f"{100-result.effective_tax_rate:.1f}% of gross")
    with col_f3:
        st.metric("Effective Tax Rate", f"{result.effective_tax_rate:.1f}%")


def display_comparison_table(result_a: ScenarioResult, result_b: ScenarioResult):
    """Display a comparison table between two scenarios."""
    def diff_str(val_a, val_b, is_currency=True, reverse=False):
        diff = val_b - val_a
        if reverse:
            diff = -diff
        sign = "+" if diff > 0 else ""
        if is_currency:
            return f"{sign}€{diff:,.2f}"
        return f"{sign}{diff:.2f}"

    def better_indicator(val_a, val_b, higher_is_better=True):
        if higher_is_better:
            if val_b > val_a:
                return "✅ B"
            elif val_a > val_b:
                return "✅ A"
        else:
            if val_b < val_a:
                return "✅ B"
            elif val_a < val_b:
                return "✅ A"
        return "="

    st.subheader("📊 Comparison Summary")

    # Key comparison metrics
    comparison_data = f"""
| Metric | {result_a.input.name} | {result_b.input.name} | Difference | Better |
|--------|---------|---------|------------|--------|
| **Shares** | {result_a.input.num_shares:,} | {result_b.input.num_shares:,} | {result_b.input.num_shares - result_a.input.num_shares:+,} | - |
| **Years Held** | {result_a.years_held:.2f} | {result_b.years_held:.2f} | {diff_str(result_a.years_held, result_b.years_held, False)} | - |
| **Taper Relief** | {result_a.relief_description} | {result_b.relief_description} | - | - |
| **Gross Proceed** | €{result_a.gross_proceed:,.2f} | €{result_b.gross_proceed:,.2f} | {diff_str(result_a.gross_proceed, result_b.gross_proceed)} | {better_indicator(result_a.gross_proceed, result_b.gross_proceed)} |
| **Acquisition Gain** | €{result_a.acquisition_gain:,.2f} | €{result_b.acquisition_gain:,.2f} | {diff_str(result_a.acquisition_gain, result_b.acquisition_gain)} | - |
| **Capital Gain** | €{result_a.capital_gain:,.2f} | €{result_b.capital_gain:,.2f} | {diff_str(result_a.capital_gain, result_b.capital_gain)} | - |
| **Total Taxes** | €{result_a.total_taxes:,.2f} | €{result_b.total_taxes:,.2f} | {diff_str(result_a.total_taxes, result_b.total_taxes)} | {better_indicator(result_a.total_taxes, result_b.total_taxes, False)} |
| **Net in Pocket** | €{result_a.net_in_pocket:,.2f} | €{result_b.net_in_pocket:,.2f} | {diff_str(result_a.net_in_pocket, result_b.net_in_pocket)} | {better_indicator(result_a.net_in_pocket, result_b.net_in_pocket)} |
| **Effective Tax Rate** | {result_a.effective_tax_rate:.1f}% | {result_b.effective_tax_rate:.1f}% | {result_b.effective_tax_rate - result_a.effective_tax_rate:+.1f}% | {better_indicator(result_a.effective_tax_rate, result_b.effective_tax_rate, False)} |
"""
    st.markdown(comparison_data)

    # Highlight the winner
    diff_net = result_b.net_in_pocket - result_a.net_in_pocket
    if abs(diff_net) > 0.01:
        winner = result_b.input.name if diff_net > 0 else result_a.input.name
        st.success(f"**{winner}** yields **€{abs(diff_net):,.2f}** more net in pocket!")


# =============================================================================
# Sidebar Configuration (shared)
# =============================================================================

st.sidebar.header("Tax Configuration")

# Regime selection
regime_name = st.sidebar.selectbox(
    "Tax Regime",
    options=list(REGIME_OPTIONS.keys()),
    index=0,
    help="""
**Macron I**: 50% abatement if held 2-8 years, 65% if held 8+ years.

**Macron III**: Automatic 50% abatement under €300k.

**Unrestricted**: No abatement.
"""
)
selected_regime = REGIME_OPTIONS[regime_name]

# Regime info
st.sidebar.markdown("---")
if selected_regime == TaxRegime.MACRON_I:
    st.sidebar.info("**Macron I:** 50%/65% abatement, 17.2% social")
elif selected_regime == TaxRegime.MACRON_III:
    st.sidebar.info(f"**Macron III:** 50% abatement under €{MACRON_III_THRESHOLD:,}")
else:
    st.sidebar.warning("**Unrestricted:** No abatement, 9.7% social")

st.sidebar.markdown("---")
st.sidebar.subheader("Income Tax Rate")

tax_input_method = st.sidebar.radio(
    "How to determine your tax rate?",
    options=["Manual (slider)", "Automatic (from annual income)"],
    index=0,
)

use_progressive_tax = tax_input_method == "Automatic (from annual income)"
annual_income_value = None

if tax_input_method == "Manual (slider)":
    acquisition_tax_rate = st.sidebar.slider(
        "Marginal Tax Rate (TMI)",
        min_value=0.0,
        max_value=0.45,
        value=0.30,
        step=0.01,
        format="%.0f%%",
    )
else:
    annual_income_value = st.sidebar.number_input(
        "Annual Taxable Income (€)",
        min_value=0,
        value=100_000,
        step=1_000,
    )
    acquisition_tax_rate = get_marginal_tax_rate(annual_income_value)
    st.sidebar.success(f"**Your TMI: {acquisition_tax_rate*100:.0f}%**")
    st.sidebar.caption("💡 Tax calculated progressively across brackets.")

st.sidebar.markdown("---")
st.sidebar.metric("Capital Gain Tax (PFU)", f"{CAPITAL_GAIN_PFU_RATE * 100:.0f}%")
social_security_rate = SOCIAL_SECURITY_RATES.get(selected_regime, 0.172)
st.sidebar.metric("Social Security Rate", f"{social_security_rate * 100:.1f}%")


# =============================================================================
# Main Content with Tabs
# =============================================================================

tab_single, tab_compare = st.tabs(["📊 Single Calculation", "⚖️ Compare Scenarios"])

# -----------------------------------------------------------------------------
# Tab 1: Single Calculation (original UI)
# -----------------------------------------------------------------------------

with tab_single:
    st.header("RSU Details")

    col1, col2 = st.columns(2)

    with col1:
        stock_ticker = st.text_input(
            "Stock Ticker",
            value="META",
            help="Enter the stock ticker symbol",
            key="single_ticker"
        ).upper().strip()

        vesting_date = st.date_input(
            "Vesting Date",
            value=date(2024, 2, 15),
            key="single_vesting"
        )

        sell_date = st.date_input(
            "Sell Date",
            value=date(date.today().year, date.today().month, 15),
            key="single_sell"
        )

        num_shares = st.number_input(
            "Number of Shares to Sell",
            min_value=1,
            value=10,
            step=1,
            key="single_shares"
        )

    with col2:
        st.write("**Stock & Currency Data**")

        if stock_ticker:
            stock_name = get_stock_name(stock_ticker)
            if stock_name != stock_ticker:
                st.caption(f"📈 {stock_name}")

        # Fetch buttons with callbacks that update widget keys directly
        def fetch_stock_prices():
            ticker = st.session_state.get("single_ticker", "META").upper().strip()
            v_date = st.session_state.get("single_vesting")
            s_date = st.session_state.get("single_sell")

            vp = fetch_stock_price_no_cache(ticker, v_date)
            cp = fetch_stock_price_no_cache(ticker, s_date)

            # Update the widget keys directly
            if vp is not None:
                st.session_state.single_vesting_value = float(vp)
            if cp is not None:
                st.session_state.single_current_value = float(cp)

            # Store status for display
            st.session_state.fetch_status = f"Vesting: {'$'+f'{vp:.2f}' if vp else 'failed'}, Current: {'$'+f'{cp:.2f}' if cp else 'failed'}"

        def fetch_usd_rate():
            rate = fetch_usd_eur_rate()
            if rate is not None:
                st.session_state.single_usd_eur_input = float(rate)
                st.session_state.rate_status = f"Rate: {rate:.4f}"
            else:
                st.session_state.rate_status = "Failed to fetch rate"

        col_fetch1, col_fetch2 = st.columns(2)
        with col_fetch1:
            st.button(f"🔄 Fetch {stock_ticker}", key="single_fetch_stock",
                     on_click=fetch_stock_prices, use_container_width=True)
        with col_fetch2:
            st.button("🔄 Fetch USD/EUR", key="single_fetch_currency",
                     on_click=fetch_usd_rate, use_container_width=True)

        # Show fetch status
        if "fetch_status" in st.session_state:
            st.caption(st.session_state.fetch_status)
        if "rate_status" in st.session_state:
            st.caption(st.session_state.rate_status)

    st.subheader("📈 Values (editable)")
    col_val1, col_val2, col_val3 = st.columns(3)

    with col_val1:
        vesting_value_usd = st.number_input(
            "Vesting Value per Share ($)",
            min_value=0.0,
            value=100.0,
            step=1.0,
            key="single_vesting_value"
        )

    with col_val2:
        actual_value_usd = st.number_input(
            "Current Share Value ($)",
            min_value=0.0,
            value=150.0,
            step=1.0,
            key="single_current_value"
        )

    with col_val3:
        usd_to_eur = st.number_input(
            "USD to EUR Rate",
            min_value=0.0,
            value=0.92,
            step=0.01,
            key="single_usd_eur_input"
        )

    # Calculate and display
    st.divider()
    st.header("📈 Results")

    single_input = ScenarioInput(
        name="Single",
        stock_ticker=stock_ticker,
        vesting_date=vesting_date,
        sell_date=sell_date,
        num_shares=num_shares,
        vesting_value_usd=vesting_value_usd,
        current_value_usd=actual_value_usd,
        usd_to_eur=usd_to_eur,
        regime=selected_regime,
        use_progressive_tax=use_progressive_tax,
        annual_income=annual_income_value,
        tax_rate=acquisition_tax_rate,
    )

    single_result = calculate_scenario(single_input)
    display_results(single_result, show_details=True)

    # Reference expanders
    with st.expander("📐 Formulas Reference"):
        st.markdown("""
### Value Conversions
- **Current Share Value (€)** = Current Share Value ($) × USD/EUR Rate
- **Vesting Value (€)** = Vesting Value ($) × USD/EUR Rate

### Gains
- **Gross Proceed** = Number of Shares × Current Share Value (€)
- **Acquisition Gain** = Number of Shares × Vesting Value (€)
- **Acquisition Gain (after relief)** = Acquisition Gain × (1 - Taper Relief Rate)
- **Capital Gain** = Gross Proceed - Acquisition Gain

### Taper Relief by Regime

| Regime | Condition | Relief |
|--------|-----------|--------|
| **Macron I** | Held < 2 years | 0% |
| **Macron I** | Held 2-8 years | 50% |
| **Macron I** | Held 8+ years | 65% |
| **Macron III** | Gain ≤ €300k | 50% (automatic) |
| **Macron III** | Gain > €300k | 0% + 10% salariale |
| **Unrestricted** | Always | 0% |

### Taxes

**On Acquisition Gain (after taper relief):**
- **Social Security** = Acquisition Gain (after relief) × Social Security Rate
- **Income Tax** = Acquisition Gain (after relief) × Tax Rate

**On Capital Gain:**
- **PFU (Flat Tax)** = Capital Gain × 30%

### Final Results
- **Net in Pocket** = Gross Proceed - Total Taxes
- **Effective Tax Rate** = (Total Taxes / Gross Proceed) × 100
""")

    with st.expander("📊 Regime Comparison"):
        st.markdown("""
### Which Regime Applies to You?

| Grant Period | Regime |
|--------------|--------|
| Before Aug 7, 2015 | Pre-Macron |
| Aug 7, 2015 - Dec 29, 2016 | **Macron I** |
| Dec 30, 2016 - Dec 31, 2017 | Macron II |
| Jan 1, 2018 - present | **Macron III** |

### Key Differences

| Feature | Macron I | Macron III | Unrestricted |
|---------|----------|------------|--------------|
| Abatement | 50-65% (holding) | 50% auto (< €300k) | None |
| Social charges | 17.2% | 17.2% / 9.7% | 9.7% |
| €300k threshold | No | Yes | No |
| 10% salariale | No | Yes (> €300k) | No |
""")


# -----------------------------------------------------------------------------
# Tab 2: Compare Scenarios
# -----------------------------------------------------------------------------

with tab_compare:
    st.header("Compare Two Scenarios")
    st.caption("Enter details for two scenarios to compare side by side. Tax settings from the sidebar apply to both.")

    # Initialize session state for comparison tab (use widget keys directly)
    if "a_vesting_value" not in st.session_state:
        st.session_state.a_vesting_value = 100.0
    if "a_current_value" not in st.session_state:
        st.session_state.a_current_value = 150.0
    if "b_vesting_value" not in st.session_state:
        st.session_state.b_vesting_value = 80.0
    if "b_current_value" not in st.session_state:
        st.session_state.b_current_value = 150.0
    if "compare_usd_eur" not in st.session_state:
        st.session_state.compare_usd_eur = 0.92

    # Shared settings
    st.subheader("🔧 Shared Settings")
    col_shared1, col_shared2, col_shared3 = st.columns(3)

    with col_shared1:
        compare_ticker = st.text_input(
            "Stock Ticker",
            value="META",
            key="compare_ticker"
        ).upper().strip()

    with col_shared3:
        compare_usd_eur = st.number_input(
            "USD to EUR Rate",
            min_value=0.0,
            value=0.92,
            step=0.01,
            key="compare_usd_eur"
        )

    st.divider()

    # Two scenarios side by side - dates first
    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("📊 Scenario A")

        a_vesting_date = st.date_input(
            "Vesting Date",
            value=date(2024, 2, 15),
            key="a_vesting"
        )

        a_sell_date = st.date_input(
            "Sell Date",
            value=date(date.today().year, date.today().month, 15),
            key="a_sell"
        )

        a_num_shares = st.number_input(
            "Number of Shares",
            min_value=1,
            value=10,
            step=1,
            key="a_shares"
        )

    with col_b:
        st.subheader("📊 Scenario B")

        b_vesting_date = st.date_input(
            "Vesting Date",
            value=date(2024, 2, 15),
            key="b_vesting"
        )

        b_sell_date = st.date_input(
            "Sell Date",
            value=date(date.today().year, date.today().month, 15),
            key="b_sell"
        )

        b_num_shares = st.number_input(
            "Number of Shares",
            min_value=1,
            value=10,
            step=1,
            key="b_shares"
        )

    # Fetch buttons with callbacks
    def fetch_compare_prices():
        ticker = st.session_state.get("compare_ticker", "META").upper().strip()
        a_v_date = st.session_state.get("a_vesting")
        a_s_date = st.session_state.get("a_sell")
        b_v_date = st.session_state.get("b_vesting")
        b_s_date = st.session_state.get("b_sell")

        a_vp = fetch_stock_price_no_cache(ticker, a_v_date)
        a_cp = fetch_stock_price_no_cache(ticker, a_s_date)
        b_vp = fetch_stock_price_no_cache(ticker, b_v_date)
        b_cp = fetch_stock_price_no_cache(ticker, b_s_date)

        if a_vp is not None:
            st.session_state.a_vesting_value = float(a_vp)
        if a_cp is not None:
            st.session_state.a_current_value = float(a_cp)
        if b_vp is not None:
            st.session_state.b_vesting_value = float(b_vp)
        if b_cp is not None:
            st.session_state.b_current_value = float(b_cp)

        a_vp_str = f"${a_vp:.2f}" if a_vp else "N/A"
        a_cp_str = f"${a_cp:.2f}" if a_cp else "N/A"
        b_vp_str = f"${b_vp:.2f}" if b_vp else "N/A"
        b_cp_str = f"${b_cp:.2f}" if b_cp else "N/A"
        st.session_state.compare_fetch_status = f"A: {a_vp_str}/{a_cp_str} | B: {b_vp_str}/{b_cp_str}"

    def fetch_compare_rate():
        rate = fetch_usd_eur_rate()
        if rate is not None:
            st.session_state.compare_usd_eur = float(rate)
            st.session_state.compare_rate_status = f"Rate: {rate:.4f}"
        else:
            st.session_state.compare_rate_status = "Failed"

    st.divider()
    col_fetch1, col_fetch2 = st.columns(2)
    with col_fetch1:
        st.button(f"🔄 Fetch {compare_ticker} Prices", key="compare_fetch",
                 on_click=fetch_compare_prices, use_container_width=True)
    with col_fetch2:
        st.button("🔄 Fetch USD/EUR Rate", key="compare_fetch_currency",
                 on_click=fetch_compare_rate, use_container_width=True)

    # Show fetch status
    if "compare_fetch_status" in st.session_state:
        st.caption(st.session_state.compare_fetch_status)
    if "compare_rate_status" in st.session_state:
        st.caption(st.session_state.compare_rate_status)

    # Value inputs
    st.subheader("📈 Stock Values")
    col_val_a, col_val_b = st.columns(2)

    with col_val_a:
        st.markdown("**Scenario A**")
        a_vesting_value = st.number_input(
            "Vesting Value ($)",
            min_value=0.0,
            value=100.0,
            step=1.0,
            key="a_vesting_value"
        )

        a_current_value = st.number_input(
            "Current Value ($)",
            min_value=0.0,
            value=150.0,
            step=1.0,
            key="a_current_value"
        )

    with col_val_b:
        st.markdown("**Scenario B**")
        b_vesting_value = st.number_input(
            "Vesting Value ($)",
            min_value=0.0,
            value=80.0,
            step=1.0,
            key="b_vesting_value"
        )

        b_current_value = st.number_input(
            "Current Value ($)",
            min_value=0.0,
            value=150.0,
            step=1.0,
            key="b_current_value"
        )

    # Calculate both scenarios
    st.divider()

    input_a = ScenarioInput(
        name="Scenario A",
        stock_ticker=compare_ticker,
        vesting_date=a_vesting_date,
        sell_date=a_sell_date,
        num_shares=a_num_shares,
        vesting_value_usd=a_vesting_value,
        current_value_usd=a_current_value,
        usd_to_eur=compare_usd_eur,
        regime=selected_regime,
        use_progressive_tax=use_progressive_tax,
        annual_income=annual_income_value,
        tax_rate=acquisition_tax_rate,
    )

    input_b = ScenarioInput(
        name="Scenario B",
        stock_ticker=compare_ticker,
        vesting_date=b_vesting_date,
        sell_date=b_sell_date,
        num_shares=b_num_shares,
        vesting_value_usd=b_vesting_value,
        current_value_usd=b_current_value,
        usd_to_eur=compare_usd_eur,
        regime=selected_regime,
        use_progressive_tax=use_progressive_tax,
        annual_income=annual_income_value,
        tax_rate=acquisition_tax_rate,
    )

    result_a = calculate_scenario(input_a)
    result_b = calculate_scenario(input_b)

    # Comparison table first
    display_comparison_table(result_a, result_b)

    st.divider()

    # Detailed results side by side
    st.subheader("📋 Detailed Results")

    detail_col_a, detail_col_b = st.columns(2)

    with detail_col_a:
        st.markdown("### Scenario A")
        display_results(result_a, show_details=True)

    with detail_col_b:
        st.markdown("### Scenario B")
        display_results(result_b, show_details=True)
