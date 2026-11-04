"""
Fluxo de criacao de sinistro de teste (obito PAN) com anexos gerados.

Passos:
1. Seleciona apolices na base indexada indexed_policy_too.person
   (product_code 246, Emitida, endorsement iniciando apos 2025-01-01).
2. Para cada apolice, pega insureds.document (CPF). Se ja existir em
   ClaimEngine.Notification.insured.documentNumber, pula e tenta o proximo,
   ate achar um CPF nao usado.
3. Chama a API Notification (POST /api/v1/Notification) com os dados montados.
4. Do retorno pega o protocol.
5. Gera 2 imagens preenchidas (certidao de obito + documento de identificacao)
   via Pillow, dados faltantes preenchidos por IA (copilot).
6. Envia cada imagem como base64 em POST /api/v1/Attachment/external.

Roda 3 cenarios em paralelo (uma thread por cenario, LIMITE sinistros cada):
1) Causa natural   + ABCESSO CEREBRAL     , data ocorrencia == data obito
2) Causa acidental + ACIDENTE DE TRÂNSITO , data ocorrencia == data obito
3) Causa acidental + ACIDENTE DE TRÂNSITO , data ocorrencia != data obito

Retomavel: mantem checkpoint dos CPFs ja processados. Se parar, continua.
"""

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import json
import os
import random
import re
import threading
import time
import warnings
from datetime import date, datetime, timedelta, timezone

import requests
import urllib3
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont
from pymongo import MongoClient

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

load_dotenv()

# ------------------------------------------------------------------ Config
MONGO_INDEXED = os.getenv("HML_INDEXED_MONGO_URI")
DB_INDEXED_POLICY = os.getenv("HML_DB_INDEXED_POLICY", "indexed_policy_too")
COL_PERSON = "person"

MONGO_CLAIM = os.getenv("HML_MONGO_URI")
DB_CLAIM = os.getenv("HML_DB_CLAIM_ENGINE", "ClaimEngine")

API_BASE = os.getenv("CLAIM_ENGINE_API_STG")
API_NOTIFICATION = f"{API_BASE}/api/v1/Notification"
API_ATTACHMENT = f"{API_BASE}/api/v1/Attachment/external"

TOKEN_URL = os.getenv("KEYCLOAK_TOKEN_URL")
TOKEN_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID")
TOKEN_USERNAME = os.getenv("KEYCLOAK_USERNAME")
TOKEN_PASSWORD = os.getenv("KEYCLOAK_PASSWORD")

COPILOT_API_KEY = os.getenv("COPILOT_API_KEY")
DIRECT_LINE_BASE_URL = os.getenv(
    "DIRECT_LINE_BASE_URL", "https://directline.botframework.com/v3/directline"
)
COPILOT_MODEL = "gpt-5.1"

TEMPLATE_CERTIDAO = "certidao-de-obito.png"
TEMPLATE_RG = "carteira_identidade.jpg"

CHECKPOINT_FILE = "criar_notificacao_com_anexos.checkpoint"
LOG_CSV = "criar_notificacao_com_anexos.csv"

# quantas apolices/CPFs criar por cenario
LIMITE = int(os.getenv("LIMITE", "100"))
# quantas apolices candidatas carregar da base indexada (compartilhadas entre cenarios)
MAX_CANDIDATOS = int(os.getenv("MAX_CANDIDATOS", "1000"))
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# ------------------------------------------------------------------ Cenarios
CENARIOS = [
    {
        "nome": "natural_mesma_data",
        "cause_type": "NATURAL_CAUSE",
        "causa": "ABCESSO CEREBRAL",
        "mesma_data": True,
    },
    {
        "nome": "acidental_mesma_data",
        "cause_type": "ACCIDENTAL_CAUSE",
        "causa": "ACIDENTE DE TRÂNSITO",
        "mesma_data": True,
    },
    {
        "nome": "acidental_data_diferente",
        "cause_type": "ACCIDENTAL_CAUSE",
        "causa": "ACIDENTE DE TRÂNSITO",
        "mesma_data": False,
    },
]

# ------------------------------------------------------------------ Coordenadas
# Coordenadas ajustadas ao template certidao-de-obito.png (613x877)
CAMPOS_CERTIDAO = {
    "nome": (95, 214),        # linha "Nome" abaixo do titulo CERTIDAO DE OBITO
    "cpf": (55, 244),         # campo CPF
    "naturalidade": (60, 353),  # NATURALIDADE
    "data_obito": (55, 428),  # DATA E HORA DE FALECIMENTO
    "cidade": (55, 464),      # LOCAL DE FALECIMENTO
    "causa": (55, 502),       # CAUSA DA MORTE
}

CAMPOS_RG = {
    "rg": (90, 870),
    "data_expedicao": (600, 870),
    "nome": (90, 925),
    "filiacao": (90, 1020),
    "naturalidade": (90, 1170),
    "data_nascimento": (745, 1170),
    "documento_origem": (90, 1260),
    "cpf": (90, 1350),
}


# ------------------------------------------------------------------ Filtro indexado
def build_filtro_indexado():
    return {
        "product_code": 246,
        "policy_status": "Emitida",
        # "endorsement_current.term_start_date": {"$gt": "2025-01-01"},
    }


# ------------------------------------------------------------------ Token / API
def get_token():
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "password",
            "client_id": TOKEN_CLIENT_ID,
            "username": TOKEN_USERNAME,
            "password": TOKEN_PASSWORD,
        },
        verify=False,
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def api_headers(token):
    return {
        "x-auth-appname": "claim-engine-api",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def create_notification(payload, token):
    resp = requests.post(
        API_NOTIFICATION, json=payload, headers=api_headers(token), verify=False, timeout=1200
    )
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list):
        return data
    return [data]


def send_attachment(payload, token):
    resp = requests.post(
        API_ATTACHMENT, json=payload, headers=api_headers(token), verify=False, timeout=1200
    )
    resp.raise_for_status()
    return resp


# ------------------------------------------------------------------ IA (copilot)
def ia_gerar_dados(nome, cpf):
    """Pede a IA para inventar dados faltantes. Retorna dict.
    Se a IA falhar, usa fallback aleatorio."""
    fallback = _fallback_dados(nome, cpf)
    if not COPILOT_API_KEY:
        return fallback

    prompt = (
        "Gere dados ficticios brasileiros validos em formato JSON puro (sem markdown) "
        "para preencher documentos de teste. Use exatamente estas chaves: "
        "rg, data_expedicao, filiacao, naturalidade, data_nascimento. "
        "Formato de datas: DD/MM/AAAA. 'filiacao' = nome de mae e pai separados por ' e '. "
        f"Pessoa: nome='{nome}', cpf='{cpf}'. Responda SOMENTE o JSON."
    )
    try:
        headers = {
            "Authorization": f"Bearer {COPILOT_API_KEY}",
            "Content-Type": "application/json",
        }
        r = requests.post(
            f"{DIRECT_LINE_BASE_URL}/conversations",
            headers=headers,
            timeout=30,
            verify=False,
        )
        r.raise_for_status()
        conv = r.json()["conversationId"]

        requests.post(
            f"{DIRECT_LINE_BASE_URL}/conversations/{conv}/activities",
            headers=headers,
            json={
                "type": "message",
                "from": {"id": "notif-bot"},
                "text": prompt,
                "channelData": {"model": COPILOT_MODEL},
            },
            timeout=30,
            verify=False,
        )

        watermark = None
        for _ in range(20):
            params = {"watermark": watermark} if watermark else {}
            resp = requests.get(
                f"{DIRECT_LINE_BASE_URL}/conversations/{conv}/activities",
                headers=headers,
                params=params,
                timeout=30,
                verify=False,
            )
            resp.raise_for_status()
            payload = resp.json()
            watermark = payload.get("watermark")
            textos = [
                a["text"]
                for a in payload.get("activities", [])
                if a.get("type") == "message"
                and a.get("text")
                and a.get("from", {}).get("id", "").lower() != "notif-bot"
            ]
            if textos:
                dados = _extrair_json(textos[-1])
                if dados:
                    return {**fallback, **dados}
                break
            time.sleep(2)
    except Exception as e:
        print(f"  IA falhou, usando fallback: {e}")

    return fallback


def _extrair_json(texto):
    match = re.search(r"\{.*\}", texto, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _fallback_dados(nome, cpf):
    maes = ["Maria Silva", "Ana Souza", "Joana Lima", "Rita Alves"]
    pais = ["Jose Silva", "Antonio Souza", "Paulo Lima", "Carlos Alves"]
    cidades = ["Sao Paulo/SP", "Rio de Janeiro/RJ", "Belo Horizonte/MG", "Curitiba/PR"]
    ano_nasc = random.randint(1945, 1990)
    return {
        "rg": f"{random.randint(10,59)}.{random.randint(100,999)}.{random.randint(100,999)}-{random.randint(0,9)}",
        "data_expedicao": f"{random.randint(1,28):02d}/{random.randint(1,12):02d}/{random.randint(2005,2020)}",
        "filiacao": f"{random.choice(maes)} e {random.choice(pais)}",
        "naturalidade": random.choice(cidades),
        "data_nascimento": f"{random.randint(1,28):02d}/{random.randint(1,12):02d}/{ano_nasc}",
        "cidade": random.choice(cidades),
        "documento_origem": f"Certidao nasc. {random.randint(1000,9999)}",
    }


# ------------------------------------------------------------------ Geracao de imagens
def _load_font(size):
    for caminho in [
        "arial.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\segoeui.ttf",
    ]:
        try:
            return ImageFont.truetype(caminho, size)
        except Exception:
            continue
    return ImageFont.load_default()


def gerar_imagem(template_path, campos_coords, valores, font_size=18):
    img = Image.open(template_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    fonte = _load_font(font_size)
    for campo, (x, y) in campos_coords.items():
        valor = valores.get(campo)
        if valor is None:
            continue
        draw.text((x, y), str(valor), fill=(0, 0, 0), font=fonte)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def gerar_certidao_b64(dados):
    valores = {
        "nome": dados.get("nome"),
        "cpf": dados.get("cpf"),
        "naturalidade": dados.get("naturalidade"),
        "data_obito": dados.get("data_obito"),
        "causa": dados.get("causa"),
        "cidade": dados.get("cidade"),
    }
    return gerar_imagem(TEMPLATE_CERTIDAO, CAMPOS_CERTIDAO, valores, font_size=13)


def gerar_rg_b64(dados):
    valores = {
        "rg": dados.get("rg"),
        "data_expedicao": dados.get("data_expedicao"),
        "nome": dados.get("nome"),
        "filiacao": dados.get("filiacao"),
        "naturalidade": dados.get("naturalidade"),
        "data_nascimento": dados.get("data_nascimento"),
        "documento_origem": dados.get("documento_origem"),
        "cpf": dados.get("cpf"),
    }
    return gerar_imagem(TEMPLATE_RG, CAMPOS_RG, valores, font_size=26)


def gerar_anexos_em_paralelo(dados):
    with ThreadPoolExecutor(max_workers=2) as executor:
        certidao_futuro, rg_futuro = submeter_geracao_anexos(executor, dados)
        resultados = []
        for futuro in (certidao_futuro, rg_futuro):
            try:
                resultados.append(futuro.result())
            except Exception as exc:
                resultados.append(exc)
        return resultados


def submeter_geracao_anexos(executor, dados):
    return (
        executor.submit(gerar_certidao_b64, dados),
        executor.submit(gerar_rg_b64, dados),
    )


# ------------------------------------------------------------------ Payloads
def _rand_data_ocorrencia(term_start, term_end):
    """Escolhe uma data entre inicio e fim de vigencia (strings YYYY-MM-DD)."""
    try:
        d_ini = datetime.strptime(term_start, "%Y-%m-%d").date()
    except Exception:
        d_ini = date(2025, 1, 2)
    try:
        d_fim = datetime.strptime(term_end, "%Y-%m-%d").date()
    except Exception:
        d_fim = date.today()

    hoje = date.today()
    if d_fim > hoje:
        d_fim = hoje
    if d_fim < d_ini:
        d_fim = d_ini

    delta = (d_fim - d_ini).days
    if delta <= 0:
        escolhido = d_ini
    else:
        escolhido = date.fromordinal(d_ini.toordinal() + random.randint(0, delta))
    return datetime(escolhido.year, escolhido.month, escolhido.day, 6, 0, 0)


def _datas_ocorrencia_obito(term_start, term_end, mesma_data):
    """Retorna (ocorrencia, obito). Se mesma_data=False o obito ocorre 1-30 dias
    apos a ocorrencia, sem ultrapassar hoje."""
    ocorrencia = _rand_data_ocorrencia(term_start, term_end)
    if mesma_data:
        return ocorrencia, ocorrencia

    dias = random.randint(1, 30)
    obito = ocorrencia + timedelta(days=dias)
    hoje = datetime.combine(date.today(), ocorrencia.time())
    if obito > hoje:
        obito = hoje
        ocorrencia = obito - timedelta(days=dias)
    return ocorrencia, obito


def _saldo_ate_is_morte(endorsement):
    """Pega o amount da cobertura MORTE e escolhe um valor aleatorio ate ele."""
    limite = 20000.0
    for cov in (endorsement or {}).get("coverages", []) or []:
        desc = (cov.get("description") or "").upper()
        if "MORTE" in desc:
            amount = (cov.get("is") or {}).get("amount")
            if amount is not None:
                try:
                    limite = float(str(amount))
                except (TypeError, ValueError):
                    pass
            break
    valor = round(random.uniform(50, limite), 2)
    return valor


def build_notification_payload(cpf, doc_person, cenario, ocorrencia):
    endorsement = doc_person.get("endorsement_current") or {}
    ticket = doc_person.get("ticket_number")

    agora = datetime.now(timezone.utc).astimezone()

    return {
        "occurrenceDate": ocorrencia.isoformat(),
        "notificationDate": agora.isoformat(),
        "occurrenceDescription": "Abertura de Sinistro para Cobertura de Óbito PAN",
        "requestor": {
            "acceptsCommunication": True,
            "communicationType": "email",
            "requestorIsInsured": False,
            "name": "Automation Test",
            "socialName": None,
            "documentType": "cpf",
            "documentNumber": "70585243190",
            "relationship": "",
            "phones": [
                {
                    "countryCallingCode": "55",
                    "areaCode": "11",
                    "number": "999999999",
                    "principal": True,
                }
            ],
            "emails": [{"email": "test@tooseguros.com.br", "principal": True}],
        },
        "insured": {"documentNumber": cpf},
        "cause": None,
        "causeType": cenario["cause_type"],
        "occurrenceCodeUf": None,
        "occurrenceNameCity": None,
        "protocol": None,
        "coverage": "DEATH",
        "notificationOrigin": "apiV5",
        "additionalInformation": {
            "contract": str(ticket) if ticket is not None else None,
            "balanceDue": _saldo_ate_is_morte(endorsement),
        },
    }


def build_attachment_payload(b64, protocol, file_name):
    return {
        "attachment": b64,
        "protocol": protocol,
        "fileName": file_name,
        "origin": "apiV5",
    }


# ------------------------------------------------------------------ Checkpoint
def carregar_checkpoint():
    if not os.path.exists(CHECKPOINT_FILE):
        return set()
    with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


# ------------------------------------------------------------------ Estado compartilhado
class Contexto:
    """Recursos compartilhados entre as threads dos cenarios (candidatos,
    checkpoint e CSV), protegidos por lock."""

    def __init__(self, candidatos, col_notification, processados, csv_file, ckpt_file, token):
        self.candidatos = iter(candidatos)
        self.col_notification = col_notification
        self.processados = processados
        self.csv_file = csv_file
        self.ckpt_file = ckpt_file
        self.token = token
        self.lock = threading.Lock()
        self.resultados = []

    def proximo_candidato(self, tag):
        """Reserva e retorna (doc, cpf, nome) de um CPF ainda nao usado.
        Retorna None quando os candidatos acabam."""
        while True:
            with self.lock:
                doc = next(self.candidatos, None)
                if doc is None:
                    return None
                insureds = doc.get("insureds") or []
                if not insureds:
                    continue
                cpf = str(insureds[0].get("document") or "").strip()
                nome = insureds[0].get("name") or "Segurado Teste"
                if not cpf or cpf in self.processados:
                    continue
                # reserva o CPF para nenhum outro cenario pegar
                self.processados.add(cpf)

            # CPF ja usado em Notification? pula
            if self.col_notification.find_one({"insured.documentNumber": cpf}, {"_id": 1}):
                print(f"{tag} CPF {cpf} ja existe em Notification. Pulando.")
                with self.lock:
                    self.ckpt_file.write(cpf + "\n")
                    self.ckpt_file.flush()
                continue

            return doc, cpf, nome

    def registrar(self, cenario, cpf, nome, ticket, protocol, status, ocorrencia, obito):
        print(
            f"[{cenario['nome']}] >>> CPF {cpf} | Protocolo: {protocol or '-'} | "
            f"Status: {status} | Causa: {cenario['causa']} ({cenario['cause_type']}) | "
            f"Ocorrencia: {ocorrencia:%d/%m/%Y} | Obito: {obito:%d/%m/%Y}"
        )
        with self.lock:
            self.resultados.append(
                {
                    "cenario": cenario["nome"],
                    "cpf": cpf,
                    "protocol": protocol,
                    "status": status,
                    "ocorrencia": ocorrencia,
                    "obito": obito,
                }
            )
            self.csv_file.write(f"{cpf},{nome},{ticket},{protocol},{status},{cenario['nome']}\n")
            self.csv_file.flush()
            self.ckpt_file.write(cpf + "\n")
            self.ckpt_file.flush()


# ------------------------------------------------------------------ Sinistro + anexos
def criar_sinistro_com_anexos(tag, payload, dados, token):
    """Cria a notification e envia os anexos. Retorna o protocol ou None se falhar."""
    with ThreadPoolExecutor(max_workers=2) as executor:
        certidao_futuro, rg_futuro = submeter_geracao_anexos(executor, dados)

        try:
            resultados = create_notification(payload, token)
            protocol = None
            for r in resultados:
                if r.get("protocol"):
                    protocol = r["protocol"]
                    break
            if not protocol:
                raise ValueError("Retorno sem protocol")
            print(f"{tag}   Notification criada. Protocolo: {protocol}")
        except Exception as e:
            print(f"{tag}   ERRO ao criar notification: {e}")
            return None

        try:
            cert_b64 = certidao_futuro.result()
        except Exception as e:
            cert_b64 = e

        try:
            rg_b64 = rg_futuro.result()
        except Exception as e:
            rg_b64 = e

        envios = []
        if not isinstance(cert_b64, Exception):
            envios.append(
                (
                    "certidao",
                    executor.submit(
                        send_attachment,
                        build_attachment_payload(
                            cert_b64, protocol, "certidao-de-obito.png"
                        ),
                        token,
                    ),
                )
            )
        if not isinstance(rg_b64, Exception):
            envios.append(
                (
                    "RG",
                    executor.submit(
                        send_attachment,
                        build_attachment_payload(
                            rg_b64, protocol, "documento-identificacao.png"
                        ),
                        token,
                    ),
                )
            )

        if isinstance(cert_b64, Exception):
            print(f"{tag}   ERRO anexo certidao: {cert_b64}")
        if isinstance(rg_b64, Exception):
            print(f"{tag}   ERRO anexo RG: {rg_b64}")

        for nome_anexo, envio_futuro in envios:
            try:
                envio_futuro.result()
                if nome_anexo == "certidao":
                    print(f"{tag}   Anexo certidao enviado.")
                else:
                    print(f"{tag}   Anexo documento de identificacao enviado.")
            except Exception as e:
                print(f"{tag}   ERRO anexo {nome_anexo}: {e}")

    return protocol


# ------------------------------------------------------------------ Cenario
def processar_cenario(cenario, ctx):
    tag = f"[{cenario['nome']}]"
    criados = 0
    while criados < LIMITE:
        candidato = ctx.proximo_candidato(tag)
        if candidato is None:
            print(f"{tag} Sem mais apolices candidatas.")
            break
        doc, cpf, nome = candidato
        ticket = doc.get("ticket_number")

        print(f"\n{tag} Processando CPF {cpf} ({nome})")

        endorsement = doc.get("endorsement_current") or {}
        ocorrencia, obito = _datas_ocorrencia_obito(
            endorsement.get("term_start_date") or "2025-01-02",
            endorsement.get("term_end_date") or "2029-01-02",
            cenario["mesma_data"],
        )
        payload = build_notification_payload(cpf, doc, cenario, ocorrencia)
        dados = {
            **ia_gerar_dados(nome, cpf),
            "nome": nome,
            "cpf": cpf,
            "data_obito": obito.strftime("%d/%m/%Y"),
            "causa": cenario["causa"],
        }

        if DRY_RUN:
            print(f"{tag}   [DRY_RUN] payload notification: {json.dumps(payload, default=str)[:200]}...")
            print(f"{tag}   [DRY_RUN] ocorrencia={ocorrencia:%d/%m/%Y} obito={dados['data_obito']}")
            cert_b64, rg_b64 = gerar_anexos_em_paralelo(dados)
            if isinstance(cert_b64, Exception):
                raise cert_b64
            if isinstance(rg_b64, Exception):
                raise rg_b64
            print(f"{tag}   [DRY_RUN] imagens geradas OK")
            ctx.registrar(cenario, cpf, nome, ticket, "DRY_RUN", "dry_run", ocorrencia, obito)
            criados += 1
            continue

        protocol = criar_sinistro_com_anexos(tag, payload, dados, ctx.token)
        if not protocol:
            ctx.registrar(cenario, cpf, nome, ticket, "", "erro_notification", ocorrencia, obito)
            continue

        ctx.registrar(cenario, cpf, nome, ticket, protocol, "ok", ocorrencia, obito)
        criados += 1
        time.sleep(0.5)

    print(f"\n{tag} Finalizado. Criados: {criados}")
    return criados


# ------------------------------------------------------------------ Main
def main():
    faltando = [
        n for n, v in {
            "HML_INDEXED_MONGO_URI": MONGO_INDEXED,
            "HML_MONGO_URI": MONGO_CLAIM,
            "CLAIM_ENGINE_API_STG": API_BASE,
            "KEYCLOAK_TOKEN_URL": TOKEN_URL,
        }.items() if not v
    ]
    if faltando:
        print(f"ERRO: variaveis .env faltando: {', '.join(faltando)}")
        return

    client_idx = MongoClient(MONGO_INDEXED)
    client_claim = MongoClient(MONGO_CLAIM)
    col_person = client_idx[DB_INDEXED_POLICY][COL_PERSON]
    col_notification = client_claim[DB_CLAIM]["Notification"]

    processados = carregar_checkpoint()
    print(f"Ja processados (checkpoint): {len(processados)}")

    token = None if DRY_RUN else get_token()
    if not DRY_RUN:
        print("Token obtido.")

    csv_novo = not os.path.exists(LOG_CSV)
    csv_file = open(LOG_CSV, "a", encoding="utf-8-sig", newline="")
    if csv_novo:
        csv_file.write("cpf,nome,ticket_number,protocol,status,cenario\n")
        csv_file.flush()
    ckpt_file = open(CHECKPOINT_FILE, "a", encoding="utf-8")

    # carrega os candidatos antes de abrir as threads (cursor do pymongo nao e thread-safe)
    filtro = build_filtro_indexado()
    projecao = {"insureds": 1, "endorsement_current": 1, "ticket_number": 1}
    candidatos = list(col_person.find(filtro, projecao).sort("_id", -1).limit(MAX_CANDIDATOS))
    print(f"Apolices candidatas: {len(candidatos)}")

    ctx = Contexto(candidatos, col_notification, processados, csv_file, ckpt_file, token)

    totais = {}
    try:
        with ThreadPoolExecutor(max_workers=len(CENARIOS)) as executor:
            futuros = {
                executor.submit(processar_cenario, cenario, ctx): cenario["nome"]
                for cenario in CENARIOS
            }
            for futuro in as_completed(futuros):
                nome_cenario = futuros[futuro]
                try:
                    totais[nome_cenario] = futuro.result()
                except Exception as e:
                    print(f"\n[{nome_cenario}] ERRO fatal: {e}")
                    totais[nome_cenario] = "erro"
    finally:
        csv_file.close()
        ckpt_file.close()
        client_idx.close()
        client_claim.close()

    print("\nFinalizado!")
    for cenario in CENARIOS:
        print(f"  {cenario['nome']}: {totais.get(cenario['nome'])}")
    print(f"  Log: {LOG_CSV}")

    print("\nNotifications por cenario:")
    for cenario in CENARIOS:
        print(f"\n  [{cenario['nome']}] {cenario['causa']} ({cenario['cause_type']})")
        itens = [r for r in ctx.resultados if r["cenario"] == cenario["nome"]]
        if not itens:
            print("    (nenhuma)")
        for r in itens:
            print(
                f"    Protocolo: {r['protocol'] or '-':<22} CPF: {r['cpf']:<12} "
                f"Ocorrencia: {r['ocorrencia']:%d/%m/%Y}  Obito: {r['obito']:%d/%m/%Y}  "
                f"Status: {r['status']}"
            )


if __name__ == "__main__":
    main()
