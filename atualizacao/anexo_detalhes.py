import os

from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("HML_MONGO_URI"))
db = client['DocumentManagement']
detalhes_collection = db['EboxDetalhes']
anexo_collection = db['AnexoDetalhes']

def update_document(b):
    anexo_collection.update_many(
        {"NomeArquivo": b['NomeArquivo']},
        {
            "$set": {
                "Obs": b['Observacoes']
            }
        }
    )

detalhes = list(detalhes_collection.find())

with ThreadPoolExecutor(max_workers=20) as executor:
    futures = {executor.submit(update_document, b): b for b in detalhes}
    for future in as_completed(futures):
        b = futures[future]
        try:
            future.result()
            print(f"Atualização bem-sucedida para: {b['Anexo']['Nome']}")
        except Exception as e:
            print(f"Erro ao atualizar {b['Anexo']['Nome']}: {e}")
