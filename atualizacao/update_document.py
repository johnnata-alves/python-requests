import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId

load_dotenv()

MONGO_URI = os.getenv("HML_MONGO_URI")
DB_NAME = "ProductEngine"
COLLECTION_NAME = "productClaim"

DOC_57 = {
    "type": "DECLARAÇÃO DE ÚNICOS HERDEIROS, COM FIRMA RECONHECIDA DA ASSINATURA DO DECLARANTE E DAS TESTEMUNHAS",
    "documentTypeIds": [],
    "requiresDataValidation": False,
    "isRequired": True,
    "isInsuredDocument": True,
    "isBeneficiaryDocument": False,
    "isActive": True,
    "erpDocumentId": 57,
    "metadata": ["string"],
    "relatedErpDocumentIds": [],
    "autoRequiredDocumentIds": []
}

def coverage_has_heirs(coverage: dict) -> bool:
    """Retorna True se beneficiaryTypes contiver 'HEIRS'."""
    beneficiary_types = coverage.get("beneficiaryTypes", [])
    return isinstance(beneficiary_types, list) and "HEIRS" in beneficiary_types

def documentation_has_erp_id(coverage: dict, erp_id: int) -> bool:
    """Retorna True se documentation já tiver algum item com erpDocumentId == erp_id."""
    docs = coverage.get("documentation", [])
    if not isinstance(docs, list):
        return False
    for d in docs:
        if isinstance(d, dict) and d.get("erpDocumentId") == erp_id:
            return True
    return False

def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    col = db[COLLECTION_NAME]

    query = {
        "coverages": {"$exists": True, "$type": "array"},
        "coverages.beneficiaryTypes": "HEIRS"
    }

    updated_docs = 0
    updated_coverages_total = 0

    cursor = col.find(query, {"coverages": 1})

    for doc in cursor:
        _id = doc["_id"]
        coverages = doc.get("coverages", [])

        if not isinstance(coverages, list) or not coverages:
            continue

        changed = False
        updated_coverages = 0

        for cov in coverages:
            if not isinstance(cov, dict):
                continue

            if coverage_has_heirs(cov):
                if not documentation_has_erp_id(cov, 57):
                    docs = cov.get("documentation", [])
                    if not isinstance(docs, list):
                        cov["documentation"] = [DOC_57]
                    else:
                        docs.append(DOC_57)

                    changed = True
                    updated_coverages += 1

        if changed:
            result = col.update_one(
                {"_id": _id},
                {"$set": {"coverages": coverages}}
            )

            if result.modified_count > 0:
                updated_docs += 1
                updated_coverages_total += updated_coverages
                print(f"[OK] _id={_id} | coverages atualizadas={updated_coverages}")
            else:
                print(f"[WARN] _id={_id} encontrado, mas não alterou (talvez concorrência).")

    print("\n====== RESUMO ======")
    print(f"Documentos atualizados: {updated_docs}")
    print(f"Coverages atualizadas (total): {updated_coverages_total}")

    client.close()

if __name__ == "__main__":
    main()
