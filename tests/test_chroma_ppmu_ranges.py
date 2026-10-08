import io

import pytest

from program_gen.platforms.chroma.writers import Force_Judge


def test_force_voltage_promotes_pt088_ua_current_to_2ma_range():
    output = io.StringIO()

    Force_Judge(
        "uA", "TP", "0V", -263.69, 0, "FORCE", "PPMU",
        -303.24, -224.14, output,
    )

    assert output.getvalue() == "  FORCE_V_PPMU(TP, 0V, ,@2mA, , 2mS);\n"


def test_force_voltage_range_covers_judgement_limits_not_only_target():
    output = io.StringIO()

    Force_Judge(
        "uA", "TP", "0V", 190, 0, "FORCE", "PPMU",
        150, 250, output,
    )

    assert output.getvalue() == "  FORCE_V_PPMU(TP, 0V, ,@2mA, , 2mS);\n"


@pytest.mark.parametrize(
    ("unit", "target", "low", "high"),
    [
        ("nA", -263690, -303240, -224140),
        ("uA", -263.69, -303.24, -224.14),
        ("mA", -0.26369, -0.30324, -0.22414),
    ],
)
def test_equivalent_current_units_select_the_same_ppmu_range(unit, target, low, high):
    output = io.StringIO()

    Force_Judge(unit, "TP", "0V", target, 0, "FORCE", "PPMU", low, high, output)

    assert "@2mA" in output.getvalue()


def test_force_current_uses_the_same_cross_unit_range_selection():
    output = io.StringIO()

    Force_Judge("V", "PA0", "263.69uA", 1.2, 0, "FORCE", "PPMU", 1.1, 1.3, output)

    assert output.getvalue() == "  FORCE_I_PPMU(PA0, 263.69uA, @2mA, ,6V, -2V ,3mS);\n"


def test_current_above_32ma_is_rejected():
    with pytest.raises(ValueError, match="32mA"):
        Force_Judge(
            "mA", "TP", "0V", 33, 0, "FORCE", "PPMU",
            30, 35, io.StringIO(),
        )


@pytest.mark.parametrize(
    ("current_ua", "expected_range"),
    [
        (1.9, "@2uA"),
        (2, "@20uA"),
        (20, "@200uA"),
        (200, "@2mA"),
        (2000, "@32mA"),
        (31999, "@32mA"),
    ],
)
def test_ppmu_current_range_boundaries(current_ua, expected_range):
    output = io.StringIO()

    Force_Judge(
        "uA", "TP", "0V", current_ua, 0, "FORCE", "PPMU",
        current_ua, current_ua, output,
    )

    assert expected_range in output.getvalue()
