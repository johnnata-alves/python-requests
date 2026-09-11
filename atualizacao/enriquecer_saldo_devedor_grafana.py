"""
Busca Notifications com SaldoDevedor pendente,
consulta Grafana/Loki por CPF para extrair contratoum + saldodevedorum,
cruza com certificate da Notification e atualiza additionalInformation.balanceDue.
Salva progresso em Excel a cada CPF processado.
"""

import json
import os
import re
import time
import warnings
from collections import defaultdict
from datetime import datetime, timedelta

import pandas as pd
import requests
import urllib3
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
DB_NAME = "ClaimEngine"

GRAFANA_URL = "https://grafana.prd.tooseguros.com.br/api/ds/query?ds_type=loki&requestId=explore_b2c_1"
GRAFANA_TOKEN = os.getenv("GRAFANA_TOKEN", "")

MARGIN_MINUTES = 5

MAX_RETRIES = 3
RETRY_DELAY = 5
OUTPUT_FILE = "resultado_saldo_devedor_grafana.xlsx"

# Data de corte no mongo
DATA_CORTE = datetime(2026, 8, 21, 0, 0, 0)


def get_grafana_range(created_at):
    """Calcula from/to em milissegundos a partir do CreatedAt com margem de 5 min."""
    from_dt = created_at - timedelta(minutes=MARGIN_MINUTES)
    to_dt = created_at + timedelta(minutes=MARGIN_MINUTES)
    from_ms = str(int(from_dt.timestamp() * 1000))
    to_ms = str(int(to_dt.timestamp() * 1000))
    return from_ms, to_ms


def query_grafana(cpf, grafana_from, grafana_to):
    """Consulta Grafana/Loki pelo CPF e retorna lista de {contratoum, saldodevedorum}."""
    expr = (
        f'{{namespace="sinistro"}} |= `{cpf}` '
        f'|= `sinistro-api.sinistro.svc.cluster.local/api/v4/Sinistros/avisar-sinistro`'
    )

    payload = {
        "queries": [{
            "refId": "A",
            "expr": expr,
            "queryType": "range",
            "datasource": {"type": "loki", "uid": "a1af6522-d8ae-419e-8c89-d35d32298c5b"},
            "editorMode": "builder",
            "maxLines": 1000,
            "legendFormat": "",
            "datasourceId": 2,
            "intervalMs": 2000,
            "maxDataPoints": 1780,
        }],
        "from": grafana_from,
        "to": grafana_to,
    }

    headers = {
        "Content-Type": "application/json",
        "accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {GRAFANA_TOKEN}",
        "x-datasource-uid": "a1af6522-d8ae-419e-8c89-d35d32298c5b",
        "x-grafana-org-id": "1",
        "x-plugin-id": "loki",
    }

    resp = requests.post(GRAFANA_URL, headers=headers, json=payload, timeout=60, verify=False)
    resp.raise_for_status()
    data = resp.json()

    # Parse response
    contratos = []
    try:
        frames = data.get("results", {}).get("A", {}).get("frames", [])
        for frame in frames:
            values = frame.get("data", {}).get("values", [])
            lines = values[2] if len(values) > 2 else []
            for line in lines:
                # Remover escapes pra facilitar extração
                clean = line.replace("\\\\\\\\", "").replace("\\\\\\\"", '"').replace('\\\\\\"', '"').replace('\\"', '"').replace("\\\\", "")
                # Buscar saldodevedorum e contratoum
                matches = re.findall(
                    r'"saldodevedorum"\s*:\s*"([^"]+)"\s*,\s*"contratoum"\s*:\s*"([^"]+)"',
                    clean, re.IGNORECASE
                )
                for saldo, contrato in matches:
                    contratos.append({
                        "contratoum": contrato.strip(),
                        "saldodevedorum": saldo.strip(),
                    })
    except Exception:
        pass

    return contratos


def query_grafana_with_retry(cpf, grafana_from, grafana_to):
    """Consulta Grafana com retry."""
    for attempt in range(MAX_RETRIES):
        try:
            result = query_grafana(cpf, grafana_from, grafana_to)
            if result:
                return result
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                return []
    return []


def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    # Buscar Notifications pendentes (SaldoDevedor existe = não processado)
    filtro = {
        "notificationOrigin": {"$regex": "v5", "$options": "i"},
        "occurrenceDescription": "Abertura de Sinistro para Cobertura de Óbito PAN",
        "notificationDate": {"$gt": DATA_CORTE},
        "additionalInformation.SaldoDevedor": {"$exists": True},
    }

    notifications = list(db["Notification"].find(filtro))
    print(f"Notifications pendentes: {len(notifications)}")

    if not notifications:
        print("Nada para processar.")
        client.close()
        return

    # Agrupar por CPF (guardar CreatedAt para range do Grafana)
    cpf_groups = defaultdict(list)
    for notif in notifications:
        cpf = (notif.get("insured") or {}).get("documentNumber", "")
        if cpf:
            cpf_groups[cpf].append(notif)

    print(f"CPFs únicos: {len(cpf_groups)}")

    # Carregar progresso anterior se existir
    resultados = []
    if os.path.exists(OUTPUT_FILE):
        df_existing = pd.read_excel(OUTPUT_FILE)
        resultados = df_existing.to_dict("records")

    for cpf in tqdm(cpf_groups, total=len(cpf_groups), desc="Processando CPFs", unit="cpf"):
        notifs = cpf_groups[cpf]

        # Usar CreatedAt da primeira notification para calcular range do Grafana
        created_at = notifs[0].get("CreatedAt") or notifs[0].get("createdAt")
        if not created_at:
            for notif in notifs:
                resultados.append({
                    "cpf": cpf,
                    "certificate": str(notif.get("certificate") or "").strip(),
                    "protocol": notif.get("protocol"),
                    "balanceDue": None,
                    "status": "Sem CreatedAt - não processado",
                })
            df = pd.DataFrame(resultados)
            df.to_excel(OUTPUT_FILE, index=False, engine="openpyxl")
            continue

        grafana_from, grafana_to = get_grafana_range(created_at)

        # Consultar Grafana
        contratos_grafana = query_grafana_with_retry(cpf, grafana_from, grafana_to)

        # Se Grafana não retornou nada, pular esse CPF (não atualiza)
        if not contratos_grafana:
            for notif in notifs:
                resultados.append({
                    "cpf": cpf,
                    "certificate": str(notif.get("certificate") or "").strip(),
                    "protocol": notif.get("protocol"),
                    "balanceDue": None,
                    "status": "Grafana sem resultados - não processado",
                })
            # Salvar progresso
            df = pd.DataFrame(resultados)
            df.to_excel(OUTPUT_FILE, index=False, engine="openpyxl")
            continue

        # Montar mapa contrato -> saldo (com e sem zeros à esquerda)
        contrato_saldo_map = {}
        for item in contratos_grafana:
            contrato = item["contratoum"]
            contrato_saldo_map[contrato] = item["saldodevedorum"]
            contrato_saldo_map[contrato.lstrip("0")] = item["saldodevedorum"]

        # Cruzar com Notifications
        for notif in notifs:
            certificate = str(notif.get("certificate") or "").strip()
            notif_id = notif["_id"]

            if certificate in contrato_saldo_map or certificate.lstrip("0") in contrato_saldo_map:
                # Match: atualizar balanceDue com saldodevedorum e remover SaldoDevedor
                saldo = contrato_saldo_map.get(certificate) or contrato_saldo_map.get(certificate.lstrip("0"))
                db["Notification"].update_one(
                    {"_id": notif_id},
                    {
                        "$set": {"additionalInformation.balanceDue": saldo},
                        "$unset": {"additionalInformation.SaldoDevedor": ""},
                    }
                )
                resultados.append({
                    "cpf": cpf,
                    "certificate": certificate,
                    "protocol": notif.get("protocol"),
                    "balanceDue": saldo,
                    "status": "Atualizado",
                })
            else:
                # Sem match no Grafana: remover SaldoDevedor, balanceDue = null
                db["Notification"].update_one(
                    {"_id": notif_id},
                    {
                        "$set": {"additionalInformation.balanceDue": None},
                        "$unset": {"additionalInformation.SaldoDevedor": ""},
                    }
                )
                status_msg = "Sem match no Grafana" if contratos_grafana else "Grafana sem resultados"
                resultados.append({
                    "cpf": cpf,
                    "certificate": certificate,
                    "protocol": notif.get("protocol"),
                    "balanceDue": None,
                    "status": status_msg,
                })

        # Salvar progresso a cada CPF
        df = pd.DataFrame(resultados)
        df.to_excel(OUTPUT_FILE, index=False, engine="openpyxl")

    client.close()

    # Resumo
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
