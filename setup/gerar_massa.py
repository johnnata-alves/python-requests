import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("HML_MONGO_URI"))

db = client["ClaimEngine"]

attachment_collection = db["Attachment"]
notification_collection = db["Notification"]

attachments = attachment_collection.find(
    {
        "metadata.DocumentType": {
            "$regex": "RG",
            "$options": "i"
        }
    },
    {
        "_id": 0,
        "protocol": 1,
        "fileName": 1
    }
)

file_names_por_protocolo = {}
for att in attachments:
    protocolo = att.get("protocol")
    file_name = att.get("fileName")
    if not protocolo:
        continue
    file_names_por_protocolo.setdefault(protocolo, []).append(file_name)

protocols = list(file_names_por_protocolo.keys())

results = notification_collection.find(
    {
        "protocol": {"$in": protocols},
        "status": {"$ne": "Enviado para regulação"}
    },
    {
        "_id": 0,
        "coverage": 1,
        "occurrenceDate": 1,
        "policyNumber": 1,
        "insured.documentNumber": 1,
        "protocol": 1,
        "flowId": 1
    }
)

for item in results:
    item["fileName"] = file_names_por_protocolo.get(item.get("protocol"), [])
    print(item)
