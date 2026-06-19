import os
from dotenv import load_dotenv
from pymongo import MongoClient
from bson import ObjectId
import requests
import boto3
from datetime import datetime
from bson.int64 import Int64

load_dotenv()

client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
db = client['OCR']
collection = db['AtomicLog']

s3 = boto3.client('s3', aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID_AUDITLOG"),
                  aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY_AUDITLOG"))

query = {
    "DataCriacao": {"$gt": datetime(2024, 12, 13, 0, 26, 33, 173000)},
    "Resposta.Arquivos.0.TipoArquivo.0.NomeTipoArquivo": {"$exists": False}
}
resultados = collection.find(query)

for doc in resultados:
    arquivo_nome = doc['NomeArquivo']

    caminho_local = f'/arquivos/{arquivo_nome}'
    bucket_name = 'auditlogprd'
    caminho_s3 = f'TemporaryFiles/{arquivo_nome}'

    caminho_atual = os.getcwd()
    local_file_path = f"{caminho_atual}/arquivos/{arquivo_nome}"
    s3.download_file(bucket_name, caminho_s3, local_file_path)

    with open(local_file_path, 'rb') as arquivo:
        files = {'arquivo': arquivo}
        response = requests.post(
            f"{os.getenv('ATOMICS_API_URL')}/api/v1/tipificacao",
            headers={
                'Authorization': f"Bearer {os.getenv('ATOMICS_API_TOKEN')}"
            },
            files=files,
            data={
                'CodigoLegado': doc['Resposta']['CodigoLegado'],
                'ExtrairDados': "true",
                'PerfilTipificacao': "Nova Arquitetura"
            }
        )

    if response.status_code == 200:
        TipificacaoId = Int64(response.text)

        update_fields = {
            "Resposta.CodigoSolicitacao": TipificacaoId,
            "TipificacaoId": TipificacaoId,
            "Resposta.Status": 0,
            "Status": 0
        }

        collection.update_one({"_id": doc['_id']}, {"$set": update_fields})

        print(f"Documento {doc['_id']} atualizado com o TipificacaoId {TipificacaoId}.")
    else:
        print(f"Erro ao processar o documento {doc['_id']}: {response.content}")
