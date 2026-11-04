"""
Envia a lista de documentos pendentes para a API de sinistros do BTG.

Para cada protocolo informado:
1. Consulta ClaimEngine.Notification (protocol) e pega
   insured.documentNumber e certificate.
2. Chama POST https://api.claims.btgpactual.com/claims/{protocolo}/documents
   com os documentos fixos (identificacao, extrato, bloqueio do cartao).

Uso:
    python integracao/enviar_documentos_btg.py 2025000123 2025000456
    python integracao/enviar_documentos_btg.py protocolos.txt   (um por linha)
Sem argumentos usa a lista PROTOCOLOS abaixo.
"""

import os
import re
import sys

import requests
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# ------------------------------------------------------------------ Config
MONGO_CLAIM = os.getenv("PRD_MONGO_URI")
DB_CLAIM = os.getenv("PRD_DB_CLAIM_ENGINE", "ClaimEngine")

BTG_API_BASE = "https://api.claims.btgpactual.com"
BTG_API_KEY = os.getenv("BTG_CLAIMS_API_KEY")

LOG_CSV = "enviar_documentos_btg.csv"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

PROTOCOLOS = [
# "11202692205015467",
# "11202692205015786",
# "11202610605055938",
# "11202610905066241",
# "112026101205068428",
# "112026101305069535",
# "112026101305072113",
# "11202692405021961",
# "112026101405077804",
# "11202692705027216"

"112026101405077804"
]

DOCUMENTOS = [
    {
        "documentName": "DOCUMENTO_IDENTIFICACAO",
        "documentDetail": "DOCUMENTO DE IDENTIFICAÇÃO DO CLIENTE DEVIDAMENTE VÁLIDO",
        "documentLocation": None,
        "repositoryName": None,
    },
    {
        "documentName": "EXTRATO_CONTA_CARTAO",
        "documentDetail": "CÓPIA DAS FATURAS/ EXTRATOS QUE COMPROVEM AS COMPRAS/ SAQUES INDEVIDOS",
        "documentLocation": None,
        "repositoryName": None,
    },
    {
        "documentName": "COMPROVANTE_BLOQUEIO_CARTAO",
        "documentDetail": "CÓPIA SIMPLES DO COMPROVANTE DE BLOQUEIO DO CARTÃO",
        "documentLocation": None,
        "repositoryName": None,
    },
]


# ------------------------------------------------------------------ Entrada
def ler_protocolos(args):
    if not args:
        return PROTOCOLOS
    if len(args) == 1 and os.path.isfile(args[0]):
        with open(args[0], "r", encoding="utf-8-sig") as f:
            return [l.strip() for l in f if l.strip()]
    return args


# ------------------------------------------------------------------ Payload / API
def build_payload(protocolo, notification):
    doc = re.sub(r"\D", "", str((notification.get("insured") or {}).get("documentNumber") or ""))
    if not doc:
        raise ValueError("insured.documentNumber vazio")
    certificate = notification.get("certificate")
    if not certificate:
        raise ValueError("certificate vazio")

    return {
        "claimNumber": str(protocolo),
        "insuredDocumentNumber": int(doc),  # numerico, sem zeros a esquerda
        "policyNumber": str(certificate),
        "endorsementNumber": "0",
        "insurerCode": 1,
        "CodigoDoCanal": None,
        "documents": DOCUMENTOS,
    }


def enviar_documentos(protocolo, payload):
    resp = requests.post(
        f"{BTG_API_BASE}/claims/{protocolo}/documents",
        json=payload,
        headers={
            "sourceSystem": "10",
            "X-API-Key": BTG_API_KEY,
            "Content-Type": "application/json",
        },
        timeout=120,
    )
    return resp


# ------------------------------------------------------------------ Main
def main():
    faltando = [
        n for n, v in {
            "PRD_MONGO_URI": MONGO_CLAIM,
            "BTG_CLAIMS_API_KEY": BTG_API_KEY or ("dry" if DRY_RUN else None),
        }.items() if not v
    ]
    if faltando:
        print(f"ERRO: variaveis .env faltando: {', '.join(faltando)}")
        return

    protocolos = ler_protocolos(sys.argv[1:])
    if not protocolos:
        print("Nenhum protocolo informado.")
        return
    print(f"Protocolos: {len(protocolos)} | DRY_RUN={DRY_RUN}")

    client = MongoClient(MONGO_CLAIM)
    col_notification = client[DB_CLAIM]["Notification"]

    csv_novo = not os.path.exists(LOG_CSV)
    csv_file = open(LOG_CSV, "a", encoding="utf-8-sig", newline="")
    if csv_novo:
        csv_file.write("protocolo,documento,certificate,status,http_status,resposta\n")

    ok = erro = 0
    try:
        for protocolo in protocolos:
            notification = col_notification.find_one(
                {"protocol": protocolo},
                {"insured.documentNumber": 1, "certificate": 1},
            )
            if not notification:
                print(f"[{protocolo}] Notification nao encontrada.")
                csv_file.write(f"{protocolo},,,nao_encontrado,,\n")
                erro += 1
                continue

            try:
                payload = build_payload(protocolo, notification)
            except ValueError as e:
                print(f"[{protocolo}] ERRO: {e}")
                csv_file.write(f"{protocolo},,,erro_dados,,{e}\n")
                erro += 1
                continue

            doc, cert = payload["insuredDocumentNumber"], payload["policyNumber"]
            if DRY_RUN:
                print(f"[{protocolo}] [DRY_RUN] doc={doc} certificate={cert}")
                csv_file.write(f"{protocolo},{doc},{cert},dry_run,,\n")
                continue

            try:
                resp = enviar_documentos(protocolo, payload)
                corpo = resp.text.replace("\n", " ").replace(",", ";")[:500]
                status = "ok" if resp.ok else "erro_api"
                print(f"[{protocolo}] HTTP {resp.status_code} doc={doc} certificate={cert}")
                if not resp.ok:
                    print(f"    {corpo}")
                csv_file.write(f"{protocolo},{doc},{cert},{status},{resp.status_code},{corpo}\n")
                ok += resp.ok
                erro += not resp.ok
            except requests.RequestException as e:
                print(f"[{protocolo}] ERRO request: {e}")
                csv_file.write(f"{protocolo},{doc},{cert},erro_request,,{e}\n")
                erro += 1
            csv_file.flush()
    finally:
        csv_file.close()
        client.close()

    print(f"\nFinalizado! OK: {ok} | Erros: {erro} | Log: {LOG_CSV}")


if __name__ == "__main__":
    main()
