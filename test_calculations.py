"""
Tests for RSU Tax Calculation Functions
"""

import pytest
from datetime import date
from dateutil.relativedelta import relativedelta

from calculations import (
    TaxRegime,
    RSUInput,
    RSUResult,
    MACRON_III_THRESHOLD,
    CAPITAL_GAIN_PFU_RATE,
    FRENCH_TAX_BRACKETS_2025,
    calculate_years_held,
    calculate_taper_relief,
    calculate_taper_relief_macron_i,
    calculate_taper_relief_macron_iii,
    convert_usd_to_eur,
    calculate_gross_proceed,
    calculate_acquisition_gain,
    calculate_acquisition_gain_after_relief,
    calculate_capital_gain,
    calculate_acquisition_social_security,
    calculate_acquisition_income_tax,
    calculate_capital_gain_tax,
    calculate_salariale_contribution,
    calculate_total_taxes,
    calculate_net_in_pocket,
    calculate_effective_tax_rate,
    calculate_rsu_taxes,
    get_regime_notes,
    get_marginal_tax_rate,
    calculate_progressive_income_tax,
    calculate_tax_on_additional_income,
)


class TestYearsHeld:
    """Tests for calculate_years_held function."""

    def test_exactly_one_year(self):
        vesting = date(2023, 1, 15)
        sell = date(2024, 1, 15)
        assert calculate_years_held(vesting, sell) == pytest.approx(1.0, rel=0.01)

    def test_exactly_two_years(self):
        vesting = date(2022, 6, 1)
        sell = date(2024, 6, 1)
        assert calculate_years_held(vesting, sell) == pytest.approx(2.0, rel=0.01)

    def test_six_months(self):
        vesting = date(2024, 1, 1)
        sell = date(2024, 7, 1)
        assert calculate_years_held(vesting, sell) == pytest.approx(0.5, rel=0.01)

    def test_same_day(self):
        vesting = date(2024, 1, 1)
        sell = date(2024, 1, 1)
        assert calculate_years_held(vesting, sell) == pytest.approx(0.0, rel=0.01)

    def test_two_years_and_six_months(self):
        vesting = date(2022, 1, 1)
        sell = date(2024, 7, 1)
        assert calculate_years_held(vesting, sell) == pytest.approx(2.5, rel=0.01)

    def test_eight_years(self):
        vesting = date(2016, 1, 1)
        sell = date(2024, 1, 1)
        assert calculate_years_held(vesting, sell) == pytest.approx(8.0, rel=0.01)


class TestTaperReliefMacronI:
    """Tests for Macron I taper relief calculation."""

    def test_no_relief_under_two_years(self):
        has_relief, rate = calculate_taper_relief_macron_i(1.5)
        assert has_relief is False
        assert rate == 0.0

    def test_no_relief_at_1_99_years(self):
        has_relief, rate = calculate_taper_relief_macron_i(1.99)
        assert has_relief is False
        assert rate == 0.0

    def test_50_percent_relief_at_exactly_two_years(self):
        has_relief, rate = calculate_taper_relief_macron_i(2.0)
        assert has_relief is True
        assert rate == 0.5

    def test_50_percent_relief_at_five_years(self):
        has_relief, rate = calculate_taper_relief_macron_i(5.0)
        assert has_relief is True
        assert rate == 0.5

    def test_50_percent_relief_at_7_99_years(self):
        has_relief, rate = calculate_taper_relief_macron_i(7.99)
        assert has_relief is True
        assert rate == 0.5

    def test_65_percent_relief_at_exactly_eight_years(self):
        has_relief, rate = calculate_taper_relief_macron_i(8.0)
        assert has_relief is True
        assert rate == 0.65

    def test_65_percent_relief_over_eight_years(self):
        has_relief, rate = calculate_taper_relief_macron_i(10.0)
        assert has_relief is True
        assert rate == 0.65

    def test_no_relief_at_zero_years(self):
        has_relief, rate = calculate_taper_relief_macron_i(0.0)
        assert has_relief is False
        assert rate == 0.0


class TestTaperReliefMacronIII:
    """Tests for Macron III taper relief calculation."""

    def test_50_percent_relief_under_threshold(self):
        has_relief, rate, over_threshold = calculate_taper_relief_macron_iii(100_000)
        assert has_relief is True
        assert rate == 0.5
        assert over_threshold is False

    def test_50_percent_relief_at_threshold(self):
        has_relief, rate, over_threshold = calculate_taper_relief_macron_iii(
            MACRON_III_THRESHOLD
        )
        assert has_relief is True
        assert rate == 0.5
        assert over_threshold is False

    def test_no_relief_over_threshold(self):
        has_relief, rate, over_threshold = calculate_taper_relief_macron_iii(
            MACRON_III_THRESHOLD + 1
        )
        assert has_relief is False
        assert rate == 0.0
        assert over_threshold is True

    def test_no_relief_way_over_threshold(self):
        has_relief, rate, over_threshold = calculate_taper_relief_macron_iii(500_000)
        assert has_relief is False
        assert rate == 0.0
        assert over_threshold is True


class TestTaperReliefUnrestricted:
    """Tests for unrestricted (non-qualified) taper relief."""

    def test_no_relief_regardless_of_years(self):
        has_relief, rate = calculate_taper_relief(5.0, TaxRegime.UNRESTRICTED)
        assert has_relief is False
        assert rate == 0.0

    def test_no_relief_even_with_long_holding(self):
        has_relief, rate = calculate_taper_relief(10.0, TaxRegime.UNRESTRICTED)
        assert has_relief is False
        assert rate == 0.0


class TestTaperReliefDispatch:
    """Tests for the main taper relief dispatch function."""

    def test_macron_i_dispatch(self):
        has_relief, rate = calculate_taper_relief(3.0, TaxRegime.MACRON_I)
        assert has_relief is True
        assert rate == 0.5

    def test_macron_iii_dispatch(self):
        has_relief, rate = calculate_taper_relief(
            1.0, TaxRegime.MACRON_III, acquisition_gain=100_000
        )
        assert has_relief is True
        assert rate == 0.5

    def test_unrestricted_dispatch(self):
        has_relief, rate = calculate_taper_relief(5.0, TaxRegime.UNRESTRICTED)
        assert has_relief is False
        assert rate == 0.0


class TestMarginalTaxRate:
    """Tests for get_marginal_tax_rate function."""

    def test_zero_income(self):
        assert get_marginal_tax_rate(0) == 0.0

    def test_first_bracket(self):
        assert get_marginal_tax_rate(10_000) == 0.0

    def test_second_bracket(self):
        assert get_marginal_tax_rate(20_000) == 0.11

    def test_third_bracket(self):
        assert get_marginal_tax_rate(50_000) == 0.30

    def test_fourth_bracket(self):
        assert get_marginal_tax_rate(100_000) == 0.41

    def test_fifth_bracket(self):
        assert get_marginal_tax_rate(200_000) == 0.45

    def test_boundary_second_bracket(self):
        assert get_marginal_tax_rate(11_498) == 0.11

    def test_boundary_third_bracket(self):
        assert get_marginal_tax_rate(29_316) == 0.30


class TestProgressiveIncomeTax:
    """Tests for calculate_progressive_income_tax function."""

    def test_zero_income(self):
        assert calculate_progressive_income_tax(0) == pytest.approx(0.0)

    def test_negative_income(self):
        assert calculate_progressive_income_tax(-1000) == pytest.approx(0.0)

    def test_first_bracket_only(self):
        # Income of €10,000 - all in 0% bracket
        assert calculate_progressive_income_tax(10_000) == pytest.approx(0.0)

    def test_at_first_bracket_boundary(self):
        # Income of €11,497 - exactly at 0% boundary
        assert calculate_progressive_income_tax(11_497) == pytest.approx(0.0)

    def test_second_bracket(self):
        # Income of €20,000
        # €0 - €11,497 at 0% = €0
        # €11,497 - €20,000 = €8,503 at 11% = €935.33
        expected = 8_503 * 0.11
        assert calculate_progressive_income_tax(20_000) == pytest.approx(expected, rel=0.01)

    def test_third_bracket(self):
        # Income of €50,000
        # €0 - €11,497 at 0% = €0
        # €11,497 - €29,315 = €17,818 at 11% = €1,959.98
        # €29,315 - €50,000 = €20,685 at 30% = €6,205.50
        expected = (17_818 * 0.11) + (20_685 * 0.30)
        assert calculate_progressive_income_tax(50_000) == pytest.approx(expected, rel=0.01)

    def test_fourth_bracket(self):
        # Income of €100,000
        # €0 - €11,497 at 0% = €0
        # €11,497 - €29,315 = €17,818 at 11% = €1,959.98
        # €29,315 - €83,823 = €54,508 at 30% = €16,352.40
        # €83,823 - €100,000 = €16,177 at 41% = €6,632.57
        expected = (17_818 * 0.11) + (54_508 * 0.30) + (16_177 * 0.41)
        assert calculate_progressive_income_tax(100_000) == pytest.approx(expected, rel=0.01)

    def test_fifth_bracket(self):
        # Income of €200,000
        # €0 - €11,497 at 0% = €0
        # €11,497 - €29,315 = €17,818 at 11%
        # €29,315 - €83,823 = €54,508 at 30%
        # €83,823 - €180,294 = €96,471 at 41%
        # €180,294 - €200,000 = €19,706 at 45%
        expected = (17_818 * 0.11) + (54_508 * 0.30) + (96_471 * 0.41) + (19_706 * 0.45)
        assert calculate_progressive_income_tax(200_000) == pytest.approx(expected, rel=0.01)


class TestTaxOnAdditionalIncome:
    """Tests for calculate_tax_on_additional_income function."""

    def test_additional_income_same_bracket(self):
        # Base income €50,000 (30% bracket), add €10,000
        # Both are fully in 30% bracket, so tax on additional is 10,000 * 30% = 3,000
        result = calculate_tax_on_additional_income(50_000, 10_000)
        assert result == pytest.approx(3_000, rel=0.01)

    def test_additional_income_spanning_brackets(self):
        # Base income €25,000 (11% bracket), add €10,000 → total €35,000
        # Tax without RSU: €11,497-€25,000 = €13,503 at 11% = €1,485.33
        # Tax with RSU: €11,497-€29,315 = €17,818 at 11% + €29,315-€35,000 = €5,685 at 30%
        #             = €1,959.98 + €1,705.50 = €3,665.48
        # Tax on RSU = €3,665.48 - €1,485.33 = €2,180.15
        result = calculate_tax_on_additional_income(25_000, 10_000)
        expected = (17_818 * 0.11 + 5_685 * 0.30) - (13_503 * 0.11)
        assert result == pytest.approx(expected, rel=0.01)

    def test_additional_income_from_zero(self):
        # Base income €0, add €20,000
        # Tax on €20,000 = €8,503 at 11% = €935.33
        result = calculate_tax_on_additional_income(0, 20_000)
        expected = 8_503 * 0.11
        assert result == pytest.approx(expected, rel=0.01)

    def test_additional_income_zero(self):
        # Adding zero should result in zero additional tax
        result = calculate_tax_on_additional_income(50_000, 0)
        assert result == pytest.approx(0.0)

    def test_additional_income_into_highest_bracket(self):
        # Base income €170,000, add €20,000 → total €190,000 (into 45% bracket)
        result = calculate_tax_on_additional_income(170_000, 20_000)
        # First €10,294 at 41%, remaining €9,706 at 45%
        expected = (10_294 * 0.41) + (9_706 * 0.45)
        assert result == pytest.approx(expected, rel=0.01)

    def test_vs_flat_rate_comparison(self):
        # Demonstrate that progressive calculation differs from flat TMI
        base_income = 25_000  # TMI would be 11%
        additional = 10_000

        # Progressive calculation (correct)
        progressive_tax = calculate_tax_on_additional_income(base_income, additional)

        # Flat TMI calculation (incorrect - overstates)
        tmi = get_marginal_tax_rate(base_income + additional)  # Would be 30%
        flat_tax = additional * tmi  # 10,000 * 30% = 3,000

        # Progressive should be LESS than flat TMI approach
        assert progressive_tax < flat_tax


class TestCurrencyConversion:
    """Tests for convert_usd_to_eur function."""

    def test_standard_conversion(self):
        assert convert_usd_to_eur(100.0, 0.92) == pytest.approx(92.0)

    def test_zero_amount(self):
        assert convert_usd_to_eur(0.0, 0.92) == 0.0

    def test_one_to_one_rate(self):
        assert convert_usd_to_eur(150.0, 1.0) == 150.0

    def test_large_amount(self):
        assert convert_usd_to_eur(10000.0, 0.85) == pytest.approx(8500.0)


class TestGrossProceeed:
    """Tests for calculate_gross_proceed function."""

    def test_standard_calculation(self):
        assert calculate_gross_proceed(10, 138.0) == pytest.approx(1380.0)

    def test_single_share(self):
        assert calculate_gross_proceed(1, 200.0) == pytest.approx(200.0)

    def test_many_shares(self):
        assert calculate_gross_proceed(100, 150.0) == pytest.approx(15000.0)


class TestAcquisitionGain:
    """Tests for calculate_acquisition_gain function."""

    def test_standard_calculation(self):
        assert calculate_acquisition_gain(10, 100.0) == pytest.approx(1000.0)

    def test_single_share(self):
        assert calculate_acquisition_gain(1, 250.0) == pytest.approx(250.0)


class TestAcquisitionGainAfterRelief:
    """Tests for calculate_acquisition_gain_after_relief function."""

    def test_no_relief(self):
        result = calculate_acquisition_gain_after_relief(1000.0, 0.0)
        assert result == pytest.approx(1000.0)

    def test_fifty_percent_relief(self):
        result = calculate_acquisition_gain_after_relief(1000.0, 0.5)
        assert result == pytest.approx(500.0)

    def test_sixty_five_percent_relief(self):
        result = calculate_acquisition_gain_after_relief(1000.0, 0.65)
        assert result == pytest.approx(350.0)

    def test_zero_gain(self):
        result = calculate_acquisition_gain_after_relief(0.0, 0.5)
        assert result == pytest.approx(0.0)


class TestCapitalGain:
    """Tests for calculate_capital_gain function."""

    def test_positive_gain(self):
        result = calculate_capital_gain(1500.0, 1000.0)
        assert result == pytest.approx(500.0)

    def test_negative_gain_loss(self):
        result = calculate_capital_gain(800.0, 1000.0)
        assert result == pytest.approx(-200.0)

    def test_zero_gain(self):
        result = calculate_capital_gain(1000.0, 1000.0)
        assert result == pytest.approx(0.0)


class TestAcquisitionSocialSecurity:
    """Tests for calculate_acquisition_social_security function."""

    def test_macron_i_rate(self):
        result = calculate_acquisition_social_security(1000.0, TaxRegime.MACRON_I)
        assert result == pytest.approx(172.0)

    def test_macron_iii_under_threshold(self):
        result = calculate_acquisition_social_security(
            1000.0, TaxRegime.MACRON_III, acquisition_gain=100_000
        )
        assert result == pytest.approx(172.0)

    def test_macron_iii_over_threshold(self):
        result = calculate_acquisition_social_security(
            1000.0, TaxRegime.MACRON_III, acquisition_gain=400_000
        )
        assert result == pytest.approx(97.0)  # 9.7% activity rate

    def test_unrestricted_rate(self):
        result = calculate_acquisition_social_security(1000.0, TaxRegime.UNRESTRICTED)
        assert result == pytest.approx(97.0)  # 9.7% activity rate


class TestAcquisitionIncomeTax:
    """Tests for calculate_acquisition_income_tax function."""

    def test_flat_rate(self):
        result = calculate_acquisition_income_tax(1000.0, tax_rate=0.30)
        assert result == pytest.approx(300.0)

    def test_zero_gain_flat(self):
        result = calculate_acquisition_income_tax(0.0, tax_rate=0.30)
        assert result == pytest.approx(0.0)

    def test_custom_flat_rate(self):
        result = calculate_acquisition_income_tax(1000.0, tax_rate=0.41)
        assert result == pytest.approx(410.0)

    def test_highest_flat_rate(self):
        result = calculate_acquisition_income_tax(1000.0, tax_rate=0.45)
        assert result == pytest.approx(450.0)

    def test_progressive_with_annual_income(self):
        # Base income €50,000, gain €10,000 - all in 30% bracket
        result = calculate_acquisition_income_tax(10_000, annual_income=50_000)
        assert result == pytest.approx(3_000, rel=0.01)

    def test_progressive_spanning_brackets(self):
        # Base income €25,000, gain €10,000 - spans 11% and 30% brackets
        result = calculate_acquisition_income_tax(10_000, annual_income=25_000)
        # Progressive tax should be less than 30% flat rate
        assert result < 3_000
        assert result > 0

    def test_progressive_from_zero_income(self):
        # Base income €0, gain €20,000
        result = calculate_acquisition_income_tax(20_000, annual_income=0)
        # €0-€11,497 at 0% + €11,497-€20,000 at 11%
        expected = 8_503 * 0.11
        assert result == pytest.approx(expected, rel=0.01)

    def test_default_when_no_params(self):
        # When neither annual_income nor tax_rate provided, default to 30%
        result = calculate_acquisition_income_tax(1000.0)
        assert result == pytest.approx(300.0)


class TestCapitalGainTax:
    """Tests for calculate_capital_gain_tax function (PFU 30%)."""

    def test_positive_gain(self):
        # Capital gain is taxed at flat 30% PFU rate
        result = calculate_capital_gain_tax(500.0)
        assert result == pytest.approx(150.0)  # 500 * 0.30 = 150

    def test_negative_gain_no_tax(self):
        result = calculate_capital_gain_tax(-200.0)
        assert result == pytest.approx(0.0)

    def test_zero_gain(self):
        result = calculate_capital_gain_tax(0.0)
        assert result == pytest.approx(0.0)

    def test_pfu_rate_applied(self):
        # Verify flat 30% PFU rate is used
        result = calculate_capital_gain_tax(1000.0)
        assert result == pytest.approx(300.0)  # 1000 * 0.30 = 300


class TestSalarialeContribution:
    """Tests for calculate_salariale_contribution function."""

    def test_macron_i_no_contribution(self):
        result = calculate_salariale_contribution(500_000, TaxRegime.MACRON_I)
        assert result == pytest.approx(0.0)

    def test_macron_iii_under_threshold_no_contribution(self):
        result = calculate_salariale_contribution(100_000, TaxRegime.MACRON_III)
        assert result == pytest.approx(0.0)

    def test_macron_iii_at_threshold_no_contribution(self):
        result = calculate_salariale_contribution(
            MACRON_III_THRESHOLD, TaxRegime.MACRON_III
        )
        assert result == pytest.approx(0.0)

    def test_macron_iii_over_threshold_10_percent(self):
        result = calculate_salariale_contribution(400_000, TaxRegime.MACRON_III)
        assert result == pytest.approx(40_000.0)

    def test_unrestricted_no_contribution(self):
        result = calculate_salariale_contribution(500_000, TaxRegime.UNRESTRICTED)
        assert result == pytest.approx(0.0)


class TestTotalTaxes:
    """Tests for calculate_total_taxes function."""

    def test_sum_all_taxes(self):
        result = calculate_total_taxes(172.0, 300.0, 150.0, 0.0)
        assert result == pytest.approx(622.0)

    def test_with_salariale_contribution(self):
        result = calculate_total_taxes(172.0, 300.0, 150.0, 40_000.0)
        assert result == pytest.approx(40_622.0)

    def test_with_zero_capital_gain_tax(self):
        result = calculate_total_taxes(172.0, 300.0, 0.0, 0.0)
        assert result == pytest.approx(472.0)


class TestNetInPocket:
    """Tests for calculate_net_in_pocket function."""

    def test_standard_calculation(self):
        result = calculate_net_in_pocket(1500.0, 622.0)
        assert result == pytest.approx(878.0)

    def test_high_taxes(self):
        result = calculate_net_in_pocket(1000.0, 800.0)
        assert result == pytest.approx(200.0)


class TestEffectiveTaxRate:
    """Tests for calculate_effective_tax_rate function."""

    def test_standard_calculation(self):
        result = calculate_effective_tax_rate(300.0, 1000.0)
        assert result == pytest.approx(30.0)

    def test_zero_gross_proceed(self):
        result = calculate_effective_tax_rate(100.0, 0.0)
        assert result == pytest.approx(0.0)

    def test_fifty_percent_rate(self):
        result = calculate_effective_tax_rate(500.0, 1000.0)
        assert result == pytest.approx(50.0)


class TestRegimeNotes:
    """Tests for get_regime_notes function."""

    def test_macron_i_no_relief(self):
        notes = get_regime_notes(TaxRegime.MACRON_I, 1.0, 1000.0, 0.0)
        assert "No abatement" in notes
        assert "need" in notes.lower()

    def test_macron_i_50_percent(self):
        notes = get_regime_notes(TaxRegime.MACRON_I, 3.0, 1000.0, 0.5)
        assert "50%" in notes
        assert "2-8 years" in notes

    def test_macron_i_65_percent(self):
        notes = get_regime_notes(TaxRegime.MACRON_I, 10.0, 1000.0, 0.65)
        assert "65%" in notes
        assert "8+ years" in notes

    def test_macron_iii_under_threshold(self):
        notes = get_regime_notes(TaxRegime.MACRON_III, 1.0, 100_000, 0.5)
        assert "50%" in notes
        assert "under" in notes.lower()

    def test_macron_iii_over_threshold(self):
        notes = get_regime_notes(TaxRegime.MACRON_III, 1.0, 400_000, 0.0)
        assert "300k" in notes.lower() or "300,000" in notes
        assert "10%" in notes

    def test_unrestricted(self):
        notes = get_regime_notes(TaxRegime.UNRESTRICTED, 5.0, 1000.0, 0.0)
        assert "No abatement" in notes
        assert "salary" in notes.lower()


class TestFullCalculationMacronI:
    """Integration tests for calculate_rsu_taxes with Macron I regime."""

    def test_macron_i_no_relief(self):
        """Test Macron I with less than 2 years holding (no relief)."""
        input_data = RSUInput(
            vesting_date=date(2024, 1, 1),
            sell_date=date(2025, 1, 1),  # 1 year
            num_shares=10,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=0.92,
            acquisition_tax_rate=0.30,
            regime=TaxRegime.MACRON_I,
        )

        result = calculate_rsu_taxes(input_data)

        assert result.regime == TaxRegime.MACRON_I
        assert result.has_taper_relief is False
        assert result.taper_relief_rate == 0.0
        assert result.acquisition_gain_after_relief == result.acquisition_gain
        assert result.salariale_contribution == 0.0

    def test_macron_i_50_percent_relief(self):
        """Test Macron I with 2-8 years holding (50% relief)."""
        input_data = RSUInput(
            vesting_date=date(2022, 1, 1),
            sell_date=date(2024, 6, 1),  # ~2.4 years
            num_shares=10,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=0.92,
            acquisition_tax_rate=0.30,
            regime=TaxRegime.MACRON_I,
        )

        result = calculate_rsu_taxes(input_data)

        assert result.has_taper_relief is True
        assert result.taper_relief_rate == 0.5
        assert result.acquisition_gain_after_relief == pytest.approx(
            result.acquisition_gain * 0.5
        )

    def test_macron_i_65_percent_relief(self):
        """Test Macron I with 8+ years holding (65% relief)."""
        input_data = RSUInput(
            vesting_date=date(2015, 1, 1),
            sell_date=date(2024, 1, 1),  # 9 years
            num_shares=10,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=0.92,
            acquisition_tax_rate=0.30,
            regime=TaxRegime.MACRON_I,
        )

        result = calculate_rsu_taxes(input_data)

        assert result.has_taper_relief is True
        assert result.taper_relief_rate == 0.65
        assert result.acquisition_gain_after_relief == pytest.approx(
            result.acquisition_gain * 0.35
        )


class TestFullCalculationMacronIII:
    """Integration tests for calculate_rsu_taxes with Macron III regime."""

    def test_macron_iii_under_threshold(self):
        """Test Macron III with gain under €300k threshold."""
        input_data = RSUInput(
            vesting_date=date(2024, 1, 1),
            sell_date=date(2025, 1, 1),
            num_shares=10,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=0.92,
            acquisition_tax_rate=0.30,
            regime=TaxRegime.MACRON_III,
        )

        result = calculate_rsu_taxes(input_data)

        assert result.regime == TaxRegime.MACRON_III
        assert result.has_taper_relief is True
        assert result.taper_relief_rate == 0.5
        assert result.salariale_contribution == 0.0
        # Social security on acquisition gain at patrimony rate (17.2%)
        assert result.acquisition_social_security == pytest.approx(
            result.acquisition_gain_after_relief * 0.172
        )

    def test_macron_iii_over_threshold(self):
        """Test Macron III with gain over €300k threshold."""
        input_data = RSUInput(
            vesting_date=date(2024, 1, 1),
            sell_date=date(2025, 1, 1),
            num_shares=5000,  # Large number to exceed threshold
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=0.92,
            acquisition_tax_rate=0.30,
            regime=TaxRegime.MACRON_III,
        )

        result = calculate_rsu_taxes(input_data)

        assert result.acquisition_gain > MACRON_III_THRESHOLD
        assert result.has_taper_relief is False
        assert result.taper_relief_rate == 0.0
        assert result.salariale_contribution == pytest.approx(
            result.acquisition_gain * 0.10
        )
        # Social security on acquisition gain at activity rate (9.7%)
        assert result.acquisition_social_security == pytest.approx(
            result.acquisition_gain_after_relief * 0.097
        )


class TestFullCalculationUnrestricted:
    """Integration tests for calculate_rsu_taxes with Unrestricted regime."""

    def test_unrestricted_no_relief(self):
        """Test Unrestricted regime - no relief regardless of holding period."""
        input_data = RSUInput(
            vesting_date=date(2020, 1, 1),
            sell_date=date(2025, 1, 1),  # 5 years
            num_shares=10,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=0.92,
            acquisition_tax_rate=0.30,
            regime=TaxRegime.UNRESTRICTED,
        )

        result = calculate_rsu_taxes(input_data)

        assert result.regime == TaxRegime.UNRESTRICTED
        assert result.has_taper_relief is False
        assert result.taper_relief_rate == 0.0
        assert result.acquisition_gain_after_relief == result.acquisition_gain
        assert result.salariale_contribution == 0.0
        # Social security on acquisition gain at activity rate (9.7%)
        assert result.acquisition_social_security == pytest.approx(
            result.acquisition_gain_after_relief * 0.097
        )


class TestFullCalculationWithCapitalLoss:
    """Tests for scenarios with capital loss."""

    def test_capital_loss_macron_i(self):
        """Test scenario where current value is lower than vesting value."""
        input_data = RSUInput(
            vesting_date=date(2022, 1, 1),
            sell_date=date(2025, 1, 1),  # 3 years - qualifies for 50% relief
            num_shares=10,
            vesting_value_usd=150.0,  # Higher vesting value
            current_value_usd=100.0,  # Lower current value = loss
            usd_to_eur=0.92,
            acquisition_tax_rate=0.30,
            regime=TaxRegime.MACRON_I,
        )

        result = calculate_rsu_taxes(input_data)

        assert result.capital_gain < 0
        assert result.capital_gain_tax == 0.0
        # Still have taper relief on acquisition gain
        assert result.has_taper_relief is True
        assert result.taper_relief_rate == 0.5


class TestSeparateTaxation:
    """Tests to verify acquisition and capital gains are taxed separately."""

    def test_acquisition_social_security_on_relief_amount(self):
        """Verify social security is calculated on acquisition gain after relief."""
        input_data = RSUInput(
            vesting_date=date(2022, 1, 1),
            sell_date=date(2025, 1, 1),  # 3 years - 50% relief
            num_shares=100,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=1.0,
            acquisition_tax_rate=0.30,
            regime=TaxRegime.MACRON_I,
        )

        result = calculate_rsu_taxes(input_data)

        # Acquisition gain: 100 * 100 = 10,000
        # After 50% relief: 5,000
        # Social security (17.2%): 5,000 * 0.172 = 860
        assert result.acquisition_gain == pytest.approx(10_000)
        assert result.acquisition_gain_after_relief == pytest.approx(5_000)
        assert result.acquisition_social_security == pytest.approx(860)

    def test_capital_gain_taxed_at_pfu(self):
        """Verify capital gain is taxed at flat 30% PFU."""
        input_data = RSUInput(
            vesting_date=date(2022, 1, 1),
            sell_date=date(2025, 1, 1),
            num_shares=100,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=1.0,
            acquisition_tax_rate=0.30,
            regime=TaxRegime.MACRON_I,
        )

        result = calculate_rsu_taxes(input_data)

        # Capital gain: (100 * 150) - (100 * 100) = 5,000
        # PFU (30%): 5,000 * 0.30 = 1,500
        assert result.capital_gain == pytest.approx(5_000)
        assert result.capital_gain_tax == pytest.approx(1_500)


class TestFullCalculationWithProgressiveTax:
    """Tests for calculate_rsu_taxes using progressive tax (annual_income)."""

    def test_progressive_tax_in_same_bracket(self):
        """Test with annual income that puts gain fully in one bracket."""
        input_data = RSUInput(
            vesting_date=date(2024, 1, 1),
            sell_date=date(2025, 1, 1),
            num_shares=100,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=1.0,
            regime=TaxRegime.MACRON_I,
            annual_income=50_000,  # 30% bracket
        )

        result = calculate_rsu_taxes(input_data)

        # Acquisition gain: 100 * 100 = 10,000 (no relief - under 2 years)
        # At €50,000 income, adding €10,000 stays in 30% bracket
        # So tax should be approximately 10,000 * 0.30 = 3,000
        assert result.acquisition_income_tax == pytest.approx(3_000, rel=0.01)

    def test_progressive_tax_spanning_brackets(self):
        """Test with annual income that causes gain to span brackets."""
        input_data = RSUInput(
            vesting_date=date(2024, 1, 1),
            sell_date=date(2025, 1, 1),
            num_shares=100,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=1.0,
            regime=TaxRegime.MACRON_I,
            annual_income=25_000,  # Near boundary of 11%/30% brackets
        )

        result = calculate_rsu_taxes(input_data)

        # Progressive tax should be LESS than flat 30% rate on €10,000
        flat_rate_tax = 10_000 * 0.30  # 3,000
        assert result.acquisition_income_tax < flat_rate_tax

    def test_progressive_with_taper_relief(self):
        """Test progressive tax with 50% taper relief applied."""
        input_data = RSUInput(
            vesting_date=date(2022, 1, 1),
            sell_date=date(2025, 1, 1),  # 3 years - 50% relief
            num_shares=100,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=1.0,
            regime=TaxRegime.MACRON_I,
            annual_income=50_000,
        )

        result = calculate_rsu_taxes(input_data)

        # Acquisition gain: 10,000, after 50% relief: 5,000
        # At €50,000 income, adding €5,000 stays in 30% bracket
        assert result.acquisition_gain == pytest.approx(10_000)
        assert result.acquisition_gain_after_relief == pytest.approx(5_000)
        assert result.acquisition_income_tax == pytest.approx(1_500, rel=0.01)

    def test_flat_rate_fallback(self):
        """Test that flat rate is used when annual_income not provided."""
        input_data = RSUInput(
            vesting_date=date(2024, 1, 1),
            sell_date=date(2025, 1, 1),
            num_shares=100,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=1.0,
            regime=TaxRegime.MACRON_I,
            acquisition_tax_rate=0.30,  # Flat rate
        )

        result = calculate_rsu_taxes(input_data)

        # Should use flat 30% rate
        assert result.acquisition_income_tax == pytest.approx(10_000 * 0.30)


class TestEdgeCases:
    """Edge case tests."""

    def test_single_share(self):
        input_data = RSUInput(
            vesting_date=date(2024, 1, 1),
            sell_date=date(2025, 1, 1),
            num_shares=1,
            vesting_value_usd=500.0,
            current_value_usd=600.0,
            usd_to_eur=0.90,
            regime=TaxRegime.MACRON_I,
        )

        result = calculate_rsu_taxes(input_data)
        assert result.gross_proceed == pytest.approx(540.0)
        assert result.acquisition_gain == pytest.approx(450.0)

    def test_same_day_sell(self):
        """Test scenario where sell date equals vesting date."""
        input_data = RSUInput(
            vesting_date=date(2024, 1, 1),
            sell_date=date(2024, 1, 1),
            num_shares=10,
            vesting_value_usd=100.0,
            current_value_usd=100.0,
            usd_to_eur=1.0,
            regime=TaxRegime.MACRON_I,
        )

        result = calculate_rsu_taxes(input_data)

        assert result.years_held == pytest.approx(0.0, abs=0.01)
        assert result.has_taper_relief is False
        assert result.capital_gain == pytest.approx(0.0)

    def test_exactly_at_macron_iii_threshold(self):
        """Test Macron III exactly at the €300k threshold."""
        # Calculate shares needed to hit exactly €300k
        vesting_value_eur = 100.0 * 1.0  # $100 at 1.0 rate = €100
        num_shares = int(MACRON_III_THRESHOLD / vesting_value_eur)

        input_data = RSUInput(
            vesting_date=date(2024, 1, 1),
            sell_date=date(2025, 1, 1),
            num_shares=num_shares,
            vesting_value_usd=100.0,
            current_value_usd=150.0,
            usd_to_eur=1.0,
            regime=TaxRegime.MACRON_III,
        )

        result = calculate_rsu_taxes(input_data)

        # At exactly threshold, should still get relief
        assert result.acquisition_gain == MACRON_III_THRESHOLD
        assert result.has_taper_relief is True
        assert result.salariale_contribution == 0.0
