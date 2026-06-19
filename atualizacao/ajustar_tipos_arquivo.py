import os

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

def connect_to_mongo():
    client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
    db = client['DocumentManagement']
    return db['AnexoDetalhes']

def atualizar_tipo_arquivo():
    collection = connect_to_mongo()

    for doc in collection.find({'TiposArquivo': {'$exists': False}}):
        tipos_arquivo = []

        if 'Resposta' in doc and 'Arquivos' in doc['Resposta']:
            for arquivo in doc['Resposta']['Arquivos']:
                if 'TipoArquivo' in arquivo:
                    for tipo in arquivo['TipoArquivo']:
                        if 'NomeTipoArquivo' in tipo:
                            tipos_arquivo.append(tipo['NomeTipoArquivo'])

        elif 'TipoArquivo' in doc:
            tipos_arquivo.append(doc['TipoArquivo'])

        collection.update_one(
            {'_id': doc['_id']},
            {
                '$set': {'TiposArquivo': tipos_arquivo},
                '$unset': {
                    'Resposta': "",
                    'TipoArquivo': ""
                }
            }
        )
    print("Atualização concluída.")

atualizar_tipo_arquivo()
