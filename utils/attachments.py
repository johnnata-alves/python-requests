import os
from dotenv import load_dotenv
import pymongo
import boto3
import csv
from bson.objectid import ObjectId
from datetime import datetime

load_dotenv()

mongo_client = pymongo.MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
db = mongo_client['SinistrosMicroService']
collection = db['Attachment']

s3_client = boto3.client('s3', aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID_AUDITLOG"), aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY_AUDITLOG"))
bucket_name = "auditlogprd"

def file_exists_in_s3(bucket, key):
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except Exception as e:
        return False

def remove_delete_marker(bucket, key):
    versions = s3_client.list_object_versions(Bucket=bucket, Prefix=key)
    delete_marker_id = None

    for version in versions.get('DeleteMarkers', []):
        if version['Key'] == key and version['IsLatest']:
            delete_marker_id = version['VersionId']
            break

    if delete_marker_id:
        print(f"Removendo delete marker para: {key}")
        s3_client.delete_object(Bucket=bucket, Key=key, VersionId=delete_marker_id)
        print("Delete marker removido com sucesso.")
    else:
        print("Nenhum delete marker encontrado.")

results = []
start_date = datetime(2024, 1, 1)
end_date = datetime(2024, 8, 31, 23, 59, 59)
for document in collection.find({"InsertDate": {"$gte": start_date, "$lte": end_date}}):
    key = document.get("Key")
    insert_date = document.get("InsertDate", {})
    doc_id = document.get("_id")

    exists = file_exists_in_s3(bucket_name, key)

    if not exists:
        remove_delete_marker(bucket_name, key)
        results.append({
            "_Id": str(doc_id),
            "Key": key,
            "InsertDate": insert_date,
            "Existe": "Sim" if exists else "Nao"
        })

csv_file_path = 'resultados.csv'
with open(csv_file_path, mode='w', newline='', encoding='utf-8') as csvfile:
    fieldnames = ["_Id", "Key", "InsertDate", "Existe"]
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames, delimiter=';')

    writer.writeheader()
    for result in results:
        writer.writerow(result)

print(f"Resultados salvos em {csv_file_path}")
