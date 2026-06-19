import os
import time
import mimetypes
import warnings
from dotenv import load_dotenv
import requests
from requests.exceptions import SSLError as RequestsSSLError
import urllib3
import boto3
from pymongo import MongoClient

load_dotenv()

warnings.filterwarnings("ignore")
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

AWS_ACCESS_KEY_ID = os.getenv("PRD_AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("PRD_AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION = os.getenv("PRD_AWS_REGION", "us-east-2")
AWS_SESSION_TOKEN = os.getenv("AWS_SESSION_TOKEN")

COPILOT_API_KEY = os.getenv("COPILOT_API_KEY")
COPILOT_MODEL = os.getenv("COPILOT_MODEL", "claude-sonnet-4.6")
DIRECT_LINE_BASE_URL = os.getenv("DIRECT_LINE_BASE_URL", "https://directline.botframework.com/v3/directline")
DIRECT_LINE_SSL_VERIFY = os.getenv("DIRECT_LINE_SSL_VERIFY", "true").strip().lower() not in ["0", "false", "no", "off"]
DIRECT_LINE_CA_BUNDLE = os.getenv("DIRECT_LINE_CA_BUNDLE")
CLIENT_AI_USER_ID = "copilot-directline-tester"
POLL_ATTEMPTS = 30
POLL_INTERVAL_SECONDS = 1

AWS_BUCKET_NAME = os.getenv("PRD_S3_BUCKET", "auditdev-too-ohio")

S3_PDF_KEY = "TemporaryFiles/11202642304477084_IMG_9619_8e58b63fcfec6c62d2fd3c487c14d094.jpeg"

class CopilotDirectLineClient:
    def __init__(self, api_key, model=None, instructions="", base_url=DIRECT_LINE_BASE_URL, verify_ssl=True):
        if not api_key:
            raise ValueError("COPILOT_API_KEY nao configurada.")
        self.api_key = api_key
        self.model = model
        self.instructions = instructions
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def _auth_headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}"
        }

    def _request(self, method, url, **kwargs):
        try:
            return requests.request(method, url, verify=self.verify_ssl, **kwargs)
        except RequestsSSLError as error:
            raise RuntimeError(
                "Falha SSL ao chamar Direct Line. Configure DIRECT_LINE_CA_BUNDLE com o certificado da empresa "
                "ou use DIRECT_LINE_SSL_VERIFY=false apenas para teste temporario."
            ) from error

    def ask(self, instructions, prompt):
        start_response = self._request(
            "POST",
            f"{self.base_url}/conversations",
            headers=self._headers(),
            timeout=30
        )
        start_response.raise_for_status()
        conversation_id = start_response.json().get("conversationId")
        if not conversation_id:
            raise RuntimeError("Copilot conversation nao foi criada.")

        activity_text = f"{instructions}\n\n{prompt}" if instructions else prompt
        activity_payload = {
            "type": "message",
            "text": activity_text,
            "from": {"id": CLIENT_AI_USER_ID},
            "channelData": {"model": self.model}
        }

        post_response = self._request(
            "POST",
            f"{self.base_url}/conversations/{conversation_id}/activities",
            headers=self._headers(),
            json=activity_payload,
            timeout=30
        )
        post_response.raise_for_status()

        watermark = None
        bot_reply = None

        for _ in range(POLL_ATTEMPTS):
            params = {"watermark": watermark} if watermark else None
            activities_response = self._request(
                "GET",
                f"{self.base_url}/conversations/{conversation_id}/activities",
                headers=self._headers(),
                params=params,
                timeout=30
            )
            activities_response.raise_for_status()
            activities_payload = activities_response.json()
            watermark = activities_payload.get("watermark")

            activities = activities_payload.get("activities") or []
            messages = [
                activity.get("text")
                for activity in activities
                if str(activity.get("type", "")).lower() == "message"
                and activity.get("text")
                and str((activity.get("from") or {}).get("id", "")).lower() != CLIENT_AI_USER_ID.lower()
            ]
            if messages:
                bot_reply = messages[-1]
                break

            time.sleep(POLL_INTERVAL_SECONDS)

        if not bot_reply:
            raise TimeoutError("Copilot nao retornou resposta antes do timeout.")
        return bot_reply

def gerar_url_temporaria_s3(key, expires=600):
    """Gera uma URL temporaria para um arquivo no S3."""
    session_kwargs = {
        'aws_access_key_id': AWS_ACCESS_KEY_ID,
        'aws_secret_access_key': AWS_SECRET_ACCESS_KEY,
        'region_name': AWS_DEFAULT_REGION
    }
    if AWS_SESSION_TOKEN:
        session_kwargs['aws_session_token'] = AWS_SESSION_TOKEN
    s3 = boto3.client('s3', **session_kwargs)
    return s3.generate_presigned_url('get_object', Params={'Bucket': AWS_BUCKET_NAME, 'Key': key}, ExpiresIn=expires)

def _aguardar_resposta(client, conversation_id):
    watermark = None
    bot_reply = None

    for _ in range(POLL_ATTEMPTS):
        params = {"watermark": watermark} if watermark else None
        activities_response = client._request(
            "GET",
            f"{client.base_url}/conversations/{conversation_id}/activities",
            headers=client._headers(),
            params=params,
            timeout=30
        )
        activities_response.raise_for_status()
        activities_payload = activities_response.json()
        watermark = activities_payload.get("watermark")

        activities = activities_payload.get("activities") or []
        messages = [
            activity.get("text")
            for activity in activities
            if str(activity.get("type", "")).lower() == "message"
            and activity.get("text")
            and str((activity.get("from") or {}).get("id", "")).lower() != CLIENT_AI_USER_ID.lower()
        ]
        if messages:
            bot_reply = messages[-1]
            break

        time.sleep(POLL_INTERVAL_SECONDS)

    if not bot_reply:
        raise TimeoutError("Copilot nao retornou resposta antes do timeout.")
    return bot_reply

def enviar_arquivo_para_directline(client, arquivo_url, arquivo_key, prompt_text):
    start_response = client._request(
        "POST",
        f"{client.base_url}/conversations",
        headers=client._headers(),
        timeout=30
    )
    start_response.raise_for_status()
    conversation_id = start_response.json().get("conversationId")
    if not conversation_id:
        raise RuntimeError("Copilot conversation nao foi criada.")

    arquivo_nome = os.path.basename(arquivo_key) or "documento.bin"
    content_type, _ = mimetypes.guess_type(arquivo_nome)
    if not content_type:
        content_type = "application/octet-stream"

    activity_payload = {
        "type": "message",
        "text": prompt_text,
        "from": {"id": CLIENT_AI_USER_ID},
        "attachments": [
            {
                "contentType": content_type,
                "contentUrl": arquivo_url,
                "name": arquivo_nome,
            }
        ],
        "channelData": {"model": client.model}
    }

    post_response = client._request(
        "POST",
        f"{client.base_url}/conversations/{conversation_id}/activities",
        headers=client._headers(),
        json=activity_payload,
        timeout=30
    )
    post_response.raise_for_status()

    return _aguardar_resposta(client, conversation_id)

def main():
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        raise ValueError("Configure AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY nas variaveis de ambiente.")
    if not COPILOT_API_KEY:
        raise ValueError("Configure COPILOT_API_KEY na variavel de ambiente.")

    key = S3_PDF_KEY

    prompt = '''
    Voce e um especialista em extracao de dados estruturados a partir de textos OCR de documentos brasileiros.

Vou te fornecer um texto bruto extraido via OCR de um Comprovante de Endereço.
Esse texto pode conter ruidos, erros de OCR, caracteres incorretos, quebras de linha e desordem.

Sua tarefa e:
- Interpretar cuidadosamente o conteudo do OCR, validar consistencia e corrigir erros comuns de leitura como pontos, barras e digitos trocados.
- Identificar no texto indicios tipicos de comprovantes, como cabecalhos de concessionarias (ex.: CPFL, ENEL, SABESP), referencias a contas mensais, numeros de cliente, secoes com endereco.
- Corrigir falhas comuns como substituicao de letras por numeros (ex.: O por 0) e ajustar espacos ou quebras que fragmentem dados essenciais.
- Extrair exclusivamente os metadados solicitados.
- Retornar exclusivamente um JSON valido e completo com os dados possiveis de serem identificados.
- Nao adicionar comentarios, explicacoes ou texto extra fora do JSON.
- Seguir rigorosamente o formato e padronizacao dos campos especificados.

Padronizacao obrigatoria dos campos de saida:
- Todas as chaves do JSON devem estar em minusculo
- Sem acentos
- Com underscore (_) no lugar de espacos

Metadados obrigatorios a extrair:
- Nome do titular
- CPF / CNPJ do titular
- Tipo de titular (Pessoa Fisica ou Pessoa Juridica, quando detectavel)
- Codigo do cliente
- Logradouro
- Numero
- Complemento
- Bairro
- Municipio
- UF
- CEP
- Nome da concessionaria
- Tipo de servico (Ex.: Energia, Agua, Gas, Internet)
- Data do vencimento (quando houver fatura vinculada)

Formato de saida esperado:
{'nome_do_titular': '', 'cpf_cnpj_do_titular': '', 'tipo_de_titular': '', 'codigo_do_cliente': '', 'logradouro': '', 'numero': '', 'complemento': '', 'bairro': '', 'municipio': '', 'uf': '', 'cep': '', 'nome_da_concessionaria': '', 'tipo_de_servico': '', 'data_do_vencimento': ''}

O resultado final deve ser somente o JSON valido, sem nenhum texto adicional.'''

    url_temp = gerar_url_temporaria_s3(key)
    print(f"URL temporária gerada: {url_temp}")

    client = CopilotDirectLineClient(
        api_key=COPILOT_API_KEY,
        model=COPILOT_MODEL,
        verify_ssl=DIRECT_LINE_CA_BUNDLE if DIRECT_LINE_CA_BUNDLE else DIRECT_LINE_SSL_VERIFY
    )

    MAX_RETRIES = 5
    RETRY_INTERVAL = 30
    INVALID_RESPONSES = [
        "This agent is currently unavailable. It has reached its usage limit. Please try again later."
    ]

    resposta = None
    for tentativa in range(1, MAX_RETRIES + 1):
        print(f"\nTentativa {tentativa}/{MAX_RETRIES} - Enviando arquivo para o modelo via DirectLine...")
        try:
            resposta = enviar_arquivo_para_directline(client, url_temp, key, prompt)
        except (TimeoutError, RuntimeError) as e:
            print(f"[ERRO] Tentativa {tentativa}: {e}")
            resposta = None

        if resposta and resposta.strip() not in INVALID_RESPONSES:
            break

        print(f"Resposta inválida ou indisponível. Aguardando {RETRY_INTERVAL}s antes de retentar...")
        if tentativa < MAX_RETRIES:
            time.sleep(RETRY_INTERVAL)

    print("\n--- RESPOSTA ---\n")
    print(resposta if resposta else "Nenhuma resposta válida após todas as tentativas.")

if __name__ == "__main__":
    main()
