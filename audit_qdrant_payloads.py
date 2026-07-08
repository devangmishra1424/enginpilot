from qdrant_client import QdrantClient

client = QdrantClient(host="localhost", port=6333)
COLLECTION_NAME = "enginpilot_docs"

def main():
    print("🔍 Scanning Qdrant payloads for Phase 0 compliance...\n")

    offset = None
    total = 0
    missing_status = 0
    missing_asset = 0
    missing_parent_text = 0
    missing_content_type = 0
    asset_counts = {}
    doc_type_counts = {}
    content_type_counts = {}
    source_docs = set()

    while True:
        records, offset = client.scroll(
            collection_name=COLLECTION_NAME,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False
        )
        if not records:
            break

        for r in records:
            total += 1
            p = r.payload

            if p.get("document_status") != "active":
                missing_status += 1

            if not p.get("asset_class"):
                missing_asset += 1

            if not p.get("parent_text"):
                missing_parent_text += 1

            if not p.get("content_type"):
                missing_content_type += 1

            ac = p.get("asset_class", "UNKNOWN")
            asset_counts[ac] = asset_counts.get(ac, 0) + 1

            dt = p.get("doc_type", "UNKNOWN")
            doc_type_counts[dt] = doc_type_counts.get(dt, 0) + 1

            ct = p.get("content_type", "UNKNOWN")
            content_type_counts[ct] = content_type_counts.get(ct, 0) + 1

            sd = p.get("source_document", "UNKNOWN")
            source_docs.add(sd)

        if offset is None:
            break

    print(f"✅ AUDIT COMPLETE: Scanned {total} vectors across {len(source_docs)} documents.\n")

    print("--- PAYLOAD INTEGRITY ---")
    if missing_status == 0:
        print(f"🟢 document_status='active': All {total} vectors OK")
    else:
        print(f"🔴 document_status='active': {missing_status} MISSING (Hard Wall will block these!)")

    if missing_asset == 0:
        print(f"🟢 asset_class: All {total} vectors OK")
    else:
        print(f"🔴 asset_class: {missing_asset} MISSING")

    if missing_parent_text == 0:
        print(f"🟢 parent_text: All {total} vectors OK (Stage 4 expansion ready)")
    else:
        print(f"🔴 parent_text: {missing_parent_text} MISSING (Stage 4 expansion will fall back to leaf text)")

    if missing_content_type == 0:
        print(f"🟢 content_type: All {total} vectors OK (Content-aware truncation ready)")
    else:
        print(f"🔴 content_type: {missing_content_type} MISSING (Will default to 'narrative')")

    print("\n--- ASSET CLASS DISTRIBUTION ---")
    for k, v in sorted(asset_counts.items()):
        print(f"   {k}: {v}")

    print("\n--- DOC TYPE DISTRIBUTION ---")
    for k, v in sorted(doc_type_counts.items()):
        print(f"   {k}: {v}")

    print("\n--- CONTENT TYPE DISTRIBUTION ---")
    for k, v in sorted(content_type_counts.items()):
        print(f"   {k}: {v}")

    print("\n--- SOURCE DOCUMENTS ---")
    for sd in sorted(source_docs):
        print(f"   📄 {sd}")

    all_green = (missing_status == 0 and missing_asset == 0 and missing_parent_text == 0 and missing_content_type == 0)
    if all_green:
        print("\n🟢 PHASE 0 PAYLOAD AUDIT PASSED. Retriever Hard Wall and Stage 4 expansion are safe to use.")
    else:
        print("\n🔴 PHASE 0 PAYLOAD AUDIT FAILED. Fix the issues above before running the evaluation harness.")

if __name__ == "__main__":
    main()