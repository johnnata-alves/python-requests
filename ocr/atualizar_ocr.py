import os

from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

def connect_to_mongo():
    client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
    db = client['DocumentManagement']
    return db['AnexoDetalhes']

def atualizar_tipo_arquivo(doc):
    tipos_arquivo = []

    if 'Resposta' in doc and 'Arquivos' in doc['Resposta']:
        for arquivo in doc['Resposta']['Arquivos']:
            if 'TipoArquivo' in arquivo:
                for tipo in arquivo['TipoArquivo']:
                    if 'NomeTipoArquivo' in tipo:
                        tipos_arquivo.append(tipo['NomeTipoArquivo'])

    elif 'TipoArquivo' in doc:
        tipos_arquivo.append(doc['TipoArquivo'])

    collection = connect_to_mongo()
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

def atualizar_todos_os_documentos():
    collection = connect_to_mongo()
    documentos = list(collection.find({'TiposArquivo': {'$exists': False}}))

    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(atualizar_tipo_arquivo, documentos)

    print("Atualização concluída.")

atualizar_todos_os_documentos()
