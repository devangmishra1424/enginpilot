import json
import uuid
import gc
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer

# --- CONFIGURATION ---
EXTRACTED_DIR = Path("infra/seed/extracted")
COLLECTION_NAME = "enginpilot_docs"
MODEL_NAME = "BAAI/bge-large-en-v1.5"
VECTOR_SIZE = 1024
BATCH_SIZE = 8

def classify_content_type(section_name: str, text: str) -> str:
    """Tags chunks so the retriever knows what is safe to truncate."""
    s = section_name.lower()
    
    # 1. Procedures & Warnings (Criterion 9)
    if any(word in s for word in ["procedure", "step", "replacement", "cleaning", "priming", "assembly", "installation", "start-up", "startup", "commissioning", "checklist"]):
        return "procedure"
    if any(word in s for word in ["warning", "caution", "danger", "escalation", "safety", "notice"]):
        return "warning"
        
    # 2. Aggressive Table Detection (Criterion 14)
    if ("|" in text and "---" in text) or \
       (text.count("|") > 4) or \
       any(word in s for word in ["table", "data", "electrical data", "torque", "specifications", "dimensions", "alarm code", "fault code", "setpoint"]):
        return "table"
        
    # 3. Numeric-heavy content (likely spec tables)
    lines = text.strip().split("\n")
    if lines:
        numeric_lines = sum(1 for l in lines if sum(c.isdigit() for c in l) > len(l) * 0.2)
        if numeric_lines > len(lines) * 0.3:
            return "table"
            
    return "narrative"

def main():
    print("🔌 Connecting to local Qdrant database...")
    client = QdrantClient(host="localhost", port=6333)

    if client.collection_exists(COLLECTION_NAME):
        print(f"⚠️ Collection {COLLECTION_NAME} exists. Deleting for clean rebuild...")
        client.delete_collection(COLLECTION_NAME)

    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE)
    )
    print(f"✅ Created Qdrant collection: {COLLECTION_NAME} ({VECTOR_SIZE}-dim)")

    print(f"🧠 Loading embedding model ({MODEL_NAME})...")
    embedder = SentenceTransformer(MODEL_NAME)

    headers_to_split_on = [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]
    md_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on, strip_headers=False)
    
    # Increased chunk_overlap from 100 to 200 for better boundary capture
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=800,
        chunk_overlap=200, 
        separators=["\n\n", "\n", ". ", " ", ""]
    )

    total_vectors = 0
    md_files = sorted(EXTRACTED_DIR.glob("*.md"))

    if not md_files:
        print("❌ No markdown files found in infra/seed/extracted/")
        return

    for md_file in md_files:
        base_name = md_file.stem
        meta_file = EXTRACTED_DIR / f"{base_name}_meta.json"

        if not meta_file.exists():
            print(f"⚠️ Skipping {base_name} (No metadata file found)")
            continue

        print(f"\n📄 Processing: {base_name}...")

        with open(meta_file, "r", encoding="utf-8") as f:
            meta = json.load(f)

        with open(md_file, "r", encoding="utf-8") as f:
            md_text = f.read()

        header_chunks = md_splitter.split_text(md_text)
        all_points = []

        for hc in header_chunks:
            full_section_text = hc.page_content
            section_name = " - ".join([v for k, v in hc.metadata.items()]) if hc.metadata else "Introduction"
            content_type = classify_content_type(section_name, full_section_text)

            # CRITICAL FIX: Keep procedures, warnings, and tables intact if under 2000 chars
            if content_type in ("procedure", "warning", "table") and len(full_section_text) <= 2000:
                sub_chunks = [full_section_text]
            else:
                sub_chunks = text_splitter.split_text(full_section_text)

            texts_batch = []
            meta_batch = []

            for sc in sub_chunks:
                chunk_id = str(uuid.uuid4())
                texts_batch.append(sc)
                meta_batch.append({
                    "chunk_id": chunk_id,
                    "parent_id": base_name,
                    "text": sc,
                    "parent_text": full_section_text,
                    "content_type": content_type,
                    "section": section_name,
                    "source_document": meta.get("filename", base_name),
                    "asset_class": meta.get("asset_class"),
                    "manufacturer": meta.get("manufacturer"),
                    "model_family": meta.get("model_family"),
                    "frequency_hz": meta.get("frequency_hz"),
                    "provenance_tier": meta.get("provenance"),
                    "doc_type": meta.get("doc_type"),
                    "document_status": "active"
                })

            if not texts_batch:
                continue

            vectors = embedder.encode(
                texts_batch,
                normalize_embeddings=True,
                batch_size=BATCH_SIZE,
                show_progress_bar=False
            ).tolist()

            for vec, payload in zip(vectors, meta_batch):
                all_points.append(PointStruct(
                    id=payload["chunk_id"],
                    vector=vec,
                    payload=payload
                ))

        for i in range(0, len(all_points), 50):
            client.upsert(collection_name=COLLECTION_NAME, points=all_points[i:i+50])

        total_vectors += len(all_points)
        print(f"   ✂️ {len(header_chunks)} sections → {len(all_points)} chunks uploaded.")

        del all_points, header_chunks, md_text
        gc.collect()

    print(f"\n🎉 SUCCESS! Ingestion complete. Total vectors: {total_vectors}")

if __name__ == "__main__":
    main()