import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("HML_MONGO_URI")
DB_NAME = "ClaimEngine"

SOURCE_COLLECTION = "DocumentTypeMappings"
TARGET_COLLECTION = "DocumentTypeMappingsVariations"
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

source_col = db[SOURCE_COLLECTION]
target_col = db[TARGET_COLLECTION]

def process_doc(doc):
    updated = False
    migrated = 0

    ocr = doc.get("OCR", {})
    documents = ocr.get("Documents", [])

    for d in documents:
        metadatas = d.get("Metadatas", [])

        for meta in metadatas:
            metadata_name = meta.get("metadata")
            descricao = meta.get("Descrição")
            variations = meta.get("variations", [])

            if "variations" in meta:
                del meta["variations"]
                updated = True

            if not metadata_name or not variations:
                continue

            normalized_variations = list(set(variations))
            if not normalized_variations:
                continue

            target_col.update_one(
                {"metadata": metadata_name},
                {
                    "$setOnInsert": {
                        "metadata": metadata_name,
                        "Descrição": descricao,
                    },
                    "$addToSet": {
                        "variations": {"$each": normalized_variations}
                    }
                },
                upsert=True,
            )
            migrated += 1

    if updated:
        source_col.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "OCR.Documents": documents
                }
            }
        )

        print(f"Atualizado doc: {doc['_id']}")

    return {"updated": updated, "migrated": migrated}

docs = list(source_col.find({}))
updated_docs = 0
migrated_metadatas = 0

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = [executor.submit(process_doc, doc) for doc in docs]

    for future in as_completed(futures):
        result = future.result()
        if result["updated"]:
            updated_docs += 1
        migrated_metadatas += result["migrated"]

print("Migração finalizada.")
print(f"Documentos atualizados: {updated_docs}")
print(f"Metadados migrados para destino: {migrated_metadatas}")
