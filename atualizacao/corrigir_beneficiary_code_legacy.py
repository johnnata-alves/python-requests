"""
Percorre ClaimEngine.LegacyDocument com beneficiaryCode != 0, agrupando
por claimNumber em lotes de 100.

Para cada lote faz UMA consulta no I4Pro (nr_sinistro in (...)) e carrega
em memoria o mapa id_sin_documento -> id_pessoa. Depois compara com o
claimDocumentId/beneficiaryCode de cada LegacyDocument do lote.

Se id_pessoa for diferente do beneficiaryCode, atualiza beneficiaryCode e
UpdatedAt (bulk_write por lote) e registra o caso no CSV. Se for igual, pula.

Retomavel: mantem checkpoint dos claimNumber ja processados. Pode ser
interrompido a qualquer momento com Ctrl+C: os lotes em andamento terminam,
o checkpoint e gravado e a proxima execucao continua de onde parou.
Um segundo Ctrl+C forca a saida imediata (o lote em andamento sera refeito).

DRY_RUN=true (padrao) apenas gera o CSV, sem atualizar o Mongo.
Dry run e execucao real usam CSV e checkpoint separados.
"""

import csv
import os
import threading
import warnings
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

import pyodbc
from dotenv import load_dotenv
from pymongo import MongoClient, UpdateOne
from tqdm import tqdm

warnings.filterwarnings("ignore")

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
SQL_CONNECTION = os.getenv("SQL_CONNECTION_I4PRO_PRD")
DB_NAME = "ClaimEngine"
COL_LEGACY_DOCUMENT = "LegacyDocument"

WORKERS = int(os.getenv("WORKERS", "10"))
LOTE_SINISTROS = int(os.getenv("LOTE_SINISTROS", "100"))
DRY_RUN = os.getenv("DRY_RUN", "true").strip().lower() in ("1", "true", "yes")

_SUFIXO = "_dryrun" if DRY_RUN else ""
OUTPUT_CSV = f"corrigir_beneficiary_code_legacy{_SUFIXO}.csv"
CHECKPOINT_FILE = f"corrigir_beneficiary_code_legacy_claims{_SUFIXO}.checkpoint"

FILTRO = {"beneficiaryCode": {"$ne": 0}}

SQL_ID_PESSOA = """
select a.nr_sinistro, a.id_sin_documento, b.id_pessoa
from
    corp_sin_documento a (nolock)
    inner join corp_sin_beneficiario b (nolock) on a.id_sin_beneficiario = b.id_sin_beneficiario
where
    a.nr_sinistro in ({placeholders})
"""

CSV_FIELDS = [
    "_id",
    "claimNumber",
    "protocol",
    "claimDocumentId",
    "documentCode",
    "beneficiaryCodeAntigo",
    "beneficiaryCodeNovo",
    "Status",
]

_thread_local = threading.local()


def get_sql_conn():
    """Uma conexao pyodbc por thread."""
    conn = getattr(_thread_local, "sql_conn", None)
    if conn is None:
        conn = pyodbc.connect(SQL_CONNECTION)
        _thread_local.sql_conn = conn
    return conn


def buscar_pessoas(claim_numbers):
    """Retorna {id_sin_documento: id_pessoa} para todos os sinistros do lote."""
    sql = SQL_ID_PESSOA.format(placeholders=",".join("?" * len(claim_numbers)))
    cursor = get_sql_conn().cursor()
    try:
        cursor.execute(sql, *claim_numbers)
        return {
            int(id_sin_documento): int(id_pessoa)
            for _, id_sin_documento, id_pessoa in cursor.fetchall()
            if id_sin_documento is not None and id_pessoa is not None
        }
    finally:
        cursor.close()


def carregar_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return set()
    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        return {linha.strip() for linha in f if linha.strip()}


def main():
    if not MONGO_URI:
        print("ERRO: PRD_MONGO_URI nao configurado no .env")
        return
    if not SQL_CONNECTION:
        print("ERRO: SQL_CONNECTION_I4PRO_PRD nao configurado no .env")
        return

    print(f"DRY_RUN: {DRY_RUN} | WORKERS: {WORKERS} | LOTE_SINISTROS: {LOTE_SINISTROS}")

    client = MongoClient(MONGO_URI)
    col = client[DB_NAME][COL_LEGACY_DOCUMENT]

    processados = carregar_checkpoint()
    print(f"Sinistros ja processados (checkpoint): {len(processados)}")

    print("Carregando claimNumbers distintos...")
    claim_numbers = [
        g["_id"]
        for g in col.aggregate(
            [
                {"$match": FILTRO},
                {"$group": {"_id": "$claimNumber"}},
            ],
            allowDiskUse=True,
        )
        if g["_id"] is not None and str(g["_id"]) not in processados
    ]
    lotes = [
        claim_numbers[i:i + LOTE_SINISTROS]
        for i in range(0, len(claim_numbers), LOTE_SINISTROS)
    ]
    print(f"Sinistros a processar: {len(claim_numbers)} em {len(lotes)} lotes")

    csv_novo = not os.path.exists(OUTPUT_CSV)
    csv_file = open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig")
    csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
    if csv_novo:
        csv_writer.writeheader()
        csv_file.flush()

    ckpt_file = open(CHECKPOINT_FILE, "a", encoding="utf-8")

    contadores = {"docs": 0, "atualizados": 0, "iguais": 0, "sem_sql": 0, "erros": 0}
    io_lock = threading.Lock()

    def processar_lote(lote):
        """Processa um lote de claimNumbers. Retorna contadores do lote."""
        pessoas = buscar_pessoas([int(c) for c in lote])

        docs = col.find(
            {**FILTRO, "claimNumber": {"$in": lote}},
            {
                "claimDocumentId": 1,
                "beneficiaryCode": 1,
                "claimNumber": 1,
                "protocol": 1,
                "documentCode": 1,
            },
        )

        res = {"docs": 0, "atualizados": 0, "iguais": 0, "sem_sql": 0}
        agora = datetime.now(timezone.utc)
        ops = []
        linhas = []

        for doc in docs:
            res["docs"] += 1
            claim_document_id = doc.get("claimDocumentId")
            beneficiary_atual = doc.get("beneficiaryCode")
            id_pessoa = pessoas.get(int(claim_document_id)) if claim_document_id else None

            if id_pessoa is None:
                res["sem_sql"] += 1
                continue
            if beneficiary_atual is not None and int(beneficiary_atual) == id_pessoa:
                res["iguais"] += 1
                continue

            res["atualizados"] += 1
            ops.append(
                UpdateOne(
                    {"_id": doc["_id"]},
                    {"$set": {"beneficiaryCode": id_pessoa, "UpdatedAt": agora}},
                )
            )
            linhas.append(
                {
                    "_id": str(doc["_id"]),
                    "claimNumber": doc.get("claimNumber"),
                    "protocol": doc.get("protocol"),
                    "claimDocumentId": claim_document_id,
                    "documentCode": doc.get("documentCode"),
                    "beneficiaryCodeAntigo": beneficiary_atual,
                    "beneficiaryCodeNovo": id_pessoa,
                    "Status": "DRY_RUN" if DRY_RUN else "Atualizado",
                }
            )

        if ops and not DRY_RUN:
            col.bulk_write(ops, ordered=False)

        # CSV e checkpoint gravados juntos, apos o bulk_write do lote
        with io_lock:
            if linhas:
                csv_writer.writerows(linhas)
                csv_file.flush()
            ckpt_file.writelines(f"{c}\n" for c in lote)
            ckpt_file.flush()

        return res

    # tqdm mostra andamento, taxa e tempo estimado (ETA)
    barra = tqdm(
        total=len(processados) + len(claim_numbers),
        initial=len(processados),
        desc="Sinistros",
        unit="sin",
    )

    def tratar(fut, lote):
        try:
            res = fut.result()
            for k, v in res.items():
                contadores[k] += v
        except Exception as e:
            contadores["erros"] += 1
            tqdm.write(f"ERRO lote {lote[0]}..{lote[-1]}: {e}")
        barra.update(len(lote))
        barra.set_postfix(
            docs=contadores["docs"],
            alt=contadores["atualizados"],
            iguais=contadores["iguais"],
            sem_sql=contadores["sem_sql"],
            erros=contadores["erros"],
        )

    def aguardar(pendentes, modo):
        # wait com timeout para o Ctrl+C ser atendido tambem no Windows
        while True:
            feitos, _ = wait(pendentes, timeout=1, return_when=modo)
            if feitos:
                for fut in feitos:
                    tratar(fut, pendentes.pop(fut))
                return

    executor = ThreadPoolExecutor(max_workers=WORKERS)
    pendentes = {}  # future -> lote
    interrompido = False
    try:
        # Submete em janela (WORKERS * 2) para o Ctrl+C nao ficar preso
        # esperando todos os lotes ja enfileirados.
        for lote in lotes:
            while len(pendentes) >= WORKERS * 2:
                aguardar(pendentes, FIRST_COMPLETED)
            pendentes[executor.submit(processar_lote, lote)] = lote
        while pendentes:
            aguardar(pendentes, FIRST_COMPLETED)
    except KeyboardInterrupt:
        interrompido = True
        for fut in list(pendentes):
            if fut.cancel():
                pendentes.pop(fut)
        tqdm.write(
            f"\nInterrompido. Aguardando {len(pendentes)} lote(s) em andamento "
            "terminarem para gravar o checkpoint (Ctrl+C de novo forca a saida)..."
        )
        while pendentes:
            aguardar(pendentes, FIRST_COMPLETED)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
        barra.close()
        csv_file.close()
        ckpt_file.close()
        client.close()

    if interrompido:
        print("\nExecucao interrompida. Rode novamente para continuar de onde parou.")
    else:
        print("\nFinalizado!")
    print(f"  Documentos analisados: {contadores['docs']}")
    print(f"  Alterados{' (dry run)' if DRY_RUN else ''}: {contadores['atualizados']}")
    print(f"  Ja iguais (pulados): {contadores['iguais']}")
    print(f"  Sem retorno no SQL: {contadores['sem_sql']}")
    print(f"  Lotes com erro: {contadores['erros']}")
    print(f"  CSV: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
