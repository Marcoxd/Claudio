from decimal import Decimal

from app.money import D, prorate, split_evenly, total


def test_split_evenly_no_pierde_centavos():
    for amount, parts in [("10.00", 3), ("0.05", 3), ("99.99", 7), ("100.00", 4)]:
        shares = split_evenly(D(amount), parts)
        assert len(shares) == parts
        assert total(shares) == D(amount)


def test_split_evenly_reparte_el_resto_a_los_primeros():
    assert split_evenly(D("10.00"), 3) == [D("3.34"), D("3.33"), D("3.33")]


def test_prorate_cuadra_el_total():
    shares = prorate(D("15.00"), [D("10"), D("20"), D("70")])
    assert total(shares) == D("15.00")
    assert shares[2] > shares[1] > shares[0]


def test_prorate_con_pesos_en_cero_reparte_igual():
    assert total(prorate(D("9.00"), [D(0), D(0), D(0)])) == D("9.00")


def test_decimal_desde_coma():
    assert D("12,50") == Decimal("12.50")
