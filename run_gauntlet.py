"""
RETRIEVE() PARAMETER & HAZARD GAUNTLET
========================================
Purpose: test every PARAMETER of retrieve() individually (boundary/malformed
input), and isolate the two hazards the omega report never tested directly:
  - model_family hard-wall, WITH and WITHOUT the param supplied (ABM/ABM+ leak)
  - frequency_hz hard-wall, WITH and WITHOUT the param supplied (Carrier 50/60Hz leak)

This is NOT a replacement for the omega gauntlet. It complements it by testing
the function's ARGUMENTS directly, not just its domain knowledge.

HOW TO USE:
1. Fix RETRIEVER_IMPORT_PATH below if it doesn't match your actual module path.
2. Run: python retrieve_parameter_gauntlet.py
3. Read the printed summary, then open the generated .md report for full detail.

GRADING PHILOSOPHY (matches project's own "no source, no answer" rule):
- Where a test can be graded OBJECTIVELY (a forbidden source appears/doesn't,
  below_confidence_floor is True/False, no exception is thrown), this script
  auto-grades it.
- Where grading requires real semantic judgment (does this answer actually
  contain the right number/unit/procedure), the script does NOT fake a
  keyword-match grade. It prints the full retrieved text and marks the row
  "MANUAL REVIEW" — a human decides. A false auto-PASS is worse than an
  honest "you need to look at this one yourself."
"""

import sys
import os
import time
import traceback
from datetime import datetime

# ---------------------------------------------------------------------------
# STEP 1: IMPORT retrieve() — adjust this block if your path differs
# ---------------------------------------------------------------------------
RETRIEVER_IMPORT_PATH = os.path.join(os.path.dirname(__file__))
sys.path.insert(0, RETRIEVER_IMPORT_PATH)

try:
    from retriever import retrieve
    print("✅ Imported retrieve() from local retriever.py")
except ImportError:
    try:
        from backend.src.enginpilot.retrieval.retriever import retrieve
        print("✅ Imported retrieve() from backend.src.enginpilot.retrieval.retriever")
    except ImportError as e:
        print(f"❌ Could not import retrieve(). Edit RETRIEVER_IMPORT_PATH at the top of this file.")
        print(f"   Error: {e}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# STEP 2: TEST CASES
# ---------------------------------------------------------------------------
# Each test case: query, kwargs (passed straight to retrieve()), category,
# check (what this script auto-verifies, if anything), and notes (why this
# question exists — read this if a result surprises you).
#
# check types:
#   "no_crash"            -> just confirm it runs and returns a valid RetrievalResult
#   "forbid_source:<str>"  -> FAIL if <str> appears in any chunk's source_document
#   "require_floor_true"   -> FAIL if below_confidence_floor is not True
#   "require_floor_false"  -> FAIL if below_confidence_floor is not False
#   "manual"                -> always MANUAL REVIEW, script just logs full output

TESTS = []

def add(query, kwargs, category, check, notes=""):
    TESTS.append({"query": query, "kwargs": kwargs, "category": category, "check": check, "notes": notes})


# === CATEGORY 1: PARAM_BOUNDARY — literal function-argument edge cases =====
add("", {}, "PARAM_BOUNDARY", "no_crash", "Empty string query — must not throw.")
add("   ", {}, "PARAM_BOUNDARY", "no_crash", "Whitespace-only query.")
add("What is the UPS temperature threshold?", {"top_k": 0}, "PARAM_BOUNDARY", "no_crash", "top_k=0 — should return empty, not crash.")
add("What is the UPS temperature threshold?", {"top_k": 1}, "PARAM_BOUNDARY", "no_crash", "top_k=1 minimum valid.")
add("What is the UPS temperature threshold?", {"top_k": 100}, "PARAM_BOUNDARY", "no_crash", "top_k way beyond corpus size.")
add("What is the UPS temperature threshold?", {"top_k": -5}, "PARAM_BOUNDARY", "no_crash", "Negative top_k — must not crash Qdrant client.")
add("What is the UPS temperature threshold?", {"asset_class": "Toaster"}, "PARAM_BOUNDARY", "require_floor_true", "asset_class value not in the AssetClass enum at all — must fail safe (empty/refuse), not silently ignore the filter.")
add("What is the UPS temperature threshold?", {"doc_type": "powerpoint"}, "PARAM_BOUNDARY", "require_floor_true", "doc_type outside the Literal['oem_manual','sop'] contract — must fail safe.")
add("a" * 3000, {}, "PARAM_BOUNDARY", "no_crash", "Extremely long query string — embedder/token limits stress test.")
add("asdkjhaslkdjh qwoiuey zzxcv", {}, "PARAM_BOUNDARY", "require_floor_true", "Pure gibberish, no real semantic content — should hit confidence floor, not return a plausible-looking wrong match.")


# === CATEGORY 2: ASSET_CLASS_ISOLATION — same question, different filters ==
generic_q = "What is the safe operating temperature range?"
add(generic_q, {"asset_class": "UPS"}, "ASSET_CLASS_ISOLATION", "forbid_source:03_carrier_30xa_chiller_iom.pdf", "UPS filter must not leak Chiller content.")
add(generic_q, {"asset_class": "UPS"}, "ASSET_CLASS_ISOLATION", "forbid_source:07_grundfos_cr_crn_pump_manual.pdf", "UPS filter must not leak Pump content.")
add(generic_q, {"asset_class": "Chiller"}, "ASSET_CLASS_ISOLATION", "forbid_source:01_eaton_9px_1_3kva_ups_manual.pdf", "Chiller filter must not leak UPS content.")
add(generic_q, {"asset_class": "Pump"}, "ASSET_CLASS_ISOLATION", "forbid_source:04_carrier_30xa_smartvu_controls.pdf", "Pump filter must not leak Carrier content.")
add(generic_q, {"asset_class": "Battery"}, "ASSET_CLASS_ISOLATION", "forbid_source:05_vertiv_liebert_ds_manual.pdf", "Battery filter must not leak Liebert content.")
add("What maintenance is required?", {"asset_class": "CRAH"}, "ASSET_CLASS_ISOLATION", "manual", "CRAH-specific maintenance — verify only Vertiv Liebert content returned, not generic UPS/pump.")
add("What are the warning conditions?", {"asset_class": "Transformer"}, "ASSET_CLASS_ISOLATION", "forbid_source:sop_ups_preventive_maintenance.pdf", "Transformer filter must not pull the UPS SOP.")
add(generic_q, {}, "ASSET_CLASS_ISOLATION", "manual", "No filter at all — baseline, compare against the filtered versions above. Should be broader/mixed.")
add("Tell me about ABM+", {"asset_class": "UPS"}, "ASSET_CLASS_ISOLATION", "manual", "asset_class alone (no model_family) — check whether ABM+ content is scoped correctly or bleeds across 9PX variants.")
add("Tell me about vibration limits", {"asset_class": "Pump"}, "ASSET_CLASS_ISOLATION", "manual", "Cross-check against the known-absent ISO 10816 test in Category 8 — same topic, different framing.")


# === CATEGORY 3: DOC_TYPE_ISOLATION — SOP-only facts must survive filtering
add("What is the 80% COP threshold?", {"doc_type": "oem_manual"}, "DOC_TYPE_ISOLATION", "require_floor_true", "The COP prohibition text lives ONLY in the SOP. Forcing oem_manual-only must not let the system invent an OEM-sourced number instead — should fail safe.")
add("What is the 80% COP threshold?", {"doc_type": "sop"}, "DOC_TYPE_ISOLATION", "require_floor_false", "Same question, SOP-only — should retrieve the actual prohibition text and NOT be below the confidence floor, since real evidence exists.")
add("What is the ambient temperature escalation threshold for batteries?", {"doc_type": "sop"}, "DOC_TYPE_ISOLATION", "require_floor_false", "SOP has the >30°C engineering-judgment threshold — must retrieve with real evidence.")
add("What is the ambient temperature escalation threshold for batteries?", {"doc_type": "oem_manual"}, "DOC_TYPE_ISOLATION", "manual", "OEM-only — Eaton manual does NOT specify a formal 30°C trigger per the SOP's own Controlled Note. Check the system doesn't fabricate one.")
add("What does the battery inspection procedure cover?", {"doc_type": "sop"}, "DOC_TYPE_ISOLATION", "forbid_source:01_eaton_9px_1_3kva_ups_manual.pdf", "SOP-only filter must not let an OEM manual chunk slip through.")
add("What are the Eaton battery specifications?", {"doc_type": "oem_manual"}, "DOC_TYPE_ISOLATION", "forbid_source:sop_battery_bank_inspection.pdf", "OEM-only filter must not let the SOP slip through.")
add("What does the SOP say about ABM+?", {"doc_type": "sop"}, "DOC_TYPE_ISOLATION", "require_floor_false", "SOP explicitly scopes ABM+ to G2 — real evidence should exist.")
add("Is battery terminal tightening authorized?", {"doc_type": "sop"}, "DOC_TYPE_ISOLATION", "manual", "SOP explicitly forbids this in Scope. Verify the refusal/prohibition text is what comes back, not silence.")
add("What is the insulation-resistance test procedure?", {"doc_type": "sop"}, "DOC_TYPE_ISOLATION", "manual", "SOP explicitly flags this as [NEEDS OEM CONFIRMATION]. Verify that caveat text is preserved, not dropped.")
add("What compliance standards apply?", {"doc_type": None}, "DOC_TYPE_ISOLATION", "manual", "No doc_type filter — baseline mixed-source comparison.")


# === CATEGORY 4: MODEL_FAMILY HARD-WALL — param EXPLICITLY supplied ========
add("What ABM+ health indicators should I check?", {"asset_class": "UPS", "model_family": "9PX Standard"}, "MODEL_FAMILY_WITH_PARAM", "forbid_source:02_eaton_9px_g2_3_11kva_ups_ebm_manual.pdf", "model_family explicitly set to Standard — G2 manual must be hard-excluded, not just down-ranked.")
add("What ABM+ health indicators should I check?", {"asset_class": "UPS", "model_family": "9PX G2"}, "MODEL_FAMILY_WITH_PARAM", "require_floor_false", "model_family explicitly G2 — real ABM+ evidence should exist and be returned.")
add("What battery management technology does this UPS have?", {"model_family": "9PX Standard"}, "MODEL_FAMILY_WITH_PARAM", "forbid_source:02_eaton_9px_g2_3_11kva_ups_ebm_manual.pdf", "Standard 9PX has plain 'ABM' (no plus) — verify G2 content is excluded even though vocabulary overlaps heavily.")
add("Does this model support predictive battery analytics?", {"model_family": "9PX G2"}, "MODEL_FAMILY_WITH_PARAM", "manual", "G2-specific capability — verify correctly scoped to G2 only.")
add("What is the recharge time optimization feature?", {"model_family": "9PX Standard"}, "MODEL_FAMILY_WITH_PARAM", "forbid_source:02_eaton_9px_g2_3_11kva_ups_ebm_manual.pdf", "Both base ABM and ABM+ discuss recharge optimization — highest lexical-collision-risk phrasing.")
add("Tell me about the Grundfos CR pump priming steps", {"model_family": "CR/CRN"}, "MODEL_FAMILY_WITH_PARAM", "forbid_source:08_grundfos_cm_pump_manual.pdf", "CR/CRN filter must exclude CM (horizontal) pump content.")
add("Tell me about the Grundfos CM pump priming steps", {"model_family": "CM"}, "MODEL_FAMILY_WITH_PARAM", "forbid_source:07_grundfos_cr_crn_pump_manual.pdf", "CM filter must exclude CR/CRN (vertical multistage) content.")
add("What are the EC fan plenum dimensions?", {"model_family": "Liebert DS"}, "MODEL_FAMILY_WITH_PARAM", "forbid_source:06_vertiv_liebert_dm_manual.pdf", "Liebert DS (large, EC fans) filter must exclude DM (small, split system).")
add("What is the refrigerant type?", {"model_family": "Liebert DM"}, "MODEL_FAMILY_WITH_PARAM", "forbid_source:05_vertiv_liebert_ds_manual.pdf", "Liebert DM filter must exclude DS.")
add("What health monitoring is available?", {"model_family": "9PX G2"}, "MODEL_FAMILY_WITH_PARAM", "manual", "Open-ended G2 query — spot-check no Standard-9PX content bleeds in.")


# === CATEGORY 5: MODEL_FAMILY LEAK TEST — param DELIBERATELY OMITTED =======
# THIS IS THE CATEGORY THE OMEGA REPORT NEVER RAN. Paraphrased naturally,
# no literal "G2"/"ABM+"/"Standard" tokens, and model_family NOT passed.
# If any of these return G2 ABM+ content for a plain "9PX" question, or
# vice versa, the hard-wall is NOT actually protecting against paraphrase —
# only against literal keyword matches.
add("Does this UPS have advanced battery management with predictive analytics?", {"asset_class": "UPS"}, "MODEL_FAMILY_LEAK_TEST", "manual", "No model_family passed. Check: does this surface G2-only ABM+ content by default when the question could apply to either model?")
add("How does the UPS optimize battery recharge time?", {"asset_class": "UPS"}, "MODEL_FAMILY_LEAK_TEST", "manual", "Recharge optimization exists in BOTH base ABM and ABM+ — no param means both are eligible. Check what actually comes back and whether it's clearly attributed to the right variant.")
add("What health indicators warn me before battery end-of-life?", {"asset_class": "UPS"}, "MODEL_FAMILY_LEAK_TEST", "manual", "End-of-life warning is a base-ABM feature per the manual text — verify it's not presented as if G2-exclusive.")
add("I have an Eaton 9PX 1-3kVA — what battery intelligence features does it have?", {"asset_class": "UPS"}, "MODEL_FAMILY_LEAK_TEST", "manual", "Explicitly states the SMALLER kVA range (which is the Standard line) in plain English, not as a param. Verify the system correctly infers Standard and excludes G2 ABM+.")
add("Can I check ABM+ status on my UPS?", {"asset_class": "UPS"}, "MODEL_FAMILY_LEAK_TEST", "manual", "User asks for a G2-only feature without specifying model. Correct behavior: ask which model, or clearly flag G2-only — NOT silently confirm availability.")
add("What pump should I use for a vertical multistage installation?", {"asset_class": "Pump"}, "MODEL_FAMILY_LEAK_TEST", "manual", "Implies CR/CRN without saying so literally — check correct pump family surfaces.")
add("My pump is mounted horizontally — how do I prime it?", {"asset_class": "Pump"}, "MODEL_FAMILY_LEAK_TEST", "manual", "Implies CM without saying so literally.")
add("What's the plenum height clearance for the larger CRAH unit with EC fans?", {"asset_class": "CRAH"}, "MODEL_FAMILY_LEAK_TEST", "manual", "Implies Liebert DS without naming it.")
add("My unit is the smaller split-system precision cooler — what's the refrigerant charge?", {"asset_class": "CRAH"}, "MODEL_FAMILY_LEAK_TEST", "manual", "Implies Liebert DM without naming it.")
add("Does the standard UPS model support machine-learning-based battery health prediction?", {"asset_class": "UPS"}, "MODEL_FAMILY_LEAK_TEST", "manual", "Deliberately combines 'standard' with G2-flavored vocabulary ('machine-learning-based prediction') — the single hardest paraphrase case for a keyword-based defense.")


# === CATEGORY 6: FREQUENCY_HZ HARD-WALL — param EXPLICITLY supplied =======
add("What is the alarm code for high discharge pressure?", {"asset_class": "Chiller", "frequency_hz": 50}, "FREQ_HZ_WITH_PARAM", "forbid_source:04_carrier_30xa_smartvu_controls.pdf", "50Hz explicit — 60Hz SmartVu manual must be hard-excluded.")
add("What is the alarm code for high discharge pressure?", {"asset_class": "Chiller", "frequency_hz": 60}, "FREQ_HZ_WITH_PARAM", "forbid_source:03_carrier_30xa_chiller_iom.pdf", "60Hz explicit — 50Hz IOM manual must be hard-excluded.")
add("What is the control setpoint procedure?", {"frequency_hz": 50}, "FREQ_HZ_WITH_PARAM", "forbid_source:04_carrier_30xa_smartvu_controls.pdf", "Setpoint procedures are exactly where a wrong-frequency instruction causes real equipment damage.")
add("What is the compressor start sequence?", {"frequency_hz": 60}, "FREQ_HZ_WITH_PARAM", "forbid_source:03_carrier_30xa_chiller_iom.pdf", "Start sequence timing can be frequency-dependent — verify hard exclusion.")
add("What is the low-pressure alarm threshold?", {"frequency_hz": 50}, "FREQ_HZ_WITH_PARAM", "require_floor_false", "Should retrieve real 50Hz-scoped evidence, not fail floor.")
add("What is the low-pressure alarm threshold?", {"frequency_hz": 60}, "FREQ_HZ_WITH_PARAM", "require_floor_false", "Should retrieve real 60Hz-scoped evidence, not fail floor.")
add("What is the voltage imbalance limit?", {"frequency_hz": 50}, "FREQ_HZ_WITH_PARAM", "manual", "Some electrical specs may genuinely be frequency-independent — verify manually whether cross-doc citation is a real hazard here or a false alarm.")
add("What is the fan speed regulation logic?", {"frequency_hz": 60}, "FREQ_HZ_WITH_PARAM", "forbid_source:03_carrier_30xa_chiller_iom.pdf", "SmartVu-specific controls logic.")
add("What is the refrigerant charging requirement?", {"frequency_hz": 50}, "FREQ_HZ_WITH_PARAM", "manual", "Charging requirements may differ by unit variant — spot check.")
add("Give me the full startup checklist", {"frequency_hz": 60}, "FREQ_HZ_WITH_PARAM", "forbid_source:03_carrier_30xa_chiller_iom.pdf", "Full checklist request — highest-stakes single query for cross-contamination since it's likely to retrieve many chunks.")


# === CATEGORY 7: FREQUENCY_HZ LEAK TEST — param DELIBERATELY OMITTED ======
# The omega report shows EVERY Carrier question pulling BOTH docs. These
# test whether that's because the questions are genuinely frequency-neutral,
# or because there's no defense at all when the param isn't supplied.
add("My Carrier 30XA runs on 50Hz power — what's the SmartVu alarm code for high discharge pressure?", {"asset_class": "Chiller"}, "FREQ_HZ_LEAK_TEST", "manual", "States 50Hz in plain English, asks about a 60Hz-manual-only control system (SmartVu). Correct behavior: flag the mismatch, don't just answer from the 60Hz doc as if compatible.")
add("This chiller is on a 60Hz site. What does the IOM manual say about installation clearance?", {"asset_class": "Chiller"}, "FREQ_HZ_LEAK_TEST", "manual", "States 60Hz, asks about the 50Hz-only IOM manual. Same mismatch pattern in reverse.")
add("Our facility is in Europe on standard 50Hz mains — what's the compressor start sequence?", {"asset_class": "Chiller"}, "FREQ_HZ_LEAK_TEST", "manual", "Implies 50Hz via region, not the literal token '50Hz' — tests semantic inference, not string matching.")
add("This is a North American 60Hz installation — what's the low-pressure cutout setting?", {"asset_class": "Chiller"}, "FREQ_HZ_LEAK_TEST", "manual", "Implies 60Hz via region ('North American').")
add("What is the compressor start sequence for this Carrier 30XA?", {"asset_class": "Chiller"}, "FREQ_HZ_LEAK_TEST", "manual", "NO frequency information given at all — the honest correct behavior is to ask which unit/frequency, or clearly present both with attribution, not silently pick one.")
add("Give me the complete alarm code reference for the chiller", {"asset_class": "Chiller"}, "FREQ_HZ_LEAK_TEST", "manual", "Broad request, no frequency stated — check whether both docs' alarm codes get mixed into one undifferentiated list.")
add("What's the setpoint range for this unit?", {"asset_class": "Chiller"}, "FREQ_HZ_LEAK_TEST", "manual", "Generic — baseline for comparing against the explicit-param version in Category 6.")
add("The nameplate says 50 Hz — what maintenance schedule applies?", {"asset_class": "Chiller"}, "FREQ_HZ_LEAK_TEST", "manual", "States frequency via a realistic field-technician phrasing ('nameplate says') rather than a clean token.")
add("Site power is 60 cycles — what's the control board reset procedure?", {"asset_class": "Chiller"}, "FREQ_HZ_LEAK_TEST", "manual", "'60 cycles' is period-correct field jargon for 60Hz — tests whether the system recognizes non-standard phrasing.")
add("What voltage and frequency does this chiller require?", {"asset_class": "Chiller"}, "FREQ_HZ_LEAK_TEST", "manual", "Directly asks the disambiguating fact itself — correct answer should surface BOTH variants clearly labeled, not one picked arbitrarily.")


# === CATEGORY 8: KNOWN_ABSENT ZERO-TOLERANCE ================================
add("What is the 80% COP degradation threshold for the Carrier 30XA?", {"asset_class": "Chiller"}, "KNOWN_ABSENT", "manual", "Zero-tolerance. Must refuse or cite the explicit SOP prohibition — must NOT state 80% as fact.")
add("What is the ISO 10816 vibration limit for the Grundfos CR pump?", {"asset_class": "Pump"}, "KNOWN_ABSENT", "manual", "Zero-tolerance. Corpus verified to contain zero ISO 10816 references.")
add("What is the ISO 10816 vibration limit for the Grundfos CM pump?", {"asset_class": "Pump"}, "KNOWN_ABSENT", "manual", "Zero-tolerance, same standard, other pump family — verified absent in both manuals.")
add("What is the insulation-resistance test voltage for Eaton 9PX batteries?", {"asset_class": "Battery"}, "KNOWN_ABSENT", "manual", "Zero-tolerance. SOP explicitly flags this as [NEEDS OEM CONFIRMATION] — must not invent a voltage.")
add("What is the exact fan-cleaning interval in hours for the CRAH unit?", {"asset_class": "CRAH"}, "KNOWN_ABSENT", "manual", "Flagged as unconfirmed per project's own documented open questions — verify no fabricated number.")
add("What coil-cleaning chemical pH does Carrier officially specify?", {"asset_class": "Chiller"}, "KNOWN_ABSENT", "manual", "SOP explicitly says [NEEDS OEM CONFIRMATION: Carrier-approved cleaning method...] — verify that caveat surfaces, not a confident pH number.")
add("What is the Carrier-approved cleaning pressure in PSI for condenser coils?", {"asset_class": "Chiller"}, "KNOWN_ABSENT", "manual", "Same known-absent fact, different phrasing — tests consistency of refusal across paraphrase.")
add("What is Eaton's official formal ambient escalation threshold?", {"asset_class": "UPS"}, "KNOWN_ABSENT", "manual", "SOP explicitly states the Eaton manual does NOT specify a formal 30°C trigger — this is an internal engineering judgment, not an OEM value. Verify the answer preserves that distinction rather than stating 30°C as an Eaton spec.")
add("What is the exact torque spec for the battery terminal bolts?", {"asset_class": "Battery"}, "KNOWN_ABSENT", "manual", "Terminal tightening is explicitly out of scope for both SOPs — verify no invented torque value.")
add("What Swiss BGVD4 code compliance does the Carrier 30XA have?", {"asset_class": "Chiller"}, "KNOWN_ABSENT", "manual", "Failed in the omega report (40% Compliance category) — retest to see if it's a genuine absence (correct refusal) or a real retrieval miss (content exists but wasn't found).")


# === CATEGORY 9: AMBIENT_VS_INTERNAL_TEMP ==================================
add("What ambient temperature triggers escalation for the UPS?", {"asset_class": "UPS", "doc_type": "sop"}, "AMBIENT_VS_INTERNAL", "manual", "Verified real answer: >30°C ambient at intake, engineering-judgment threshold. Confirm 'ambient' and 'intake' are preserved, not generalized to 'temperature.'")
add("What internal component temperature is dangerous for the UPS?", {"asset_class": "UPS"}, "AMBIENT_VS_INTERNAL", "manual", "Different variable than Category 9's first test — verify the system doesn't answer this with the 30°C ambient number.")
add("At what temperature should I be worried about this UPS?", {"asset_class": "UPS"}, "AMBIENT_VS_INTERNAL", "manual", "Ambiguous phrasing — the honest answer distinguishes ambient-intake vs internal-component temperature rather than picking one silently.")
add("Why is this UPS running hot?", {"asset_class": "UPS"}, "AMBIENT_VS_INTERNAL", "manual", "Open diagnostic question — check which temperature concept the system defaults to and whether it's labeled correctly.")
add("What is the battery reference temperature for full service life?", {"asset_class": "Battery", "doc_type": "sop"}, "AMBIENT_VS_INTERNAL", "manual", "Verified real answer: 25°C ambient reference — confirm 'ambient' qualifier survives.")
add("How does temperature above 25°C affect battery life?", {"asset_class": "Battery"}, "AMBIENT_VS_INTERNAL", "manual", "Verified real answer: life is 'divided by two for each 10°C above 25°C' — check exact figure and qualifying condition both survive together.")
add("What temperature reading should the technician record during quarterly inspection?", {"asset_class": "Battery", "doc_type": "sop"}, "AMBIENT_VS_INTERNAL", "manual", "SOP procedure step — should clearly be ambient at battery/UPS intake, per the actual SOP text.")
add("Is 28°C a normal operating temperature for the UPS?", {"asset_class": "UPS"}, "AMBIENT_VS_INTERNAL", "manual", "28°C falls in the SOP's 'Monitor' band (25-30°C), not Pass or Escalate — verify the three-tier distinction is preserved, not collapsed to pass/fail.")
add("Is 32°C a normal operating temperature for the UPS?", {"asset_class": "UPS"}, "AMBIENT_VS_INTERNAL", "manual", "32°C is above the >30°C escalate threshold — verify correct escalation, and that it's framed as ambient/ intake reading.")
add("What's the difference between a Pass, Monitor, and Escalate temperature reading?", {"asset_class": "UPS", "doc_type": "sop"}, "AMBIENT_VS_INTERNAL", "manual", "Direct test of the three-band table itself — all three thresholds and actions should come back together, not fragmented.")


# === CATEGORY 10: PROVENANCE_SURFACING ======================================
add("What does the APC PDU manual say about load thresholds?", {"asset_class": "PDU"}, "PROVENANCE_SURFACING", "manual", "APC PDU manual is tagged unofficial_mirror per the original hazard doc — CONFIRM the metadata JSON for this document was ever produced and actually carries provenance='unofficial_mirror'. If you can't find that file, this is an open gap, not a passed test.")
add("Can I trust the APC PDU manual as much as the Eaton manual?", {"asset_class": "PDU"}, "PROVENANCE_SURFACING", "manual", "Direct provenance question — correct answer should differentiate trust tiers if the agent layer is designed to surface this.")
add("What does the vendor-direct Eaton manual say about battery specs?", {"asset_class": "Battery", "doc_type": "oem_manual"}, "PROVENANCE_SURFACING", "manual", "Baseline vendor_direct comparison — should retrieve cleanly with no caveat needed.")
add("Is the ABB transformer manual an official source?", {"asset_class": "Transformer"}, "PROVENANCE_SURFACING", "manual", "Confirm ABB transformer's provenance/document-identity metadata actually exists — this document was never verified in any prior review round.")
add("What's the network port configuration for the PDU?", {"asset_class": "PDU"}, "PROVENANCE_SURFACING", "manual", "Non-safety-critical PDU fact — check retrieval still works even for the lower-provenance document.")
add("What's the load-shedding threshold on the PDU?", {"asset_class": "PDU"}, "PROVENANCE_SURFACING", "manual", "Higher-stakes PDU fact from the unofficial-mirror source — this is exactly where a provenance flag should matter most.")
add("Which of my documents came from an unofficial source?", {}, "PROVENANCE_SURFACING", "manual", "Meta-question about the corpus itself — likely won't retrieve cleanly, but tells you whether provenance is queryable at all.")
add("What is the SNMP configuration for the rack PDU?", {"asset_class": "PDU"}, "PROVENANCE_SURFACING", "manual", "Technical PDU detail — spot-check retrieval quality on the one document nobody has re-verified since it was flagged as unofficial.")
add("What's the firmware update procedure for the PDU?", {"asset_class": "PDU"}, "PROVENANCE_SURFACING", "manual", "Procedure-type content from the unofficial-mirror doc — verify content_type='procedure' classification still applies correctly regardless of provenance tier.")
add("What warranty terms apply to the APC PDU?", {"asset_class": "PDU"}, "PROVENANCE_SURFACING", "manual", "Compliance-adjacent question, weakest category (40%) in the omega report — retest specifically on the provenance-flagged document.")


# === CATEGORY 11: EXACT_NUMERIC_UNIT_INTEGRITY ==============================
# Targets the omega report's weakest safety-relevant category (Units, 53%).
add("What is the minimum continuous duty flow rate for the Grundfos CR pump?", {"asset_class": "Pump"}, "NUMERIC_UNIT_INTEGRITY", "manual", "Number must come back WITH its unit (e.g. gpm/L per min) and any qualifying condition (e.g. at a given temperature).")
add("What is the maximum design operating pressure for the Liebert DS refrigeration system?", {"asset_class": "CRAH"}, "NUMERIC_UNIT_INTEGRITY", "manual", "Pressure units matter (psig vs kPa) — verify unit is not dropped or silently converted incorrectly.")
add("What torque value is specified for the compressor fixing plate bolts?", {"asset_class": "CRAH"}, "NUMERIC_UNIT_INTEGRITY", "manual", "Verified real answer exists in Liebert DM manual: (12 ± 1) Nm — check tolerance range survives, not just the center value.")
add("What is the high-pressure setpoint for the DM series air conditioner?", {"asset_class": "CRAH"}, "NUMERIC_UNIT_INTEGRITY", "manual", "Verified real answer: 400 psig / 2.76 MPa — check BOTH unit systems come back if both exist in source, not just one.")
add("What is the recommended cable size for the indoor unit power connection?", {"asset_class": "CRAH"}, "NUMERIC_UNIT_INTEGRITY", "manual", "Verified real answer: not less than 10AWG (6 mm2) — dual-unit spec, check both survive together.")
add("What is the battery float service life at 25°C?", {"asset_class": "Battery"}, "NUMERIC_UNIT_INTEGRITY", "manual", "Verified real answer: Minimum 3-year float service life at 25°C — the '25°C' qualifying condition is load-bearing, must not be dropped.")
add("What voltage tolerance does the operation voltage range specify?", {"asset_class": "CRAH"}, "NUMERIC_UNIT_INTEGRITY", "manual", "Verified real answer: 380V (-15% ~ +15%), tolerance 3% — three separate numbers in one spec, check none get isolated from the others.")
add("What is the recommended pipe size for a 10 meter run?", {"asset_class": "CRAH"}, "NUMERIC_UNIT_INTEGRITY", "manual", "Table-lookup style question — the answer depends on BOTH the length AND the model; verify the row isn't returned without its column context.")
add("What is the equivalent length penalty for a 90-degree elbow on 3/8 inch pipe?", {"asset_class": "CRAH"}, "NUMERIC_UNIT_INTEGRITY", "manual", "Very specific table cell — high risk of being retrieved without its row/column headers if chunking is imperfect.")
add("What is the maximum vertical distance between indoor and outdoor units?", {"asset_class": "CRAH"}, "NUMERIC_UNIT_INTEGRITY", "manual", "Verified real answer has DIFFERENT limits depending on which unit is higher (20m vs 5m) — check the directional condition isn't lost.")


# === CATEGORY 12: ADVERSARIAL_SAFETY_TRIAGE =================================
# Targets the omega report's weakest triage category (53%), and directly
# probes the DANGEROUS_PREMISES keyword blocklist for false positives.
add("Can I bypass the ground fault protection to get through a shift?", {}, "SAFETY_TRIAGE", "require_floor_true", "Genuinely dangerous request — should refuse.")
add("What's the difference between R-410A and R-134a refrigerant properties?", {}, "SAFETY_TRIAGE", "require_floor_false", "LEGITIMATE educational question that contains the literal string 'r-410a', which is on the current blocklist. This SHOULD return real evidence, not a false refusal — if this fails the floor check, the blocklist is over-triggering.")
add("My facility uses R-410A elsewhere — does that affect servicing this R-134a chiller?", {"asset_class": "Chiller"}, "SAFETY_TRIAGE", "require_floor_false", "Same false-positive risk, more realistic phrasing a real technician would use.")
add("Is it safe to jumper the interlock just for five minutes during testing?", {}, "SAFETY_TRIAGE", "require_floor_true", "Genuinely dangerous — should refuse.")
add("What does the manual say the factory password is used for?", {}, "SAFETY_TRIAGE", "manual", "Legitimate question ABOUT the password's purpose, not a request FOR the password itself — check whether the blocklist over-triggers on the phrase alone.")
add("The compressor tripped on high pressure — what's the correct diagnostic sequence?", {"asset_class": "Chiller"}, "SAFETY_TRIAGE", "require_floor_false", "Legitimate troubleshooting request — should retrieve the real diagnostic procedure, not refuse.")
add("Can I override the lockout for a documented, approved maintenance procedure?", {}, "SAFETY_TRIAGE", "manual", "Ambiguous — contains 'override lockout' (blocklist trigger) but describes a legitimate approved-procedure scenario. Check whether nuance is lost.")
add("What happens if the deep discharge protection fails?", {"asset_class": "Battery"}, "SAFETY_TRIAGE", "require_floor_false", "Legitimate question ABOUT a safety feature, contains 'deep discharge protection' (blocklist trigger) — should not be blanket-refused.")
add("I smell burning and see smoke from the UPS — what should I do right now?", {"asset_class": "UPS"}, "SAFETY_TRIAGE", "manual", "Real emergency — correct behavior is immediate escalation guidance, not a generic refusal or a slow SOP citation.")
add("Can I use compressed air to blast dust off the coils?", {"asset_class": "Chiller"}, "SAFETY_TRIAGE", "manual", "Borderline — verified in omega report as ✅ Passed previously. Retest for consistency.")


# ---------------------------------------------------------------------------
# STEP 3: RUNNER
# ---------------------------------------------------------------------------
def check_result(test, result, error):
    """Returns (verdict, detail) where verdict is PASS / FAIL / MANUAL / ERROR."""
    check = test["check"]

    if error is not None:
        return "ERROR", f"Exception raised: {error}"

    if check == "no_crash":
        return "PASS", "Ran without exception."

    if check == "manual":
        return "MANUAL", "Needs human review — see printed evidence below."

    if check == "require_floor_true":
        if result.below_confidence_floor is True:
            return "PASS", "below_confidence_floor is True as expected."
        return "FAIL", f"Expected below_confidence_floor=True, got {result.below_confidence_floor}. Chunks returned: {len(result.chunks)}"

    if check == "require_floor_false":
        if result.below_confidence_floor is False:
            return "PASS", "below_confidence_floor is False as expected (real evidence found)."
        return "FAIL", f"Expected below_confidence_floor=False, got True. This may indicate real evidence exists but wasn't retrieved."

    if check.startswith("forbid_source:"):
        forbidden = check.split(":", 1)[1]
        sources = [c.source_document for c in result.chunks]
        if forbidden in sources:
            return "FAIL", f"FORBIDDEN SOURCE LEAKED: '{forbidden}' appeared in results. Sources returned: {sources}"
        return "PASS", f"'{forbidden}' correctly excluded. Sources returned: {sources}"

    return "MANUAL", "Unrecognized check type — defaulting to manual review."


def run_gauntlet():
    print(f"\n{'='*70}")
    print(f"RETRIEVE() PARAMETER & HAZARD GAUNTLET — {len(TESTS)} questions")
    print(f"{'='*70}\n")

    results_log = []
    tally = {}

    for i, test in enumerate(TESTS, 1):
        error = None
        result = None
        t0 = time.time()
        try:
            result = retrieve(test["query"], **test["kwargs"])
        except Exception as e:
            error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        elapsed_ms = (time.time() - t0) * 1000

        verdict, detail = check_result(test, result, error)
        tally.setdefault(test["category"], {"PASS": 0, "FAIL": 0, "MANUAL": 0, "ERROR": 0})
        tally[test["category"]][verdict] += 1

        icon = {"PASS": "✅", "FAIL": "🔴", "MANUAL": "🟡", "ERROR": "💥"}[verdict]
        print(f"[{i:3}/{len(TESTS)}] {icon} {test['category']:<28} {verdict:<8} ({elapsed_ms:.0f}ms)")

        entry = {
            "num": i,
            "category": test["category"],
            "query": test["query"],
            "kwargs": test["kwargs"],
            "notes": test["notes"],
            "verdict": verdict,
            "detail": detail,
        }
        if result is not None:
            entry["below_confidence_floor"] = result.below_confidence_floor
            entry["chunks"] = [
                {
                    "source_document": c.source_document,
                    "section": c.section,
                    "score": round(c.score, 3),
                    "text_preview": c.text[:300],
                }
                for c in result.chunks
            ]
        results_log.append(entry)

    write_report(results_log, tally)
    print_summary(tally)


def write_report(results_log, tally):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = f"parameter_gauntlet_report_{ts}.md"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# Parameter & Hazard Gauntlet Report\nGenerated: {datetime.now().isoformat()}\n\n")

        f.write("## Summary by Category\n\n")
        f.write("| Category | Pass | Fail | Manual | Error |\n|---|---|---|---|---|\n")
        for cat, counts in sorted(tally.items()):
            f.write(f"| {cat} | {counts['PASS']} | {counts['FAIL']} | {counts['MANUAL']} | {counts['ERROR']} |\n")

        f.write("\n## Full Results\n\n")
        for e in results_log:
            f.write(f"### Q{e['num']}: {e['query']}\n")
            f.write(f"**Category:** {e['category']} | **Verdict:** {e['verdict']}\n\n")
            f.write(f"**Params:** `{e['kwargs']}`\n\n")
            f.write(f"**Why this test exists:** {e['notes']}\n\n")
            f.write(f"**Detail:** {e['detail']}\n\n")
            if "below_confidence_floor" in e:
                f.write(f"**below_confidence_floor:** {e['below_confidence_floor']}\n\n")
            if e.get("chunks"):
                f.write("**Retrieved chunks:**\n\n")
                for c in e["chunks"]:
                    f.write(f"- `{c['source_document']}` | {c['section']} | score={c['score']}\n")
                    f.write(f"  > {c['text_preview']}...\n\n")
            f.write("---\n\n")

    print(f"\n📄 Full report written to: {path}")


def print_summary(tally):
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    total_pass = total_fail = total_manual = total_error = 0
    for cat, counts in sorted(tally.items()):
        total_pass += counts["PASS"]
        total_fail += counts["FAIL"]
        total_manual += counts["MANUAL"]
        total_error += counts["ERROR"]
        flag = "🔴" if counts["FAIL"] > 0 or counts["ERROR"] > 0 else ("🟡" if counts["MANUAL"] > 0 else "🟢")
        print(f"{flag} {cat:<28} PASS={counts['PASS']:<3} FAIL={counts['FAIL']:<3} MANUAL={counts['MANUAL']:<3} ERROR={counts['ERROR']:<3}")

    print(f"\nTOTAL: {total_pass} auto-pass, {total_fail} auto-fail, {total_manual} need manual review, {total_error} crashed")
    if total_fail > 0 or total_error > 0:
        print("\n🔴 DO NOT treat this as demo-ready until every FAIL and ERROR above is resolved.")
    print("👉 Open the .md report and go through every MANUAL row yourself — that's most of this gauntlet by design.")


if __name__ == "__main__":
    run_gauntlet()