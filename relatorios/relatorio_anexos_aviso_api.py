import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DB_NAME = "SinistrosMicroService"
FILTER_DATE = datetime(2026, 3, 1)
OUTPUT_FILE = "relatorios/relatorio_anexos_aviso_api.xlsx"

def main():
    if not MONGO_URI:
        raise ValueError("Defina PRD_MONGO_URI.")

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    print("Buscando protocolos com 'Aviso API'...")
    aviso_cursor = db["AvisoSinistro"].find(
        {"InformacoesComplementares.origemdocumento": {"$regex": "Aviso API", "$options": "i"}},
        {"Protocolo": 1, "Segurado.CpfCnpj": 1, "_id": 0},
        batch_size=10000,
    )

    protocolo_cpf_map = {}
    for doc in aviso_cursor:
        protocolo = doc.get("Protocolo")
        if protocolo:
            cpf = (doc.get("Segurado") or {}).get("CpfCnpj") or ""
            protocolo_cpf_map[protocolo] = cpf

    print(f"Protocolos 'Aviso API': {len(protocolo_cpf_map)}")

    if not protocolo_cpf_map:
        print("Nenhum protocolo encontrado. Encerrando.")
        client.close()
        return

    print("Buscando anexos em paralelo...")
    protocolos_list = list(protocolo_cpf_map.keys())
    BATCH_SIZE = 500
    MAX_WORKERS = 8
    batches = [protocolos_list[i:i + BATCH_SIZE] for i in range(0, len(protocolos_list), BATCH_SIZE)]

    def fetch_anexos_batch(batch):
        c = MongoClient(MONGO_URI)
        col = c[DB_NAME]["AvisoSinistroAnexo"]
        anexos = col.find(
            {
                "Protocolo": {"$in": batch},
                "DataInclusaoAnexo": {"$gt": FILTER_DATE},
            },
            {"Key": 1, "DataInclusaoAnexo": 1, "Protocolo": 1, "_id": 0},
            batch_size=5000,
        )
        batch_results = []
        for anexo in anexos:
            protocolo = anexo.get("Protocolo")
            dt = anexo.get("DataInclusaoAnexo")
            batch_results.append({
                "Key": anexo.get("Key") or "",
                "DataInclusaoAnexo": dt.strftime("%d/%m/%Y %H:%M:%S") if isinstance(dt, datetime) else str(dt or ""),
                "Protocolo": protocolo,
                "Segurado_CpfCnpj": protocolo_cpf_map.get(protocolo, ""),
            })
        c.close()
        return batch_results

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_anexos_batch, b): b for b in batches}
        with tqdm(total=len(futures), desc="Batches anexos") as pbar:
            for future in as_completed(futures):
                results.extend(future.result())
                pbar.update(1)

    client.close()

    df = pd.DataFrame(results)
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    df.to_excel(OUTPUT_FILE, index=False)

    print(f"\nResultados: {len(results)} registros")
    print(f"Salvo em: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
