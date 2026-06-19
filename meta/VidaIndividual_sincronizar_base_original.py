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
COLLECTION_DESTINO = "MetaVidaIndividual"

BATCH_SIZE = 2000
MAX_WORKERS = 12
DRY_RUN = False

FILTRO_ORIGEM = {
    "product_code": {"$in": [303, 325, 341, 342, 358, 359, 372, 374, 375, 385, 388, 389, 393, 394]}
}

def load_destino_index() -> set:
    """Carrega chaves (policy_number_i4pro, insured_document) do destino em memória como set."""
    client = MongoClient(MONGO_URI)
    col_destino = client[DB_DESTINO][COLLECTION_DESTINO]

    total = col_destino.estimated_document_count()
    print(f"Carregando índice do destino (~{total} registros)...")

    index = set()
    cursor = col_destino.find(
        {},
        {"policy_number_i4pro": 1, "insured_document": 1, "_id": 0},
        batch_size=10000,
    )

    for doc in cursor:
        pn = doc.get("policy_number_i4pro", "")
        cpf = doc.get("insured_document", "")
        if pn and cpf:
            index.add((str(pn).strip(), str(cpf).strip()))

    client.close()
    print(f"Índice destino carregado: {len(index)} chaves")
    return index

def process_batch(batch: list, destino_index: set) -> dict:
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
                    {"policy_number_i4pro": policy_number, "insured_document": insured_document},
                    {"$set": {"status": "Pendente geração de certificado", "updatedAt": datetime.utcnow()}},
                )
            )
        else:
            inseridos += 1
            novo_doc = {k: v for k, v in doc.items() if k not in ("_id", "status")}
            novo_doc["createdAt"] = datetime.utcnow()
            operations.append(InsertOne(novo_doc))

    if operations and not DRY_RUN:
        col_destino.bulk_write(operations, ordered=False)

    client.close()
    return {"encontrados": encontrados, "inseridos": inseridos}

def main() -> None:
    if not MONGO_URI:
        raise ValueError("Defina PRD_MONGO_SA_EAST.")

    destino_index = load_destino_index()

    client = MongoClient(MONGO_URI)
    col_origem = client[DB_ORIGEM][COLLECTION_ORIGEM]

    total = col_origem.count_documents(FILTRO_ORIGEM)
    print(f"Registros na base original (filtrados): {total}")

    cursor = col_origem.find(FILTRO_ORIGEM, batch_size=5000, no_cursor_timeout=True)
    batches = []
    batch = []

    print("Carregando origem em batches...")
    for doc in tqdm(cursor, total=total, desc="Lendo origem"):
        batch.append(doc)
        if len(batch) >= BATCH_SIZE:
            batches.append(batch)
            batch = []

    if batch:
        batches.append(batch)

    cursor.close()
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
