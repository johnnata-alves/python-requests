import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
db = client['OCR']
dbDocumentManagement = client['DocumentManagement']

AnexoDetalhes = dbDocumentManagement['AnexoDetalhes']

registros_a = db['AtomicLog_20241218'].find()

for registro in registros_a:
    registro_b = db['AtomicLog'].find_one({'_id': registro['_id']})

    if registro_b:
        tipificacao_id = registro_b.get('TipificacaoId')
        nome_arquivo = registro_b.get('NomeArquivo')

        resultado = dbDocumentManagement['AnexoDetalhes'].update_one(
            {'NomeArquivo': nome_arquivo},
            {'$set': {'TipificacaoId': int(tipificacao_id)}}
        )

        if resultado.modified_count > 0:
            print(f'TipificacaoId atualizado para NomeArquivo: {nome_arquivo}')
        else:
            print(f'Nenhuma atualização feita para NomeArquivo: {nome_arquivo}')
    else:
        print(f'Registro não encontrado na collection B para o _id: {registro["_id"]}')

client.close()
