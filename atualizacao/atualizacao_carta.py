import os

import pandas as pd
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
clientHML = MongoClient(os.getenv("HML_MONGO_URI"))
db = client['SinistrosMicroService']
dbHML = clientHML['SinistrosMicroService']
collection = db['ProdutoElegivelAutomacao_nova']
ProdutoElegivelAutomacao = db['ProdutoElegivelAutomacao_new']

excel_file_path = 'parametros_motor.xlsx'
vigencia_df = pd.read_excel(excel_file_path)

for document in collection.find():
    new_document = {
        "_id": document["_id"],
        'Codigo': document['Codigo'],
        'Nome': document['Nome'],
        'Ativo': document['Ativo'],
        'IdAtendimentoPadrao': document['IdAtendimentoPadrao'],
        'Coberturas': []
    }

    for cobertura in document.get('Coberturas', []):
        nova_cobertura = {
            'CoberturaI4proId': cobertura['CoberturaI4proId'],
            'CoberturaNomeI4pro': cobertura['CoberturaNomeI4pro'],
            'RamoId': cobertura['RamoId'],
            'GrupoCoberturaId': cobertura['GrupoCoberturaId'],
            'Ramo': cobertura['Ramo'],
            'TipoCausaId': cobertura['TipoCausaId'],
            'TipoCausa': cobertura['TipoCausa'],
            'ElegivelAutomacao': cobertura['ElegivelAutomacao'],
            'Documentacao': cobertura['Documentacao'],
            'RegraAutomacaoList': []
        }

        for regra in cobertura.get('RegraAutomacaoList', []):
            filtered_row = vigencia_df[
                (vigencia_df['Codigo'] == document['Codigo']) &
                (vigencia_df['TipoCausaId'] == cobertura['TipoCausaId']) &
                (vigencia_df['Nome_regra'] == regra['Nome']) &
                (vigencia_df['GrupoCoberturaId'] == cobertura['GrupoCoberturaId'])
            ]

            if not filtered_row.empty:
                updated_condicoes = filtered_row.iloc[0]['CondicoesGerais']
                updated_condicoes = updated_condicoes.replace('Whatsapp',
                    '<a href="https://api.whatsapp.com/send?1=pt_BR&phone=5511994003326" target="_blank">Whatsapp</a>')
                updated_condicoes = updated_condicoes.replace('site',
                    '<a href="https://tooseguros.com.br/" target="_blank">Too Seguros</a>')
                updated_condicoes = updated_condicoes.replace('www.tooseguros.com.br',
                    '<a href="https://tooseguros.com.br/" target="_blank">Too Seguros</a>')

                updated_texto = filtered_row.iloc[0]['TextoRecusa']
                updated_texto = updated_texto.replace('dataEvento', 'dataOcorrencia')

                nova_cobertura['RegraAutomacaoList'].append({
                    'Nome': regra['Nome'],
                    'CodMotivo': regra.get('CodMotivo', None),
                    'Valor': regra['Valor'],
                    'Tipo': regra.get('Tipo', 'int'),
                    'Periodicidade': regra.get('Periodicidade', 'Years'),
                    'CartaRecusa': regra.get('CartaRecusa', ''),
                    'Ativo': regra['Ativo'],
                    'CondicoesGerais': updated_condicoes,
                    'TextoRecusa': updated_texto
                })
            else:
                nova_cobertura['RegraAutomacaoList'].append({
                    'Nome': regra['Nome'],
                    'CodMotivo': regra.get('CodMotivo', None),
                    'Valor': regra['Valor'],
                    'Tipo': regra.get('Tipo', 'int'),
                    'Periodicidade': regra.get('Periodicidade', 'Years'),
                    'CartaRecusa': regra.get('CartaRecusa', ''),
                    'Ativo': regra['Ativo'],
                    'CondicoesGerais': regra.get('CondicoesGerais', None),
                    'TextoRecusa': regra.get('TextoRecusa', None)
                })

        if nova_cobertura['RegraAutomacaoList']:
            new_document['Coberturas'].append(nova_cobertura)

    if new_document['Coberturas']:
        ProdutoElegivelAutomacao.insert_one(new_document)

print("Inserções concluídas.")
