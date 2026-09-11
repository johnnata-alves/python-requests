"""
Abordagem em 2 etapas:
1) Baixa TODOS os logs do Grafana das últimas 12h (hora a hora) sem filtro de CPF
   e salva em /logs
2) Processa Notifications com additionalInformation.SaldoDevedor cruzando com os logs salvos
"""

import json
import os
import re
import time
import warnings
from collections import defaultdict
from datetime import datetime, timezone, timedelta

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

LOGS_DIR = "logs"
OUTPUT_FILE = "resultado_saldo_devedor_grafana_v2.xlsx"
DATA_CORTE = datetime(2026, 8, 21, 0, 0, 0)

# Janela de 6h, intervalos de 20min
HORAS_ATRAS = 6
INTERVALO_MS = 20 * 60 * 1000  # 20 minutos em ms


def query_grafana_hora(from_ms, to_ms):
    """Consulta Grafana sem filtro de CPF, só pelo path da API."""
    expr = (
        '{namespace="sinistro"} '
        '|= `sinistro-api.sinistro.svc.cluster.local/api/v4/Sinistros/avisar-sinistro`'
        ' |= `saldodevedorum`'
    )

    payload = {
        "queries": [{
            "refId": "A",
            "expr": expr,
            "queryType": "range",
            "datasource": {"type": "loki", "uid": "a1af6522-d8ae-419e-8c89-d35d32298c5b"},
            "editorMode": "builder",
            "maxLines": 5000,
            "legendFormat": "",
            "datasourceId": 2,
            "intervalMs": 2000,
            "maxDataPoints": 1780,
        }],
        "from": str(from_ms),
        "to": str(to_ms),
    }

    headers = {
        "Content-Type": "application/json",
        "accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {GRAFANA_TOKEN}",
        "x-datasource-uid": "a1af6522-d8ae-419e-8c89-d35d32298c5b",
        "x-grafana-org-id": "1",
        "x-plugin-id": "loki",
    }

    resp = requests.post(GRAFANA_URL, headers=headers, json=payload, timeout=120, verify=False)
    resp.raise_for_status()
    return resp.json()


def extrair_contratos_do_log(line):
    """Extrai cpf, contratoum, saldodevedorum de uma linha de log."""
    clean = line.replace("\\\\\\\\", "").replace("\\\\\\\"", '"').replace('\\\\\\"', '"').replace('\\"', '"').replace("\\\\", "")

    # CPF do segurado
    cpf_match = re.search(r'"segurado"\s*:\s*\{[^}]*"cpfCnpj"\s*:\s*"(\d+)"', clean)
    cpf = cpf_match.group(1) if cpf_match else None

    # saldodevedorum e contratoum
    info_match = re.search(
        r'"saldodevedorum"\s*:\s*"([^"]+)"\s*,\s*"contratoum"\s*:\s*"([^"]+)"',
        clean, re.IGNORECASE
    )

    if cpf and info_match:
        return {
            "cpf": cpf,
            "saldodevedorum": info_match.group(1).strip(),
            "contratoum": info_match.group(2).strip(),
        }
    return None


def etapa1_baixar_logs():
    """Baixa logs do Grafana a cada 20min e salva em /logs. Retoma de onde parou."""
    os.makedirs(LOGS_DIR, exist_ok=True)

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = now_ms - (HORAS_ATRAS * 3600 * 1000)

    # Gerar todos os intervalos de 20min
    intervalos = []
    current = start_ms
    while current < now_ms:
        intervalos.append((current, min(current + INTERVALO_MS, now_ms)))
        current += INTERVALO_MS

    # Verificar quais já foram baixados
    existentes = set(os.listdir(LOGS_DIR))
    pendentes = []
    for from_ms, to_ms in intervalos:
        filename = f"{from_ms}_{to_ms}.json"
        if filename not in existentes:
            pendentes.append((from_ms, to_ms))

    print(f"Etapa 1: {len(intervalos)} intervalos de 20min | Já baixados: {len(intervalos) - len(pendentes)} | Pendentes: {len(pendentes)}")

    if not pendentes:
        print("  Todos os logs já foram baixados.")
        return

    total_lines = 0

    for from_ms, to_ms in tqdm(pendentes, desc="Baixando logs", unit="intervalo"):
        from_dt = datetime.fromtimestamp(from_ms / 1000, tz=timezone.utc).strftime("%H:%M")
        to_dt = datetime.fromtimestamp(to_ms / 1000, tz=timezone.utc).strftime("%H:%M")

        try:
            data = query_grafana_hora(from_ms, to_ms)

            lines = []
            frames = data.get("results", {}).get("A", {}).get("frames", [])
            for frame in frames:
                values = frame.get("data", {}).get("values", [])
                if len(values) > 2:
                    lines.extend(values[2])

            filename = os.path.join(LOGS_DIR, f"{from_ms}_{to_ms}.json")
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(lines, f, ensure_ascii=False)

            total_lines += len(lines)
            print(f"  [{from_dt} - {to_dt} UTC] OK - {len(lines)} linhas")

        except Exception as e:
            print(f"  [{from_dt} - {to_dt} UTC] ERRO: {e}")

        time.sleep(1)

    print(f"  Total de linhas baixadas nesta execução: {total_lines}")


def etapa2_processar():
    """Lê logs salvos, monta mapa CPF+contrato -> saldo, atualiza Notifications."""
    print("\nEtapa 2: Processando logs salvos...")

    # Ler todos os logs
    cpf_contrato_map = defaultdict(dict)  # cpf -> {contrato: saldo}

    log_files = sorted([f for f in os.listdir(LOGS_DIR) if f.endswith(".json")])
    if not log_files:
        print("  Nenhum log encontrado na pasta /logs")
        return

    total_extraidos = 0
    for filename in tqdm(log_files, desc="Lendo logs", unit="arquivo"):
        filepath = os.path.join(LOGS_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            lines = json.load(f)

        for line in lines:
            item = extrair_contratos_do_log(line)
            if item:
                cpf = item["cpf"]
                contrato = item["contratoum"]
                contrato_sem_zero = contrato.lstrip("0")
                saldo = item["saldodevedorum"]
                cpf_contrato_map[cpf][contrato] = saldo
                cpf_contrato_map[cpf][contrato_sem_zero] = saldo
                total_extraidos += 1

    print(f"  CPFs únicos nos logs: {len(cpf_contrato_map)}")
    print(f"  Contratos extraídos: {total_extraidos}")

    # Buscar Notifications pendentes
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    filtro = {
        "notificationOrigin": {"$regex": "v5", "$options": "i"},
        "occurrenceDescription": "Abertura de Sinistro para Cobertura de Óbito PAN",
        "notificationDate": {"$gt": DATA_CORTE},
        "additionalInformation.SaldoDevedor": {"$exists": True},
    }

    notifications = list(db["Notification"].find(filtro))
    print(f"  Notifications pendentes: {len(notifications)}")

    if not notifications:
        print("  Nada para processar.")
        client.close()
        return

    resultados = []

    for notif in tqdm(notifications, desc="Atualizando", unit="doc"):
        cpf = (notif.get("insured") or {}).get("documentNumber", "")
        certificate = str(notif.get("certificate") or "").strip()
        certificate_sem_zero = certificate.lstrip("0")
        notif_id = notif["_id"]

        contrato_map = cpf_contrato_map.get(cpf, {})

        if not contrato_map:
            # CPF não encontrado nos logs - não mexe
            resultados.append({
                "cpf": cpf,
                "certificate": certificate,
                "protocol": notif.get("protocol"),
                "balanceDue": None,
                "status": "CPF não encontrado nos logs",
            })
            continue

        # Tentar match pelo certificate
        saldo = contrato_map.get(certificate) or contrato_map.get(certificate_sem_zero)

        if saldo:
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
            # CPF existe nos logs mas certificate não bate - limpa SaldoDevedor
            db["Notification"].update_one(
                {"_id": notif_id},
                {
                    "$set": {"additionalInformation.balanceDue": None},
                    "$unset": {"additionalInformation.SaldoDevedor": ""},
                }
            )
            resultados.append({
                "cpf": cpf,
                "certificate": certificate,
                "protocol": notif.get("protocol"),
                "balanceDue": None,
                "status": "Sem match de certificate",
            })

    client.close()

    # Exportar Excel
    df = pd.DataFrame(resultados)
    df.to_excel(OUTPUT_FILE, index=False, engine="openpyxl")

    atualizados = len([r for r in resultados if r["status"] == "Atualizado"])
    print(f"\nFinalizado!")
    print(f"  Total notifications: {len(notifications)}")
    print(f"  Atualizados: {atualizados}")
    print(f"  Excel: {OUTPUT_FILE}")


def main():
    etapa1_baixar_logs()
    etapa2_processar()


if __name__ == "__main__":
    main()
