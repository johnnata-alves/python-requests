import json
import os
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bson import ObjectId
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

STATUS_PENDENTE = "Pendente geração de certificado"
STATUS_PROCESSADO = "Processado"
STATUS_SEM_TEMPLATE = "Sem TemplateId"
STATUS_FORA_CORTE = "Fora do corte"

MONGO_URI = os.getenv("PRD_MONGO_SA_EAST")
MONGO_DB = "testeMigracao"
MONGO_COLLECTION = "MetaPanProtege"
OUTPUT_DIR = Path(__file__).resolve().parent / "PanProtege_meta_sem_certificados"
DRY_RUN = False

DATA_CORTE = {
    "218": datetime(2025, 12, 1),
    "274": datetime(2025, 12, 1),
    "246": datetime(2025, 12, 4),
    "342": datetime(2025, 12, 5),
    "325": datetime(2025, 12, 5),
    "365": datetime(2025, 12, 8),
    "251": datetime(2025, 12, 11),
    "370": datetime(2025, 12, 11),
    "360": datetime(2026, 1, 6),
    "371": datetime(2026, 1, 12),
    "301": datetime(2026, 2, 18),
    "302": datetime(2026, 2, 18),
    "200": datetime(2026, 3, 4),
    "215": datetime(2026, 3, 4),
    "225": datetime(2026, 3, 5),
    "260": datetime(2026, 3, 5),
    "272": datetime(2026, 3, 6),
    "310": datetime(2026, 3, 12),
}

def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()

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

def decimal_to_json(value: Optional[Decimal]):
    if value is None:
        return None
    integral = value.to_integral_value()
    if value == integral:
        return int(integral)
    return float(value.quantize(Decimal("0.01")))

def first_value(detail: dict, *keys: str) -> Any:
    for key in keys:
        value = detail.get(key)
        if value not in (None, ""):
            return value
    return None

def parse_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")

    text = normalize_text(value)
    if not text:
        return None

    formats = ("%d/%m/%Y", "%d%m%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    return text

def parse_date_obj(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    text = normalize_text(value)
    if not text:
        return None

    formats = ("%d/%m/%Y", "%d%m%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None

def build_pending_filter() -> dict:
    return {
        "details.0": {"$exists": True},
        "status": STATUS_PENDENTE,
    }

def collect_coberturas(detail: dict) -> List[dict]:
    coberturas = []
    for i in range(1, 12):
        descricao = normalize_text(detail.get(f"nm_cob_{i}"))
        if not descricao:
            continue
        capital = parse_decimal(detail.get(f"nr_capital_{i}"))
        premio = parse_decimal(detail.get(f"vl_premio_tarifario_{i}"))
        coberturas.append({
            "Descricao": descricao,
            "Capital_Segurado": decimal_to_json(capital),
            "Premio_Liquido": decimal_to_json(premio),
        })
    return coberturas

def collect_prolaboristas(detail: dict) -> List[dict]:
    prolaboristas = []
    for i in range(1, 3):
        nome = normalize_text(detail.get(f"nm_prolaborista_{i}"))
        cnpj = normalize_text(detail.get(f"nr_cnpj_prolaborista_{i}"))
        if not nome and not cnpj:
            continue
        prolaboristas.append({
            "NomeProLaborista": nome,
            "CNPJ": cnpj,
            "Remuneracao": normalize_text(
                first_value(
                    detail,
                    f"nr_percentual_prolaborista_{i}",
                    f"nr_percetual_pralaborista_{i}",
                )
            ),
        })
    return prolaboristas

def collect_estipulantes(detail: dict) -> List[dict]:
    estipulantes = []
    for i in range(1, 4):
        nome = normalize_text(detail.get(f"nm_agenciador_{i}"))
        cnpj = normalize_text(detail.get(f"nr_cnpj_agenciador_{i}"))
        if not nome and not cnpj:
            continue
        estipulantes.append({
            "Nome": nome,
            "Cnpj": cnpj,
            "Tx_Remuneracao": normalize_text(detail.get(f"nr_percetual_agenciador_{i}")),
        })
    return estipulantes

def build_payload(doc: dict, detail: dict) -> dict:
    premio_liquido = parse_decimal(first_value(detail, "Vl_Premio_Liquido_Total", "vl_premio_total")) or Decimal("0")
    valor_iof = parse_decimal(first_value(detail, "Vl_IOF", "nr_iof")) or Decimal("0")
    premio_bruto = premio_liquido + valor_iof

    nr_certificado = normalize_text(first_value(detail, "Nr_Certificado", "nr_certificado_individual"))
    nr_certificado_val: Any = int(nr_certificado) if nr_certificado.isdigit() else nr_certificado

    template_id = normalize_text(first_value(detail, "id_template", "TemplateId", "Template_Id"))

    return {
        "Nr_Certificado": nr_certificado_val,
        "Nr_Apolice": normalize_text(first_value(detail, "Nr_Apolice", "cd_apolice", "nr_apolice_1")),
        "Nr_Apolice_Agrupadora": normalize_text(first_value(detail, "Nr_apolice_Agrupadora", "nr_apolice_1", "cd_apolice")),
        "Dt_Emissao": parse_date(detail.get("dt_emissao")),
        "Nr_Proposta": normalize_text(first_value(detail, "Nr_Proposta", "nr_proposta")),
        "Dt_Inicio_Vigencia": parse_date(detail.get("dt_inicio_vigencia")),
        "Dt_Fim_Vigencia": parse_date(first_value(detail, "Dt_Fim_Vigencia", "dt_fim_vigencia_apolice")),
        "Cod_Produto": normalize_text(first_value(detail, "Cod_Produto", "cd_produto")),
        "Template_Id": template_id,
        "Nm_Produto": normalize_text(detail.get("nm_produto")),
        "Vl_Premio_Liquido_Total": decimal_to_json(premio_liquido),
        "Vl_IOF": decimal_to_json(valor_iof),
        "Vl_Premio_Bruto_Total": decimal_to_json(premio_bruto),
        "Segurados": [{
            "Nome": normalize_text(first_value(detail, "Segurado_Nome", "nm_segurado")),
            "NomeSocial": normalize_text(first_value(detail, "Segurado_Nome_Social", "nm_social_segurado")),
            "CPF": normalize_text(first_value(detail, "Segurado_CPF", "nr_cpf_seg")),
            "Dt_Nascimento": parse_date(first_value(detail, "Segurado_Dt_nascimento", "dt_nascimento_seg")),
            "Endereco": normalize_text(first_value(detail, "Segurado_Endereco", "nm_endereco_seg")),
            "Complemento": normalize_text(first_value(detail, "Segurado_Complemento", "nm_compl_end_seg")),
            "Bairro": normalize_text(first_value(detail, "Segurado_Bairro", "nm_bairro_seg")),
            "Cidade": normalize_text(first_value(detail, "Segurado_Cidade", "nm_cidade_seg")),
            "Uf": normalize_text(first_value(detail, "Segurado_UF", "nm_uf_seg")),
            "CEP": normalize_text(first_value(detail, "Segurado_CEP", "nr_cep_seg")),
            "Email": normalize_text(first_value(detail, "Segurado_Email", "nm_email")),
            "Celular": normalize_text(first_value(detail, "Segurado_Celular", "nr_cel")),
        }],
        "Coberturas": collect_coberturas(detail),
        "Capitalizacao": {
            "Vl_Bruto_Sorteio": None,
            "Nr_Sorte": normalize_text(first_value(detail, "nr_sorte_1", "Nr_Sorte")),
        },
        "Estipulantes": collect_estipulantes(detail),
        "ProLaboristas": collect_prolaboristas(detail),
    }

def update_status(collection, ids: List[ObjectId], status: str, lote_nome: str = None) -> int:
    if not ids:
        return 0
    set_fields: Dict[str, Any] = {"status": status, "updatedAt": datetime.utcnow()}
    if lote_nome:
        set_fields["lote_nome"] = lote_nome

    modified = 0
    batch_size = 500
    for i in range(0, len(ids), batch_size):
        chunk = ids[i:i + batch_size]
        result = collection.update_many(
            {"_id": {"$in": chunk}},
            {"$set": set_fields},
        )
        modified += result.modified_count
    return modified

def main() -> None:
    if not MONGO_URI:
        raise ValueError("Defina PRD_MONGO_SA_EAST.")

    if not DRY_RUN:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    client = MongoClient(MONGO_URI)
    collection = client[MONGO_DB][MONGO_COLLECTION]

    pending_filter = build_pending_filter()
    total = collection.count_documents(pending_filter)
    print(f"Registros pendentes: {total}")
    print(f"Saída: {OUTPUT_DIR}")

    grouped_payloads: Dict[str, List[dict]] = defaultdict(list)
    grouped_ids: Dict[str, List[ObjectId]] = defaultdict(list)
    sem_template_ids: List[ObjectId] = []
    fora_corte_ids: List[ObjectId] = []

    cursor = collection.find(pending_filter, batch_size=5000, no_cursor_timeout=True)

    try:
        for doc in tqdm(cursor, total=total, desc="Classificando"):
            details = doc.get("details")
            if not isinstance(details, list) or not details:
                continue

            detail = details[0]
            if not isinstance(detail, dict):
                continue

            cod_produto = normalize_text(first_value(detail, "Cod_Produto", "cd_produto"))
            if cod_produto in DATA_CORTE:
                dt_emissao = parse_date_obj(detail.get("dt_emissao"))
                if dt_emissao and dt_emissao > DATA_CORTE[cod_produto]:
                    fora_corte_ids.append(doc["_id"])
                    continue

            template_id = normalize_text(first_value(detail, "id_template", "TemplateId", "Template_Id"))
            if not template_id:
                sem_template_ids.append(doc["_id"])
                continue

            payload = build_payload(doc, detail)
            grouped_payloads[template_id].append(payload)
            grouped_ids[template_id].append(doc["_id"])
    finally:
        cursor.close()

    lote_timestamp = datetime.now().strftime("%d%m%Y-%H%M")
    arquivos_gerados = 0
    documentos_processados = 0

    for template_id in tqdm(sorted(grouped_payloads.keys()), desc="Gerando arquivos"):
        lote_nome = f"Id_{template_id}_MetaFile_PANPROTEGE_{lote_timestamp}"
        file_path = OUTPUT_DIR / f"{lote_nome}.json"
        registros = grouped_payloads[template_id]

        if DRY_RUN:
            print(f"[dry-run] {file_path.name}: {len(registros)} registros")
            arquivos_gerados += 1
            documentos_processados += len(grouped_ids[template_id])
            continue

        try:
            existentes = []
            if file_path.exists():
                with file_path.open("r", encoding="utf-8") as f:
                    existentes = json.load(f)

            with file_path.open("w", encoding="utf-8") as f:
                json.dump(existentes + registros, f, ensure_ascii=False, indent=2)

            arquivos_gerados += 1
            documentos_processados += update_status(
                collection, grouped_ids[template_id], STATUS_PROCESSADO, lote_nome
            )
        except Exception as exc:
            print(f"[ERRO] {file_path.name}: {exc}")

    sem_template_atualizados = 0
    fora_corte_atualizados = 0

    if not DRY_RUN:
        sem_template_atualizados = update_status(collection, sem_template_ids, STATUS_SEM_TEMPLATE)
        fora_corte_atualizados = update_status(collection, fora_corte_ids, STATUS_FORA_CORTE)
    else:
        sem_template_atualizados = len(sem_template_ids)
        fora_corte_atualizados = len(fora_corte_ids)

    client.close()

    print(
        f"\nResumo | "
        f"arquivos: {arquivos_gerados} | "
        f"processados: {documentos_processados} | "
        f"sem template: {sem_template_atualizados} | "
        f"fora do corte: {fora_corte_atualizados}"
    )

if __name__ == "__main__":
    main()
