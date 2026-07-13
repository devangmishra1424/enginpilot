"""
ENGINPILOT — ENTERPRISE-GRADE RAG QUALITY BENCHMARK  (READ-ONLY)

Not a parameter/level diagnostic (that's rag_diagnostic.py). This grades HOW
GOOD the retrieval is on the dimensions enterprise RAG is judged on, with 10+
labeled queries per dimension and explicit pass thresholds:

  M1  Context Recall (source hit@k)      M7  Citation integrity (present + un-mangled)
  M2  Context Precision (class purity)   M8  Metadata-filter precision (infer_metadata harm)
  M3  Retrieval relevance (score health) M9  Paraphrase robustness
  M4  Hallucination resistance           M10 Determinism
      (negative rejection)               M11 Latency (p50/p95)
  M5  Table integrity (whole tables)     M12 Faithfulness  [optional, --llm]
  M6  Procedure/step completeness

Ground truth is the known corpus (Carrier 30XA chiller, Vertiv Liebert DS/DM
CRAH, APC AP88XX PDU, Eaton 9PX UPS, Grundfos CR/CM pumps, ABB transformer,
3 SOPs). All checks are read-only queries; nothing is written or deleted.

Run:  ./.venv/Scripts/python.exe rag_quality_eval.py           (deterministic core, no tokens)
      ./.venv/Scripts/python.exe rag_quality_eval.py --llm     (also runs M12 faithfulness via NVIDIA)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import logging
import statistics

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
logging.disable(logging.CRITICAL)

from qdrant_client.models import Filter, FieldCondition, MatchValue  # noqa: E402
from backend.src.enginpilot.retrieval.retriever import (  # noqa: E402
    retrieve, parse_agentic_metadata, infer_metadata,
    _get_qdrant_client, _get_embedder,
    COLLECTION_NAME, CONFIDENCE_FLOOR, BGE_QUERY_PREFIX,
)

REPORT_PATH = "rag_quality_report.json"
report: dict = {}
LAT: list[float] = []
_emb: dict[str, list] = {}


def embed(q: str) -> list:
    if q not in _emb:
        _emb[q] = _get_embedder().encode(BGE_QUERY_PREFIX + q, normalize_embeddings=True).tolist()
    return _emb[q]


def R(query, top_k=5, asset_class=None, doc_type=None):
    """Timed retrieve()."""
    t0 = time.time()
    res = retrieve(query, top_k=top_k, asset_class=asset_class, doc_type=doc_type)
    LAT.append((time.time() - t0) * 1000)
    return res


def stems(res):
    return [c.source_document or "" for c in res.chunks]


def pct_grade(score, good, ok):
    return "PASS" if score >= good else ("DEGRADED" if score >= ok else "FAIL")


def hdr(mid, name):
    print(f"\n[{mid}] {name}")


# ---------------------------------------------------------------------------
# Labeled ground-truth query sets
# ---------------------------------------------------------------------------
# (query, expected source-doc stem, expected asset_class)
LABELED = [
    ("What is the internal ambient temperature limit for the Eaton 9PX UPS?", "eaton_9px", "UPS"),
    ("How do I put the Eaton 9PX UPS into bypass mode?", "eaton_9px", "UPS"),
    ("What is the battery runtime behaviour of the Eaton 9PX?", "eaton_9px", "UPS"),
    ("What refrigerant does the Carrier 30XA chiller use?", "carrier_30xa", "Chiller"),
    ("How is the 30XA SmartVU control interface navigated?", "carrier_30xa_smartvu", "Chiller"),
    ("What is the minimum chilled water flow requirement for the 30XA?", "carrier_30xa", "Chiller"),
    ("What is the airflow arrangement for the Vertiv Liebert DS?", "vertiv_liebert_ds", "CRAH"),
    ("How is the Vertiv Liebert DM split system configured?", "vertiv_liebert_dm", "CRAH"),
    ("How do I reset the network interface on the APC AP88XX PDU?", "apc_ap88xx", "PDU"),
    ("Where are recent device events shown on the APC PDU?", "apc_ap88xx", "PDU"),
    ("What is the installation guidance for the Grundfos CR/CRN pump?", "grundfos_cr", "Pump"),
    ("What is the maintenance guidance for the Grundfos CM pump?", "grundfos_cm", "Pump"),
    ("What are the cooling requirements for the ABB transformer?", "abb_transformer", "Transformer"),
    ("What are the preventive maintenance steps for the UPS?", "sop_ups_preventive_maintenance", "UPS"),
    ("What is the chiller preventive maintenance procedure?", "sop_chiller_preventive_maintenance", "Chiller"),
    ("What is the battery bank inspection procedure?", "sop_battery_bank_inspection", "Battery"),
]

# Facts/entities NOT in the corpus — retrieval MUST return nothing above floor.
KNOWN_ABSENT = [
    "What is the exact ISO 10816 velocity limit in mm/s for PUMP-07 mounting class?",
    "What is the rated amperage of the main switchgear?",
    "What is the maximum load in kW for server rack R-14?",
    "What is the fuel tank capacity of the diesel generator?",
    "What is the insulation resistance test procedure for the Eaton 9PX?",
    "What is the firmware version of the building management system controller?",
    "What is the water treatment schedule for the cooling tower?",
    "What is the seismic bracing specification for the transformer?",
    "What is the fire suppression agent used in the data hall?",
    "What is the access control badge reader model number?",
    "What is the SNMP OID map for temperature on the PDU?",
    "What is the exact amp-hour rating of the UPS battery string?",
]

# Table-bearing content
TABLE_QUERIES = [
    "List the physical and electrical specifications table for the Carrier 30XA chiller",
    "What are the electrical data ratings for the 30XA?",
    "Show the event and alarm codes for the APC AP88XX PDU",
    "What are the dimensions and weights for the Vertiv Liebert DS?",
    "What are the performance data values for the Grundfos CR pump?",
    "What are the technical specification values for the Eaton 9PX UPS?",
    "What are the fan and motor ratings for the CRAH unit?",
    "List the refrigerant and compressor data for the 30XA",
    "What are the operating condition limits table for the chiller?",
    "What are the network configuration parameters for the APC PDU?",
]

# Multi-step procedures
STEP_QUERIES = [
    "What are the step-by-step preventive maintenance steps for the UPS?",
    "List the battery bank inspection steps in order",
    "What is the chiller preventive maintenance procedure step by step?",
    "What is the commissioning procedure for the Grundfos CR pump?",
    "What is the startup sequence for the Carrier 30XA chiller?",
    "What are the steps to reset the APC PDU network interface?",
    "What is the shutdown procedure for the Vertiv Liebert DS?",
    "How do I replace the UPS battery module step by step?",
    "What is the filter maintenance procedure for the CRAH?",
    "What are the numbered maintenance tasks for the pump?",
]

# Queries carrying an infer_metadata trigger word (measures filter harm)
TRIGGER_QUERIES = [
    "loads on PDU-01",
    "chiller preventive maintenance plan",
    "DM sensor reading trend",
    "standard operating procedure for the UPS",
    "DS airflow configuration",
    "CM pump vibration limit",
    "g2 battery module replacement",
    "smartvu alarm history",
    "30xa condenser cleaning",
    "ap88xx outlet grouping",
]

# Paraphrase groups (same intent, different phrasing) -> should retrieve same top doc
PARAPHRASE_GROUPS = {
    "ups_temp": [
        "At what temperature does the UPS overheat?",
        "What is the UPS high-temperature threshold?",
        "When is the UPS internal temperature considered too high?",
    ],
    "pdu_reset": [
        "How do I reset the PDU network interface?",
        "What are the steps to reset networking on the APC PDU?",
        "How do I reboot the network card on the AP88XX?",
    ],
    "chiller_refrig": [
        "What refrigerant does the 30XA use?",
        "Which refrigerant type is used in the Carrier chiller?",
        "What is the refrigerant for the 30XA chiller?",
    ],
    "pump_vibration": [
        "What are the vibration limits for the pump?",
        "What is the acceptable vibration level for the Grundfos pump?",
        "How much vibration is too much for the pump?",
    ],
}


# ---------------------------------------------------------------------------
# M1 recall + M2 precision + M3 relevance  (shared labeled set)
# ---------------------------------------------------------------------------
def m1_m2_m3():
    hdr("M1/M2/M3", "Context Recall / Precision / Relevance  (16 labeled queries)")
    recalls, precisions, top_scores, rows = [], [], [], []
    for q, exp_stem, exp_class in LABELED:
        res = R(q, top_k=5)
        srcs = stems(res)
        hit = any(exp_stem in s for s in srcs)
        recalls.append(1.0 if hit else 0.0)
        if res.chunks:
            match = sum(1 for c in res.chunks if c.asset_class == exp_class)
            precisions.append(match / len(res.chunks))
            top_scores.append(max(c.score for c in res.chunks))
        trigger = bool(infer_metadata(parse_agentic_metadata(q)[0]).get("model_family"))
        rows.append({"query": q, "expected": exp_stem, "class": exp_class,
                     "returned": len(res.chunks), "hit": hit,
                     "got_sources": sorted(set(srcs)),
                     "infer_trigger": trigger})
    recall = statistics.mean(recalls)
    precision = statistics.mean(precisions) if precisions else 0.0
    mean_top = statistics.mean(top_scores) if top_scores else 0.0
    frac_strong = (sum(1 for s in top_scores if s >= 0.60) / len(top_scores)) if top_scores else 0.0
    empties = sum(1 for r in rows if r["returned"] == 0)
    report["M1_recall"] = {"score": round(recall, 3), "empties": empties, "rows": rows,
                           "grade": pct_grade(recall, 0.85, 0.70)}
    report["M2_precision"] = {"score": round(precision, 3),
                              "grade": pct_grade(precision, 0.80, 0.65)}
    report["M3_relevance"] = {"mean_top_score": round(mean_top, 3),
                              "frac_top>=0.60": round(frac_strong, 3),
                              "grade": pct_grade(frac_strong, 0.80, 0.60)}
    print(f"   M1 recall@5    {report['M1_recall']['grade']:8} = {recall:.0%}  "
          f"(empty results on {empties}/16)")
    print(f"   M2 precision   {report['M2_precision']['grade']:8} = {precision:.0%}  (class purity of returned chunks)")
    print(f"   M3 relevance   {report['M3_relevance']['grade']:8} = mean_top_score {mean_top:.3f}, "
          f"{frac_strong:.0%} of queries have a top chunk >=0.60")
    for r in rows:
        mark = "OK  " if r["hit"] else "MISS"
        note = "  [infer_metadata trigger]" if (not r["hit"] and r["infer_trigger"]) else ""
        print(f"      [{mark}] ret={r['returned']} exp={r['expected']:34} got={r['got_sources']}{note}")


# ---------------------------------------------------------------------------
# M4 hallucination resistance (negative rejection)
# ---------------------------------------------------------------------------
def m4():
    hdr("M4", "Hallucination resistance / negative rejection  (12 known-absent queries)")
    rows, rejected = [], 0
    for q in KNOWN_ABSENT:
        res = R(q, top_k=5)
        ok = len(res.chunks) == 0 and res.below_confidence_floor
        rejected += int(ok)
        rows.append({"query": q, "returned": len(res.chunks),
                     "below_floor": res.below_confidence_floor, "correctly_rejected": ok,
                     "leaked_sources": sorted(set(stems(res)))})
    score = rejected / len(KNOWN_ABSENT)
    report["M4_hallucination_resistance"] = {"score": round(score, 3), "rejected": rejected,
                                             "total": len(KNOWN_ABSENT), "rows": rows,
                                             "grade": pct_grade(score, 1.0, 0.80)}
    print(f"   {report['M4_hallucination_resistance']['grade']:8} = {score:.0%} correctly rejected "
          f"({rejected}/{len(KNOWN_ABSENT)}) — a confident hit on absent info feeds hallucination")
    for r in rows:
        if not r["correctly_rejected"]:
            print(f"      [LEAK] ret={r['returned']} {r['leaked_sources']} :: {r['query'][:60]!r}")


# ---------------------------------------------------------------------------
# M5 table integrity
# ---------------------------------------------------------------------------
_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
_SEP_RE = re.compile(r"\|\s*:?-{2,}", re.MULTILINE)


def m5():
    hdr("M5", "Table integrity — whole tables, not orphan rows  (10 table queries)")
    rows, complete = [], 0
    for q in TABLE_QUERIES:
        res = R(q, top_k=5)
        best_rows, has_sep, truncated = 0, False, False
        for c in res.chunks:
            t = c.text or ""
            n = len(_ROW_RE.findall(t))
            best_rows = max(best_rows, n)
            has_sep = has_sep or bool(_SEP_RE.search(t))
            truncated = truncated or ("[TRUNCATED" in t)
        is_complete = best_rows >= 3  # header + separator/data or several data rows
        complete += int(is_complete)
        rows.append({"query": q, "returned": len(res.chunks), "max_table_rows": best_rows,
                     "has_separator": has_sep, "truncated": truncated, "complete": is_complete})
    score = complete / len(TABLE_QUERIES)
    report["M5_table_integrity"] = {"score": round(score, 3), "rows": rows,
                                    "grade": pct_grade(score, 0.80, 0.60)}
    print(f"   {report['M5_table_integrity']['grade']:8} = {score:.0%} of table queries returned a "
          f"multi-row table chunk (>=3 rows)")
    for r in rows:
        print(f"      rows={r['max_table_rows']:>2} sep={str(r['has_separator']):5} "
              f"trunc={str(r['truncated']):5} complete={r['complete']} :: {r['query'][:50]!r}")


# ---------------------------------------------------------------------------
# M6 procedure / step completeness
# ---------------------------------------------------------------------------
_STEP_RE = re.compile(r"(?:^|\n)\s*(?:step\s*)?(\d{1,2})[\.\):]", re.IGNORECASE)


def m6():
    hdr("M6", "Procedure/step completeness — contiguous steps, not 1,3,7  (10 step queries)")
    rows, good = [], 0
    for q in STEP_QUERIES:
        res = R(q, top_k=5, doc_type="sop")
        best = None
        for c in res.chunks:
            nums = [int(m) for m in _STEP_RE.findall(c.text or "")]
            if len(nums) >= 2:
                contiguous = nums == list(range(nums[0], nums[0] + len(nums)))
                if best is None or (contiguous and not best[1]):
                    best = (nums, contiguous)
        if best is None:
            # fall back to any doc_type (some procedures live in OEM manuals)
            res = R(q, top_k=5)
            for c in res.chunks:
                nums = [int(m) for m in _STEP_RE.findall(c.text or "")]
                if len(nums) >= 2:
                    contiguous = nums == list(range(nums[0], nums[0] + len(nums)))
                    if best is None or (contiguous and not best[1]):
                        best = (nums, contiguous)
        ok = best is not None and best[1]
        good += int(ok)
        rows.append({"query": q, "returned": len(res.chunks),
                     "steps_found": best[0] if best else [], "contiguous": best[1] if best else None})
    score = good / len(STEP_QUERIES)
    report["M6_step_completeness"] = {"score": round(score, 3), "rows": rows,
                                     "grade": pct_grade(score, 0.80, 0.60)}
    print(f"   {report['M6_step_completeness']['grade']:8} = {score:.0%} of procedure queries returned a "
          f"contiguous step sequence")
    for r in rows:
        print(f"      steps={str(r['steps_found']):24} contiguous={r['contiguous']} :: {r['query'][:48]!r}")


# ---------------------------------------------------------------------------
# M7 citation integrity (source present + text un-mangled)
# ---------------------------------------------------------------------------
_MANGLE_RE = re.compile(r"E_B_M|Class_B|Warranty void\b", re.IGNORECASE)


def m7():
    hdr("M7", "Citation integrity — every chunk sourced & text un-mangled  (all returned chunks)")
    total, sourced, mangled = 0, 0, 0
    examples = []
    for q, _, _ in LABELED:
        for c in R(q, top_k=5).chunks:
            total += 1
            if (c.source_document or "").strip():
                sourced += 1
            if _MANGLE_RE.search(c.text or ""):
                mangled += 1
                if len(examples) < 5:
                    m = _MANGLE_RE.search(c.text).group(0)
                    examples.append({"source": c.source_document, "mangled_token": m})
    src_rate = sourced / total if total else 0.0
    mangle_free = 1 - (mangled / total) if total else 1.0
    report["M7_citation_integrity"] = {
        "chunks_examined": total, "source_present_rate": round(src_rate, 3),
        "mangle_free_rate": round(mangle_free, 3), "mangled_chunks": mangled,
        "examples": examples,
        "grade": pct_grade(min(src_rate, mangle_free), 1.0, 0.98)}
    print(f"   {report['M7_citation_integrity']['grade']:8} = source_present {src_rate:.0%}, "
          f"un-mangled {mangle_free:.0%}  ({mangled} mangled of {total} chunks)")
    for e in examples:
        print(f"      MANGLED '{e['mangled_token']}' in {e['source']}")


# ---------------------------------------------------------------------------
# M8 metadata-filter precision (infer_metadata harm)
# ---------------------------------------------------------------------------
def _above_floor_count(vec, model_family=None):
    must = [FieldCondition(key="document_status", match=MatchValue(value="active"))]
    if model_family:
        must.append(FieldCondition(key="model_family", match=MatchValue(value=model_family)))
    pts = _get_qdrant_client().query_points(
        collection_name=COLLECTION_NAME, query=vec, query_filter=Filter(must=must), limit=20).points
    return sum(1 for p in pts if p.score >= CONFIDENCE_FLOOR)


def m8():
    hdr("M8", "Metadata-filter precision — does infer_metadata kill recall?  (10 trigger queries)")
    rows, harmed = [], 0
    for q in TRIGGER_QUERIES:
        clean, parsed = parse_agentic_metadata(q)
        model = parsed.get("model_family") or infer_metadata(clean).get("model_family")
        vec = embed(clean)
        without = _above_floor_count(vec, None)
        with_f = _above_floor_count(vec, model) if model else without
        kills = model is not None and without > 0 and with_f == 0
        reduces = model is not None and with_f < without
        harmed += int(kills)
        rows.append({"query": q, "inferred_model_family": model,
                     "above_floor_without_filter": without, "above_floor_with_filter": with_f,
                     "recall_killed": kills, "recall_reduced": reduces})
    score = 1 - harmed / len(TRIGGER_QUERIES)  # 1.0 = no harm
    report["M8_filter_precision"] = {"score": round(score, 3), "queries_recall_killed": harmed,
                                    "rows": rows, "grade": pct_grade(score, 1.0, 0.80)}
    print(f"   {report['M8_filter_precision']['grade']:8} = inferred filter KILLS all above-floor "
          f"candidates on {harmed}/{len(TRIGGER_QUERIES)} trigger queries")
    for r in rows:
        flag = "  <== RECALL KILLED" if r["recall_killed"] else ("  (reduced)" if r["recall_reduced"] else "")
        print(f"      model={str(r['inferred_model_family']):12} without={r['above_floor_without_filter']:>2} "
              f"with={r['above_floor_with_filter']:>2}{flag} :: {r['query'][:34]!r}")


# ---------------------------------------------------------------------------
# M9 paraphrase robustness
# ---------------------------------------------------------------------------
def m9():
    hdr("M9", "Paraphrase robustness — same intent -> same top source  (4 groups x 3)")
    rows, consistent = [], 0
    for name, variants in PARAPHRASE_GROUPS.items():
        tops = []
        for v in variants:
            res = R(v, top_k=5)
            tops.append(res.chunks[0].source_document if res.chunks else None)
        agree = len({t for t in tops if t}) == 1 and all(tops)
        consistent += int(agree)
        rows.append({"group": name, "top_sources": tops, "consistent": agree})
    score = consistent / len(PARAPHRASE_GROUPS)
    report["M9_paraphrase_robustness"] = {"score": round(score, 3), "rows": rows,
                                         "grade": pct_grade(score, 0.80, 0.60)}
    print(f"   {report['M9_paraphrase_robustness']['grade']:8} = {score:.0%} of groups return the same "
          f"top source across all paraphrases")
    for r in rows:
        print(f"      {'OK ' if r['consistent'] else 'VARY'}  {r['group']:16} -> {r['top_sources']}")


# ---------------------------------------------------------------------------
# M10 determinism
# ---------------------------------------------------------------------------
def m10():
    hdr("M10", "Determinism — identical results on repeat  (16 queries x2)")
    rows, identical = [], 0
    for q, _, _ in LABELED:
        a = R(q, top_k=5)
        b = R(q, top_k=5)
        ka = [(c.chunk_id, round(c.score, 4)) for c in a.chunks]
        kb = [(c.chunk_id, round(c.score, 4)) for c in b.chunks]
        same = ka == kb
        identical += int(same)
        rows.append({"query": q, "identical": same})
    score = identical / len(LABELED)
    report["M10_determinism"] = {"score": round(score, 3), "rows": rows,
                                "grade": pct_grade(score, 1.0, 0.95)}
    print(f"   {report['M10_determinism']['grade']:8} = {score:.0%} of queries return identical "
          f"(chunk_id, score) on repeat")


# ---------------------------------------------------------------------------
# M11 latency
# ---------------------------------------------------------------------------
def m11():
    hdr("M11", "Latency — retrieval wall-clock across the whole run")
    if not LAT:
        return
    s = sorted(LAT)
    p50 = statistics.median(s)
    p95 = s[min(len(s) - 1, int(0.95 * len(s)))]
    report["M11_latency"] = {"calls": len(s), "p50_ms": round(p50, 1), "p95_ms": round(p95, 1),
                            "max_ms": round(max(s), 1),
                            "grade": pct_grade(1 if p95 < 1500 else (0.5 if p95 < 3000 else 0), 1, 0.5)}
    print(f"   {report['M11_latency']['grade']:8} = p50 {p50:.0f}ms  p95 {p95:.0f}ms  "
          f"max {max(s):.0f}ms  over {len(s)} calls")


# ---------------------------------------------------------------------------
# M12 faithfulness (optional, LLM-judged)
# ---------------------------------------------------------------------------
def m12():
    hdr("M12", "Faithfulness — generated answer grounded in retrieved context  (LLM-judged)")
    try:
        from llm import router
    except Exception as e:  # noqa: BLE001
        print(f"   SKIPPED — cannot import llm.router ({e})")
        return
    rows, grounded, ran = [], 0, 0
    for q, _, _ in LABELED[:10]:
        res = R(q, top_k=5)
        ctx = "\n\n".join((c.text or "")[:1200] for c in res.chunks)
        if not ctx.strip():
            rows.append({"query": q, "verdict": "NO_CONTEXT"})
            continue
        try:
            ans = router.generate(
                f"Answer the question using ONLY the context below. If the context does not "
                f"contain the answer, reply exactly 'NOT IN CONTEXT'.\n\nContext:\n{ctx}\n\n"
                f"Question: {q}\nAnswer:", role="articulation")
            verdict = router.generate(
                f"Context:\n{ctx}\n\nAnswer:\n{ans}\n\nIs every factual claim in the Answer "
                f"directly supported by the Context? Reply only YES or NO.", role="articulation")
        except Exception as e:  # noqa: BLE001
            print(f"   SKIPPED at query {ran+1} — LLM call failed ({type(e).__name__}); "
                  f"NVIDIA free tier may be queued. Core metrics above are unaffected.")
            report["M12_faithfulness"] = {"status": "partial/failed", "ran": ran}
            return
        ran += 1
        g = verdict.strip().upper().startswith("YES")
        grounded += int(g)
        rows.append({"query": q, "grounded": g, "answer_head": ans[:100]})
    if ran:
        score = grounded / ran
        report["M12_faithfulness"] = {"score": round(score, 3), "ran": ran, "rows": rows,
                                     "grade": pct_grade(score, 0.90, 0.75)}
        print(f"   {report['M12_faithfulness']['grade']:8} = {score:.0%} of answers fully grounded "
              f"in retrieved context ({grounded}/{ran})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="also run M12 faithfulness (uses NVIDIA API)")
    args = ap.parse_args()

    print("=" * 100)
    print("ENGINPILOT ENTERPRISE RAG QUALITY BENCHMARK  (READ-ONLY)  — collection:", COLLECTION_NAME)
    print("=" * 100)
    embed("warmup")

    m1_m2_m3(); m4(); m5(); m6(); m7(); m8(); m9(); m10(); m11()
    if args.llm:
        m12()

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print("\n" + "=" * 100)
    print("SCORECARD")
    print("=" * 100)
    order = ["M1_recall", "M2_precision", "M3_relevance", "M4_hallucination_resistance",
             "M5_table_integrity", "M6_step_completeness", "M7_citation_integrity",
             "M8_filter_precision", "M9_paraphrase_robustness", "M10_determinism",
             "M11_latency", "M12_faithfulness"]
    for k in order:
        if k in report and "grade" in report[k]:
            sc = report[k].get("score")
            scs = f"{sc:.0%}" if isinstance(sc, (int, float)) else "-"
            print(f"   {report[k]['grade']:9} {k:32} {scs}")
    grades = [report[k]["grade"] for k in order if k in report and "grade" in report[k]]
    fails = grades.count("FAIL"); degr = grades.count("DEGRADED"); passes = grades.count("PASS")
    print(f"\n   TOTALS: {passes} PASS / {degr} DEGRADED / {fails} FAIL   (of {len(grades)} graded)")
    print(f"   full report -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
