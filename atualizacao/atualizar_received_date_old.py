"""
Atualiza receivedDate em paralelo:
1) Notification + Claim sem receivedDate -> busca maior CreatedAt na Attachment
2) LegacyClaim sem receivedDate -> busca maior CreatedAt na LegacyAttachment
Ambos rodam em paralelo com 10 threads cada.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from pymongo import MongoClient, DESCENDING
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
DB_NAME = "ClaimEngine"
WORKERS = 10

SEM_RECEIVED = {"$or": [
    {"receivedDate": {"$exists": False}},
    {"receivedDate": None}
]}


def processar_notification_claim(protocolos):
    """Método 1: Notification + Claim -> Attachment"""
    lock = threading.Lock()
    totais = {"notification": 0, "claim": 0, "sem_anexo": 0}

    def processar(protocolo):
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]

        att = db["Attachment"].find_one(
            {"protocol": protocolo},
            {"CreatedAt": 1},
            sort=[("CreatedAt", DESCENDING)]
        )

        if not att or not att.get("CreatedAt"):
            with lock:
                totais["sem_anexo"] += 1
            client.close()
            return

        max_date = att["CreatedAt"]
        filtro = {"protocol": protocolo, **SEM_RECEIVED}

        r1 = db["Notification"].update_many(filtro, {"$set": {"receivedDate": max_date}})
        r2 = db["Claim"].update_many(filtro, {"$set": {"receivedDate": max_date}})

        with lock:
            totais["notification"] += r1.modified_count
            totais["claim"] += r2.modified_count

        client.close()

    with tqdm(total=len(protocolos), desc="[1] Notification+Claim", unit="doc") as pbar:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(processar, p): p for p in protocolos}
            for f in as_completed(futures):
                f.result()
                pbar.update(1)

    return totais


def processar_legacy_claim(protocolos):
    """Método 2: LegacyClaim -> LegacyAttachment (otimizado com aggregation em batch)"""
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    print(f"  [2] Agregando maior CreatedAt na LegacyAttachment para {len(protocolos)} protocolos...")

    # Aggregation em batch pra pegar max CreatedAt por protocolo de uma vez
    BATCH = 5000
    protocolo_list = list(protocolos)
    max_dates = {}

    for i in tqdm(range(0, len(protocolo_list), BATCH), desc="[2] Agregando", unit="lote"):
        batch = protocolo_list[i:i+BATCH]
        pipeline = [
            {"$match": {"protocol": {"$in": batch}}},
            {"$group": {"_id": "$protocol", "maxCreatedAt": {"$max": "$CreatedAt"}}}
        ]
        for doc in db["LegacyAttachment"].aggregate(pipeline, allowDiskUse=True):
            proto = doc["_id"]
            if proto and doc.get("maxCreatedAt"):
                max_dates[proto] = doc["maxCreatedAt"]

    print(f"  [2] Protocolos com anexo: {len(max_dates)} / {len(protocolos)}")

    if not max_dates:
        client.close()
        return {"legacy_claim": 0, "sem_anexo": len(protocolos)}

    # Bulk update em lotes
    from pymongo import UpdateMany
    total_updated = 0
    items = list(max_dates.items())

    for i in tqdm(range(0, len(items), BATCH), desc="[2] Atualizando", unit="lote"):
        batch = items[i:i+BATCH]
        operations = [
            UpdateMany(
                {"protocol": proto, "$or": [
                    {"receivedDate": {"$exists": False}},
                    {"receivedDate": None}
                ]},
                {"$set": {"receivedDate": max_date}}
            )
            for proto, max_date in batch
        ]
        result = db["LegacyClaim"].bulk_write(operations, ordered=False)
        total_updated += result.modified_count

    client.close()
    return {"legacy_claim": total_updated, "sem_anexo": len(protocolos) - len(max_dates)}


def coletar_protocolos_sem_received(collections):
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    protocolos = set()

    for col_name in collections:
        for doc in db[col_name].find(SEM_RECEIVED, {"protocol": 1}):
            proto = doc.get("protocol")
            if proto:
                protocolos.add(proto)

    client.close()
    return protocolos


def main():
    # Coletar protocolos em paralelo
    print("Coletando protocolos sem receivedDate...")

    protocolos_nc = coletar_protocolos_sem_received(["Notification", "Claim"])
    print(f"  Notification+Claim: {len(protocolos_nc)} protocolos")

    protocolos_legacy = coletar_protocolos_sem_received(["LegacyClaim"])
    print(f"  LegacyClaim: {len(protocolos_legacy)} protocolos")

    if not protocolos_nc and not protocolos_legacy:
        print("Nada para processar.")
        return

    # Rodar ambos em paralelo
    results = {}

    def run_nc():
        if protocolos_nc:
            results["nc"] = processar_notification_claim(list(protocolos_nc))

    def run_legacy():
        if protocolos_legacy:
            results["legacy"] = processar_legacy_claim(list(protocolos_legacy))

    t1 = threading.Thread(target=run_nc)
    t2 = threading.Thread(target=run_legacy)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print(f"\nFinalizado!")
    if "nc" in results:
        nc = results["nc"]
        print(f"  [1] Notification atualizados: {nc['notification']}")
        print(f"  [1] Claim atualizados: {nc['claim']}")
        print(f"  [1] Sem anexo: {nc['sem_anexo']}")
    if "legacy" in results:
        lg = results["legacy"]
        print(f"  [2] LegacyClaim atualizados: {lg['legacy_claim']}")
        print(f"  [2] Sem anexo: {lg['sem_anexo']}")


if __name__ == "__main__":
    main()
