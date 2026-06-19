"""
Script para atualizar o campo InformacoesComplementares.origemdocumento na AvisoSinistro
com base na Notification correspondente (pelo Protocolo).

Regras:
- Busca AvisoSinistro sem InformacoesComplementares.origemdocumento e Ramo != FiancaLocaticia
- Para cada registro, busca a Notification pelo protocol
- Se notificationOrigin == "ApiV5" -> salva "Aviso API V4" na AvisoSinistro
- Senão -> mantém o valor de notificationOrigin da Notification
- Se a Notification tiver claimNumber preenchido, adiciona ao array Sinistros na Notification
- Atualiza updatedAt em ambas as collections quando há alteração
"""
import os
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

MONGO_URI_SINISTRO = os.getenv("PRD_MONGO_SA_EAST")
MONGO_URI_NOTIFICATION = os.getenv("PRD_MONGO_URI")
DB_SINISTRO = "SinistrosMicroService"
DB_NOTIFICATION = "ClaimEngine"

BATCH_SIZE = 100
MAX_WORKERS = 20

def make_db_sinistro():
    client = MongoClient(MONGO_URI_SINISTRO)
    return client[DB_SINISTRO]

def make_db_notification():
    client = MongoClient(MONGO_URI_NOTIFICATION)
    return client[DB_NOTIFICATION]

def processar_aviso(aviso, db_sinistro, db_notification):
    """Processa um único AvisoSinistro. Retorna status string."""
    protocolo = aviso.get("Protocolo")
    aviso_id = aviso["_id"]

    if not protocolo:
        return "sem_protocolo"

    col_notification = db_notification["Notification"]
    col_aviso = db_sinistro["AvisoSinistro"]

    notification = col_notification.find_one({"protocol": str(protocolo)})

    if not notification:
        return "notification_nao_encontrada"

    notification_origin = notification.get("notificationOrigin") or ""
    if notification_origin == "ApiV5":
        origem_documento = "Aviso API V4"
    else:
        origem_documento = notification_origin

    now = datetime.utcnow()

    col_aviso.update_one(
        {"_id": aviso_id},
        {
            "$set": {
                "InformacoesComplementares.origemdocumento": origem_documento,
                "updatedAt": now,
            }
        }
    )

    claim_number = notification.get("claimNumber")
    if claim_number and str(claim_number).strip():
        col_notification.update_one(
            {"_id": notification["_id"]},
            {
                "$addToSet": {"Sinistros": str(claim_number).strip()},
                "$set": {"updatedAt": now},
            }
        )
        return "atualizado_com_sinistro"

    return "atualizado"

def main():
    print(f"Conectando: {DB_SINISTRO} + {DB_NOTIFICATION}")
    db_sinistro = make_db_sinistro()
    col_aviso = db_sinistro["AvisoSinistro"]

    filtro = {
        "InformacoesComplementares.origemdocumento": {"$exists": False},
        "Ramo": {"$ne": "FiancaLocaticia"},
    }

    total = col_aviso.count_documents(filtro)
    print(f"Total de avisos a processar: {total}")

    if total == 0:
        print("Nada a processar.")
        return

    stats = {
        "atualizado": 0,
        "atualizado_com_sinistro": 0,
        "notification_nao_encontrada": 0,
        "sem_protocolo": 0,
        "erro": 0,
    }

    start_time = time.time()
    processados = 0

    while True:
        batch = list(col_aviso.find(filtro, {"_id": 1, "Protocolo": 1}).limit(BATCH_SIZE))
        if not batch:
            break

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for aviso in batch:
                thread_db_sinistro = make_db_sinistro()
                thread_db_notification = make_db_notification()
                futures[executor.submit(processar_aviso, aviso, thread_db_sinistro, thread_db_notification)] = aviso

            for future in as_completed(futures):
                try:
                    status = future.result()
                    stats[status] = stats.get(status, 0) + 1
                except Exception as e:
                    stats["erro"] += 1

                processados += 1

        elapsed = time.time() - start_time
        rate = processados / elapsed if elapsed > 0 else 0
        remaining = (total - processados) / rate if rate > 0 else 0
        sys.stdout.write(
            f"\r  Processados: {processados}/{total} | "
            f"{rate:.1f}/s | "
            f"OK={stats['atualizado']} | "
            f"C/Sin={stats['atualizado_com_sinistro']} | "
            f"S/Notif={stats['notification_nao_encontrada']} | "
            f"Err={stats['erro']} | "
            f"Resta: {int(remaining)}s   "
        )
        sys.stdout.flush()

    elapsed = time.time() - start_time
    print(f"\n\n{'=' * 60}")
    print(f"FINALIZADO em {int(elapsed)}s")
    print(f"  Atualizados:                  {stats['atualizado']}")
    print(f"  Atualizados com Sinistro:     {stats['atualizado_com_sinistro']}")
    print(f"  Notification não encontrada:  {stats['notification_nao_encontrada']}")
    print(f"  Sem protocolo:                {stats['sem_protocolo']}")
    print(f"  Erros:                        {stats['erro']}")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()
