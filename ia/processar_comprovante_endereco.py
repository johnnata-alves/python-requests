import boto3
import json
import os
import time
from dotenv import load_dotenv

load_dotenv()

AWS_ACCESS_KEY = os.getenv("PRD_AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.getenv("PRD_AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("PRD_AWS_REGION", "us-east-1")

S3_BUCKET = os.getenv("PRD_S3_BUCKET", "s3-virginia-prd-auditlogprd")
S3_FILE = "TemporaryFiles/11202651904551990_download_2_ba2fa983907333f85ac6d8190dcf29bf.pdf"

print(f"Bucket: {S3_BUCKET}")
print(f"Key: {S3_FILE}")
print(f"Region: {AWS_REGION}")

textract = boto3.client(
    "textract",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)

s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)

print("Verificando se o arquivo existe no S3...")
try:
    head = s3.head_object(Bucket=S3_BUCKET, Key=S3_FILE)
    print(f"Arquivo encontrado: {head['ContentLength']} bytes, ContentType: {head['ContentType']}")
except Exception as e:
    print(f"ERRO: Arquivo não encontrado no S3 - {e}")
    exit(1)

QUERIES = [
    {"Text": "Qual o CPF do titular? Retorne completo ou parcial exatamente como aparece.", "Alias": "CPF"},
    {"Text": "Qual o nome do titular?", "Alias": "NOME"},
    {"Text": "Qual o endereço completo?", "Alias": "ENDERECO"},
    {"Text": "Qual a data de vencimento?", "Alias": "VENCIMENTO"},
]

def processar_sincrono():
    print("\nProcessando com analyze_document (síncrono)...")
    response = textract.analyze_document(
        Document={"S3Object": {"Bucket": S3_BUCKET, "Name": S3_FILE}},
        FeatureTypes=["FORMS", "QUERIES"],
        QueriesConfig={"Queries": QUERIES}
    )
    return response["Blocks"]

def processar_assincrono():
    print("\nUsando start_document_analysis (assíncrono)...")
    start_response = textract.start_document_analysis(
        DocumentLocation={"S3Object": {"Bucket": S3_BUCKET, "Name": S3_FILE}},
        FeatureTypes=["FORMS"]
    )
    job_id = start_response["JobId"]
    print(f"Job iniciado: {job_id}")

    while True:
        result = textract.get_document_analysis(JobId=job_id)
        status = result["JobStatus"]
        print(f"  Status: {status}")
        if status == "SUCCEEDED":
            break
        elif status == "FAILED":
            print(f"  ERRO: {result.get('StatusMessage', 'Falha desconhecida')}")
            exit(1)
        time.sleep(3)

    blocks = result["Blocks"]
    next_token = result.get("NextToken")
    while next_token:
        result = textract.get_document_analysis(JobId=job_id, NextToken=next_token)
        blocks.extend(result["Blocks"])
        next_token = result.get("NextToken")

    return blocks

try:
    blocks = processar_assincrono()
except Exception as e:
    print(f"Erro inesperado: {type(e).__name__}: {e}")
    exit(1)

queries_result = []
forms_result = []

for block in blocks:
    if block["BlockType"] == "KEY_VALUE_SET" and "KEY" in block.get("EntityTypes", []):
        key_text = ""
        value_text = ""
        for rel in block.get("Relationships", []):
            if rel["Type"] == "CHILD":
                for child_id in rel["Ids"]:
                    child = next((b for b in blocks if b["Id"] == child_id), None)
                    if child and child["BlockType"] == "WORD":
                        key_text += child.get("Text", "") + " "
            if rel["Type"] == "VALUE":
                for val_id in rel["Ids"]:
                    val_block = next((b for b in blocks if b["Id"] == val_id), None)
                    if val_block:
                        for vrel in val_block.get("Relationships", []):
                            if vrel["Type"] == "CHILD":
                                for vc_id in vrel["Ids"]:
                                    vc = next((b for b in blocks if b["Id"] == vc_id), None)
                                    if vc and vc["BlockType"] == "WORD":
                                        value_text += vc.get("Text", "") + " "
        if key_text.strip():
            forms_result.append({"chave": key_text.strip(), "valor": value_text.strip()})

print("\n================ FORMULÁRIOS (KEY-VALUE) ================\n")
print(json.dumps(forms_result, indent=4, ensure_ascii=False))

texto = []
for block in blocks:
    if block["BlockType"] == "LINE":
        texto.append(block["Text"])

print("\n================ OCR COMPLETO ================\n")
print("\n".join(texto))
