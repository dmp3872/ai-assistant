from app.models import NormalizedItem, SalesFields


def test_hash_stable_across_whitespace_and_case():
    a = NormalizedItem(source="skool", source_id="1", body="Hello   World")
    b = NormalizedItem(source="skool", source_id="2", body="hello world")
    assert a.compute_hash() == b.compute_hash()


def test_hash_differs_by_source():
    a = NormalizedItem(source="skool", source_id="1", body="same")
    b = NormalizedItem(source="gmail", source_id="1", body="same")
    assert a.compute_hash() != b.compute_hash()


def test_sales_fields_defaults():
    f = SalesFields(vendor="Acme", discount="20%")
    assert f.vendor == "Acme"
    assert f.confidence == "low"
    assert f.coupon_code is None
