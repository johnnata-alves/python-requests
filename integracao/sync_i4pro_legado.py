import os
import pyodbc
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pymongo import MongoClient
from datetime import datetime, date
from decimal import Decimal
from dotenv import load_dotenv

load_dotenv()

MAX_WORKERS = int(os.getenv("WORKERS", "16"))
SQL_BATCH = int(os.getenv("SQL_BATCH", "500"))
USER_CODE = "johnnata.alves"

SQL_CONNECTION = os.getenv("SQL_CONNECTION_I4PRO_PRD")
MONGO_CONNECTION = os.getenv("PRD_MONGO_URI")
MONGO_AVISO_CONNECTION = os.getenv("PRD_MONGO_SA_EAST")
DATABASE_MONGO = "ClaimEngine"
DATABASE_AVISO = "SinistrosMicroService"

WHERE_FILTRO = "csin.id_ramo not in (33) and csin.dt_sistema > '2025-01-01'"

SINISTRO_LIST_QUERY = f"""
select distinct csin.nr_sinistro
    from i4pro_erp..corp_sinistro csin with(NOLOCK)
    inner join i4pro_erp..corp_endosso ce with(NOLOCK) on csin.id_endosso = ce.id_endosso
    inner join i4pro_erp..corp_sub_estipulante cse with(NOLOCK) on ce.id_sub = cse.id_sub
    inner join i4pro_erp..corp_apolice ca with(NOLOCK) on cse.id_apolice = ca.id_apolice
    where {WHERE_FILTRO}
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
    mvto.id_produto_cobertura as ProdutoCobertura,
	mvto2.id_tp_motivo
from
    i4pro_erp..corp_sinistro csin with(NOLOCK)
    inner join i4pro_erp..corp_sin_movto mvto with(NOLOCK) on csin.nr_sinistro = mvto.nr_sinistro and mvto.cd_evento = 10101
    left join i4pro_erp..corp_sin_movto mvto2 with(NOLOCK) on csin.nr_sinistro = mvto2.nr_sinistro and mvto2.cd_evento = 10105
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
where csin.nr_sinistro in ({placeholders})
"""

DOC_QUERY = """
    select d.nr_sinistro, d.id_sin_documento, d.id_documento, d.dt_recebimento, d.dt_solicitacao, d.dv_solicitar, d.id_sin_beneficiario
    from i4pro_erp..corp_sin_documento d with(NOLOCK)
    where d.nr_sinistro in ({placeholders})
"""

AVISO_PROJECTION = {"Protocolo": 1, "Segurado": 1, "Reclamante": 1, "InformacoesComplementares": 1, "Sinistros": 1}


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
    text = str(value).strip()
    return text.zfill(11) if text else None


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


def load_coverage_map(db):
    cov = {}
    for d in db.Coverage.find({}, {"coverage": 1, "groupCoverageCodes": 1, "coverageCodes": 1}):
        for g in d.get("groupCoverageCodes") or []:
            cov[("g", g)] = d.get("coverage")
        for c in d.get("coverageCodes") or []:
            cov[("c", c)] = d.get("coverage")
    return cov


def load_relationship_map(db):
    return {d["RelationshipCode"]: d.get("Relationship")
            for d in db.Relationship.find({}, {"RelationshipCode": 1, "Relationship": 1})
            if "RelationshipCode" in d}


def load_docmap(db):
    return {d["ERPDocumentId"]: d.get("ERPDocumentName")
            for d in db.DocumentTypeMappings.find({}, {"ERPDocumentId": 1, "ERPDocumentName": 1})
            if "ERPDocumentId" in d}


def build_claim_document(sinistro, registros, aviso, cov_map, rel_map):
    base = registros[0]

    protocolo_num = aviso.get("Protocolo") or f"SIN-{sinistro}"    
    reclamante_aviso = aviso.get("Reclamante") or {}
    info_compl = aviso.get("InformacoesComplementares") or {}
    origem_documento = info_compl.get("origemdocumento", "")

    group_code_base = int(base["IdGrupoCobertura"]) if base["IdGrupoCobertura"] else None
    if group_code_base:
        coverage_value = cov_map.get(("g", group_code_base))
    else:
        coverage_value = cov_map.get(("c", int(base["IdCobertura"]) if base["IdCobertura"] else None))

    relacao = int(base["IdRelacao"]) if base["IdRelacao"] else None
    relationship_value = rel_map.get(relacao, "OTHER") if relacao else "OTHER"

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
        "documentNumber": normalize_cpf(base["CPFSegurado"]),
        "name": base["NomeSegurado"],
        "birthDate": format_birthdate(base.get("NascimentoSegurado")),
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

    return {
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
        "step": "REGULATION",
        "additionalInformation": {},
        "regulatoryStatusCode": status_code,
        "occurrenceCodeUf": int(base["UFOcorrencia"]) if base["UFOcorrencia"] else None,
        "occurrenceNameCity": base["CidadeOcorrencia"],
        "causeType": base["TipoCausa"],
        "regulatoryStatusName": base["StatusSinistro"],
        "createdOrigin": None,
        "updatedOrigin": origem_documento,
        "isJudicial": False,
        "priorityFlag": False,
        "cancellationReasonCode": to_int_or_none(base.get("id_tp_motivo")),
    }


def build_document(sinistro, doc_row, protocolo_num, docmap):
    status = "Pending" if doc_row["dt_recebimento"] is None else "Completed"
    return {
        "UpdatedUserName": USER_CODE,
        "UpdatedAt": doc_row["dt_solicitacao"],
        "CreatedAt": doc_row["dt_solicitacao"],
        "DeliveryAt": None,
        "flowId": "",
        "claimNumber": sinistro,
        "protocol": protocolo_num,
        "documentName": docmap.get(to_int_or_none(doc_row["id_documento"])),
        "documentCode": to_int_or_none(doc_row["id_documento"]),
        "docClassificationCode": "Basic",
        "documentIsRequired": bool(doc_row["dv_solicitar"]),
        "requestDate": doc_row["dt_solicitacao"],
        "receiveDate": doc_row["dt_recebimento"],
        "beneficiaryCode": to_int_or_none(doc_row["id_sin_beneficiario"]) or 0,
        "justification": None,
        "userCode": "",
        "status": status,
        "integrationStatus": "Synchronized",
        "isActive": True,
        "claimDocumentId": to_int_or_none(doc_row["id_sin_documento"]),
        "step": "Pending",
        "createdOrigin": "Platform",
        "updatedOrigin": "I4Pro",
        "isReportDocument": False,
        "attachments": [],
        "isSupplemental": None,
    }


def build_attachment(anexo, protocolo_num, origem_documento):
    key = anexo.get("Key") or ""
    insert_date = anexo.get("DataInclusaoAnexo") or datetime.utcnow()
    file_name = key.split("/")[-1] if "/" in key else key
    return {
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
        "hash": anexo.get("Hash") or "",
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


def fetch_grouped(sql_conn, query_template, key_col, sinistros):
    placeholders = ",".join("?" * len(sinistros))
    cursor = sql_conn.cursor()
    cursor.execute(query_template.format(placeholders=placeholders), sinistros)
    columns = [c[0] for c in cursor.description]
    key_idx = columns.index(key_col)
    grouped = defaultdict(list)
    for row in cursor.fetchall():
        grouped[int(row[key_idx])].append(dict(zip(columns, row)))
    return grouped


_thread_local = threading.local()


def get_sql_conn():
    if not hasattr(_thread_local, "sql_conn"):
        _thread_local.sql_conn = pyodbc.connect(SQL_CONNECTION)
    return _thread_local.sql_conn


def main():
    inicio = datetime.now()

    client = MongoClient(MONGO_CONNECTION)
    db = client[DATABASE_MONGO]
    client_aviso = MongoClient(MONGO_AVISO_CONNECTION)
    db_aviso = client_aviso[DATABASE_AVISO]

    sql_conn = pyodbc.connect(SQL_CONNECTION)

    print("Carregando lista de sinistros...")
    cursor = sql_conn.cursor()
    cursor.execute(SINISTRO_LIST_QUERY)
    sinistro_list = [int(r[0]) for r in cursor.fetchall()]
    sql_conn.close()
    total = len(sinistro_list)
    print(f"Sinistros: {total}")

    print("Carregando mapas de apoio (Coverage/Relationship/DocMappings)...")
    cov_map = load_coverage_map(db)
    rel_map = load_relationship_map(db)
    docmap = load_docmap(db)

    print("Pré-carregando claims já existentes...")
    existing = set(db.LegacyClaim.distinct("claimNumber")) | set(db.Claim.distinct("claimNumber"))
    print(f"  já existentes na base: {len(existing)}")

    pendentes_total = [s for s in sinistro_list if s not in existing]
    ja_existe_total = total - len(pendentes_total)
    print(f"Pendentes a processar: {len(pendentes_total)} | já existentes: {ja_existe_total}")

    counters = {"sincronizado": 0, "sem_detalhes": 0, "ja_existe": ja_existe_total, "erros": 0}
    lock = threading.Lock()

    batches = [pendentes_total[i:i + SQL_BATCH] for i in range(0, len(pendentes_total), SQL_BATCH)]

    def process_batch(batch):
        local = {"sincronizado": 0, "sem_detalhes": 0, "erros": 0}
        conn = get_sql_conn()

        details_by_sin = fetch_grouped(conn, DETAIL_QUERY, "Sinistro", batch)
        docs_by_sin = fetch_grouped(conn, DOC_QUERY, "nr_sinistro", batch)

        str_to_sin = {str(s): s for s in batch}
        aviso_map = {}
        for av in db_aviso["AvisoSinistro"].find({"Sinistros": {"$in": list(str_to_sin.keys())}}, AVISO_PROJECTION):
            sins = av.get("Sinistros")
            if isinstance(sins, list):
                for sv in sins:
                    if str(sv) in str_to_sin:
                        aviso_map[str_to_sin[str(sv)]] = av
            elif str(sins) in str_to_sin:
                aviso_map[str_to_sin[str(sins)]] = av

        protocolos = {a.get("Protocolo") for a in aviso_map.values() if a.get("Protocolo")}
        anexos_by_proto = defaultdict(list)
        if protocolos:
            for anexo in db_aviso["AvisoSinistroAnexo"].find(
                {"Protocolo": {"$in": list(protocolos)}}, {"Key": 1, "Hash": 1, "DataInclusaoAnexo": 1, "Protocolo": 1}
            ):
                anexos_by_proto[anexo.get("Protocolo")].append(anexo)

        claims_buf, docs_buf, attach_buf = [], [], []
        for sinistro in batch:
            registros = details_by_sin.get(sinistro)
            if not registros:
                local["sem_detalhes"] += 1
                continue
            try:
                aviso = aviso_map.get(sinistro, {})
                claim = build_claim_document(sinistro, registros, aviso, cov_map, rel_map)
                protocolo_num = claim["protocol"]
                origem_documento = claim["notificationOrigin"]
                claims_buf.append(sanitize_for_mongo(claim))

                for doc_row in docs_by_sin.get(sinistro, []):
                    docs_buf.append(sanitize_for_mongo(build_document(sinistro, doc_row, protocolo_num, docmap)))

                for anexo in anexos_by_proto.get(protocolo_num, []):
                    attach_buf.append(sanitize_for_mongo(build_attachment(anexo, protocolo_num, origem_documento)))

                local["sincronizado"] += 1
            except Exception as e:
                local["erros"] += 1
                print(f"  ERRO {sinistro}: {e}")

        if claims_buf:
            db.LegacyClaim.insert_many(claims_buf, ordered=False)
        if docs_buf:
            db.LegacyDocument.insert_many(docs_buf, ordered=False)
        if attach_buf:
            db.LegacyAttachment.insert_many(attach_buf, ordered=False)

        return local

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(process_batch, b) for b in batches]
        for fut in as_completed(futures):
            local = fut.result()
            with lock:
                for k, v in local.items():
                    counters[k] += v
                done = counters["sincronizado"] + counters["sem_detalhes"] + counters["ja_existe"] + counters["erros"]
                print(f"[{done}/{total}] sync={counters['sincronizado']} skip={counters['ja_existe']} "
                      f"sem_detalhe={counters['sem_detalhes']} erro={counters['erros']}")

    client.close()
    client_aviso.close()

    duracao = (datetime.now() - inicio).total_seconds()
    print("\n" + "=" * 60)
    print("RELATÓRIO DE SINCRONIZAÇÃO LEGADO")
    print("=" * 60)
    print(f"Total SQL: {total}")
    print(f"Sincronizados: {counters['sincronizado']}")
    print(f"Sem detalhes/pulados: {counters['sem_detalhes']}")
    print(f"Já existentes: {counters['ja_existe']}")
    print(f"Erros: {counters['erros']}")
    print(f"Duração: {duracao:.1f}s")
    print("=" * 60)


if __name__ == "__main__":
    main()
