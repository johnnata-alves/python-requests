import os
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
MONGO_DB = "testeMigracao"

TIMEZONE_OFFSET = timezone(timedelta(hours=-3))

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "dados")

MAX_WORKERS = 5

RAMOS = [
    {
        "aba": "GM",
        "collection": "MetaGM",
        "campos": [
            ("details.cd_produto",   "cd_produto"),
            ("details.id_apolice",   "id_apolice"),
            ("details.nr_apolice_1", "nr_apolice"),
            ("details.id_sub",       "id_sub"),
        ],
    },
    {
        "aba": "Coletivo",
        "collection": "MetaColetivo",
        "campos": [
            ("details.cd_produto",  "cd_produto"),
            ("details.cd_apolice",  "cd_apolice"),
            ("details.id_apolice",  "id_apolice"),
            ("details.id_sub",      "id_sub"),
        ],
    },
    {
        "aba": "PanProtege",
        "collection": "MetaPanProtege",
        "campos": [
            ("details.Cod_Produto", "Cod_Produto"),
            ("details.Nr_Apolice",  "Nr_Apolice"),
            ("details.id_apolice",  "id_apolice"),
            ("details.id_sub",      "id_sub"),
        ],
    },
    {
        "aba": "RCF",
        "collection": "MetaRCF",
        "campos": [
            ("details.cd_produto",   "cd_produto"),
            ("details.id_apolice",   "id_apolice"),
            ("details.nr_apolice_1", "nr_apolice"),
            ("details.id_sub",       "id_sub"),
        ],
    },
    {
        "aba": "VidaIndividual",
        "collection": "MetaVidaIndividual",
        "campos": [
            ("details.Cod_Produto", "Cod_Produto"),
            ("details.Nr_Apolice",  "Nr_Apolice"),
            ("details.id_apolice",  "id_apolice"),
            ("details.id_sub",      "id_sub"),
        ],
    },
]

def extrair_ramo(ramo: dict, now: str) -> tuple:
    """
    Executa em thread separada com sua própria conexão Mongo.
    Usa aggregation pipeline com $unwind para extrair items do array details
    diretamente no servidor (evita transferir o documento inteiro para Python).
    """
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    collection = db[ramo["collection"]]

    campos = ramo["campos"]

    campos_detail = []
    for campo_mongo, nome_col in campos:
        chave = campo_mongo.split("details.")[-1]
        campos_detail.append((chave, nome_col))

    project_fields = {}
    group_id_fields = {}
    for chave, nome_col in campos_detail:
        project_fields[nome_col] = f"$details.{chave}"
        group_id_fields[nome_col] = f"${nome_col}"

    pipeline = [
        {"$match": {
            "details.0.TemplateId": {"$in": [None, ""]},
            "details.0.id_template": {"$in": [None, ""]},
        }},
        {"$unwind": "$details"},
        {"$match": {
            "$and": [
                {"$or": [{"details.TemplateId": {"$in": [None, ""]}}, {"details.TemplateId": {"$exists": False}}]},
                {"$or": [{"details.id_template": {"$in": [None, ""]}}, {"details.id_template": {"$exists": False}}]},
            ]
        }},
        {"$project": project_fields},
        {"$group": {"_id": group_id_fields}},
        {"$replaceRoot": {"newRoot": "$_id"}},
    ]

    try:
        cursor = collection.aggregate(pipeline, allowDiskUse=True, batchSize=5000)
        linhas = list(cursor)
    finally:
        client.close()

    df = pd.DataFrame(linhas, columns=[col for _, col in campos_detail])

    output_path = os.path.join(OUTPUT_DIR, f"sem_template_{ramo['aba']}_{now}.xlsx")
    df.to_excel(output_path, index=False, engine="openpyxl")

    return ramo["aba"], len(df), output_path

def main():
    if not MONGO_URI:
        raise ValueError("Defina PRD_MONGO_SA_EAST no ambiente.")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    now = datetime.now(TIMEZONE_OFFSET).strftime("%Y%m%d_%H%M")

    print("=" * 60)
    print("RELATÓRIO: Registros sem TemplateId por ramo")
    print(f"Workers: {MAX_WORKERS} | Ramos: {len(RAMOS)}")
    print("=" * 60)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(extrair_ramo, ramo, now): ramo for ramo in RAMOS}

        for future in as_completed(futures):
            ramo = futures[future]
            try:
                aba, count, path = future.result()
                print(f"  [{aba}] {count} registros distintos -> {path}")
            except Exception as e:
                print(f"  [{ramo['aba']}] ERRO: {e}")

    print(f"\nArquivos gerados em: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
