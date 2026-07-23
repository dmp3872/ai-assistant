"""Vendor allowlist + new-sale routing, pinned against real inbox shapes."""
from app.classifiers import vendors
from app.classifiers.sales_filter import classify_gmail, is_new_sale, is_commission
from app.models import NormalizedItem


def _gmail(handle, subject, body):
    it = NormalizedItem(source="gmail", source_id=handle, author_handle=handle,
                        title=subject, body=body)
    it.body_clean = body
    return it


def test_vendor_domain_match():
    assert vendors.match(handle="support@ezpeptides.com") == "EZ Peptides"
    assert vendors.match(handle="nova@hello.novapeptidesupply.com") == "Nova Peptides"
    assert vendors.match(handle="cs@southernaminos.com") == "Southern Aminos"
    # not on the allowlist
    assert vendors.match(handle="info@trivialbioworks.com") is None
    assert vendors.match(handle="krispykreme@em.krispykreme.com") is None


def test_vendor_name_match_fallback():
    assert vendors.match(handle="x@unknown.com", subject="Valor Peptides weekly") == "Valor Peptides"


def test_new_sales_from_allowlisted_vendors_go_to_sales():
    for h, s, b in [
        ("nova@hello.novapeptidesupply.com", "Your Next Step", "15% OFF is active!"),
        ("support@valorpeptides.com", "Peptides of the week", "FLAT 30% OFF"),
        ("support@ezpeptides.com", "Save 35% on Everything", "entire store seven days"),
        ("news@instantpeptides.com", "Buy 3 Get 1 Free", "mix and match the whole store"),
        ("affiliates@peptira.com", "45% off sale EXTENDED", "35% Sitewide plus 10% code"),
        ("noreply@disguisedalpha.com", "Three new releases", "R60, Wolverine+ and Cerebrolysin"),
    ]:
        assert classify_gmail(_gmail(h, s, b))["category"] == "peptideprice_sales", h


def test_commission_notices_go_to_work_not_sales():
    r = classify_gmail(_gmail("felix@felix-mail.com",
                              "new order from your referral", "Commission earned $4.50"))
    assert r["category"] == "email_work" and r["spam"] is False
    r2 = classify_gmail(_gmail("cs@southernaminos.com",
                               "You have made a new referral sale!", "unpaid commission"))
    assert r2["category"] == "email_work"


def test_cart_and_browse_nudges_filtered():
    for h, s, b in [
        ("noreply@modernresearchpeptides.net", "Your cart misses you!", "items left in your cart"),
        ("noreply@kimerachems.co", "Did something catch your eye?", "Take another look"),
    ]:
        r = classify_gmail(_gmail(h, s, b))
        assert r["category"] == "newsletter_spam" and r["spam"] is True, h


def test_non_allowlisted_marketing_filtered():
    assert classify_gmail(_gmail("info@trivialbioworks.com", "Ipamorelin 20% off", "sale"))["spam"] is True
    assert classify_gmail(_gmail("krispykreme@em.krispykreme.com", "Blueberry fans", "buy a dozen"))["spam"] is True


def test_own_roundup_is_content():
    assert classify_gmail(_gmail("derek@peptideprice.store", "July 23 Sales Update",
                                 "49% off Flawless")) ["category"] == "content"


def test_personal_correspondence():
    r = classify_gmail(_gmail("notifications@hily.com", "Someone Reacted to Your Profile",
                              "like back through the app"))
    assert r["category"] == "email_personal"
