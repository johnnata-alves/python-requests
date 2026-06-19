import os
from dotenv import load_dotenv
import pandas as pd
from pymongo import MongoClient
from bson import ObjectId
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

load_dotenv()

excel_path = "DocumentosSemVinculo.xlsx"

conn_string_1 = os.getenv("DEV_MONGO_URI")
conn_string_2 = os.getenv("PRD_MONGO_URI")

database_name = "ClaimEngine"
collection_name = "Document"

client1 = MongoClient(conn_string_1)
client2 = MongoClient(conn_string_2)

db1 = client1[database_name]
db2 = client2[database_name]

col1 = db1[collection_name]
col2 = db2[collection_name]

df = pd.read_excel(excel_path)

ids = df.iloc[:, 0].dropna().tolist()

print(f"Total de IDs encontrados: {len(ids)}")

total_ids = len(ids)
progress = {
    "processed": 0,
    "updated": 0,
    "not_found": 0,
    "errors": 0
}
progress_lock = threading.Lock()

def process_id(id_str):
    try:
        obj_id = ObjectId(str(id_str))

        doc = col1.find_one(
            {"_id": obj_id},
            {"flowId": 1, "claimNumber": 1, "protocol": 1}
        )

        if not doc:
            with progress_lock:
                progress["processed"] += 1
                progress["not_found"] += 1
                current = progress["processed"]
            print(f"[{current}/{total_ids}] ❌ Não encontrado na origem: {obj_id}")
            return

        flow_id = doc.get("flowId")
        claim_number = doc.get("claimNumber")
        protocol = doc.get("protocol")

        result = col2.update_one(
            {"_id": obj_id},
            {
                "$set": {
                    "flowId": flow_id,
                    "claimNumber": claim_number,
                    "protocol": protocol
                }
            }
        )

        with progress_lock:
            progress["processed"] += 1
            progress["updated"] += 1
            current = progress["processed"]
        print(f"[{current}/{total_ids}] ✅ Atualizado: {obj_id} | matched: {result.matched_count}")

    except Exception as e:
        with progress_lock:
            progress["processed"] += 1
            progress["errors"] += 1
            current = progress["processed"]
        print(f"[{current}/{total_ids}] ⚠️ Erro no ID {id_str}: {e}")

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(process_id, id_str) for id_str in ids]
    for future in as_completed(futures):
        future.result()

print("Processo finalizado.")
print(
    f"Resumo -> Processados: {progress['processed']} | "
    f"Atualizados: {progress['updated']} | "
    f"Não encontrados: {progress['not_found']} | "
    f"Erros: {progress['errors']}"
)
