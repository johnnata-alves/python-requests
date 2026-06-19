import os
from pymongo import MongoClient
from deepdiff import DeepDiff
import json
from dotenv import load_dotenv

load_dotenv()

PRD_CONNECTION_STRING = os.getenv("PRD_MONGO_CLAIM_ENGINE")
STG_CONNECTION_STRING = os.getenv("HML_MONGO_URI")

DATABASE_NAME = "ClaimEngine"
COLLECTION_NAME = "DocumentTypeMappings"

prd_client = MongoClient(PRD_CONNECTION_STRING)
stg_client = MongoClient(STG_CONNECTION_STRING)

prd_collection = prd_client[DATABASE_NAME][COLLECTION_NAME]
stg_collection = stg_client[DATABASE_NAME][COLLECTION_NAME]

differences = []

total = 0
missing_in_stg = 0
different_docs = 0

for prd_doc in prd_collection.find({}):

    total += 1

    document_id = prd_doc["_id"]

    stg_doc = stg_collection.find_one({"_id": document_id})

    if not stg_doc:

        missing_in_stg += 1

        differences.append({
            "_id": str(document_id),
            "issue": "DOCUMENTO NÃO EXISTE EM STG"
        })

        continue

    diff = DeepDiff(
        prd_doc,
        stg_doc,
        ignore_order=True
    )

    if diff:

        different_docs += 1

        differences.append({
            "_id": str(document_id),
            "differences": json.loads(diff.to_json())
        })

print("=" * 50)
print(f"TOTAL ANALISADOS: {total}")
print(f"NÃO EXISTEM EM STG: {missing_in_stg}")
print(f"DOCUMENTOS DIFERENTES: {different_docs}")
print("=" * 50)

for item in differences:

    print(json.dumps(item, indent=4, ensure_ascii=False))

with open("mongo_diff_result.json", "w", encoding="utf-8") as f:
    json.dump(
        differences,
        f,
        indent=4,
        ensure_ascii=False
    )

print("\nArquivo gerado: mongo_diff_result.json")
