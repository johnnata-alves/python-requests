import os
import re
import unicodedata
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("HML_MONGO_URI")
DB_NAME = "ClaimEngine"
COLLECTION_NAME = "DocumentTypeMappingsVariations"

def normalize(text: str) -> str:
    if not text:
        return ""

    text = text.lower()

    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")

    text = text.replace("ç", "c")

    text = re.sub(r"[^a-z0-9]+", "_", text)

    text = re.sub(r"_+", "_", text).strip("_")

    return text

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION_NAME]

for doc in collection.find({}):

    metadata = doc.get("metadata")
    if not metadata:
        continue

    variations = doc.get("variations", [])

    normalized_metadata = normalize(metadata)

    normalized_variations = [v for v in variations if v]

    if normalized_metadata not in normalized_variations:
        normalized_variations.append(normalized_metadata)

        seen = set()
        unique_variations = []
        for v in normalized_variations:
            if v not in seen:
                seen.add(v)
                unique_variations.append(v)

        collection.update_one(
            {"_id": doc["_id"]},
            {"$set": {"variations": unique_variations}}
        )

        print(f"[UPDATED] {doc['_id']} -> adicionou: {normalized_metadata}")
    else:
        print(f"[OK] {doc['_id']}")

client.close()
