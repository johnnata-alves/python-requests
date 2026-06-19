"""
Script de migração - Garantia Mecânica
Busca apólices no SQL Server, verifica existência no MongoDB (indexed_customer_files.file_paths),
e salva resultados na collection testeMigracao.Meta.

Features:
- Multithread para processamento rápido
- Retomável: continua de onde parou (último cd_apolice processado)
- Paginação automática de 10.000 em 10.000
- Consulta de detalhes em lote (proc com 100 apólices por vez)
- Barra de progresso com % total, req/s e ETA em horas
- Connection pooling SQL e MongoDB otimizado
"""

import os
import sys
import time
import signal
import threading
from dotenv import load_dotenv
import pyodbc
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from queue import Queue

load_dotenv()

SQL_CONNECTION_STRING = os.getenv("SQL_CONNECTION_I4PRO_META_PRD")
MONGO_URI_INDEXED = os.getenv("PRD_MONGO_SA_EAST")
MONGO_URI_DESTINO = os.getenv("PRD_MONGO_SA_EAST")

DB_INDEXED = "indexed_customer_files"
COLLECTION_FILE_PATHS = "file_paths"

DB_DESTINO = "testeMigracao"
COLLECTION_META = "Meta"

BATCH_SIZE = 1000
PROC_BATCH_SIZE = 100
WORKERS = 20

STOP_REQUESTED = False

def signal_handler(sig, frame):
    global STOP_REQUESTED
    print("\n[STOP] Parada solicitada. Aguardando threads finalizarem...")
    STOP_REQUESTED = True

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class SqlConnectionPool:
    """Pool de conexões SQL reutilizáveis por thread."""

    def __init__(self, connection_string, max_size=20):
        self._connection_string = connection_string
        self._pool = Queue(maxsize=max_size)
        self._lock = threading.Lock()
        for _ in range(max_size):
            self._pool.put(self._create_connection())

    def _create_connection(self):
        return pyodbc.connect(self._connection_string)

    def get(self):
        try:
            conn = self._pool.get_nowait()
            try:
                conn.cursor().execute("SELECT 1")
                return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                return self._create_connection()
        except Exception:
            return self._create_connection()

    def release(self, conn):
        try:
            self._pool.put_nowait(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass

sql_pool = None
mongo_client_indexed = None
mongo_client_destino = None
db_indexed_global = None
db_destino_global = None

def init_connections():
    global sql_pool, mongo_client_indexed, mongo_client_destino
    global db_indexed_global, db_destino_global

    sql_pool = SqlConnectionPool(SQL_CONNECTION_STRING, max_size=WORKERS)

    mongo_client_indexed = MongoClient(MONGO_URI_INDEXED, maxPoolSize=WORKERS + 5)
    db_indexed_global = mongo_client_indexed[DB_INDEXED]

    if MONGO_URI_INDEXED == MONGO_URI_DESTINO:
        mongo_client_destino = mongo_client_indexed
    else:
        mongo_client_destino = MongoClient(MONGO_URI_DESTINO, maxPoolSize=WORKERS + 5)
    db_destino_global = mongo_client_destino[DB_DESTINO]

def print_progress(processed_total, total_global, start_time,
                   existing_count=0, pending_count=0, no_return_count=0, error_count=0,
                   batch_number=0):
    """Imprime progresso numa única linha que se atualiza no terminal."""
    elapsed = time.time() - start_time
    req_per_sec = processed_total / elapsed if elapsed > 0 else 0

    pct_total = (processed_total / total_global * 100) if total_global > 0 else 0

    el_hours = int(elapsed // 3600)
    el_min = int((elapsed % 3600) // 60)
    el_sec = int(elapsed % 60)

    remaining = total_global - processed_total
    eta_seconds = remaining / req_per_sec if req_per_sec > 0 else 0
    eta_hours = int(eta_seconds // 3600)
    eta_min = int((eta_seconds % 3600) // 60)
    eta_sec = int(eta_seconds % 60)

    bar_len = 20
    filled = int(bar_len * pct_total / 100) if total_global > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)

    line = (
        f"\r[{bar}] {pct_total:5.1f}% "
        f"({processed_total:,}/{total_global:,}) | "
        f"{req_per_sec:.1f}r/s | "
        f"Dec:{el_hours}h{el_min:02d}m{el_sec:02d}s | "
        f"Resta:{eta_hours}h{eta_min:02d}m{eta_sec:02d}s | "
        f"B{batch_number} | "
        f"E={existing_count} P={pending_count} S={no_return_count} Err={error_count}"
    )
    sys.stdout.write(line + "   ")
    sys.stdout.flush()

def get_total_count():
    """Busca o total de registros a processar."""
    query = """
        SELECT COUNT(*)
        FROM IntegraMeta..CertificateGrouping cg WITH(NOLOCK)
        INNER JOIN i4pro_erp..corp_apolice ca WITH(NOLOCK)
            ON ca.cd_produto = cg.ProductCode
        INNER JOIN i4pro_erp..corp_pessoas pp WITH(NOLOCK)
            ON ca.id_pessoa_cliente = pp.id_pessoa
        WHERE cg.BranchId = 56
            AND ca.cd_apolice IS NOT NULL
    """
    conn = sql_pool.get()
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        row = cursor.fetchone()
        return row[0] if row else 0
    finally:
        sql_pool.release(conn)

def get_last_processed_apolice():
    """Busca o último cd_apolice processado usando campo numérico auxiliar."""
    last = db_destino_global[COLLECTION_META].find_one(
        {},
        sort=[("cd_apolice_num", -1)],
        projection={"cd_apolice_num": 1}
    )
    if last and "cd_apolice_num" in last:
        return last["cd_apolice_num"]

    pipeline = [
        {"$addFields": {"cd_apolice_int": {"$toLong": "$cd_apolice"}}},
        {"$sort": {"cd_apolice_int": -1}},
        {"$limit": 1},
        {"$project": {"cd_apolice": 1}}
    ]
    result = list(db_destino_global[COLLECTION_META].aggregate(pipeline))
    if result:
        return int(result[0]["cd_apolice"])
    return 1

def fetch_batch_from_sql(last_apolice):
    """Busca um lote de apólices a partir do último cd_apolice processado."""
    query = f"""
        select distinct nr_cnpj_cpf, cd_apolice
        from (
        select top {BATCH_SIZE} pp.nr_cnpj_cpf, ca.cd_apolice
        from
            IntegraMeta..CertificateGrouping cg with(NOLOCK)
            inner join i4pro_erp..corp_apolice ca with(NOLOCK) on ca.cd_produto = cg.ProductCode
            inner join i4pro_erp..corp_pessoas pp with(NOLOCK) on ca.id_pessoa_cliente = pp.id_pessoa
        where
            cg.BranchId = 56
            and ca.cd_apolice is not null
            and ca.cd_apolice > ?
        order by ca.cd_apolice ) as tb
    """
    conn = sql_pool.get()
    try:
        cursor = conn.cursor()
        cursor.execute(query, last_apolice)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]
    finally:
        sql_pool.release(conn)

def check_file_paths_exists(policy_number, document):
    """Verifica se a apólice + documento já existe na collection file_paths."""
    result = db_indexed_global[COLLECTION_FILE_PATHS].find_one(
        {"policy_number": str(policy_number), "document": str(document)},
        projection={"_id": 1}
    )
    return result is not None

def execute_proc_lista(apolices_list):
    """
    Executa a proc sp_GetApoliceGarantiaMecanica_lista em lote.
    Recebe lista de cd_apolice e retorna dict {cd_apolice: [rows]} com os resultados.
    """
    if not apolices_list:
        return {}

    apolices_str = ",".join(str(a) for a in apolices_list)
    conn = sql_pool.get()
    try:
        cursor = conn.cursor()
        cursor.execute(f"EXEC sp_GetApoliceGarantiaMecanica_lista @cd_apolices = '{apolices_str}'")

        columns = [col[0] for col in cursor.description] if cursor.description else []
        rows = cursor.fetchall()

        results_by_apolice = {}
        for row in rows:
            record = {}
            for i, col in enumerate(columns):
                value = row[i]
                if isinstance(value, datetime):
                    record[col] = value
                elif hasattr(value, 'isoformat'):
                    record[col] = value.isoformat()
                else:
                    record[col] = value

            apolice_key = str(record.get("nr_apolice_1", ""))

            if apolice_key:
                if apolice_key not in results_by_apolice:
                    results_by_apolice[apolice_key] = []
                results_by_apolice[apolice_key].append(record)

        return results_by_apolice
    except Exception:
        return {}
    finally:
        sql_pool.release(conn)

def process_batch_proc(records_needing_proc):
    """
    Processa um lote de registros que precisam da proc.
    Chama a proc em lote e salva os resultados no MongoDB.
    Retorna lista de resultados.
    """
    if not records_needing_proc:
        return []

    apolices = [str(r["cd_apolice"]) for r in records_needing_proc]
    proc_results = execute_proc_lista(apolices)

    results = []
    for record in records_needing_proc:
        if STOP_REQUESTED:
            break

        cd_apolice = str(record["cd_apolice"])
        cd_apolice_num = int(record["cd_apolice"])
        nr_cnpj_cpf = str(record["nr_cnpj_cpf"])

        details = proc_results.get(cd_apolice, None)

        if details:
            doc = {
                "cd_apolice": cd_apolice,
                "cd_apolice_num": cd_apolice_num,
                "nr_cnpj_cpf": nr_cnpj_cpf,
                "status": "Pendente geração de certificado",
                "details": details,
                "processed_at": datetime.utcnow()
            }
            status = "Pendente geração de certificado"
        else:
            doc = {
                "cd_apolice": cd_apolice,
                "cd_apolice_num": cd_apolice_num,
                "nr_cnpj_cpf": nr_cnpj_cpf,
                "status": "Sem retorno proc",
                "processed_at": datetime.utcnow()
            }
            status = "Sem retorno proc"

        try:
            db_destino_global[COLLECTION_META].insert_one(doc)
        except DuplicateKeyError:
            status = "já processado"

        results.append({"apolice": cd_apolice, "status": status})

    return results

def process_record_check(record):
    """
    Fase 1: Verifica se o registro já existe no file_paths.
    Retorna o resultado ou None se precisar da proc.
    """
    if STOP_REQUESTED:
        return None, record

    cd_apolice = str(record["cd_apolice"])
    cd_apolice_num = int(record["cd_apolice"])
    nr_cnpj_cpf = str(record["nr_cnpj_cpf"])

    if check_file_paths_exists(cd_apolice, nr_cnpj_cpf):
        doc = {
            "cd_apolice": cd_apolice,
            "cd_apolice_num": cd_apolice_num,
            "nr_cnpj_cpf": nr_cnpj_cpf,
            "status": "Certificado já existente",
            "processed_at": datetime.utcnow()
        }
        try:
            db_destino_global[COLLECTION_META].insert_one(doc)
        except DuplicateKeyError:
            return {"apolice": cd_apolice, "status": "já processado"}, None
        return {"apolice": cd_apolice, "status": "Certificado já existente"}, None
    else:
        return None, record

def main():
    global STOP_REQUESTED

    print("=" * 60)
    print("MIGRAÇÃO GARANTIA MECÂNICA")
    print("=" * 60)
    print(f"Workers: {WORKERS}")
    print(f"Batch size: {BATCH_SIZE:,}")
    print(f"Proc batch size: {PROC_BATCH_SIZE}")
    print()

    print("Inicializando conexões...")
    init_connections()
    print("Conexões OK")
    print()

    print("Contando total de registros...")
    total_global = get_total_count()
    print(f"Total de registros: {total_global:,}")
    print()

    db_destino_global[COLLECTION_META].create_index([("cd_apolice", 1), ("nr_cnpj_cpf", 1)], unique=True)
    db_destino_global[COLLECTION_META].create_index([("cd_apolice_num", -1)])

    already_processed = db_destino_global[COLLECTION_META].estimated_document_count()
    print(f"Já processados anteriormente: {already_processed:,}")
    if already_processed > 0:
        print("Retomando de onde parou...")

    total_processed = already_processed
    batch_number = 0
    existing_count = 0
    pending_count = 0
    no_return_count = 0
    error_count = 0

    global_start_time = time.time()

    while not STOP_REQUESTED:
        batch_number += 1

        last_apolice = get_last_processed_apolice()

        records = fetch_batch_from_sql(last_apolice)

        if not records:
            sys.stdout.write("\r" + " " * 150 + "\r")
            print("[FIM] Não há mais registros para processar.")
            break

        records_needing_proc = []

        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            futures = {
                executor.submit(process_record_check, record): record
                for record in records
            }

            for future in as_completed(futures):
                if STOP_REQUESTED:
                    sys.stdout.write("\r" + " " * 150 + "\r")
                    print("[STOP] Cancelando tarefas pendentes...")
                    executor.shutdown(wait=False, cancel_futures=True)
                    break

                try:
                    result, needs_proc = future.result()
                    if result:
                        total_processed += 1
                        status = result["status"]
                        if "já existente" in status:
                            existing_count += 1
                        elif "já processado" in status:
                            pass

                        print_progress(
                            total_processed, total_global, global_start_time,
                            existing_count, pending_count, no_return_count, error_count,
                            batch_number
                        )
                    elif needs_proc:
                        records_needing_proc.append(needs_proc)
                except Exception as e:
                    error_count += 1
                    total_processed += 1

        if STOP_REQUESTED:
            break

        if records_needing_proc:
            chunks = [
                records_needing_proc[i:i + PROC_BATCH_SIZE]
                for i in range(0, len(records_needing_proc), PROC_BATCH_SIZE)
            ]

            with ThreadPoolExecutor(max_workers=WORKERS) as executor:
                futures = {
                    executor.submit(process_batch_proc, chunk): chunk
                    for chunk in chunks
                }

                for future in as_completed(futures):
                    if STOP_REQUESTED:
                        sys.stdout.write("\r" + " " * 150 + "\r")
                        print("[STOP] Cancelando tarefas pendentes...")
                        executor.shutdown(wait=False, cancel_futures=True)
                        break

                    try:
                        batch_results = future.result()
                        for result in batch_results:
                            total_processed += 1
                            status = result["status"]
                            if "Pendente" in status:
                                pending_count += 1
                            elif "Sem retorno" in status:
                                no_return_count += 1
                            elif "Erro" in status:
                                error_count += 1

                            print_progress(
                                total_processed, total_global, global_start_time,
                                existing_count, pending_count, no_return_count, error_count,
                                batch_number
                            )
                    except Exception as e:
                        error_count += 1

    total_elapsed = time.time() - global_start_time
    total_hours = int(total_elapsed // 3600)
    total_min = int((total_elapsed % 3600) // 60)
    total_sec = int(total_elapsed % 60)

    sys.stdout.write("\r" + " " * 150 + "\r")
    print(f"{'=' * 60}")
    print(f"FINALIZADO")
    print(f"  Total processado: {total_processed:,} / {total_global:,}")
    print(f"  Existentes: {existing_count:,} | Pendentes: {pending_count:,} | Sem retorno: {no_return_count:,} | Erros: {error_count:,}")
    print(f"  Tempo total: {total_hours}h{total_min:02d}m{total_sec:02d}s")
    print(f"{'=' * 60}")

if __name__ == "__main__":
    main()
