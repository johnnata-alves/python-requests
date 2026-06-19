from pymongo import MongoClient, UpdateOne
from datetime import datetime
import os
from dotenv import load_dotenv
load_dotenv()

MONGO_CONNECTION = os.getenv("PRD_MONGO_SA_EAST")
DATABASE = "testeMigracao"
COLLECTION = "MetaPanProtege"

DATAS_CORTE = {
    "365": "07122025",
    "274": "30112025",
    "218": "30112025",
    "246": "03122025",
    "360": "05012026",
    "251": "10122025",
}

STATUS_FORA_CORTE = "fora do corte"

client = MongoClient(MONGO_CONNECTION)
collection = client[DATABASE][COLLECTION]

datas_corte_convertidas = {
    produto: datetime.strptime(data, "%d%m%Y")
    for produto, data in DATAS_CORTE.items()
}

operations = []
batch_size = 1000

total_lidos = 0
total_atualizados = 0
total_fora_corte = 0

cursor = collection.find(
    {
        "details.0.Cod_Produto": {
            "$in": list(DATAS_CORTE.keys())
        }
    },
    {
        "_id": 1,
        "details": 1
    }
)

for doc in cursor:

    try:

        details = doc.get("details")

        if not details or not isinstance(details, list):
            continue

        primeiro_item = details[0]

        produto = primeiro_item.get("Cod_Produto")
        dt_emissao_str = primeiro_item.get("dt_emissao")

        if not produto or not dt_emissao_str:
            continue

        total_lidos += 1

        data_corte = datas_corte_convertidas.get(produto)

        if not data_corte:
            continue

        dt_emissao = datetime.strptime(
            dt_emissao_str,
            "%d%m%Y"
        )

        if dt_emissao > data_corte:

            total_fora_corte += 1

            operations.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {
                        "$set": {
                            "status": STATUS_FORA_CORTE
                        }
                    }
                )
            )

        if len(operations) >= batch_size:

            result = collection.bulk_write(
                operations,
                ordered=False
            )

            total_atualizados += result.modified_count
            operations = []

    except Exception as ex:

        print(
            f"Erro documento {doc['_id']}: {str(ex)}"
        )

if operations:

    result = collection.bulk_write(
        operations,
        ordered=False
    )

    total_atualizados += result.modified_count

print("=" * 50)
print(f"Documentos analisados: {total_lidos}")
print(f"Fora do corte: {total_fora_corte}")
print(f"Atualizados: {total_atualizados}")
print("=" * 50)
