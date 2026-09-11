"""
Busca Attachments dos últimos 7 dias, agrupa maior CreatedAt por protocolo,
atualiza receivedDate nas collections: Notification, Claim e LegacyClaim.
Roda em 10 threads.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
DB_NAME = "ClaimEngine"
WORKERS = 10
DIAS = 7

lock = threading.Lock()
totais = {"Notification": 0, "Claim": 0, "LegacyClaim": 0}


def atualizar_protocolo(protocolo, max_date):
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    local = {"Notification": 0, "Claim": 0, "LegacyClaim": 0}

    for col_name in ["Notification", "Claim", "LegacyClaim"]:
        result = db[col_name].update_many(
            {"protocol": protocolo},
            {"$set": {"receivedDate": max_date}}
        )
        local[col_name] = result.modified_count

    client.close()

    with lock:
        for k in local:
            totais[k] += local[k]


def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    data_limite = datetime.utcnow() - timedelta(days=DIAS)

    print(f"Agregando maior CreatedAt por protocolo na Attachment (últimos {DIAS} dias)...")

    pipeline = [
        {"$match": {"CreatedAt": {"$gte": data_limite}}},
        {"$group": {
            "_id": "$protocol",
            "maxCreatedAt": {"$max": "$CreatedAt"}
        }}
    ]

    protocolo_map = {}
    for doc in db["Attachment"].aggregate(pipeline, allowDiskUse=True):
        proto = doc["_id"]
        if proto:
            protocolo_map[proto] = doc["maxCreatedAt"]

    client.close()

    print(f"Protocolos únicos: {len(protocolo_map)}")

    if not protocolo_map:
        print("Nada para processar.")
        return

    items = list(protocolo_map.items())

    with tqdm(total=len(items), desc="Atualizando receivedDate", unit="doc") as pbar:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {
                executor.submit(atualizar_protocolo, proto, max_date): proto
                for proto, max_date in items
            }
            for future in as_completed(futures):
                future.result()
                pbar.update(1)

    print(f"\nFinalizado!")
    print(f"  Protocolos processados: {len(protocolo_map)}")
    for col_name in ["Notification", "Claim", "LegacyClaim"]:
        print(f"  {col_name} atualizados: {totais[col_name]}")


if __name__ == "__main__":
    main()
