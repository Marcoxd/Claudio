"""Conciliación de un estado de cuenta contra lo registrado.

Los casos salen de un estado PacifiCard real (corte 25/jul–24/ago) cruzado
contra la hoja de cálculo del mismo mes.
"""
import datetime as dt

from app.money import D
from app.services.reconcile import (
    Movimiento,
    Registro,
    conciliar,
)


def mov(dia, desc, monto, kind="consumo", **kw):
    return Movimiento(dt.date(2026, 8, dia), desc, D(monto), kind, **kw)


def reg(dia, desc, monto, kind="gasto", id=0):
    return Registro(id, dt.date(2026, 8, dia), desc, D(monto), kind)


def test_empareja_por_monto_y_nombre_parecido():
    r = conciliar(
        [mov(2, "COMERCIAL KYWI SA", "13.83")],
        [reg(2, "kiwy", "13.83")],
    )
    assert len(r.cuadran) == 1
    assert r.faltan == [] and r.sobran == []


def test_el_monto_exacto_gana_sobre_el_cercano():
    """34.68 debe emparejar con J.G. Global Color, no con la gasolinera de 34.74."""
    r = conciliar(
        [mov(2, "ESTACION DE SERVICIO E", "34.74"),
         mov(5, "J.G. GLOBAL COLOR", "34.68", kind="cuota", installment="02/03")],
        [reg(15, "Maguayer", "34.68")],
    )
    assert len(r.cuadran) == 1
    assert r.cuadran[0].movimiento.description == "J.G. GLOBAL COLOR"
    assert [m.description for m in r.faltan] == ["ESTACION DE SERVICIO E"]


def test_diferencia_de_centavos_se_reporta_sin_romper_el_emparejamiento():
    r = conciliar(
        [mov(2, "SUPER SANTAMARIA SANGO", "154.75")],
        [reg(2, "Santa Maria", "154.73")],
    )
    assert len(r.difieren) == 1
    assert r.difieren[0].diferencia == D("0.02")
    assert r.descuadre == D("0.02")


def test_diferencia_grande_no_empareja():
    """Sabai: la hoja dice 30.00 y el banco 71.50. No son lo mismo."""
    r = conciliar([mov(1, "SABAI BEER GARDEN", "71.50")], [reg(1, "Sabai", "30.00")])
    assert r.pares == []
    assert len(r.faltan) == 1 and len(r.sobran) == 1


def test_lo_que_no_registre_sale_como_faltante():
    r = conciliar(
        [mov(1, "MARCO FERNANDEZ", "40.25"), mov(3, "SUPERCINES", "18.81")],
        [],
    )
    assert len(r.faltan) == 2
    assert r.total_faltante == D("59.06")
    assert r.descuadre == D("59.06")


def test_lo_registrado_que_no_esta_en_el_estado_sale_aparte():
    """Suele ser de la otra tarjeta, o una compra posterior al corte."""
    r = conciliar([], [reg(26, "Comida playa camaron", "19.98")])
    assert len(r.sobran) == 1
    assert r.total_sobrante == D("19.98")
    assert r.descuadre == D("-19.98")


def test_los_pagos_se_separan_de_los_consumos():
    r = conciliar(
        [mov(4, "SU PAGO PAGO DIRECTO BDP", "490.74", kind="pago"),
         mov(2, "COMERCIAL KYWI SA", "13.83")],
        [reg(2, "kiwy", "13.83")],
    )
    assert len(r.pagos) == 1
    assert len(r.cuadran) == 1
    assert r.faltan == []


def test_intereses_y_cargos_no_cuentan_como_gasto_faltante():
    r = conciliar([mov(15, "INTERES FINANCIAMIENTO", "12.50", kind="interes")], [])
    assert r.faltan == [] and r.pares == []


def test_dos_montos_iguales_no_se_pisan():
    """Dos Licorsariato el mismo día: cada uno con su registro."""
    r = conciliar(
        [mov(8, "LICORSARIATO", "15.65"), mov(8, "LICORSARIATO", "29.14")],
        [reg(8, "Licor Paty", "15.65"), reg(8, "Licor Alejo", "29.14")],
    )
    assert len(r.cuadran) == 2
    montos = {p.movimiento.amount for p in r.cuadran}
    assert montos == {D("15.65"), D("29.14")}


def test_montos_repetidos_se_reparten_por_cercania_de_fecha():
    r = conciliar(
        [mov(1, "MALL DEL PACIFICO", "3.00"), mov(20, "MALL DEL PACIFICO", "3.00")],
        [reg(19, "Souvenir", "3.00")],
    )
    assert len(r.cuadran) == 1
    assert r.cuadran[0].movimiento.date == dt.date(2026, 8, 20)
    assert len(r.faltan) == 1


def test_caso_completo_de_agosto():
    """Doce filas del estado contra nueve registros de la hoja."""
    estado = [
        mov(2, "COMERCIAL KYWI SA", "13.83"),
        mov(2, "SUPER SANTAMARIA SANGO", "154.75"),
        mov(7, "RB SAN LUIS", "28.98"),
        mov(8, "CAFETERIA EN LA VIA", "6.50"),
        mov(8, "CORAL HIPERMERCADOS MO", "39.41"),
        mov(8, "LICORSARIATO", "15.65"),
        mov(9, "POOL WINGS", "41.71"),
        mov(10, "TANDAPI 1", "42.64"),
        mov(11, "LISTO MONTESERRIN", "6.85"),
        mov(15, "SUPER K SERITO", "29.00"),
        mov(1, "MARCO FERNANDEZ", "40.25"),
        mov(4, "SU PAGO PAGO DIRECTO BDP", "490.74", kind="pago"),
    ]
    hoja = [
        reg(2, "kiwy", "13.83"),
        reg(2, "Santa Maria", "154.73"),
        reg(7, "R y B ropa", "28.98"),
        reg(8, "Comida en la via", "6.50"),
        reg(8, "Coral ropa paty", "39.41"),
        reg(8, "Licor Paty", "15.65"),
        reg(9, "Comida Alitas", "41.75"),
        reg(10, "Gasolina+Aditivo", "42.64"),
        reg(11, "Listo", "6.75"),
        reg(15, "Comida hornado", "29.00"),
    ]
    r = conciliar(estado, hoja)

    assert len(r.cuadran) == 7
    assert len(r.difieren) == 3          # Santa María, Pool Wings y Listo
    assert [m.description for m in r.faltan] == ["MARCO FERNANDEZ"]
    assert r.sobran == []
    assert len(r.pagos) == 1
    assert r.revisado == 11
    # el banco cobró 40.25 que no estaban, más 0.08 neto de centavos
    # (Santa María +0.02, Pool Wings -0.04, Listo +0.10)
    assert r.descuadre == D("40.33")
