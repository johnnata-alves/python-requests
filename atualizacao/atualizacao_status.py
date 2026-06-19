import os

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
db = client['SinistrosMicroService']
collection = db['ProdutoElegivelAutomacao']

df = pd.read_excel('atualizacao_status.xlsx')

for _, row in df.iterrows():
    nome_do_produto = row['Nome do produto']
    cobertura_nome_i4pro = row['CoberturaNomeI4pro']
    tipo_causa = row['TipoCausa']
    nome_da_regra = row['Nome da regra']

    documento = collection.find_one({'Nome': nome_do_produto})

    if documento:
        coberturas = documento['Coberturas']
        for cobertura in coberturas:
            if (cobertura['CoberturaNomeI4pro'] == cobertura_nome_i4pro and
                cobertura['TipoCausa'] == tipo_causa):

                for regra in cobertura['RegraAutomacaoList']:
                    if regra['Nome'] == nome_da_regra:
                        regra['Ativo'] = True

                        collection.update_one({'_id': documento['_id']}, {'$set': {'Coberturas': coberturas}})

                        break

print("Processo finalizado.")
