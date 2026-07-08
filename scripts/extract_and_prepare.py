import json
import hashlib
from pathlib import Path
from docling.document_converter import DocumentConverter

# --- STRICT METADATA REGISTRY ---
# Enforces 50Hz/60Hz separation, ABM/ABM+ model boundaries, and provenance tiers.
REGISTRY = {
    "01_eaton_9px_1_3kva_ups_manual.pdf": {"asset_class": "UPS", "manufacturer": "Eaton", "model_family": "9PX Standard", "frequency_hz": None, "provenance_tier": "vendor_direct", "doc_type": "oem_manual"},
    "02_eaton_9px_g2_3_11kva_ups_ebm_manual.pdf": {"asset_class": "UPS", "manufacturer": "Eaton", "model_family": "9PX G2", "frequency_hz": None, "provenance_tier": "vendor_direct", "doc_type": "oem_manual"},
    "03_carrier_30xa_chiller_iom.pdf": {"asset_class": "Chiller", "manufacturer": "Carrier", "model_family": "30XA", "frequency_hz": 50, "provenance_tier": "vendor_direct", "doc_type": "oem_manual"},
    "04_carrier_30xa_smartvu_controls.pdf": {"asset_class": "Chiller", "manufacturer": "Carrier", "model_family": "30XA", "frequency_hz": 60, "provenance_tier": "vendor_direct", "doc_type": "oem_manual"},
    "05_vertiv_liebert_ds_manual.pdf": {"asset_class": "CRAH", "manufacturer": "Vertiv", "model_family": "Liebert DS", "frequency_hz": 60, "provenance_tier": "vendor_direct", "doc_type": "oem_manual"},
    "06_vertiv_liebert_dm_manual.pdf": {"asset_class": "CRAH", "manufacturer": "Vertiv", "model_family": "Liebert DM", "frequency_hz": 60, "provenance_tier": "vendor_direct", "doc_type": "oem_manual"},
    "07_grundfos_cr_crn_pump_manual.pdf": {"asset_class": "Pump", "manufacturer": "Grundfos", "model_family": "CR/CRN", "frequency_hz": None, "provenance_tier": "vendor_direct", "doc_type": "oem_manual"},
    "08_grundfos_cm_pump_manual.pdf": {"asset_class": "Pump", "manufacturer": "Grundfos", "model_family": "CM", "frequency_hz": None, "provenance_tier": "vendor_direct", "doc_type": "oem_manual"},
    "09_apc_ap88xx_pdu_manual.pdf": {"asset_class": "PDU", "manufacturer": "APC", "model_family": "AP88XX", "frequency_hz": None, "provenance_tier": "unofficial_mirror", "doc_type": "oem_manual"},
    "10_abb_transformer_manual.pdf": {"asset_class": "Transformer", "manufacturer": "ABB", "model_family": "Dry Type", "frequency_hz": None, "provenance_tier": "vendor_direct", "doc_type": "oem_manual"},
    "sop_ups_preventive_maintenance.pdf": {"asset_class": "UPS", "manufacturer": "ENGINPILOT", "model_family": "SOP", "frequency_hz": None, "provenance_tier": "internal_approved", "doc_type": "sop"},
    "sop_chiller_preventive_maintenance.pdf": {"asset_class": "Chiller", "manufacturer": "ENGINPILOT", "model_family": "SOP", "frequency_hz": None, "provenance_tier": "internal_approved", "doc_type": "sop"},
    "sop_battery_bank_inspection.pdf": {"asset_class": "Battery", "manufacturer": "ENGINPILOT", "model_family": "SOP", "frequency_hz": None, "provenance_tier": "internal_approved", "doc_type": "sop"}
}

def main():
    pdf_dir = Path("infra/seed/sample_pdfs")
    out_dir = Path("infra/seed/extracted")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("⏳ Initializing IBM Docling... (Downloads AI models on first run, ~1-2 mins)")
    converter = DocumentConverter()

    for pdf_path in sorted(pdf_dir.glob("*.pdf")):
        filename = pdf_path.name
        meta = REGISTRY.get(filename)
        
        if not meta:
            print(f"⚠️  SKIPPING {filename} (Not in registry)")
            continue

        print(f"📄 Processing: {filename}...")

        # 1. Generate SHA-256 Hash for Document Identity
        with open(pdf_path, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()

        # 2. Extract with Docling (Preserves tables, headings, reading order)
        try:
            result = converter.convert(str(pdf_path))
            md_text = result.document.export_to_markdown()
        except Exception as e:
            print(f"❌ Docling failed on {filename}: {e}")
            continue

        # 3. Save Markdown
        md_path = out_dir / f"{pdf_path.stem}.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)

        # 4. Attach Metadata & Save JSON
        meta.update({
            "document_id": sha256[:12],
            "filename": filename,
            "sha256": sha256,
            "document_status": "active",
            "ingested_at": "2026-07-07T00:00:00Z"
        })
        
        json_path = out_dir / f"{pdf_path.stem}_meta.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        print(f"✅ Saved: {md_path.name} & {json_path.name}")

    print("\n🎉 EXTRACTION COMPLETE. Check 'infra/seed/extracted/' for outputs.")

if __name__ == "__main__":
    main()