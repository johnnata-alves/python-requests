import os
from dotenv import load_dotenv
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
DB_NAME = "SinistrosMicroService"

client = MongoClient(MONGO_URI)
db = client[DB_NAME]

avisos = db["AvisoSinistro"]
anexos = db["AvisoSinistroAnexo"]
timeline = db["SinistroTimeline"]

DETALHE_SINISTRO_URL = "http://i4pro.tooseguros.com.br/i4protoo_prd/erpws/run/Sinistro/ConsultaDetalheSinistro"
DETALHE_SINISTRO_HEADERS = {
    "clientId": os.getenv("I4PRO_CLIENT_ID"),
    "clientSecret": os.getenv("I4PRO_CLIENT_SECRET"),
    "Content-Type": "application/json"
}
DATA_CORTE_TIMELINE = datetime.fromisoformat("2026-02-15T03:00:00+03:00")
LIMITE_RELATORIO = 500
MAX_WORKERS_AVISOS = 10
MAX_WORKERS_SINISTROS = 10
CODIGOS_SITUACAO_VALIDOS = {"426", "454", "455", "456"}
ARQUIVO_PROTOCOLOS_PENDENTES = "ProtocolosPendentesDocs500.xlsx"

def console_log(mensagem, contador):
    print(f"[{contador}/{LIMITE_RELATORIO}] {mensagem}")

def normalizar_protocolo(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).strip()
    if texto.endswith(".0") and texto[:-2].isdigit():
        texto = texto[:-2]
    return texto

def carregar_protocolos_pendentes(caminho_arquivo):
    protocolos = set()
    try:
        workbook = load_workbook(caminho_arquivo, read_only=True, data_only=True)
    except FileNotFoundError:
        console_log(
            f"Planilha {caminho_arquivo} nao encontrada. Nenhum protocolo sera pulado por planilha.",
            0
        )
        return protocolos
    except Exception as erro:
        console_log(
            f"Falha ao ler planilha {caminho_arquivo}: {erro}. Nenhum protocolo sera pulado por planilha.",
            0
        )
        return protocolos

    try:
        sheet = workbook.active
        rows_iterator = sheet.iter_rows(values_only=True)
        primeira_linha = next(rows_iterator, None)

        if primeira_linha is None:
            return protocolos

        indice_protocolo = None
        for indice, valor_coluna in enumerate(primeira_linha):
            if "protocolo" in str(valor_coluna or "").strip().lower():
                indice_protocolo = indice
                break

        if indice_protocolo is not None:
            for linha in rows_iterator:
                if linha is None or indice_protocolo >= len(linha):
                    continue
                protocolo = normalizar_protocolo(linha[indice_protocolo])
                if protocolo:
                    protocolos.add(protocolo)
        else:
            protocolo_primeira_linha = normalizar_protocolo(primeira_linha[0] if primeira_linha else None)
            if protocolo_primeira_linha:
                protocolos.add(protocolo_primeira_linha)

            for linha in rows_iterator:
                if not linha:
                    continue
                protocolo = normalizar_protocolo(linha[0])
                if protocolo:
                    protocolos.add(protocolo)
    finally:
        workbook.close()

    return protocolos

def consultar_detalhe_sinistro(num_sinistro):
    payload = {
        "numSinistro": str(num_sinistro),
        "dvUserAdmin": True
    }

    try:
        response = requests.post(
            DETALHE_SINISTRO_URL,
            headers=DETALHE_SINISTRO_HEADERS,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException as erro:
        return {"erro": f"Erro ao consultar sinistro {num_sinistro}: {erro}"}

def consultar_sinistro_status_alvo(num_sinistro):
    detalhe_sinistro = consultar_detalhe_sinistro(num_sinistro)
    if not detalhe_sinistro:
        return {"num_sinistro": str(num_sinistro), "status_alvo": False, "mensagem": "Sem retorno da consulta"}

    if detalhe_sinistro.get("erro"):
        return {"num_sinistro": str(num_sinistro), "status_alvo": False, "mensagem": detalhe_sinistro.get("erro")}

    if detalhe_sinistro.get("cd_retorno") != 0:
        return {
            "num_sinistro": str(num_sinistro),
            "status_alvo": False,
            "mensagem": f"cd_retorno {detalhe_sinistro.get('cd_retorno')}"
        }

    codigo_situacao = detalhe_sinistro.get("regulacao", {}).get("codigoSituacao")
    return {
        "num_sinistro": str(num_sinistro),
        "status_alvo": str(codigo_situacao) in CODIGOS_SITUACAO_VALIDOS,
        "mensagem": f"codigoSituacao {codigo_situacao}"
    }

def avaliar_aviso(aviso, indice_aviso):
    protocolo = normalizar_protocolo(aviso.get("Protocolo"))
    if not protocolo:
        return {
            "valido": False,
            "indice": indice_aviso,
            "protocolo": protocolo,
            "motivo": "protocolo invalido"
        }

    if protocolo in protocolos_pendentes_planilha:
        return {
            "valido": False,
            "indice": indice_aviso,
            "protocolo": protocolo,
            "motivo": f"protocolo presente na planilha {ARQUIVO_PROTOCOLOS_PENDENTES}"
        }

    sinistros = aviso.get("Sinistros", [])
    if not sinistros:
        return {
            "valido": False,
            "indice": indice_aviso,
            "protocolo": protocolo,
            "motivo": "sem sinistros no aviso"
        }

    sinistros_status_alvo = []
    mensagens = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS_SINISTROS) as executor_sinistros:
        futuros_sinistros = {
            executor_sinistros.submit(consultar_sinistro_status_alvo, num_sinistro): num_sinistro
            for num_sinistro in sinistros
        }

        for futuro_sinistro in as_completed(futuros_sinistros):
            resultado_sinistro = futuro_sinistro.result()
            mensagens.append(
                f"sinistro {resultado_sinistro['num_sinistro']}: {resultado_sinistro['mensagem']}"
            )
            if resultado_sinistro.get("status_alvo"):
                sinistros_status_alvo.append(resultado_sinistro["num_sinistro"])

    if len(sinistros_status_alvo) != 1:
        return {
            "valido": False,
            "indice": indice_aviso,
            "protocolo": protocolo,
            "motivo": (
                f"quantidade de sinistros com situacao 426/454/455/456 = "
                f"{len(sinistros_status_alvo)}"
            ),
            "mensagens": mensagens
        }

    ja_notificado = timeline.find_one(
        {
            "Protocolo": protocolo,
            "Codigo": "426",
            "DataEvento": {"$gt": DATA_CORTE_TIMELINE},
            "NotificaParceiro": True,
            "ParceiroNotificado": True
        }
    )

    if ja_notificado:
        return {
            "valido": False,
            "indice": indice_aviso,
            "protocolo": protocolo,
            "motivo": "ja possui timeline 426 notificada apos data de corte",
            "mensagens": mensagens
        }

    ultimo_timeline = timeline.find_one(
        {"Protocolo": protocolo, "Codigo": "426"},
        sort=[("_id", -1)]
    )

    if not ultimo_timeline:
        return {
            "valido": False,
            "indice": indice_aviso,
            "protocolo": protocolo,
            "motivo": "nao foi encontrado timeline 426 para atualizacao",
            "mensagens": mensagens
        }

    return {
        "valido": True,
        "indice": indice_aviso,
        "protocolo": protocolo,
        "timeline_id": ultimo_timeline["_id"],
        "aviso": aviso,
        "sinistro_status_alvo": sinistros_status_alvo[0],
        "mensagens": mensagens
    }

filtro_avisos = {
    "InformacoesComplementares.origemdocumento": re.compile("V4", re.IGNORECASE),
    "CnpjEstipulante": "59285411000113",
    "Criacao": {
        "$gt": datetime(2025, 6, 1, tzinfo=timezone.utc)
    }
}

relatorio = []
protocolos_relatorio = set()
contador_registros = 0
protocolos_pendentes_planilha = carregar_protocolos_pendentes(ARQUIVO_PROTOCOLOS_PENDENTES)

console_log("Iniciando reprocessamento de protocolos pendentes", contador_registros)
console_log(
    f"Protocolos carregados da planilha para pular: {len(protocolos_pendentes_planilha)}",
    contador_registros
)

avisos_lista = list(avisos.find(filtro_avisos))
console_log(f"Total de avisos encontrados: {len(avisos_lista)}", contador_registros)

with ThreadPoolExecutor(max_workers=MAX_WORKERS_AVISOS) as executor_avisos:
    futuros_avisos = {
        executor_avisos.submit(avaliar_aviso, aviso, indice_aviso): indice_aviso
        for indice_aviso, aviso in enumerate(avisos_lista, start=1)
    }

    for futuro_aviso in as_completed(futuros_avisos):
        if contador_registros >= LIMITE_RELATORIO:
            break

        resultado_aviso = futuro_aviso.result()
        protocolo = resultado_aviso.get("protocolo")
        indice = resultado_aviso.get("indice")

        for mensagem in resultado_aviso.get("mensagens", []):
            console_log(f"Aviso {indice} / Protocolo {protocolo}: {mensagem}", contador_registros)

        if not resultado_aviso.get("valido"):
            console_log(
                f"Aviso {indice} / Protocolo {protocolo}: {resultado_aviso.get('motivo')}. Pulando",
                contador_registros
            )
            continue

        if protocolo in protocolos_relatorio:
            console_log(f"Aviso {indice} / Protocolo {protocolo}: protocolo ja processado, pulando", contador_registros)
            continue

        timeline.update_one(
            {"_id": resultado_aviso["timeline_id"]},
            {
                "$set": {
                    "NotificaParceiro": True,
                    "ParceiroNotificado": False,
                    "Processado": False,
                    "DataEvento": datetime.now(timezone.utc)
                }
            }
        )

        aviso = resultado_aviso["aviso"]
        relatorio.append({
            "Protocolo": protocolo,
            "CpfCnpj": aviso.get("Segurado", {}).get("CpfCnpj"),
            "Ocorrencia": aviso.get("Ocorrencia"),
            "DataDoAviso": aviso.get("DataDoAviso")
        })
        protocolos_relatorio.add(protocolo)
        contador_registros += 1

        console_log(
            f"Aviso {indice} / Protocolo {protocolo}: timeline atualizada "
            f"(sinistro com status elegivel: {resultado_aviso['sinistro_status_alvo']})",
            contador_registros
        )

workbook = Workbook()
sheet = workbook.active
sheet.title = "Notificados"

headers = ["Protocolo", "CpfCnpj", "Ocorrencia", "DataDoAviso"]
sheet.append(headers)

header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
header_font = Font(color="FFFFFF", bold=True)

for col_idx, header in enumerate(headers, start=1):
    cell = sheet.cell(row=1, column=col_idx, value=header)
    cell.fill = header_fill
    cell.font = header_font
    cell.alignment = Alignment(horizontal="center", vertical="center")

for item in relatorio:
    data_aviso = item.get("DataDoAviso")
    if isinstance(data_aviso, str):
        try:
            data_aviso = datetime.fromisoformat(data_aviso.replace("Z", "+00:00"))
        except ValueError:
            pass

    sheet.append([
        item.get("Protocolo"),
        item.get("CpfCnpj"),
        item.get("Ocorrencia"),
        data_aviso,
    ])

for row in sheet.iter_rows(min_row=2, max_row=sheet.max_row):
    row[3].alignment = Alignment(horizontal="center")
    if isinstance(row[3].value, datetime):
        row[3].number_format = "DD/MM/YYYY HH:MM:SS"

sheet.freeze_panes = "A2"

for column in sheet.columns:
    max_length = 0
    column_letter = column[0].column_letter
    for cell in column:
        value = "" if cell.value is None else str(cell.value)
        if len(value) > max_length:
            max_length = len(value)
    sheet.column_dimensions[column_letter].width = min(max_length + 2, 60)

workbook.save("relatorio_protocolos_notificados.xlsx")

console_log(f"Total notificados: {len(relatorio)}", contador_registros)

if len(relatorio) < LIMITE_RELATORIO:
    console_log(
        f"Nao foi possivel atingir {LIMITE_RELATORIO} protocolos diferentes com os filtros atuais.",
        contador_registros
    )
