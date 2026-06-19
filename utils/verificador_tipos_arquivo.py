import os
from dotenv import load_dotenv
from pymongo import MongoClient
import csv

load_dotenv()

client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
db = client['OCR']
dbDM = client['DocumentManagement']

pipeline = [
    {"$unwind": "$Resposta.Arquivos"},
    {"$unwind": "$Resposta.Arquivos.TipoArquivo"},
    {
        "$group": {
            "_id": None,
            "tipos": {
                "$addToSet": {
                    "TipoArquivo": "$Resposta.Arquivos.TipoArquivo.TipoArquivo",
                    "NomeTipoArquivo": "$Resposta.Arquivos.TipoArquivo.NomeTipoArquivo"
                }
            }
        }
    }
]

resultados = db['AtomicLog'].aggregate(pipeline)

tipos_lista = []
adicionados = set()

for resultado in resultados:
    for tipo in resultado['tipos']:
        if ' - ' in tipo['NomeTipoArquivo']:
            tipoo = tipo['NomeTipoArquivo'].split(" - ")[0] if len(tipo['NomeTipoArquivo'].split(" - ")) > 1 else tipo['NomeTipoArquivo']
            descricao = tipo['NomeTipoArquivo'].split(" - ")[1] if len(tipo['NomeTipoArquivo'].split(" - ")) > 1 else tipo['NomeTipoArquivo']
        else:
            tipoo = "9999"
            descricao = tipo['NomeTipoArquivo']

        tipo_id = tipoo.lstrip('0') or '0'

        if (tipo_id, descricao) not in adicionados:
            tipos_lista.append({
                "Id": tipo_id,
                "Tipo": descricao
            })
            adicionados.add((tipo_id, descricao))

not_found = tipos_lista.copy()
found = []

for tipo_id in tipos_lista:
    resultado = dbDM['TipoDocumento'].find_one({"_id": tipo_id['Id']})
    if resultado:
        found.append(tipo_id)
        not_found.remove(tipo_id)

with open('relatorio_tipos_arquivo.csv', 'w', newline='') as csvfile:
    fieldnames = ['ID', 'Tipo', 'Status']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    for tipo_id in found:
        writer.writerow({'ID': tipo_id['Id'], 'Tipo': tipo_id['Tipo'], 'Status': 'Encontrado'})

    for tipo_id in not_found:
        writer.writerow({'ID': tipo_id['Id'], 'Tipo': tipo_id['Tipo'], 'Status': 'Não Encontrado'})

print("Relatório gerado com sucesso: relatorio_tipos_arquivo.csv")
