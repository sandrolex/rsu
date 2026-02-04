"""
RSU Tax Calculation Functions

This module contains the core calculation logic for the RSU selling calculator.
All monetary values are in EUR unless otherwise specified.

Supported tax regimes:
- Macron I (August 7, 2015 - December 29, 2016)
- Macron III (January 1, 2018 - present)
- Unrestricted (Non-qualified plans)
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional
from dateutil.relativedelta import relativedelta


class TaxRegime(Enum):
    """French RSU tax regimes."""
    MACRON_I = "macron_i"
    MACRON_III = "macron_iii"
    UNRESTRICTED = "unrestricted"


# Capital gain is taxed at flat 30% PFU (Prélèvement Forfaitaire Unique)
# PFU includes: 12.8% income tax + 17.2% social contributions
CAPITAL_GAIN_PFU_RATE = 0.30

# French progressive income tax brackets for 2025 (on 2024 income)
# Each tuple is (threshold, rate) - rate applies to income ABOVE the threshold
FRENCH_TAX_BRACKETS_2025 = [
    (0, 0.00),           # 0% up to €11,497
    (11_497, 0.11),      # 11% from €11,498 to €29,315
    (29_315, 0.30),      # 30% from €29,316 to €83,823
    (83_823, 0.41),      # 41% from €83,824 to €180,294
    (180_294, 0.45),     # 45% above €180,294
]


@dataclass
class RSUInput:
    """Input parameters for RSU tax calculation."""
    vesting_date: date
    sell_date: date
    num_shares: int
    vesting_value_usd: float
    current_value_usd: float
    usd_to_eur: float
    regime: TaxRegime = TaxRegime.MACRON_I
    # For progressive tax calculation, provide ONE of:
    # - annual_income: Your annual taxable income (RSU gain will be added and taxed progressively)
    # - acquisition_tax_rate: Manual rate to apply (simplified, may overstate tax)
    annual_income: Optional[float] = None
    acquisition_tax_rate: Optional[float] = None  # Fallback if annual_income not provided


@dataclass
class RSUResult:
    """Results of RSU tax calculation."""
    # Holding period
    years_held: float
    has_taper_relief: bool
    taper_relief_rate: float

    # Values in EUR
    vesting_value_eur: float
    current_value_eur: float
    gross_proceed: float

    # Gains
    acquisition_gain: float
    acquisition_gain_after_relief: float
    capital_gain: float

    # Taxes breakdown
    acquisition_social_security: float  # Social security on acquisition gain
    acquisition_income_tax: float       # Income tax on acquisition gain
    capital_gain_tax: float             # PFU on capital gain (includes social)
    salariale_contribution: float       # 10% contribution (Macron III over €300k)
    total_taxes: float

    # Final results
    net_in_pocket: float
    effective_tax_rate: float

    # Regime info
    regime: TaxRegime
    regime_notes: str


# Social security rates by regime (applies to acquisition gain only)
SOCIAL_SECURITY_RATES = {
    TaxRegime.MACRON_I: 0.172,      # Patrimony rate (17.2%)
    TaxRegime.MACRON_III: 0.172,    # Patrimony rate for gains under €300k
    TaxRegime.UNRESTRICTED: 0.097,  # Activity rate (9.7% = 9.2% CSG + 0.5% CRDS)
}

# Additional rates for Macron III over €300k threshold
MACRON_III_THRESHOLD = 300_000
MACRON_III_OVER_THRESHOLD_SOCIAL_RATE = 0.097  # Activity rate
MACRON_III_SALARIALE_CONTRIBUTION = 0.10  # 10% employee contribution


def get_marginal_tax_rate(annual_income: float) -> float:
    """
    Get the marginal tax rate (TMI) based on annual taxable income.

    Args:
        annual_income: Annual taxable income in EUR

    Returns:
        Marginal tax rate (0.0 to 0.45)
    """
    rate = 0.0
    for threshold, bracket_rate in FRENCH_TAX_BRACKETS_2025:
        if annual_income > threshold:
            rate = bracket_rate
    return rate


def calculate_progressive_income_tax(taxable_income: float) -> float:
    """
    Calculate French income tax using progressive brackets.

    Tax is calculated bracket by bracket:
    - 0% on income from €0 to €11,497
    - 11% on income from €11,497 to €29,315
    - 30% on income from €29,315 to €83,823
    - 41% on income from €83,823 to €180,294
    - 45% on income above €180,294

    Args:
        taxable_income: Total taxable income in EUR

    Returns:
        Total income tax in EUR
    """
    if taxable_income <= 0:
        return 0.0

    tax = 0.0
    brackets = FRENCH_TAX_BRACKETS_2025

    for i in range(len(brackets)):
        threshold, rate = brackets[i]
        next_threshold = brackets[i + 1][0] if i + 1 < len(brackets) else float("inf")

        if taxable_income <= threshold:
            break

        # Calculate taxable amount in this bracket
        bracket_ceiling = min(taxable_income, next_threshold)
        bracket_income = bracket_ceiling - threshold
        tax += bracket_income * rate

    return tax


def calculate_tax_on_additional_income(
    base_income: float, additional_income: float
) -> float:
    """
    Calculate the tax specifically on additional income (e.g., RSU acquisition gain).

    This correctly handles cases where the additional income spans multiple brackets.
    The tax is calculated as: tax(base + additional) - tax(base)

    Args:
        base_income: Existing annual income in EUR (before RSU)
        additional_income: Additional income to be taxed in EUR (RSU gain)

    Returns:
        Tax attributable to the additional income in EUR
    """
    tax_with_additional = calculate_progressive_income_tax(base_income + additional_income)
    tax_base_only = calculate_progressive_income_tax(base_income)
    return tax_with_additional - tax_base_only


def calculate_years_held(vesting_date: date, sell_date: date) -> float:
    """
    Calculate the number of years between vesting and sell date.

    Args:
        vesting_date: Date when RSU vested
        sell_date: Date when selling

    Returns:
        Number of years as a float
    """
    delta = relativedelta(sell_date, vesting_date)
    return delta.years + delta.months / 12 + delta.days / 365


def calculate_taper_relief_macron_i(years_held: float) -> tuple[bool, float]:
    """
    Calculate taper relief for Macron I regime.

    Macron I abatements:
    - 0% if held < 2 years
    - 50% if held >= 2 years and < 8 years
    - 65% if held >= 8 years

    Args:
        years_held: Number of years shares were held

    Returns:
        Tuple of (has_relief, relief_rate)
    """
    if years_held >= 8:
        return True, 0.65
    elif years_held >= 2:
        return True, 0.50
    return False, 0.0


def calculate_taper_relief_macron_iii(
    acquisition_gain: float,
) -> tuple[bool, float, bool]:
    """
    Calculate taper relief for Macron III regime.

    Macron III rules:
    - Automatic 50% abatement for gains under €300,000
    - No abatement for gains over €300,000 (treated as salary)

    Args:
        acquisition_gain: Total acquisition gain in EUR

    Returns:
        Tuple of (has_relief, relief_rate, over_threshold)
    """
    if acquisition_gain <= MACRON_III_THRESHOLD:
        return True, 0.50, False
    return False, 0.0, True


def calculate_taper_relief(
    years_held: float,
    regime: TaxRegime,
    acquisition_gain: float = 0,
) -> tuple[bool, float]:
    """
    Determine if taper relief applies and the rate based on regime.

    Args:
        years_held: Number of years shares were held
        regime: Tax regime to apply
        acquisition_gain: Total acquisition gain (for Macron III threshold)

    Returns:
        Tuple of (has_relief, relief_rate)
    """
    if regime == TaxRegime.MACRON_I:
        return calculate_taper_relief_macron_i(years_held)
    elif regime == TaxRegime.MACRON_III:
        has_relief, rate, _ = calculate_taper_relief_macron_iii(acquisition_gain)
        return has_relief, rate
    else:  # UNRESTRICTED
        return False, 0.0


def convert_usd_to_eur(usd_amount: float, usd_to_eur: float) -> float:
    """
    Convert USD amount to EUR.

    Args:
        usd_amount: Amount in USD
        usd_to_eur: Conversion rate (EUR per 1 USD)

    Returns:
        Amount in EUR
    """
    return usd_amount * usd_to_eur


def calculate_gross_proceed(num_shares: int, current_value_eur: float) -> float:
    """
    Calculate gross proceed from selling shares.

    Formula: num_shares × current_value_eur

    Args:
        num_shares: Number of shares to sell
        current_value_eur: Current share value in EUR

    Returns:
        Gross proceed in EUR
    """
    return num_shares * current_value_eur


def calculate_acquisition_gain(num_shares: int, vesting_value_eur: float) -> float:
    """
    Calculate acquisition gain (value at vesting).

    Formula: num_shares × vesting_value_eur

    Args:
        num_shares: Number of shares
        vesting_value_eur: Share value at vesting in EUR

    Returns:
        Acquisition gain in EUR
    """
    return num_shares * vesting_value_eur


def calculate_acquisition_gain_after_relief(
    acquisition_gain: float, taper_relief_rate: float
) -> float:
    """
    Apply taper relief to acquisition gain.

    Formula: acquisition_gain × (1 - taper_relief_rate)

    Args:
        acquisition_gain: Original acquisition gain in EUR
        taper_relief_rate: Relief rate (0.0, 0.5, or 0.65)

    Returns:
        Acquisition gain after relief in EUR
    """
    return acquisition_gain * (1 - taper_relief_rate)


def calculate_capital_gain(gross_proceed: float, acquisition_gain: float) -> float:
    """
    Calculate capital gain or loss.

    Formula: gross_proceed - acquisition_gain

    Args:
        gross_proceed: Gross proceed from sale in EUR
        acquisition_gain: Acquisition gain in EUR

    Returns:
        Capital gain (positive) or loss (negative) in EUR
    """
    return gross_proceed - acquisition_gain


def calculate_acquisition_social_security(
    acquisition_gain_after_relief: float,
    regime: TaxRegime,
    acquisition_gain: float = 0,
) -> float:
    """
    Calculate social security taxes on acquisition gain (after taper relief).

    Rates:
    - Macron I: 17.2% (patrimony rate)
    - Macron III under €300k: 17.2% (patrimony rate)
    - Macron III over €300k: 9.7% (activity rate)
    - Unrestricted: 9.7% (activity rate)

    Args:
        acquisition_gain_after_relief: Acquisition gain after taper relief in EUR
        regime: Tax regime
        acquisition_gain: Original acquisition gain (for Macron III threshold)

    Returns:
        Social security taxes in EUR
    """
    if regime == TaxRegime.MACRON_III and acquisition_gain > MACRON_III_THRESHOLD:
        return acquisition_gain_after_relief * MACRON_III_OVER_THRESHOLD_SOCIAL_RATE

    rate = SOCIAL_SECURITY_RATES.get(regime, 0.172)
    return acquisition_gain_after_relief * rate


def calculate_acquisition_income_tax(
    acquisition_gain_after_relief: float,
    annual_income: Optional[float] = None,
    tax_rate: Optional[float] = None,
) -> float:
    """
    Calculate income tax on acquisition gain (after taper relief).

    Uses French progressive brackets when annual_income is provided.
    Falls back to flat rate if only tax_rate is provided.

    Args:
        acquisition_gain_after_relief: Acquisition gain after relief in EUR
        annual_income: Annual taxable income (for progressive calculation)
        tax_rate: Flat rate fallback (0% to 45%), used if annual_income is None

    Returns:
        Income tax on acquisition gain in EUR
    """
    if annual_income is not None:
        # Use proper progressive calculation
        return calculate_tax_on_additional_income(
            annual_income, acquisition_gain_after_relief
        )
    elif tax_rate is not None:
        # Fallback to flat rate (simplified)
        return acquisition_gain_after_relief * tax_rate
    else:
        # Default to 30% if nothing provided
        return acquisition_gain_after_relief * 0.30


def calculate_capital_gain_tax(capital_gain: float) -> float:
    """
    Calculate tax on capital gain using PFU (flat rate).

    Capital gains are taxed at a flat 30% rate (PFU):
    - 12.8% income tax
    - 17.2% social contributions

    Only positive capital gains are taxed. Losses are not taxed.

    Formula: max(capital_gain, 0) × 0.30

    Args:
        capital_gain: Capital gain in EUR

    Returns:
        Capital gain tax in EUR (0 if capital loss)
    """
    if capital_gain > 0:
        return capital_gain * CAPITAL_GAIN_PFU_RATE
    return 0.0


def calculate_salariale_contribution(
    acquisition_gain: float,
    regime: TaxRegime,
) -> float:
    """
    Calculate the 10% salariale contribution (Macron III over €300k only).

    Args:
        acquisition_gain: Original acquisition gain in EUR
        regime: Tax regime

    Returns:
        Salariale contribution in EUR
    """
    if regime == TaxRegime.MACRON_III and acquisition_gain > MACRON_III_THRESHOLD:
        return acquisition_gain * MACRON_III_SALARIALE_CONTRIBUTION
    return 0.0


def calculate_total_taxes(
    acquisition_social_security: float,
    acquisition_income_tax: float,
    capital_gain_tax: float,
    salariale_contribution: float = 0.0,
) -> float:
    """
    Calculate total taxes.

    Formula: acquisition_social + acquisition_income + capital_gain + salariale

    Args:
        acquisition_social_security: Social security on acquisition gain in EUR
        acquisition_income_tax: Income tax on acquisition gain in EUR
        capital_gain_tax: PFU tax on capital gain in EUR
        salariale_contribution: 10% salariale contribution (Macron III over €300k)

    Returns:
        Total taxes in EUR
    """
    return (
        acquisition_social_security
        + acquisition_income_tax
        + capital_gain_tax
        + salariale_contribution
    )


def calculate_net_in_pocket(gross_proceed: float, total_taxes: float) -> float:
    """
    Calculate net amount after taxes.

    Formula: gross_proceed - total_taxes

    Args:
        gross_proceed: Gross proceed in EUR
        total_taxes: Total taxes in EUR

    Returns:
        Net in pocket in EUR
    """
    return gross_proceed - total_taxes


def calculate_effective_tax_rate(total_taxes: float, gross_proceed: float) -> float:
    """
    Calculate effective tax rate as a percentage.

    Formula: (total_taxes / gross_proceed) × 100

    Args:
        total_taxes: Total taxes in EUR
        gross_proceed: Gross proceed in EUR

    Returns:
        Effective tax rate as percentage (0-100)
    """
    if gross_proceed <= 0:
        return 0.0
    return (total_taxes / gross_proceed) * 100


def get_regime_notes(
    regime: TaxRegime,
    years_held: float,
    acquisition_gain: float,
    taper_relief_rate: float,
) -> str:
    """
    Generate explanatory notes about the regime and its application.

    Args:
        regime: Tax regime
        years_held: Years shares were held
        acquisition_gain: Acquisition gain in EUR
        taper_relief_rate: Applied taper relief rate

    Returns:
        Explanatory notes string
    """
    if regime == TaxRegime.MACRON_I:
        if years_held >= 8:
            return "Macron I: 65% abatement (held 8+ years)"
        elif years_held >= 2:
            return "Macron I: 50% abatement (held 2-8 years)"
        else:
            return f"Macron I: No abatement (held < 2 years, need {2 - years_held:.1f} more years)"

    elif regime == TaxRegime.MACRON_III:
        if acquisition_gain > MACRON_III_THRESHOLD:
            return f"Macron III: Over €300k threshold - treated as salary + 10% contribution"
        else:
            return "Macron III: 50% automatic abatement (gain under €300k)"

    else:  # UNRESTRICTED
        return "Unrestricted: No abatement - fully taxed as salary"


def calculate_rsu_taxes(input_data: RSUInput) -> RSUResult:
    """
    Perform complete RSU tax calculation.

    This is the main entry point that combines all calculation functions.

    Args:
        input_data: RSUInput dataclass with all input parameters

    Returns:
        RSUResult dataclass with all calculated values
    """
    # Calculate holding period
    years_held = calculate_years_held(input_data.vesting_date, input_data.sell_date)

    # Convert values to EUR
    vesting_value_eur = convert_usd_to_eur(
        input_data.vesting_value_usd, input_data.usd_to_eur
    )
    current_value_eur = convert_usd_to_eur(
        input_data.current_value_usd, input_data.usd_to_eur
    )

    # Calculate acquisition gain first (needed for Macron III threshold)
    acquisition_gain = calculate_acquisition_gain(
        input_data.num_shares, vesting_value_eur
    )

    # Calculate taper relief based on regime
    has_taper_relief, taper_relief_rate = calculate_taper_relief(
        years_held, input_data.regime, acquisition_gain
    )

    # Apply taper relief to acquisition gain
    acquisition_gain_after_relief = calculate_acquisition_gain_after_relief(
        acquisition_gain, taper_relief_rate
    )

    # Calculate gains
    gross_proceed = calculate_gross_proceed(input_data.num_shares, current_value_eur)
    capital_gain = calculate_capital_gain(gross_proceed, acquisition_gain)

    # Calculate taxes on acquisition gain (after taper relief)
    acquisition_social_security = calculate_acquisition_social_security(
        acquisition_gain_after_relief, input_data.regime, acquisition_gain
    )
    acquisition_income_tax = calculate_acquisition_income_tax(
        acquisition_gain_after_relief,
        annual_income=input_data.annual_income,
        tax_rate=input_data.acquisition_tax_rate,
    )

    # Calculate tax on capital gain (PFU - includes social security)
    capital_gain_tax = calculate_capital_gain_tax(capital_gain)

    # Calculate salariale contribution (Macron III over €300k only)
    salariale_contribution = calculate_salariale_contribution(
        acquisition_gain, input_data.regime
    )

    # Calculate total taxes
    total_taxes = calculate_total_taxes(
        acquisition_social_security,
        acquisition_income_tax,
        capital_gain_tax,
        salariale_contribution,
    )

    # Calculate final results
    net_in_pocket = calculate_net_in_pocket(gross_proceed, total_taxes)
    effective_tax_rate = calculate_effective_tax_rate(total_taxes, gross_proceed)

    # Generate regime notes
    regime_notes = get_regime_notes(
        input_data.regime, years_held, acquisition_gain, taper_relief_rate
    )

    return RSUResult(
        years_held=years_held,
        has_taper_relief=has_taper_relief,
        taper_relief_rate=taper_relief_rate,
        vesting_value_eur=vesting_value_eur,
        current_value_eur=current_value_eur,
        gross_proceed=gross_proceed,
        acquisition_gain=acquisition_gain,
        acquisition_gain_after_relief=acquisition_gain_after_relief,
        capital_gain=capital_gain,
        acquisition_social_security=acquisition_social_security,
        acquisition_income_tax=acquisition_income_tax,
        capital_gain_tax=capital_gain_tax,
        salariale_contribution=salariale_contribution,
        total_taxes=total_taxes,
        net_in_pocket=net_in_pocket,
        effective_tax_rate=effective_tax_rate,
        regime=input_data.regime,
        regime_notes=regime_notes,
    )
