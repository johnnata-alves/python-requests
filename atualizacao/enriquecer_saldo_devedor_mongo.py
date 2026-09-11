"""
Busca Notifications com SaldoDevedor pendente,
consulta SinistrosMicroService.AvisoSinistroExternalNotification por CPF
para extrair contrato + saldo devedor via InformacoesComplementares,
cruza com certificate da Notification e atualiza additionalInformation.balanceDue.
Salva progresso em Excel a cada CPF processado.
"""

import os
import warnings
from collections import defaultdict
from datetime import datetime

import pandas as pd
import urllib3
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
MONGO_SINISTROS_URI = os.getenv("PRD_MONGO_SA_EAST", MONGO_URI)

DB_CLAIM_ENGINE = "ClaimEngine"
DB_SINISTROS = "SinistrosMicroService"

OUTPUT_FILE = "resultado_saldo_devedor_mongo.xlsx"
DATA_CORTE = datetime(2026, 8, 21, 0, 0, 0)


def buscar_contratos_sinistros(db_sinistros, cpf):
    """
    Busca na collection AvisoSinistroExternalNotification pelo CPF.
    Retorna mapa {contrato: saldo_devedor} extraído de InformacoesComplementares.
    """
    filtro = {"ClaimNotification.Insured.DocumentNumber": cpf}
    registros = list(db_sinistros["AvisoSinistroExternalNotification"].find(filtro))

    if not registros:
        return {}

    contrato_saldo_map = {}

    for reg in registros:
        aviso = reg.get("AvisoSinisto") or {}
        infos = aviso.get("InformacoesComplementares") or []

        # Extrair saldo devedor (primeiro valor numérico) e contrato (valor string numérico)
        saldo = None
        contrato = None

        for info in infos:
            valor = info.get("Valor")
            if valor is None:
                continue

            # Saldo devedor: valor numérico (float/int)
            if isinstance(valor, (int, float)):
                saldo = str(valor)

            # Contrato: valor string que é puramente numérico
            if isinstance(valor, str) and valor.isdigit():
                contrato = valor

        if contrato and saldo:
            contrato_saldo_map[contrato] = saldo
            contrato_saldo_map[contrato.lstrip("0")] = saldo

    return contrato_saldo_map


def main():
    client_ce = MongoClient(MONGO_URI)
    client_sin = MongoClient(MONGO_SINISTROS_URI)

    db_ce = client_ce[DB_CLAIM_ENGINE]
    db_sin = client_sin[DB_SINISTROS]

    filtro = {
        "notificationOrigin": {"$regex": "v5", "$options": "i"},
        "occurrenceDescription": "Abertura de Sinistro para Cobertura de Óbito PAN",
        # "protocol": "11202682104827861",
        "notificationDate": {"$gt": DATA_CORTE},
        "$or": [
            {"additionalInformation.balanceDue": {"$exists": False}},
            {"additionalInformation.balanceDue": None},
        ],
    }

    notifications = list(db_ce["Notification"].find(filtro))
    print(f"Notifications pendentes: {len(notifications)}")

    if not notifications:
        print("Nada para processar.")
        client_ce.close()
        client_sin.close()
        return

    cpf_groups = defaultdict(list)
    for notif in notifications:
        cpf = (notif.get("insured") or {}).get("documentNumber", "")
        if cpf:
            cpf_groups[cpf].append(notif)

    print(f"CPFs únicos: {len(cpf_groups)}")

    resultados = []
    if os.path.exists(OUTPUT_FILE):
        try:
            df_existing = pd.read_excel(OUTPUT_FILE, engine="openpyxl")
            resultados = df_existing.to_dict("records")
        except Exception as e:
            print(f"Ignorando {OUTPUT_FILE} invalido/corrompido: {e}")
            resultados = []

    for cpf in tqdm(cpf_groups, total=len(cpf_groups), desc="Processando CPFs", unit="cpf"):
        notifs = cpf_groups[cpf]

        # Buscar na collection de sinistros
        contrato_saldo_map = buscar_contratos_sinistros(db_sin, cpf)

        # Sem registros para esse CPF: pular, não atualiza nada
        if not contrato_saldo_map:
            for notif in notifs:
                resultados.append({
                    "cpf": cpf,
                    "certificate": str(notif.get("certificate") or "").strip(),
                    "protocol": notif.get("protocol"),
                    "balanceDue": None,
                    "status": "CPF não encontrado em Sinistros - não processado",
                })
            df = pd.DataFrame(resultados)
            df.to_excel(OUTPUT_FILE, index=False, engine="openpyxl")
            continue

        # Cruzar com Notifications
        for notif in notifs:
            certificate = str(notif.get("certificate") or "").strip()
            notif_id = notif["_id"]
            flow_id = notif.get("flowId")

            match = contrato_saldo_map.get(certificate) or contrato_saldo_map.get(certificate.lstrip("0"))

            saldo_final = match if match else None

            db_ce["Notification"].update_one(
                {"_id": notif_id},
                {
                    "$set": {"additionalInformation.balanceDue": saldo_final},
                    "$unset": {"additionalInformation.SaldoDevedor": ""},
                }
            )

            # Atualizar Claim pelo flowId, se houver
            claim_atualizado = False
            if flow_id:
                res_claim = db_ce["Claim"].update_one(
                    {"flowId": flow_id},
                    {
                        "$set": {"additionalInformation.balanceDue": saldo_final},
                        "$unset": {"additionalInformation.SaldoDevedor": ""},
                    }
                )
                claim_atualizado = res_claim.matched_count > 0

            resultados.append({
                "cpf": cpf,
                "certificate": certificate,
                "protocol": notif.get("protocol"),
                "flowId": flow_id,
                "balanceDue": saldo_final,
                "claimAtualizado": claim_atualizado,
                "status": "Atualizado" if match else "Sem match de certificado",
            })

        df = pd.DataFrame(resultados)
        df.to_excel(OUTPUT_FILE, index=False, engine="openpyxl")

    client_ce.close()
    client_sin.close()

    df_final = pd.DataFrame(resultados)
    atualizados = len(df_final[df_final["status"] == "Atualizado"])
    sem_match = len(df_final[df_final["status"] != "Atualizado"])

    print(f"\nFinalizado!")
    print(f"  CPFs processados: {len(cpf_groups)}")
    print(f"  Notifications atualizadas: {atualizados}")
    print(f"  Sem match: {sem_match}")
    print(f"  Excel: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
