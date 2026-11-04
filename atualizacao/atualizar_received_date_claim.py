"""
Notification + Claim sem receivedDate -> busca maior CreatedAt na Attachment.
Usa aggregation em batch + bulk_write.
"""

import os

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateMany
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
DB_NAME = "ClaimEngine"
BATCH = 5000

SEM_RECEIVED = {"$or": [
    {"receivedDate": {"$exists": False}},
    {"receivedDate": None}
]}


def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    print("Coletando protocolos sem receivedDate em Notification + Claim...")
    protocolos = set()
    for col_name in ["Notification", "Claim"]:
        for doc in db[col_name].find(SEM_RECEIVED, {"protocol": 1}):
            proto = doc.get("protocol")
            if proto:
                protocolos.add(proto)

    protocolo_list = list(protocolos)
    print(f"Protocolos únicos: {len(protocolo_list)}")

    if not protocolo_list:
        print("Nada para processar.")
        client.close()
        return

    # Aggregation em batch
    print("Agregando maior CreatedAt na Attachment...")
    max_dates = {}
    for i in tqdm(range(0, len(protocolo_list), BATCH), desc="Agregando", unit="lote"):
        batch = protocolo_list[i:i+BATCH]
        pipeline = [
            {"$match": {"protocol": {"$in": batch}}},
            {"$group": {"_id": "$protocol", "maxCreatedAt": {"$max": "$CreatedAt"}}}
        ]
        for doc in db["Attachment"].aggregate(pipeline, allowDiskUse=True):
            proto = doc["_id"]
            if proto and doc.get("maxCreatedAt"):
                max_dates[proto] = doc["maxCreatedAt"]

    print(f"Protocolos com anexo: {len(max_dates)}")

    if not max_dates:
        print("Nenhum anexo encontrado.")
        client.close()
        return

    # Bulk update
    items = list(max_dates.items())
    total_notification = 0
    total_claim = 0

    for i in tqdm(range(0, len(items), BATCH), desc="Atualizando", unit="lote"):
        batch = items[i:i+BATCH]
        operations = [
            UpdateMany(
                {"protocol": proto, **SEM_RECEIVED},
                {"$set": {"receivedDate": max_date}}
            )
            for proto, max_date in batch
        ]
        r1 = db["Notification"].bulk_write(operations, ordered=False)
        r2 = db["Claim"].bulk_write(operations, ordered=False)
        total_notification += r1.modified_count
        total_claim += r2.modified_count

    client.close()

    print(f"\nFinalizado!")
    print(f"  Notification atualizados: {total_notification}")
    print(f"  Claim atualizados: {total_claim}")
    print(f"  Sem anexo: {len(protocolo_list) - len(max_dates)}")


if __name__ == "__main__":
    main()
