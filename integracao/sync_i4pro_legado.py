import os
import pyodbc
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pymongo import MongoClient
from datetime import datetime, date
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

QUANTIDADE_IMPORTAR = 1000
MAX_WORKERS = 8
USER_CODE = "johnnata.alves"

SQL_CONNECTION = os.getenv("SQL_CONNECTION_I4PRO_PRD")
MONGO_CONNECTION = os.getenv("PRD_MONGO_CLAIM_ENGINE")
MONGO_AVISO_CONNECTION = os.getenv("PRD_MONGO_SA_EAST")
DATABASE_MONGO = "ClaimEngine"
DATABASE_AVISO = "SinistrosMicroService"

SINISTRO_LIST_QUERY = f"""
    select distinct csin.nr_sinistro, ca.cd_apolice
    from i4pro_erp..corp_sinistro csin with(NOLOCK)
    inner join i4pro_erp..corp_endosso ce with(NOLOCK) on csin.id_endosso = ce.id_endosso
    inner join i4pro_erp..corp_sub_estipulante cse with(NOLOCK) on ce.id_sub = cse.id_sub
    inner join i4pro_erp..corp_apolice ca with(NOLOCK) on cse.id_apolice = ca.id_apolice
    where csin.cd_status in(804, 801, 426)
"""

DETAIL_QUERY = """
select distinct
    csin.nr_sinistro as Sinistro,
    ca.cd_apolice as Apolice,
    ca.nr_bilhete as Certificado,
    rm.nr_ramo as IdRamo,
    cp.cd_produto as IdProduto,
    cp.nm_produto as Produto,
    cob.id_cobertura as IdCobertura,
    cob.nm_cobertura as Cobertura,
    gpc.id_grupo_cobertura as IdGrupoCobertura,
    stt.nm_status as StatusSinistro,
    csin.cd_status as IdStatusSinistro,
    convert(varchar(max),csin.dt_sistema,103) as DataSistema,
    convert(varchar(max),csin.dt_comunicado,103) as DataAviso,
    convert(varchar(max),csin.dt_ocorrencia,103) as DataOcorrencia,
    pess.nr_cnpj_cpf as CPFSegurado,
    pess.nm_pessoa as NomeSegurado,
    pess.dt_nascimento as NascimentoSegurado,
    sexo_seg.nm_sexo as GeneroSegurado,
    uf_seg.nm_uf as UFSegurado,
    end_seg.nm_bairro as BairroSegurado,
    end_seg.nr_rua_endereco as NumeroRuaSegurado,
    end_seg.nm_endereco as RuaSegurado,
    end_seg.nm_cidade as CidadeSegurado,
    end_seg.nm_cep as CepSegurado,
    email_seg.nm_meio_comunicacao as EmailSegurado,
    email_seg.dv_principal as EmailSeguradoPrincipal,
    telefone_seg.nr_ddd as DDDSegurado,
    telefone_seg.nm_meio_comunicacao as TelefoneSegurado,
    telefone_seg.dv_principal as TelefoneSeguradoPrincipal,
    csin.id_sin_relacao as IdRelacao,
    pess_rec.nr_cnpj_cpf as CPFReclamante,
    pess_rec.nm_pessoa as NomeReclamante,
    case when pess_rec.cd_tipo_pessoa = 1 then 'CPF' else 'CNPJ' end as TipoPessoa,
    email_rec.nm_meio_comunicacao as EmailReclamante,
    email_rec.dv_principal as EmailReclamantePrincipal,
    telefone_rec.nr_ddd as DDDReclamante,
    telefone_rec.nm_meio_comunicacao as TelefoneReclamante,
    telefone_rec.dv_principal as TelefoneReclamantePrincipal,
    csin.cd_uf_ocorrencia as UFOcorrencia,
    csin.nm_cidade_ocorrencia as CidadeOcorrencia,
    csin.cd_causa as Causa,
    csin.cd_tp_causa as TipoCausa,
    mvto.id_produto_cobertura as ProdutoCobertura
from
    i4pro_erp..corp_sinistro csin with(NOLOCK)
    inner join i4pro_erp..corp_sin_movto mvto with(NOLOCK) on csin.nr_sinistro = mvto.nr_sinistro and mvto.cd_evento = 10101
    inner join i4pro_erp..corp_status stt with(NOLOCK) on csin.cd_status = stt.cd_status
    inner join i4pro_erp..corp_ramo rm with(NOLOCK) on csin.id_ramo = rm.id_ramo
    inner join i4pro_erp..corp_produto_cobertura cpp with(NOLOCK) on mvto.id_produto_cobertura = cpp.id_produto_cobertura
    inner join i4pro_erp..corp_produto cp with(NOLOCK) on cp.cd_produto = cpp.cd_produto
    inner join i4pro_erp..corp_cobertura cob with(NOLOCK) on cob.id_cobertura = cpp.id_cobertura
    inner join i4pro_erp..corp_pessoas pess with(nolock) on pess.id_pessoa = csin.id_pessoa_sinistrado
    inner join i4pro_erp..corp_endosso ce with(NOLOCK) on csin.id_endosso = ce.id_endosso
    inner join i4pro_erp..corp_sub_estipulante cse with(NOLOCK) on ce.id_sub = cse.id_sub
    inner join i4pro_erp..corp_apolice ca with(NOLOCK) on cse.id_apolice = ca.id_apolice
    inner join i4pro_erp..corp_pessoas pess_rec with(nolock) on pess_rec.id_pessoa = mvto.id_pessoa_reclamante
    left join i4pro_erp..corp_sin_relacao rel with(nolock) on rel.id_sin_relacao = csin.id_sin_relacao
    left join i4pro_erp..corp_grupo_produto_cobertura gpc with(NOLOCK) on mvto.id_produto_cobertura = gpc.id_produto_cobertura and gpc.dv_vincular = 1
    left join cad.t_pessoas_endereco end_seg with(NOLOCK) on end_seg.id_pessoa = pess.id_pessoa
    left join i4pro_erp..corp_uf uf_seg with(NOLOCK) on uf_seg.cd_uf = end_seg.cd_uf
    left join i4pro_erp..corp_sexo sexo_seg with(NOLOCK) on sexo_seg.id_sexo = pess.id_sexo
    left join i4pro_erp.cad.t_pessoas_meio_comunicacao email_seg with(NOLOCK) on email_seg.id_pessoa = pess.id_pessoa and email_seg.cd_tp_meio_comunicacao = 4
    left join i4pro_erp.cad.t_pessoas_meio_comunicacao telefone_seg with(NOLOCK) on telefone_seg.id_pessoa = pess.id_pessoa and telefone_seg.cd_tp_meio_comunicacao = 3
    left join i4pro_erp.cad.t_pessoas_meio_comunicacao email_rec with(NOLOCK) on email_rec.id_pessoa = pess_rec.id_pessoa and email_rec.cd_tp_meio_comunicacao = 4
    left join i4pro_erp.cad.t_pessoas_meio_comunicacao telefone_rec with(NOLOCK) on telefone_rec.id_pessoa = pess_rec.id_pessoa and telefone_rec.cd_tp_meio_comunicacao = 3
where csin.nr_sinistro = ?
"""

DOC_QUERY = """
    select id_sin_documento, id_documento, dt_recebimento, dt_solicitacao, dv_solicitar, id_sin_beneficiario
    from i4pro_erp..corp_sin_documento with(NOLOCK)
    where nr_sinistro = ?
"""

def parse_date(date_str):
    if not date_str:
        return None
    return datetime.strptime(date_str, "%d/%m/%Y")

def format_birthdate(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, datetime.min.time())
    else:
        return str(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def normalize_cpf(value):
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits.zfill(11) if digits else None

def sanitize_for_mongo(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, dict):
        return {k: sanitize_for_mongo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_mongo(v) for v in value]
    return value

def to_int_or_none(value):
    if value is None or value == "":
        return None
    return int(value)

def log_step(index, total, sinistro, message):
    print(f"[{index}/{total}] Sinistro {sinistro}: {message}")

_thread_local = threading.local()

def get_sql_conn():
    if not hasattr(_thread_local, "sql_conn"):
        _thread_local.sql_conn = pyodbc.connect(SQL_CONNECTION)
    return _thread_local.sql_conn

def process_sinistro(idx, sinistro, total, db, db_aviso):
    log_step(idx, total, sinistro, "Iniciando processamento")

    sql_conn = get_sql_conn()

    if db.Claim.find_one({"claimNumber": sinistro}):
        log_step(idx, total, sinistro, "Claim já existe, pulando")
        return "ja_existe"

    if db.LegacyClaim.find_one({"claimNumber": sinistro}):
        log_step(idx, total, sinistro, "LegacyClaim já existe, pulando")
        return "ja_existe"

    aviso = db_aviso["AvisoSinistro"].find_one({"Sinistros": str(sinistro)})
    if not aviso:
        log_step(idx, total, sinistro, "AvisoSinistro não encontrado, importando com dados vazios")
        aviso = {}

    protocolo_num = aviso.get("Protocolo", "")
    segurado_aviso = aviso.get("Segurado") or {}
    reclamante_aviso = aviso.get("Reclamante") or {}
    info_compl = aviso.get("InformacoesComplementares") or {}
    origem_documento = info_compl.get("origemdocumento", "")

    detail_cursor = sql_conn.cursor()
    detail_cursor.execute(DETAIL_QUERY, sinistro)
    detail_columns = [column[0] for column in detail_cursor.description]
    detail_rows = detail_cursor.fetchall()

    if not detail_rows:
        log_step(idx, total, sinistro, "Sem detalhes SQL, pulando")
        return "sem_detalhes"

    registros = [dict(zip(detail_columns, row)) for row in detail_rows]
    base = registros[0]

    if base["IdGrupoCobertura"]:
        coverage_doc = db.Coverage.find_one({"groupCoverageCodes": int(base["IdGrupoCobertura"])})
    else:
        coverage_doc = db.Coverage.find_one({"coverageCodes": int(base["IdCobertura"])})
    coverage_value = coverage_doc["coverage"] if coverage_doc else None

    if base["IdRelacao"]:
        relationship_doc = db.Relationship.find_one({"RelationshipCode": int(base["IdRelacao"])})
        relationship_value = relationship_doc["Relationship"] if relationship_doc else None
    else:
        relationship_value = "OTHER"

    coverages = []
    coverage_set = set()
    for r in registros:
        coverage_code = int(r["IdCobertura"])
        group_code = int(r["IdGrupoCobertura"]) if r["IdGrupoCobertura"] else None
        branch_code = int(r["IdRamo"])
        coverage_key = (coverage_code, group_code, branch_code)
        if coverage_key in coverage_set:
            continue
        coverage_set.add(coverage_key)
        coverages.append({
            "coverageCode": coverage_code,
            "groupCoverageCode": group_code,
            "branchCode": branch_code,
        })

    status_code = int(base["IdStatusSinistro"]) if base.get("IdStatusSinistro") else None
    claim_status = "Importado"
    regulatory_status_name = base["StatusSinistro"]
    claim_step = "REGULATION"

    requestor = {
        "acceptsCommunication": reclamante_aviso.get("AceitaComunicacao", True),
        "communicationType": "EmailSMS",
        "requestorIsInsured": reclamante_aviso.get("ProprioSegurado", False),
        "name": reclamante_aviso.get("Nome"),
        "socialName": reclamante_aviso.get("SocialName"),
        "documentType": "CNPJ" if len(str(reclamante_aviso.get("CpfCnpj", "")).strip()) > 11 else "CPF",
        "documentNumber": reclamante_aviso.get("CpfCnpj"),
        "relationship": relationship_value,
        "phones": [{"countryCallingCode": "+55", "areaCode": "", "number": reclamante_aviso.get("Telefone", ""), "principal": True}],
        "emails": [{"email": reclamante_aviso.get("Email", ""), "principal": True}],
    }

    insured = {
        "documentNumber": normalize_cpf(segurado_aviso.get("CpfCnpj") or base["CPFSegurado"]),
        "name": base["NomeSegurado"],
        "birthDate": format_birthdate(segurado_aviso.get("DataNascimento") or base.get("NascimentoSegurado")),
        "gender": base.get("GeneroSegurado"),
        "documentType": "CPF",
        "contact": {
            "addresses": [{
                "principal": True,
                "origin": origem_documento,
                "street": base["RuaSegurado"],
                "number": base["NumeroRuaSegurado"],
                "districtName": base["BairroSegurado"],
                "townName": base["CidadeSegurado"],
                "countrySubDivision": base["UFSegurado"],
                "zipCode": base["CepSegurado"],
                "type": "Cobrança",
            }],
            "phones": [{"principal": True, "origin": "I4PRO", "areaCode": base["DDDSegurado"], "number": base["TelefoneSegurado"], "type": "Telefone residencial"}],
            "emails": [{"email": base["EmailSegurado"], "origin": "I4PRO", "principal": True}],
        },
    }

    claim_document = {
        "UpdatedUserName": None,
        "UpdatedAt": parse_date(base["DataAviso"]),
        "CreatedAt": parse_date(base["DataSistema"]),
        "DeliveryAt": parse_date(base["DataSistema"]),
        "claimNumber": sinistro,
        "product": int(base["IdProduto"]),
        "productName": base["Produto"],
        "protocol": protocolo_num,
        "flowId": "",
        "policyNumber": str(base["Apolice"]),
        "certificate": str(base["Certificado"]),
        "userCode": USER_CODE,
        "occurrenceDate": parse_date(base["DataOcorrencia"]),
        "notificationDate": parse_date(base["DataAviso"]),
        "occurrenceDescription": "",
        "integrationStatus": "Synchronized",
        "status": "Importado",
        "integrationFailedMessage": None,
        "coverageProductId": int(base["ProdutoCobertura"]) if base.get("ProdutoCobertura") else None,
        "requestor": requestor,
        "insured": insured,
        "cause": int(base["Causa"]) if base["Causa"] else 0,
        "coverage": coverage_value,
        "coverages": coverages,
        "notificationOrigin": origem_documento,
        "step": claim_step,
        "additionalInformation": {},
        "regulatoryStatusCode": status_code,
        "occurrenceCodeUf": int(base["UFOcorrencia"]) if base["UFOcorrencia"] else None,
        "occurrenceNameCity": base["CidadeOcorrencia"],
        "causeType": base["TipoCausa"],
        "regulatoryStatusName": regulatory_status_name,
        "createdOrigin": None,
        "updatedOrigin": origem_documento,
        "isJudicial": False,
        "priorityFlag": False,
    }

    log_step(idx, total, sinistro, "Inserindo LegacyClaim")
    db.LegacyClaim.insert_one(sanitize_for_mongo(claim_document))

    log_step(idx, total, sinistro, "Sincronizando Documentos")
    docs_cursor = sql_conn.cursor()
    docs_cursor.execute(DOC_QUERY, sinistro)
    docs_rows = docs_cursor.fetchall()

    for doc_row in docs_rows:
        document_mapping = db.DocumentTypeMappings.find_one({"ERPDocumentId": to_int_or_none(doc_row.id_documento)})
        document_name = document_mapping["ERPDocumentName"] if document_mapping else None

        claim_doc = {
            "UpdatedUserName": USER_CODE,
            "UpdatedAt": doc_row.dt_solicitacao,
            "CreatedAt": doc_row.dt_solicitacao,
            "DeliveryAt": None,
            "flowId": "",
            "claimNumber": sinistro,
            "protocol": protocolo_num,
            "documentName": document_name,
            "documentCode": to_int_or_none(doc_row.id_documento),
            "docClassificationCode": "Basic",
            "documentIsRequired": bool(doc_row.dv_solicitar),
            "requestDate": doc_row.dt_solicitacao,
            "receiveDate": doc_row.dt_recebimento,
            "beneficiaryCode": to_int_or_none(doc_row.id_sin_beneficiario) or 0,
            "justification": None,
            "userCode": "",
            "status": "Completed",
            "integrationStatus": "Synchronized",
            "isActive": True,
            "claimDocumentId": to_int_or_none(doc_row.id_sin_documento),
            "step": "Pending",
            "createdOrigin": "Platform",
            "updatedOrigin": "I4Pro",
            "isReportDocument": False,
            "attachments": [],
            "isSupplemental": None,
        }
        db.LegacyDocument.insert_one(sanitize_for_mongo(claim_doc))

    log_step(idx, total, sinistro, "Importando anexos")
    anexos_cursor = db_aviso["AvisoSinistroAnexo"].find({"Protocolo": protocolo_num})

    for anexo in anexos_cursor:
        key = anexo.get("Key") or ""
        hash_val = anexo.get("Hash") or ""
        insert_date = anexo.get("DataInclusaoAnexo") or datetime.utcnow()
        file_name = key.split("/")[-1] if "/" in key else key

        legacy_attachment = {
            "UpdatedUserName": None,
            "UpdatedAt": None,
            "CreatedAt": insert_date,
            "DeliveryAt": None,
            "protocol": protocolo_num,
            "key": key,
            "insertDate": insert_date,
            "status": "Completed",
            "tipificationCode": None,
            "tipificationDate": None,
            "documentTypeCode": None,
            "documentTypeNames": None,
            "documentTypes": None,
            "erpDocuments": None,
            "suggestedDocumentCode": "",
            "metadata": None,
            "metadataSuccess": False,
            "metadataValidationSuccess": False,
            "integrationStep": None,
            "userCode": "api-legado-v5",
            "hash": hash_val,
            "sizeKb": 100,
            "fileName": file_name,
            "isOpen": False,
            "origin": origem_documento or "apiV5",
            "notes": "",
            "beneficiaryCode": None,
            "calls": [],
            "relatedDocumentFlowIds": None,
            "errors": [],
            "documentTypificationCall": None,
        }
        db.LegacyAttachment.insert_one(sanitize_for_mongo(legacy_attachment))

    log_step(idx, total, sinistro, "Finalizado")
    return "sincronizado"

def main():
    report = {

        "quantidade_solicitada": QUANTIDADE_IMPORTAR,
        "inicio": datetime.now(),
        "sincronizados": [],
        "sem_detalhes": [],
        "ja_existe": [],
        "erros": [],
    }

    client = MongoClient(MONGO_CONNECTION)
    db = client[DATABASE_MONGO]

    client_aviso = MongoClient(MONGO_AVISO_CONNECTION)
    db_aviso = client_aviso[DATABASE_AVISO]

    sql_conn = pyodbc.connect(SQL_CONNECTION)
    cursor = sql_conn.cursor()
    cursor.execute(SINISTRO_LIST_QUERY)
    rows = cursor.fetchall()
    sql_conn.close()

    sinistro_list = [int(row[0]) for row in rows][:QUANTIDADE_IMPORTAR]
    total_sinistros = len(sinistro_list)

    report["total_encontrados"] = total_sinistros
    print(f"Encontrados: {total_sinistros} | Workers: {MAX_WORKERS}")

    lock = threading.Lock()

    def worker(idx, sinistro):
        try:
            resultado = process_sinistro(idx, sinistro, total_sinistros, db, db_aviso)
            with lock:
                if resultado == "sincronizado":
                    report["sincronizados"].append(sinistro)
                elif resultado == "sem_detalhes":
                    report["sem_detalhes"].append(sinistro)
                elif resultado == "ja_existe":
                    report["ja_existe"].append(sinistro)
        except Exception as e:
            with lock:
                report["erros"].append({"sinistro": sinistro, "erro": str(e)})
            print(f"  ERRO {sinistro}: {e}")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(worker, idx, sin) for idx, sin in enumerate(sinistro_list, start=1)]
        for _ in as_completed(futures):
            pass

    client.close()
    client_aviso.close()

    report["fim"] = datetime.now()
    report["duracao_segundos"] = (report["fim"] - report["inicio"]).total_seconds()

    print("\n" + "=" * 60)
    print("RELATÓRIO DE SINCRONIZAÇÃO LEGADO")
    print("=" * 60)
    print(f"Total SQL: {report['total_encontrados']}")
    print(f"Sincronizados: {len(report['sincronizados'])}")
    print(f"Sem detalhes/pulados: {len(report['sem_detalhes'])}")
    print(f"Já existentes: {len(report['ja_existe'])}")
    print(f"Erros: {len(report['erros'])}")
    print(f"Duração: {report['duracao_segundos']:.1f}s")
    print("=" * 60)

    if report["sincronizados"]:
        print(f"\nSinistros sincronizados:")
        for s in report["sincronizados"]:
            print(f"  - {s}")

    if report["erros"]:
        print(f"\nErros:")
        for e in report["erros"]:
            print(f"  - {e['sinistro']}: {e['erro']}")

if __name__ == "__main__":
    main()
