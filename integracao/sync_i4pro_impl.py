import os
import pyodbc
import requests
from pymongo import MongoClient, ReturnDocument
from datetime import datetime, date
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv()

STATUS_IMPORTAR = 804
QUANTIDADE_IMPORTAR = 1
USER_CODE = "johnnata.alves"
PROTOCOLO_URL = os.getenv("PROTOCOLO_API_URL")

INTERNAL_CLIENT_ID = os.getenv("INTERNAL_CLIENT_ID")
SQL_CONNECTION = os.getenv("SQL_CONNECTION_I4PRO_HML")
MONGO_CONNECTION = os.getenv("HML_MONGO_MONITORING")
MONGO_INDEXED_CONNECTION = os.getenv("HML_INDEXED_MONITORING_URI")
DATABASE_MONGO = "ClaimEngine"
DATABASE_INDEXED = "indexed_policy_too"
COLLECTION_INDEXED = "person_branch_catalog"

SINISTRO_LIST_QUERY = f"""
    select  distinct csin.nr_sinistro, ca.cd_apolice
    from i4pro_erp..corp_sinistro csin with(NOLOCK)
    inner join i4pro_erp..corp_endosso ce with(NOLOCK) on csin.id_endosso = ce.id_endosso
    inner join i4pro_erp..corp_sub_estipulante cse with(NOLOCK) on ce.id_sub = cse.id_sub
    inner join i4pro_erp..corp_apolice ca with(NOLOCK) on cse.id_apolice = ca.id_apolice
    where csin.cd_status = {STATUS_IMPORTAR}
"""

DETAIL_QUERY = """

select   distinct
	csin.nr_sinistro as Sinistro -- claimNumber
	, ca.cd_apolice as Apolice -- policyNumber
	, ca.nr_bilhete as Certificado -- certificate
	, rm.nr_ramo as IdRamo -- coverages.branchCode
	, cp.cd_produto as IdProduto -- product
	, cp.nm_produto as Produto -- productName
	, cob.id_cobertura as IdCobertura -- coverages.coverageCode
	, cob.nm_cobertura as Cobertura
	, gpc.id_grupo_cobertura as IdGrupoCobertura -- coverages.groupCoverageCode
	, stt.nm_status as StatusSinistro
	, csin.cd_status as IdStatusSinistro
	, convert(varchar(max),csin.dt_sistema,103) as DataSistema -- CreatedAt
	, convert(varchar(max),csin.dt_comunicado,103) as DataAviso -- notificationDate E UpdatedAt E protocolCreatedAt
	, convert(varchar(max),csin.dt_ocorrencia,103) as DataOcorrencia -- occurrenceDate
	, pess.id_pessoa as IdSegurado
	, pess.dt_nascimento as NascimentoSegurado -- insured.birthDate
	, pess.nr_cnpj_cpf as CPFSegurado -- insured.documentNumber
	, sexo_seg.nm_sexo as GeneroSegurado -- insured.gender
	, pess.nm_pessoa as NomeSegurado -- insured.name
	, uf_seg.nm_uf as UFSegurado -- insured.contact.addresses.countrySubDivision
	, end_seg.nm_bairro as BairroSegurado -- insured.contact.addresses.districtName
	, end_seg.nr_rua_endereco as NumeroRuaSegurado -- insured.contact.addresses.number
	, end_seg.nm_endereco as RuaSegurado -- insured.contact.addresses.street
	, end_seg.nm_cidade as CidadeSegurado -- insured.contact.addresses.townName
	, end_seg.nm_cep as CepSegurado -- insured.contact.addresses.zipCode
	, email_seg.nm_meio_comunicacao as EmailSegurado -- insured.contact.emails.email
	, email_seg.dv_principal as EmailSeguradoPrincipal -- insured.contact.emails.principal
	, telefone_seg.nr_ddd as DDDSegurado -- insured.contact.phones.areaCode
	, telefone_seg.nm_meio_comunicacao as TelefoneSegurado -- insured.contact.phones.number
	, telefone_seg.dv_principal as TelefoneSeguradoPrincipal -- insured.contact.phones.principal
	, csin.id_sin_relacao as IdRelacao -- requestor.relationship (fazer De/para)
	, rel.nm_sin_relacao as Relacao
	, pess_rec.id_pessoa as IdReclamante
	, pess_rec.nr_cnpj_cpf as CPFReclamante -- requestor.documentNumber
	, pess_rec.nm_pessoa as NomeReclamante -- requestor.name e requestor.socialName
	, case when pess_rec.cd_tipo_pessoa = 1 then 'CPF' else 'CNPJ' end as TipoPessoa --requestor.documentType
	, email_rec.nm_meio_comunicacao as EmailReclamante -- requestor.emails.email
	, email_rec.dv_principal as EmailReclamantePrincipal -- requestor.emails.principal
	, telefone_rec.nr_ddd as DDDReclamante -- requestor.phones.areaCode
	, telefone_rec.nm_meio_comunicacao as TelefoneReclamante-- requestor.phones.number
	, telefone_rec.dv_principal as TelefoneReclamantePrincipal -- requestor.phones.principal
	, isnull(convert(varchar(max),mvto2.dt_agendamento,103),'') as DataAgendamento
	, isnull(replace(convert(varchar(max),mvto2.vl_operacao),'.',','),'') as ValorPagamento
	, isnull(mot.nm_motivo,'')as MotivoCancelamento
	, csin.cd_uf_ocorrencia as UFOcorrencia -- occurrenceCodeUf
	, csin.nm_cidade_ocorrencia as CidadeOcorrencia --occurrenceNameCity,
	, csin.cd_causa as Causa --causeType
	, csin.cd_tp_causa as TipoCausa  --cause
	, mvto.id_produto_cobertura as ProdutoCobertura
from
	i4pro_erp..corp_sinistro csin with(NOLOCK)
	inner join i4pro_erp..corp_sin_movto mvto with(NOLOCK) on csin.nr_sinistro = mvto.nr_sinistro and mvto.cd_evento = 10101
	inner join i4pro_erp..corp_status stt with(NOLOCK) on csin.cd_status = stt.cd_status
	inner join i4pro_erp..corp_ramo rm with(NOLOCK) on csin.id_ramo = rm.id_ramo
	inner join i4pro_erp..corp_produto_cobertura cpp with(NOLOCK) on mvto.id_produto_cobertura = cpp.id_produto_cobertura
	inner join i4pro_erp..corp_produto cp with(NOLOCK) on cp.cd_produto = cpp.cd_produto
	inner join i4pro_erp..corp_cobertura cob with(NOLOCK) on cob.id_cobertura = cpp.id_cobertura
	left join i4pro_erp..corp_sin_movto mvto2 with(NOLOCK) on csin.nr_sinistro = mvto2.nr_sinistro and mvto2.cd_evento = 11001
	left join i4pro_erp..corp_sin_movto mvto3 with(NOLOCK) on csin.nr_sinistro = mvto3.nr_sinistro and mvto3.cd_evento = 10105
	inner join i4pro_erp..corp_pessoas pess with(nolock) on pess.id_pessoa = csin.id_pessoa_sinistrado
	left join i4pro_erp..corp_tp_motivo mot with(nolock) on mot.id_tp_motivo = mvto3.id_tp_motivo
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
	left join cad.t_pessoas_endereco end_rec with(NOLOCK) on end_rec.id_pessoa = pess_rec.id_pessoa
	left join i4pro_erp.cad.t_pessoas_meio_comunicacao email_rec with(NOLOCK) on email_rec.id_pessoa = pess_rec.id_pessoa and email_rec.cd_tp_meio_comunicacao = 4
	left join i4pro_erp.cad.t_pessoas_meio_comunicacao telefone_rec with(NOLOCK) on telefone_rec.id_pessoa = pess_rec.id_pessoa and telefone_rec.cd_tp_meio_comunicacao = 3

	where
		csin.nr_sinistro = ?
"""

DOC_QUERY = """
	select id_sin_documento, id_documento, dt_recebimento, dt_solicitacao, dv_solicitar, id_sin_beneficiario
	from i4pro_erp..corp_sin_documento with(NOLOCK)
	where nr_sinistro = ?
"""

BENEF_QUERY = """
	select a.id_pessoa, a.pe_participacao, a.id_parentesco, a.cd_tp_beneficiario, a.dt_registro, b.nr_cnpj_cpf
	from i4pro_erp..corp_sin_beneficiario a with(NOLOCK)
		inner join i4pro_erp..corp_pessoas b with(NOLOCK) on a.id_pessoa = b.id_pessoa
	where nr_sinistro = ?
"""

MOV_QUERY = """
	select nr_sinistro, id_sin_movto, cd_evento, dt_movimento, vl_operacao, dt_sistema, id_tp_motivo,
		   id_produto_cobertura, cd_usuario, cd_sistema_externo
	from corp_sin_movto with(NOLOCK)
	where nr_sinistro = ?
"""

FOLLOW_QUERY = """
	select id_folowup, dt_folowup, ds_folowup, cd_usuario, id_sin_tp_informacao, a.id_tp_followup, b.nm_tp_followup
	from corp_sin_folowup a with(NOLOCK)
		left join corp_tp_followup b on a.id_tp_followup = b.id_tp_followup
	where nr_sinistro = ?
"""

PENDING_LOG_QUERY = """
	select top 1 dt_alteracao, cd_usuario_alteracao
	from t_sin_log_status with(NOLOCK)
	where nr_sinistro = ? and cd_status = 426
	order by dt_alteracao desc
"""

def protocolo():
    response = requests.post(
        PROTOCOLO_URL,
        headers={"clientID": INTERNAL_CLIENT_ID},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if "protocolNumber" not in data:
        raise RuntimeError("Resposta inválida do serviço de protocolo.")
    return data["protocolNumber"]

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

def dedupe_dict_list(items, key_fn):
    seen = set()
    result = []
    for item in items:
        key = key_fn(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result

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

EVENT_NAME_MAP = {
    9501: "Defeat",
    10103: "Reopening",
    10102: "AdjustmentIncrease",
    10105: "Cancellation",
    11001: "Indemnity",
    10104: "AdjustmentDecrease",
    12001: "Expenses",
    13001: "Fees",
    14001: "Reimbursement",
    15001: "Salvage",
    10101: "Warning",
}

def log_step(index, total, sinistro, message):
    print(f"[{index}/{total}] Sinistro {sinistro}: {message}")

def get_sql_connection():
    return pyodbc.connect(SQL_CONNECTION)

def process_sinistro(idx, sinistro, total, db, db_indexed):
    log_step(idx, total, sinistro, "Iniciando processamento")

    if db.Notification.find_one({"claimNumber": sinistro}):
        log_step(idx, total, sinistro, "Já existe Notification, pulando")
        return "ja_existe"

    if db.Claim.find_one({"claimNumber": sinistro}):
        log_step(idx, total, sinistro, "Claim já existe na base, pulando")
        return "ja_existe"

    sql_conn = get_sql_connection()
    try:
        detail_cursor = sql_conn.cursor()
        detail_cursor.execute(DETAIL_QUERY, sinistro)
        detail_columns = [column[0] for column in detail_cursor.description]
        detail_rows = detail_cursor.fetchall()

        if not detail_rows:
            log_step(idx, total, sinistro, "Sem detalhes, pulando")
            return "sem_detalhes"

        registros = [dict(zip(detail_columns, row)) for row in detail_rows]
        base = registros[0]

        if not base.get("TipoCausa"):
            log_step(idx, total, sinistro, "CauseType null, pulando")
            return "sem_detalhes"

        policy_number = str(base.get("Apolice"))
        person = db_indexed[COLLECTION_INDEXED].find_one({"policy_number": policy_number})
        if not person:
            log_step(idx, total, sinistro, "Apolice nao encontrada, pulando")
            return "apolice_nao_encontrada"

        log_step(idx, total, sinistro, "Buscando cobertura")
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

        log_step(idx, total, sinistro, "Gerando flowId e protocolo")
        flow = db.NotificationCode.find_one_and_update(
            {"key": "2026"},
            {"$inc": {"value": 1}},
            return_document=ReturnDocument.AFTER,
        )
        flow_value = flow["value"]
        flow_id = f"{datetime.now().year}{flow_value:08d}"

        protocolo_num = protocolo()

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
                "branchCode": branch_code
            })

        requestor_phones = dedupe_dict_list([
            {
                "countryCallingCode": "+55",
                "areaCode": base["DDDReclamante"],
                "number": base["TelefoneReclamante"],
                "principal": bool(base["TelefoneReclamantePrincipal"])
            }
        ], lambda x: (x["countryCallingCode"], x["areaCode"], x["number"], x["principal"]))

        requestor_emails = dedupe_dict_list([
            {
                "email": base["EmailReclamante"],
                "principal": bool(base["EmailReclamantePrincipal"])
            }
        ], lambda x: (x["email"], x["principal"]))

        insured_addresses = dedupe_dict_list([
            {
                "principal": True,
                "origin": "I4PRO",
                "street": base["RuaSegurado"],
                "number": base["NumeroRuaSegurado"],
                "districtName": base["BairroSegurado"],
                "townName": base["CidadeSegurado"],
                "countrySubDivision": base["UFSegurado"],
                "zipCode": base["CepSegurado"],
                "type": "Cobrança"
            }
        ], lambda x: (
            x["principal"], x["origin"], x["street"], x["number"], x["districtName"],
            x["townName"], x["countrySubDivision"], x["zipCode"], x["type"]
        ))

        insured_phones = dedupe_dict_list([
            {
                "principal": bool(base["TelefoneSeguradoPrincipal"]),
                "origin": "I4PRO",
                "areaCode": base["DDDSegurado"],
                "number": base["TelefoneSegurado"],
                "type": "Telefone residencial"
            }
        ], lambda x: (x["principal"], x["origin"], x["areaCode"], x["number"], x["type"]))

        insured_emails = dedupe_dict_list([
            {
                "email": base["EmailSegurado"],
                "origin": "I4PRO",
                "principal": bool(base["EmailSeguradoPrincipal"])
            }
        ], lambda x: (x["email"], x["origin"], x["principal"]))

        status_code = int(base["IdStatusSinistro"]) if base.get("IdStatusSinistro") else None
        if status_code == 801:
            claim_status = "Análise regulação"
            regulatory_status_name = base["StatusSinistro"]
        elif status_code == 426:
            claim_status = "Pendenciado - Documentação complementar"
            regulatory_status_name = "Pendenciado - Documentação complementar"
        else:
            claim_status = base["StatusSinistro"]
            regulatory_status_name = base["StatusSinistro"]

        reiteration_map = {
            "1ª Reiteração": "Reiteração 1",
            "2ª Reiteração": "Reiteração 2",
            "3ª Reiteração": "Reiteração 3",
        }
        claim_status = reiteration_map.get(claim_status, claim_status)

        claim_step = "REGULATION"
        if status_code == 447:
            claim_status = "Pagamento liquidado"
            claim_step = "PAYMENT"

        mov_cursor = sql_conn.cursor()
        mov_cursor.execute(MOV_QUERY, sinistro)
        mov_rows = mov_cursor.fetchall()
        has_rejected_movement = any(
            to_int_or_none(row.cd_evento) == 10105 for row in mov_rows
        )

        if has_rejected_movement:
            claim_status = "Sinistro cancelado"
            regulatory_status_name = "Recusado"
            status_code = 804
            claim_step = "CONCLUSION"

        document = {
            "UpdatedUserName": USER_CODE,
            "UpdatedAt": parse_date(base["DataAviso"]),
            "CreatedAt": parse_date(base["DataSistema"]),
            "DeliveryAt": None,
            "coverage": coverage_value,
            "flowId": flow_id,
            "caseId": None,
            "product": int(base["IdProduto"]),
            "protocol": protocolo_num,
            "claimNumber": sinistro,
            "step": "CONCLUSION",
            "protocolCreatedAt": parse_date(base["DataAviso"]),
            "policyNumber": int(base["Apolice"]),
            "certificate": base["Certificado"],
            "userCode": USER_CODE,
            "occurrenceDate": parse_date(base["DataOcorrencia"]),
            "notificationDate": parse_date(base["DataAviso"]),
            "occurrenceDescription": "",
            "requestor": {
                "acceptsCommunication": True,
                "communicationType": "EmailSMS",
                "requestorIsInsured": base["CPFSegurado"] == base["CPFReclamante"],
                "name": base["NomeReclamante"],
                "socialName": None,
                "documentType": base["TipoPessoa"],
                "documentNumber": base["CPFReclamante"],
                "relationship": relationship_value,
                "phones": requestor_phones,
                "emails": requestor_emails
            },
            "insured": {
                "documentNumber": normalize_cpf(base["CPFSegurado"]),
                "name": base["NomeSegurado"],
                "birthDate": format_birthdate(base["NascimentoSegurado"]),
                "gender": base["GeneroSegurado"],
                "documentType": "CPF",
                "contact": {
                    "addresses": insured_addresses,
                    "phones": insured_phones,
                    "emails": insured_emails
                }
            },
            "cause": int(base["Causa"]) if base["Causa"] else 0,
            "coverages": coverages,
            "integrationStatus": "Completed",
            "status": "Enviado para regulação",
            "beneficiaryTypes": ["STIPULATOR"],
            "causeType": base["TipoCausa"],
            "occurrenceCodeUf": int(base["UFOcorrencia"]) if base["UFOcorrencia"] else None,
            "occurrenceNameCity": base["CidadeOcorrencia"],
            "productName": base["Produto"],
            "createdOrigin": None,
            "updatedOrigin": None,
            "notificationOrigin": "I4Pro",
            "cancellation": None,
            "validated": True,
            "additionalInformation": {},
            "priorityFlag": False,
            "sendedAllAttachmentsToBpm": False,
            "requestorCommunication": True,
            "errors": []
        }

        log_step(idx, total, sinistro, "Inserindo Notification")
        db.Notification.insert_one(sanitize_for_mongo(document))

        claim_document = {
            "UpdatedUserName": None,
            "UpdatedAt": parse_date(base["DataAviso"]),
            "CreatedAt": parse_date(base["DataSistema"]),
            "DeliveryAt": parse_date(base["DataSistema"]),
            "claimNumber": sinistro,
            "product": int(base["IdProduto"]),
            "productName": base["Produto"],
            "protocol": protocolo_num,
            "flowId": flow_id,
            "policyNumber": str(base["Apolice"]),
            "certificate": str(base["Certificado"]),
            "userCode": USER_CODE,
            "occurrenceDate": parse_date(base["DataOcorrencia"]),
            "notificationDate": parse_date(base["DataAviso"]),
            "occurrenceDescription": "",
            "integrationStatus": "Synchronized",
            "status": claim_status,
            "integrationFailedMessage": None,
            "coverageProductId": int(base["ProdutoCobertura"]) if base.get("ProdutoCobertura") else None,
            "requestor": {
                "acceptsCommunication": True,
                "communicationType": "EmailSMS",
                "requestorIsInsured": base["CPFSegurado"] == base["CPFReclamante"],
                "name": base["NomeReclamante"],
                "socialName": None,
                "documentType": base["TipoPessoa"],
                "documentNumber": base["CPFReclamante"],
                "relationship": relationship_value,
                "phones": requestor_phones,
                "emails": requestor_emails
            },
            "insured": {
                "documentNumber": normalize_cpf(base["CPFSegurado"]),
                "name": base["NomeSegurado"],
                "birthDate": format_birthdate(base["NascimentoSegurado"]),
                "gender": base["GeneroSegurado"],
                "documentType": "CPF",
                "contact": {
                    "addresses": insured_addresses,
                    "phones": insured_phones,
                    "emails": insured_emails
                }
            },
            "cause": int(base["Causa"]) if base["Causa"] else 0,
            "coverage": coverage_value,
            "coverages": coverages,
            "notificationOrigin": "I4Pro",
            "step": claim_step,
            "additionalInformation": {},
            "regulatoryStatusCode": status_code,
            "occurrenceCodeUf": int(base["UFOcorrencia"]) if base["UFOcorrencia"] else None,
            "occurrenceNameCity": base["CidadeOcorrencia"],
            "causeType": base["TipoCausa"],
            "regulatoryStatusName": regulatory_status_name,
            "createdOrigin": None,
            "updatedOrigin": "I4Pro",
            "isJudicial": False,
            "priorityFlag": False
        }

        log_step(idx, total, sinistro, "Inserindo Claim")
        db.Claim.insert_one(sanitize_for_mongo(claim_document))

        if status_code == 804:
            log_step(idx, total, sinistro, "Inserindo Letter (RefusedClaim)")
            letter_document = {
                "UpdatedUserName": None,
                "UpdatedAt": datetime.utcnow(),
                "CreatedAt": datetime.utcnow(),
                "DeliveryAt": None,
                "flowId": flow_id,
                "protocol": protocolo_num,
                "claimNumber": sinistro,
                "type": "RefusedClaim",
                "documentCode": None,
                "status": "Pending",
                "description": "",
                "originId": None,
                "errors": None,
            }
            db.Letter.insert_one(sanitize_for_mongo(letter_document))

        log_step(idx, total, sinistro, "Inativando documentos existentes")
        db.Document.update_many(
            {"claimNumber": sinistro},
            {"$set": {"isActive": False}}
        )

        log_step(idx, total, sinistro, "Sincronizando Documentos")
        docs_cursor = sql_conn.cursor()
        docs_cursor.execute(DOC_QUERY, sinistro)
        docs_rows = docs_cursor.fetchall()

        for doc_row in docs_rows:
            document_mapping = db.DocumentTypeMappings.find_one({
                "ERPDocumentId": to_int_or_none(doc_row.id_documento)
            })
            document_name = document_mapping["ERPDocumentName"] if document_mapping else None

            claim_doc = {
                "UpdatedUserName": USER_CODE,
                "UpdatedAt": doc_row.dt_solicitacao,
                "CreatedAt": doc_row.dt_solicitacao,
                "DeliveryAt": None,
                "flowId": flow_id,
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
                "isSupplemental": None
            }

            db.Document.insert_one(sanitize_for_mongo(claim_doc))

        if status_code in (426, 454, 455, 456):
            log_step(idx, total, sinistro, "Inserindo PendingIssue")
            pending_cursor = sql_conn.cursor()
            pending_cursor.execute(PENDING_LOG_QUERY, sinistro)
            pending_row = pending_cursor.fetchone()

            pending_documents = []
            for doc_row in docs_rows:
                if doc_row.dt_recebimento:
                    continue
                pending_documents.append({
                    "documentCode": to_int_or_none(doc_row.id_documento),
                    "beneficiaryCode": to_int_or_none(doc_row.id_sin_beneficiario) or 0
                })

            if pending_row and pending_documents:
                pending_issue = {
                    "UpdatedUserName": None,
                    "UpdatedAt": pending_row.dt_alteracao,
                    "CreatedAt": pending_row.dt_alteracao,
                    "DeliveryAt": None,
                    "flowId": flow_id,
                    "protocol": None,
                    "claimNumber": sinistro,
                    "pendingType": "Documentation",
                    "documents": pending_documents,
                    "justification": "",
                    "status": "Pending",
                    "step": "Processing",
                    "userCode": pending_row.cd_usuario_alteracao,
                    "communications": [],
                    "errors": []
                }

                if not db.PendingIssue.find_one({"claimNumber": sinistro, "flowId": flow_id}):
                    db.PendingIssue.insert_one(sanitize_for_mongo(pending_issue))

        log_step(idx, total, sinistro, "Sincronizando Beneficiários")
        benef_cursor = sql_conn.cursor()
        benef_cursor.execute(BENEF_QUERY, sinistro)
        benef_rows = benef_cursor.fetchall()

        for benef_row in benef_rows:
            relationship_code = 3
            relationship_name = "Filho(a)"
            relationship_type = "Beneficiary"

            beneficiary_document = {
                "UpdatedUserName": None,
                "UpdatedAt": benef_row.dt_registro,
                "CreatedAt": benef_row.dt_registro,
                "DeliveryAt": None,
                "claimNumber": sinistro,
                "flowId": flow_id,
                "protocol": protocolo_num,
                "personCode": to_int_or_none(benef_row.id_pessoa),
                "personId": None,
                "percentage": float(benef_row.pe_participacao) if benef_row.pe_participacao is not None else None,
                "relationshipCode": relationship_code,
                "relationshipName": relationship_name,
                "relationshipType": relationship_type,
                "justification": "",
                "userCode": USER_CODE,
                "isActive": True,
                "status": "Synchronized",
                "step": None,
                "documentNumber": str(benef_row.nr_cnpj_cpf) if benef_row.nr_cnpj_cpf is not None else None,
                "createdOrigin": "Platform",
                "updatedOrigin": None,
                "bankDetails": None,
                "additionalInformation": None
            }

            db.Beneficiary.update_one(
                {"claimNumber": sinistro, "personCode": to_int_or_none(benef_row.id_pessoa)},
                {"$set": sanitize_for_mongo(beneficiary_document)},
                upsert=True
            )

        log_step(idx, total, sinistro, "Sincronizando Movimentos")

        for mov_row in mov_rows:
            integration_id = to_int_or_none(mov_row.id_sin_movto)
            if integration_id is None:
                continue

            if db.Movement.find_one({"claimNumber": sinistro, "integrationId": integration_id}):
                continue

            event_code = to_int_or_none(mov_row.cd_evento)
            event_name = EVENT_NAME_MAP.get(event_code)

            movement_status_map = {
                10101: "Criado",
                11001: "Pagamento liquidado",
                10104: "Aprovado",
                10105: "Aprovado",
                10103: "Pending",
            }
            mov_status = movement_status_map.get(event_code, "Approved")

            movement_document = {
                "UpdatedUserName": None,
                "UpdatedAt": mov_row.dt_sistema,
                "CreatedAt": mov_row.dt_sistema,
                "DeliveryAt": None,
                "claimNumber": to_int_or_none(mov_row.nr_sinistro),
                "eventName": event_name,
                "coverageProductId": to_int_or_none(mov_row.id_produto_cobertura),
                "operationAmount": float(mov_row.vl_operacao) if mov_row.vl_operacao is not None else None,
                "reasonTypeId": to_int_or_none(mov_row.id_tp_motivo),
                "amount": str(mov_row.vl_operacao) if mov_row.vl_operacao is not None else None,
                "franchiseAmount": None,
                "indemnityTypeCode": None,
                "scheduledDate": None,
                "paymentMethodId": None,
                "favoredId": None,
                "agencyNumber": None,
                "externalSystemCode": to_int_or_none(mov_row.cd_sistema_externo),
                "bankNumber": None,
                "checkingAccountNumber": None,
                "agencyCheckDigit": None,
                "accountCheckDigit": None,
                "eventCode": event_code,
                "status": mov_status,
                "userCode": mov_row.cd_usuario,
                "step": "Pending",
                "observation": None,
                "shouldApplyInterest": False,
                "integrationId": integration_id,
                "integrationStatus": None,
                "workerIntegrationStatus": None,
                "paymentId": None,
                "movementReserveType": None,
                "movementServiceType": None,
                "isActive": True,
                "approvals": [],
                "personCode": None,
                "relationship": None,
                "percentage": None,
                "isPaid": None
            }

            db.Movement.insert_one(sanitize_for_mongo(movement_document))

        log_step(idx, total, sinistro, "Sincronizando FollowUps")
        follow_cursor = sql_conn.cursor()
        follow_cursor.execute(FOLLOW_QUERY, sinistro)
        follow_rows = follow_cursor.fetchall()

        for follow_row in follow_rows:
            follow_code = to_int_or_none(follow_row.id_folowup)
            if follow_code is None:
                continue

            if db.FollowUp.find_one({"claimNumber": sinistro, "followUpCode": follow_code}):
                continue

            info_type = "Public" if follow_row.id_sin_tp_informacao == 2 else "Private"

            follow_document = {
                "UpdatedUserName": None,
                "UpdatedAt": follow_row.dt_folowup,
                "CreatedAt": follow_row.dt_folowup,
                "DeliveryAt": follow_row.dt_folowup,
                "followUpCode": follow_code,
                "claimNumber": sinistro,
                "flowId": flow_id,
                "followUpTypeCode": to_int_or_none(follow_row.id_tp_followup),
                "followUpDescription": follow_row.ds_folowup,
                "userCode": follow_row.cd_usuario,
                "followUpTypeName": follow_row.nm_tp_followup,
                "claimInformationType": info_type,
                "productCode": 0,
                "status": "Synchronized",
                "step": "Pending",
                "createdOrigin": "Platform",
                "updatedOrigin": None
            }

            db.FollowUp.insert_one(sanitize_for_mongo(follow_document))

        log_step(idx, total, sinistro, "Finalizado")
        return "sincronizado"
    finally:
        sql_conn.close()

def main():
    report = {
        "status_importar": STATUS_IMPORTAR,
        "quantidade_solicitada": QUANTIDADE_IMPORTAR,
        "inicio": datetime.now(),
        "sincronizados": [],
        "ja_existentes": [],
        "sem_detalhes": [],
        "apolice_nao_encontrada": [],
        "erros": [],
    }

    with MongoClient(MONGO_CONNECTION) as client:
        db = client[DATABASE_MONGO]

        client_indexed = MongoClient(MONGO_INDEXED_CONNECTION)
        db_indexed = client_indexed[DATABASE_INDEXED]

        sql = pyodbc.connect(SQL_CONNECTION)
        cursor = sql.cursor()
        cursor.execute(SINISTRO_LIST_QUERY)
        rows = cursor.fetchall()
        sql.close()

        sinistro_apolice_map = {}
        for row in rows:
            sinistro_apolice_map[int(row[0])] = str(row[1])

        sinistro_list = list(sinistro_apolice_map.keys())
        total_sinistros = len(sinistro_list)

        report["total_encontrados"] = total_sinistros
        print(f"Status: {STATUS_IMPORTAR} | Encontrados: {total_sinistros} | Limite inserções: {QUANTIDADE_IMPORTAR}")

        inseridos = 0
        apolices_cache = {}

        for idx, sinistro in enumerate(sinistro_list, start=1):
            if inseridos >= QUANTIDADE_IMPORTAR:
                break

            if db.Notification.find_one({"claimNumber": sinistro}):
                report["ja_existentes"].append(sinistro)
                continue

            pn = sinistro_apolice_map.get(sinistro)
            if pn not in apolices_cache:
                exists = db_indexed[COLLECTION_INDEXED].find_one(
                    {"policy_number": pn}, {"_id": 1}
                )
                apolices_cache[pn] = exists is not None

            if not apolices_cache[pn]:
                report["apolice_nao_encontrada"].append(sinistro)
                continue

            try:
                resultado = process_sinistro(idx, sinistro, total_sinistros, db, db_indexed)
                if resultado == "sincronizado":
                    report["sincronizados"].append(sinistro)
                    inseridos += 1
                elif resultado == "ja_existe":
                    report["ja_existentes"].append(sinistro)
                elif resultado == "sem_detalhes":
                    report["sem_detalhes"].append(sinistro)
                elif resultado == "apolice_nao_encontrada":
                    report["apolice_nao_encontrada"].append(sinistro)
            except Exception as e:
                report["erros"].append({"sinistro": sinistro, "erro": str(e)})

        print(f"Elegíveis processados | Inseridos: {inseridos} | Cache apólices: {len(apolices_cache)}")

    client_indexed.close()

    report["fim"] = datetime.now()
    report["duracao_segundos"] = (report["fim"] - report["inicio"]).total_seconds()

    print("\n" + "=" * 60)
    print("RELATÓRIO DE SINCRONIZAÇÃO")
    print("=" * 60)
    print(f"Status importado: {STATUS_IMPORTAR}")
    print(f"Total encontrados no SQL: {report['total_encontrados']}")
    print(f"Sincronizados: {len(report['sincronizados'])}")
    print(f"Já existentes (pulados): {len(report['ja_existentes'])}")
    print(f"Sem detalhes: {len(report['sem_detalhes'])}")
    print(f"Apólice não encontrada: {len(report['apolice_nao_encontrada'])}")
    print(f"Erros: {len(report['erros'])}")
    print(f"Total já processados: {len(report['ja_existentes']) + len(report['sincronizados'])}")
    print(f"Duração: {report['duracao_segundos']:.1f}s")
    print("=" * 60)

    if report["sincronizados"]:
        print(f"\nSinistros sincronizados ({len(report['sincronizados'])}):")
        for s in report["sincronizados"]:
            print(f"  - {s}")

    if report["erros"]:
        print(f"\nErros ({len(report['erros'])}):")
        for e in report["erros"]:
            print(f"  - Sinistro {e['sinistro']}: {e['erro']}")

    print("\nSincronização finalizada.")

if __name__ == "__main__":
    main()
