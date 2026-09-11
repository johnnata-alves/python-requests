"""
Busca LegacyClaim com protocol "SIN-*", cria um novo protocolo via API
(PROTOCOLO_API_URL) e atualiza o protocol na LegacyClaim, LegacyDocument
e LegacyAttachment correspondentes (mesmo protocol antigo SIN-*).
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

MONGO_URI_CLAIM = os.getenv("PRD_MONGO_URI")
DB_CLAIM = "ClaimEngine"
WORKERS = 20

PROTOCOLO_URL = os.getenv("PROTOCOLO_API_URL")
INTERNAL_CLIENT_ID = os.getenv("INTERNAL_CLIENT_ID")

lock = threading.Lock()
totais = {"atualizado": 0, "erro": 0, "documents": 0, "attachments": 0}


def gerar_protocolo():
    """Cria um novo protocolo na API e retorna o protocolNumber."""
    response = requests.post(
        PROTOCOLO_URL,
        headers={"clientID": INTERNAL_CLIENT_ID},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if "protocolNumber" not in data:
        raise RuntimeError("Resposta invalida do servico de protocolo.")
    return data["protocolNumber"]


def processar_claim(claim):
    client_claim = MongoClient(MONGO_URI_CLAIM)
    db_claim = client_claim[DB_CLAIM]

    claim_id = claim["_id"]
    protocolo_antigo = claim.get("protocol")

    try:
        novo_protocolo = gerar_protocolo()
        agora = datetime.now(timezone.utc)

        db_claim["LegacyClaim"].update_one(
            {"_id": claim_id},
            {"$set": {"protocol": novo_protocolo, "UpdatedAt": agora}},
        )

        # Atualiza documentos e anexos que apontam para o protocolo antigo SIN-*
        docs = db_claim["LegacyDocument"].update_many(
            {"protocol": protocolo_antigo},
            {"$set": {"protocol": novo_protocolo, "UpdatedAt": agora}},
        )
        attach = db_claim["LegacyAttachment"].update_many(
            {"protocol": protocolo_antigo},
            {"$set": {"protocol": novo_protocolo, "UpdatedAt": agora}},
        )

        with lock:
            totais["atualizado"] += 1
            totais["documents"] += docs.modified_count
            totais["attachments"] += attach.modified_count

    except Exception:
        with lock:
            totais["erro"] += 1

    finally:
        client_claim.close()


def main():
    client = MongoClient(MONGO_URI_CLAIM)
    db = client[DB_CLAIM]

    print("Buscando LegacyClaim com protocol SIN-*...")
    filtro = {"protocol": {"$regex": "^SIN-", "$options": "i"}}

    claims = list(db["LegacyClaim"].find(filtro, {"_id": 1, "protocol": 1}))
    client.close()

    print(f"Total LegacyClaim encontradas: {len(claims)}")

    if not claims:
        print("Nada para processar.")
        return

    with tqdm(total=len(claims), desc="Gerando protocolo", unit="doc") as pbar:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(processar_claim, c): c for c in claims}
            for future in as_completed(futures):
                future.result()
                pbar.update(1)

    print(f"\nFinalizado!")
    print(f"  Total: {len(claims)}")
    print(f"  LegacyClaim atualizados: {totais['atualizado']}")
    print(f"  LegacyDocument atualizados: {totais['documents']}")
    print(f"  LegacyAttachment atualizados: {totais['attachments']}")
    print(f"  Erros: {totais['erro']}")


if __name__ == "__main__":
    main()
