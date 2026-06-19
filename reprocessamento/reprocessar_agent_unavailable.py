from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient
import os

load_dotenv()

MONGO_URI = os.getenv("HML_MONGO_URI")

DB_TYPIFICATION = "DocumentTypification"
COLLECTION_LOG = "TypificationDocumentCalls"
COLLECTION_DOCUMENT = "TypificationDocument"

client = MongoClient(MONGO_URI)
db = client[DB_TYPIFICATION]

col_log = db[COLLECTION_LOG]
col_document = db[COLLECTION_DOCUMENT]

filtro = {
    "response": "This agent is currently unavailable. It has reached its usage limit. Please try again later."
}

docs = col_log.find(filtro, {"typification_document_id": 1, "_id": 0})

ids = [doc["typification_document_id"] for doc in docs if doc.get("typification_document_id")]
print(f"Total de registros encontrados: {len(ids)}")

atualizados = 0
erros = 0

for doc_id in ids:
    try:
        if isinstance(doc_id, str):
            doc_id = ObjectId(doc_id)

        result = col_document.update_one(
            {"_id": doc_id},
            {"$set": {"status": "pending"}}
        )

        if result.modified_count > 0:
            atualizados += 1
        elif result.matched_count > 0:
            print(f"  [SKIP] _id={doc_id} já está com status pending")
        else:
            print(f"  [NOT FOUND] _id={doc_id} não encontrado em {COLLECTION_DOCUMENT}")
            erros += 1
    except Exception as e:
        erros += 1
        print(f"  [ERRO] _id={doc_id}: {e}")

print(f"\nFinalizado. Atualizados: {atualizados} | Erros/Não encontrados: {erros}")
