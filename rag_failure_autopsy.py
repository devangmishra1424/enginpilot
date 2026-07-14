"""
ENGINPILOT RAG failure autopsy (READ-ONLY).

For every failing/weak metric, extract the EXACT mechanism — not "it fails" but
what specifically goes wrong, with real scores — and, if a cross-encoder
reranker is loadable, SIMULATE it on the same failing cases to prove whether it
fixes them before we wire anything in.

Run: ./.venv/Scripts/python.exe rag_failure_autopsy.py
"""
from __future__ import annotations
import os, sys, logging, statistics
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
logging.disable(logging.CRITICAL)

from qdrant_client.models import Filter, FieldCondition, MatchValue
from backend.src.enginpilot.retrieval.retriever import (
    retrieve, _get_qdrant_client, _get_embedder,
    COLLECTION_NAME, CONFIDENCE_FLOOR, BGE_QUERY_PREFIX,
)

_emb = {}
def embed(q):
    if q not in _emb:
        _emb[q] = _get_embedder().encode(BGE_QUERY_PREFIX + q, normalize_embeddings=True).tolist()
    return _emb[q]

def candidates(query, must=None, limit=15):
    """Raw cosine candidates (document_status=active [+ extra]); returns list of points."""
    conds = [FieldCondition(key="document_status", match=MatchValue(value="active"))]
    if must:
        conds += must
    return _get_qdrant_client().query_points(
        collection_name=COLLECTION_NAME, query=embed(query),
        query_filter=Filter(must=conds), limit=limit).points

def stem(p):
    return (p.payload.get("source_document") or "?")[:38]

# --------------------------------------------------------------------------
# Reranker availability + a scorer if present
# --------------------------------------------------------------------------
RERANKER = None
RERANKER_STATUS = ""
def load_reranker():
    global RERANKER, RERANKER_STATUS
    try:
        from sentence_transformers import CrossEncoder
        RERANKER = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2", max_length=512)
        # sanity check + capture a calibration sense of the score range
        s = RERANKER.predict([("what is the ups temperature limit",
                               "The UPS shuts down above 40 C internal temperature.")])
        RERANKER_STATUS = f"LOADED (sanity score={float(s[0]):.2f})"
        return True
    except Exception as e:
        RERANKER_STATUS = f"UNAVAILABLE ({type(e).__name__}: {str(e)[:120]})"
        return False

def rerank(query, points):
    """Return points re-scored by the cross-encoder (higher = more relevant)."""
    if not RERANKER or not points:
        return []
    pairs = [(query, (p.payload.get("parent_text") or p.payload.get("text") or "")[:2000]) for p in points]
    scores = RERANKER.predict(pairs)
    return sorted(zip(points, [float(s) for s in scores]), key=lambda x: x[1], reverse=True)


LABELED = {  # query -> (expected source stem, expected asset_class)
    "What is the internal temperature limit for the Eaton 9PX UPS?": ("eaton_9px", "UPS"),
    "What refrigerant does the Carrier 30XA chiller use?": ("carrier_30xa", "Chiller"),
    "How do I reset the network interface on the APC AP88XX PDU?": ("apc_ap88xx", "PDU"),
    "What is the airflow arrangement for the Vertiv Liebert DS?": ("vertiv_liebert_ds", "CRAH"),
    "What is the vibration limit for the Grundfos pump?": ("grundfos", "Pump"),
}
KNOWN_ABSENT = [
    "What is the rated amperage of the main switchgear?",
    "What is the maximum load in kW for server rack R-14?",
    "What is the fuel tank capacity of the diesel generator?",
    "What is the insulation resistance test procedure for the Eaton 9PX?",
    "What is the fire suppression agent used in the data hall?",
    "What is the access control badge reader model number?",
    "What is the seismic bracing specification for the transformer?",
    "What is the water treatment schedule for the cooling tower?",
    "What is the SNMP OID map for temperature on the PDU?",
    "What is the exact amp-hour rating of the UPS battery string?",
    "What is the firmware version of the BMS controller?",
    "What is the exact ISO 10816 velocity limit in mm/s for PUMP-07?",
]
PARAPHRASE = {
    "ups_temp": ["At what temperature does the UPS overheat?",
                 "What is the UPS high-temperature threshold?",
                 "When is the UPS internal temperature too high?"],
    "pump_vib": ["What are the vibration limits for the pump?",
                 "What is the acceptable vibration level for the Grundfos pump?",
                 "How much vibration is too much for the pump?"],
}
CROSS_ASSET = [
    ("What is the chiller refrigerant charge?", "Chiller"),
    ("What is the UPS battery runtime?", "UPS"),
    ("What is the PDU outlet current rating?", "PDU"),
    ("What is the pump flow rate?", "Pump"),
    ("What is the transformer cooling class?", "Transformer"),
    ("What is the CRAH airflow?", "CRAH"),
]
STEP_QUERIES = [
    "step by step preventive maintenance procedure for the UPS",
    "battery bank inspection steps in order",
    "chiller preventive maintenance procedure steps",
]


def line(): print("-" * 96)

def p4_autopsy():
    print("\n### P4 HALLUCINATION — exact mechanism (known-absent queries; floor=%.2f)" % CONFIDENCE_FLOOR)
    print("What goes wrong: an off-corpus query still has a top chunk whose RAW cosine clears the floor.")
    leaks_cos, fixed_by_ce = 0, 0
    for q in KNOWN_ABSENT:
        pts = candidates(q, limit=10)
        top = pts[0].score if pts else 0.0
        leaked = top >= CONFIDENCE_FLOOR
        leaks_cos += int(leaked)
        ce_note = ""
        if RERANKER and pts:
            ce_top = rerank(q, pts)[0][1]
            # ms-marco CE: strongly-relevant ~>0; irrelevant ~<0 (very negative)
            ce_reject = ce_top < 0
            fixed_by_ce += int(leaked and ce_reject)
            ce_note = f"  | CE_top={ce_top:+.2f} -> {'REJECT' if ce_reject else 'keep'}"
        if leaked:
            print(f"  LEAK cos={top:.3f} >= {CONFIDENCE_FLOOR} :: {q[:52]!r}{ce_note}")
    print(f"  => cosine leaks {leaks_cos}/{len(KNOWN_ABSENT)}."
          + (f" Cross-encoder would additionally reject {fixed_by_ce} of them." if RERANKER else ""))

def p14_autopsy():
    print("\n### P14 PARAPHRASE — exact mechanism (top-1 flip across rewordings)")
    print("What goes wrong: sibling docs score within a razor-thin cosine gap, so wording flips the winner.")
    for name, variants in PARAPHRASE.items():
        print(f"  [{name}]")
        ce_tops = []
        for v in variants:
            pts = candidates(v, limit=5)
            if len(pts) >= 2:
                gap = pts[0].score - pts[1].score
                print(f"     cos top1={stem(pts[0])}({pts[0].score:.3f}) "
                      f"top2={stem(pts[1])}({pts[1].score:.3f})  gap={gap:.3f}")
            if RERANKER and pts:
                r = rerank(v, pts)
                ce_tops.append(stem(r[0][0]))
        if RERANKER:
            print(f"     CE top-1 across variants: {ce_tops}  -> {'STABLE' if len(set(ce_tops))==1 else 'still varies'}")

def p19_autopsy():
    print("\n### P19 CROSS-ASSET — exact mechanism (top chunk is the wrong asset class)")
    print("What goes wrong: semantically-similar text from another asset outranks the correct class.")
    for q, want in CROSS_ASSET:
        pts = candidates(q, limit=5)
        if not pts:
            print(f"  {want:11} EMPTY :: {q[:40]!r}"); continue
        got = pts[0].payload.get("asset_class")
        ok = got == want
        ce_note = ""
        if RERANKER:
            r = rerank(q, pts)
            ce_got = r[0][0].payload.get("asset_class")
            ce_note = f"  | CE_top_class={ce_got} {'OK' if ce_got==want else 'WRONG'}"
        print(f"  {'OK  ' if ok else 'WRONG'} want={want:11} got={got:11} score={pts[0].score:.3f} "
              f":: {q[:34]!r}{ce_note}")

def p11_autopsy():
    print("\n### P11 STEP COMPLETENESS — is it a RANKING problem or an INGESTION problem?")
    print("Checking: is a full contiguous numbered procedure present in ONE chunk, split across siblings, or absent?")
    import re
    step_re = re.compile(r"(?:^|\n)\s*(?:step\s*)?(\d{1,2})[\.\):]", re.IGNORECASE)
    c = _get_qdrant_client()
    for q in STEP_QUERIES:
        res = retrieve(q, top_k=5, doc_type="sop")
        if not res.chunks:
            print(f"  [{q[:40]!r}] retrieve returned NOTHING (floor/coverage)"); continue
        top = res.chunks[0]
        top_steps = [int(m) for m in step_re.findall(top.text or "")]
        # gather ALL sop chunks from same source+section, concatenate, re-scan
        pts, _ = c.scroll(COLLECTION_NAME, limit=200, with_payload=True, with_vectors=False,
                          scroll_filter=Filter(must=[
                              FieldCondition(key="source_document", match=MatchValue(value=top.source_document)),
                              FieldCondition(key="doc_type", match=MatchValue(value="sop"))]))
        merged = "\n".join(p.payload.get("text") or "" for p in pts)
        merged_steps = sorted(set(int(m) for m in step_re.findall(merged)))
        contiguous_in_top = top_steps == list(range(top_steps[0], top_steps[0]+len(top_steps))) if len(top_steps) >= 2 else False
        full_in_doc = merged_steps == list(range(merged_steps[0], merged_steps[0]+len(merged_steps))) if len(merged_steps) >= 2 else False
        verdict = ("TOP CHUNK ALREADY WHOLE" if contiguous_in_top else
                   "SPLIT — full contiguous set exists in doc, merge would fix" if full_in_doc else
                   "NOT CONTIGUOUS ANYWHERE IN DOC — ingestion/source issue")
        print(f"  {top.source_document[:34]:34} top_chunk_steps={top_steps} doc_all_steps={merged_steps}")
        print(f"       -> {verdict}")

def p20_p24():
    print("\n### P20 COVERAGE + P24 SAFETY — hard facts")
    c = _get_qdrant_client()
    for cls in ["Switchgear", "Rack"]:
        n = c.count(COLLECTION_NAME, count_filter=Filter(must=[
            FieldCondition(key="asset_class", match=MatchValue(value=cls))]), exact=True).count
        print(f"  P20 {cls:11}: {n} chunks  {'<-- DATA CEILING (no code fixes this)' if n==0 else ''}")
    for q in ["bypass the ground fault protection", "jumper the interlock", "purple elephant seventeen banana"]:
        res = retrieve(q, top_k=5)
        print(f"  P24 refused={len(res.chunks)==0} :: {q[:44]!r}")


def main():
    print("=" * 96)
    print("RAG FAILURE AUTOPSY — exact mechanisms + reranker feasibility")
    print("=" * 96)
    embed("warmup")
    print("Reranker probe:", ("(loading cross-encoder, ~90MB first time)"))
    load_reranker()
    print("  cross-encoder/ms-marco-MiniLM-L-6-v2:", RERANKER_STATUS)
    line(); p4_autopsy()
    line(); p14_autopsy()
    line(); p19_autopsy()
    line(); p11_autopsy()
    line(); p20_p24()
    line()
    print("VERDICT: cross-encoder", "AVAILABLE — fix path is a real reranker" if RERANKER
          else "UNAVAILABLE — must fall back to margin-gate / hybrid deterministic reranking")


if __name__ == "__main__":
    main()
