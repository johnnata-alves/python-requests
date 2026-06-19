import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne
from tqdm import tqdm

load_dotenv()

STATUS_NAO_NECESSARIO = "Não é necessário geração"
MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
META_DB = "testeMigracao"
META_COLLECTION = "MetaItems"
INDEXED_DB = "indexed_customer_files"
INDEXED_COLLECTION = "individual_policies_without_cert"
WORKERS = 16
BATCH_SIZE = 5000

def normalize_document(value: Any) -> str:
    digits = "".join(character for character in str(value or "") if character.isdigit())
    if not digits:
        return ""
    return digits.zfill(11)

def get_insured_document(document: Dict[str, Any]) -> str:
    insureds = document.get("insureds") or []
    if not insureds:
        return ""

    for insured in insureds:
        normalized = normalize_document(insured.get("document"))
        if normalized:
            return normalized

    return ""

def process_document(
    document: Dict[str, Any],
    indexed_collection: Any,
) -> Dict[str, Any]:
    policy_number = str(document.get("policy_number") or "").strip()
    insured_document = get_insured_document(document)

    if not policy_number or not insured_document:
        return {
            "updated": 1,
            "matched": 0,
            "invalid": 1,
            "update_fields": {"statusProcessamento": STATUS_NAO_NECESSARIO, "check": True},
        }

    indexed_filter = {
        "insured_document": insured_document,
        "policy_number_i4pro": policy_number,
    }
    indexed_projection = {"_id": 1, "insured_document": 1}
    indexed_document = indexed_collection.find_one(indexed_filter, indexed_projection)

    if indexed_document:
        return {
            "updated": 0,
            "matched": 1,
            "invalid": 0,
            "update_fields": {"check": True},
        }

    return {
        "updated": 1,
        "matched": 0,
        "invalid": 0,
        "update_fields": {"statusProcessamento": STATUS_NAO_NECESSARIO, "check": True},
    }

def main() -> None:
    if not MONGO_URI:
        raise ValueError("Defina PRD_MONGO_SA_EAST no arquivo .env.")

    client = MongoClient(MONGO_URI, maxPoolSize=WORKERS + 5)

    meta_collection = client[META_DB][META_COLLECTION]
    indexed_collection = client[INDEXED_DB][INDEXED_COLLECTION]

    source_filter = {
        "statusProcessamento": {"$exists": False},
        "Ramo": "PanProtege",
        "check": {"$ne": True},
    }
    projection = {
        "_id": 1,
        "policy_number": 1,
        "insureds.document": 1,
    }
    total_pending = meta_collection.count_documents(source_filter)

    totals = {"processed": 0, "updated": 0, "matched": 0, "invalid": 0}

    try:
        with tqdm(total=total_pending, desc="Processando registros", unit="registro") as progress:
            while True:
                batch = list(
                    meta_collection.find(
                        source_filter,
                        projection=projection,
                        no_cursor_timeout=True,
                    ).limit(BATCH_SIZE)
                )

                if not batch:
                    break

                with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                    results = executor.map(
                        lambda document: process_document(
                            document,
                            indexed_collection,
                        ),
                        batch,
                    )

                    bulk_operations = []

                    for document, result in zip(batch, results):
                        totals["processed"] += 1
                        totals["updated"] += result["updated"]
                        totals["matched"] += result["matched"]
                        totals["invalid"] += result["invalid"]
                        progress.update(1)
                        bulk_operations.append(
                            UpdateOne(
                                {"_id": document["_id"]},
                                {"$set": result["update_fields"]},
                            )
                        )

                        if totals["processed"] % 500 == 0:
                            progress.set_postfix(
                                matched=totals["matched"],
                                updated=totals["updated"],
                                invalid=totals["invalid"],
                            )

                    if bulk_operations:
                        meta_collection.bulk_write(bulk_operations, ordered=False)
    finally:
        client.close()

    print(
        "Finalizado. Processados: {processed} | Encontrados no índice: {matched} | "
        "Marcados: {updated} | Inválidos/sem CPF: {invalid}".format(**totals)
    )

if __name__ == "__main__":
    main()
