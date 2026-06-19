import os

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

mongo_url = os.getenv("HML_MONGO_URI")

from pymongo import MongoClient
from bson.objectid import ObjectId
import sys
import traceback

CSV_FILE = "find_query_with_keys_en.csv"
ID_FIELD = "_id"
DOC_FIELD = "DOC_TYPE_KEY"
TARGET_FIELD = "document"
DB_NAME = "ClaimEngine"
COLLECTION_NAME = "DocumentTypeMappings"

def try_objectid(val):
    if isinstance(val, str) and len(val.strip()) == 24:
        try:
            return ObjectId(val.strip())
        except Exception:
            return val.strip()
    return val

def main():
    try:
        df = pd.read_csv(CSV_FILE, dtype=str).fillna("")
    except Exception as e:
        print("Erro ao ler o CSV:", e)
        sys.exit(1)

    if ID_FIELD not in df.columns or DOC_FIELD not in df.columns:
        print(f"CSV não contém as colunas esperadas: {ID_FIELD} ou {DOC_FIELD}")
        print("Colunas do CSV:", list(df.columns))
        sys.exit(1)

    try:
        client = MongoClient(mongo_url)
        coll = client[DB_NAME][COLLECTION_NAME]
        client.admin.command('ping')
    except Exception as e:
        print("Erro ao conectar no MongoDB:")
        traceback.print_exc()
        sys.exit(1)

    total = 0
    updated = 0

    for _, row in df[[ID_FIELD, DOC_FIELD]].iterrows():
        total += 1
        raw_id = row[ID_FIELD]
        new_val = row[DOC_FIELD]

        if not raw_id or not new_val:
            continue

        _id = try_objectid(raw_id)

        try:
            res = coll.update_one({"_id": _id}, {"$set": {TARGET_FIELD: new_val}})
            if res.matched_count:
                updated += 1
            else:
                pass
        except Exception:
            print("Erro ao atualizar _id:", raw_id)
            traceback.print_exc()

    print(f"Linhas processadas: {total}")
    print(f"Documentos atualizados: {updated}")

if __name__ == "__main__":
    main()
