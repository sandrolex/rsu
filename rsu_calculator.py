import streamlit as st
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import yfinance as yf
import requests

from calculations import (
    TaxRegime,
    SOCIAL_SECURITY_RATES,
    MACRON_III_THRESHOLD,
    MACRON_III_SALARIALE_CONTRIBUTION,
)

st.set_page_config(page_title="RSU Selling Calculator", page_icon="💰")
st.title("RSU Selling Calculator")


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


@st.cache_data(ttl=3600)
def fetch_stock_price(ticker: str, target_date: date):
    """Fetch stock price for a given ticker and date."""
    try:
        stock = yf.Ticker(ticker)
        # For historical data, we need to fetch a range
        start_date = target_date - timedelta(days=5)
        end_date = target_date + timedelta(days=1)
        hist = stock.history(start=start_date, end=end_date)

        if hist.empty:
            return None

        # Find the closest date (markets may be closed on weekends/holidays)
        hist.index = hist.index.date
        if target_date in hist.index:
            return float(hist.loc[target_date]["Close"])
        else:
            # Get the most recent date before or on target_date
            available_dates = [d for d in hist.index if d <= target_date]
            if available_dates:
                closest_date = max(available_dates)
                return float(hist.loc[closest_date]["Close"])
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


# Regime display names - order matters for default selection
REGIME_OPTIONS = {
    "Macron III (Jan 2018 - present)": TaxRegime.MACRON_III,
    "Macron I (Aug 2015 - Dec 2016)": TaxRegime.MACRON_I,
    "Unrestricted (Non-qualified)": TaxRegime.UNRESTRICTED,
}

# Sidebar for tax rate configuration
st.sidebar.header("Tax Configuration")

# Regime selection (default: Macron III, index=0)
regime_name = st.sidebar.selectbox(
    "Tax Regime",
    options=list(REGIME_OPTIONS.keys()),
    index=0,  # Macron III is now first
    help="""
**Macron I** (Aug 2015 - Dec 2016): 50% abatement if held 2-8 years, 65% if held 8+ years. 17.2% social charges.

**Macron III** (Jan 2018 - present): Automatic 50% abatement for gains under €300k. Over €300k: no abatement + 10% salariale contribution.

**Unrestricted**: Non-qualified plans. No abatement, fully taxed as salary with 9.7% social charges.
"""
)
selected_regime = REGIME_OPTIONS[regime_name]

# Show regime-specific info
st.sidebar.markdown("---")
if selected_regime == TaxRegime.MACRON_I:
    st.sidebar.info("""
    **Macron I Rules:**
    - 50% abatement: 2-8 years
    - 65% abatement: 8+ years
    - Social charges: 17.2%
    """)
elif selected_regime == TaxRegime.MACRON_III:
    st.sidebar.info(f"""
    **Macron III Rules:**
    - 50% automatic abatement (under €{MACRON_III_THRESHOLD:,})
    - Over €{MACRON_III_THRESHOLD:,}: salary treatment + 10% contribution
    - Social charges: 17.2% (under threshold)
    """)
else:
    st.sidebar.warning("""
    **Unrestricted Rules:**
    - No abatement
    - Fully taxed as salary
    - Social charges: 9.7%
    """)

st.sidebar.markdown("---")

tax_rate = st.sidebar.slider(
    "Income Tax Rate",
    min_value=0.0,
    max_value=0.5,
    value=0.30,
    step=0.01,
    help="Tax rate applied to acquisition and capital gains (default 30%)"
)

# Show the social security rate (not editable, depends on regime)
social_security_rate = SOCIAL_SECURITY_RATES.get(selected_regime, 0.172)
st.sidebar.metric(
    "Social Security Rate",
    f"{social_security_rate * 100:.1f}%",
    help="Rate depends on selected regime"
)

# Input section
st.header("📊 RSU Details")

col1, col2 = st.columns(2)

with col1:
    # Stock ticker input
    stock_ticker = st.text_input(
        "Stock Ticker",
        value="META",
        help="Enter the stock ticker symbol (e.g., META, AAPL, GOOGL, MSFT)",
        placeholder="META"
    ).upper().strip()

    vesting_date = st.date_input(
        "Vesting Date",
        value=date.today() - relativedelta(years=1),
        help="Date when the RSU vested"
    )

    sell_date = st.date_input(
        "Sell Date",
        value=date.today(),
        help="Date when you plan to sell"
    )

    num_shares = st.number_input(
        "Number of Shares to Sell",
        min_value=1,
        value=10,
        step=1,
        help="How many shares you want to sell"
    )

# Fetch data buttons and values
with col2:
    st.write("**Stock & Currency Data**")

    # Show stock name if available
    if stock_ticker:
        stock_name = get_stock_name(stock_ticker)
        if stock_name != stock_ticker:
            st.caption(f"📈 {stock_name}")

    # Fetch buttons
    col_fetch1, col_fetch2 = st.columns(2)
    with col_fetch1:
        fetch_stock = st.button(f"🔄 Fetch {stock_ticker} Prices", use_container_width=True)
    with col_fetch2:
        fetch_currency = st.button("🔄 Fetch USD/EUR", use_container_width=True)

    # Initialize session state for fetched values
    if "vesting_price" not in st.session_state:
        st.session_state.vesting_price = 100.0
    if "current_price" not in st.session_state:
        st.session_state.current_price = 150.0
    if "usd_eur_rate" not in st.session_state:
        st.session_state.usd_eur_rate = 0.92
    if "last_vesting_date" not in st.session_state:
        st.session_state.last_vesting_date = None
    if "last_sell_date" not in st.session_state:
        st.session_state.last_sell_date = None
    if "last_ticker" not in st.session_state:
        st.session_state.last_ticker = None

    # Auto-fetch when dates or ticker change
    dates_changed = (
        st.session_state.last_vesting_date != vesting_date or
        st.session_state.last_sell_date != sell_date
    )
    ticker_changed = st.session_state.last_ticker != stock_ticker

    if fetch_stock or ((dates_changed or ticker_changed) and st.session_state.last_vesting_date is not None):
        with st.spinner(f"Fetching {stock_ticker} stock prices..."):
            vesting_price = fetch_stock_price(stock_ticker, vesting_date)
            if vesting_price:
                st.session_state.vesting_price = vesting_price

            current_price = fetch_stock_price(stock_ticker, sell_date)
            if current_price:
                st.session_state.current_price = current_price

        st.session_state.last_vesting_date = vesting_date
        st.session_state.last_sell_date = sell_date
        st.session_state.last_ticker = stock_ticker

    if fetch_currency:
        with st.spinner("Fetching USD/EUR rate..."):
            rate = fetch_usd_eur_rate()
            if rate:
                st.session_state.usd_eur_rate = rate

    # Update last dates and ticker
    st.session_state.last_vesting_date = vesting_date
    st.session_state.last_sell_date = sell_date
    st.session_state.last_ticker = stock_ticker

# Editable values (user can override fetched values)
st.subheader("📈 Values (editable)")
col_val1, col_val2, col_val3 = st.columns(3)

with col_val1:
    vesting_value_usd = st.number_input(
        "Vesting Value per Share ($)",
        min_value=0.0,
        value=st.session_state.vesting_price,
        step=1.0,
        help=f"Stock price at vesting date in USD. Auto-fetched from Yahoo Finance for {stock_ticker}, but you can override."
    )

with col_val2:
    actual_value_usd = st.number_input(
        "Current Share Value ($)",
        min_value=0.0,
        value=st.session_state.current_price,
        step=1.0,
        help=f"Stock price at sell date in USD. Auto-fetched from Yahoo Finance for {stock_ticker}, but you can override."
    )

with col_val3:
    usd_to_eur = st.number_input(
        "USD to EUR Rate",
        min_value=0.0,
        value=st.session_state.usd_eur_rate,
        step=0.01,
        help="How many Euros per 1 Dollar. Auto-fetched, but you can override."
    )

# Calculations
st.divider()
st.header("📈 Results")

# Calculate holding period
holding_delta = relativedelta(sell_date, vesting_date)
years_held = holding_delta.years + holding_delta.months / 12 + holding_delta.days / 365

# Convert values to EUR
actual_value_eur = actual_value_usd * usd_to_eur
vesting_value_eur = vesting_value_usd * usd_to_eur

# Gross proceed
gross_proceed = num_shares * actual_value_eur

# Acquisition gain (value at vesting, converted to EUR)
acquisition_gain = num_shares * vesting_value_eur

# Capital gain/loss
capital_gain = gross_proceed - acquisition_gain

# Calculate taper relief based on regime
if selected_regime == TaxRegime.MACRON_I:
    if years_held >= 8:
        has_taper_relief = True
        taper_relief_rate = 0.65
        relief_description = "65% (held 8+ years)"
    elif years_held >= 2:
        has_taper_relief = True
        taper_relief_rate = 0.50
        relief_description = "50% (held 2-8 years)"
    else:
        has_taper_relief = False
        taper_relief_rate = 0.0
        relief_description = "None (need 2+ years)"
elif selected_regime == TaxRegime.MACRON_III:
    if acquisition_gain <= MACRON_III_THRESHOLD:
        has_taper_relief = True
        taper_relief_rate = 0.50
        relief_description = f"50% (under €{MACRON_III_THRESHOLD:,})"
    else:
        has_taper_relief = False
        taper_relief_rate = 0.0
        relief_description = f"None (over €{MACRON_III_THRESHOLD:,})"
else:  # UNRESTRICTED
    has_taper_relief = False
    taper_relief_rate = 0.0
    relief_description = "None (unrestricted)"

# Apply taper relief to acquisition gain
acquisition_gain_after_relief = acquisition_gain * (1 - taper_relief_rate)

# Tributable gain = acquisition gain (after relief) + capital gain
tributable_gain = acquisition_gain_after_relief + capital_gain

# Calculate social security rate based on regime
if selected_regime == TaxRegime.MACRON_III and acquisition_gain > MACRON_III_THRESHOLD:
    effective_social_rate = 0.097  # Activity rate for over-threshold
else:
    effective_social_rate = SOCIAL_SECURITY_RATES.get(selected_regime, 0.172)

# Taxes
social_security_taxes = tributable_gain * effective_social_rate
acquisition_taxes = acquisition_gain_after_relief * tax_rate

if capital_gain > 0:
    capital_gain_taxes = capital_gain * tax_rate
else:
    capital_gain_taxes = 0  # No taxes on capital losses

# Salariale contribution (Macron III over €300k only)
if selected_regime == TaxRegime.MACRON_III and acquisition_gain > MACRON_III_THRESHOLD:
    salariale_contribution = acquisition_gain * MACRON_III_SALARIALE_CONTRIBUTION
else:
    salariale_contribution = 0.0

# Total taxes
total_taxes = social_security_taxes + acquisition_taxes + capital_gain_taxes + salariale_contribution

# Net in pocket
net_in_pocket = gross_proceed - total_taxes

# Tax percentage
total_loss_in_taxes = gross_proceed - net_in_pocket
tax_percentage = (total_loss_in_taxes / gross_proceed * 100) if gross_proceed > 0 else 0

# Display regime info
st.info(f"**Regime:** {regime_name} | **Taper Relief:** {relief_description}")

# Display holding period info
col_info1, col_info2 = st.columns(2)
with col_info1:
    st.metric(
        "Years Held",
        f"{years_held:.2f}",
        help="**Formula:** (Sell Date - Vesting Date) in years"
    )
with col_info2:
    if has_taper_relief:
        st.metric(
            "Taper Relief",
            f"{taper_relief_rate*100:.0f}% ✅",
            help=f"**{regime_name}**\n\n{relief_description}"
        )
    else:
        if selected_regime == TaxRegime.MACRON_I:
            days_to_relief = (vesting_date + relativedelta(years=2) - sell_date).days
            if days_to_relief > 0:
                st.metric(
                    "Taper Relief",
                    f"No ❌ ({days_to_relief} days left)",
                    help="**Macron I:** Need to hold 2+ years for 50% abatement"
                )
            else:
                st.metric("Taper Relief", "No ❌")
        elif selected_regime == TaxRegime.MACRON_III:
            st.metric(
                "Taper Relief",
                "No ❌",
                help=f"**Macron III:** Acquisition gain exceeds €{MACRON_III_THRESHOLD:,} threshold"
            )
        else:
            st.metric(
                "Taper Relief",
                "No ❌",
                help="**Unrestricted:** No abatement available"
            )

st.divider()

# Value breakdown
st.subheader("💵 Value Breakdown")
col_v1, col_v2, col_v3 = st.columns(3)
with col_v1:
    st.metric(
        "Current Share Value (€)",
        f"€{actual_value_eur:,.2f}",
        help=f"**Formula:** Current Share Value ($) × USD/EUR Rate\n\n= ${actual_value_usd:,.2f} × {usd_to_eur} = €{actual_value_eur:,.2f}"
    )
with col_v2:
    st.metric(
        "Vesting Value per Share (€)",
        f"€{vesting_value_eur:,.2f}",
        help=f"**Formula:** Vesting Value ($) × USD/EUR Rate\n\n= ${vesting_value_usd:,.2f} × {usd_to_eur} = €{vesting_value_eur:,.2f}"
    )
with col_v3:
    st.metric(
        "Gross Proceed",
        f"€{gross_proceed:,.2f}",
        help=f"**Formula:** Number of Shares × Current Share Value (€)\n\n= {num_shares} × €{actual_value_eur:,.2f} = €{gross_proceed:,.2f}"
    )

# Gains breakdown
st.subheader("📊 Gains Breakdown")
col_g1, col_g2, col_g3 = st.columns(3)
with col_g1:
    st.metric(
        "Acquisition Gain",
        f"€{acquisition_gain:,.2f}",
        help=f"**Formula:** Number of Shares × Vesting Value (€)\n\n= {num_shares} × €{vesting_value_eur:,.2f} = €{acquisition_gain:,.2f}"
    )
with col_g2:
    st.metric(
        "Acquisition Gain (after relief)",
        f"€{acquisition_gain_after_relief:,.2f}",
        delta=f"{-acquisition_gain * taper_relief_rate:,.2f}" if has_taper_relief else None,
        delta_color="inverse",
        help=f"**Formula:** Acquisition Gain × (1 - Taper Relief Rate)\n\n= €{acquisition_gain:,.2f} × (1 - {taper_relief_rate}) = €{acquisition_gain_after_relief:,.2f}"
    )
with col_g3:
    st.metric(
        "Capital Gain",
        f"€{capital_gain:,.2f}",
        help=f"**Formula:** Gross Proceed - Acquisition Gain\n\n= €{gross_proceed:,.2f} - €{acquisition_gain:,.2f} = €{capital_gain:,.2f}"
    )

st.metric(
    "Tributable Gain",
    f"€{tributable_gain:,.2f}",
    help=f"**Formula:** Acquisition Gain (after relief) + Capital Gain\n\n= €{acquisition_gain_after_relief:,.2f} + €{capital_gain:,.2f} = €{tributable_gain:,.2f}"
)

# Taxes breakdown
st.subheader("🏛️ Taxes Breakdown")

# Determine number of columns based on whether salariale contribution applies
if salariale_contribution > 0:
    col_t1, col_t2, col_t3, col_t4 = st.columns(4)
else:
    col_t1, col_t2, col_t3 = st.columns(3)

with col_t1:
    st.metric(
        f"Social Security ({effective_social_rate*100:.1f}%)",
        f"€{social_security_taxes:,.2f}",
        help=f"**Formula:** Tributable Gain × Social Security Rate\n\n= €{tributable_gain:,.2f} × {effective_social_rate} = €{social_security_taxes:,.2f}"
    )
with col_t2:
    st.metric(
        f"Acquisition Tax ({tax_rate*100:.0f}%)",
        f"€{acquisition_taxes:,.2f}",
        help=f"**Formula:** Acquisition Gain (after relief) × Tax Rate\n\n= €{acquisition_gain_after_relief:,.2f} × {tax_rate} = €{acquisition_taxes:,.2f}"
    )
with col_t3:
    st.metric(
        f"Capital Gain Tax ({tax_rate*100:.0f}%)",
        f"€{capital_gain_taxes:,.2f}",
        help=f"**Formula:** Capital Gain × Tax Rate (only if positive)\n\n= €{max(capital_gain, 0):,.2f} × {tax_rate} = €{capital_gain_taxes:,.2f}"
    )

if salariale_contribution > 0:
    with col_t4:
        st.metric(
            f"Salariale (10%)",
            f"€{salariale_contribution:,.2f}",
            help=f"**Formula:** Acquisition Gain × 10% (Macron III over €300k)\n\n= €{acquisition_gain:,.2f} × 0.10 = €{salariale_contribution:,.2f}"
        )

st.divider()

# Final results
st.subheader("💰 Final Results")
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    st.metric(
        "Total Taxes",
        f"€{total_taxes:,.2f}",
        delta=f"-{tax_percentage:.1f}%",
        delta_color="inverse",
        help=f"**Formula:** Social Security + Acquisition Tax + Capital Gain Tax + Salariale\n\n= €{social_security_taxes:,.2f} + €{acquisition_taxes:,.2f} + €{capital_gain_taxes:,.2f} + €{salariale_contribution:,.2f} = €{total_taxes:,.2f}"
    )
with col_f2:
    st.metric(
        "Net in Pocket",
        f"€{net_in_pocket:,.2f}",
        delta=f"{100-tax_percentage:.1f}% of gross",
        delta_color="normal",
        help=f"**Formula:** Gross Proceed - Total Taxes\n\n= €{gross_proceed:,.2f} - €{total_taxes:,.2f} = €{net_in_pocket:,.2f}"
    )
with col_f3:
    st.metric(
        "Effective Tax Rate",
        f"{tax_percentage:.1f}%",
        help=f"**Formula:** (Total Taxes / Gross Proceed) × 100\n\n= (€{total_taxes:,.2f} / €{gross_proceed:,.2f}) × 100 = {tax_percentage:.1f}%"
    )

# Summary table
st.divider()
with st.expander("📋 Detailed Summary"):
    summary_data = f"""
    | Item | Value |
    |------|-------|
    | **Tax Regime** | {regime_name} |
    | **Shares to Sell** | {num_shares} |
    | **Current Value (USD)** | ${actual_value_usd:,.2f} |
    | **USD/EUR Rate** | {usd_to_eur} |
    | **Current Value (EUR)** | €{actual_value_eur:,.2f} |
    | **Vesting Value (USD)** | ${vesting_value_usd:,.2f} |
    | **Vesting Value (EUR)** | €{vesting_value_eur:,.2f} |
    | **Years Held** | {years_held:.2f} |
    | **Taper Relief** | {relief_description} |
    | --- | --- |
    | **Gross Proceed** | €{gross_proceed:,.2f} |
    | **Acquisition Gain** | €{acquisition_gain:,.2f} |
    | **Acquisition Gain (after relief)** | €{acquisition_gain_after_relief:,.2f} |
    | **Capital Gain** | €{capital_gain:,.2f} |
    | **Tributable Gain** | €{tributable_gain:,.2f} |
    | --- | --- |
    | **Social Security Taxes ({effective_social_rate*100:.1f}%)** | €{social_security_taxes:,.2f} |
    | **Acquisition Taxes** | €{acquisition_taxes:,.2f} |
    | **Capital Gain Taxes** | €{capital_gain_taxes:,.2f} |
    """

    if salariale_contribution > 0:
        summary_data += f"| **Salariale Contribution (10%)** | €{salariale_contribution:,.2f} |\n"

    summary_data += f"""| **Total Taxes** | €{total_taxes:,.2f} |
    | --- | --- |
    | **Net in Pocket** | €{net_in_pocket:,.2f} |
    | **Effective Tax Rate** | {tax_percentage:.1f}% |
    """
    st.write(summary_data)

# Formulas reference
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
    - **Tributable Gain** = Acquisition Gain (after relief) + Capital Gain

    ### Taper Relief by Regime

    | Regime | Condition | Relief |
    |--------|-----------|--------|
    | **Macron I** | Held 2-8 years | 50% |
    | **Macron I** | Held 8+ years | 65% |
    | **Macron III** | Gain ≤ €300k | 50% (automatic) |
    | **Macron III** | Gain > €300k | 0% + 10% salariale |
    | **Unrestricted** | Always | 0% |

    ### Social Security Rates

    | Regime | Rate | Type |
    |--------|------|------|
    | **Macron I** | 17.2% | Patrimony |
    | **Macron III** (≤ €300k) | 17.2% | Patrimony |
    | **Macron III** (> €300k) | 9.7% | Activity |
    | **Unrestricted** | 9.7% | Activity |

    ### Taxes
    - **Social Security Taxes** = Tributable Gain × Social Security Rate
    - **Acquisition Taxes** = Acquisition Gain (after relief) × Income Tax Rate
    - **Capital Gain Taxes** = Capital Gain × Income Tax Rate *(only if positive)*
    - **Salariale Contribution** = Acquisition Gain × 10% *(Macron III over €300k only)*
    - **Total Taxes** = Social Security + Acquisition Taxes + Capital Gain Taxes + Salariale

    ### Final Results
    - **Net in Pocket** = Gross Proceed - Total Taxes
    - **Effective Tax Rate** = (Total Taxes / Gross Proceed) × 100
    """)

# Regime comparison
with st.expander("📊 Regime Comparison"):
    st.markdown("""
    ### Which Regime Applies to You?

    The regime depends on when your RSUs were **granted** (shareholder approval date):

    | Grant Period | Regime |
    |--------------|--------|
    | Before Aug 7, 2015 | Pre-Macron |
    | Aug 7, 2015 - Dec 29, 2016 | **Macron I** |
    | Dec 30, 2016 - Dec 31, 2017 | Macron II |
    | Jan 1, 2018 - present | **Macron III** |

    ### Unrestricted (Non-Qualified)

    If your RSU plan does not comply with French Commercial Code requirements (no French sub-plan),
    the RSUs are considered "unrestricted" and taxed fully as salary income.

    ### Key Differences

    | Feature | Macron I | Macron III | Unrestricted |
    |---------|----------|------------|--------------|
    | Abatement | 50-65% (holding period) | 50% automatic (under €300k) | None |
    | Social charges | 17.2% | 17.2% / 9.7% | 9.7% |
    | €300k threshold | No | Yes | No |
    | 10% salariale | No | Yes (over €300k) | No |
    | Best for | Long-term holds | Gains under €300k | - |
    """)
