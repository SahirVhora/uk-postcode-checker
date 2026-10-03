from pipeline.matching import best_match, match_method, normalise


def sale(paon, street, saon=""):
    return {"paon": paon, "saon": saon, "street": street}


def epc(cert, a1, a2=None, date="2023-01-01"):
    return {"cert_number": cert, "address1": a1, "address2": a2, "address3": None, "registration_date": date}


def test_normalise():
    assert normalise("Flat 9, Bronte Ct.") == "9 BRONTE COURT"
    assert normalise("37  Bronte Farm Rd") == "37 BRONTE FARM ROAD"
    assert normalise("Smith & Sons") == "SMITH AND SONS"


def test_house_number_exact():
    assert match_method(sale("37", "BRONTE FARM ROAD"), epc("c", "37 Bronte Farm Road")) == "exact"
    assert match_method(sale("37", "BRONTE FARM ROAD"), epc("c", "37, Bronte Farm Rd")) == "exact"
    assert match_method(sale("37", "BRONTE FARM ROAD"), epc("c", "137 Bronte Farm Road")) is None


def test_flat_in_named_building():
    s = sale("BRONTE COURT", "BELLAMY FARM ROAD", saon="FLAT 9")
    assert match_method(s, epc("c", "Flat 9, Bronte Court", "Bellamy Farm Road")) == "exact"
    assert match_method(s, epc("c", "Flat 19, Bronte Court", "Bellamy Farm Road")) is None


def test_extra_number_guard():
    # A house at number 1 must not match flat 1 in number 10.
    assert match_method(sale("1", "HIGH STREET"), epc("c", "Flat 1", "10 High Street")) is None


def test_best_match_prefers_latest_certificate():
    s = sale("37", "BRONTE FARM ROAD")
    got = best_match(s, [epc("old", "37 Bronte Farm Road", date="2015-01-01"),
                         epc("new", "37 Bronte Farm Road", date="2024-01-01"),
                         epc("other", "39 Bronte Farm Road", date="2025-01-01")])
    assert got == ("new", "exact")
    assert best_match(s, []) is None
