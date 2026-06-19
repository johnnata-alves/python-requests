import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

mongo_uri = os.getenv("HML_MONGO_URI")
db_name = "SinistrosMicroService"
collection_name = "ProdutoElegivelAutomacao"

client = MongoClient(mongo_uri)
db = client[db_name]

collection = db[collection_name]
def atualizar_texto_recusa():
    documentos = collection.find()

    for documento in documentos:
        coberturas = documento.get("Coberturas", [])

        for cobertura in coberturas:
            regras_automacao = cobertura.get("RegraAutomacaoList", [])

            for regra in regras_automacao:
                if regra.get("Nome") == "PRESCRICAO":
                    if "TextoRecusa" in regra and regra["TextoRecusa"] is not None:
                        regra["TextoRecusa"] = regra["TextoRecusa"].replace("{dataOcorrencia}", "{dataSinistro}")
                        regra["TextoRecusa"] = regra["TextoRecusa"].replace("{dataCominicacao}", "{dataComunicacao}")

            collection.update_one({"_id": documento["_id"]}, {"$set": {"Coberturas": coberturas}})

atualizar_texto_recusa()
print("Atualização concluída.")
