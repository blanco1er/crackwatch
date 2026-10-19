"""Owner-only report (in French) of the hosted demo: who tried it, from where, how far they went, and what
the LLM cost today. Reads the DynamoDB table with the owner's own AWS profile; there is no public page for it.
Visits of the owner's devices (private link) and of our scripts are never logged (crackwatch/visits.py).

  AWS_PROFILE=<profile> python scripts/visits_report.py                       # last 14 days
  AWS_PROFILE=<profile> python scripts/visits_report.py --depuis 2026-10-21 [--jusqu 2026-11-09] [--detail]
  AWS_PROFILE=<profile> python scripts/visits_report.py --lien-interne         # private link that excludes this browser
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

GAP_S = 30 * 60
STEP_FR = {"blurry": "photo floue", "far": "photo de loin", "close": "photo rapprochée", "visit2": "2e visite", "upload": "photo perso"}


def _t(iso):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))


def hm(iso):
    try:
        from zoneinfo import ZoneInfo
        return _t(iso).astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m %H:%M")
    except Exception:
        return iso[5:16]


def sessions(rows):
    by = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["at"]):
        lst = by[r["visitor"]]
        if not lst or (_t(r["at"]) - _t(lst[-1]["end"])).total_seconds() > GAP_S:
            lst.append({"visitor": r["visitor"], "start": r["at"], "end": r["at"], "events": [r]})
        else:
            lst[-1]["end"] = r["at"]
            lst[-1]["events"].append(r)
    return sorted((s for v in by.values() for s in v), key=lambda s: s["start"])


def dur(s):
    sec = (_t(s["end"]) - _t(s["start"])).total_seconds()
    return f"{max(1, round(sec))} s" if sec < 60 else f"{round(sec / 60)} min"


def summarize(rows, usage, d0, d1, detail=False):
    rows = [r for r in rows if not r.get("bot")]
    out = [f"CrackWatch · visites de la démo publique du {d0} au {d1} (visites internes et robots exclus)"]
    if not rows:
        out += ["", "Aucune visite externe sur la période."]
    else:
        vis = {r["visitor"] for r in rows}
        count = lambda pred: len({r["visitor"] for r in rows if pred(r)})  # noqa: E731
        out += ["", f"Visiteurs uniques : {len(vis)} · inspections lancées : {sum(r['type'] == 'inspect' for r in rows)}"]
        out += ["", "Par jour :"]
        for d in sorted({r["at"][:10] for r in rows}):
            rs = [r for r in rows if r["at"][:10] == d]
            out.append(f"  {d} : {len({r['visitor'] for r in rs})} visiteur(s), {sum(r['type'] == 'inspect' for r in rs)} inspection(s)")
        ref = {}
        for r in rows:
            if r.get("ref") and r["visitor"] not in ref:
                ref[r["visitor"]] = r["ref"]
        refs = Counter(ref.get(v, "accès direct") for v in vis)
        out += ["", "Provenance : " + " · ".join(f"{k} {n}" for k, n in refs.most_common())]
        utm = Counter(r["utm"] for r in rows if r.get("utm"))
        if utm:
            out.append("Liens suivis (utm_source) : " + " · ".join(f"{k} {n}" for k, n in utm.most_common()))
        out += ["", "Jusqu'où ils sont allés :"]
        for s in ("blurry", "far", "close", "visit2"):
            n = count(lambda r, s=s: r["type"] == "inspect" and r.get("sample") == s)
            out.append(f"  étape {STEP_FR[s]} : {n} visiteur(s)")
        out.append(f"  photo personnelle envoyée : {count(lambda r: r['type'] == 'upload')}")
        out.append(f"  ticket validé : {count(lambda r: r['type'] == 'ticket' and r.get('action') == 'approved')} · refusé : "
                   f"{count(lambda r: r['type'] == 'ticket' and r.get('action') == 'rejected')}")
        out.append(f"  carte PDF ouverte : {count(lambda r: r['type'] == 'card')} · passage en français : {count(lambda r: r['type'] == 'lang' and r.get('lang') == 'fr')}")
        dec = Counter(r.get("action") for r in rows if r["type"] == "inspect")
        out.append("  décisions de l'agent : " + " · ".join(f"{k} {n}" for k, n in dec.most_common()))
        plan = Counter("Nova 2 Lite" if "nova" in (r.get("planner") or "") else "règles" for r in rows if r["type"] == "inspect")
        out.append("  décidé par : " + " · ".join(f"{k} {n}" for k, n in plan.most_common()))
        fam = Counter()
        for v in vis:
            r = next(x for x in rows if x["visitor"] == v)
            fam[f"{r['browser']}/{r['os']}"] += 1
        out += ["", "Navigateurs : " + " · ".join(f"{k} {n}" for k, n in fam.most_common())]
        scr = Counter(r.get("screen") for r in rows if r["type"] == "view" and r.get("screen"))
        out.append("Écrans : " + " · ".join(f"{k} {n}" for k, n in scr.most_common()) if scr else "Écrans : —")
        ss = sessions(rows)
        ds = sorted((_t(s["end"]) - _t(s["start"])).total_seconds() for s in ss)
        out += ["", f"Sessions : {len(ss)} · durée médiane {round(ds[len(ds) // 2])} s · la plus longue {round(ds[-1])} s"]
        if detail:
            out += ["", "Détail par session :"]
            for s in ss:
                e0 = s["events"][0]
                out.append(f"\n  {s['visitor'][:6]} · {hm(s['start'])} · {dur(s)} · {ref.get(s['visitor'], 'accès direct')} · {e0['browser']}/{e0['os']}")
                for e in s["events"]:
                    bits = [e["type"], e.get("sample") and STEP_FR.get(e["sample"], e["sample"]), e.get("action"), e.get("lang")]
                    out.append(f"    {hm(e['at'])} " + " · ".join(b for b in bits if b))
    if usage:
        out += ["", "Consommation (compteurs du service) :"]
        for day, u in sorted(usage.items()):
            llm = u.get("llm_calls", 0)
            out.append(f"  {day} : {u.get('inspections', 0)} inspection(s), {llm} appel(s) Nova 2 Lite ≈ {llm * 0.0015:.3f} $ (estimation)")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depuis")
    ap.add_argument("--jusqu")
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--lien-interne", action="store_true")
    ap.add_argument("--table", default=os.environ.get("CW_TABLE"))
    ap.add_argument("--stack", default=os.environ.get("CW_STACK", "crackwatch"))
    a = ap.parse_args()
    import boto3
    cfn = boto3.client("cloudformation", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    outs = {o["OutputKey"]: o["OutputValue"] for o in cfn.describe_stacks(StackName=a.stack)["Stacks"][0]["Outputs"]}
    if a.lien_interne:
        secret_file = os.environ.get("CW_SECRET_FILE", os.path.expanduser("~/.config/crackwatch/visit-secret"))
        os.environ["CW_VISIT_SECRET"] = open(secret_file).read().strip()
        from crackwatch.visits import internal_key
        print(f"Ouvrez une fois ce lien sur chacun de vos appareils (il n'est valable que pour vous, ne le partagez pas) :\n"
              f"{outs['DemoUrl']}internal?k={internal_key()}")
        return
    from crackwatch.store import DynamoStore
    st = DynamoStore(a.table or outs["TableName"], region=os.environ.get("AWS_REGION", "us-east-1"))
    today = dt.date.today()
    d1 = dt.date.fromisoformat(a.jusqu) if a.jusqu else today
    d0 = dt.date.fromisoformat(a.depuis) if a.depuis else d1 - dt.timedelta(days=13)
    rows, usage = [], {}
    d = d0
    while d <= d1:
        rows += st.query(f"VISIT#{d.isoformat()}")
        u = {r["sk"]: r.get("n", 0) for r in st.query(f"USAGE#{d.isoformat()}") if "#" not in r["sk"]}
        if u:
            usage[d.isoformat()] = u
        d += dt.timedelta(days=1)
    print(summarize(rows, usage, d0.isoformat(), d1.isoformat(), a.detail))


if __name__ == "__main__":
    main()
