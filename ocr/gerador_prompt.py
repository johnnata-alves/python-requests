import os
import re
import time
import unicodedata
from datetime import datetime

from dotenv import load_dotenv
import requests
from pymongo import MongoClient
from requests.exceptions import SSLError as RequestsSSLError

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "ClaimEngine")
DB_OCR = os.getenv("DB_OCR", "DocumentTypification")
TYPO_COLLECTION_NAME = os.getenv("TYPO_COLLECTION_NAME", "TypificationDocument")
MAPPINGS_COLLECTION_NAME = os.getenv("MAPPINGS_COLLECTION_NAME", "DocumentTypeMappings")
PROMPT_COLLECTION_NAME = os.getenv("PROMPT_COLLECTION_NAME", "DocumentPrompt")
PROMPT_AUDIT_COLLECTION_NAME = os.getenv("PROMPT_AUDIT_COLLECTION_NAME", "DocumentPromptAudit")

COPILOT_API_KEY = os.getenv("COPILOT_API_KEY")
COPILOT_MODEL = os.getenv("COPILOT_MODEL", "gpt-5.1")
COPILOT_INSTRUCTIONS = (
	"Retorne apenas o prompt final em texto puro, sem markdown, sem cercas de codigo e sem comentarios extras."
)
DIRECT_LINE_BASE_URL = os.getenv("DIRECT_LINE_BASE_URL", "https://directline.botframework.com/v3/directline")
DIRECT_LINE_SSL_VERIFY = os.getenv("DIRECT_LINE_SSL_VERIFY", "true").strip().lower() not in ["0", "false", "no", "off"]
DIRECT_LINE_CA_BUNDLE = os.getenv("DIRECT_LINE_CA_BUNDLE")
CLIENT_AI_USER_ID = "document-prompt-generator"
POLL_ATTEMPTS = 30
POLL_INTERVAL_SECONDS = 1
DEFAULT_INITIAL_VERSION = os.getenv("DEFAULT_INITIAL_VERSION", "1.0.0")

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
			"Content-Type": "application/json",
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
			timeout=30,
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
			"channelData": {"model": self.model},
		}

		post_response = self._request(
			"POST",
			f"{self.base_url}/conversations/{conversation_id}/activities",
			headers=self._headers(),
			json=activity_payload,
			timeout=30,
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
				timeout=30,
			)
			activities_response.raise_for_status()
			payload = activities_response.json()
			watermark = payload.get("watermark")

			activities = payload.get("activities") or []
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

def strip_accents(text):
	text = unicodedata.normalize("NFKD", str(text or ""))
	return "".join(char for char in text if not unicodedata.combining(char))

def normalize_key(text):
	text = strip_accents(text).lower()
	return re.sub(r"[^a-z0-9]+", "", text)

def normalize_field_name(text):
	text = strip_accents(text).lower().strip()
	text = re.sub(r"[^a-z0-9]+", "_", text)
	return text.strip("_")

def clean_prompt_text(text):
	cleaned = (text or "").strip()
	if cleaned.startswith("```"):
		cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
		cleaned = re.sub(r"\s*```$", "", cleaned)
	return cleaned.strip()

def bump_patch_version(version):
	raw_version = str(version or DEFAULT_INITIAL_VERSION).strip()
	parts = raw_version.split(".")
	while len(parts) < 3:
		parts.append("0")

	try:
		major = int(parts[0])
		minor = int(parts[1])
		patch = int(parts[2]) + 1
	except ValueError:
		return DEFAULT_INITIAL_VERSION

	return f"{major}.{minor}.{patch}"

def build_output_example(metadata_items):
	output = {}
	for metadata in metadata_items:
		key = normalize_field_name(metadata)
		if key:
			output[key] = ""
	return output

def build_generation_prompt(document_type, metadata_items):
	metadata_lines = []
	for metadata_name in metadata_items:
		if not metadata_name:
			continue
		metadata_lines.append(f"- {metadata_name} ")

	metadata_block = "\n".join(metadata_lines) if metadata_lines else "- sem metadados mapeados"

	output_example = build_output_example(metadata_items)

	return f"""
Gere um prompt final, em portugues do Brasil, para extracao de dados estruturados via OCR.

O prompt final sera armazenado em banco e usado depois por outro processo. Portanto, responda somente com o texto do prompt final.

Contexto do documento:
- tipo_documento: {document_type}

O prompt final precisa conter exatamente estas instrucoes, adaptadas ao documento:

Exemplo:
[ Voce e um especialista em extracao de dados estruturados a partir de textos OCR de documentos brasileiros.

Vou te fornecer um texto bruto extraido via OCR de um {document_type}.
Esse texto pode conter ruidos, erros de OCR, caracteres incorretos, quebras de linha e desordem.

Sua tarefa e:
- Interpretar o conteudo do OCR
- Corrigir possiveis erros comuns de leitura
- Extrair os metadados solicitados
- Retornar exclusivamente um JSON valido, sem explicacoes adicionais
- Deve seguir exatamente o exemplo citado

Padronizacao obrigatoria dos campos de saida:
- Todas as chaves do JSON devem estar em minusculo
- Sem acentos
- Com underscore (_) no lugar de espacos ]

Metadados a extrair:
{metadata_block}

Formato de saida esperado:
{output_example}

Regras adicionais:
- Nao invente informacoes ausentes no OCR.
- Quando um campo nao puder ser identificado com seguranca, não retorne o metadado
- Caso tenha CPF/CNPJ, não retornar com mascara
- Preserve datas no formato mais fiel possivel ao documento.
- Enriqueça o prompt com orientacoes e verificacoes importantes para esse tipo de documento, considerando campos, sinais, identificadores, datas, orgaos emissores, numeracoes, filiacoes, localidades e outros elementos que normalmente sao relevantes para interpretar corretamente esse arquivo.
- Se fizer sentido para esse tipo documental, inclua no prompt instrucoes para tentar identificar informacoes relevantes adicionais, mesmo que nao estejam na lista base de metadados, desde que sejam uteis para melhorar a interpretacao e a extracao futura.
- Oriente o modelo final a priorizar os metadados explicitamente listados, mas aproveitar tambem o contexto documental para reconhecer informacoes complementares importantes.
- O resultado final deve ser apenas um JSON valido.
""".strip()

def metadata_key_set(metadata_items):
	return {item.get("metadata") for item in metadata_items}

def append_unique_metadatas(target_items, new_items):
	existing_keys = metadata_key_set(target_items)
	for metadata in new_items:
		metadata_name = metadata.get("metadata")
		if metadata_name and metadata_name not in existing_keys:
			target_items.append(metadata)
			existing_keys.add(metadata_name)

def document_matches_source(document, normalized_source):
	document_keys = document.get("DocumentKeys") or []
	normalized_keys = {normalize_key(key) for key in document_keys if key}
	return normalized_source in normalized_keys

def build_match_entry(mapping, document, source_document_type):
	return {
		"source_document_type": source_document_type,
		"document_type": (document.get("Document") or mapping.get("document") or source_document_type).strip(),
		"mapping_id": mapping.get("_id"),
		"erp_document_id": mapping.get("ERPDocumentId"),
		"document_name": mapping.get("documentName"),
		"metadatas": [],
	}

def iter_ocr_documents(mapping):
	return (mapping.get("OCR") or {}).get("Documents") or []

def find_matching_documents(mappings_collection, source_document_type):
	normalized_source = normalize_key(source_document_type)
	matches = {}

	for mapping in mappings_collection.find({"isActive": True}):
		for document in iter_ocr_documents(mapping):
			if not document_matches_source(document, normalized_source):
				continue

			match_entry = build_match_entry(mapping, document, source_document_type)
			document_type = match_entry["document_type"]
			if document_type not in matches:
				matches[document_type] = match_entry

			append_unique_metadatas(matches[document_type]["metadatas"], document.get("Metadatas") or [])

	return list(matches.values())

def upsert_document_prompt(prompt_collection, audit_collection, document_info, prompt_text):
	now = datetime.now()
	document_type = document_info["document_type"]
	source_document_type = document_info["source_document_type"]

	existing = prompt_collection.find_one({"DocumentType": document_type})
	if existing:
		audit_payload = {key: value for key, value in existing.items() if key != "_id"}
		audit_payload.update(
			{
				"DocumentPromptId": existing.get("_id"),
				"ArchivedAt": now,
				"SourceDocumentType": source_document_type,
			}
		)
		audit_collection.insert_one(audit_payload)

		new_version = bump_patch_version(existing.get("Version"))
		prompt_collection.update_one(
			{"_id": existing["_id"]},
			{
				"$set": {
					"Prompt": prompt_text,
					"Version": new_version,
					"UpdatedAt": now,
					"SourceDocumentType": source_document_type,
				}
			},
		)
		return "updated", new_version

	prompt_collection.insert_one(
		{
			"DocumentType": document_type,
			"Prompt": prompt_text,
			"Version": DEFAULT_INITIAL_VERSION,
			"CreatedAt": now,
			"UpdatedAt": now,
			"SourceDocumentType": source_document_type,
		}
	)
	return "inserted", DEFAULT_INITIAL_VERSION

def main():

	mongo = MongoClient(MONGO_URI)
	db = mongo[DB_NAME]
	dbOCR = mongo[DB_OCR]

	typification_collection = dbOCR[TYPO_COLLECTION_NAME]
	prompt_collection = dbOCR[PROMPT_COLLECTION_NAME]

	ai_client = CopilotDirectLineClient(
		api_key=COPILOT_API_KEY,
		model=COPILOT_MODEL,
		instructions=COPILOT_INSTRUCTIONS,
		verify_ssl=DIRECT_LINE_CA_BUNDLE if DIRECT_LINE_CA_BUNDLE else DIRECT_LINE_SSL_VERIFY,
	)

	all_types = set()
	for doc in prompt_collection.find({"Prompt": None}):
		doc_type = doc.get("DocumentType")
		if isinstance(doc_type, str) and doc_type.strip():
			all_types.add(doc_type.strip())

	if not all_types:
		print("Nenhum DocumentType com Prompt nulo encontrado.")
		return

	total_inserted = 0
	total_skipped = 0

	for doc_type in sorted(all_types):
		now = datetime.now()
		existing = prompt_collection.find_one({"DocumentType": doc_type})

		if existing and existing.get("Prompt"):
			total_skipped += 1
			print(f"[SKIPPED - Prompt já existe] {doc_type}")
			continue

		mappings_collection = db["DocumentTypeMappings"]
		mapping = mappings_collection.find_one({"OCR.Documents.DocumentKeys": doc_type})
		metadata_items = []
		if mapping:
			ocr_docs = (mapping.get("OCR") or {}).get("Documents") or []
			for ocr_doc in ocr_docs:
				if doc_type in (ocr_doc.get("Document"), *(ocr_doc.get("DocumentKeys") or [])):
					for meta in ocr_doc.get("Metadatas", []):
						meta_name = meta.get("metadata")
						if meta_name and meta_name not in metadata_items:
							metadata_items.append(meta_name)

		generation_prompt = build_generation_prompt(
			doc_type,
			metadata_items
		)

		max_retries = 3
		for attempt in range(max_retries):
			prompt_text = clean_prompt_text(ai_client.ask(generation_prompt))
			if prompt_text.strip().lower() != "contentfiltered":
				break
			print(f"[WARN] Resposta 'ContentFiltered' recebida para {doc_type}, tentativa {attempt+1}/{max_retries}")
			time.sleep(2)
		else:
			total_skipped += 1
			print(f"[ERRO] Copilot retornou 'ContentFiltered' para {doc_type} em todas as tentativas")
			continue

		if existing:
			prompt_collection.update_one(
				{"_id": existing["_id"]},
				{"$set": {"Prompt": prompt_text, "UpdatedAt": now}}
			)
			total_inserted += 1
			print(f"[UPDATED - Prompt era nulo] {doc_type}")
		else:
			prompt_doc = {
				"DocumentType": doc_type,
				"Prompt": prompt_text,
				"Version": DEFAULT_INITIAL_VERSION,
				"CreatedAt": now,
				"UpdatedAt": now,
				"NextSteps": [
					{"Next": "MetadatasExtraction", "Model": "gpt-5.1-mini"}
				],
				"Variations": [doc_type],
			}
			prompt_collection.insert_one(prompt_doc)
			total_inserted += 1
			print(f"[INSERTED] {doc_type}")

	print(f"Concluido | prompts inseridos: {total_inserted} | prompts atualizados: {total_skipped}")

if __name__ == "__main__":
	main()
