"""Verify data_service loads and normalizes all 150 cases."""
from caso03.domain.models import CompensationCase
from caso03.services.data_service import load_cases


def test_loads_150_cases():
    cases = load_cases()
    assert len(cases) == 150
    assert all(isinstance(c, CompensationCase) for c in cases)


def test_ids_are_unique_and_complete():
    cases = load_cases()
    ids = [c.caso_id for c in cases]
    assert len(set(ids)) == 150
    assert all(c.caso_id.startswith("COMP-") for c in cases)


def test_encoding_is_normalized():
    """The real string is valid Unicode and should not contain replacement chars."""
    gps_vals = {c.entrega_confirmada_gps for c in load_cases()}
    assert "Señal perdida" in gps_vals
    assert "SÍ - confirmada" in gps_vals
    assert not any("�" in v for v in gps_vals)


def test_requested_compensation_never_exceeds_order_value():
    """Key invariant: requested compensation never exceeds the order value."""
    cases = load_cases()
    assert all(
        c.compensacion_solicitada_mxn <= c.valor_orden_mxn for c in cases
    )
