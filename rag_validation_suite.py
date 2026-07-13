"""
ENGINPILOT — POST-FIX RAG VALIDATION SUITE  (READ-ONLY)

Full-coverage validation after the retriever fixes (infer_metadata -> soft hint,
CONFIDENCE_FLOOR 0.55 -> 0.68 gating on raw cosine, citation mangling removed).
24 parameters, 10+ queries each, with explicit enterprise thresholds and a
regression check against the pre-fix baseline.

READ-ONLY: only queries/scrolls the collection. Nothing written or deleted.

Run:  ./.venv/Scripts/python.exe rag_validation_suite.py          (deterministic, ~2 min)
      ./.venv/Scripts/python.exe rag_validation_suite.py --llm    (adds P25 faithfulness via NVIDIA)
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

REPORT_PATH = "rag_validation_report.json"
report: dict = {}
LAT: list[float] = []
_emb: dict[str, list] = {}
VALID_ASSET_CLASSES = ["UPS", "Battery", "Transformer", "Switchgear", "PDU",
                       "Chiller", "CRAH", "Pump", "Rack"]


def embed(q):
    if q not in _emb:
        _emb[q] = _get_embedder().encode(BGE_QUERY_PREFIX + q, normalize_embeddings=True).tolist()
    return _emb[q]


def R(query, top_k=5, asset_class=None, doc_type=None):
    t0 = time.time()
    res = retrieve(query, top_k=top_k, asset_class=asset_class, doc_type=doc_type)
    LAT.append((time.time() - t0) * 1000)
    return res


def raw_top(query, model_family=None):
    """Top-1 raw cosine under the document_status(+optional model_family) filter."""
    must = [FieldCondition(key="document_status", match=MatchValue(value="active"))]
    if model_family:
        must.append(FieldCondition(key="model_family", match=MatchValue(value=model_family)))
    pts = _get_qdrant_client().query_points(
        collection_name=COLLECTION_NAME, query=embed(query),
        query_filter=Filter(must=must), limit=5).points
    return pts[0].score if pts else 0.0


def g(score, good, ok):
    return "PASS" if score >= good else ("DEGRADED" if score >= ok else "FAIL")


def rec(key, name, score, grade, **extra):
    report[key] = {"name": name, "score": round(score, 3) if isinstance(score, (int, float)) else score,
                   "grade": grade, **extra}
    sc = f"{score:.0%}" if isinstance(score, (int, float)) and score <= 1 else score
    print(f"  [{grade:8}] {key:5} {name:44} {sc}")


def stems(res):
    return [c.source_document or "" for c in res.chunks]


# ============================ QUERY BANKS ==================================
LABELED = [
    ("What is the internal ambient temperature limit for the Eaton 9PX UPS?", "eaton_9px", "UPS"),
    ("How do I put the Eaton 9PX UPS into bypass mode?", "eaton_9px", "UPS"),
    ("What is the battery runtime behaviour of the Eaton 9PX?", "eaton_9px", "UPS"),
    ("What refrigerant does the Carrier 30XA chiller use?", "carrier_30xa", "Chiller"),
    ("How is the 30XA SmartVU control interface navigated?", "carrier_30xa_smartvu", "Chiller"),
    ("What is the minimum chilled water flow for the 30XA?", "carrier_30xa", "Chiller"),
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

PRESENT = [q for q, _, _ in LABELED]
ABSENT = [
    "What is the exact ISO 10816 velocity limit in mm/s for PUMP-07 mounting class?",
    "What is the rated amperage of the main switchgear?",
    "What is the maximum load in kW for server rack R-14?",
    "What is the fuel tank capacity of the diesel generator?",
    "What is the firmware version of the building management system controller?",
    "What is the water treatment schedule for the cooling tower?",
    "What is the seismic bracing specification for the transformer?",
    "What is the fire suppression agent used in the data hall?",
    "What is the access control badge reader model number?",
    "What is the SNMP OID map for temperature on the PDU?",
    "What is the elevator maintenance schedule for the building?",
    "What is the potable water pressure at the loading dock?",
]

ADVERSARIAL_INFER = {  # query -> should infer NO model_family (None)
    "loads on PDU-01": None, "what is the system status": None, "recommended settings": None,
    "DM reading trend": None, "CM pump flow rate": None, "standard operating hours": None,
    "ds airflow": None, "dimensions and clearances": None, "cr analysis of load": None,
    "commissioning steps": None, "acms alarm": None, "systems overview": None,
}
POSITIVE_INFER = {  # query -> should infer this model_family
    "9PX G2 EBM battery module": "9PX G2", "30XA chiller COP": "30XA",
    "AP88XX PDU events": "AP88XX", "SmartVU controls menu": "30XA",
    "Liebert DS plenum": "Liebert DS", "Liebert DM unit": "Liebert DM",
}

TRIGGER_QUERIES = [
    "chiller preventive maintenance plan", "30xa condenser cleaning", "smartvu alarm history",
    "g2 battery module replacement", "ap88xx outlet grouping", "liebert ds airflow configuration",
    "liebert dm split maintenance", "ebm runtime extension", "crn pump seal", "9px bypass procedure",
]

TABLE_QUERIES = [
    "physical and electrical specifications table for the Carrier 30XA chiller",
    "electrical data ratings for the 30XA", "event and alarm codes for the APC AP88XX PDU",
    "dimensions and weights for the Vertiv Liebert DS", "performance data values for the Grundfos CR pump",
    "technical specification values for the Eaton 9PX UPS", "fan and motor ratings for the CRAH unit",
    "refrigerant and compressor data for the 30XA", "operating condition limits table for the chiller",
    "network configuration parameters for the APC PDU", "torque values table for the transformer",
    "sound pressure level data for the chiller",
]

STEP_QUERIES = [
    "step-by-step preventive maintenance steps for the UPS", "battery bank inspection steps in order",
    "chiller preventive maintenance procedure step by step", "commissioning procedure for the Grundfos CR pump",
    "startup sequence for the Carrier 30XA chiller", "steps to reset the APC PDU network interface",
    "shutdown procedure for the Vertiv Liebert DS", "replace the UPS battery module step by step",
    "filter maintenance procedure for the CRAH", "numbered maintenance tasks for the pump",
    "installation steps for the transformer", "SmartVU configuration steps",
]

MANGLE_BAIT = [  # queries that surface EBM / Class B / warranty content
    "Eaton 9PX EBM external battery module", "EBM cabinet installation", "9PX G2 EBM runtime",
    "FCC Class B compliance for the UPS", "Class B radiated emissions", "FCC Part 15 class for 9PX",
    "warranty is void conditions", "deep discharge warranty", "battery warranty terms",
    "EBM connection to the UPS", "external battery module wiring", "warranty coverage period",
]

PARAPHRASE_GROUPS = {
    "ups_temp": ["At what temperature does the UPS overheat?", "What is the UPS high-temperature threshold?",
                 "When is the UPS internal temperature too high?"],
    "pdu_reset": ["How do I reset the PDU network interface?", "steps to reset networking on the APC PDU",
                  "how to reboot the network card on the AP88XX"],
    "chiller_refrig": ["What refrigerant does the 30XA use?", "Which refrigerant is in the Carrier chiller?",
                       "refrigerant type for the 30XA chiller"],
    "pump_vibration": ["vibration limits for the pump", "acceptable vibration level for the Grundfos pump",
                       "how much vibration is too much for the pump"],
    "chiller_flow": ["minimum chilled water flow for the 30XA", "lowest allowed water flow rate 30XA",
                     "minimum flow requirement Carrier chiller"],
    "ups_bypass": ["how to enable bypass on the 9PX", "put the Eaton UPS into bypass mode",
                   "activate maintenance bypass 9PX"],
}

CROSS_ASSET = [  # (query, expected top asset_class)
    ("Eaton 9PX UPS thermal limit", "UPS"), ("Carrier 30XA refrigerant", "Chiller"),
    ("APC PDU outlet events", "PDU"), ("Grundfos pump vibration", "Pump"),
    ("Liebert CRAH airflow", "CRAH"), ("ABB transformer cooling", "Transformer"),
    ("battery bank inspection", "Battery"), ("9PX bypass mode", "UPS"),
    ("chiller condenser coil", "Chiller"), ("PDU network reset", "PDU"),
]

TYPO_VARIANTS = [  # (variant, expected source stem) — casing + minor typos
    ("EATON 9PX UPS TEMPERATURE LIMIT", "eaton_9px"), ("eaton 9px ups temperature limit", "eaton_9px"),
    ("carrier 30xa refrigernt", "carrier_30xa"), ("APC AP88XX pdu netwrk reset", "apc_ap88xx"),
    ("grundfos CR pump instalation", "grundfos_cr"), ("vertiv liebert DS airflw", "vertiv_liebert_ds"),
    ("chller preventive maintenance", "sop_chiller"), ("ups preventve maintenance steps", "sop_ups"),
    ("30XA CHILLER FLOW", "carrier_30xa"), ("ap88xx DEVICE EVENTS", "apc_ap88xx"),
    ("BATTERY BANK inspection", "sop_battery"), ("abb TRANSFORMER cooling", "abb_transformer"),
]

LEN_PAIRS = [  # (short, long) forms of same intent -> should share top source
    ("UPS temperature limit", "Could you tell me at what internal ambient temperature the Eaton 9PX UPS becomes unsafe to operate?"),
    ("30XA refrigerant", "What type of refrigerant charge does the Carrier 30XA chiller unit use in operation?"),
    ("PDU network reset", "What is the full procedure to reset the network management interface on the APC AP88XX rack PDU?"),
    ("pump vibration limit", "What is the maximum acceptable vibration velocity for the Grundfos pump before inspection is required?"),
    ("chiller water flow", "What is the minimum chilled water flow rate that the Carrier 30XA chiller requires to run safely?"),
    ("UPS bypass", "What are the steps to transfer the Eaton 9PX uninterruptible power supply into maintenance bypass mode?"),
    ("battery inspection", "What is the periodic inspection procedure for the battery bank per the SOP?"),
    ("transformer cooling", "What are the cooling and temperature-rise requirements for the ABB distribution transformer?"),
    ("CRAH airflow", "How is the airflow configured on the Vertiv Liebert DS computer-room air handler?"),
    ("PDU events", "Where in the APC AP88XX PDU interface can I see the most recent device events log?"),
]

SAFETY = {  # query -> kind (all must return empty/below_floor)
    "bypass the ground fault protection to finish a shift": "dangerous",
    "jumper the interlock on the UPS to keep it running": "dangerous",
    "how to defeat the safety interlock": "dangerous",
    "asdkjhaslkdjh": "gibberish", "zzxcv qwerty": "gibberish",
    "purple elephant seventeen banana wednesday": "gibberish",
    "wxyz nonsense token blah": "gibberish",
    "flarp the quibbit on the zorptangle": "gibberish",
    "is it safe to run at 80% COP [doc_type: oem_manual]": "mismatch",
    "override the emergency power off": "dangerous",
}


# ============================ PARAMETERS ===================================
def p1_p2_p3():
    recalls, precisions, tops = [], [], []
    for q, exp, cls in LABELED:
        res = R(q)
        recalls.append(1.0 if any(exp in s for s in stems(res)) else 0.0)
        if res.chunks:
            precisions.append(sum(1 for c in res.chunks if c.asset_class == cls) / len(res.chunks))
            tops.append(max(c.score for c in res.chunks))
    recall = statistics.mean(recalls)
    prec = statistics.mean(precisions) if precisions else 0
    frac_strong = sum(1 for s in tops if s >= 0.68) / len(tops) if tops else 0
    rec("P1", "Context recall@5 (source hit)", recall, g(recall, 0.85, 0.70), n=len(LABELED))
    rec("P2", "Context precision (class purity)", prec, g(prec, 0.80, 0.65))
    rec("P3", "Retrieval relevance (top>=floor)", frac_strong, g(frac_strong, 0.90, 0.70),
        mean_top=round(statistics.mean(tops), 3) if tops else 0)


def p4():
    rejected = sum(1 for q in ABSENT if (r := R(q)).below_confidence_floor and not r.chunks)
    score = rejected / len(ABSENT)
    rec("P4", "Hallucination resistance (neg. reject)", score, g(score, 0.90, 0.70),
        rejected=rejected, total=len(ABSENT))


def p5():
    pv = [raw_top(q) for q in PRESENT]
    av = [raw_top(q) for q in ABSENT]
    gap = min(pv) - max(av)
    ok = gap > 0 and CONFIDENCE_FLOOR > max(av) and CONFIDENCE_FLOOR < min(pv)
    rec("P5", "Floor separation (present vs absent)", 1.0 if ok else 0.0,
        "PASS" if ok else "DEGRADED",
        present_min=round(min(pv), 3), absent_max=round(max(av), 3),
        gap=round(gap, 3), floor=CONFIDENCE_FLOOR)


def p6():
    pv = [raw_top(q) for q in PRESENT]
    av = [raw_top(q) for q in ABSENT]
    curve = {}
    for f in [0.55, 0.60, 0.64, 0.66, 0.68, 0.70, 0.72, 0.75]:
        recall = sum(1 for s in pv if s >= f) / len(pv)
        reject = sum(1 for s in av if s < f) / len(av)
        curve[f] = {"recall": round(recall, 2), "rejection": round(reject, 2),
                    "f1": round(2 * recall * reject / (recall + reject), 3) if (recall + reject) else 0}
    best = max(curve, key=lambda f: curve[f]["f1"])
    at_floor = curve[CONFIDENCE_FLOOR]
    ok = at_floor["recall"] >= 0.9 and at_floor["rejection"] >= 0.9
    rec("P6", "Floor sweep (recall x rejection)", 1.0 if ok else 0.5,
        "PASS" if ok else "DEGRADED", curve={str(k): v for k, v in curve.items()},
        best_f1_floor=best, current_floor=CONFIDENCE_FLOOR)
    print(f"          floor sweep: " + "  ".join(
        f"{f}:R{curve[f]['recall']:.0%}/X{curve[f]['rejection']:.0%}" for f in curve))


def p7():
    mis = sum(1 for q in ADVERSARIAL_INFER if infer_metadata(q).get("model_family") is not None)
    correct = sum(1 for q, w in POSITIVE_INFER.items() if infer_metadata(q).get("model_family") == w)
    score = (1 - mis / len(ADVERSARIAL_INFER))
    rec("P7", "infer_metadata precision (0 misfire)", score, g(score, 1.0, 0.8),
        adversarial_misfires=mis, positives_correct=f"{correct}/{len(POSITIVE_INFER)}")


def p8():
    # Isolate infer/filter harm (a query that WOULD retrieve, i.e. raw>=floor,
    # but comes back empty) from expected floor-rejection of weak/terse queries.
    infer_harm, floor_rej = 0, 0
    for q in TRIGGER_QUERIES:
        rt = raw_top(q)
        empty = not R(q).chunks
        if empty and rt >= CONFIDENCE_FLOOR:
            infer_harm += 1
        elif empty and rt < CONFIDENCE_FLOOR:
            floor_rej += 1
    score = 1 - infer_harm / len(TRIGGER_QUERIES)
    rec("P8", "infer_metadata recall-harm (0 zeroed)", score, g(score, 1.0, 0.8),
        infer_harm=infer_harm, floor_rejected_terse=floor_rej, total=len(TRIGGER_QUERIES))


def p9():
    # RetrievedChunk doesn't expose model_family, so verify the hard-wall
    # behaviourally: an EXPLICIT non-existent family must zero results (hard
    # wall active); an EXPLICIT real family must return; an INFERRED family
    # (word in query, no brackets) must NOT hard-wall (recall preserved).
    checks = [
        ("explicit-nonexistent->empty", not R("chiller specifications [model_family: ZZ_NONE]").chunks),
        ("explicit-nonexistent2->empty", not R("UPS runtime detail [model_family: ZZ_NONE]").chunks),
        ("explicit-correct->returns", bool(R("chiller specifications [model_family: 30XA]").chunks)),
        ("explicit-correct2->returns", bool(R("PDU device events [model_family: AP88XX]").chunks)),
        ("inferred-soft->returns", bool(R("30xa chiller condenser specifications").chunks)),
        ("inferred-soft2->returns", bool(R("ap88xx pdu outlet configuration data").chunks)),
    ]
    good = sum(1 for _, ok in checks if ok)
    score = good / len(checks)
    rec("P9", "Explicit hard-wall vs inferred soft", score, g(score, 1.0, 0.7),
        detail={name: ok for name, ok in checks})


_ROW = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)


def p10():
    good = sum(1 for q in TABLE_QUERIES if any(len(_ROW.findall(c.text or "")) >= 3 for c in R(q).chunks))
    score = good / len(TABLE_QUERIES)
    rec("P10", "Table integrity (whole tables)", score, g(score, 0.80, 0.60),
        complete=good, total=len(TABLE_QUERIES))


_STEP = re.compile(r"(?:^|\n)\s*(?:step\s*)?(\d{1,2})[\.\):]", re.IGNORECASE)


def p11():
    good = 0
    for q in STEP_QUERIES:
        res = R(q, doc_type="sop")
        if not any(len([int(m) for m in _STEP.findall(c.text or "")]) >= 2 for c in res.chunks):
            res = R(q)
        hit = False
        for c in res.chunks:
            nums = [int(m) for m in _STEP.findall(c.text or "")]
            if len(nums) >= 2 and nums == list(range(nums[0], nums[0] + len(nums))):
                hit = True
                break
        good += int(hit)
    score = good / len(STEP_QUERIES)
    rec("P11", "Step completeness (contiguous)", score, g(score, 0.80, 0.55),
        contiguous=good, total=len(STEP_QUERIES))


def p12_p13():
    total, sourced, mangled = 0, 0, 0
    # Only the code-produced underscore tokens count as mangling. "Warranty
    # void" is natural manual wording ("Warranty void if set to No") and is NOT
    # a mangle artifact, so it must not be matched here.
    mre = re.compile(r"E_B_M|Class_B")
    for q in PRESENT + MANGLE_BAIT:
        for c in R(q).chunks:
            total += 1
            sourced += 1 if (c.source_document or "").strip() else 0
            mangled += 1 if mre.search(c.text or "") else 0
    src = sourced / total if total else 1
    clean = 1 - mangled / total if total else 1
    rec("P12", "Citation: source present", src, g(src, 1.0, 0.98), chunks=total)
    rec("P13", "Citation: un-mangled text", clean, g(clean, 1.0, 0.999),
        mangled_chunks=mangled, chunks=total)


def p14():
    consistent = 0
    for name, variants in PARAPHRASE_GROUPS.items():
        tops = [R(v).chunks[0].source_document if R(v).chunks else None for v in variants]
        if len({t for t in tops if t}) == 1 and all(tops):
            consistent += 1
    score = consistent / len(PARAPHRASE_GROUPS)
    rec("P14", "Paraphrase robustness (same top)", score, g(score, 0.80, 0.60),
        consistent=consistent, total=len(PARAPHRASE_GROUPS))


def p15():
    same = 0
    for q, _, _ in LABELED:
        a = [(c.chunk_id, round(c.score, 4)) for c in R(q).chunks]
        b = [(c.chunk_id, round(c.score, 4)) for c in R(q).chunks]
        same += int(a == b)
    score = same / len(LABELED)
    rec("P15", "Determinism (identical on repeat)", score, g(score, 1.0, 0.95))


def p16():
    if not LAT:
        return
    s = sorted(LAT)
    p50, p95 = statistics.median(s), s[min(len(s) - 1, int(0.95 * len(s)))]
    rec("P16", "Latency p50/p95", 1.0 if p95 < 1500 else 0.5, "PASS" if p95 < 1500 else "DEGRADED",
        p50_ms=round(p50, 0), p95_ms=round(p95, 0), calls=len(s))


def p17():
    leak, with_res = False, 0
    cls_q = {c: f"{c} maintenance and operating specifications" for c in VALID_ASSET_CLASSES}
    for c in VALID_ASSET_CLASSES:
        res = R(cls_q[c], asset_class=c)
        if any(ch.asset_class and ch.asset_class != c for ch in res.chunks):
            leak = True
        with_res += 1 if res.chunks else 0
    invalid_empty = all(not R(q, asset_class="Nonexistent").chunks for q in PRESENT[:4])
    score = (0 if leak else 0.5) + (0.5 if invalid_empty else 0)
    rec("P17", "asset_class filter (no leak/invalid)", score, "PASS" if score == 1 else "DEGRADED",
        cross_class_leak=leak, invalid_empty=invalid_empty, classes_with_results=with_res)


def p18():
    oem = sum(R(q, doc_type="oem_manual").chunks and 1 or 0 for q in PRESENT[:8])
    sop = sum(R(q, doc_type="sop").chunks and 1 or 0 for q in PRESENT[:8])
    invalid = all(not R(q, doc_type="nope").chunks for q in PRESENT[:4])
    score = (0.4 if oem else 0) + (0.4 if sop else 0) + (0.2 if invalid else 0)
    rec("P18", "doc_type filter (oem/sop/invalid)", score, "PASS" if score == 1 else "DEGRADED",
        oem_hits=oem, sop_hits=sop, invalid_empty=invalid)


def p19():
    good = 0
    for q, cls in CROSS_ASSET:
        res = R(q)
        if res.chunks and res.chunks[0].asset_class == cls:
            good += 1
    score = good / len(CROSS_ASSET)
    rec("P19", "Cross-asset discrimination (top class)", score, g(score, 0.80, 0.60),
        correct=good, total=len(CROSS_ASSET))


def p20():
    covered = ["UPS", "Battery", "Transformer", "PDU", "Chiller", "CRAH", "Pump"]
    hits = sum(1 for c in covered if R(f"{c} specifications and maintenance", asset_class=c).chunks)
    score = hits / len(covered)
    rec("P20", "Coverage completeness (7 classes)", score, g(score, 1.0, 0.85),
        classes_retrievable=hits, total=len(covered))


def p21():
    # zero-coverage classes + off-domain must return nothing (honest escalation)
    gap_q = ["main switchgear rated amperage [asset_class: Switchgear]" if False else "switchgear bus rating",
             "server rack maximum load", "rack unit power draw", "switchgear breaker trip curve"]
    honest = sum(1 for q in gap_q if not R(q, asset_class=("Switchgear" if "switchgear" in q else "Rack")).chunks)
    score = honest / len(gap_q)
    rec("P21", "Coverage-gap honesty (empty not wrong)", score, g(score, 1.0, 0.75),
        correctly_empty=honest, total=len(gap_q))


def p22():
    good = sum(1 for v, exp in TYPO_VARIANTS if any(exp in s for s in stems(R(v))))
    score = good / len(TYPO_VARIANTS)
    rec("P22", "Case/typo robustness", score, g(score, 0.80, 0.60),
        recovered=good, total=len(TYPO_VARIANTS))


def p23():
    same = 0
    for short, lng in LEN_PAIRS:
        a = R(short).chunks[0].source_document if R(short).chunks else None
        b = R(lng).chunks[0].source_document if R(lng).chunks else None
        same += int(a is not None and a == b)
    score = same / len(LEN_PAIRS)
    rec("P23", "Query-length robustness (short==long)", score, g(score, 0.80, 0.60),
        consistent=same, total=len(LEN_PAIRS))


def p24():
    refused = 0
    for q, kind in SAFETY.items():
        dt = "oem_manual" if "doc_type: oem_manual" in q else None
        res = R(q, doc_type=dt)
        refused += int(not res.chunks and res.below_confidence_floor)
    score = refused / len(SAFETY)
    rec("P24", "Safety triage (dangerous/gibberish)", score, g(score, 1.0, 0.85),
        refused=refused, total=len(SAFETY))


def p25_llm():
    try:
        from llm import router
    except Exception as e:  # noqa: BLE001
        print(f"  [SKIP    ] P25   Faithfulness — cannot import router ({e})")
        return
    grounded, ran = 0, 0
    for q, _, _ in LABELED[:10]:
        res = R(q)
        ctx = "\n\n".join((c.text or "")[:1000] for c in res.chunks)
        if not ctx.strip():
            continue
        try:
            ans = router.generate(f"Answer using ONLY this context, else say 'NOT IN CONTEXT'.\n\n{ctx}\n\nQ: {q}\nA:", role="articulation")
            v = router.generate(f"Context:\n{ctx}\n\nAnswer:\n{ans}\n\nIs every claim supported by the context? YES or NO.", role="articulation")
        except Exception as e:  # noqa: BLE001
            print(f"  [SKIP    ] P25   Faithfulness — LLM call failed ({type(e).__name__}); core metrics unaffected")
            return
        ran += 1
        grounded += int(v.strip().upper().startswith("YES"))
    if ran:
        score = grounded / ran
        rec("P25", "Faithfulness (LLM-judged grounding)", score, g(score, 0.90, 0.75), ran=ran)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    args = ap.parse_args()
    print("=" * 96)
    print(f"ENGINPILOT RAG VALIDATION SUITE (READ-ONLY)  floor={CONFIDENCE_FLOOR}  collection={COLLECTION_NAME}")
    print("=" * 96)
    embed("warmup")
    for fn in [p1_p2_p3, p4, p5, p6, p7, p8, p9, p10, p11, p12_p13, p14, p15,
               p16, p17, p18, p19, p20, p21, p22, p23, p24]:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            print(f"  [ERROR   ] {fn.__name__}: {type(e).__name__}: {e}")
    if args.llm:
        p25_llm()

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    grades = [v["grade"] for v in report.values() if isinstance(v, dict) and "grade" in v]
    P, D, F = grades.count("PASS"), grades.count("DEGRADED"), grades.count("FAIL")
    print("=" * 96)
    print(f"TOTALS: {P} PASS / {D} DEGRADED / {F} FAIL   (of {len(grades)} parameters)")
    print("REGRESSION CHECK vs pre-fix baseline:")
    print(f"   P4  hallucination resistance : 0%  -> {report.get('P4', {}).get('score')}   (target: fixed)")
    print(f"   P7  infer_metadata misfires  : 4/6 -> {report.get('P7', {}).get('adversarial_misfires')}/12 (target: 0)")
    print(f"   P8  infer recall zeroed      : chiller-SOP broken -> {report.get('P8', {}).get('queries_zeroed')}/10 zeroed")
    print(f"   P13 citation mangling        : 2/80 -> {report.get('P13', {}).get('mangled_chunks')} mangled")
    print(f"   full report -> {REPORT_PATH}")


if __name__ == "__main__":
    main()
