"""Tests for Pydantic extraction model contract (EXT-06 + D-08)."""
from app.models.extraction import ExtractedInvoice, LineItem, TipoComprobante


def test_all_optional():
    """EXT-06: ExtractedInvoice can be instantiated with no arguments (all fields None)."""
    invoice = ExtractedInvoice()
    assert invoice.tipo_comprobante is None
    assert invoice.numero_documento is None
    assert invoice.proveedor is None
    assert invoice.fecha is None
    assert invoice.cuit_proveedor is None
    assert invoice.cae is None
    assert invoice.fecha_vencimiento_cae is None
    assert invoice.line_items == []


def test_unknown_enum():
    """D-08: TipoComprobante.UNKNOWN is valid; use_enum_values=True serializes to string."""
    assert TipoComprobante.UNKNOWN.value == "UNKNOWN"

    # With use_enum_values=True, the field value is stored as the string, not the enum object
    invoice = ExtractedInvoice(tipo_comprobante=TipoComprobante.UNKNOWN)
    assert invoice.tipo_comprobante == "UNKNOWN"


def test_line_item_optional():
    """EXT-06: LineItem can be instantiated with no arguments (all fields None)."""
    item = LineItem()
    assert item.descripcion is None
    assert item.codigo_sku is None
    assert item.bultos is None
    assert item.unidades_por_bulto is None
    assert item.precio_unitario_sin_iva is None
    assert item.descuento_pct is None
    assert item.iva_rate is None
    assert item.percepciones_iibb is None
