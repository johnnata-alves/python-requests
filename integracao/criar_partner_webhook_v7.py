


import json
import os
import requests
from datetime import datetime, timezone

from bson import ObjectId
from bson.int64 import Int64
from dotenv import load_dotenv
from pymongo import MongoClient
from tqdm import tqdm

load_dotenv()

MONGO_URI = os.getenv("PRD_MONGO_URI")
DB_NAME = "ClaimEngine"

# SinistroTimeline (usada para achar o idPagamento hash de eventos legados)
MONGO_URI_SA_EAST = os.getenv("PRD_MONGO_SA_EAST")
DB_NAME_SINISTRO = "SinistrosMicroService"

# Eventos: "ClaimOpened", "DocumentRequested", "ClaimStatusChanged", "CompensationPaid", "ClaimReopen"
# "ClaimReopen" cria um ClaimStatusChanged com status 10103 (Reaberto).
# "CompensationPaid" (ou "CompensationReleased + CompensationPaid") dispara o mesmo bloco:
# cria CompensationReleased + CompensationPaid (+ ClaimStatusChanged 447) com a logica atual.
EVENTS_TO_CREATE = "ClaimReopen"

# DRY_RUN = True -> simula, NAO grava no banco. False -> grava de verdade.
DRY_RUN = False

# INCLUIR_COMPENSATION_RELEASED = False -> pula o CompensationReleased,
# cria apenas CompensationPaid + ClaimStatusChanged 447 (caso pontual).
INCLUIR_COMPENSATION_RELEASED = True

LEGACY_DOCUMENT_REQUESTED_CODES = [124, 314]

COMPENSATION_RELEASED_EVENT_STATUS = "11111"
COMPENSATION_PAID_EVENT_STATUS = "11112"


def consultar_detalhes_sinistro(nr_sinistro):
    url = f'{os.getenv("I4PRO_ERPWS_READ")}/erpws/run/Sinistro/ConsultaDetalheSinistro'
    payload = {"numSinistro": nr_sinistro, "dvUserAdmin": True}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception:
        return None

# Lista de sinistros a processar
SINISTROS = [
2007700050036,
2007700052327,
2007700053320,
2007700043057,
2007700042588,
2007700042506,
2007700042619,
2007700054485,
2007700017093,
2007700012127,
2007700010968
]


def _to_int(value):
    try:
        return int(value)
    except Exception:
        return None


def _to_int_or_default(value, default=0):
    parsed = _to_int(value)
    return parsed if parsed is not None else default


def _first_present(*values):
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _pick_principal(items):
    items = items or []
    for item in items:
        if item.get("principal"):
            return item
    return items[0] if items else None


def _to_iso_z(value):
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    return None


def _to_iso_without_timezone(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat(timespec="seconds")
    return None


def _to_midnight_utc_z(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        value = value.replace(hour=0, minute=0, second=0, microsecond=0)
        return value.isoformat().replace("+00:00", "Z")
    return None


def _resolve_partner_coverage_id(partner, claim):
    claim_coverage = str(claim.get("coverage") or "").strip()
    for coverage in partner.get("coverages", []) or []:
        if str(coverage.get("coverage") or "").strip() == claim_coverage:
            return _to_int(coverage.get("externalCoverage"))
    return None


def _resolve_partner_cause_type_id(partner, claim):
    claim_cause_type = str(claim.get("causeType") or "").strip()
    for cause_type in partner.get("causeTypes", []) or []:
        if str(cause_type.get("causeType") or "").strip() == claim_cause_type:
            return _to_int(cause_type.get("externalCauseType"))
    return None


def _resolve_claim_contract_date(claim):
    return _to_iso_without_timezone(_first_present(
        claim.get("contractDate"),
        claim.get("policyStartDate"),
        claim.get("startDate"),
        claim.get("coverageStartDate"),
    ))


def _resolve_claim_opened_status_text(claim):
    claim_number = claim.get("claimNumber")
    protocol = claim.get("protocol")
    product_name = claim.get("productName") or ""
    return f"Sinistro: {claim_number} aberto com o protocolo {protocol} para os produtos {product_name}"


def _resolve_claim_coverage_code(claim):
    coverage_code = claim.get("coverage")
    if coverage_code not in (None, ""):
        return coverage_code
    for coverage in claim.get("coverages", []) or []:
        code = _first_present(coverage.get("coverage"), coverage.get("coverageCode"))
        if code not in (None, ""):
            return code
    return None


def _resolve_partner_external_coverage(partner, claim_coverage_code):
    claim_coverage = str(claim_coverage_code or "").strip()
    if not claim_coverage:
        return None
    for coverage in partner.get("coverages", []) or []:
        if str(coverage.get("coverage") or "").strip() == claim_coverage:
            external_coverage = coverage.get("externalCoverage")
            return str(external_coverage) if external_coverage is not None else None
    return None


def _build_claim_opened_payload(claim, partner):
    insured = claim.get("insured") or {}
    requestor = claim.get("requestor") or {}
    insured_document = _first_present(insured.get("documentNumber"), insured.get("cpfCnpj"))
    insured_name = insured.get("name")

    partner_requestor = partner.get("requestorDetails")
    if partner_requestor:
        reclamante = {
            "aceitaComunicacao": partner_requestor.get("acceptsCommunication"),
            "tipoComunicacao": partner_requestor.get("communicationType") or "",
            "tipoComunicacaoValue": partner_requestor.get("communicationTypeValue"),
            "email": partner_requestor.get("email"),
            "telefone": partner_requestor.get("phone"),
            "proprioSegurado": partner_requestor.get("isInsured"),
            "cpfCnpj": partner_requestor.get("document"),
            "nome": partner_requestor.get("name"),
            "genero": partner_requestor.get("gender") or "",
            "endereco": partner_requestor.get("address"),
            "relacao": partner_requestor.get("relationship") or "SEG - SEGURADO(A)",
        }
    else:
        relationship = requestor.get("relationship")
        req_email = _pick_principal(requestor.get("emails") or [])
        req_phone = _pick_principal(requestor.get("phones") or [])
        reclamante = {
            "aceitaComunicacao": requestor.get("acceptsCommunication"),
            "tipoComunicacao": "",
            "tipoComunicacaoValue": None,
            "email": req_email.get("email") if req_email else None,
            "telefone": req_phone.get("number") if req_phone else None,
            "proprioSegurado": requestor.get("requestorIsInsured"),
            "cpfCnpj": requestor.get("documentNumber"),
            "nome": requestor.get("name"),
            "genero": requestor.get("gender") or "",
            "endereco": None,
            "relacao": relationship if relationship not in (None, "") else "SEG - SEGURADO(A)",
        }

    now = datetime.now(timezone.utc)

    return {
        "protocolo": claim.get("protocol"),
        "numeroSinistro": str(claim.get("claimNumber")) if claim.get("claimNumber") is not None else None,
        "produto": {
            "codigo": _to_int(claim.get("product")),
            "descricao": claim.get("productName"),
        },
        "status": _resolve_claim_opened_status_text(claim),
        "ocorrencia": _to_iso_z(claim.get("occurrenceDate")),
        "segurado": {
            "nome": insured_name,
            "cpfCnpj": insured_document,
            "dataNascimento": _to_iso_z(insured.get("birthDate")),
            "endereco": None,
        },
        "reclamante": reclamante,
        "sinistrado": {
            "cpfCnpj": insured_document,
            "nome": insured_name,
        },
        "itens": [],
        "relato": claim.get("occurrenceDescription") or None,
        "apolices": [{
            "numeroApolice": _to_int(claim.get("policyNumber")) or claim.get("policyNumber"),
            "numeroCertificado": _to_int_or_default(claim.get("certificate"), 0),
            "codigoEstipulante": None,
            "dataContrato": _resolve_claim_contract_date(claim),
            "coberturas": [{
                "id": _resolve_partner_coverage_id(partner, claim),
                "grupoCoberturaId": 0,
                "tipoCausaId": _resolve_partner_cause_type_id(partner, claim),
                "saldoDevedor": None,
            }],
            "endereco": None,
        }],
        "cnpjEstipulante": partner.get("partnerId"),
        "garantido": None,
        "beneficiarios": [],
        "informacoesComplementares": {
            "origemdocumento": "platform",
        },
        "dataDoAviso": _to_midnight_utc_z(_first_present(
            claim.get("notificationDate"), claim.get("CreatedAt"), now
        )),
        "codigoStatus": 20002,
    }


def _build_legacy_document_requested_payload(claim, documents_map):
    request_date = _to_iso_without_timezone(datetime.now(timezone.utc))
    pending_documents = []
    for document_code in LEGACY_DOCUMENT_REQUESTED_CODES:
        document_info = documents_map.get(document_code, {})
        pending_documents.append({
            "idDocumento": document_code,
            "nomeDocumento": document_info.get("documentName") or str(document_code),
            "dataSolicitacao": request_date,
            "nomeClassificacao": "basic",
        })

    return {
        "protocolo": claim.get("protocol"),
        "codigoProduto": _to_int(claim.get("product")),
        "numeroSinistro": claim.get("claimNumber"),
        "status": "426",
        "dataEvento": _to_iso_z(datetime.now(timezone.utc)),
        "documentosPendentes": pending_documents,
        "numeroBilhete": claim.get("certificate"),
        "numeroApolice": str(claim.get("policyNumber")) if claim.get("policyNumber") is not None else None,
    }


def _build_partner_codes_map(raw_payment):
    if isinstance(raw_payment, list):
        return {str(pd.get("partnerCode") or "").strip(): pd for pd in raw_payment}
    if isinstance(raw_payment, dict):
        pc = str(raw_payment.get("partnerCode") or "").strip()
        return {pc: raw_payment} if pc else {"": raw_payment}
    return {}


def _default_payment_details(raw_payment):
    if isinstance(raw_payment, list) and raw_payment:
        return raw_payment[0]
    if isinstance(raw_payment, dict):
        return raw_payment
    return {}


def _existe_legado_para_sinistro(db, claim_number, sinistro, partner_name):
    """Retorna True se ha algum evento importLegacy:true para o sinistro/partner."""
    claim_numbers = [claim_number, int(sinistro), str(sinistro)]
    doc = db["PartnerWebhook"].find_one({
        "claimNumber": {"$in": claim_numbers},
        "partner": partner_name,
        "importLegacy": True,
    })
    return doc is not None


def _buscar_hash_legado_timeline(sinistro_db, sinistro):
    """Busca na SinistroTimeline o hash de idPagamento (evento 11111) do sinistro.

    Elo: NumeroSinistro (= str do claimNumber) + Codigo "11111". Pega o PRIMEIRO doc
    e retorna o hash de InformacaoAdicional.Indenizacao.Pagamento.IdPagamento, ou None.
    """
    if sinistro_db is None:
        return None
    doc = sinistro_db["SinistroTimeline"].find_one(
        {"NumeroSinistro": str(sinistro), "Codigo": "11111"},
        {"InformacaoAdicional.Indenizacao.Pagamento.IdPagamento": 1},
    )
    if not doc:
        return None
    pagamento = (((doc.get("InformacaoAdicional") or {})
                  .get("Indenizacao") or {})
                 .get("Pagamento") or {})
    id_pag = pagamento.get("IdPagamento")
    return str(id_pag) if id_pag not in (None, "") else None


def _existe_evento(db, event, claim_number, sinistro, partner_name, id_pagamento, legado_hash=None):
    """Valida duplicidade do evento por payload.pagamento.idPagamento.

    Casa por idSInMvto (id_pagamento) e, se informado (sinistro legado), tambem
    pelo hash da SinistroTimeline. Se qualquer um ja existir, considera duplicado.
    """
    variants = []
    if id_pagamento is not None:
        variants.extend([id_pagamento, str(id_pagamento)])
    if legado_hash:
        variants.append(str(legado_hash))
    if not variants:
        return False
    claim_numbers = [claim_number, int(sinistro), str(sinistro)]
    existe = db["PartnerWebhook"].find_one({
        "event": event,
        "claimNumber": {"$in": claim_numbers},
        "partner": partner_name,
        "payload.pagamento.idPagamento": {"$in": variants},
    })
    return existe is not None


# Acumula os docs simulados em DRY_RUN para exportar depois
DRY_RUN_DOCS = []


def _inserir_webhook(db, doc):
    """Insere o doc no PartnerWebhook. Em DRY_RUN apenas coleta (nao grava)."""
    if DRY_RUN:
        DRY_RUN_DOCS.append(doc)
        return None
    return db["PartnerWebhook"].insert_one(doc)


def main():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]

    # Conexao com SinistrosMicroService (SinistroTimeline) para achar hashes de idPagamento legados
    sinistro_client = None
    sinistro_db = None
    if MONGO_URI_SA_EAST:
        sinistro_client = MongoClient(MONGO_URI_SA_EAST)
        sinistro_db = sinistro_client[DB_NAME_SINISTRO]

    if DRY_RUN:
        print(">>> DRY_RUN ATIVO: nada sera gravado no banco. Apenas simulacao. <<<")

    # Buscar partner PAN
    partner = db["Partner"].find_one({
        "active": True,
        "partner": "PAN"
    })
    if not partner:
        print("ERRO: Partner PAN não encontrado ou inativo.")
        client.close()
        return

    # Buscar documents map para DocumentRequested
    documents_map = {}
    for doc in db["Document"].find(
        {"documentCode": {"$in": LEGACY_DOCUMENT_REQUESTED_CODES}, "isActive": True},
        {"documentCode": 1, "documentName": 1, "_id": 0}
    ):
        code = _to_int(doc.get("documentCode"))
        if code is not None and code not in documents_map:
            documents_map[code] = doc

    print(f"Processando {len(SINISTROS)} sinistros...")
    print(f"Eventos ativos: {EVENTS_TO_CREATE}")

    criar_opened = "ClaimOpened" in EVENTS_TO_CREATE
    criar_requested = "DocumentRequested" in EVENTS_TO_CREATE
    criar_status_changed = "ClaimStatusChanged" in EVENTS_TO_CREATE
    criar_compensation_paid = "CompensationPaid" in EVENTS_TO_CREATE
    criar_reopen = "ClaimReopen" in EVENTS_TO_CREATE

    criados_opened = 0
    criados_requested = 0
    criados_status_changed = 0
    criados_compensation_released = 0
    criados_compensation_paid = 0
    duplicados_compensation_paid = 0
    duplicados_compensation_released = 0
    erros = 0
    resultados = []

    for sinistro in tqdm(SINISTROS, desc="Criando PartnerWebhook", unit="doc"):
        try:
            claim = db["LegacyClaim"].find_one({"claimNumber": int(sinistro)})
            is_legacy = True
            if not claim:
                claim = db["Claim"].find_one({"claimNumber": int(sinistro)})
                is_legacy = False
            if not claim:
                resultados.append({"sinistro": sinistro, "status": "Claim não encontrada"})
                erros += 1
                continue

            claim_number = claim.get("claimNumber")
            partner_name = partner.get("partner")
            now = datetime.now(timezone.utc)
            eventos_criados = []

            # ClaimOpened (cria se necessário para qualquer fluxo que dependa dele)
            needs_opened = criar_opened or criar_requested or criar_status_changed or criar_compensation_paid or criar_reopen
            if needs_opened:
                existe_opened = db["PartnerWebhook"].find_one({
                    "event": "ClaimOpened",
                    "claimNumber": {"$in": [claim_number, int(sinistro), str(sinistro)]},
                    "partner": partner_name,
                })

                if not existe_opened:
                    payload = _build_claim_opened_payload(claim, partner)
                    opened_doc = {
                        "event": "ClaimOpened",
                        "key": str(claim["_id"]),
                        "partner": partner_name,
                        "calls": [],
                        "claimNumber": claim_number,
                        "createdAt": now,
                        "deliveryAt": None,
                        "payload": payload,
                        "protocol": claim.get("protocol"),
                        "status": "Pending",
                        "legacyClaim": is_legacy,
                    }
                    _inserir_webhook(db, opened_doc)
                    criados_opened += 1
                    eventos_criados.append("ClaimOpened")

            # DocumentRequested
            if criar_requested:
                inicio_dia = now.replace(hour=0, minute=0, second=0, microsecond=0)
                existe_requested_hoje = db["PartnerWebhook"].find_one({
                    "event": "DocumentRequested",
                    "claimNumber": {"$in": [claim_number, int(sinistro), str(sinistro)]},
                    "partner": partner_name,
                    "createdAt": {"$gte": inicio_dia},
                })

                if not existe_requested_hoje:
                    doc_payload = _build_legacy_document_requested_payload(claim, documents_map)
                    requested_doc = {
                        "event": "DocumentRequested",
                        "key": str(claim["_id"]),
                        "partner": partner_name,
                        "calls": [],
                        "claimNumber": claim_number,
                        "createdAt": now,
                        "deliveryAt": None,
                        "payload": doc_payload,
                        "protocol": claim.get("protocol"),
                        "status": "Waiting",
                        "legacyClaim": is_legacy,
                    }
                    _inserir_webhook(db, requested_doc)
                    criados_requested += 1
                    eventos_criados.append("DocumentRequested")

            # ClaimStatusChanged (447 - Liquidado final) como Pending - sempre insere
            if criar_status_changed:
                status_payload = {
                    "protocolo": claim.get("protocol"),
                    "numeroSinistro": str(claim_number),
                    "descricao": "Liquidado final",
                    "status": "447",
                    "dataEvento": _to_iso_z(now),
                }
                status_doc = {
                    "event": "ClaimStatusChanged",
                    "key": str(claim_number),
                    "partner": partner_name,
                    "calls": [],
                    "claimNumber": claim_number,
                    "createdAt": now,
                    "deliveryAt": None,
                    "payload": status_payload,
                    "protocol": claim.get("protocol"),
                    "status": "Pending",
                    "legacyClaim": is_legacy,
                }
                _inserir_webhook(db, status_doc)
                criados_status_changed += 1
                eventos_criados.append("ClaimStatusChanged 447")

            # ClaimReopen: ClaimStatusChanged (10103 - Reaberto) como Pending - sempre insere
            if criar_reopen:
                reopen_payload = {
                    "protocolo": claim.get("protocol"),
                    "numeroSinistro": str(claim_number),
                    "descricao": "Reabertura",
                    "status": "10103",
                    "dataEvento": _to_iso_z(now),
                }
                reopen_doc = {
                    "event": "ClaimStatusChanged",
                    "key": str(claim_number),
                    "partner": partner_name,
                    "calls": [],
                    "claimNumber": claim_number,
                    "createdAt": now,
                    "deliveryAt": None,
                    "payload": reopen_payload,
                    "protocol": claim.get("protocol"),
                    "status": "Pending",
                    "legacyClaim": is_legacy,
                }
                _inserir_webhook(db, reopen_doc)
                criados_status_changed += 1
                eventos_criados.append("ClaimStatusChanged 10103")

            # CompensationPaid: processa TODOS os movimentos 11001.
            # Para cada movimento cria CompensationReleased + CompensationPaid,
            # validando duplicidade por idPagamento. ClaimStatusChanged 447 uma vez no fim.
            if criar_compensation_paid:
                detalhe = consultar_detalhes_sinistro(str(sinistro))
                raw_payment = partner.get("paymentDetails") or {}
                partner_codes_map = _build_partner_codes_map(raw_payment)

                movimentos_11001 = []
                if isinstance(detalhe, dict):
                    for mov in (detalhe.get("movimentos") or []):
                        if str(mov.get("codigoEvento")) == "11001":
                            movimentos_11001.append(mov)

                if not movimentos_11001:
                    eventos_criados.append("CompensationPaid: sem movimento 11001 no i4pro")
                else:
                    algum_paid_criado = False

                    # Sinistro legado: idPagamento vem do hash da SinistroTimeline (evento 11111).
                    tem_legado = _existe_legado_para_sinistro(db, claim_number, sinistro, partner_name)
                    legado_hash = None
                    if tem_legado:
                        legado_hash = _buscar_hash_legado_timeline(sinistro_db, sinistro)
                        if not legado_hash:
                            # Legado sem hash na timeline -> nao processa, marca como critica/erro
                            erros += 1
                            eventos_criados.append("ERRO CRITICO: legado sem hash 11111 na SinistroTimeline")
                            resultados.append({
                                "sinistro": sinistro,
                                "status": " + ".join(eventos_criados),
                            })
                            continue

                    for mov_indenizacao in movimentos_11001:
                        favorecido = str(mov_indenizacao.get("idPessoaFavorecido") or "").strip()
                        # So processa se o favorecido existir na Partner (paymentDetails).
                        if favorecido not in partner_codes_map:
                            eventos_criados.append(f"11001 ignorado: favorecido {favorecido} nao e do Partner")
                            continue
                        matched_payment_details = partner_codes_map[favorecido]

                        id_sin_movto = _to_int(mov_indenizacao.get("idSInMvto"))

                        # idPagamento do payload dos eventos: hash da timeline se legado;
                        # senao idSInMvto. So afeta payload.pagamento.idPagamento.
                        id_pagamento_evento = legado_hash if tem_legado else id_sin_movto

                        # Duplicidade: se legado, casa SOMENTE pelo hash (envios antigos
                        # nao tem hash, entao reenviar com hash e permitido).
                        # Se nao legado, casa por idSInMvto (como hoje).
                        if tem_legado:
                            dedup_id = None
                            dedup_hash = legado_hash
                        else:
                            dedup_id = id_sin_movto
                            dedup_hash = None
                        ja_tem_released = _existe_evento(db, "CompensationReleased", claim_number, sinistro, partner_name, dedup_id, dedup_hash)
                        ja_tem_paid = _existe_evento(db, "CompensationPaid", claim_number, sinistro, partner_name, dedup_id, dedup_hash)
                        # Pula o movimento se ja existe tudo que seria criado.
                        released_ja_resolvido = ja_tem_released or not INCLUIR_COMPENSATION_RELEASED
                        if released_ja_resolvido and ja_tem_paid:
                            duplicados_compensation_paid += 1
                            eventos_criados.append(f"CompensationPaid ja existe (idPagamento {id_sin_movto}) - ignorado")
                            continue

                        valor = mov_indenizacao.get("valor")
                        try:
                            valor = float(str(valor).replace(",", ".")) if valor else None
                        except (ValueError, TypeError):
                            valor = None

                        data_agendamento = mov_indenizacao.get("dataAgendamento")
                        data_pagamento = mov_indenizacao.get("dataAgendamento")
                        coverage_code = _resolve_claim_coverage_code(claim)
                        external_coverage = _resolve_partner_external_coverage(partner, coverage_code)
                        queue_key = str(id_sin_movto) if id_sin_movto else str(claim_number)

                        # CompensationReleased
                        released_payload = {
                            "protocolo": claim.get("protocol"),
                            "numeroSinistro": str(claim_number),
                            "codigoProduto": _to_int(claim.get("product")),
                            "certificado": claim.get("certificate"),
                            "apolice": str(claim.get("policyNumber")) if claim.get("policyNumber") else None,
                            "status": COMPENSATION_RELEASED_EVENT_STATUS,
                            "dataEvento": _to_iso_z(data_agendamento) if data_agendamento else _to_iso_z(now),
                            "pagamento": {
                                "dataAgendamento": _to_iso_z(data_agendamento) if data_agendamento else None,
                                "beneficiario": matched_payment_details.get("beneficiary"),
                                "cpfCnpjBeneficiario": partner.get("partnerId"),
                                "meioPagamento": matched_payment_details.get("paymentMethod"),
                                "codBanco": matched_payment_details.get("bankCode"),
                                "agencia": matched_payment_details.get("branch"),
                                "digitoAgencia": matched_payment_details.get("branchCheckDigit"),
                                "contaCorrente": matched_payment_details.get("accountNumber"),
                                "digitoContaCorrente": matched_payment_details.get("accountCheckDigit"),
                                "idPagamento": str(id_pagamento_evento) if id_pagamento_evento is not None else None,
                                "coberturas": [{
                                    "idPagamento": id_sin_movto,
                                    "tipoPagamento": "Cobertura",
                                    "cobertura": mov_indenizacao.get("cobertura"),
                                    "codCobertura": str(external_coverage) if external_coverage else None,
                                    "valor": valor,
                                }],
                                "valorTotal": valor,
                            },
                        }
                        released_doc = {
                            "event": "CompensationReleased",
                            "key": queue_key,
                            "partner": partner_name,
                            "calls": [],
                            "claimNumber": claim_number,
                            "createdAt": now,
                            "deliveryAt": None,
                            "payload": released_payload,
                            "protocol": claim.get("protocol"),
                            "status": "Pending",
                            "legacyClaim": is_legacy,
                        }
                        if not INCLUIR_COMPENSATION_RELEASED:
                            pass  # Released desligado por flag (caso pontual)
                        elif ja_tem_released:
                            duplicados_compensation_released += 1
                            eventos_criados.append(f"CompensationReleased duplicado (idPagamento {id_sin_movto}) - ignorado")
                        else:
                            _inserir_webhook(db, released_doc)
                            criados_compensation_released += 1
                            eventos_criados.append(f"CompensationReleased (idPagamento {id_pagamento_evento})")

                        # CompensationPaid
                        paid_payload = {
                            "protocolo": claim.get("protocol"),
                            "numeroSinistro": str(claim_number),
                            "codigoProduto": _to_int(claim.get("product")),
                            "certificado": claim.get("certificate"),
                            "apolice": str(claim.get("policyNumber")) if claim.get("policyNumber") else None,
                            "status": COMPENSATION_PAID_EVENT_STATUS,
                            "dataEvento": _to_iso_z(data_pagamento) if data_pagamento else _to_iso_z(now),
                            "pagamento": {
                                "dataEfetivacaoPagamento": _to_iso_z(data_pagamento) if data_pagamento else _to_iso_z(now),
                                "beneficiario": matched_payment_details.get("beneficiary"),
                                "cpfCnpjBeneficiario": partner.get("partnerId"),
                                "meioPagamento": matched_payment_details.get("paymentMethod"),
                                "codBanco": matched_payment_details.get("bankCode"),
                                "agencia": matched_payment_details.get("branch"),
                                "digitoAgencia": matched_payment_details.get("branchCheckDigit"),
                                "contaCorrente": matched_payment_details.get("accountNumber"),
                                "digitoContaCorrente": matched_payment_details.get("accountCheckDigit"),
                                "idPagamento": str(id_pagamento_evento) if id_pagamento_evento is not None else None,
                                "coberturas": [{
                                    "idPagamento": id_sin_movto,
                                    "tipoPagamento": "Cobertura",
                                    "cobertura": mov_indenizacao.get("cobertura"),
                                    "codCobertura": str(external_coverage) if external_coverage else None,
                                    "valor": valor,
                                }],
                                "valorTotal": valor,
                            },
                        }
                        paid_doc = {
                            "event": "CompensationPaid",
                            "key": queue_key,
                            "partner": partner_name,
                            "calls": [],
                            "claimNumber": claim_number,
                            "createdAt": now,
                            "deliveryAt": None,
                            "payload": paid_payload,
                            "protocol": claim.get("protocol"),
                            "status": "Pending",
                            "legacyClaim": is_legacy,
                        }
                        if ja_tem_paid:
                            duplicados_compensation_paid += 1
                            eventos_criados.append(f"CompensationPaid duplicado (idPagamento {id_sin_movto}) - ignorado")
                        else:
                            _inserir_webhook(db, paid_doc)
                            criados_compensation_paid += 1
                            algum_paid_criado = True
                            eventos_criados.append(f"CompensationPaid (idPagamento {id_pagamento_evento})")

                    # ClaimStatusChanged 447 - apenas se algum CompensationPaid novo foi criado
                    if algum_paid_criado:
                        status_payload = {
                            "protocolo": claim.get("protocol"),
                            "numeroSinistro": str(claim_number),
                            "descricao": "Liquidado final",
                            "status": "447",
                            "dataEvento": _to_iso_z(now),
                        }
                        status_doc = {
                            "event": "ClaimStatusChanged",
                            "key": str(claim_number),
                            "partner": partner_name,
                            "calls": [],
                            "claimNumber": claim_number,
                            "createdAt": now,
                            "deliveryAt": None,
                            "payload": status_payload,
                            "protocol": claim.get("protocol"),
                            "status": "Pending",
                            "legacyClaim": is_legacy,
                        }
                        _inserir_webhook(db, status_doc)
                        criados_status_changed += 1
                        eventos_criados.append("ClaimStatusChanged 447")

            resultados.append({
                "sinistro": sinistro,
                "status": " + ".join(eventos_criados) if eventos_criados else "Nenhum evento criado (já existentes)",
            })

        except Exception as e:
            resultados.append({"sinistro": sinistro, "status": f"ERRO: {e}"})
            erros += 1

    client.close()
    if sinistro_client is not None:
        sinistro_client.close()

    # Em DRY_RUN, exportar os artefatos que SERIAM gravados no MongoDB
    dry_run_file = None
    if DRY_RUN:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dry_run_file = f"dryrun_partner_webhook_{timestamp}.json"
        with open(dry_run_file, "w", encoding="utf-8") as f:
            json.dump(DRY_RUN_DOCS, f, ensure_ascii=False, indent=2, default=str)

    # Exportar Excel
    import pandas as pd
    df = pd.DataFrame(resultados)
    output_file = f"resultado_partner_webhook_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    df.to_excel(output_file, index=False, engine="openpyxl")

    print(f"\nFinalizado!")
    if DRY_RUN:
        print("  *** DRY_RUN: nada foi gravado no banco. Numeros abaixo = o que SERIA criado. ***")
    print(f"  ClaimOpened criados: {criados_opened}")
    print(f"  DocumentRequested criados: {criados_requested}")
    print(f"  ClaimStatusChanged criados: {criados_status_changed}")
    print(f"  CompensationReleased criados: {criados_compensation_released}")
    print(f"  CompensationPaid criados: {criados_compensation_paid}")
    print(f"  CompensationReleased duplicados (ignorados): {duplicados_compensation_released}")
    print(f"  CompensationPaid duplicados (ignorados): {duplicados_compensation_paid}")
    print(f"  Erros: {erros}")
    print(f"  Excel: {output_file}")
    if DRY_RUN and dry_run_file:
        print(f"  Artefatos simulados (JSON): {dry_run_file} ({len(DRY_RUN_DOCS)} docs)")


if __name__ == "__main__":
    main()
