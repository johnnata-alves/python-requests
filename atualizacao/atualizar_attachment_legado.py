"""
Busca AvisoSinistroAnexo com DataInclusaoAnexo > 01/01/2026,
verifica se protocolo existe na LegacyClaim,
se o anexo existe na LegacyAttachment,
e se DataInclusaoAnexo > receivedDate da LegacyClaim, atualiza receivedDate.
Roda em 10 threads.
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient, DESCENDING
from tqdm import tqdm

load_dotenv()

MONGO_URI_SINISTRO = os.getenv("PRD_MONGO_SA_EAST")
MONGO_URI_CLAIM = os.getenv("PRD_MONGO_URI")
DB_SINISTRO = "SinistrosMicroService"
DB_CLAIM = "ClaimEngine"
WORKERS = 10
DATA_CORTE = datetime(2026, 7, 1)

lock = threading.Lock()
totais = {"atualizados": 0, "sem_legacy": 0, "ja_atualizado": 0, "inseridos": 0}


def processar_protocolo(protocolo, anexos):
    client_claim = MongoClient(MONGO_URI_CLAIM)
    db_claim = client_claim[DB_CLAIM]

    # Verificar se protocolo existe na LegacyClaim
    legacy = db_claim["LegacyClaim"].find_one(
        {"protocol": protocolo},
        {"receivedDate": 1}
    )

    if not legacy:
        with lock:
            totais["sem_legacy"] += 1
        client_claim.close()
        return

    # Inserir anexos que não existem na LegacyAttachment
    inseridos = 0
    max_data = None

    for anexo in anexos:
        hash_val = anexo.get("Hash")
        key_val = anexo.get("Key")
        data_inclusao = anexo.get("DataInclusaoAnexo")

        # Verificar se já existe pelo hash
        existe = db_claim["LegacyAttachment"].find_one(
            {"protocol": protocolo, "hash": hash_val},
            {"_id": 1}
        )

        if not existe:
            doc = {
                "UpdatedUserName": None,
                "UpdatedAt": None,
                "CreatedAt": data_inclusao,
                "DeliveryAt": None,
                "protocol": protocolo,
                "key": key_val,
                "insertDate": data_inclusao,
                "status": "Pending",
                "tipificationCode": None,
                "tipificationDate": None,
                "documentTypeCode": None,
                "documentTypeNames": None,
                "documentTypes": None,
                "erpDocuments": None,
                "suggestedDocumentCode": None,
                "metadata": None,
                "metadataSuccess": False,
                "metadataValidationSuccess": False,
                "integrationStep": None,
                "userCode": "api-legado-v5",
                "hash": hash_val,
                "sizeKb": 100,
                "fileName": key_val.split("/")[-1] if key_val else "",
                "isOpen": False,
                "origin": "Formulário de Aviso Too",
                "notes": "",
                "beneficiaryCode": None,
                "calls": [],
                "relatedDocumentFlowIds": None,
                "errors": [],
                "documentTypificationCall": None,
            }
            db_claim["LegacyAttachment"].insert_one(doc)
            inseridos += 1

        if data_inclusao and (max_data is None or data_inclusao > max_data):
            max_data = data_inclusao

    # Atualizar receivedDate se DataInclusaoAnexo > receivedDate atual
    received = legacy.get("receivedDate")
    if max_data and (not received or max_data > received):
        db_claim["LegacyClaim"].update_many(
            {"protocol": protocolo},
            {"$set": {"receivedDate": max_data}}
        )
        with lock:
            totais["atualizados"] += 1
    else:
        with lock:
            totais["ja_atualizado"] += 1

    with lock:
        totais["inseridos"] += inseridos

    client_claim.close()


def main():
    client_sinistro = MongoClient(MONGO_URI_SINISTRO)
    db_sinistro = client_sinistro[DB_SINISTRO]

    print(f"Buscando AvisoSinistroAnexo com DataInclusaoAnexo > {DATA_CORTE.isoformat()}...")

    # Agrupar anexos por protocolo
    from collections import defaultdict
    protocolo_map = defaultdict(list)

    cursor = db_sinistro["AvisoSinistroAnexo"].find(
        {"DataInclusaoAnexo": {"$gt": DATA_CORTE} },
        {"Protocolo": 1, "Hash": 1, "Key": 1, "DataInclusaoAnexo": 1}
    )
    for doc in cursor:
        proto = doc.get("Protocolo")
        if proto:
            protocolo_map[proto].append(doc)

    client_sinistro.close()

    print(f"Protocolos únicos com anexos após corte: {len(protocolo_map)}")

    if not protocolo_map:
        print("Nada para processar.")
        return

    items = list(protocolo_map.items())

    with tqdm(total=len(items), desc="Processando", unit="doc") as pbar:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {
                executor.submit(processar_protocolo, proto, anexos): proto
                for proto, anexos in items
            }
            for future in as_completed(futures):
                future.result()
                pbar.update(1)

    print(f"\nFinalizado!")
    print(f"  Protocolos processados: {len(protocolo_map)}")
    print(f"  LegacyClaim atualizados: {totais['atualizados']}")
    print(f"  LegacyAttachment inseridos: {totais['inseridos']}")
    print(f"  Sem LegacyClaim: {totais['sem_legacy']}")
    print(f"  Já com receivedDate maior: {totais['ja_atualizado']}")


if __name__ == "__main__":
    main()
