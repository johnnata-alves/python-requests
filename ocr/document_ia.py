import ast
import json
import os
import time
import unicodedata

from dotenv import load_dotenv
import pandas as pd
import requests
from bson import ObjectId
from pymongo import MongoClient
from requests.exceptions import SSLError as RequestsSSLError

load_dotenv()

MONGO_URI = os.getenv("HML_MONGO_URI")
DB_NAME = "ClaimEngine"
COLLECTION_NAME = "DocumentTypeMappings"
EXCEL_PATH = "docs_ocr.xlsx"
EXCEL_OUTPUT_PATH = os.getenv("EXCEL_OUTPUT_PATH", EXCEL_PATH)

COPILOT_API_KEY = os.getenv("COPILOT_API_KEY")
COPILOT_MODEL = "gpt-5.1"
COPILOT_INSTRUCTIONS = "Return ONLY a JSON payload with the requested fields."
DIRECT_LINE_BASE_URL = os.getenv("DIRECT_LINE_BASE_URL", "https://directline.botframework.com/v3/directline")
DIRECT_LINE_SSL_VERIFY = os.getenv("DIRECT_LINE_SSL_VERIFY", "true").strip().lower() not in ["0", "false", "no", "off"]
DIRECT_LINE_CA_BUNDLE = os.getenv("DIRECT_LINE_CA_BUNDLE")
CLIENT_AI_USER_ID = "document-typification"
POLL_ATTEMPTS = 30
POLL_INTERVAL_SECONDS = 1

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

    def _request(self, method, url, **kwargs):
        try:
            return requests.request(method, url, verify=self.verify_ssl, **kwargs)
        except RequestsSSLError as error:
            raise RuntimeError(
                "Falha SSL ao chamar Direct Line. Configure DIRECT_LINE_CA_BUNDLE com o certificado da empresa "
                "ou use DIRECT_LINE_SSL_VERIFY=false apenas para teste temporario."
            ) from error

    def ask(self, prompt):
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

        activity_text = f"{self.instructions}\n\n{prompt}" if self.instructions else prompt
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

client_ai = CopilotDirectLineClient(
    api_key=COPILOT_API_KEY,
    model=COPILOT_MODEL,
    instructions=COPILOT_INSTRUCTIONS,
    verify_ssl=DIRECT_LINE_CA_BUNDLE if DIRECT_LINE_CA_BUNDLE else DIRECT_LINE_SSL_VERIFY
)

def normalize(text):
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])
    return text.lower().replace(" ", "_")

def generate_variations(text):
    if not text:
        return []
    base = text.strip()
    return list(set([
        base,
        base.lower(),
        normalize(base),
        base.replace(" ", "_"),
        normalize(base).replace("_", " ")
    ]))

def parse_ai_json(content):
    text = (content or "").strip()
    if not text:
        return None

    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(candidate)
            except (ValueError, SyntaxError):
                return None

    return None

def is_blank(value):
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except TypeError:
        pass
    return isinstance(value, str) and not value.strip()

def get_row_value(row, keys, default=None):
    for key in keys:
        value = row.get(key)
        if not is_blank(value):
            return value
    return default

def parse_required_flag(value):
    normalized = str(value).strip().upper()
    return normalized in ["S", "SIM", "TRUE", "1"]

def to_int_if_possible(value):
    if is_blank(value):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return value

def normalize_list(values):
    if not isinstance(values, list):
        return []
    normalized_values = [str(value).strip() for value in values if not is_blank(value)]
    return list(dict.fromkeys(normalized_values))

def call_ai(documents, grupo, documento, metadados):
    documents_json = json.dumps(documents, ensure_ascii=False)
    metadados_list = "\n".join([f"- {m}" for m in metadados]) if metadados else "- (sem metadados)"

    prompt = f"""
Voce recebera uma lista de documentos do MongoDB e um documento alvo.
Classifique e retorne APENAS um JSON valido (sem markdown, sem texto extra).

OBJETIVO:
1. Escolher um ou mais IDs mais compativeis com o documento alvo.
2. Gerar variacoes de DocumentKeys.
3. Gerar variacoes para CADA metadado recebido.

REGRAS IMPORTANTES:
- Use somente IDs existentes na lista de DOCUMENTOS DISPONIVEIS.
- Retorne "IDs" como lista de strings hexadecimal (24 chars), sem ObjectId(...).
- Sempre retorne ao menos 1 ID em "IDs".
- "DocumentKeys" deve conter variacoes relevantes e sem duplicidade.
- Para cada termo em "DocumentKeys" e para cada metadado, gere variacoes com:
  a) acento e espacos (forma natural)
  b) sem acento e com espacos
  c) sem acento e com underscore
  d) sem acento e sem espacos
- Inclua sinonimos usuais quando fizer sentido.
- Nao invente metadados fora da lista recebida.
- Em "metadatas", inclua TODOS os metadados recebidos, um por item.
- Cada item de "metadatas" deve ter no minimo 4 variacoes.

EXEMPLO DE VARIACOES ESPERADAS:
- "Ano de Fabricacao" -> ["Ano de Fabricacao", "Ano Fabricacao", "ano_de_fabricacao", "anodefabricacao"]
- "Placa" -> ["Placa", "Placa do Veiculo", "placa_do_veiculo", "placadoveiculo"]

DOCUMENTOS DISPONIVEIS:
{documents_json}

DOCUMENTO ALVO:
Grupo: {grupo}
Metadados:
{metadados_list}

FORMATO DE RESPOSTA (JSON estrito):
{{
  "IDs": ["6935026a6537fcae6b3bf0ab", "6935026a6537fcae6b3bf0ac"],
  "DocumentKeys": [
    "Documento de Veiculo",
    "Documento Veiculo",
    "documento_de_veiculo",
    "documentodeveiculo"
  ],
  "metadatas": [
    {{
      "metadata": "Placa",
      "variations": ["Placa", "Placa do Veiculo", "placa_do_veiculo", "placadoveiculo"]
    }}
  ]
}}
"""

    return client_ai.ask(prompt)

mongo = MongoClient(MONGO_URI)
db = mongo[DB_NAME]
collection = db[COLLECTION_NAME]

mongo_docs_filter = {
    "$or": [
        {"documentName": {"$regex": ".*boletim.*", "$options": "i"}},
        {"documentName": {"$regex": ".*Declara.*", "$options": "i"}}
    ]
}

mongo_docs = list(collection.find(mongo_docs_filter, {
    "_id": 1,
    "documentName": 1,
    "ERPDocumentName": 1
}))

mongo_docs_str = [
    {
        "_id": str(doc["_id"]),
        "documentName": doc.get("documentName"),
        "ERPDocumentName": doc.get("ERPDocumentName")
    }
    for doc in mongo_docs
]

df = pd.read_excel(EXCEL_PATH)
if "status" not in df.columns:
    raise ValueError("A planilha precisa ter a coluna 'status' para reprocessamento.")

df["status"] = df["status"].fillna("").astype(str)
error_rows = df[df["status"].str.strip().str.lower() == "erro"]

if error_rows.empty:
    df.to_excel(EXCEL_OUTPUT_PATH, index=False)
    print(f"Nenhum registro com status=erro para reprocessar. Excel salvo em: {EXCEL_OUTPUT_PATH}")
    raise SystemExit(0)

groups = error_rows.groupby(["CdGrupoDocumento", "CdDocumento"])

for (cd_grupo, cd_doc), group in groups:
    group_indexes = group.index
    status_value = "erro"
    grupo_nome = group["GrupoDocumento"].iloc[0]
    documento_nome = group["Documento"].iloc[0]

    try:
        metadados = group["Metadado"].dropna().tolist()

        ai_response = call_ai(mongo_docs_str, grupo_nome, documento_nome, metadados)

        result = parse_ai_json(ai_response)
        if not result:
            raise ValueError("Erro ao parsear resposta da IA")

        ids_from_ai = result.get("IDs")
        if isinstance(ids_from_ai, list):
            candidate_doc_ids = [str(item).strip() for item in ids_from_ai if str(item).strip()]
        else:
            single_id = str(result.get("_id", "")).strip()
            candidate_doc_ids = [single_id] if single_id else []

        candidate_doc_ids = list(dict.fromkeys(candidate_doc_ids))
        if not candidate_doc_ids:
            raise ValueError("Resposta da IA sem IDs")

        valid_doc_ids = [doc_id for doc_id in candidate_doc_ids if ObjectId.is_valid(doc_id)]
        if not valid_doc_ids:
            raise ValueError("Resposta da IA sem IDs validos")

        object_ids = [ObjectId(doc_id) for doc_id in valid_doc_ids]
        existing_docs = list(collection.find({"_id": {"$in": object_ids}}, {"_id": 1, "OCR": 1, "DocumentKeys": 1}))
        if not existing_docs:
            raise ValueError(f"Nenhum documento encontrado no Mongo para IDs: {valid_doc_ids}")

        new_keys = normalize_list(result.get("DocumentKeys", []))

        new_metadatas = []

        for _, row in group.iterrows():
            meta = row.get("Metadado")
            if not meta:
                continue

            ai_meta = next(
                (
                    m for m in result.get("metadatas", [])
                    if normalize(str(m.get("metadata", ""))) == normalize(str(meta))
                ),
                None
            )

            ai_variations = ai_meta.get("variations", []) if ai_meta else []
            variations = normalize_list(ai_variations) or generate_variations(str(meta))
            variations = list(dict.fromkeys(variations + generate_variations(str(meta))))

            new_metadatas.append({
                "metadata": meta,
                "Descrição": get_row_value(row, ["Descrição", "Descricao"], meta),
                "fieldType": get_row_value(row, ["Tipo de dado", "Tipo"], ""),
                "variations": variations,
                "domain": "Notification",
                "fieldValidation": get_row_value(row, ["Regra de validação?", "Regra de validacao?", "Regra"], ""),
                "isRequired": parse_required_flag(
                    get_row_value(
                        row,
                        ["Mandatório para regulação?", "Mandatorio para regulacao?", "Mandatorio"],
                        "N"
                    )
                )
            })

        updated_ids = []

        group_document_code = to_int_if_possible(cd_grupo)
        document_code = to_int_if_possible(cd_doc)

        for existing_doc in existing_docs:
            ocr = existing_doc.get("OCR", {})
            if not isinstance(ocr, dict):
                ocr = {}

            ocr_documents = ocr.get("Documents", [])
            if not isinstance(ocr_documents, list):
                ocr_documents = []

            existing_document_entry = next(
                (item for item in ocr_documents if str(item.get("DocumentCode")) == str(document_code)),
                None
            )
            existing_document_keys = normalize_list(
                existing_document_entry.get("DocumentKeys", []) if existing_document_entry else []
            )
            legacy_top_level_keys = normalize_list(existing_doc.get("DocumentKeys", []))
            final_keys = list(dict.fromkeys(existing_document_keys + legacy_top_level_keys + new_keys))

            current_document_entry = {
                "DocumentCode": document_code,
                "Document": documento_nome,
                "Metadatas": new_metadatas,
                "DocumentKeys": final_keys
            }

            if existing_document_entry:
                update = {
                    "$set": {
                        "OCR.GroupDocumentCode": group_document_code,
                        "OCR.GroupDocument": grupo_nome,
                        "OCR.Documents.$[doc]": current_document_entry
                    },
                    "$unset": {
                        "OCRDocumentCode": "",
                        "OCRDocument": "",
                        "OCRGroupDocumentCode": "",
                        "OCRGroupDocument": "",
                        "metadatas": "",
                        "DocumentKeys": ""
                    }
                }
                update_result = collection.update_one(
                    {"_id": existing_doc["_id"]},
                    update,
                    array_filters=[{"doc.DocumentCode": document_code}]
                )
            else:
                update = {
                    "$set": {
                        "OCR.GroupDocumentCode": group_document_code,
                        "OCR.GroupDocument": grupo_nome
                    },
                    "$push": {
                        "OCR.Documents": current_document_entry
                    },
                    "$unset": {
                        "OCRDocumentCode": "",
                        "OCRDocument": "",
                        "OCRGroupDocumentCode": "",
                        "OCRGroupDocument": "",
                        "metadatas": "",
                        "DocumentKeys": ""
                    }
                }
                update_result = collection.update_one({"_id": existing_doc["_id"]}, update)

            if update_result.matched_count > 0:
                updated_ids.append(str(existing_doc["_id"]))

        if not updated_ids:
            raise RuntimeError(f"Atualizacao nao encontrou documento para IDs: {valid_doc_ids}")

        status_value = "sucesso"
        print(f"Atualizado(s) documento(s): {', '.join(updated_ids)}")
    except Exception as error:
        print(f"Erro ao atualizar grupo {cd_grupo}/{cd_doc}: {error}")
    finally:
        df.loc[group_indexes, "status"] = status_value

df.to_excel(EXCEL_OUTPUT_PATH, index=False)
print(f"Processo finalizado. Excel salvo em: {EXCEL_OUTPUT_PATH}")
