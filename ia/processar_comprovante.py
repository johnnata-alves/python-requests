import os
import json
import time
import mimetypes
import requests
import boto3

from requests.exceptions import SSLError as RequestsSSLError
from dotenv import load_dotenv

load_dotenv()

AWS_ACCESS_KEY_ID = os.getenv("PRD_AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("PRD_AWS_SECRET_ACCESS_KEY")
AWS_DEFAULT_REGION = os.getenv("PRD_AWS_REGION", "us-east-2")
AWS_SESSION_TOKEN = os.getenv("AWS_SESSION_TOKEN")

AWS_BUCKET_NAME = os.getenv(
    "PRD_S3_BUCKET",
    "auditdev-too-ohio"
)

COPILOT_API_KEY = os.getenv("COPILOT_API_KEY")

COPILOT_MODEL = os.getenv(
    "COPILOT_MODEL",
    "gpt-5.5"
)

DIRECT_LINE_BASE_URL = os.getenv(
    "DIRECT_LINE_BASE_URL",
    "https://directline.botframework.com/v3/directline"
)

DIRECT_LINE_SSL_VERIFY = (
    os.getenv(
        "DIRECT_LINE_SSL_VERIFY",
        "true"
    ).strip().lower()
    not in ["0", "false", "no", "off"]
)

DIRECT_LINE_CA_BUNDLE = os.getenv(
    "DIRECT_LINE_CA_BUNDLE"
)

CLIENT_AI_USER_ID = "copilot-directline-tester"

POLL_ATTEMPTS = 30
POLL_INTERVAL_SECONDS = 1

S3_FILE_KEY = (
    "TemporaryFiles/"
    "11202651904551990_download_2_ba2fa983907333f85ac6d8190dcf29bf.pdf"
)

class CopilotDirectLineClient:

    def __init__(
        self,
        api_key,
        model=None,
        instructions="",
        base_url=DIRECT_LINE_BASE_URL,
        verify_ssl=True,
        ca_bundle=None
    ):

        if not api_key:
            raise ValueError(
                "COPILOT_API_KEY nao configurada."
            )

        self.api_key = api_key
        self.model = model
        self.instructions = instructions
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.ca_bundle = ca_bundle

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

        verify = self.verify_ssl

        if self.ca_bundle:
            verify = self.ca_bundle

        try:

            return requests.request(
                method,
                url,
                verify=verify,
                **kwargs
            )

        except RequestsSSLError as error:

            raise RuntimeError(
                "Falha SSL ao chamar Direct Line."
            ) from error

    def _start_conversation(self):

        response = self._request(
            "POST",
            f"{self.base_url}/conversations",
            headers=self._headers(),
            timeout=30
        )

        response.raise_for_status()

        payload = response.json()

        conversation_id = payload.get(
            "conversationId"
        )

        if not conversation_id:

            raise RuntimeError(
                "Nao foi possivel criar conversation."
            )

        return conversation_id

    def _upload_attachment(
        self,
        conversation_id,
        file_bytes,
        file_name,
        content_type
    ):

        files = {
            "file": (
                file_name,
                file_bytes,
                content_type
            )
        }

        response = self._request(
            "POST",
            (
                f"{self.base_url}/conversations/"
                f"{conversation_id}/upload"
                f"?userId={CLIENT_AI_USER_ID}"
            ),
            headers=self._auth_headers(),
            files=files,
            timeout=120
        )

        response.raise_for_status()

        upload_payload = response.json()

        attachment_id = upload_payload.get("id")

        return {
            "contentType": content_type,
            "contentUrl": attachment_id,
            "name": file_name
        }

    def ask_document_from_s3(
        self,
        bucket_name,
        object_key,
        prompt
    ):

        s3 = boto3.client(
            "s3",
            region_name=AWS_DEFAULT_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            aws_session_token=AWS_SESSION_TOKEN
        )

        print(
            f"\nBaixando arquivo do S3:\n"
            f"s3://{bucket_name}/{object_key}\n"
        )

        s3_object = s3.get_object(
            Bucket=bucket_name,
            Key=object_key
        )

        file_bytes = s3_object["Body"].read()

        file_name = os.path.basename(object_key)

        content_type = (
            s3_object.get("ContentType")
            or mimetypes.guess_type(file_name)[0]
            or "application/octet-stream"
        )

        print(f"Arquivo: {file_name}")
        print(f"Content-Type: {content_type}")
        print(f"Tamanho: {len(file_bytes)} bytes")

        conversation_id = self._start_conversation()

        print(f"\nConversation criada: {conversation_id}")

        final_prompt = f"""
{self.instructions}

{prompt}

IMPORTANTE:
- Extraia TODOS os metadados de identificacao
- Retorne JSON VALIDO
- Nao invente dados
- Caso nao encontre algum campo, retornar null

Extraia:
- nome completo
- cpf
- rg
- cnpj
- endereco
- bairro
- cidade
- estado
- cep
- telefone
- email
- numero documento
- numero unidade consumidora
- codigo cliente
- nota fiscal
- chave acesso
- empresa emissora
- datas
- vencimentos
- valores
- observacoes

Formato JSON esperado:

{{
  "nome_completo": "",
  "cpf": "",
  "rg": "",
  "cnpj": "",
  "numero_documento": "",
  "numero_uc": "",
  "codigo_cliente": "",
  "endereco": "",
  "bairro": "",
  "cidade": "",
  "estado": "",
  "cep": "",
  "telefone": "",
  "email": "",
  "empresa_emissora": "",
  "nota_fiscal": "",
  "chave_acesso": "",
  "datas_importantes": [],
  "valores": [],
  "observacoes": []
}}
"""

        print("\nEnviando arquivo + prompt via upload...")

        files = {
            "file": (file_name, file_bytes, content_type)
        }

        data = {
            "userId": CLIENT_AI_USER_ID,
            "type": "message",
            "text": final_prompt
        }

        upload_response = self._request(
            "POST",
            f"{self.base_url}/conversations/{conversation_id}/upload?userId={CLIENT_AI_USER_ID}",
            headers=self._auth_headers(),
            files=files,
            data={"activity": json.dumps({
                "type": "message",
                "from": {"id": CLIENT_AI_USER_ID},
                "text": final_prompt,
                "channelData": {"model": self.model}
            })},
            timeout=120
        )

        upload_response.raise_for_status()
        print("Arquivo + prompt enviados.")

        watermark = None
        bot_reply = None

        for attempt in range(POLL_ATTEMPTS):

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
                print(f"\nResposta recebida (tentativa {attempt + 1})")
                break

            print(f"Aguardando resposta ({attempt + 1}/{POLL_ATTEMPTS})")
            time.sleep(POLL_INTERVAL_SECONDS)

        if not bot_reply:
            raise TimeoutError("Copilot nao respondeu antes do timeout.")

        return bot_reply

if __name__ == "__main__":

    client = CopilotDirectLineClient(

        api_key=COPILOT_API_KEY,

        model=COPILOT_MODEL,

        verify_ssl=DIRECT_LINE_SSL_VERIFY,

        ca_bundle=DIRECT_LINE_CA_BUNDLE,

        instructions="""
Voce e um OCR inteligente especializado em:
- contas de energia
- documentos brasileiros
- CNH
- RG
- CPF
- boletos
- comprovantes

Extraia todos os metadados importantes.

Sempre retorne JSON valido como chave e valor
"""
    )

    resposta = client.ask_document_from_s3(

        bucket_name=AWS_BUCKET_NAME,

        object_key=S3_FILE_KEY,

        prompt="""
Extraia todos os metadados importantes
de identificacao desse documento.
"""
    )

    print(
        "\n================ RESULTADO ================\n"
    )

    try:

        parsed = json.loads(resposta)

        print(
            json.dumps(
                parsed,
                indent=2,
                ensure_ascii=False
            )
        )

    except Exception:

        print(resposta)
