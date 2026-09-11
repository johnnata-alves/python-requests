"""
Atualiza additionalInformation.balanceDue na Notification (e Claim) com base em duas planilhas:
1. "massa de testes preaviso.xlsx" -> lista de CPFs a processar
2. "Analitico_sinistro_.xlsx" -> mapa CPF -> contrato -> saldo devedor
"""

import os
import threading
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import pandas as pd
import urllib3
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
# MONGO_URI = os.getenv("HML_MONGO_URI")
DB_NAME = "ClaimEngine"

PLANILHA_CPFS = "massa de prod.xlsx"
PLANILHA_ANALITICO = "gabarito.xlsx"
OUTPUT_FILE = "resultado_atualizar_saldo_planilha.xlsx"

MAX_WORKERS = 10


def norm(valor) -> str:
    """Normaliza certificado/contrato: tira .0 final e zeros a esquerda."""
    s = str(valor or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s.lstrip("0")


def processar_cpf(db, cpf, contrato_map, certificados_planilha):
    """Processa um CPF e retorna lista de resultados. Thread-safe (MongoClient e thread-safe)."""
    saida = []
    cpf_padded = cpf.zfill(11)
    notifications = list(db["Notification"].find({
        "insured.documentNumber": cpf_padded,
        "coverage": "DEATH",
    }))

    if not notifications:
        saida.append({"cpf": cpf, "certificate": "", "protocol": "", "balanceDue": None, "status": "Nenhuma Notification encontrada"})
        return saida

    for notif in notifications:
        certificate = str(notif.get("certificate") or "").strip()
        certificate_norm = norm(certificate)
        notif_id = notif["_id"]
        flow_id = notif.get("flowId")
        claim_number = notif.get("claimNumber")

        # So processa certificados presentes na planilha de CPFs (comparacao normalizada)
        if certificate_norm not in certificados_planilha:
            saida.append({
                "cpf": cpf,
                "certificate": certificate,
                "protocol": notif.get("protocol"),
                "balanceDue": None,
                "claimAtualizado": False,
                "status": "Certificate fora da planilha - ignorado",
            })
            continue

        # Verificar match com planilha analitico (comparacao normalizada)
        saldo = contrato_map.get(certificate_norm)

        if saldo and saldo != "nan":
            db["Notification"].update_one(
                {"_id": notif_id},
                {
                    "$set": {"additionalInformation.balanceDue": saldo, "UpdatedAt": datetime.now(timezone.utc)},
                    "$unset": {"additionalInformation.SaldoDevedor": ""},
                }
            )

            if claim_number is not None:
                db["Claim"].update_one(
                    {"flowId": flow_id},
                    {
                        "$set": {"additionalInformation.balanceDue": saldo, "UpdatedAt": datetime.now(timezone.utc)},
                        "$unset": {"additionalInformation.SaldoDevedor": ""},
                    }
                )

            saida.append({
                "cpf": cpf,
                "certificate": certificate,
                "protocol": notif.get("protocol"),
                "balanceDue": saldo,
                "claimAtualizado": claim_number is not None,
                "status": "Atualizado",
            })
        else:
            db["Notification"].update_one(
                {"_id": notif_id},
                {
                    "$set": {"additionalInformation.balanceDue": None, "UpdatedAt": datetime.now(timezone.utc)},
                    "$unset": {"additionalInformation.SaldoDevedor": ""},
                }
            )

            if claim_number is not None:
                db["Claim"].update_one(
                    {"flowId": flow_id},
                    {
                        "$set": {"additionalInformation.balanceDue": None, "UpdatedAt": datetime.now(timezone.utc)},
                        "$unset": {"additionalInformation.SaldoDevedor": ""},
                    }
                )

            saida.append({
                "cpf": cpf,
                "certificate": certificate,
                "protocol": notif.get("protocol"),
                "balanceDue": None,
                "claimAtualizado": claim_number is not None,
                "status": "Sem match - balanceDue null",
            })

    return saida


def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    # Ler planilha de CPFs: colunas certificate + insured.documentNumber
    df_cpfs = pd.read_excel(PLANILHA_CPFS, dtype=str)
    df_cpfs["insured.documentNumber"] = df_cpfs["insured.documentNumber"].astype(str).str.strip()
    df_cpfs["certificate"] = df_cpfs["certificate"].astype(str).str.strip()

    # cpf -> set de certificates normalizados (sem zero a esquerda)
    # certificate vazio ('') e valido e deve ser processado
    cpf_certificados = {}
    for _, row in df_cpfs.iterrows():
        cpf = row["insured.documentNumber"]
        raw = str(row["certificate"] or "").strip()
        # nan da planilha vira vazio
        cert = "" if raw.lower() == "nan" else norm(row["certificate"])
        if cpf not in cpf_certificados:
            cpf_certificados[cpf] = set()
        cpf_certificados[cpf].add(cert)

    cpfs = list(cpf_certificados.keys())
    print(f"CPFs na planilha: {len(cpfs)}")

    # Ler planilha analítico e montar mapa: cpf -> {contrato: saldo}
    df_analitico = pd.read_excel(PLANILHA_ANALITICO, dtype=str)
    df_analitico["CPF Segurado"] = df_analitico["CPF Segurado"].astype(str).str.strip()
    df_analitico["Num Contrato"] = df_analitico["Num Contrato"].astype(str).str.strip()
    df_analitico["Saldo Devedor"] = df_analitico["Saldo Devedor"].astype(str).str.strip()

    # Mapa: cpf -> dict de {contrato_normalizado: saldo_devedor}
    cpf_saldo_map = {}
    for _, row in df_analitico.iterrows():
        cpf = row["CPF Segurado"]
        raw_contrato = str(row["Num Contrato"] or "").strip()
        contrato = "" if raw_contrato.lower() == "nan" else norm(row["Num Contrato"])
        saldo = row["Saldo Devedor"]

        if cpf not in cpf_saldo_map:
            cpf_saldo_map[cpf] = {}

        cpf_saldo_map[cpf][contrato] = saldo

    resultados = []
    lock = threading.Lock()
    processados = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                processar_cpf,
                db,
                cpf,
                cpf_saldo_map.get(cpf, {}),
                cpf_certificados.get(cpf, set()),
            ): cpf
            for cpf in cpfs
        }

        for future in tqdm(as_completed(futures), total=len(futures), desc="Processando CPFs", unit="cpf"):
            saida = future.result()
            with lock:
                resultados.extend(saida)
                processados += 1
                # Salvar progresso a cada 25 CPFs
                if processados % 25 == 0:
                    pd.DataFrame(resultados).to_excel(OUTPUT_FILE, index=False, engine="openpyxl")

    # Salvar final
    pd.DataFrame(resultados).to_excel(OUTPUT_FILE, index=False, engine="openpyxl")

    client.close()

    df_final = pd.DataFrame(resultados)
    atualizados = len(df_final[df_final["status"] == "Atualizado"])
    sem_match = len(df_final[df_final["status"] != "Atualizado"])

    print(f"\nFinalizado!")
    print(f"  CPFs processados: {len(cpfs)}")
    print(f"  Notifications atualizadas com saldo: {atualizados}")
    print(f"  Notifications sem match (null): {sem_match}")
    print(f"  Excel: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
