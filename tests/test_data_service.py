"""Verifica que data_service carga y normaliza los 150 casos correctamente."""
from caso03.domain.models import CompensationCase
from caso03.services.data_service import load_cases


def test_carga_150_casos():
    cases = load_cases()
    assert len(cases) == 150
    assert all(isinstance(c, CompensationCase) for c in cases)


def test_ids_unicos_y_completos():
    cases = load_cases()
    ids = [c.caso_id for c in cases]
    assert len(set(ids)) == 150
    assert all(c.caso_id.startswith("COMP-") for c in cases)


def test_encoding_normalizado():
    """La cadena real es Unicode válido: 'Señal perdida' debe existir sin '�'."""
    gps_vals = {c.entrega_confirmada_gps for c in load_cases()}
    assert "Señal perdida" in gps_vals
    assert "SÍ - confirmada" in gps_vals  # ojo: Í mayúscula (U+00CD) en el dato real
    assert not any("�" in v for v in gps_vals)


def test_invariante_no_sobre_reclamo():
    """Hallazgo clave: la compensación nunca supera el valor de la orden."""
    cases = load_cases()
    assert all(
        c.compensacion_solicitada_mxn <= c.valor_orden_mxn for c in cases
    )
