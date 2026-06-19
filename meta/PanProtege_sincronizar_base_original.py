import os
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")

DB_ORIGEM = "indexed_customer_files"
COLLECTION_ORIGEM = "individual_policies_without_cert"

DB_DESTINO = "testeMigracao"
COLLECTION_DESTINO = "MetaPanProtege"

DRY_RUN = False

FILTRO_ORIGEM = {
    "product_code": {"$in": [215, 200, 218, 225, 246, 251, 260, 272, 274, 301, 302, 310, 360, 365, 371, 342]}
}

def main() -> None:
    if not MONGO_URI:
        raise ValueError("Defina PRD_MONGO_SA_EAST.")

    client = MongoClient(MONGO_URI)
    col_origem = client[DB_ORIGEM][COLLECTION_ORIGEM]
    col_destino = client[DB_DESTINO][COLLECTION_DESTINO]

    print("Carregando índice do destino...")
    destino_index = set()
    for doc in col_destino.find({}, {"policy_number": 1, "nr_cnpj_cpf": 1, "_id": 0}, batch_size=10000):
        pn = doc.get("policy_number", "")
        cpf = doc.get("nr_cnpj_cpf", "")
        if pn and cpf:
            destino_index.add((str(pn).strip(), str(cpf).strip()))
    print(f"Índice destino: {len(destino_index)} chaves")

    total = col_origem.count_documents(FILTRO_ORIGEM)
    print(f"Registros na origem: {total}")

    novos = []
    existentes = []

    print("Classificando registros...")
    cursor = col_origem.find(FILTRO_ORIGEM, {"policy_number_i4pro": 1, "insured_document": 1, "product_name": 1}, batch_size=10000, no_cursor_timeout=True)

    origem_index = set()
    for doc in tqdm(cursor, total=total, desc="Lendo origem"):
        pn = str(doc.get("policy_number_i4pro", "")).strip()
        cpf = str(doc.get("insured_document", "")).strip()
        if not pn or not cpf:
            continue

        origem_index.add((pn, cpf))
        key = (pn, cpf)

        if key in destino_index:
            existentes.append(key)
        else:
            novos.append({
                "cd_apolice": pn,
                "nr_cnpj_cpf": cpf,
                "policy_number": pn,
                "product_name": str(doc.get("product_name", "")).strip(),
                "Ramo": "PanProtege",
                "createdAt": datetime.utcnow(),
            })

    cursor.close()

    print(f"Novos para inserir: {len(novos)}")
    print(f"Existentes para atualizar: {len(existentes)}")

    if novos and not DRY_RUN:
        batch_size = 5000
        for i in tqdm(range(0, len(novos), batch_size), desc="Inserindo novos"):
            chunk = novos[i:i + batch_size]
            col_destino.insert_many(chunk, ordered=False)

    if existentes and not DRY_RUN:
        from collections import defaultdict
        por_policy = defaultdict(list)
        for pn, cpf in existentes:
            por_policy[pn].append(cpf)

        batch_size = 100
        policy_keys = list(por_policy.keys())
        total_atualizado = 0

        for i in tqdm(range(0, len(policy_keys), batch_size), desc="Atualizando existentes"):
            chunk_keys = policy_keys[i:i + batch_size]
            filters = []
            for pn in chunk_keys:
                cpfs = por_policy[pn]
                if len(cpfs) == 1:
                    filters.append({"policy_number": pn, "nr_cnpj_cpf": cpfs[0]})
                else:
                    filters.append({"policy_number": pn, "nr_cnpj_cpf": {"$in": cpfs}})

            result = col_destino.update_many(
                {"$or": filters},
                {"$set": {"status": "Pendente geração de certificado", "updatedAt": datetime.utcnow()}},
            )
            total_atualizado += result.modified_count

    removidos_keys = destino_index - origem_index
    print(f"Registros a marcar como removido: {len(removidos_keys)}")

    if removidos_keys and not DRY_RUN:
        batch_size = 500
        removidos_list = list(removidos_keys)
        for i in tqdm(range(0, len(removidos_list), batch_size), desc="Marcando removidos"):
            chunk = removidos_list[i:i + batch_size]
            filters = [{"policy_number": pn, "nr_cnpj_cpf": cpf} for pn, cpf in chunk]
            col_destino.update_many(
                {"$or": filters},
                {"$set": {"status": "removido", "updatedAt": datetime.utcnow()}},
            )

    client.close()

    print(
        f"\nResumo | "
        f"inseridos: {len(novos)} | "
        f"atualizados: {len(existentes)} | "
        f"removidos: {len(removidos_keys)}"
    )

if __name__ == "__main__":
    main()
