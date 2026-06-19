import os

from bson.objectid import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

client = MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
db = client['OCR']

obito_collection = db['AtomicLog_Obito']
log_collection = db['AtomicLog']

for obito in obito_collection.find({'DataCriacao': {'$exists': False}}):
    obito_id = obito['_id']

    log_record = log_collection.find_one({'_id': obito_id})

    if log_record:
        data_criacao = log_record.get('DataCriacao')

        obito_collection.update_one(
            {'_id': obito_id},
            {'$set': {'DataCriacao': data_criacao}}
        )

print("Atualização concluída.")
