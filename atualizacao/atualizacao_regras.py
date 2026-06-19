import os

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client  = MongoClient(os.getenv("HML_MONGO_URI"))
db = client["SinistrosMicroService"]
collection = db["ProdutoElegivelAutomacao"]
df = pd.read_csv("regras.csv", sep=';')

for documento in collection.find():
    codigo = documento['Codigo']
    coberturas = documento['Coberturas']

    for cobertura in coberturas:
        grupo_cobertura_id = cobertura['GrupoCoberturaId']
        tipo_causa_id = cobertura['TipoCausaId']
        regras_automacao = cobertura['RegraAutomacaoList']

        correspondencias = df[(df['Codigo'] == codigo) &
                              (df['GrupoCoberturaId'] == grupo_cobertura_id) &
                              (df['TipoCausaId'] == tipo_causa_id)]

        for regra in regras_automacao:
            nome_regra = regra['Nome']
            if not correspondencias[correspondencias['Nome da regra'] == nome_regra].empty:
                ativo_csv = correspondencias.loc[correspondencias['Nome da regra'] == nome_regra, 'Ativo'].values[0]
                regra['Ativo'] = True if ativo_csv == 'TRUE' else False

    collection.update_one({'_id': documento['_id']}, {'$set': {'Coberturas': coberturas}})

print("Atualizações concluídas.")
