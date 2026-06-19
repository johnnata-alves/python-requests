import os
from datetime import datetime
import uuid
import threading

import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3
import pandas as pd
import requests
import urllib3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config as BotoConfig
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

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

file_ = "eBox_registros_Sinistros_Cobertura_Desemprego_134206644203881640.csv"
EXCEL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_)

RATE_LIMIT_MIN = 0.05
RATE_LIMIT_MAX = 2.0
RATE_LIMIT_INCREASE = 1.5
RATE_LIMIT_DECREASE = 0.9
RATE_LIMIT_SUCCESS_STREAK = 10

SEARCH_TERM_RETRIES = 5
SEARCH_TERM_RETRY_INITIAL_WAIT = 5

MAX_WORKERS = 30

DOC_WORKERS = 8

CUTOFF_DATE = datetime(2020, 1, 1)

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
col_import = db["ImportEbox"]
col_anexo = db["AvisoSinistroAnexo"]

boto_config = BotoConfig(
    region_name=S3_REGION,
    max_pool_connections=100,
    retries={"max_attempts": 3, "mode": "adaptive"},
    tcp_keepalive=True,
)
s3 = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY_ID,
    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    config=boto_config,
)

S3_TRANSFER_CONFIG = TransferConfig(
    multipart_threshold=8 * 1024 * 1024,
    multipart_chunksize=16 * 1024 * 1024,
    max_concurrency=15,
    use_threads=True,
    io_chunksize=4 * 1024 * 1024,
)

if os.getenv("S3_USE_ACCELERATION", "").lower() == "true":
    boto_config_accel = BotoConfig(
        region_name=S3_REGION,
        max_pool_connections=100,
        retries={"max_attempts": 3, "mode": "adaptive"},
        tcp_keepalive=True,
        s3={"use_accelerate_endpoint": True},
    )
    s3 = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        config=boto_config_accel,
    )
    print("[S3] Transfer Acceleration habilitado")

http_session = requests.Session()
http_adapter = requests.adapters.HTTPAdapter(
    pool_connections=50,
    pool_maxsize=100,
    max_retries=0
)
http_session.mount("http://", http_adapter)
http_session.mount("https://", http_adapter)
http_session.verify = False

class AdaptiveRateLimiter:
    """Rate limiter dinâmico e thread-safe. Começa rápido e desacelera ao detectar erros."""

    def __init__(self):
        self._lock = threading.Lock()
        self._interval = RATE_LIMIT_MIN
        self._last_request = 0.0
        self._success_count = 0

    @property
    def interval(self):
        with self._lock:
            return self._interval

    def wait(self):
        """Aguarda o intervalo necessário antes da próxima request."""
        with self._lock:
            elapsed = time.time() - self._last_request
            wait_time = self._interval - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_request = time.time()

    def report_success(self):
        """Registra sucesso. Após N sucessos seguidos, reduz o intervalo."""
        with self._lock:
            self._success_count += 1
            if self._success_count >= RATE_LIMIT_SUCCESS_STREAK:
                self._success_count = 0
                novo = self._interval * RATE_LIMIT_DECREASE
                self._interval = max(novo, RATE_LIMIT_MIN)

    def report_error(self):
        """Registra erro. Aumenta o intervalo imediatamente."""
        with self._lock:
            self._success_count = 0
            novo = self._interval * RATE_LIMIT_INCREASE
            self._interval = min(novo, RATE_LIMIT_MAX)
            print(f"[rate-limit] Erro detectado, intervalo ajustado para {self._interval:.3f}s")

rate_limiter = AdaptiveRateLimiter()

class StepMetrics:
    """Coletor thread-safe de tempos por etapa com display em tempo real."""

    STEP_LABELS = {
        "1_api_ebox_documentos": "API eBox (documentos)",
        "2_check_duplicado_mongo": "Check duplicado Mongo",
        "3_check_s3_exists": "Check S3 exists",
        "4_download_upload_s3": "Download/Upload S3",
        "4a_download_ebox": "  └ Download eBox",
        "4b_upload_s3": "  └ Upload S3",
        "5_mongo_anexo": "Mongo Anexo",
        "6_save_import_mongo": "Save Import Mongo",
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._counts = {}
        self._totals = {}
        self._mins = {}
        self._maxs = {}

    def record(self, step_name, duration):
        with self._lock:
            if step_name not in self._counts:
                self._counts[step_name] = 0
                self._totals[step_name] = 0.0
                self._mins[step_name] = float("inf")
                self._maxs[step_name] = 0.0
            self._counts[step_name] += 1
            self._totals[step_name] += duration
            if duration < self._mins[step_name]:
                self._mins[step_name] = duration
            if duration > self._maxs[step_name]:
                self._maxs[step_name] = duration

    def summary(self):
        with self._lock:
            result = {}
            for step in self._counts:
                count = self._counts[step]
                total = self._totals[step]
                result[step] = {
                    "count": count,
                    "total": total,
                    "avg": total / count if count else 0,
                    "min": self._mins[step] if self._mins[step] != float("inf") else 0,
                    "max": self._maxs[step],
                }
            return result

    def display_lines(self):
        """Retorna as linhas formatadas para exibição no terminal."""
        with self._lock:
            lines = []
            for step in sorted(self._counts.keys()):
                count = self._counts[step]
                total = self._totals[step]
                avg = total / count if count else 0
                mn = self._mins[step] if self._mins[step] != float("inf") else 0
                mx = self._maxs[step]
                label = self.STEP_LABELS.get(step, step)
                lines.append(
                    f"  {label:<25} | N={count:<5} | Avg={avg:.3f}s | "
                    f"Min={mn:.3f}s | Max={mx:.3f}s | Tot={total:.1f}s"
                )
            return lines

metrics = StepMetrics()

class ThroughputTracker:
    """Acompanha MB transferidos via wall-clock (throughput real agregado)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._dl_mb = 0.0
        self._up_mb = 0.0
        self._dl_first_ts = None
        self._dl_last_ts = None
        self._up_first_ts = None
        self._up_last_ts = None

    def record_download(self, mb, seconds):
        now = time.time()
        with self._lock:
            self._dl_mb += mb
            if self._dl_first_ts is None:
                self._dl_first_ts = now - seconds
            self._dl_last_ts = now

    def record_upload(self, mb, seconds):
        now = time.time()
        with self._lock:
            self._up_mb += mb
            if self._up_first_ts is None:
                self._up_first_ts = now - seconds
            self._up_last_ts = now

    def stats(self):
        with self._lock:
            dl_wall = (self._dl_last_ts - self._dl_first_ts) if self._dl_first_ts else 0
            up_wall = (self._up_last_ts - self._up_first_ts) if self._up_first_ts else 0
            dl_speed = self._dl_mb / dl_wall if dl_wall > 0 else 0
            up_speed = self._up_mb / up_wall if up_wall > 0 else 0
            return {
                "download_mb": self._dl_mb,
                "download_seconds": dl_wall,
                "download_mb_s": dl_speed,
                "upload_mb": self._up_mb,
                "upload_seconds": up_wall,
                "upload_mb_s": up_speed,
            }

throughput = ThroughputTracker()

def metrics_display_loop(stop_event, interval=10.0):
    """Thread que printa snapshots das métricas a cada N segundos usando tqdm.write
    (compatível com a barra de progresso do tqdm)."""
    while not stop_event.is_set():
        stop_event.wait(interval)
        if stop_event.is_set():
            break
        lines = metrics.display_lines()
        if not lines:
            continue
        tp = throughput.stats()
        block = []
        block.append("─" * 80)
        block.append(f"  {'ETAPA':<25} | {'':5} | {'Média':>9} | {'Min':>9} | {'Max':>9} | {'Total':>8}")
        block.append("─" * 80)
        block.extend(lines)
        block.append("─" * 80)
        block.append(
            f"  Rate limit: {rate_limiter.interval:.3f}s | "
            f"DL: {tp['download_mb_s']:.2f} MB/s ({tp['download_mb']:.0f} MB) | "
            f"UP: {tp['upload_mb_s']:.2f} MB/s ({tp['upload_mb']:.0f} MB)"
        )
        tqdm.write("\n".join(block))

def s3_file_info(key):
    """Retorna (existe, tamanho_kb) em uma única chamada head_object."""
    try:
        obj = s3.head_object(Bucket=S3_BUCKET, Key=key)
        return True, round(obj["ContentLength"] / 1024, 2)
    except Exception:
        return False, None

def s3_file_exists(key):
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except:
        return False

def download_to_s3(uri, key):
    """
    Baixa do eBox e sobe para o S3, separando os tempos de download e upload em
    métricas distintas para identificar gargalos.
    - Pequenos (< 8 MB): baixa para memória e faz put_object
    - Grandes (>= 8 MB): baixa para BytesIO e faz upload_fileobj com multipart paralelo
    """
    import io
    try:
        t_dl = time.time()
        with http_session.get(uri, timeout=120, stream=True) as response:
            if response.status_code != 200:
                metrics.record("4a_download_ebox", time.time() - t_dl)
                return False, None

            response.raw.decode_content = True
            buffer = io.BytesIO()
            tamanho_bytes = 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    buffer.write(chunk)
                    tamanho_bytes += len(chunk)
            buffer.seek(0)
        dl_dur = time.time() - t_dl
        metrics.record("4a_download_ebox", dl_dur)
        if dl_dur > 0:
            mb = tamanho_bytes / (1024 * 1024)
            throughput.record_download(mb, dl_dur)

        t_up = time.time()
        if tamanho_bytes < 8 * 1024 * 1024:
            s3.put_object(Bucket=S3_BUCKET, Key=key, Body=buffer.getvalue())
        else:
            s3.upload_fileobj(
                buffer,
                Bucket=S3_BUCKET,
                Key=key,
                Config=S3_TRANSFER_CONFIG
            )
        up_dur = time.time() - t_up
        metrics.record("4b_upload_s3", up_dur)
        if up_dur > 0:
            mb = tamanho_bytes / (1024 * 1024)
            throughput.record_upload(mb, up_dur)

        return True, round(tamanho_bytes / 1024, 2)
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
    """Lê os Registro Id de um arquivo CSV e retorna cada um como dict."""
    df = pd.read_csv(EXCEL_FILE, encoding="latin-1", sep=";", on_bad_lines="skip")
    coluna = "Registro Id"
    if coluna not in df.columns:
        print(f"Coluna '{coluna}' não encontrada no CSV. Colunas disponíveis: {list(df.columns)}")
        return

    registros = df[coluna].dropna().astype(int).tolist()
    print(f"Total de registros no CSV: {len(registros)}")

    for registro_id in registros:
        yield {"registroId": int(registro_id)}

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

def processar_documento(doc, registro_id, descricao, chave_ebox):
    """Processa um único documento (S3 + Mongo). Pode rodar em paralelo com outros docs."""
    try:
        t1 = time.time()
        ja_existe = col_import.find_one({"documentoId": doc["documentoId"]})
        metrics.record("2_check_duplicado_mongo", time.time() - t1)

        if ja_existe:
            return

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

        t2 = time.time()
        existe_s3, tamanho_kb = s3_file_info(key)
        metrics.record("3_check_s3_exists", time.time() - t2)

        t3 = time.time()
        if not existe_s3:
            nome_base, ext = os.path.splitext(nome_arquivo)
            guid = uuid.uuid4().hex
            nome_arquivo_s3 = f"{nome_base}_{guid}{ext}"
            key = f"TemporaryFiles/{nome_arquivo_s3}"
            baixado_s3, tamanho_kb = download_to_s3(doc["uri"], key)
        else:
            nome_arquivo_s3 = nome_arquivo
            baixado_s3 = True
        metrics.record("4_download_upload_s3", time.time() - t3)

        t4 = time.time()
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
        metrics.record("5_mongo_anexo", time.time() - t4)

        if baixado_s3:
            status = "Download realizado, remoção pendente"
        else:
            status = "Erro no download"

        t5 = time.time()
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
            "nomeArquivoS3": nome_arquivo_s3,
            "s3Key": key
        }
        col_import.insert_one(registro)
        metrics.record("6_save_import_mongo", time.time() - t5)

    except Exception as e:
        print(f"Erro documento {doc.get('documentoId')} do registro {registro_id}: {e}")

_doc_executor = None

def processar_registro(registro_id, descricao=None, chave_ebox=None):
    url = f"{BASE_URL}/registros/{registro_id}/documentos"

    try:
        t0 = time.time()
        response = None
        for tentativa in range(1, SEARCH_TERM_RETRIES + 1):
            rate_limiter.wait()
            try:
                response = http_session.get(
                    url,
                    headers={"X-Api-Key": API_KEY},
                    timeout=60
                )
                if response.status_code == 200:
                    rate_limiter.report_success()
                    break
                rate_limiter.report_error()
                print(f"[documentos] registro={registro_id} tentativa {tentativa}/{SEARCH_TERM_RETRIES} "
                      f"status={response.status_code}")
            except Exception as e:
                rate_limiter.report_error()
                print(f"[documentos] registro={registro_id} tentativa {tentativa}/{SEARCH_TERM_RETRIES} erro: {e}")
                response = None

            if tentativa < SEARCH_TERM_RETRIES:
                backoff = SEARCH_TERM_RETRY_INITIAL_WAIT * (2 ** (tentativa - 1))
                time.sleep(backoff)
        metrics.record("1_api_ebox_documentos", time.time() - t0)

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

        if _doc_executor is not None and len(documentos) > 1:
            futs = [_doc_executor.submit(processar_documento, doc, registro_id, descricao, chave_ebox)
                    for doc in documentos]
            for f in futs:
                try:
                    f.result()
                except Exception as e:
                    print(f"Erro doc paralelo registro {registro_id}: {e}")
        else:
            for doc in documentos:
                processar_documento(doc, registro_id, descricao, chave_ebox)

    except Exception as e:
        print(f"Erro geral registro {registro_id}: {e}")

def main():
    global _doc_executor
    inicio = time.time()
    ids_processados = set()
    tarefas = []

    registros = list(buscar_registros())
    total = len(registros)
    print(f"Total de registros a processar: {total}")
    print(f"Rate limit inicial: {RATE_LIMIT_MIN}s | máximo: {RATE_LIMIT_MAX}s")

    processados = 0
    pulados = 0

    stop_display = threading.Event()
    display_thread = threading.Thread(target=metrics_display_loop, args=(stop_display, 10.0), daemon=True)
    display_thread.start()

    _doc_executor = ThreadPoolExecutor(max_workers=DOC_WORKERS)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        for item in tqdm(registros, desc="Enviando", unit="reg"):
            registro_id = item.get("registroId") or item.get("RegistroId")
            if not registro_id or registro_id in ids_processados:
                pulados += 1
                continue
            ids_processados.add(registro_id)

            if col_import.find_one({"registroId": registro_id}):
                pulados += 1
                continue

            descricao = item.get("descricao") or item.get("Descricao")
            chave_ebox = extrair_chave_ebox(item)

            tarefas.append(executor.submit(
                processar_registro,
                registro_id,
                descricao,
                chave_ebox
            ))
            processados += 1

        print(f"\nAguardando conclusão de {len(tarefas)} tarefas...")
        for future in tqdm(as_completed(tarefas), total=len(tarefas), desc="Processando", unit="reg"):
            try:
                future.result()
            except Exception as e:
                print(f"Erro em tarefa paralela: {e}")

    stop_display.set()
    display_thread.join(timeout=2)

    _doc_executor.shutdown(wait=True)

    duracao = time.time() - inicio
    minutos = int(duracao // 60)
    segundos = int(duracao % 60)

    print(f"\n\nFinalizado em {minutos}m {segundos}s")
    print(f"  Total CSV: {total}")
    print(f"  Processados: {processados}")
    print(f"  Pulados: {pulados}")
    print(f"  Rate limit final: {rate_limiter.interval:.3f}s")

    tp = throughput.stats()
    print(f"\n  Download eBox: {tp['download_mb']:.1f} MB em {tp['download_seconds']:.0f}s "
          f"({tp['download_mb_s']:.2f} MB/s)")
    print(f"  Upload S3:     {tp['upload_mb']:.1f} MB em {tp['upload_seconds']:.0f}s "
          f"({tp['upload_mb_s']:.2f} MB/s)")

    print(f"\n{'=' * 80}")
    print("TEMPO MÉDIO POR ETAPA (FINAL)")
    print(f"{'=' * 80}")
    summary = metrics.summary()
    for step in sorted(summary.keys()):
        s = summary[step]
        label = StepMetrics.STEP_LABELS.get(step, step)
        print(f"  {label:<25} | N={s['count']:<5} | Avg={s['avg']:.3f}s | "
              f"Min={s['min']:.3f}s | Max={s['max']:.3f}s | Tot={s['total']:.1f}s")
    print(f"{'=' * 80}")

if __name__ == "__main__":
    main()
