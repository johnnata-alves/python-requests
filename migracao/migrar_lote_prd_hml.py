"""
Migra registros com Status "Lote" da AvisoSinistroAutomacao (PRD):
1. Verifica se já foi importado em HML (idempotência)
2. Busca AvisoSinistro e AvisoSinistroAnexo por Protocolo em PRD
3. Insere nas mesmas collections em HML
4. Atualiza status: "Lote Sucesso" ou "Lote Erro" + message
"""

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

PRD_MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
HML_MONGO_URI = os.getenv("HML_MONGO_URI")
DB_NAME = "SinistrosMicroService"
WORKERS = int(os.getenv("WORKERS", "8"))

lock = threading.Lock()
counters = {"sucesso": 0, "erro": 0, "ja_importado": 0}


def get_connections():
    prd = MongoClient(PRD_MONGO_URI)
    hml = MongoClient(HML_MONGO_URI)
    return prd, hml


def processar_item(item):
    prd_client, hml_client = get_connections()
    prd_db = prd_client[DB_NAME]
    hml_db = hml_client[DB_NAME]

    col_automacao = hml_db["AvisoSinistroAutomacao"]

    item_id = item["_id"]
    protocolo = item.get("Protocolo")
    sinistro = item.get("Sinistro", "?")

    try:
        if not protocolo:
            raise ValueError("Protocolo vazio no registro")

        # Verificar se já foi importado em HML
        aviso_existente = hml_db["AvisoSinistro"].find_one({"Protocolo": protocolo}, {"_id": 1})
        if aviso_existente:
            col_automacao.update_one(
                {"_id": item_id},
                {"$set": {
                    "Status": "Lote Sucesso",
                    "message": "Já importado anteriormente em HML",
                    "ProcessamentoLote": datetime.utcnow()
                }}
            )
            with lock:
                counters["ja_importado"] += 1
            return

        # Buscar AvisoSinistro em PRD
        avisos = list(prd_db["AvisoSinistro"].find({"Protocolo": protocolo}))
        if not avisos:
            raise ValueError(f"AvisoSinistro não encontrado para protocolo {protocolo}")

        # Buscar AvisoSinistroAnexo em PRD
        anexos = list(prd_db["AvisoSinistroAnexo"].find({"Protocolo": protocolo}))

        # Inserir em HML
        for aviso in avisos:
            hml_db["AvisoSinistro"].replace_one(
                {"_id": aviso["_id"]}, aviso, upsert=True
            )

        for anexo in anexos:
            hml_db["AvisoSinistroAnexo"].replace_one(
                {"_id": anexo["_id"]}, anexo, upsert=True
            )

        col_automacao.update_one(
            {"_id": item_id},
            {"$set": {
                "Status": "Lote Sucesso",
                "message": f"Importado {len(avisos)} aviso(s) e {len(anexos)} anexo(s) para HML",
                "ProcessamentoLote": datetime.utcnow()
            }}
        )
        with lock:
            counters["sucesso"] += 1

    except Exception as e:
        col_automacao.update_one(
            {"_id": item_id},
            {"$set": {
                "Status": "Lote Erro",
                "message": str(e),
                "ProcessamentoLote": datetime.utcnow()
            }}
        )
        with lock:
            counters["erro"] += 1

    finally:
        prd_client.close()
        hml_client.close()


def main():
    hml_client = MongoClient(HML_MONGO_URI)
    hml_db = hml_client[DB_NAME]

    lotes = list(hml_db["AvisoSinistroAutomacao"].find({"Status": "Lote"}))
    hml_client.close()

    total = len(lotes)
    print(f"Registros com Status 'Lote': {total}")
    print(f"Workers: {WORKERS}\n")

    if not lotes:
        print("Nada para processar.")
        return

    with tqdm(total=total, desc="Migrando", unit="doc") as pbar:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {executor.submit(processar_item, item): item for item in lotes}

            for future in as_completed(futures):
                future.result()
                pbar.update(1)

    print(f"\nFinalizado!")
    print(f"  Total:          {total}")
    print(f"  Sucesso:        {counters['sucesso']}")
    print(f"  Já importado:   {counters['ja_importado']}")
    print(f"  Erro:           {counters['erro']}")


if __name__ == "__main__":
    main()
