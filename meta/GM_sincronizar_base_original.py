import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne, InsertOne
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")

DB_ORIGEM = "indexed_customer_files"
COLLECTION_ORIGEM = "individual_policies_without_cert"

DB_DESTINO = "testeMigracao"
COLLECTION_DESTINO = "MetaGM"

BATCH_SIZE = 500
MAX_WORKERS = 8
DRY_RUN = False

FILTRO_ORIGEM = {
    "product_code": {"$in": [262, 273, 288, 315, 316, 330, 331, 369, 381, 386, 387, 392, 396]}
}

def load_destino_index(policy_numbers: list) -> dict:
    """Carrega do destino apenas registros cujo policy_number está na lista."""
    client = MongoClient(MONGO_URI)
    col_destino = client[DB_DESTINO][COLLECTION_DESTINO]

    print(f"Carregando base destino filtrada ({len(policy_numbers)} apólices)...")
    cursor = col_destino.find(
        {"policy_number": {"$in": policy_numbers}},
        {"_id": 1, "policy_number": 1, "nr_cnpj_cpf": 1},
    )

    index = {}
    for doc in cursor:
        pn = str(doc.get("policy_number", "")).strip()
        cpf = str(doc.get("nr_cnpj_cpf", "")).strip()
        if pn and cpf:
            index[(pn, cpf)] = doc["_id"]

    client.close()
    print(f"Base destino carregada: {len(index)} registros")
    return index

def process_batch(batch: list, destino_index: dict) -> dict:
    """Processa um lote comparando em memória e faz bulk_write."""
    client = MongoClient(MONGO_URI)
    col_destino = client[DB_DESTINO][COLLECTION_DESTINO]

    operations = []
    encontrados = 0
    inseridos = 0

    for doc in batch:
        policy_number = str(doc.get("policy_number_i4pro", "")).strip()
        insured_document = str(doc.get("insured_document", "")).strip()

        if not policy_number or not insured_document:
            continue

        key = (policy_number, insured_document)

        if key in destino_index:
            encontrados += 1
            operations.append(
                UpdateOne(
                    {"_id": destino_index[key]},
                    {"$set": {"status": "Pendente geração de certificado", "updatedAt": datetime.utcnow()}},
                )
            )
        else:
            inseridos += 1
            operations.append(
                InsertOne({
                    "cd_apolice": policy_number,
                    "nr_cnpj_cpf": insured_document,
                    "status": "pendente proc",
                    "policy_number": policy_number,
                    "Ramo": "GM",
                    "createdAt": datetime.utcnow(),
                })
            )

    if operations and not DRY_RUN:
        col_destino.bulk_write(operations, ordered=False)

    client.close()
    return {"encontrados": encontrados, "inseridos": inseridos}

def main() -> None:
    if not MONGO_URI:
        raise ValueError("Defina PRD_MONGO_SA_EAST.")

    client = MongoClient(MONGO_URI)
    col_origem = client[DB_ORIGEM][COLLECTION_ORIGEM]

    apolices_origem = col_origem.distinct("policy_number_i4pro", FILTRO_ORIGEM)
    apolices_origem = [str(a).strip() for a in apolices_origem if a]
    print(f"Apólices distintas na origem: {len(apolices_origem)}")

    destino_index = load_destino_index(apolices_origem)

    total = col_origem.count_documents(FILTRO_ORIGEM)
    print(f"Registros na base original (filtrados): {total}")

    cursor = col_origem.find(FILTRO_ORIGEM, {"policy_number_i4pro": 1, "insured_document": 1})
    batches = []
    batch = []

    for doc in cursor:
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            batches.append(batch)
            batch = []

    if batch:
        batches.append(batch)

    client.close()

    print(f"Batches: {len(batches)} | Workers: {MAX_WORKERS}")

    total_encontrados = 0
    total_inseridos = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_batch, b, destino_index): b for b in batches}

        with tqdm(total=len(futures), desc="Processando batches") as pbar:
            for future in as_completed(futures):
                result = future.result()
                total_encontrados += result["encontrados"]
                total_inseridos += result["inseridos"]
                pbar.update(1)

    print(
        f"\nResumo | "
        f"encontrados (atualizados): {total_encontrados} | "
        f"não encontrados (inseridos): {total_inseridos}"
    )

if __name__ == "__main__":
    main()
