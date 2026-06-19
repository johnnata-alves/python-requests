import os

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
dbOCR = client['DocumentManagement']

def encontrar_registros_com_objectid():
    documentos = dbOCR['AnexoDetalhes'].find({"_id": {"$type": 7}})

    for documento in documentos:
        if isinstance(documento['_id'], ObjectId):
            novo_documento = documento.copy()
            novo_documento['_id'] = str(novo_documento['_id'])

            dbOCR['AnexoDetalhes'].insert_one(novo_documento)

            dbOCR['AnexoDetalhes'].delete_one({'_id': documento['_id']})

            print(f"Substituído _id de {documento['_id']} por {novo_documento['_id']}")

encontrar_registros_com_objectid()
