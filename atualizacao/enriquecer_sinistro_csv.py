"""
Enriquece corrigir_saldo_automacao.csv com o campo Sinistro
da collection AvisoSinistroAutomacao, cruzando pelo _id.
Gera novo arquivo com a coluna Sinistro adicionada.
"""

import csv
import os
import warnings

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

warnings.filterwarnings("ignore")

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DB_NAME = "SinistrosMicroService"
COL_AUTOMACAO = "AvisoSinistroAutomacao"

INPUT_CSV = "corrigir_saldo_automacao.csv"
OUTPUT_CSV = "corrigir_saldo_automacao_sinistro.csv"


def main():
    if not MONGO_URI:
        print("ERRO: PRD_MONGO_SA_EAST nao configurado no .env")
        return

    if not os.path.exists(INPUT_CSV):
        print(f"ERRO: {INPUT_CSV} nao encontrado")
        return

    client = MongoClient(MONGO_URI)
    col = client[DB_NAME][COL_AUTOMACAO]

    with open(INPUT_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        linhas = list(reader)
        campos = list(reader.fieldnames or [])

    # coletar _ids validos e buscar Sinistro em lote
    ids = []
    for linha in linhas:
        try:
            ids.append(ObjectId(linha["_id"]))
        except Exception:
            pass

    sinistro_por_id = {}
    for doc in tqdm(
        col.find({"_id": {"$in": ids}}, {"Sinistro": 1}),
        total=len(ids),
        desc="Buscando Sinistro",
        unit="reg",
    ):
        sinistro_por_id[str(doc["_id"])] = doc.get("Sinistro")

    client.close()

    if "Sinistro" not in campos:
        campos.append("Sinistro")

    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        writer.writeheader()
        for linha in linhas:
            linha["Sinistro"] = sinistro_por_id.get(linha["_id"], "")
            writer.writerow(linha)

    print(f"\nFinalizado! {len(linhas)} linhas.")
    print(f"  Sinistros encontrados: {len(sinistro_por_id)}")
    print(f"  CSV: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
