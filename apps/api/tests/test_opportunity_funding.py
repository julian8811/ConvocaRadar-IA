"""Funding parser 022: COP inference, tr filter, R$/€/USD, 18e9."""
import pytest
from app.services.opportunity import _parse_funding_amount, _is_tr_artifact
def test_tr_artifact():
    assert _is_tr_artifact("tr") and _is_tr_artifact("TR") and _is_tr_artifact(" td ")
    assert not _is_tr_artifact("$980.000.000") and not _is_tr_artifact(None)
def test_tr_filtered(): assert _parse_funding_amount("tr")== (None,None) and _parse_funding_amount("  TR  ")[0] is None
@pytest.mark.parametrize("raw,country,url,exp_val,exp_cur",[
    ("$980.000.000","Colombia",None,980000000.0,"COP"),("$980.000.000",None,"https://fondoemprender.sena.edu.co/foo",980000000.0,"COP"),
    ("$1.234.567,50","Colombia",None,1234567.5,"COP"),("R$ 500.000,00",None,None,500000.0,"BRL"),
    ("€5.000",None,None,5000.0,"EUR"),("EUR 1.2 million",None,None,1200000.0,"EUR"),
    ("USD 1.2M",None,None,1200000.0,"USD"),("COP 5000000",None,None,5000000.0,"COP"),
    ("500.000","Colombia",None,500000.0,"COP"),("18e9","Colombia",None,18e9,"COP"),
    ("1.5e6 EUR",None,None,1500000.0,"EUR"),("$10,000 USD",None,None,10000.0,"USD"),
])
def test_funding_cases(raw,country,url,exp_val,exp_cur):
    v,c=_parse_funding_amount(raw,country=country,url=url); assert v==pytest.approx(exp_val) and c==exp_cur
def test_bare_dollar_no_context_rejected(): assert _parse_funding_amount("$500")[0] is None
def test_cap_and_empty():
    assert _parse_funding_amount("COP 2000000000000")[0] is None
    assert _parse_funding_amount(None)==(None,None) and _parse_funding_amount("Por validar")[0] is None
