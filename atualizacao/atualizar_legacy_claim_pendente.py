"""
Busca LegacyAttachment dos últimos 30 dias (por CreatedAt),
pega o protocolo, consulta LegacyClaim com status "Importado"
e atualiza para "Pendente" + UpdatedAt + receivedDate.
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
WORKERS = 8

lock = threading.Lock()
counters = {"atualizados": 0, "ignorados": 0}


def processar_protocolo(protocolo):
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    try:
        ultimo_anexo = db["LegacyAttachment"].find_one(
            {"protocol": protocolo},
            {"CreatedAt": 1},
            sort=[("CreatedAt", -1)]
        )
        received_date = (ultimo_anexo or {}).get("CreatedAt")

        update_fields = {
            "status": "Pendente",
            "userCode": "usr_claim-engine",
            "UpdatedAt": datetime.utcnow()
        }
        if received_date:
            update_fields["receivedDate"] = received_date

        result = db["LegacyClaim"].update_many(
            {"protocol": protocolo, "status": "Importado"},
            {"$set": update_fields}
        )

        with lock:
            if result.modified_count > 0:
                counters["atualizados"] += result.modified_count
            else:
                counters["ignorados"] += 1
    finally:
        client.close()


def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    data_limite = datetime.utcnow() - timedelta(days=30)

    print(f"Buscando LegacyAttachment com CreatedAt >= {data_limite.isoformat()}...")

    attachments = db["LegacyAttachment"].find(
        {"CreatedAt": {"$gte": data_limite}},
        {"protocol": 1}
    )

    protocolos = set()
    for att in attachments:
        proto = att.get("protocol")
        if proto:
            protocolos.add(proto)

    client.close()

    print(f"Protocolos únicos encontrados: {len(protocolos)}")

    if not protocolos:
        print("Nada para processar.")
        return

    with tqdm(total=len(protocolos), desc="Atualizando LegacyClaim", unit="doc") as pbar:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(processar_protocolo, p): p for p in protocolos}
            for future in as_completed(futures):
                future.result()
                pbar.update(1)

    print(f"\nFinalizado!")
    print(f"  Protocolos: {len(protocolos)}")
    print(f"  Atualizados: {counters['atualizados']}")
    print(f"  Ignorados: {counters['ignorados']}")


if __name__ == "__main__":
    main()
