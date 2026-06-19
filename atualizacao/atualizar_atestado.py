import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("HML_MONGO_URI"))

db = client["ClaimEngine"]
collection = db["DocumentTypeMappings"]

filter_query = {
    "OCR.Documents.Document": "Atestado Médico"
}

documents = collection.find(filter_query)

updated_count = 0

for doc in documents:

    modified = False

    documents_ocr = doc.get("OCR", {}).get("Documents", [])

    for ocr_document in documents_ocr:

        if ocr_document.get("Document") != "Atestado Médico":
            continue

        metadatas = ocr_document.get("Metadatas", [])

        for metadata in metadatas:

            if metadata.get("metadata") == "CPF do Paciente":

                metadata["fieldValidation"] = ""
                metadata["isRequired"] = False

                modified = True

    if modified:

        collection.update_one(
            {"_id": doc["_id"]},
            {
                "$set": {
                    "OCR.Documents": documents_ocr
                }
            }
        )

        updated_count += 1

        print(f"Documento atualizado: {doc['_id']}")

print(f"\nTotal atualizados: {updated_count}")
