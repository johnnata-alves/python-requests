import os

import pymongo
import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient
import boto3
import datetime

load_dotenv()

mongo_client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
db = mongo_client['OCR']
db2 = mongo_client['SinistrosMicroService']
colecao1 = db['AtomicLog_Obito']
colecao2 = db2['AvisoSinistro']

query1 = {
    "Arquivo": {"$regex": "CO", "$options": "i"}
}
resultados1 = list(colecao1.find(query1))

dados = []

for item in resultados1:
    protocolo = item.get('Protocolo')
    resultado2 = colecao2.find_one({"Protocolo": protocolo})

    if resultado2:
        metadados = item.get('Metadados')
        data_falecimento = metadados['DataFalecimento'].strftime('%Y-%m-%d') if metadados and metadados.get('DataFalecimento') else None
        data_atualizacao = item.get('DataAtualizacao')
        tipos_arquivo = item.get('TiposArquivo', [])

        dados.append({
            "IdRetornado": item.get('IdRetornado'),
            "Protocolo": protocolo,
            "Arquivo": item.get('Arquivo'),
            "Status": item.get('Status'),
            "DataCriacao": item.get('DataCriacao'),
            "DataAtualizacao": data_atualizacao,
            "DocumentoIdentificacao": item.get('DocumentoIdentificacao'),
            "CPF": metadados['CPF'] if metadados else None,
            "Nome": metadados['Nome'] if metadados else None,
            "DataFalecimento": data_falecimento,
            "CausaMorte": metadados['CausaMorte'] if metadados else None,
            "MetadadosCompleto": item.get('MetadadosCompleto'),
            "TiposArquivo": tipos_arquivo[0] if tipos_arquivo else None,
            "Ocorrencia": resultado2.get('Ocorrencia'),
            "CpfCnpjSegurado": resultado2['Segurado']['CpfCnpj'],
            "Comparacao_CPF": metadados['CPF'] == resultado2['Segurado']['CpfCnpj'] if metadados else False,
            "Comparacao_DataFalecimento": data_falecimento == resultado2['Ocorrencia'].strftime('%Y-%m-%d') if resultado2.get('Ocorrencia') else False
        })

df = pd.DataFrame(dados)

if 'TiposArquivo' not in df.columns:
    df['TiposArquivo'] = None

df['DataCriacao'] = pd.to_datetime(df['DataCriacao'])
df['DataCriacao'] = df['DataCriacao'].dt.date

excel_file = 'resultado_consultas.xlsx'
with pd.ExcelWriter(excel_file, engine='openpyxl') as writer:
    df.to_excel(writer, sheet_name='Resultados', index=False)

    grouped_report = df.groupby('DataCriacao').agg(
        Total_Registros=('IdRetornado', 'count'),
        Registros_Completos=('MetadadosCompleto', lambda x: (x == True).sum()),
        Registros_Certidao_Obito=('TiposArquivo', lambda x: x.str.contains("Certidão de Óbito", na=False).sum() if x is not None else 0),
        Registros_OK=('IdRetornado', lambda x: ((df.loc[x.index, 'MetadadosCompleto'] == True) &
                                                 (df.loc[x.index, 'Comparacao_CPF'] == True) &
                                                 (df.loc[x.index, 'Comparacao_DataFalecimento'] == True)).sum())
    )

    grouped_report['Percentual_Completos'] = (grouped_report['Registros_Completos'] / grouped_report['Total_Registros'] * 100).fillna(0)
    grouped_report['Percentual_Certidao_Obito'] = (grouped_report['Registros_Certidao_Obito'] / grouped_report['Total_Registros'] * 100).fillna(0)
    grouped_report['Percentual_OK'] = (grouped_report['Registros_OK'] / grouped_report['Total_Registros'] * 100).fillna(0)

    grouped_report.reset_index(inplace=True)
    grouped_report.to_excel(writer, sheet_name='Relatório Agrupado', index=False)

print("Processo concluído com sucesso!")
