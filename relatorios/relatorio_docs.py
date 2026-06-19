import os
from dotenv import load_dotenv
import pandas as pd
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
db = client['OCR']
collection = db['AtomicLog_Obito']

registros = list(collection.find())

data = {}

for registro in registros:
    protocolo = registro["Protocolo"]
    if protocolo not in data:
        data[protocolo] = {
            "CertidaoObitoEncontrada": False,
            "DocIdentificacaoEncontrado": False,
            "IdsRetornados": [],
            "Arquivos": [],
            "TiposArquivo": []
        }

    if "Certidão de Óbito" in registro.get("TiposArquivo", []):
        data[protocolo]["CertidaoObitoEncontrada"] = True

    if registro.get("DocumentoIdentificacao", False):
        data[protocolo]["DocIdentificacaoEncontrado"] = True

    data[protocolo]["IdsRetornados"].append(registro["IdRetornado"])
    data[protocolo]["Arquivos"].append(registro["Arquivo"])
    data[protocolo]["TiposArquivo"].extend(registro.get("TiposArquivo", []))

relatorio = []
for protocolo, info in data.items():
    relatorio.append({
        "Protocolo": protocolo,
        "CertidaoObitoEncontrada": info["CertidaoObitoEncontrada"],
        "DocIdentificacaoEncontrado": info["DocIdentificacaoEncontrado"],
        "Lista IdRetornado": ", ".join(info["IdsRetornados"]),
        "Lista Arquivos": ", ".join(info["Arquivos"]),
        "Lista TiposArquivo": ", ".join(set(info["TiposArquivo"]))
    })

df = pd.DataFrame(relatorio)
df.to_excel("relatorio_docs.xlsx", index=False)

print("Relatório gerado com sucesso!")
