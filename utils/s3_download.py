import os
import sys

import boto3
from dotenv import load_dotenv

load_dotenv()

S3_URL  = "s3://s3-virginia-prd-auditlogprd/TemporaryFiles/IMG_20200520_101806318_671826d35d9e43f48fb591c6769a4255.jpg"
DEST_DIR = r"C:\Downloads"

s3 = boto3.client(
    "s3",
    region_name=os.getenv("PRD_AWS_REGION"),
    aws_access_key_id=os.getenv("PRD_AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("PRD_AWS_SECRET_ACCESS_KEY"),
)

def parse_s3_url(url: str):
    if not url.startswith("s3://"):
        raise ValueError(f"URL inválida: '{url}'. Deve começar com s3://")
    partes = url[5:].split("/", 1)
    if len(partes) < 2 or not partes[1]:
        raise ValueError(f"URL inválida: '{url}'. Formato esperado: s3://bucket/caminho/arquivo")
    return partes[0], partes[1]

def download(s3_url: str, dest_dir: str):
    bucket, key = parse_s3_url(s3_url)
    nome_arquivo = os.path.basename(key)
    destino = os.path.join(dest_dir, nome_arquivo)

    os.makedirs(dest_dir, exist_ok=True)

    print(f"Bucket : {bucket}")
    print(f"Key    : {key}")
    print(f"Destino: {destino}")
    print("Baixando...", end=" ", flush=True)

    s3.download_file(bucket, key, destino)

    tamanho_kb = os.path.getsize(destino) / 1024
    print(f"OK ({tamanho_kb:.1f} KB)")

if __name__ == "__main__":
    try:
        download(S3_URL, DEST_DIR)
    except Exception as e:
        print(f"Erro: {e}", file=sys.stderr)
        sys.exit(1)
