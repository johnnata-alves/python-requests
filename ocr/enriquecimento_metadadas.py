import ast
import json
import os
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
import requests
import urllib3
from pymongo import MongoClient
from requests.exceptions import SSLError as RequestsSSLError

load_dotenv()

MONGO_URI = os.getenv("HML_MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "ClaimEngine")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "DocumentTypeMappingsVariations")

COPILOT_API_KEY = os.getenv("COPILOT_API_KEY")
COPILOT_MODEL = os.getenv("COPILOT_MODEL", "gpt-4-o")
COPILOT_INSTRUCTIONS = "Return ONLY a JSON payload with the requested fields."
DIRECT_LINE_BASE_URL = os.getenv("DIRECT_LINE_BASE_URL", "https://directline.botframework.com/v3/directline")
DIRECT_LINE_SSL_VERIFY = os.getenv("DIRECT_LINE_SSL_VERIFY", "true").strip().lower() not in ["0", "false", "no", "off"]
DIRECT_LINE_CA_BUNDLE = os.getenv("DIRECT_LINE_CA_BUNDLE")
CLIENT_AI_USER_ID = "metadata-enrichment"
POLL_ATTEMPTS = int(os.getenv("POLL_ATTEMPTS", "30"))
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "1"))
NEW_VARIATIONS_TARGET = int(os.getenv("NEW_VARIATIONS_TARGET", "50"))
REQUEST_SLEEP_SECONDS = float(os.getenv("REQUEST_SLEEP_SECONDS", "0.2"))
MIN_VARIATIONS_TO_SKIP = int(os.getenv("MIN_VARIATIONS_TO_SKIP", "200"))
CACHE_ENABLED = os.getenv("CACHE_ENABLED", "true").strip().lower() not in ["0", "false", "no", "off"]
CACHE_FILE_PATH = os.getenv("CACHE_FILE_PATH", "enriquecimento_metadadas_cache.json")
SUPPRESS_WARNINGS = os.getenv("SUPPRESS_WARNINGS", "true").strip().lower() not in ["0", "false", "no", "off"]
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))

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
    return value is None or (isinstance(value, str) and not value.strip())

def normalize(value):
    text = str(value).strip().lower()
    return "".join(ch for ch in text if ch.isalnum())

def normalize_list(values):
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if not is_blank(value)]

def unique_merge(values):
    ordered = []
    seen = set()
    for value in values:
        key = normalize(value)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(str(value).strip())
    return ordered

def build_cache_key(metadata_name, description, field_type, existing_variations):
    payload = {
        "metadata": str(metadata_name or "").strip().lower(),
        "description": str(description or "").strip().lower(),
        "field_type": str(field_type or "").strip().lower(),
        "existing_variations": sorted({normalize(item) for item in existing_variations if not is_blank(item)}),
        "target": NEW_VARIATIONS_TARGET,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)

def load_cache(cache_file_path):
    if not CACHE_ENABLED:
        return {}
    if not os.path.exists(cache_file_path):
        return {}
    try:
        with open(cache_file_path, "r", encoding="utf-8") as cache_file:
            content = json.load(cache_file)
            return content if isinstance(content, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def save_cache(cache_file_path, cache_data):
    if not CACHE_ENABLED:
        return
    try:
        with open(cache_file_path, "w", encoding="utf-8") as cache_file:
            json.dump(cache_data, cache_file, ensure_ascii=False, indent=2)
    except OSError as error:
        print(f"[cache] Falha ao salvar cache em '{cache_file_path}': {error}")

def generate_new_variations(ai_client, metadata_name, description, field_type, existing_variations, cache_data, cache_lock):
    cache_key = build_cache_key(metadata_name, description, field_type, existing_variations)
    if CACHE_ENABLED:
        with cache_lock:
            if cache_key in cache_data:
                cached_values = normalize_list(cache_data.get(cache_key, []))
                print(f"[cache] HIT para metadata='{metadata_name}'")
                return cached_values[:NEW_VARIATIONS_TARGET]

    print(f"[cache] MISS para metadata='{metadata_name}'")
    existing_json = json.dumps(existing_variations, ensure_ascii=False)

    prompt = f"""
Voce deve gerar EXATAMENTE {NEW_VARIATIONS_TARGET} novas variacoes para um metadado de OCR.
Retorne SOMENTE JSON valido e sem markdown no formato:
{{
  "new_variations": ["..."]
}}

Regras obrigatorias:
- Gerar {NEW_VARIATIONS_TARGET} variacoes diferentes entre si.
- Nao repetir nenhuma variacao existente.
- Nao repetir variacoes ja normalizadas (ignorando acentos, caixa, espacos e pontuacao).
- Variacoes devem ser em portugues e relevantes para o metadado informado.
- Pode incluir sinonimos usuais
- Retornar sempre todas opções com underline, sem espaço, sem caracteres especiais, sem acentos e tudo minúsculo.
- Sempre incluir variações com 1, 2 e 3 palavras
- Cada item deve ser string nao vazia.
- Deve adicionar transformacoes simples como: Descrição do Lançamento -> descricao_do_lancamento e descricao_lancamento

Metadado: {metadata_name}
Descricao: {description or ""}
Variacoes existentes: {existing_json}
"""

    response = ai_client.ask(prompt)
    parsed = parse_ai_json(response)
    if not parsed:
        raise ValueError("Resposta da IA nao esta em JSON valido")

    raw_new = normalize_list(parsed.get("new_variations", []))
    if not raw_new:
        return []

    existing_normalized = {normalize(item) for item in existing_variations}
    filtered = []
    seen_new = set()

    for value in raw_new:
        key = normalize(value)
        if not key:
            continue
        if key in existing_normalized or key in seen_new:
            continue
        seen_new.add(key)
        filtered.append(value)

    result = filtered[:NEW_VARIATIONS_TARGET]
    if CACHE_ENABLED:
        with cache_lock:
            cache_data[cache_key] = result
    return result

def process_document(
    mongo_doc,
    total_docs,
    collection,
    ai_client,
    cache_data,
    cache_lock,
    total_target_metadatas,
    progress_state,
    progress_lock,
):
    doc_id = str(mongo_doc.get("_id"))
    doc_number = progress_state["doc_index_by_id"].get(doc_id, 0)
    print(f"[doc] Processando documento {doc_number}/{total_docs} - _id={doc_id}")

    changed = False
    metadata_processed = 0
    metadata_updated = 0
    total_variations_added = 0

    metadata_name = str(mongo_doc.get("metadata", "")).strip()
    description = mongo_doc.get("Descrição") or mongo_doc.get("Descricao") or ""

    if not metadata_name:
        return {
            "updated_doc": False,
            "metadata_processed": 0,
            "metadata_updated": 0,
            "total_variations_added": 0,
        }

    metadata_processed = 1
    current_variations = unique_merge(normalize_list(mongo_doc.get("variations", [])))

    if len(current_variations) >= MIN_VARIATIONS_TO_SKIP:
        return {
            "updated_doc": False,
            "metadata_processed": metadata_processed,
            "metadata_updated": 0,
            "total_variations_added": 0,
        }

    with progress_lock:
        progress_state["metadata_targets_processed"] += 1
        metadata_targets_processed = progress_state["metadata_targets_processed"]

    progress_pct = (metadata_targets_processed / total_target_metadatas * 100) if total_target_metadatas else 100.0
    print(
        f"[progresso] {metadata_targets_processed}/{total_target_metadatas} ({progress_pct:.2f}%) | "
        f"doc={doc_id} | metadata='{metadata_name}' | variacoes_atuais={len(current_variations)}"
    )

    try:
        new_variations = generate_new_variations(
            ai_client,
            metadata_name=metadata_name,
            description=description,
            field_type="",
            existing_variations=current_variations,
            cache_data=cache_data,
            cache_lock=cache_lock,
        )
    except Exception as error:
        print(
            f"Erro ao enriquecer metadata '{metadata_name}' no documento {mongo_doc.get('_id')}: {error}"
        )
        return {
            "updated_doc": False,
            "metadata_processed": metadata_processed,
            "metadata_updated": 0,
            "total_variations_added": 0,
        }

    if not new_variations:
        return {
            "updated_doc": False,
            "metadata_processed": metadata_processed,
            "metadata_updated": 0,
            "total_variations_added": 0,
        }

    merged = unique_merge(current_variations + new_variations)
    added_count = len(merged) - len(current_variations)
    if added_count > 0:
        changed = True
        metadata_updated = 1
        total_variations_added = added_count
        print(
            f"[ok] metadata='{metadata_name}' | novas_adicionadas={added_count} | total_final={len(merged)}"
        )
        time.sleep(REQUEST_SLEEP_SECONDS)

    if changed:
        update_result = collection.update_one(
            {"_id": mongo_doc["_id"]},
            {"$set": {"variations": merged}}
        )
        if update_result.matched_count > 0:
            print(f"[save] Documento atualizado com sucesso: _id={doc_id}")
            updated_doc = True
        else:
            print(f"[save] Nenhum documento atualizado: _id={doc_id}")
            updated_doc = False
    else:
        print(f"[doc] Sem alteracoes para _id={doc_id}")
        updated_doc = False

    return {
        "updated_doc": updated_doc,
        "metadata_processed": metadata_processed,
        "metadata_updated": metadata_updated,
        "total_variations_added": total_variations_added,
    }

def validate_config():
    if not MONGO_URI:
        raise ValueError("MONGO_URI nao configurada.")
    if not COPILOT_API_KEY:
        raise ValueError("COPILOT_API_KEY nao configurada.")

def configure_warnings():
    if not SUPPRESS_WARNINGS:
        return

    warnings.filterwarnings("ignore")
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def main():
    validate_config()
    configure_warnings()

    print("[inicio] Iniciando enriquecimento de metadados")
    print(f"[config] DB={DB_NAME} | Collection={COLLECTION_NAME} | MinVariationsToSkip={MIN_VARIATIONS_TO_SKIP} | NewVariationsTarget={NEW_VARIATIONS_TARGET}")
    print(f"[config] CacheEnabled={CACHE_ENABLED} | CacheFile={CACHE_FILE_PATH}")
    print(f"[config] MaxWorkers={MAX_WORKERS}")

    cache_data = load_cache(CACHE_FILE_PATH)
    print(f"[cache] Entradas carregadas: {len(cache_data)}")

    ai_client = CopilotDirectLineClient(
        api_key=COPILOT_API_KEY,
        model=COPILOT_MODEL,
        instructions=COPILOT_INSTRUCTIONS,
        verify_ssl=DIRECT_LINE_CA_BUNDLE if DIRECT_LINE_CA_BUNDLE else DIRECT_LINE_SSL_VERIFY
    )

    mongo = MongoClient(MONGO_URI)
    db = mongo[DB_NAME]
    collection = db[COLLECTION_NAME]

    query = {"metadata": {"$exists": True, "$ne": ""}}
    projection = {"_id": 1, "metadata": 1, "Descrição": 1, "Descricao": 1, "variations": 1}
    mongo_docs = list(collection.find(query, projection))

    total_target_metadatas = 0
    for mongo_doc in mongo_docs:
        metadata_name = str(mongo_doc.get("metadata", "")).strip()
        if not metadata_name:
            continue

        current_variations = unique_merge(normalize_list(mongo_doc.get("variations", [])))
        if len(current_variations) < MIN_VARIATIONS_TO_SKIP:
            total_target_metadatas += 1

    print(f"[scan] Documentos encontrados: {len(mongo_docs)}")
    print(f"[scan] Metadados elegiveis para enriquecimento: {total_target_metadatas}")

    total_docs = len(mongo_docs)
    updated_docs = 0
    metadata_processed = 0
    metadata_updated = 0
    total_variations_added = 0
    cache_lock = threading.Lock()
    progress_lock = threading.Lock()
    progress_state = {
        "metadata_targets_processed": 0,
        "doc_index_by_id": {str(doc.get("_id")): index for index, doc in enumerate(mongo_docs, start=1)}
    }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(
                process_document,
                mongo_doc,
                total_docs,
                collection,
                ai_client,
                cache_data,
                cache_lock,
                total_target_metadatas,
                progress_state,
                progress_lock,
            )
            for mongo_doc in mongo_docs
        ]

        for future in as_completed(futures):
            try:
                result = future.result()
                metadata_processed += result["metadata_processed"]
                metadata_updated += result["metadata_updated"]
                total_variations_added += result["total_variations_added"]
                if result["updated_doc"]:
                    updated_docs += 1
            except Exception as error:
                print(f"[erro] Falha na thread de processamento: {error}")

    metadata_targets_processed = progress_state["metadata_targets_processed"]

    save_cache(CACHE_FILE_PATH, cache_data)
    print(f"[cache] Entradas finais no cache: {len(cache_data)}")

    print("[fim] Processamento concluido")
    print(f"Documentos lidos: {total_docs}")
    print(f"Documentos atualizados: {updated_docs}")
    print(f"Metadados processados: {metadata_processed}")
    print(f"Metadados elegiveis processados: {metadata_targets_processed}/{total_target_metadatas}")
    print(f"Metadados enriquecidos: {metadata_updated}")
    print(f"Total de novas variacoes adicionadas: {total_variations_added}")

if __name__ == "__main__":
    main()
