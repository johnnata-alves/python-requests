import os
from datetime import datetime
from pymongo import MongoClient, UpdateOne, UpdateMany
from dotenv import load_dotenv

load_dotenv()

MONGO_CONNECTION = os.getenv("HML_MONGO_URI")
DATABASE_MONGO = "ClaimEngine"
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1000"))

SEM_PROTOCOLO_FILTER = {
    "$or": [
        {"protocol": {"$exists": False}},
        {"protocol": None},
        {"protocol": ""},
    ]
}


def flush(collection, ops):
    if not ops:
        return 0
    return collection.bulk_write(ops, ordered=False).modified_count


def main():
    inicio = datetime.now()

    client = MongoClient(MONGO_CONNECTION)
    db = client[DATABASE_MONGO]

    total = db.LegacyClaim.count_documents(SEM_PROTOCOLO_FILTER)
    print(f"LegacyClaim sem protocolo: {total}")

    claim_ops, doc_ops = [], []
    claims_atualizados, docs_atualizados = 0, 0

    cursor = db.LegacyClaim.find(SEM_PROTOCOLO_FILTER, {"claimNumber": 1}, batch_size=5000, no_cursor_timeout=True)
    try:
        for claim in cursor:
            claim_number = claim.get("claimNumber")
            if claim_number is None:
                continue

            novo_protocolo = f"SIN-{claim_number}"
            claim_ops.append(UpdateOne({"_id": claim["_id"]}, {"$set": {"protocol": novo_protocolo}}))
            doc_ops.append(UpdateMany({"claimNumber": claim_number}, {"$set": {"protocol": novo_protocolo}}))

            if len(claim_ops) >= BATCH_SIZE:
                claims_atualizados += flush(db.LegacyClaim, claim_ops)
                docs_atualizados += flush(db.LegacyDocument, doc_ops)
                claim_ops, doc_ops = [], []
                print(f"  Progresso: claims={claims_atualizados} docs={docs_atualizados}")
    finally:
        cursor.close()

    claims_atualizados += flush(db.LegacyClaim, claim_ops)
    docs_atualizados += flush(db.LegacyDocument, doc_ops)

    client.close()

    duracao = (datetime.now() - inicio).total_seconds()
    print("\n" + "=" * 60)
    print("ATUALIZAÇÃO DE PROTOCOLO LEGADO")
    print("=" * 60)
    print(f"LegacyClaim sem protocolo: {total}")
    print(f"LegacyClaim atualizados: {claims_atualizados}")
    print(f"LegacyDocument atualizados: {docs_atualizados}")
    print(f"Duração: {duracao:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
