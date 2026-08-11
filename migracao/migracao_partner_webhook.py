import json
import os
import queue
import threading
import time

from bson import ObjectId
from bson.int64 import Int64
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

SOURCE_MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
TARGET_MONGO_URI = os.getenv("PRD_MONGO_CLAIM_ENGINE")

SOURCE_DB = "SinistrosMicroService"
SOURCE_COLLECTION = "SinistroTimeline_exported"
TARGET_DB = "ClaimEngine"
TARGET_COLLECTION = "PartnerWebhook"

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
LIMIT = int(os.getenv("LIMIT", "0"))  # 0 = sem limite
MAX_WORKERS = int(os.getenv("WORKERS", "8"))

# Codigo -> event
CODIGO_EVENT = {
    "10105": "ClaimCanceled",
    "11111": "CompensationReleased",
    "11112": "CompensationPaid",
    "11114": "CompensationCanceled",
    "11113": "CompensationRejected",
    "426": "DocumentRequested",
    "20003": "DocumentAttached",
    "20002": "ClaimOpened",
}
COMPENSATION_EVENTS = {
    "CompensationReleased",
    "CompensationPaid",
    "CompensationCanceled",
    "CompensationRejected",
}


def map_event(codigo):
    return CODIGO_EVENT.get(str(codigo), "ClaimStatusChanged")


def detalhes_dict(info_adicional):
    detalhes = (info_adicional or {}).get("Detalhes") or []
    result = {}
    for item in detalhes:
        chave = item.get("Chave")
        if chave is not None:
            result[chave] = item.get("Valor")
    return result


def extract_id_pagamento(info_adicional, detalhes):
    # 1) direto de Indenizacao.Pagamento.Coberturas[].IdPagamento
    indenizacao = (info_adicional or {}).get("Indenizacao") or {}
    pagamento = (indenizacao or {}).get("Pagamento") or {}
    coberturas = pagamento.get("Coberturas") or []
    for cob in coberturas:
        id_pag = cob.get("IdPagamento")
        if id_pag is not None:
            return id_pag
    # 2) fallback: parse do payload em Detalhes
    payload_raw = detalhes.get("payload")
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
            for cob in (payload.get("pagamento") or {}).get("coberturas") or []:
                id_pag = cob.get("idPagamento")
                if id_pag is not None:
                    return id_pag
        except (ValueError, TypeError):
            pass
    return None


def resolve_key(event, info_adicional, detalhes):
    if event in COMPENSATION_EVENTS:
        return extract_id_pagamento(info_adicional, detalhes)
    if event == "DocumentAttached":
        return detalhes.get("AnexoDocumentoId")
    # ClaimCanceled, DocumentRequested, ClaimOpened, ClaimStatusChanged
    return None


def to_int64(value):
    if value is None:
        return None
    try:
        return Int64(int(str(value).strip()))
    except (ValueError, TypeError):
        return None


def is_eligible(doc):
    if not doc.get("NotificaParceiro"):
        return False
    detalhes = detalhes_dict(doc.get("InformacaoAdicional"))
    return detalhes.get("Parceiro") == "PAN"


def transform(doc):
    info_adicional = doc.get("InformacaoAdicional") or {}
    detalhes = detalhes_dict(info_adicional)
    event = map_event(doc.get("Codigo"))
    data_inclusao = doc.get("DataInclusao")

    return {
        "_id": ObjectId(),
        "partner": detalhes.get("Parceiro"),
        "key": resolve_key(event, info_adicional, detalhes),
        "event": event,
        "calls": [],
        "claimNumber": to_int64(doc.get("NumeroSinistro")),
        "createdAt": data_inclusao,
        "deliveryAt": data_inclusao,
        "payload": None,
        "protocol": doc.get("Protocolo"),
        "status": "Success",
    }


BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1000"))
QUEUE_MAXSIZE = MAX_WORKERS * 2
RESET_PROCESSING = os.getenv("RESET_PROCESSING", "false").lower() == "true"

# so processa quem ainda nao tem status
QUERY = {"ParceiroNotificado": True, "status": None}

STATUS_PROCESSING = "processing"
STATUS_OK = "sucesso"
STATUS_INELEGIVEL = "não elegível"

PROJECTION = {
    "Protocolo": 1,
    "NumeroSinistro": 1,
    "Codigo": 1,
    "DataInclusao": 1,
    "NotificaParceiro": 1,
    "InformacaoAdicional": 1,
}


def claim_batch(source_collection, ids):
    # marca o lote como processing (claim) para permitir retomada em caso de falha
    if not DRY_RUN:
        source_collection.update_many(
            {"_id": {"$in": ids}},
            {"$set": {"status": STATUS_PROCESSING}},
        )


def process_batch(batch, source_collection, target_collection):
    docs = []
    ok_ids = []
    inelegivel_ids = []
    for doc in batch:
        if is_eligible(doc):
            docs.append(transform(doc))
            ok_ids.append(doc["_id"])
        else:
            inelegivel_ids.append(doc["_id"])

    if not DRY_RUN:
        if docs:
            target_collection.insert_many(docs, ordered=False)
        if ok_ids:
            source_collection.update_many(
                {"_id": {"$in": ok_ids}},
                {"$set": {"status": STATUS_OK}},
            )
        if inelegivel_ids:
            source_collection.update_many(
                {"_id": {"$in": inelegivel_ids}},
                {"$set": {"status": STATUS_INELEGIVEL}},
            )

    return len(ok_ids), len(inelegivel_ids)


def reader_loop(source_collection, work_queue, stop_event):
    """Leitor unico: streaming do cursor, claim em processing e enfileira lotes."""
    cursor = source_collection.find(
        QUERY, PROJECTION, no_cursor_timeout=True
    ).batch_size(BATCH_SIZE)
    sent = 0
    batch = []
    try:
        for doc in cursor:
            if stop_event.is_set():
                break
            batch.append(doc)
            if len(batch) >= BATCH_SIZE:
                claim_batch(source_collection, [d["_id"] for d in batch])
                work_queue.put(batch)
                sent += len(batch)
                batch = []
                if LIMIT > 0 and sent >= LIMIT:
                    break
        if batch and not stop_event.is_set():
            claim_batch(source_collection, [d["_id"] for d in batch])
            work_queue.put(batch)
    finally:
        cursor.close()
        for _ in range(MAX_WORKERS):
            work_queue.put(None)


def worker_loop(work_queue, source_collection, target_collection, stats, lock, pbar):
    while True:
        batch = work_queue.get()
        if batch is None:
            work_queue.task_done()
            break
        try:
            ins, skp = process_batch(batch, source_collection, target_collection)
            with lock:
                stats["inserted"] += ins
                stats["inelegivel"] += skp
                stats["processed"] += len(batch)
                pbar.update(len(batch))
        except Exception as exc:  # nao derruba a migracao inteira por 1 lote
            with lock:
                stats["errors"] += 1
            print(f"\nErro no lote: {exc}")
        finally:
            work_queue.task_done()


def main():
    source_client = MongoClient(SOURCE_MONGO_URI)
    target_client = MongoClient(TARGET_MONGO_URI)

    source = source_client[SOURCE_DB][SOURCE_COLLECTION]
    target = target_client[TARGET_DB][TARGET_COLLECTION]

    if RESET_PROCESSING and not DRY_RUN:
        reverted = source.update_many(
            {"status": STATUS_PROCESSING}, {"$set": {"status": None}}
        ).modified_count
        print(f"Reset: {reverted} registros 'processing' voltaram para pendente.")

    total = source.count_documents(QUERY)
    if LIMIT > 0:
        total = min(total, LIMIT)

    print(f"Origem: {SOURCE_DB}.{SOURCE_COLLECTION} ({total} pendentes)")
    print(f"Destino: {TARGET_DB}.{TARGET_COLLECTION}")
    print(f"DRY_RUN={DRY_RUN} | WORKERS={MAX_WORKERS} | BATCH_SIZE={BATCH_SIZE}")

    if total == 0:
        print("Nada a processar.")
        return

    work_queue = queue.Queue(maxsize=QUEUE_MAXSIZE)
    stop_event = threading.Event()
    lock = threading.Lock()
    stats = {"inserted": 0, "inelegivel": 0, "processed": 0, "errors": 0}

    with tqdm(total=total, desc="Migrando", unit="reg") as pbar:
        workers = [
            threading.Thread(
                target=worker_loop,
                args=(work_queue, source, target, stats, lock, pbar),
                daemon=True,
            )
            for _ in range(MAX_WORKERS)
        ]
        for w in workers:
            w.start()

        reader = threading.Thread(
            target=reader_loop, args=(source, work_queue, stop_event), daemon=True
        )
        reader.start()

        try:
            reader.join()
            for w in workers:
                w.join()
        except KeyboardInterrupt:
            print("\nInterrompido. Registros em 'processing' podem ser retomados "
                  "com RESET_PROCESSING=true.")
            stop_event.set()

    print(
        f"\nFinalizado | Processados: {stats['processed']} | "
        f"Inseridos: {stats['inserted']} | Não elegíveis: {stats['inelegivel']} | "
        f"Lotes com erro: {stats['errors']}"
    )
    if DRY_RUN:
        print("DRY_RUN ativo: nada foi gravado nem atualizado.")


RESTART_DELAY = int(os.getenv("RESTART_DELAY", "10"))  # segundos


if __name__ == "__main__":
    while True:
        try:
            main()
        except KeyboardInterrupt:
            print("\nEncerrado pelo usuário.")
            break
        except Exception as exc:
            print(f"\nErro no ciclo: {exc}")
        print(f"Aguardando {RESTART_DELAY}s para reiniciar...")
        time.sleep(RESTART_DELAY)
