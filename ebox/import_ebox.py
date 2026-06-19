import os
from datetime import datetime

import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import requests
import urllib3
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_KEY = os.getenv("EBOX_API_KEY")
BASE_URL = os.getenv("EBOX_BASE_URL")

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DB_NAME = "SinistrosMicroService"

S3_BUCKET = os.getenv("PRD_S3_BUCKET")
S3_REGION = os.getenv("PRD_AWS_REGION")
AWS_ACCESS_KEY_ID = os.getenv("PRD_AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("PRD_AWS_SECRET_ACCESS_KEY")

PROJECT_ID = 2564
PAGE_SIZE = 10000

SEARCH_TERM_RETRIES = 5
SEARCH_TERM_RETRY_INTERVAL = 30

MAX_WORKERS = 5

CUTOFF_DATE = datetime(2020, 1, 1)

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
col_import = db["ImportEbox"]
col_anexo = db["AvisoSinistroAnexo"]

s3 = boto3.client(
    "s3",
    region_name=S3_REGION,
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY
)

def s3_file_exists(key):
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except:
        return False

def download_to_s3(uri, key):
    try:
        response = requests.get(uri, timeout=30, verify=False)
        if response.status_code == 200:
            s3.put_object(Bucket=S3_BUCKET, Key=key, Body=response.content)
            return True, round(len(response.content) / 1024, 2)
    except Exception as e:
        print(f"Erro download S3: {e}")
    return False, None

def delete_ebox(registro_id, documento_id):
    try:
        url = f"{BASE_URL}/registros/{registro_id}/documentos/deleteattachment"
        params = {"documentId": documento_id}

        response = requests.delete(
            url,
            headers={"X-Api-Key": API_KEY},
            params=params,
            verify=False
        )
        return response.status_code in [200, 204]
    except:
        return False

def parse_doc_date(valor):
    """Converte a string de data do documento em datetime naive (sem timezone)."""
    if not valor:
        return None
    if isinstance(valor, datetime):
        return valor.replace(tzinfo=None) if valor.tzinfo else valor
    s = str(valor)
    if s.endswith("Z"):
        s = s[:-1]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s[:10])
        except ValueError:
            return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt

def buscar_registros():
    """Itera sobre a API search-term paginando via 'from' (take=100, from=0,100,200,...).
    Faz até SEARCH_TERM_RETRIES tentativas com SEARCH_TERM_RETRY_INTERVAL segundos entre elas."""
    url = f"{BASE_URL}/registros/search-term"
    headers = {
        "X-Api-Key": API_KEY,
        "Content-Type": "application/json"
    }
    from_idx = 0

    while True:
        payload = {
            "termsCombined": [],
            "criteriaArguments": None,
            "workflowEstadoIds": None,
            "workflowFormalizacaoEstadoIds": None,
            "take": PAGE_SIZE,
            "from": from_idx,
            "tipoDocumentoIds": None
        }

        response = None
        for tentativa in range(1, SEARCH_TERM_RETRIES + 1):
            try:
                response = requests.post(url, headers=headers, json=payload, verify=False, timeout=60)
                if response.status_code == 200:
                    break
                print(f"[search-term] from={from_idx} tentativa {tentativa}/{SEARCH_TERM_RETRIES} "
                      f"status={response.status_code}")
            except Exception as e:
                print(f"[search-term] from={from_idx} tentativa {tentativa}/{SEARCH_TERM_RETRIES} erro: {e}")
                response = None

            if tentativa < SEARCH_TERM_RETRIES:
                time.sleep(SEARCH_TERM_RETRY_INTERVAL)

        if response is None or response.status_code != 200:
            status = response.status_code if response is not None else "sem resposta"
            body = response.text if response is not None else ""
            print(f"Erro search-term from={from_idx} após {SEARCH_TERM_RETRIES} tentativas: {status} {body}")
            break

        data = response.json()

        if isinstance(data, dict):
            itens = data.get("items") or data.get("data") or data.get("registros") or []
        else:
            itens = data

        print(f"Página from={from_idx} -> {len(itens)} itens")

        if not itens:
            break

        for item in itens:
            yield item

        from_idx += PAGE_SIZE

def extrair_chave_ebox(item):
    """Extrai o valor de camposChave[nomeInterno == 'chaveebox'].valor"""
    campos = item.get("camposChave") or item.get("CamposChave") or []
    for campo in campos:
        nome = (campo.get("nomeInterno") or campo.get("NomeInterno") or "").lower()
        if nome == "chaveebox":
            return campo.get("valor") or campo.get("Valor")
    return None

def normalizar_nome_arquivo(nome_arquivo, uri, documento_id):
    """Se o nome não tiver extensão e nem '_', prefixa com documentoId e
    adiciona a extensão extraída da URI. Caso contrário, mantém o nome original."""
    if not nome_arquivo:
        return nome_arquivo

    tem_underscore = "_" in nome_arquivo
    tem_extensao = "." in nome_arquivo.rsplit("/", 1)[-1]

    if tem_underscore or tem_extensao:
        return nome_arquivo

    ext = ""
    if uri:
        caminho = uri.split("?", 1)[0]
        base = caminho.rsplit("/", 1)[-1]
        if "." in base:
            ext = "." + base.rsplit(".", 1)[-1]

    return f"{documento_id}_{nome_arquivo}{ext}"

def processar_registro(registro_id, descricao=None, chave_ebox=None):
    url = f"{BASE_URL}/registros/{registro_id}/documentos"

    try:
        response = None
        for tentativa in range(1, SEARCH_TERM_RETRIES + 1):
            try:
                response = requests.get(
                    url,
                    headers={"X-Api-Key": API_KEY},
                    verify=False,
                    timeout=60
                )
                if response.status_code == 200:
                    break
                print(f"[documentos] registro={registro_id} tentativa {tentativa}/{SEARCH_TERM_RETRIES} "
                      f"status={response.status_code}")
            except Exception as e:
                print(f"[documentos] registro={registro_id} tentativa {tentativa}/{SEARCH_TERM_RETRIES} erro: {e}")
                response = None

            if tentativa < SEARCH_TERM_RETRIES:
                time.sleep(SEARCH_TERM_RETRY_INTERVAL)

        if response is None or response.status_code != 200:
            col_import.insert_one({
                "registroId": registro_id,
                "descricao": descricao,
                "chaveEbox": chave_ebox,
                "statusSincronismo": "Registro Id não encontrado",
                "dataProcessamento": datetime.now()
            })
            return

        documentos = response.json()

        if not documentos:
            col_import.insert_one({
                "registroId": registro_id,
                "descricao": descricao,
                "chaveEbox": chave_ebox,
                "statusSincronismo": "Sem documentos",
                "dataProcessamento": datetime.now()
            })
            print(f"Registro {registro_id} sem documentos")
            return

        datas = [parse_doc_date(d.get("data")) for d in documentos]
        if any(dt is not None and dt >= CUTOFF_DATE for dt in datas):
            col_import.insert_one({
                "registroId": registro_id,
                "descricao": descricao,
                "chaveEbox": chave_ebox,
                "statusSincronismo": "Ignorado - possui documento a partir de 2020",
                "dataProcessamento": datetime.now(),
                "totalDocumentos": len(documentos)
            })
            return

        for doc in documentos:
            if col_import.find_one({"documentoId": doc["documentoId"]}):
                continue

            nome_arquivo_original = doc.get("nomeArquivo")
            nome_arquivo = normalizar_nome_arquivo(
                nome_arquivo_original,
                doc.get("uri"),
                doc.get("documentoId")
            )
            key = f"TemporaryFiles/{nome_arquivo}"

            existe_s3 = False
            baixado_s3 = False
            removido = False
            anexo_id = None
            tamanho_kb = None

            existe_s3 = s3_file_exists(key)

            if not existe_s3:
                baixado_s3, tamanho_kb = download_to_s3(doc["uri"], key)
            else:
                baixado_s3 = True
                obj = s3.head_object(Bucket=S3_BUCKET, Key=key)
                tamanho_kb = round(obj["ContentLength"] / 1024, 2)

            protocolo = None
            if nome_arquivo_original and "_" in nome_arquivo_original:
                protocolo = nome_arquivo_original.split("_")[0].strip() or None

            if protocolo:
                anexo = col_anexo.find_one({"Key": key})

                if not anexo:
                    novo_anexo = {
                        "Protocolo": protocolo,
                        "AnexoId": "0",
                        "Region": S3_REGION,
                        "BucketName": S3_BUCKET,
                        "Hash": None,
                        "Key": key,
                        "DataInclusaoAnexo": datetime.now(),
                        "DataAlteracaoAnexo": datetime.now(),
                        "NotificadoEmail": None
                    }

                    result = col_anexo.insert_one(novo_anexo)
                    anexo_id = result.inserted_id
                else:
                    anexo_id = anexo["_id"]

            if baixado_s3:
                status = "Download realizado, remoção pendente"
            else:
                status = "Erro no download"

            registro = {
                "registroId": registro_id,
                "descricao": descricao,
                "chaveEbox": chave_ebox,
                "statusSincronismo": status,
                "dataProcessamento": datetime.now(),
                "existeS3": existe_s3,
                "baixadoS3": baixado_s3,
                "removido": removido,
                "registradoMongo": True,
                "AnexoId": anexo_id,
                "tamanhoKB": tamanho_kb,
                **doc,
                "nomeArquivoOriginal": nome_arquivo_original,
                "nomeArquivo": nome_arquivo,
                "s3Key": key
            }

            col_import.insert_one(registro)

    except Exception as e:
        print(f"Erro geral registro {registro_id}: {e}")

def main():
    ids_processados = set()
    tarefas = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for item in buscar_registros():
            registro_id = item.get("registroId") or item.get("RegistroId")
            if not registro_id or registro_id in ids_processados:
                continue
            ids_processados.add(registro_id)

            data_criacao = parse_doc_date(item.get("dataCriacao") or item.get("DataCriacao"))
            if data_criacao is None:
                print(f"RegistroId={registro_id} sem dataCriacao, pulando")
                continue
            if data_criacao >= CUTOFF_DATE:
                print(f"RegistroId={registro_id} dataCriacao={data_criacao.date()} >= {CUTOFF_DATE.date()}, pulando")
                continue

            if col_import.find_one({"registroId": registro_id}):
                print(f"RegistroId={registro_id} já existe em ImportEbox, pulando")
                continue

            descricao = item.get("descricao") or item.get("Descricao")
            chave_ebox = extrair_chave_ebox(item)

            print(f"Agendando registroId={registro_id} dataCriacao={data_criacao.date()} chaveEbox={chave_ebox}")
            tarefas.append(executor.submit(
                processar_registro,
                registro_id,
                descricao,
                chave_ebox
            ))

        for future in as_completed(tarefas):
            try:
                future.result()
            except Exception as e:
                print(f"Erro em tarefa paralela: {e}")

if __name__ == "__main__":
    main()
