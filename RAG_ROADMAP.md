# ENGINPILOT RAG — Measured Diagnostic & Action Roadmap

**Generated from `rag_diagnostic.py` (read-only) against the live `enginpilot_docs` collection.**
Full machine report: `rag_diagnostic_report.json`. Every number below is measured, not inferred.
Governing scope: playbook EP-MVP-DC-001 (demo-grade "architecture rehearsal," per §2.2 — goal is *correct + upgrade-ready*, not full enterprise).

---

## 0. What the measurement changed about my static review (honesty first)

Running the harness **withdrew or downgraded four** of the concerns from my earlier read-only review. Stating this plainly so the roadmap isn't inflated:

| Earlier claim | Measured reality | Verdict |
|---|---|---|
| Lexical boost defeats the 0.55 floor | **0** chunks crossed the floor via boost across all golden queries; only 1 query got any boost at all | **Downgraded** — latent design smell, not currently breaking anything |
| `asset_class` raw-string filter is leak-prone | Invalid class → empty; **zero** cross-class leakage observed | **Withdrawn** — filter works correctly |
| Fragmented multi-step procedures | No fragmented step sequences detected on SOP retrieval | **Downgraded** — not observed (keep an eye on it) |
| Real gibberish isn't caught | Dangerous / mismatch / gibberish queries **all** correctly return empty (via the confidence floor, even when the hardcoded gibberish gate doesn't fire) | **Downgraded** — safety refusal works in practice |

This is exactly why we measured first.

---

## 1. Measured baseline (grades)

| Section | Grade | Key number |
|---|---|---|
| A — Environment / data | **DEGRADED** | 4,879 pts; 234 near-empty (4.8%); 293 dup texts; layer set on 0; mangleable tokens in 280 chunks |
| B — top_k sweep | PASS | no crash on k=0/-1; output caps at 5 (`MAX_EVIDENCE_UNITS`) regardless of k |
| C — asset_class filter | PASS | invalid→empty, no leakage — but only **7/9 classes have corpus coverage** (Switchgear + Rack = 0 docs); see #3b |
| D — doc_type filter | PASS | filters correctly |
| E — layer filter | PASS* | *layer is dead metadata (0/4879 set); filter always falls back |
| F — infer_metadata | **DEGRADED** | **4/6 adversarial queries misfire**; positives 3/3 |
| G — parse_agentic_metadata | PASS | brackets parse, malformed doesn't crash |
| H — floor vs boost | PASS | **0** floor-crossings via boost |
| J — safety triage | PASS | dangerous/mismatch/gibberish all refused |
| K — fragmentation | PASS | none detected |
| L — golden retrieval recall | **DEGRADED** | 2/10 raw — but see §2.1: only 3 cases are RAG-checkable, and the 1 real miss is caused by F |

---

## 2. Corrections, priority-ordered, with before→target

### TIER 0 — Retrieval correctness (breaks a demo scenario today)

**#1 — `infer_metadata` over-eager inference [HIGH — breaks Demo Scenario 2]**
`retriever.py:108-136`
- **Measured before:** 4/6 adversarial queries get a false `model_family` (`"loads on PDU-01"`→`Liebert DS`, `"DM reading"`→`Liebert DM`, `"CM pump flow"`→`CM`, `"standard operating hours"`→`9PX Standard`). Traced consequence: *"Generate a maintenance plan for Chiller-03."* → `"chiller"` substring → `model_family='30XA'` hard-wall → chiller SOP chunks (tagged `model_family='SOP'`) are excluded → **`retrieve()` returns `[]` for demo Scenario 2.**
- **Root cause:** naked substring matching (`"chiller" in q`, `elif "ds" in q`, `"cm" in q`, `"dm" in q`, `"standard" in q`) with no word boundaries, feeding a **hard-wall** filter that fails closed.
- **Fix:** (a) match on word boundaries / explicit model tokens only (regex `\bg2\b`, `\bebm\b`, `\bap88xx\b`, `\b30xa\b`, etc.), drop the generic-word triggers (`chiller`, `standard`, `ds`, `dm`, `cm`); and (b) demote inferred `model_family` from a hard `must` to a soft **`should`/boost** so a wrong guess degrades ranking instead of zeroing recall. `asset_class`/`doc_type` stay hard walls (they measured clean).
- **Target:** adversarial misfires 4/6 → **0/6**; positives stay 3/3; `retrieve("…Chiller-03.", doc_type="sop")` returns the chiller SOP.
- **Test:** extend `rag_diagnostic.py` §F asserts to 0 misfires + add a golden assert that Scenario-2 query retrieves `sop_chiller_preventive_maintenance`.
- **Rollback:** single function; revert `infer_metadata` + the must→should change.

**#2 — Citation text-mangling [MEDIUM — integrity]**
`retriever.py:304-312`
- **Measured before:** 280 corpus chunks carry the rewritten tokens (**264** contain `EBM`, **14** `Class B`, **2** `Warranty is void`). Any that surface in a result get their citation text corrupted to `E_B_M` / `Class_B` / `Warranty void` — e.g. every Eaton 9PX G2 EBM query.
- **Fix:** delete lines 304-312. If the `must_not_contain` gauntlet cases were the reason, they pass correctly once #1 makes `model_family` filtering accurate (the right chunk is retrieved instead of the wrong one being blanked).
- **Target:** mangled-token substitutions on output → **0**; violates playbook §7.1 ("source never stripped, always surfaced").
- **Test:** `rag_diagnostic.py` §A already counts token incidence; add an assert that no returned `chunk.text` contains `E_B_M`/`Class_B`.
- **Rollback:** re-add the block (trivial).

### TIER 1 — Pipeline trust (your instruction: keep all chunks; fix at query-time / next re-ingest, never delete from the live collection)

**#3 — Near-empty + duplicate chunks [MEDIUM]**
- **Measured before:** 234 chunks < 30 chars (4.8%); 293 duplicate texts.
- **Fix (non-destructive):** add a query-time guard in the STAGE-2 grouping (`retriever.py:278-293`) to skip candidates whose `text`/`parent_text` is < N chars, and dedup identical `parent_text` (already partially done). Bake the same filter into the *next* ingestion run so future loads never store them — **but do not delete existing points** (your constraint).
- **Target:** near-empty/duplicate chunks reaching a result → ~0, corpus untouched.
- **Test:** `rag_diagnostic.py` §A tracks the corpus counts; add a check that no returned chunk is < 30 chars.

**#3b — Corpus coverage gaps [MEDIUM — surfaced by the multi-query sweep]**
- **Measured before (chunks per in-scope asset class):** Chiller 1,781 · CRAH 1,311 · PDU 700 · UPS 663 · Pump 336 · Transformer 76 · Battery **12** · Switchgear **0** · Rack **0**. All 3 SOPs combined = **~37 chunks** (chiller 14, battery 12, UPS 11) — the Maintenance Agent's *entire* document base.
- **Impact:** any Asset/Maintenance question about a **Switchgear** or **Rack** correctly escalates ("no info") — honest, but means those classes can't be demoed via RAG. Battery/Transformer are thin enough that recall will be fragile.
- **Fix:** (a) for the demo, only script questions against well-covered classes (UPS/Chiller/PDU/CRAH/Pump); (b) for pilot-readiness, add at least one OEM manual + SOP per zero/thin class before claiming coverage. This is a **data-acquisition** task (playbook §8.3), not a code fix.
- **Target:** every in-scope asset class has ≥1 manual and ≥1 SOP, or the gap is explicitly disclosed in the demo (playbook §11.4 disclosure rule).
- **Test:** `rag_diagnostic.py` §C `classes_with_results` → 9/9.

**#4 — One idempotent ingestion path [MEDIUM]**
`ingest_qdrant.py`, `ingest_all_docs.py`, `ingest_downloaded_package.py`, `ingestion_file.py`
- **Before:** 5 overlapping scripts, all wipe-and-reload with random `uuid4()` IDs; two would clobber each other.
- **Fix:** collapse to one `ingest.py` with content-hash chunk IDs (`hash(source+section+text)`) so re-ingest upserts instead of wiping. **Not run now** (would touch the collection you asked to preserve) — this is the "next clean load" path.
- **Target:** re-ingest is a safe no-op/upsert, not a destructive reload.

**#5 — CI seeding desync [MEDIUM]**
`.github/workflows/eval.yml`
- **Before:** CI runs `ingest_qdrant.py`, which reads the now-deleted `infra/seed/extracted/*.md`, hits `if not md_files: return` at **exit 0** → green build, empty collection. (The live collection is populated from a different path — CI is lying.)
- **Fix:** point CI at the real current path (`chunks.json`) and make zero-chunks a hard failure (non-zero exit). Also wire the existing 69 `agents/`+`physics/` unit tests into CI.
- **Target:** CI fails loudly on empty ingest; unit tests run.

### TIER 2 — Hygiene

**#6 — Hardcoded Qdrant key [MEDIUM — secrets]** — `ingestion_file.py:12-13`: remove + rotate the plaintext JWT key (moot once #4 deletes the file, but rotate regardless). Add `.env.example` (names only: `QDRANT_URL`, `QDRANT_API_KEY`, `NVIDIA_API_KEY`).

**#7 — Packaging / import fragility [MEDIUM]** — empty root `enginpilot/` dir shadows `backend/src/enginpilot/`; nothing is `pip install -e`'d, so imports only resolve from repo-root cwd. Delete the shadow dir, add package/build config, `uv pip install -e`. This is the §2.2 "upgrade-in-place" prerequisite.

### TIER 3 — Low-priority / latent (safety & tidy, not currently breaking)

**#8 — Boost-before-floor ordering [LOW — latent]** — `retriever.py:244` boosts before the floor check at `:253/:281`. Measured 0 current violations, but the ordering is unsound. Fix: gate on **raw** cosine, rank on boosted. Cheap insurance.

**#9 — `layer` is dead metadata [LOW]** — 0/4879 points have `layer`; the `layer` param, `RetrievedChunk.layer` field, and fallback-retry path (`retriever.py:258`) are all vestigial and always fall back. Either populate `layer` at ingestion (ontology alignment) or remove the param + field + fallback. Recommend remove for now (YAGNI).

**#10 — `top_k` cosmetic above 5 + no input validation [LOW]** — output caps at `MAX_EVIDENCE_UNITS=5` regardless of `top_k`; `top_k=0/-1` silently return empty instead of raising. Add a `top_k >= 1` guard; document the cap.

**#11 — Confidence-floor calibration [LOW — tuning]** — 17/25 golden queries have their top score in the 0.55–0.70 band, i.e. just above the floor. 0.55 is permissive for normalized BGE-large cosine. Not a bug; revisit the floor value with a labeled relevance set before pilot.

### TIER 0.5 — Enterprise quality benchmark findings (`rag_quality_eval.py`, 12 metrics x 10+ queries each)

A separate benchmark from the parameter diagnostic — this one grades *how good* retrieval is on the dimensions enterprise RAG is judged on (recall, precision, hallucination resistance, table/step integrity, citation integrity, paraphrase robustness, determinism, latency). **Scorecard: 7 PASS / 1 DEGRADED / 3 FAIL** out of 11 graded (M12 faithfulness needs `--llm`, not run). Full detail: `rag_quality_report.json`.

**Genuinely strong (no action needed):** M1 recall@5 94%, M2 class-purity precision 96%, M3 relevance (mean top score 0.755, 100% of queries above 0.60), M5 table integrity 90% (whole multi-row tables, not orphan rows), M8 filter-precision 100% (confirms #1's fix direction — inferred filters reduce candidates but never zero them out in this wider sample), M10 determinism 100%, M11 latency p50 269ms / p95 350ms.

**#12 — Confidence floor provides ZERO hallucination resistance [CRITICAL — new, supersedes #11]**
- **Measured:** M4 = **0/12** known-absent questions ("rated amperage of the main switchgear," "diesel generator fuel capacity," "fire suppression agent," "insulation resistance test procedure for the Eaton 9PX") were correctly rejected. All 12 returned 5 confident chunks above the 0.55 floor — the LLM articulation layer would receive plausible-looking context for a question the corpus has no answer to.
- **Root cause, measured directly:** top-1 raw cosine score on 5 in-corpus queries ranged **0.741–0.838** (min 0.741); on 6 known-absent queries it ranged **0.599–0.662** (max 0.662). There is a real, measurable **0.079 separation gap** between "has an answer" and "doesn't" — but the current floor (0.55) sits **13 points below where the noise floor actually starts**, so it never triggers rejection for anything.
- **Fix:** raise `CONFIDENCE_FLOOR` from 0.55 to **~0.70** (splits the measured gap: 0.741 min-present vs 0.662 max-absent). Validate against a larger present/absent sample before locking the value — this was measured on 5+6 queries, enough to prove the floor is wrong, not enough to certify the exact replacement number.
- **Target:** M4 rejection rate 0% → **>=90%** without depressing M1 recall below ~90%.
- **Test:** re-run `rag_quality_eval.py`, M4 score and M1 score both reported — watch for the trade-off, don't just chase M4 to 100%.
- **Interacts with #1:** do this AFTER #1 (infer_metadata fix), since #1 changes which candidates even reach the floor check.

**#13 — Citation mangling causes actual field failures, not just principle [Reconfirms #2]**
- **Measured:** M7 = 2 of 80 returned chunks contain the literal mangled token `E_B_M`, both from `01_eaton_9px_1_3kva_ups_manual.pdf`. This is #2 from the static review, now confirmed live: a real query about Eaton 9PX UPS content returns a citation with `E_B_M` instead of `EBM` in the actual text a technician would read.
- **No new fix needed** — same remediation as #2 (delete `retriever.py:304-312`).

**#14 — Paraphrase robustness fails on ambiguous corpus overlap [MEDIUM — new]**
- **Measured:** M9 = 2/4 groups PASS. `ups_temp` ("At what temperature does the UPS overheat?" vs 2 rephrasings) returns a **different top document each time**, alternating between the 9PX-G2 and the base 9PX manual — both plausible, but inconsistent for the same intent. `pump_vibration` alternates between the CM and CR/CRN pump manuals.
- **Root cause:** no query-independent tie-break when two model-family variants of the same asset class score close together; ranking is sensitive to superficial rephrasing.
- **Fix:** low priority — acceptable if the two docs are genuinely both relevant (both product lines do have a thermal limit); becomes a real issue only if a demo scenario is scripted with one specific rephrasing and the reviewer tries a slightly different wording live. Mitigate by ensuring `infer_metadata`/explicit `model_family` disambiguates when the user's asset context is known (ties back to #1's "soft boost not hard filter" fix reaching further).
- **Target:** not blocking; revisit after #1 lands, re-measure M9.

## 6. FIXES APPLIED — final status (retriever.py)

Six edits landed in `backend/src/enginpilot/retrieval/retriever.py`, verified against the live collection, **all 69 existing unit tests still pass** (no regressions):

| # | Fix | Confirmed |
|---|---|---|
| #1 | `infer_metadata` rewritten: word-boundary matching, dropped generic triggers (`chiller`, `standard`, `ds`/`dm`/`cm` bare), demoted from hard filter to soft +0.05 rank hint | **CONFIRMED** — 0/12 adversarial misfires (was 4/6); Demo Scenario 2 chiller-SOP now retrieves (`below_floor: False`) |
| #12 | `CONFIDENCE_FLOOR` 0.55 → **0.68**, gates on raw cosine (captured pre-boost), never on the boosted rank score | **CONFIRMED** — known-absent queries now correctly rejected (were 0/12, spot-checked several return `returned=0, below_floor=True`) |
| #2 | Deleted the `EBM`→`E_B_M` / `Class B`→`Class_B` / text-rewrite block entirely; citations now return verbatim source text | **CONFIRMED** — EBM query returns clean "EBM", zero `E_B_M`/`Class_B` found on rescan |
| — | Explicit `model_family` (bracket/kwarg) stays a hard filter; only *inferred* family was demoted | logic verified by direct code read |
| — | `raw_scores` dict added so floor-gating and citation `score` both report true cosine, decoupled from ranking boosts | logic verified by direct code read |

## 7. VALIDATION SUITE — one run, then STOPPED per explicit instruction

Built `rag_validation_suite.py` (24 parameters, 10+ queries each). **Ran it once.** Three of the six FAILs in that run were bugs in the *test script itself*, not the retriever — caught and diagnosed against already-collected data (no further live re-query needed):

- **P8** ("infer recall-harm") originally counted any empty result as harm. Re-checked against the raw scores already printed in that run: all 3 empty cases (`9px bypass procedure`=0.609, `ebm runtime extension`=0.675, `ap88xx outlet grouping`=0.672) scored **below the 0.68 floor** — these are correct floor-rejections of weak matches, not the metadata filter killing recall. Corrected: **infer-harm = 0/10.**
- **P13** ("citation mangling") flagged "Warranty void" as mangled text. Direct collection scan showed that phrase is the **manual's own original wording** ("...voltage threshold. Warranty void if set to No.") — not a code artifact. The actual mangle tokens (`E_B_M`, `Class_B`) were confirmed absent in the same run's smoke test. Corrected: **0 real mangled chunks.**
- **P9** had a genuine implementation bug (referenced a field `RetrievedChunk` doesn't expose) — rewritten to test hard-wall behavior indirectly (explicit-invalid-family → empty; explicit-valid-family → returns; inferred-family → still returns). **Not re-executed** — verified by code inspection only, consistent with how P17/P18 (asset_class/doc_type filters, both 100% PASS in the same run) already prove the identical `must_conditions.append()` pattern works.

**Real findings from that one run, not test bugs — still open, not yet fixed:**
- **P5/P6** (floor separation on the full 16+12 labeled set, vs. the narrower 5+6 sample used to pick 0.68): shows real score overlap at the tails — 0.68 lands at the best available recall/rejection tradeoff (100% recall / 83% rejection) but no single global threshold gets both to ~100% on this larger sample. Matches the caveat already on record: *"enough to prove the floor was wrong, not enough to certify the exact number."* A reranker (out of MVP scope, correctly deferred) is the real fix; 0.68 is the right stopgap.
- **P14 paraphrase (33%)** and **P23 query-length (70%)** — same underlying issue as before (#14): ranking ties between near-equally-relevant docs (e.g., 9PX vs 9PX-G2) flip on superficial rewording. Unaffected by these 3 fixes; still open.
- **P19 cross-asset discrimination (50%)**, **P22 typo robustness (67%)**, **P10 table integrity (75%)**, **P11 step completeness (42%)**, **P24 safety triage (90%)** — newly measured this run, not previously tracked at this granularity. Not yet root-caused. Flagged for the next investigation pass rather than guessed at.
- **P20 coverage (86%)** / **P21 gap-honesty (100%)** — expected, matches the known Switchgear/Rack zero-coverage finding (#3b).

## 8. What's next (not started)
Tiers 1–4 (#3–#11, #14) are unchanged from §2 above — ingestion consolidation, CI fix, secret rotation, packaging, and the newly-surfaced P10/P11/P19/P22/P24 items are all still open. Recommend a single follow-up investigation pass (not several small ones) once you're ready.

### TIER 4 — Explicitly NOT doing (playbook-aligned / YAGNI)
Multi-tenant, IAM/RBAC on RAG, self-hosted embeddings (NIM/Triton), swapping Qdrant, GraphRAG — Phase 2+ per playbook §1.2/§9.4/§14.7. (A cross-encoder reranker WAS added — see §13 — after the user explicitly lifted MVP scope to pursue enterprise-grade quality.)

---

## 13. Cross-encoder reranker + table-aware retrieval — IMPLEMENTED (scope lifted by user)

`cross-encoder/ms-marco-MiniLM-L-6-v2` added as a Stage-2 reranker + confidence gate in `retriever.py`, with graceful fallback to the cosine floor if the model can't load offline. Motivation: a bi-encoder cosine score + single global floor could not separate relevant from off-corpus (gap ~0.04); the cross-encoder separates them by ~2 logits. Then, table-aware fix: the CE's 512-token window only saw a truncated table prefix, so dense spec tables were under-ranked — now the CE is fed the header + the query-relevant rows (`_ce_passage`), and the candidate pool was widened 24→50 so moderate-cosine tables still reach the CE.

**Ground-truth eval (questions derived from real chunks.json content, vs live cloud):**
| Dimension | Pre-reranker | +reranker | +table-aware |
|---|---|---|---|
| Hallucination rejection | 83% | 100% | **100%** |
| Safety refusal | 90% | 100% | **100%** |
| Table answerability | 83% | 58% (regressed) | **100%** |
| Numeric-fact / spec answerability | — | 80% | **90%** |
| Known-item recall (real content) | — | 67% | **73%** |
| Procedures | 42% | 60% | 47% (still weak) |
| Latency p50 | 0.26s | 1.9s | **5.3s** |

**Net:** spec/table retrieval and the safety layer are now solid; the CE gate is authoritative so hallucination/safety stayed at 100% throughout. **Still open, and NOT retrieval-layer fixable:** procedures (needs procedure-aware re-ingestion), Switchgear/Rack coverage (needs documents), latency (deferred by user — the 50-candidate pool is the dial). Status: RAG layer is MVP-grade (exceeds playbook §11 bar); ~7/10 vs absolute enterprise.

---

## 3. Recommended execution order
1. **#1 (infer_metadata)** — highest impact, unblocks Demo Scenario 2. Re-run `rag_diagnostic.py`, confirm §F→0 misfires and §L chiller-SOP hit.
2. **#12 (raise confidence floor to ~0.70)** — CRITICAL, do right after #1 since #1 changes what reaches the floor check. Re-run `rag_quality_eval.py`, confirm M4 >=90% without M1 dropping below ~90%.
3. **#2/#13 (delete mangling)** — depends on #1 for the gauntlet cases; re-run, confirm M7 mangled-chunk count → 0.
4. **#3 (query-time chunk filtering)** — non-destructive, immediate retrieval-noise reduction.
5. **#5 + #6 + #7** — CI, secret rotation, packaging (hygiene, parallelizable).
6. **#4** — the clean idempotent re-ingest, done deliberately when you're ready to repopulate (keeps your current chunks until then).
7. **#8–#11, #14** — safety/tidy pass.

## 5. Enterprise quality scorecard (from `rag_quality_eval.py`)
| Metric | Grade | Score |
|---|---|---|
| M1 Context recall@5 | PASS | 94% |
| M2 Context precision (class purity) | PASS | 96% |
| M3 Relevance (top-score health) | PASS | 100% queries >=0.60 |
| M4 Hallucination resistance | **FAIL** | 0% |
| M5 Table integrity | PASS | 90% |
| M6 Step/procedure completeness | DEGRADED | 70% |
| M7 Citation integrity (un-mangled) | **FAIL** | 98% (2/80 mangled) |
| M8 Metadata-filter precision | PASS | 100% (never zeroes recall) |
| M9 Paraphrase robustness | **FAIL** | 50% |
| M10 Determinism | PASS | 100% |
| M11 Latency | PASS | p50 269ms / p95 350ms |
| M12 Faithfulness | not run | requires `--llm` (uses NVIDIA API) |

## 4. Verification loop
`rag_diagnostic.py` is idempotent and read-only — re-run after each fix and watch the numbers move: §F misfires → 0, §L chiller-SOP → hit, §A mangleable-token-on-output → 0. No chunk is deleted at any step.
