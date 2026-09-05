"""
Tests unitarios de `compute_cuts` (Usage and Billing, task 12).

Verifican el cálculo de los tres cortes de un cierre mensual (Req 5.1, 5.4, 5.5):
- cutoff = 00:00 día 1 de (M+1)
- cut1   = 00:00 día 1 de (M−2)  (Caso 1, inactividad)
- cut2   = 00:00 día 1 de (M−3)  (Caso 2, abandono)

Cubren: America/Lima (sin DST), UTC, rollover de mes (diciembre → enero del año
siguiente para cutoff), rollover de año hacia atrás (enero → meses del año anterior
para cut1/cut2), y una zona con DST (Europe/Madrid) para confirmar el offset correcto
en verano e invierno. Los cortes se comparan como `datetime` naive en UTC, la
convención de almacenamiento del modelo.

_Requirements: 5.1, 5.4, 5.5_
"""

from datetime import datetime

import pytest

from app.services.billing_time import BillingCuts, compute_cuts


class TestCortesAmericaLima:
    """America/Lima es UTC−5 fijo (sin DST): la medianoche local = 05:00 UTC."""

    def test_cerrando_noviembre_ejemplo_del_requisito(self):
        # Cerrando noviembre 2025 (M=11): el requisito dice cut1 = 1 sep, cut2 = 1 ago.
        cuts = compute_cuts("America/Lima", 2025, 11)

        # cutoff = 00:00 del 1 de diciembre en Lima = 05:00 UTC del 1 de diciembre.
        assert cuts.cutoff == datetime(2025, 12, 1, 5, 0, 0)
        # cut1 = 00:00 del 1 de septiembre en Lima = 05:00 UTC.
        assert cuts.cut1 == datetime(2025, 9, 1, 5, 0, 0)
        # cut2 = 00:00 del 1 de agosto en Lima = 05:00 UTC.
        assert cuts.cut2 == datetime(2025, 8, 1, 5, 0, 0)

    def test_devuelve_namedtuple_naive(self):
        cuts = compute_cuts("America/Lima", 2025, 6)
        assert isinstance(cuts, BillingCuts)
        # Todos los cortes son naive (sin tzinfo).
        assert cuts.cutoff.tzinfo is None
        assert cuts.cut1.tzinfo is None
        assert cuts.cut2.tzinfo is None


class TestCortesUTC:
    """En UTC la medianoche local coincide con la medianoche UTC (offset 0)."""

    def test_mes_intermedio(self):
        cuts = compute_cuts("UTC", 2025, 6)  # cerrando junio
        assert cuts.cutoff == datetime(2025, 7, 1, 0, 0, 0)  # M+1 = julio
        assert cuts.cut1 == datetime(2025, 4, 1, 0, 0, 0)    # M−2 = abril
        assert cuts.cut2 == datetime(2025, 3, 1, 0, 0, 0)    # M−3 = marzo


class TestRolloverMes:
    """cutoff = M+1 debe cruzar a enero del año siguiente cuando M = diciembre."""

    def test_cerrando_diciembre_cutoff_enero_siguiente(self):
        cuts = compute_cuts("UTC", 2025, 12)  # cerrando diciembre 2025
        # cutoff = 00:00 del 1 de enero de 2026.
        assert cuts.cutoff == datetime(2026, 1, 1, 0, 0, 0)
        # cut1 = M−2 = octubre 2025, cut2 = M−3 = septiembre 2025.
        assert cuts.cut1 == datetime(2025, 10, 1, 0, 0, 0)
        assert cuts.cut2 == datetime(2025, 9, 1, 0, 0, 0)


class TestRolloverAnioHaciaAtras:
    """cut1 (M−2) y cut2 (M−3) deben cruzar al año anterior en meses tempranos."""

    def test_cerrando_enero_cortes_del_anio_anterior(self):
        cuts = compute_cuts("UTC", 2025, 1)  # cerrando enero 2025
        # cutoff = M+1 = febrero 2025.
        assert cuts.cutoff == datetime(2025, 2, 1, 0, 0, 0)
        # cut1 = M−2 = noviembre 2024.
        assert cuts.cut1 == datetime(2024, 11, 1, 0, 0, 0)
        # cut2 = M−3 = octubre 2024.
        assert cuts.cut2 == datetime(2024, 10, 1, 0, 0, 0)

    def test_cerrando_febrero_cut2_cruza_anio(self):
        cuts = compute_cuts("UTC", 2025, 2)  # cerrando febrero 2025
        assert cuts.cutoff == datetime(2025, 3, 1, 0, 0, 0)   # marzo 2025
        assert cuts.cut1 == datetime(2024, 12, 1, 0, 0, 0)    # diciembre 2024
        assert cuts.cut2 == datetime(2024, 11, 1, 0, 0, 0)    # noviembre 2024

    def test_cerrando_marzo_cut2_es_diciembre_anterior(self):
        cuts = compute_cuts("UTC", 2025, 3)  # cerrando marzo 2025
        assert cuts.cutoff == datetime(2025, 4, 1, 0, 0, 0)   # abril 2025
        assert cuts.cut1 == datetime(2025, 1, 1, 0, 0, 0)     # enero 2025
        assert cuts.cut2 == datetime(2024, 12, 1, 0, 0, 0)    # diciembre 2024


class TestZonaConDST:
    """
    Europe/Madrid usa CET (UTC+1) en invierno y CEST (UTC+2) en verano. El offset del
    corte debe reflejar el DST vigente en el mes de cada corte, no un offset fijo.
    """

    def test_cerrando_julio_mezcla_verano_e_invierno_en_los_cortes(self):
        # Cerrando julio 2025 (M=7):
        #   cutoff = 1 de agosto 2025 (verano, UTC+2) → 22:00 UTC del 31 de julio.
        #   cut1   = 1 de mayo   2025 (verano, UTC+2) → 22:00 UTC del 30 de abril.
        #   cut2   = 1 de abril  2025 (verano, UTC+2) → 22:00 UTC del 31 de marzo.
        cuts = compute_cuts("Europe/Madrid", 2025, 7)
        assert cuts.cutoff == datetime(2025, 7, 31, 22, 0, 0)
        assert cuts.cut1 == datetime(2025, 4, 30, 22, 0, 0)
        assert cuts.cut2 == datetime(2025, 3, 31, 22, 0, 0)

    def test_cerrando_febrero_cortes_en_invierno(self):
        # Cerrando febrero 2025 (M=2):
        #   cutoff = 1 de marzo    2025 (invierno, UTC+1) → 23:00 UTC del 28 de febrero.
        #   cut1   = 1 de diciembre 2024 (invierno, UTC+1) → 23:00 UTC del 30 de noviembre.
        #   cut2   = 1 de noviembre 2024 (invierno, UTC+1) → 23:00 UTC del 31 de octubre.
        cuts = compute_cuts("Europe/Madrid", 2025, 2)
        assert cuts.cutoff == datetime(2025, 2, 28, 23, 0, 0)
        assert cuts.cut1 == datetime(2024, 11, 30, 23, 0, 0)
        assert cuts.cut2 == datetime(2024, 10, 31, 23, 0, 0)

    def test_cutoff_verano_y_cut_invierno_distinto_offset(self):
        # Cerrando septiembre 2025 (M=9):
        #   cutoff = 1 de octubre 2025 (aún verano hasta el último domingo, UTC+2)
        #            → 22:00 UTC del 30 de septiembre.
        #   cut2   = 1 de junio   2025 (verano, UTC+2) → 22:00 UTC del 31 de mayo.
        # Y cerrando marzo 2025 (M=3):
        #   cut2   = 1 de diciembre 2024 (invierno, UTC+1) → 23:00 UTC del 30 de noviembre.
        verano = compute_cuts("Europe/Madrid", 2025, 9)
        assert verano.cutoff == datetime(2025, 9, 30, 22, 0, 0)
        assert verano.cut2 == datetime(2025, 5, 31, 22, 0, 0)

        invierno = compute_cuts("Europe/Madrid", 2025, 3)
        assert invierno.cut2 == datetime(2024, 11, 30, 23, 0, 0)


class TestValidacion:
    """Validación de parámetros de entrada."""

    @pytest.mark.parametrize("month", [0, 13, -1, 100])
    def test_mes_fuera_de_rango_lanza_valueerror(self, month):
        with pytest.raises(ValueError):
            compute_cuts("UTC", 2025, month)

    def test_timezone_invalida_lanza_error(self):
        from zoneinfo import ZoneInfoNotFoundError

        with pytest.raises(ZoneInfoNotFoundError):
            compute_cuts("No/Existe", 2025, 6)


class TestConsistenciaOrden:
    """Invariante estructural: cut2 < cut1 < cutoff (los cortes están ordenados)."""

    @pytest.mark.parametrize(
        "tz,year,month",
        [
            ("America/Lima", 2025, 11),
            ("UTC", 2025, 1),
            ("UTC", 2025, 12),
            ("Europe/Madrid", 2025, 7),
            ("Europe/Madrid", 2025, 2),
        ],
    )
    def test_orden_de_cortes(self, tz, year, month):
        cuts = compute_cuts(tz, year, month)
        assert cuts.cut2 < cuts.cut1 < cuts.cutoff
