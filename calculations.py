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
from dateutil.relativedelta import relativedelta


class TaxRegime(Enum):
    """French RSU tax regimes."""
    MACRON_I = "macron_i"
    MACRON_III = "macron_iii"
    UNRESTRICTED = "unrestricted"


@dataclass
class RSUInput:
    """Input parameters for RSU tax calculation."""
    vesting_date: date
    sell_date: date
    num_shares: int
    vesting_value_usd: float
    current_value_usd: float
    usd_to_eur: float
    tax_rate: float = 0.30
    regime: TaxRegime = TaxRegime.MACRON_I


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
    tributable_gain: float

    # Taxes
    social_security_taxes: float
    acquisition_taxes: float
    capital_gain_taxes: float
    salariale_contribution: float
    total_taxes: float

    # Final results
    net_in_pocket: float
    effective_tax_rate: float

    # Regime info
    regime: TaxRegime
    regime_notes: str


# Social security rates by regime
SOCIAL_SECURITY_RATES = {
    TaxRegime.MACRON_I: 0.172,      # Patrimony rate (17.2%)
    TaxRegime.MACRON_III: 0.172,    # Patrimony rate for gains under €300k
    TaxRegime.UNRESTRICTED: 0.097,  # Activity rate (9.7% = 9.2% CSG + 0.5% CRDS)
}

# Additional rates for Macron III over €300k threshold
MACRON_III_THRESHOLD = 300_000
MACRON_III_OVER_THRESHOLD_SOCIAL_RATE = 0.097  # Activity rate
MACRON_III_SALARIALE_CONTRIBUTION = 0.10  # 10% employee contribution


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
    - 50% if held 2-8 years
    - 65% if held 8+ years

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


def calculate_tributable_gain(
    acquisition_gain_after_relief: float, capital_gain: float
) -> float:
    """
    Calculate total tributable (taxable) gain.

    Formula: acquisition_gain_after_relief + capital_gain

    Args:
        acquisition_gain_after_relief: Acquisition gain after taper relief in EUR
        capital_gain: Capital gain in EUR

    Returns:
        Tributable gain in EUR
    """
    return acquisition_gain_after_relief + capital_gain


def calculate_social_security_taxes(
    tributable_gain: float,
    regime: TaxRegime,
    acquisition_gain: float = 0,
) -> float:
    """
    Calculate social security taxes based on regime.

    Rates:
    - Macron I: 17.2% (patrimony rate)
    - Macron III under €300k: 17.2% (patrimony rate)
    - Macron III over €300k: 9.7% (activity rate)
    - Unrestricted: 9.7% (activity rate)

    Args:
        tributable_gain: Tributable gain in EUR
        regime: Tax regime
        acquisition_gain: Original acquisition gain (for Macron III threshold)

    Returns:
        Social security taxes in EUR
    """
    if regime == TaxRegime.MACRON_III and acquisition_gain > MACRON_III_THRESHOLD:
        return tributable_gain * MACRON_III_OVER_THRESHOLD_SOCIAL_RATE

    rate = SOCIAL_SECURITY_RATES.get(regime, 0.172)
    return tributable_gain * rate


def calculate_acquisition_taxes(
    acquisition_gain_after_relief: float, tax_rate: float
) -> float:
    """
    Calculate taxes on acquisition gain.

    Formula: acquisition_gain_after_relief × tax_rate

    Args:
        acquisition_gain_after_relief: Acquisition gain after relief in EUR
        tax_rate: Income tax rate (default 0.30)

    Returns:
        Acquisition taxes in EUR
    """
    return acquisition_gain_after_relief * tax_rate


def calculate_capital_gain_taxes(capital_gain: float, tax_rate: float) -> float:
    """
    Calculate taxes on capital gain.

    Only positive capital gains are taxed. Losses are not taxed.

    Formula: max(capital_gain, 0) × tax_rate

    Args:
        capital_gain: Capital gain in EUR
        tax_rate: Income tax rate (default 0.30)

    Returns:
        Capital gain taxes in EUR (0 if capital loss)
    """
    if capital_gain > 0:
        return capital_gain * tax_rate
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
    social_security_taxes: float,
    acquisition_taxes: float,
    capital_gain_taxes: float,
    salariale_contribution: float = 0.0,
) -> float:
    """
    Calculate total taxes.

    Formula: social_security + acquisition_taxes + capital_gain_taxes + salariale

    Args:
        social_security_taxes: Social security taxes in EUR
        acquisition_taxes: Acquisition taxes in EUR
        capital_gain_taxes: Capital gain taxes in EUR
        salariale_contribution: 10% salariale contribution (Macron III over €300k)

    Returns:
        Total taxes in EUR
    """
    return (
        social_security_taxes
        + acquisition_taxes
        + capital_gain_taxes
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

    # Calculate gains
    gross_proceed = calculate_gross_proceed(input_data.num_shares, current_value_eur)
    acquisition_gain_after_relief = calculate_acquisition_gain_after_relief(
        acquisition_gain, taper_relief_rate
    )
    capital_gain = calculate_capital_gain(gross_proceed, acquisition_gain)
    tributable_gain = calculate_tributable_gain(
        acquisition_gain_after_relief, capital_gain
    )

    # Calculate taxes
    social_security_taxes = calculate_social_security_taxes(
        tributable_gain, input_data.regime, acquisition_gain
    )
    acquisition_taxes = calculate_acquisition_taxes(
        acquisition_gain_after_relief, input_data.tax_rate
    )
    capital_gain_taxes = calculate_capital_gain_taxes(
        capital_gain, input_data.tax_rate
    )
    salariale_contribution = calculate_salariale_contribution(
        acquisition_gain, input_data.regime
    )
    total_taxes = calculate_total_taxes(
        social_security_taxes,
        acquisition_taxes,
        capital_gain_taxes,
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
        tributable_gain=tributable_gain,
        social_security_taxes=social_security_taxes,
        acquisition_taxes=acquisition_taxes,
        capital_gain_taxes=capital_gain_taxes,
        salariale_contribution=salariale_contribution,
        total_taxes=total_taxes,
        net_in_pocket=net_in_pocket,
        effective_tax_rate=effective_tax_rate,
        regime=input_data.regime,
        regime_notes=regime_notes,
    )
