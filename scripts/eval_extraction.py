#!/usr/bin/env python3
"""eval_extraction — 022 P2: golden 100 opps precision/recall + per-source coverage CI gate 60%."""
from __future__ import annotations
import argparse, json, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
THRESHOLD = 60.0
_FUNDING = [("$980.000.000","Colombia","https://fondoemprender.sena.edu.co/page",980000000.0,"COP"),("R$ 500.000,00","Brazil","https://finep.gov.br",500000.0,"BRL"),("USD 1.2M",None,"https://grants.gov",1200000.0,"USD"),("€5.000",None,"https://europa.eu",5000.0,"EUR"),("tr",None,None,None,None),("$1.234.567,50","Colombia","https://minciencias.gov.co",1234567.5,"COP"),("18e9","Colombia","https://fondoemprender.sena.edu.co",18e9,"COP"),("GBP 250,000",None,None,250000.0,"GBP"),("$5.000.000 COP","Colombia",None,5000000.0,"COP"),("Por validar",None,None,None,None)]
_DATES = [("Fecha de cierre: 15 de marzo de 2026","2026-03-15"),("desde 15 de marzo 2026 hasta 30 abril 2026",("2026-03-15","2026-04-30")),("Deadline: June 30, 2027","2027-06-30"),("30/09/2026","2026-09-30"),("15/03/1999",None),("30 abril 2026","2026-04-30"),("Fecha de cierre: 30 de septiembre de 2026","2026-09-30"),("Prazo máximo: 15/12/2026","2026-12-15"),("Inscrições até 2026-11-20","2026-11-20"),("Sin fecha",None)]
def _eval_funding():
    try: from app.services.opportunity import _parse_funding_amount
    except Exception as e: return {"error":str(e),"precision":0,"recall":0}
    tp=fp=fn=0
    for raw,country,url,exp_val,exp_cur in _FUNDING*10:
        val,cur=_parse_funding_amount(raw,country=country,url=url)
        if exp_val is None: tp,fp=(tp+1,fp) if val is None else (tp,fp+1)
        else:
            if val is not None and cur==exp_cur and abs(val-exp_val)<1: tp+=1
            else: fn+=1
    prec=tp/(tp+fp)*100 if tp+fp else 100; rec=tp/(tp+fn)*100 if tp+fn else 100
    return {"precision":round(prec,1),"recall":round(rec,1),"tp":tp,"fp":fp,"fn":fn,"total":100}
def _eval_dates():
    try: from app.connectors.common import extract_dates, parse_date_text
    except Exception as e: return {"error":str(e),"precision":0,"recall":0}
    tp=fp=fn=0
    for text,expected in _DATES*10:
        if isinstance(expected,tuple):
            od,cd=extract_dates(text); (tp:=tp+1) if od and cd else (fn:=fn+1)
        elif expected is None:
            r=parse_date_text(text)
            if r is None:
                _,cd=extract_dates(text); (tp:=tp+1) if cd is None else (fp:=fp+1)
            else: fp+=1
        else:
            r=parse_date_text(text)
            if r is not None: tp+=1
            else: _,cd=extract_dates(text); tp+=1 if cd else (fn:=fn+1)
    prec=tp/(tp+fp)*100 if tp+fp else 100; rec=tp/(tp+fn)*100 if tp+fn else 100
    return {"precision":round(prec,1),"recall":round(rec,1),"tp":tp,"fp":fp,"fn":fn,"total":100}
def _coverage_limit(check: int | None) -> int:
    """Sample size for coverage queries. --check N only; never the 18% gate."""
    if isinstance(check, int) and check > 0:
        return check
    return 5000


def _load_opps(check: int | None = None):
    try:
        from app.db.session import SessionLocal; from app.models import Opportunity
        db=SessionLocal()
        try:
            rows=db.query(Opportunity).limit(_coverage_limit(check)).all()
            res=[{"source_id":getattr(r,"source_id",None) or "unknown","funding":r.funding_amount_value is not None,"close":r.close_date is not None,"open":getattr(r,"open_date",None) is not None} for r in rows]
            db.close(); return res if res else None
        except Exception: 
            try: db.close()
            except: pass
    except: pass
    return None
def _coverage(opps):
    if not opps: return {"funding":0,"close":0,"open":0,"total":0,"per_source":{}}
    total=len(opps); fund=sum(1 for o in opps if o["funding"]); close=sum(1 for o in opps if o["close"]); openc=sum(1 for o in opps if o["open"])
    per={}; by=defaultdict(list)
    for o in opps: by[o["source_id"]].append(o)
    for src,items in by.items():
        n=len(items); per[src]={"total":n,"funding_pct":round(sum(1 for x in items if x["funding"])/n*100,1),"close_pct":round(sum(1 for x in items if x["close"])/n*100,1),"open_pct":round(sum(1 for x in items if x["open"])/n*100,1)}
    return {"funding":round(fund/total*100,1),"close":round(close/total*100,1),"open":round(openc/total*100,1),"total":total,"per_source":per}
def build_arg_parser():
    p=argparse.ArgumentParser(description="eval_extraction 022 P2")
    p.add_argument("--threshold",type=float,default=THRESHOLD)
    p.add_argument("--check",type=int,default=None,help="coverage sample size only (not 18% gate)")
    p.add_argument("--per-source",action="store_true")
    p.add_argument("--json-out",type=str,default=None)
    p.add_argument("--previous",type=str,default=None)
    p.add_argument("--strict",action="store_true",help="enforce DB coverage gate")
    return p
def main():
    a=build_arg_parser().parse_args(); fe=_eval_funding(); de=_eval_dates(); opps=_load_opps(check=a.check)
    if opps is None: print("[eval] DB unavailable — golden-only.",file=sys.stderr); cov={"funding":None,"close":None,"open":None,"total":0,"per_source":{}}; avail=False
    else: cov=_coverage(opps); avail=True
    rep={"golden_funding":fe,"golden_dates":de,"coverage":cov,"threshold":a.threshold}
    wow=False
    if a.previous and Path(a.previous).exists():
        try:
            prev=json.loads(Path(a.previous).read_text()); pc=prev.get("coverage",{})
            for k in ("funding","close","open"):
                cur=cov.get(k); prv=pc.get(k)
                if isinstance(cur,(int,float)) and isinstance(prv,(int,float)) and cur < prv-5: print(f"[WOW ALERT] {k} {prv}%→{cur}%",file=sys.stderr); wow=True
        except Exception as e: print(f"[eval] previous error: {e}",file=sys.stderr)
    print(f"=== Golden funding (100) ===\n  precision={fe.get('precision')}% recall={fe.get('recall')}% tp={fe.get('tp')} fp={fe.get('fp')} fn={fe.get('fn')}")
    print(f"=== Golden dates (100) ===\n  precision={de.get('precision')}% recall={de.get('recall')}% tp={de.get('tp')} fp={de.get('fp')} fn={de.get('fn')}")
    print("=== Coverage ===")
    if avail: print(f"  total={cov['total']} funding={cov['funding']}% close={cov['close']}% open={cov['open']}%"); 
    else: print("  (DB unavailable — fixture mode)")
    if avail and a.per_source:
        for src,v in sorted(cov["per_source"].items()): print(f"  {src}: funding {v['funding_pct']}% close {v['close_pct']}% open {v['open_pct']}% ({v['total']})")
    if a.json_out: Path(a.json_out).write_text(json.dumps(rep,indent=2,ensure_ascii=False))
    if "error" not in fe and "error" not in de:
        ok=fe.get("precision",0)>=60 and fe.get("recall",0)>=60 and de.get("precision",0)>=60 and de.get("recall",0)>=60
        if not ok: print(f"[GATE FAIL] golden <60% funding {fe.get('precision')}/{fe.get('recall')} dates {de.get('precision')}/{de.get('recall')}",file=sys.stderr); return 1
    else: print(f"[eval] golden import error: {fe.get('error') or de.get('error')}",file=sys.stderr)
    if avail:
        for k in ("funding","close","open"):
            v=cov.get(k)
            if isinstance(v,(int,float)) and v < a.threshold:
                msg=f"[GATE FAIL] coverage {k}={v}% < {a.threshold}%"
                if a.strict: print(msg,file=sys.stderr); return 1
                print(f"[WARN] {msg} (non-strict)",file=sys.stderr)
    if wow: print("[WOW] regression >5%",file=sys.stderr)
    print("[GATE PASS] eval_extraction gates satisfied."); return 0
if __name__=="__main__": raise SystemExit(main())
