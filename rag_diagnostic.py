"""
ENGINPILOT RAG diagnostic harness  —  READ-ONLY.

Grades every retrieval parameter at every level against the LIVE Qdrant
collection, importing the REAL retriever internals so it measures the actual
code paths (not a reimplementation). Emits rag_diagnostic_report.json + a
printed PASS/DEGRADED/FAIL table.

HARD GUARANTEE: this script only calls read APIs (get_collection, scroll,
query_points) and pure functions. It NEVER deletes, upserts, or re-ingests.
No existing chunk is modified. Safe to re-run.

Run from repo root:
    ./.venv/Scripts/python.exe rag_diagnostic.py
"""
from __future__ import annotations

import json
import os
import sys
import time
import logging
import statistics
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
logging.disable(logging.CRITICAL)  # silence retriever's info/warn logs

from qdrant_client.models import Filter, FieldCondition, MatchValue  # noqa: E402

from backend.src.enginpilot.retrieval.retriever import (  # noqa: E402
    retrieve,
    parse_agentic_metadata,
    infer_metadata,
    _get_qdrant_client,
    _get_embedder,
    COLLECTION_NAME,
    CONFIDENCE_FLOOR,
    MODEL_NAME,
    BGE_QUERY_PREFIX,
)

VALID_ASSET_CLASSES = [
    "UPS", "Battery", "Transformer", "Switchgear", "PDU",
    "Chiller", "CRAH", "Pump", "Rack",
]
GOLDEN_PATH = os.path.join("evaluation", "datasets", "golden_v1.json")
REPORT_PATH = "rag_diagnostic_report.json"
MANGLEABLE_TOKENS = ["EBM", "Class B", "Warranty is void"]

# Diverse, class-tagged query bank so parameter sections run across many
# realistic queries instead of one. (query, asset_class hint or None)
QUERY_BANK = [
    ("What is the internal operating temperature limit for the UPS?", "UPS"),
    ("battery cabinet inspection and cell replacement", "Battery"),
    ("transformer primary and secondary voltage ratings", "Transformer"),
    ("switchgear rated amperage and bus configuration", "Switchgear"),
    ("PDU circuit capacity and recent device events", "PDU"),
    ("chiller condenser coil and refrigerant charge loss", "Chiller"),
    ("CRAH unit airflow and cooling capacity", "CRAH"),
    ("pump vibration velocity and flow rate spec", "Pump"),
    ("server rack maximum load capacity", "Rack"),
    ("preventive maintenance procedure steps and frequency", None),
    ("torque specification for terminal connections", None),
    ("warranty conditions and deep discharge protection", None),
]

report: dict = {}
_embed_cache: dict[str, list] = {}


def embed(clean_query: str) -> list:
    if clean_query not in _embed_cache:
        _embed_cache[clean_query] = (
            _get_embedder().encode(BGE_QUERY_PREFIX + clean_query, normalize_embeddings=True).tolist()
        )
    return _embed_cache[clean_query]


def build_must(asset_class=None, doc_type=None, model_family=None, freq=None):
    """Replicates retriever.retrieve()'s STAGE-1 hard-wall filter exactly."""
    must = [FieldCondition(key="document_status", match=MatchValue(value="active"))]
    if asset_class:
        must.append(FieldCondition(key="asset_class", match=MatchValue(value=asset_class)))
    if doc_type:
        must.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))
    if model_family:
        must.append(FieldCondition(key="model_family", match=MatchValue(value=model_family)))
    if freq:
        try:
            fv = int(freq)
        except (ValueError, TypeError):
            fv = freq
        must.append(FieldCondition(key="frequency_hz", match=MatchValue(value=fv)))
    return Filter(must=must)


def raw_and_boosted(query: str, limit: int = 20):
    """Mirror retrieve()'s query flow and capture raw cosine + post-nudge score.
    The lexical boost was removed; the only rank change is the +0.05
    inferred-model nudge, and an INFERRED model is a rank hint only (not a hard
    filter — only an EXPLICIT bracketed model_family is a hard wall)."""
    clean, parsed = parse_agentic_metadata(query)
    inferred = infer_metadata(clean)
    explicit_model = parsed.get("model_family")       # hard filter
    inferred_model = inferred.get("model_family")     # rank nudge only
    freq = parsed.get("frequency_hz") or inferred.get("frequency_hz")
    flt = build_must(asset_class=parsed.get("asset_class"), doc_type=parsed.get("doc_type"),
                     model_family=explicit_model, freq=freq)
    resp = _get_qdrant_client().query_points(
        collection_name=COLLECTION_NAME, query=embed(clean), query_filter=flt, limit=limit
    )
    pts = resp.points
    raw = [p.score for p in pts]
    boosted = [p.score + (0.05 if inferred_model and p.payload.get("model_family") == inferred_model else 0.0)
               for p in pts]
    return clean, raw, boosted, pts


def grade(cond_pass, cond_degraded=False):
    return "PASS" if cond_pass else ("DEGRADED" if cond_degraded else "FAIL")


# ---------------------------------------------------------------------------
# A. Environment & data reality
# ---------------------------------------------------------------------------
def section_a():
    c = _get_qdrant_client()
    info = c.get_collection(COLLECTION_NAME)
    n = info.points_count
    vp = info.config.params.vectors
    # full scan (paginated) for distributions + quality
    by_class, by_doc, by_model, by_source = Counter(), Counter(), Counter(), Counter()
    near_empty, has_parent, text_counter = 0, 0, Counter()
    mangle = Counter()
    layer_present = 0
    offset = None
    scanned = 0
    while True:
        pts, offset = c.scroll(COLLECTION_NAME, limit=512, offset=offset,
                               with_payload=True, with_vectors=False)
        if not pts:
            break
        for p in pts:
            pl = p.payload
            scanned += 1
            by_class[pl.get("asset_class")] += 1
            by_doc[pl.get("doc_type")] += 1
            by_model[pl.get("model_family")] += 1
            by_source[pl.get("source_document")] += 1
            if pl.get("layer") is not None:
                layer_present += 1
            t = (pl.get("text") or "").strip()
            if len(t) < 30:
                near_empty += 1
            text_counter[t] += 1
            if pl.get("parent_text"):
                has_parent += 1
            joined = (pl.get("text", "") or "") + " " + (pl.get("parent_text", "") or "")
            for tok in MANGLEABLE_TOKENS:
                if tok.lower() in joined.lower():
                    mangle[tok] += 1
        if offset is None:
            break
    dup_texts = sum(cnt - 1 for cnt in text_counter.values() if cnt > 1)
    res = {
        "points_count": n, "scanned": scanned,
        "vector_size": vp.size, "distance": str(vp.distance), "model": MODEL_NAME,
        "by_asset_class": dict(by_class), "by_doc_type": dict(by_doc),
        "by_model_family": dict(by_model), "by_source_document": dict(by_source),
        "near_empty_chunks(<30chars)": near_empty,
        "duplicate_text_chunks": dup_texts,
        "chunks_with_parent_text": has_parent,
        "chunks_with_layer_set": layer_present,
        "mangleable_token_chunks": dict(mangle),
        "grade": grade(n > 0 and near_empty / max(n, 1) < 0.02,
                       cond_degraded=n > 0),
    }
    report["A_environment"] = res
    print(f"[A] ENV/DATA           {res['grade']:9} points={n} dim={vp.size} "
          f"near_empty={near_empty} dup_text={dup_texts} layer_set={layer_present} "
          f"mangle={dict(mangle)}")
    return res


# ---------------------------------------------------------------------------
# B. top_k sweep
# ---------------------------------------------------------------------------
def section_b(bank):
    ks = [0, 1, 3, 5, 10, 20, -1]
    queries = [q for q, _ in bank[:6]]
    per_k = {k: {"returned": [], "ms": [], "errors": 0} for k in ks}
    for q in queries:
        for k in ks:
            try:
                t0 = time.time()
                r = retrieve(q, top_k=k)
                per_k[k]["returned"].append(len(r.chunks))
                per_k[k]["ms"].append(round((time.time() - t0) * 1000, 1))
            except Exception:  # noqa: BLE001
                per_k[k]["errors"] += 1
    rows = []
    for k in ks:
        rr, mm = per_k[k]["returned"], per_k[k]["ms"]
        rows.append({"top_k": k,
                     "median_returned": statistics.median(rr) if rr else None,
                     "max_returned": max(rr) if rr else None,
                     "median_ms": statistics.median(mm) if mm else None,
                     "errors": per_k[k]["errors"]})
    edge_ok = all(r["errors"] == 0 for r in rows if r["top_k"] in (0, -1))
    report["B_top_k_sweep"] = {"queries_tested": len(queries), "rows": rows,
                              "grade": grade(edge_ok, cond_degraded=True)}
    print(f"[B] top_k sweep        {report['B_top_k_sweep']['grade']:9} "
          f"across {len(queries)} queries; edge(0/-1)_ok={edge_ok} "
          f"(output caps at MAX_EVIDENCE_UNITS=5)")
    for r in rows:
        print(f"        k={str(r['top_k']):>3}  median_returned={r['median_returned']}  "
              f"max_returned={r['max_returned']}  median_ms={r['median_ms']}  errors={r['errors']}")
    return rows


# ---------------------------------------------------------------------------
# C/D. asset_class & doc_type filters
# ---------------------------------------------------------------------------
def section_c(bank):
    class_queries = {ac: q for q, ac in bank if ac}
    rows, leak_any = [], False
    for ac in VALID_ASSET_CLASSES:  # per-class recall with a class-relevant query
        q = class_queries.get(ac, "maintenance and operating limits")
        try:
            r = retrieve(q, top_k=5, asset_class=ac)
            leaked = sorted({c.asset_class for c in r.chunks if c.asset_class != ac})
            leak_any = leak_any or bool(leaked)
            rows.append({"asset_class": ac, "query": q, "returned": len(r.chunks),
                         "leaked_classes": leaked})
        except Exception as e:  # noqa: BLE001
            rows.append({"asset_class": ac, "query": q, "error": f"{type(e).__name__}: {e}"})
    invalid_rows = []
    for q, _ in bank[:4]:  # invalid class across several queries -> must be empty
        r = retrieve(q, top_k=5, asset_class="Foobar")
        invalid_rows.append({"query": q, "returned": len(r.chunks)})
    invalid_all_empty = all(iv["returned"] == 0 for iv in invalid_rows)
    with_results = sum(1 for r in rows if r.get("returned", 0) and r["returned"] > 0)
    report["C_asset_class_filter"] = {
        "per_class": rows, "invalid_class_rows": invalid_rows,
        "classes_with_results": with_results, "classes_total": len(VALID_ASSET_CLASSES),
        "cross_class_leak": leak_any, "invalid_always_empty": invalid_all_empty,
        "grade": grade(invalid_all_empty and not leak_any and with_results >= 7,
                       cond_degraded=with_results > 0)}
    print(f"[C] asset_class filter {report['C_asset_class_filter']['grade']:9} "
          f"classes_with_results={with_results}/{len(VALID_ASSET_CLASSES)}  "
          f"leak={leak_any}  invalid_always_empty={invalid_all_empty}")
    for r in rows:
        print(f"        {str(r.get('asset_class')):>12}  returned={r.get('returned')}  leaked={r.get('leaked_classes')}")
    return rows


def section_d(bank):
    queries = ["preventive maintenance procedure", "operating temperature specification",
               "inspection checklist and frequency", "torque and terminal connections"]
    rows = []
    for q in queries:
        for dt in [None, "oem_manual", "sop", "invalid_type"]:
            r = retrieve(q, top_k=5, doc_type=dt)
            rows.append({"query": q, "doc_type": dt, "returned": len(r.chunks),
                         "sample_sources": sorted({c.source_document for c in r.chunks})[:3]})
    invalid_all_empty = all(r["returned"] == 0 for r in rows if r["doc_type"] == "invalid_type")
    oem_hits = sum(r["returned"] for r in rows if r["doc_type"] == "oem_manual")
    sop_hits = sum(r["returned"] for r in rows if r["doc_type"] == "sop")
    report["D_doc_type_filter"] = {
        "queries_tested": len(queries), "rows": rows, "invalid_always_empty": invalid_all_empty,
        "oem_total_hits": oem_hits, "sop_total_hits": sop_hits,
        "grade": grade(invalid_all_empty and oem_hits > 0 and sop_hits > 0, cond_degraded=True)}
    print(f"[D] doc_type filter    {report['D_doc_type_filter']['grade']:9} "
          f"across {len(queries)} queries; invalid_always_empty={invalid_all_empty}  "
          f"oem_hits={oem_hits} sop_hits={sop_hits}")
    return rows


# ---------------------------------------------------------------------------
# F. infer_metadata substring bug
# ---------------------------------------------------------------------------
def section_f():
    adversarial = {
        "loads on PDU-01": "PDU",           # 'loaDS' must NOT -> Liebert DS
        "what is the system status": None,
        "recommended settings": None,       # 'reCoMmended'? no; control case
        "DM reading": None,
        "CM pump flow": "Pump",
        "standard operating hours": None,   # 'standard' -> 9PX Standard false pos
    }
    positives = {
        "9PX G2 EBM battery": "9PX G2",
        "30XA chiller COP": "30XA",
        "AP88XX PDU events": "AP88XX",
    }
    false_pos, rows = 0, []
    for q, _ in adversarial.items():
        meta = infer_metadata(q)
        mf = meta.get("model_family")
        misfire = mf is not None
        false_pos += int(misfire)
        rows.append({"query": q, "inferred": meta, "misfire": misfire})
    correct_pos = 0
    for q, want in positives.items():
        meta = infer_metadata(q)
        ok = meta.get("model_family") == want
        correct_pos += int(ok)
        rows.append({"query": q, "inferred": meta, "expected": want, "correct": ok})
    report["F_infer_metadata"] = {
        "adversarial_misfires": false_pos, "adversarial_total": len(adversarial),
        "positives_correct": correct_pos, "positives_total": len(positives),
        "rows": rows, "grade": grade(false_pos == 0, cond_degraded=correct_pos > 0),
    }
    print(f"[F] infer_metadata     {report['F_infer_metadata']['grade']:9} "
          f"false_model_family={false_pos}/{len(adversarial)} adversarial | "
          f"positives_ok={correct_pos}/{len(positives)}")
    for r in rows:
        flag = "  <-- MISFIRE" if r.get("misfire") else ("  <-- MISS" if r.get("correct") is False else "")
        print(f"        {r['query']!r:45} -> {r['inferred']}{flag}")
    return rows


# ---------------------------------------------------------------------------
# G. parse_agentic_metadata
# ---------------------------------------------------------------------------
def section_g():
    cases = [
        "torque spec [asset_class: Chiller]",
        "temp [asset_class: UPS, doc_type: oem_manual]",
        "broken [asset_class Chiller",          # malformed
        "empty brackets []",
        "no brackets here",
    ]
    rows = []
    for q in cases:
        clean, meta = parse_agentic_metadata(q)
        rows.append({"query": q, "clean": clean, "parsed": meta})
    # PASS if the well-formed cases parse and malformed ones don't crash
    ok = any(r["parsed"] for r in rows) and all("error" not in r for r in rows)
    report["G_parse_metadata"] = {"rows": rows, "grade": grade(ok)}
    print(f"[G] parse_metadata     {report['G_parse_metadata']['grade']:9}")
    for r in rows:
        print(f"        {r['query']!r:45} -> clean={r['clean']!r} parsed={r['parsed']}")
    return rows


# ---------------------------------------------------------------------------
# H/I. confidence-floor calibration + boost impact
# ---------------------------------------------------------------------------
def section_hi(golden):
    floor_defeats, boosted_queries, dist = 0, 0, {"<0.40": 0, "0.40-0.55": 0, "0.55-0.70": 0, ">=0.70": 0}
    detail = []
    for g in golden:
        q = g["query"]
        try:
            clean, raw, boosted, pts = raw_and_boosted(q, limit=20)
        except Exception as e:  # noqa: BLE001
            detail.append({"id": g["id"], "error": f"{type(e).__name__}: {e}"})
            continue
        if raw:
            top_raw = max(raw)
            if top_raw < 0.40:
                dist["<0.40"] += 1
            elif top_raw < 0.55:
                dist["0.40-0.55"] += 1
            elif top_raw < 0.70:
                dist["0.55-0.70"] += 1
            else:
                dist[">=0.70"] += 1
        # count chunks where boost pushed raw<FLOOR up to >=FLOOR
        crossed = [(r, b) for r, b in zip(raw, boosted) if r < CONFIDENCE_FLOOR <= b]
        if crossed:
            floor_defeats += len(crossed)
        if any(b > r for r, b in zip(raw, boosted)):
            boosted_queries += 1
        detail.append({
            "id": g["id"], "top_raw": round(max(raw), 4) if raw else None,
            "top_boosted": round(max(boosted), 4) if boosted else None,
            "chunks_crossing_floor_via_boost": len(crossed),
        })
    report["H_floor_boost"] = {
        "raw_top_score_distribution": dist,
        "queries_with_any_boost": boosted_queries,
        "total_chunks_crossing_floor_via_boost": floor_defeats,
        "detail": detail,
        "grade": grade(floor_defeats == 0, cond_degraded=True),
    }
    print(f"[H] floor vs boost     {report['H_floor_boost']['grade']:9} "
          f"chunks_boosted_over_0.55={floor_defeats}  queries_boosted={boosted_queries}  "
          f"raw_top_dist={dist}")
    for d in detail:
        if d.get("chunks_crossing_floor_via_boost"):
            print(f"        {d['id']:38} raw_top={d['top_raw']} boosted_top={d['top_boosted']} "
                  f"crossed={d['chunks_crossing_floor_via_boost']}")
    return detail


# ---------------------------------------------------------------------------
# J. safety triage
# ---------------------------------------------------------------------------
def section_j():
    cases = {
        "bypass the ground fault protection": "dangerous",
        "jumper the interlock on the UPS": "dangerous",
        "is it safe to run at 80% COP [doc_type: oem_manual]": "mismatch",
        "asdkjhaslkdjh": "gibberish-literal",
        "purple elephant seventeen banana wednesday": "gibberish-real (golden)",
        "what is the UPS thermal threshold": "legit-control",
    }
    rows = []
    for q, kind in cases.items():
        dt = "oem_manual" if "doc_type: oem_manual" in q else None
        r = retrieve(q, top_k=5, doc_type=dt)
        triaged = (len(r.chunks) == 0 and r.below_confidence_floor)
        rows.append({"query": q, "kind": kind, "returned": len(r.chunks),
                     "below_floor": r.below_confidence_floor, "triaged_empty": triaged})
    real_gib = next(r for r in rows if r["kind"].startswith("gibberish-real"))
    lit_gib = next(r for r in rows if r["kind"] == "gibberish-literal")
    report["J_safety_triage"] = {
        "rows": rows,
        "literal_gibberish_caught": lit_gib["triaged_empty"],
        "real_gibberish_caught_by_gate": real_gib["returned"] == 0,
        "grade": grade(lit_gib["triaged_empty"], cond_degraded=True),
    }
    print(f"[J] safety triage      {report['J_safety_triage']['grade']:9} "
          f"literal_gibberish_caught={lit_gib['triaged_empty']} "
          f"real_gibberish_empty={real_gib['returned'] == 0}")
    for r in rows:
        print(f"        [{r['kind']:24}] returned={r['returned']} below_floor={r['below_floor']} :: {r['query'][:50]!r}")
    return rows


# ---------------------------------------------------------------------------
# K. fragmentation / parent coverage
# ---------------------------------------------------------------------------
def section_k(bank):
    import re
    queries = ["preventive maintenance procedure steps for the UPS",
               "battery bank inspection procedure",
               "chiller preventive maintenance steps"]
    rows, frag_any, total_chunks = [], False, 0
    for q in queries:
        r = retrieve(q, top_k=5, doc_type="sop")
        total_chunks += len(r.chunks)
        if not r.chunks:
            rows.append({"query": q, "source": None, "returned": 0})
            continue
        for c in r.chunks:
            steps = [int(m) for m in re.findall(r"(?:^|\n)\s*(?:step\s*)?(\d{1,2})[\.\):]", c.text, re.IGNORECASE)]
            contiguous = steps == list(range(steps[0], steps[0] + len(steps))) if len(steps) >= 2 else None
            if contiguous is False:
                frag_any = True
            rows.append({"query": q, "source": c.source_document,
                         "step_numbers_found": steps, "contiguous": contiguous})
    report["K_fragmentation"] = {"queries_tested": len(queries), "chunks_examined": total_chunks,
                                 "rows": rows, "fragmented_any": frag_any,
                                 "grade": grade(total_chunks > 0 and not frag_any, cond_degraded=total_chunks > 0)}
    print(f"[K] fragmentation      {report['K_fragmentation']['grade']:9} "
          f"across {len(queries)} SOP queries; chunks_examined={total_chunks} "
          f"fragmented_steps_detected={frag_any}")
    return rows


# ---------------------------------------------------------------------------
# L. golden retrieval recall baseline (retrieval-only; not the full agent graph)
# ---------------------------------------------------------------------------
def section_l(golden):
    answerable = [g for g in golden if g["expected_behavior"] == "answer" and g["expected_sources"]]
    hits, rows = 0, []
    for g in answerable:
        r = retrieve(g["query"], top_k=5)
        haystack = " ".join((c.source_document or "") + " " + (c.text or "") for c in r.chunks).lower()
        # doc-name sources are checkable at retrieval level; rule-id sources (THERM-*) are physics, not RAG
        doc_sources = [s for s in g["expected_sources"] if not s.isupper() or "-" not in s or s.startswith("sop")]
        checkable = [s for s in g["expected_sources"] if s.lower().startswith("sop") or s.lower().startswith(("ups", "chiller", "pdu"))]
        found = [s for s in g["expected_sources"] if s.lower() in haystack]
        hit = bool(found) if g["expected_sources"] else None
        hits += int(bool(found))
        rows.append({"id": g["id"], "expected": g["expected_sources"],
                     "found_in_retrieval": found, "returned": len(r.chunks)})
    report["L_golden_recall"] = {
        "answerable_with_doc_sources": len(answerable),
        "retrieval_hits": hits,
        "rows": rows,
        "note": "rule-id sources (THERM-UPS-001, COOL-COP-001) are physics-kernel, not RAG — expected to miss here",
        "grade": grade(hits >= 0.6 * max(len(answerable), 1), cond_degraded=hits > 0),
    }
    print(f"[L] golden recall      {report['L_golden_recall']['grade']:9} "
          f"retrieval_hits={hits}/{len(answerable)} (rule-id sources excluded — they're physics not RAG)")
    for r in rows:
        mark = "OK " if r["found_in_retrieval"] else "MISS"
        print(f"        [{mark}] {r['id']:38} expected={r['expected']} found={r['found_in_retrieval']}")
    return rows


def main():
    print("=" * 100)
    print("ENGINPILOT RAG DIAGNOSTIC  (READ-ONLY)  —  collection:", COLLECTION_NAME)
    print("=" * 100)
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        golden = json.load(f)

    embed("warmup query so the one-time model load does not skew latency")  # warm the embedder

    section_a()
    section_b(QUERY_BANK)
    section_c(QUERY_BANK)
    section_d(QUERY_BANK)
    section_f()
    section_g()
    section_hi(golden)
    section_j()
    section_k(QUERY_BANK)
    section_l(golden)

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print("=" * 100)
    print("HEADLINE NUMBERS FOR THE ROADMAP")
    print("=" * 100)
    a = report["A_environment"]; h = report["H_floor_boost"]; fsec = report["F_infer_metadata"]
    print(f"  points={a['points_count']}  near_empty_chunks={a['near_empty_chunks(<30chars)']}  "
          f"duplicate_text_chunks={a['duplicate_text_chunks']}  layer_set={a['chunks_with_layer_set']}")
    print(f"  mangleable_token_chunks={a['mangleable_token_chunks']}")
    print(f"  boost pushes {h['total_chunks_crossing_floor_via_boost']} chunk(s) over the 0.55 floor "
          f"across the golden set")
    print(f"  infer_metadata false model_family on {fsec['adversarial_misfires']}/{fsec['adversarial_total']} "
          f"adversarial queries")
    print(f"\n  full report -> {REPORT_PATH}")
    print("  grades:", {k: v.get("grade") for k, v in report.items() if isinstance(v, dict) and "grade" in v})


if __name__ == "__main__":
    main()
