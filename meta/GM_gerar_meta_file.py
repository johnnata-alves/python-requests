import json
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

STATUS_PENDENTE = "Pendente geração de certificado"
STATUS_PROCESSADO = "Processado"
STATUS_DUPLICADO = "Duplicado"
STATUS_SEM_TEMPLATE = "Sem TemplateId"

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
MONGO_DB = "testeMigracao"
MONGO_COLLECTION = "MetaGM"
OUTPUT_DIR = Path(__file__).resolve().parent / "meta_gm_sem_certificados"
DRY_RUN = False
MAX_WORKERS = min(32, (os.cpu_count() or 4) * 4)

def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()

def normalize_nullable_text(value: Any) -> Optional[str]:
    normalized = normalize_text(value)
    return normalized or None

def first_non_empty(details: Sequence[Dict[str, Any]], field_name: str) -> str:
    for detail in details:
        value = normalize_text(detail.get(field_name))
        if value:
            return value
    return ""

def parse_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    text = normalize_text(value)
    if not text:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return Decimal(text)
    except InvalidOperation:
        return None

def decimal_to_json_number(value: Optional[Decimal]) -> Optional[float | int]:
    if value is None:
        return None
    integral_value = value.to_integral_value()
    if value == integral_value:
        return int(integral_value)
    return float(value.quantize(Decimal("0.01")))

def parse_datetime_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")

    text = normalize_text(value)
    if not text:
        return None

    date_formats = (
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
    )
    for fmt in date_formats:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue

    return text

def build_pending_filter() -> Dict[str, Any]:
    return {"status": STATUS_PENDENTE }

def get_document_key(document: Dict[str, Any]) -> Tuple[str, str]:
    return (
        normalize_text(document.get("cd_apolice")),
        normalize_text(document.get("nr_cnpj_cpf")),
    )

def find_template_id(details: Sequence[Dict[str, Any]]) -> str:
    for detail in details:
        template_id = normalize_text(detail.get("TemplateId"))
        if template_id:
            return template_id
    return ""

def append_unique(items: List[Dict[str, Any]], item: Dict[str, Any], seen: set[Tuple[Any, ...]], key: Tuple[Any, ...]) -> None:
    if key in seen:
        return
    seen.add(key)
    items.append(item)

def collect_coberturas(details: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    coberturas: List[Dict[str, Any]] = []
    seen: set[Tuple[Any, ...]] = set()

    for detail in details:
        for indice in range(1, 11):
            descricao = normalize_text(detail.get(f"nm_cob_{indice}"))
            if not descricao:
                continue

            capital = parse_decimal(detail.get(f"nr_capital_{indice}"))
            premio = parse_decimal(detail.get(f"vl_premio_tarifario_{indice}"))
            item = {
                "Descricao": descricao,
                "Capital_Segurado": decimal_to_json_number(capital),
                "Premio_Liquido": decimal_to_json_number(premio),
            }
            key = (
                item["Descricao"],
                item["Capital_Segurado"],
                item["Premio_Liquido"],
            )
            append_unique(coberturas, item, seen, key)

    return coberturas

def collect_estipulantes(details: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    estipulantes: List[Dict[str, Any]] = []
    seen: set[Tuple[Any, ...]] = set()

    for detail in details:
        for indice in range(1, 4):
            nome = normalize_text(detail.get(f"nm_agenciador_{indice}"))
            cnpj = normalize_text(detail.get(f"nr_cnpj_agenciador_{indice}"))
            remuneracao = normalize_nullable_text(detail.get(f"nr_percetual_agenciador_{indice}"))
            if not nome and not cnpj:
                continue

            item = {
                "Nome": nome,
                "Cnpj": cnpj,
                "Tx_Remuneracao": remuneracao,
            }
            key = (item["Nome"], item["Cnpj"], item["Tx_Remuneracao"])
            append_unique(estipulantes, item, seen, key)

    return estipulantes

def collect_prolaboristas(details: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    prolaboristas: List[Dict[str, Any]] = []
    seen: set[Tuple[Any, ...]] = set()

    for detail in details:
        for indice in range(1, 3):
            nome = normalize_text(detail.get(f"nm_prolaborista_{indice}"))
            cnpj = normalize_text(detail.get(f"nr_cnpj_prolaborista_{indice}"))
            remuneracao = normalize_nullable_text(detail.get(f"nr_percentual_prolaborista_{indice}"))
            if not nome and not cnpj:
                continue

            item = {
                "Nome": nome,
                "Cnpj": cnpj,
                "Tx_Remuneracao": remuneracao,
            }
            key = (item["Nome"], item["Cnpj"], item["Tx_Remuneracao"])
            append_unique(prolaboristas, item, seen, key)

    return prolaboristas

def collect_segurados(details: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    segurados: List[Dict[str, Any]] = []
    seen: set[Tuple[Any, ...]] = set()

    for detail in details:
        nome = detail.get("nm_segurado")
        cpf = normalize_text(detail.get("nr_cpf_seg"))
        if not normalize_text(nome) and not cpf:
            continue

        item = {
            "Nome": "" if nome is None else str(nome),
            "NomeSocial": normalize_text(detail.get("nm_social_segurado")),
            "CPF": cpf,
            "Dt_Nascimento": parse_datetime_string(detail.get("dt_nascimento_seg")),
            "Endereco": "" if detail.get("nm_endereco_seg") is None else str(detail.get("nm_endereco_seg")),
            "Complemento": "" if detail.get("nm_compl_end_seg") is None else str(detail.get("nm_compl_end_seg")),
            "Bairro": "" if detail.get("nm_bairro_seg") is None else str(detail.get("nm_bairro_seg")),
            "Cidade": "" if detail.get("nm_cidade_seg") is None else str(detail.get("nm_cidade_seg")),
            "Uf": normalize_text(detail.get("nm_uf_seg")),
            "CEP": normalize_text(detail.get("nr_cep_seg")),
            "Email": "",
            "Celular": "",
        }
        key = (item["CPF"], item["Nome"], item["Dt_Nascimento"])
        append_unique(segurados, item, seen, key)

    return segurados

def build_corretor(details: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "Corretora": first_non_empty(details, "nm_corretor"),
        "CNPJ": first_non_empty(details, "nr_cnpj_corretor"),
        "RegistroSUSEP": first_non_empty(details, "nr_susep_corretor"),
        "Endereco": None,
        "Bairro": None,
        "Cidade": None,
        "UF": None,
        "CEP": None,
    }

def build_veiculo(details: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "Marca": normalize_nullable_text(first_non_empty(details, "nm_marca")),
        "Modelo": normalize_nullable_text(first_non_empty(details, "nm_modelo")),
        "Chassi": normalize_nullable_text(first_non_empty(details, "nr_chassi")),
        "Placa": normalize_nullable_text(first_non_empty(details, "nr_placa")),
        "AnoFabricacao": normalize_nullable_text(first_non_empty(details, "nr_ano_fabricacao")),
    }

def build_sub_estipulante(details: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    endereco = normalize_text(first_non_empty(details, "Endereco_Sub"))
    numero = normalize_text(first_non_empty(details, "Num_Endereco_Sub"))
    endereco_composto = ", ".join([parte for parte in [endereco, numero] if parte]) or None

    return {
        "Nome": first_non_empty(details, "Nome_Sub"),
        "Cnpj": first_non_empty(details, "CNPJ_Sub"),
        "Endereco": endereco_composto,
        "Complemento": normalize_nullable_text(first_non_empty(details, "Compl_Sub")),
        "Bairro": normalize_nullable_text(first_non_empty(details, "Bairro_Sub")),
        "Cidade": normalize_nullable_text(first_non_empty(details, "Cidade_Sub")),
        "UF": normalize_nullable_text(first_non_empty(details, "Uf_Sub")),
        "CEP": normalize_nullable_text(first_non_empty(details, "Cep_Sub")),
        "Telefone": normalize_nullable_text(first_non_empty(details, "Tel_Sub")),
        "Tx_Remuneracao": None,
    }

def build_payload(document: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    details = document.get("details") or []
    if not details:
        return None

    template_id = find_template_id(details)
    if not template_id:
        return None

    premio_liquido = parse_decimal(first_non_empty(details, "vl_premio_total")) or Decimal("0")
    valor_iof = parse_decimal(first_non_empty(details, "nr_iof")) or Decimal("0")
    premio_bruto = premio_liquido + valor_iof

    nr_certificado = normalize_text(first_non_empty(details, "nr_certificado_individual"))
    nr_certificado_json: Any = int(nr_certificado) if nr_certificado.isdigit() else nr_certificado

    return {
        "ProcessoSUSÈP": first_non_empty(details, "nr_susep_1"),
        "Corretor": build_corretor(details),
        "Veiculo": build_veiculo(details),
        "SubEstipulante": build_sub_estipulante(details),
        "Nr_Certificado": nr_certificado_json,
        "Nr_Apolice": normalize_text(document.get("cd_apolice")) or first_non_empty(details, "nr_apolice_1"),
        "Nr_Apolice_Agrupadora": first_non_empty(details, "nr_apolice_2"),
        "Dt_Emissao": parse_datetime_string(first_non_empty(details, "dt_emissao")),
        "Nr_Proposta": "" if first_non_empty(details, "nr_proposta") == "" else str(next((detail.get("nr_proposta") for detail in details if detail.get("nr_proposta") is not None), "")),
        "Dt_Inicio_Vigencia": parse_datetime_string(first_non_empty(details, "dt_inicio_vigencia")),
        "Dt_Fim_Vigencia": parse_datetime_string(first_non_empty(details, "dt_fim_vigencia")),
        "Cod_Produto": first_non_empty(details, "cd_produto"),
        "Template_Id": template_id,
        "Nm_Produto": first_non_empty(details, "nm_produto"),
        "Vl_Premio_Liquido_Total": decimal_to_json_number(premio_liquido),
        "Vl_IOF": decimal_to_json_number(valor_iof),
        "Vl_Premio_Bruto_Total": decimal_to_json_number(premio_bruto),
        "Segurados": collect_segurados(details),
        "Coberturas": collect_coberturas(details),
        "Capitalizacao": None,
        "Estipulantes": collect_estipulantes(details),
        "ProLaboristas": collect_prolaboristas(details),
    }

def load_existing_json(file_path: Path) -> List[Dict[str, Any]]:
    if not file_path.exists():
        return []

    with file_path.open("r", encoding="utf-8") as file:
        content = json.load(file)

    if not isinstance(content, list):
        raise ValueError(f"Arquivo existente inválido: {file_path}")

    return content

def update_status(collection, ids: Iterable[ObjectId], status: str, lote_nome: str = None) -> int:
    ids = list(ids)
    if not ids:
        return 0

    set_fields = {"status": status, "updatedAt": datetime.utcnow()}
    if lote_nome:
        set_fields["lote_nome"] = lote_nome

    result = collection.update_many(
        {"_id": {"$in": ids}},
        {"$set": set_fields},
    )
    return result.modified_count

def load_processed_keys(collection) -> set[Tuple[str, str]]:
    processed_keys: set[Tuple[str, str]] = set()
    cursor = collection.find(
        {"status": STATUS_PROCESSADO},
        {"cd_apolice": 1, "nr_cnpj_cpf": 1},
    )
    try:
        for document in cursor:
            key = get_document_key(document)
            if key[0] and key[1]:
                processed_keys.add(key)
    finally:
        cursor.close()

    return processed_keys

def process_pending_document(document: Dict[str, Any]) -> Tuple[str, ObjectId, Optional[Dict[str, Any]]]:
    payload = build_payload(document)
    return get_document_key(document)[0], document["_id"], payload

def main() -> None:
    if not MONGO_URI:
        raise ValueError("Defina a variável de ambiente PRD_MONGO_SA_EAST.")
    if MAX_WORKERS <= 0:
        raise ValueError("MAX_WORKERS deve ser maior que zero.")

    if not DRY_RUN:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    client = MongoClient(MONGO_URI)
    collection = client[MONGO_DB][MONGO_COLLECTION]

    pending_filter = build_pending_filter()
    total_pending = collection.count_documents(pending_filter)
    print(f"Registros pendentes encontrados: {total_pending}")
    print(f"Diretório de saída: {OUTPUT_DIR}")
    print(f"Threads para montagem de payload: {MAX_WORKERS}")

    grouped_payloads: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    grouped_ids: Dict[str, List[ObjectId]] = defaultdict(list)
    duplicate_ids: List[ObjectId] = []
    sem_template_ids: List[ObjectId] = []
    seen_keys: set[Tuple[str, str]] = set()
    documents_to_process: List[Dict[str, Any]] = []
    processed_keys = load_processed_keys(collection)

    cursor = collection.find(pending_filter).sort([("cd_apolice_num", 1), ("_id", 1)])

    try:
        with tqdm(total=total_pending, desc="Classificando registros", unit="registro") as progress:
            for document in cursor:
                key = get_document_key(document)

                if key in seen_keys or key in processed_keys:
                    duplicate_ids.append(document["_id"])
                    progress.update(1)
                    continue

                seen_keys.add(key)
                documents_to_process.append(document)
                progress.update(1)
    finally:
        cursor.close()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        iterator = executor.map(process_pending_document, documents_to_process)
        for _, document_id, payload in tqdm(
            iterator,
            total=len(documents_to_process),
            desc="Montando payloads",
            unit="registro",
        ):
            if payload is None:
                sem_template_ids.append(document_id)
                continue

            template_id = str(payload["Template_Id"])
            grouped_payloads[template_id].append(payload)
            grouped_ids[template_id].append(document_id)

    arquivos_gerados = 0
    documentos_processados = 0
    erros_arquivo = 0
    lote_timestamp = datetime.now().strftime("%d%m%Y-%H%M")

    for template_id in tqdm(sorted(grouped_payloads.keys()), desc="Gerando arquivos", unit="arquivo"):
        lote_nome = f"Id_{template_id}_MetaFile_GM_sem_certificados_{lote_timestamp}"
        file_path = OUTPUT_DIR / f"{lote_nome}.json"
        novos_registros = grouped_payloads[template_id]

        if DRY_RUN:
            print(
                f"[dry-run] Arquivo {file_path.name} receberia {len(novos_registros)} novos registros"
            )
            arquivos_gerados += 1
            documentos_processados += len(grouped_ids[template_id])
            continue

        try:
            existentes = load_existing_json(file_path)
            conteudo_final = existentes + novos_registros
            with file_path.open("w", encoding="utf-8") as file:
                json.dump(conteudo_final, file, ensure_ascii=False, indent=2)

            arquivos_gerados += 1
            documentos_processados += update_status(
                collection,
                grouped_ids[template_id],
                STATUS_PROCESSADO,
                lote_nome,
            )
        except Exception as exc:
            erros_arquivo += 1
            print(f"[ERRO] Falha ao gerar {file_path.name}: {exc}")

    duplicados_atualizados = 0
    sem_template_atualizados = 0

    if DRY_RUN:
        duplicados_atualizados = len(duplicate_ids)
        sem_template_atualizados = len(sem_template_ids)
    else:
        duplicados_atualizados = update_status(collection, duplicate_ids, STATUS_DUPLICADO)
        sem_template_atualizados = update_status(collection, sem_template_ids, STATUS_SEM_TEMPLATE)

    print(
        "Resumo | "
        f"arquivos gerados: {arquivos_gerados} | "
        f"documentos marcados como {STATUS_PROCESSADO}: {documentos_processados} | "
        f"documentos marcados como {STATUS_DUPLICADO}: {duplicados_atualizados} | "
        f"documentos marcados como {STATUS_SEM_TEMPLATE}: {sem_template_atualizados} | "
        f"erros de arquivo: {erros_arquivo}"
    )

    client.close()

if __name__ == "__main__":
    main()
