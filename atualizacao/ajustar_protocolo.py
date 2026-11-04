"""Corrige o campo protocol em LegacyDocument e LegacyAttachment.

Para cada registro cujo protocol casa /.*SIN-.*/i:
- pega claimNumber
- busca LegacyClaim por claimNumber
- pega o protocol correto do LegacyClaim
- atualiza protocol e updatedAt no registro original
"""

import os
import re
from datetime import datetime, timezone

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo import UpdateOne
from tqdm import tqdm

load_dotenv()

MONGO_SINISTRO_URI = os.getenv("PRD_MONGO_URI", "")
BATCH_SIZE = int(os.getenv("FIX_PROTOCOL_BATCH_SIZE", "500"))

# Filtro: protocol contendo "SIN-" (case-insensitive)
PROTOCOL_FILTER = {"protocol": {"$regex": r".*SIN-.*", "$options": "i"}}

client = MongoClient(MONGO_SINISTRO_URI)
db = client["ClaimEngine"]
collection_legacy_claim = db["LegacyClaim"]
collection_legacy_document = db["LegacyDocument"]
collection_legacy_attachment = db["LegacyAttachment"]

# Cache de claimNumber -> protocol para evitar consultas repetidas
_protocol_cache = {}


def _get_protocol_by_claim_number(claim_number):
    if claim_number is None:
        return None
    if claim_number in _protocol_cache:
        return _protocol_cache[claim_number]

    claim = collection_legacy_claim.find_one(
        {"claimNumber": claim_number}, {"protocol": 1}
    )
    protocol = (claim or {}).get("protocol")
    _protocol_cache[claim_number] = protocol
    return protocol


def _fix_collection(collection, label):
    print(f"\n=== {label} ===")
    total_docs = collection.count_documents(PROTOCOL_FILTER)
    cursor = collection.find(
        PROTOCOL_FILTER, {"claimNumber": 1, "protocol": 1}, no_cursor_timeout=True
    )

    total = 0
    updated = 0
    skipped_no_claim = 0
    skipped_no_protocol = 0
    ops = []

    try:
        for doc in tqdm(cursor, total=total_docs, desc=label, unit="doc"):
            total += 1
            claim_number = doc.get("claimNumber")
            if claim_number is None:
                skipped_no_claim += 1
                continue

            new_protocol = _get_protocol_by_claim_number(claim_number)
            if not new_protocol:
                skipped_no_protocol += 1
                continue

            # Nada a fazer se ja esta correto
            if doc.get("protocol") == new_protocol:
                continue

            ops.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {
                        "$set": {
                            "protocol": new_protocol,
                            "UpdatedAt": datetime.now(timezone.utc),
                        }
                    },
                )
            )

            if len(ops) >= BATCH_SIZE:
                result = collection.bulk_write(ops, ordered=False)
                updated += result.modified_count
                ops = []
    finally:
        cursor.close()

    if ops:
        result = collection.bulk_write(ops, ordered=False)
        updated += result.modified_count

    print(f"lidos: {total}")
    print(f"atualizados: {updated}")
    print(f"sem claimNumber: {skipped_no_claim}")
    print(f"sem protocol na LegacyClaim: {skipped_no_protocol}")


def main():
    if not MONGO_SINISTRO_URI:
        raise SystemExit("Variavel de ambiente PRD_MONGO_URI nao definida.")

    _fix_collection(collection_legacy_document, "LegacyDocument")
    _fix_collection(collection_legacy_attachment, "LegacyAttachment")
    print("\nConcluido.")


if __name__ == "__main__":
    main()
