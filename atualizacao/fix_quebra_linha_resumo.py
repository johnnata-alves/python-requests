import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("HML_MONGO_URI")
client = MongoClient(MONGO_URI)
db = client["NotificationEngine"]
collection = db["templates"]

def corrigir_quebra():
    templates = collection.find({})
    total = 0
    corrigidos = 0

    for template in templates:
        total += 1
        resumo = template.get("resumo_da_ocorrencia", "")
        if not resumo:
            continue

        if "\n\nResumo:\n" in resumo:
            continue

        if "\nResumo:\n" not in resumo:
            continue

        resumo_corrigido = resumo.replace("\nResumo:\n", "\n\nResumo:\n")

        collection.update_one(
            {"_id": template["_id"]},
            {"$set": {"resumo_da_ocorrencia": resumo_corrigido}}
        )
        corrigidos += 1
        print(f"[OK] {template.get('name', template['_id'])} - quebra de linha adicionada")

    print(f"\nFinalizado. Total: {total} | Corrigidos: {corrigidos}")
    client.close()

if __name__ == "__main__":
    corrigir_quebra()
