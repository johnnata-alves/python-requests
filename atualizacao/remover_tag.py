import os
import boto3
from dotenv import load_dotenv

load_dotenv()

s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID_AUDITLOG"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY_AUDITLOG"),
)
bucket_name = os.getenv("S3_BUCKET_AUDITLOG")
object_key = 'FiancaLocaticia/dynulnfuf3t_METRAGEM_f03a43887d0d45d67927b766b70c7cb073a924960840361c93cec72ec2127b6cb8e6f4611644a88049018259ad46fbf0807a02ff21a21262e84d310342262ec9.pdf'

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

remove_delete_marker(bucket_name, object_key)
