"""
Percorre AvisoSinistroAutomacao, pega Protocolo + NumeroBilhete,
busca o saldo devedor correspondente na AvisoSinistro
(InformacoesComplementaresContrato[].contratoum ou InformacoesComplementares.contratoum),
comparando pelo NumeroBilhete, e compara com SaldoDevedorUm.

Se diferente (ou nao encontrado -> null), atualiza AvisoSinistroAutomacao:
  - SaldoDevedorUm com o saldo encontrado (ou null)
  - ContratoUm com o NumeroBilhete
e registra o caso no CSV.

Retomavel: mantem checkpoint dos _id ja processados. Se o script parar,
continua de onde parou.
"""

import csv
import os
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

warnings.filterwarnings("ignore")

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DB_NAME = "SinistrosMicroService"
COL_AUTOMACAO = "AvisoSinistroAutomacao"
COL_AVISO = "AvisoSinistro"

OUTPUT_CSV = "corrigir_saldo_automacao.csv"
CHECKPOINT_FILE = "corrigir_saldo_automacao.checkpoint"

WORKERS = int(os.getenv("WORKERS", "20"))

CSV_FIELDS = [
    "_id",
    "Protocolo",
    "NumeroBilhete",
    "ContratoAntigo",
    "SaldoAntigo",
    "SaldoNovo",
    "Origem",
    "Status",
]


def normalizar_contrato(valor):
    """Normaliza contrato para comparacao: string sem zeros a esquerda."""
    if valor is None:
        return None
    return str(valor).strip().lstrip("0") or "0"


def buscar_saldo(aviso, contrato_alvo):
    """
    Procura o saldo devedor na AvisoSinistro para o contrato informado.
    Retorna (saldo, origem) ou (None, None) se nao encontrar.
    """
    alvo = normalizar_contrato(contrato_alvo)
    if alvo is None:
        return None, None

    # InformacoesComplementaresContrato (lista)
    for info in aviso.get("InformacoesComplementaresContrato") or []:
        if normalizar_contrato(info.get("contratoum")) == alvo:
            return info.get("saldodevedorum"), "InformacoesComplementaresContrato"

    # InformacoesComplementares (objeto unico)
    info_single = aviso.get("InformacoesComplementares") or {}
    if isinstance(info_single, dict):
        if normalizar_contrato(info_single.get("contratoum")) == alvo:
            return info_single.get("saldodevedorum"), "InformacoesComplementares"

    return None, None


def saldo_vazio(valor):
    """Considera null, vazio ou 0 como 'sem saldo'."""
    if valor is None:
        return True
    if isinstance(valor, str) and valor.strip() == "":
        return True
    try:
        return round(float(valor), 2) == 0.0
    except (TypeError, ValueError):
        return False


def saldos_diferentes(atual, novo):
    """Compara saldos tolerando float.
    null/vazio/0 sao tratados como equivalentes entre si."""
    atual_vazio = saldo_vazio(atual)
    novo_vazio = saldo_vazio(novo)

    if atual_vazio and novo_vazio:
        return False
    if atual_vazio or novo_vazio:
        return True
    try:
        return round(float(atual), 2) != round(float(novo), 2)
    except (TypeError, ValueError):
        return str(atual) != str(novo)


def carregar_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return set()
    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        return {linha.strip() for linha in f if linha.strip()}


def main():
    if not MONGO_URI:
        print("ERRO: PRD_MONGO_SA_EAST nao configurado no .env")
        return

    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    col_automacao = db[COL_AUTOMACAO]
    col_aviso = db[COL_AVISO]

    processados = carregar_checkpoint()
    print(f"Ja processados (checkpoint): {len(processados)}")

    csv_novo = not os.path.exists(OUTPUT_CSV)
    csv_file = open(OUTPUT_CSV, "a", newline="", encoding="utf-8-sig")
    csv_writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDS)
    if csv_novo:
        csv_writer.writeheader()
        csv_file.flush()

    ckpt_file = open(CHECKPOINT_FILE, "a", encoding="utf-8")

    filtro = {"NumeroBilhete": {"$nin": [None, ""]}}
    total = col_automacao.count_documents(filtro)
    cursor = col_automacao.find(
        filtro,
        {"Protocolo": 1, "NumeroBilhete": 1, "ContratoUm": 1, "SaldoDevedorUm": 1},
    )

    contadores = {"atualizados": 0, "sem_saldo": 0}
    io_lock = threading.Lock()
    cont_lock = threading.Lock()

    def processar(doc):
        """Processa 1 documento. Thread-safe. Retorna id_str para checkpoint."""
        _id = doc["_id"]
        id_str = str(_id)

        protocolo = doc.get("Protocolo")
        numero_bilhete = doc.get("NumeroBilhete")
        contrato_atual = doc.get("ContratoUm")
        saldo_atual = doc.get("SaldoDevedorUm")

        aviso = None
        if protocolo:
            aviso = col_aviso.find_one(
                {"Protocolo": protocolo},
                {
                    "InformacoesComplementaresContrato": 1,
                    "InformacoesComplementares": 1,
                },
            )

        if aviso is None:
            saldo_novo, origem = None, None
            encontrado = False
        else:
            # Busca o saldo pelo NumeroBilhete
            saldo_novo, origem = buscar_saldo(aviso, numero_bilhete)
            encontrado = origem is not None

        # So atualiza se diferente ou nao encontrado
        if saldos_diferentes(saldo_atual, saldo_novo):
            col_automacao.update_one(
                {"_id": _id},
                {"$set": {"SaldoDevedorUm": saldo_novo, "ContratoUm": numero_bilhete}},
            )

            if not encontrado:
                status = "Atualizado (saldo nao encontrado -> null)"
            else:
                status = "Atualizado"

            with cont_lock:
                contadores["atualizados"] += 1
                if not encontrado:
                    contadores["sem_saldo"] += 1

            with io_lock:
                csv_writer.writerow(
                    {
                        "_id": id_str,
                        "Protocolo": protocolo,
                        "NumeroBilhete": numero_bilhete,
                        "ContratoAntigo": contrato_atual,
                        "SaldoAntigo": saldo_atual,
                        "SaldoNovo": saldo_novo,
                        "Origem": origem or "",
                        "Status": status,
                    }
                )
                csv_file.flush()

        return id_str

    def drenar(futures, barra):
        for fut in as_completed(futures):
            id_str = fut.result()
            with io_lock:
                ckpt_file.write(id_str + "\n")
                ckpt_file.flush()
            barra.update(1)

    try:
        with ThreadPoolExecutor(max_workers=WORKERS) as executor:
            barra = tqdm(total=total, desc="Automacao", unit="reg")
            futures = []
            lote = WORKERS * 10  # limita futures em memoria

            for doc in cursor:
                if str(doc["_id"]) in processados:
                    barra.update(1)
                    continue
                futures.append(executor.submit(processar, doc))
                if len(futures) >= lote:
                    drenar(futures, barra)
                    futures = []

            if futures:
                drenar(futures, barra)

            barra.close()
    finally:
        csv_file.close()
        ckpt_file.close()
        client.close()

    print("\nFinalizado!")
    print(f"  Atualizados: {contadores['atualizados']}")
    print(f"  Sem saldo (setado null): {contadores['sem_saldo']}")
    print(f"  CSV: {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
