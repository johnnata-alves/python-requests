import os

from dotenv import load_dotenv
from pymongo import MongoClient
import re
import json
import time
from datetime import datetime
from functools import cache
import pandas as pd
import requests
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.metrics import accuracy_score
import numpy as np
from dateutil import parser
from dateutil.relativedelta import relativedelta
from dateutil.tz import tzutc

load_dotenv()

@cache
def get_session(url: str = "") -> requests.Session:
    return requests.Session()

client = MongoClient(os.getenv("HML_MONGO_URI"))

dbOCR = client['OCR']
dbSinistrosMicroService = client['SinistrosMicroService']
urlErp = "http://toovasd09/i4pro_dev1/erpws/run/ConsultaDadosApolice/dadosApolice"
urlMotor = "https://sinistro-node-red-prod-interno.tooseguros.com.br/api/sinistro/cancelamento-automatico"
motor = {}
headers = {"Content-Type": "application/json"}
collectionOCR = dbOCR['AtomicLog']
collectionAvisoSinistro = dbSinistrosMicroService['AvisoSinistro']
collectionCoberturaConfiguracao = dbSinistrosMicroService['CoberturaConfiguracao']

protocolo_geral = "0jutovseqqw"
inicio_tempo = time.time()
def tempo():
    tempo_decorrido = time.time() - inicio_tempo
    return f"{tempo_decorrido:.2f} seg"

resultadosAviso = collectionAvisoSinistro.find({"Protocolo": protocolo_geral})
print(f"{protocolo_geral} - Sucesso: Consulta de aviso - {tempo()}")

resultadosCoberturaConfiguracao = collectionCoberturaConfiguracao.find()
print(f"{protocolo_geral} - Sucesso: Consulta setup coberturas - {tempo()}")

df = pd.read_csv('base_conhecimento.csv', sep=';')

df['Causa da morte'] = df['Causa da morte'].str.strip()

le = LabelEncoder()
df['Classificação'] = le.fit_transform(df['Classificação'])

X = df['Causa da morte']
y = df['Classificação']

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

vectorizer = TfidfVectorizer()
X_train_vec = vectorizer.fit_transform(X_train)
X_test_vec = vectorizer.transform(X_test)

model = MultinomialNB()
model.fit(X_train_vec, y_train)

y_pred = model.predict(X_test_vec)
accuracy = accuracy_score(y_test, y_pred)

def pascal_to_camel(pascal_case_str):
    if not pascal_case_str:
        return pascal_case_str
    return pascal_case_str[0].lower() + pascal_case_str[1:]

def convert_keys_to_camel_case(data):
    if isinstance(data, dict):
        return {
            pascal_to_camel(key): convert_keys_to_camel_case(value)
            for key, value in data.items()
        }
    elif isinstance(data, list):
        return [convert_keys_to_camel_case(item) for item in data]
    else:
        return data

def validar_coberturas(aviso):
    coberturas_validadas = []

    if aviso.get('origem') == 'Aviso API V4':
        for cobertura in aviso.get('coberturas_avisadas'):
            cobertura_id = cobertura.get('_id')
            tipo_causa_id = cobertura.get('TipoCausaId')
            for config in resultadosCoberturaConfiguracao:
                if config.get('CoberturaId') == cobertura_id and config.get('TipoCausaId') == tipo_causa_id:
                    for cobertura_item in config.get('CoberturasIntegracao', []):
                        coberturas_validadas.append({
                            "CoberturaId": cobertura_item.get('CoberturaId'),
                            "GrupoCoberturaId": cobertura_item.get('GrupoCoberturaId'),
                            "TipoCausaId": config.get('TipoCausaIdIntegracao')
                        })

    elif aviso.get('origem') in ['Formulário de Aviso Too', 'WhatsApp']:
        for cobertura in aviso.get('coberturas_avisadas'):
            coberturas_validadas.append({
                "CoberturaId": cobertura.get('_id'),
                "GrupoCoberturaId": cobertura.get('GrupoCoberturaId'),
                "TipoCausaId": cobertura.get('TipoCausaId')
            })

    print(f"{protocolo_geral} - Sucesso: Validação de coberturas - {tempo()}")

    return coberturas_validadas

def extrair_informacoes(aviso):
    data_ocorrencia = parser.isoparse(aviso.get('Ocorrencia'))
    data_comunicado = parser.isoparse(aviso.get('DataDoAviso'))
    segurado_cpf = aviso.get('Segurado', {}).get('CpfCnpj')
    protocolo = aviso.get('Protocolo')
    coberturas_avisadas = aviso.get('Coberturas', [])
    origem = aviso.get('InformacoesComplementares', {}).get('origemdocumento')
    saldo_devedor = aviso.get('InformacoesComplementares', {}).get('saldodevedorum')
    contrato_num = aviso.get('InformacoesComplementares', {}).get('contratoum')
    pessoa = consulta_pessoa(aviso)

    idade_obito = relativedelta(pessoa["data_nascimento"], data_ocorrencia).years *-1
    resultado_final = []
    causa_morte_texto = ''
    doc_certidao_obito = False
    doc_rg = False
    doc_cpf = False
    for cobertura in coberturas_avisadas:
        tipo_causa = "CAUSA NATURAL" if cobertura.get('TipoCausaId') == 4 else "CAUSA ACIDENTAL"
        cd_causa = "2" if cobertura.get('TipoCausaId') == 4 else "1"

    print(f"{protocolo_geral} - Sucesso: Extração de informações - {tempo()}")
    return {
        "data_ocorrencia": data_ocorrencia,
        "data_comunicado": data_comunicado,
        "segurado_cpf": segurado_cpf,
        "protocolo": protocolo,
        "coberturas_avisadas": coberturas_avisadas,
        "origem": origem,
        "resultado_final": resultado_final,
        "causa_morte_texto": causa_morte_texto,
        "doc_certidao_obito": doc_certidao_obito,
        "doc_rg": doc_rg,
        "doc_cpf": doc_cpf,
        "saldo_devedor": saldo_devedor,
        "contrato_num": contrato_num,
        "data_nascimento": pessoa["data_nascimento"],
        "cd_uf": pessoa["cd_uf"],
        "cidade": pessoa["cidade"],
        "idade_obito": idade_obito,
        "tipo_causa": tipo_causa,
        "cd_causa": cd_causa
    }

def classificar_obito (causas):

    novas_causas_vec = vectorizer.transform(causas)
    predicoes = model.predict(novas_causas_vec)

    classificacoes = le.inverse_transform(predicoes)

    probabilidades = model.predict_proba(novas_causas_vec)

    retorno = []
    print(f"{protocolo_geral} - Sucesso: Classificação de óbito - {tempo()}")
    for causa, classificacao, probabilidade in zip(causas, classificacoes, probabilidades):
        probabilidade_classificacao = probabilidade[le.transform([classificacao])[0]] * 100
        retorno.append({
                    "causa": causa,
                    "classificação": classificacao,
                    "acuracia": probabilidade_classificacao
                })

    return retorno

def buscar_documentos(aviso):
    docs = []
    pattern = re.compile(rf'.*{aviso.get("protocolo")}.*', re.IGNORECASE)

    resultadosOCR = collectionOCR.find({"NomeArquivo": pattern})

    doc_certidao_obito = False
    doc_rg = False
    doc_cpf = False
    causa_morte_texto = []
    classificacao_obito = []
    cpf_obito = ""
    for documento in resultadosOCR:
        nome_arquivo = documento.get("NomeArquivo")
        arquivos = documento.get("Resposta", {}).get("Arquivos", [])

        for arquivo in arquivos:
            for tipo_arquivo in arquivo.get("TipoArquivo", []):
                nome_tipo_arquivo = tipo_arquivo.get("NomeTipoArquivo")
                metadados = tipo_arquivo.get("Metadados", [])
                data_criacao = documento.get("DataCriacao")

                if nome_tipo_arquivo == '10 - Certidão de Óbito':
                    doc_certidao_obito = True
                    if 'CausaMorteTexto' in metadados:
                        causa_morte_texto.append(metadados['CausaMorteTexto'])
                    if 'CPFTexto' in metadados:
                        cpf_obito = metadados['CPFTexto'].replace("-","").replace(".","").replace("CPF","").replace(" ","").replace("/","")
                if nome_tipo_arquivo == '21 - RG':
                    doc_rg = True
                if nome_tipo_arquivo in ['21 - CNH', '21 - CPF']:
                    doc_cpf = True

                docs.append({
                    "NomeArquivo": nome_arquivo,
                    "NomeTipoArquivo": nome_tipo_arquivo,
                    "Metadados": metadados,
                    "DataCriacao": data_criacao
                })

    if len(causa_morte_texto) > 0:
        classificacao_obito = classificar_obito(causa_morte_texto)

    docs_recebidos = doc_certidao_obito and (doc_rg or doc_cpf)

    print(f"{protocolo_geral} - Sucesso: Consulta de documentos - {tempo()}")
    return {
        "docs_recebidos": docs_recebidos,
        "docs": docs,
        "classificacao_obito": classificacao_obito,
        "cpf_obito": cpf_obito,
        "causa_obito": ''.join(causa_morte_texto)
    }

def consultar_apolices(aviso, coberturas_validadas):
    urlErp = "http://toovasd09/i4pro_dev1/erpws/run/ConsultaDadosApolice/dadosApolice"
    response = get_session(urlErp).get(urlErp, params={"numCnpjCpfSegurado": aviso.get('segurado_cpf')})
    polices = []
    if response.status_code == 200:
        dados = response.json()
        for apolice in dados.get("dadosApolice", []):
            codigoProduto = apolice.get("codigoProduto")
            idItem = 0
            idProdutoCobertura = 0
            numeroApolice = apolice.get("numeroApolice")
            numeroBilhete = apolice.get("numeroBilhete")
            codigoSegurado = apolice.get("codigoSegurado")
            nomeProduto = apolice.get("nomeProduto")
            dadosEndosso = apolice.get("endosso", {}).get("dadosEndosso", [])
            dataInicioVigencia = datetime.strptime(apolice.get("dt_inicio_vigencia_item"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=tzutc())
            dataFimVigencia = datetime.strptime(apolice.get("dt_fim_vigencia_item"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=tzutc())
            vigencia = "sim" if dataInicioVigencia <= aviso.get('data_ocorrencia') <= dataFimVigencia else "não"
            cobertura_contratada = "não"
            valor_is = 0
            saldo_is = 0

            if len(dadosEndosso) == 0:
                cobertura_contratada = "talvez"

            for endosso in dadosEndosso:
                dataInicioVigencia = datetime.strptime(endosso.get("dataInicioVigencia"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=tzutc())
                dataFimVigencia = datetime.strptime(endosso.get("dataFimVigencia"), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=tzutc())

                vigencia = "sim" if dataInicioVigencia <= aviso.get('data_ocorrencia') <= dataFimVigencia else "não"

                for dadosItem in endosso.get("item", {}).get("dadosItem", []):
                    idItem = dadosItem.get('idItem')
                    for dadosCobertura in dadosItem.get("cobertura", {}).get("dadosCobertura", []):
                        valor_is = dadosCobertura.get("valorIS")
                        saldo_excedido = True if dadosCobertura.get("valorIS") >= aviso.get('saldo_devedor') else False
                        saldo_is = aviso.get('saldo_devedor') if dadosCobertura.get("valorIS") >= aviso.get('saldo_devedor') else dadosCobertura.get("valorIS")
                        if len(dadosCobertura.get("grupo", {}).get("gruposCobertura")) == 0:
                            for cobertura_validada in coberturas_validadas:
                                if dadosCobertura.get("idCobertura") == cobertura_validada.get('CoberturaId'):
                                    idProdutoCobertura = dadosCobertura.get("idProdutoCobertura")
                                    cobertura_contratada = "sim"
                                    break
                            if cobertura_contratada == "sim":
                                    break

                        for gruposCobertura in dadosCobertura.get("grupo", {}).get("gruposCobertura", []):
                            for cobertura_validada in coberturas_validadas:
                                if gruposCobertura.get("idGrupoCobertura") == cobertura_validada.get('GrupoCoberturaId'):
                                    idProdutoCobertura = dadosCobertura.get("idProdutoCobertura")
                                    cobertura_contratada = "sim"
                                    break
                                if cobertura_contratada == "sim":
                                    break
                        if cobertura_contratada == "sim":
                            break
                    if cobertura_contratada == "sim":
                        break

            if len(polices) > 0:
                for index, police in enumerate(polices):
                    encontrado = 0
                    if police["numeroApolice"] == numeroApolice:
                        encontrado = 1
                        break

                if encontrado == 1:
                    if vigencia == "sim" and police["cobertura_contratada"] == "não":
                        polices[index]["valor_is"] = valor_is
                        polices[index]["saldo_is"] = saldo_is
                        polices[index]["saldo_excedido"] = saldo_excedido
                        polices[index]["vigencia"] = vigencia
                        polices[index]["cobertura_contratada"] = (
                            cobertura_contratada
                        )
                        for index, original in enumerate(motor["apolices"]):
                            if original["numeroApolice"] == numeroApolice:
                                del motor["apolices"][index]
                                if len(dadosEndosso) > 0:
                                    for produto in produtos:
                                        if produto["codigo"] == codigoProduto:
                                            motor[
                                                "produtoElegivelAutomacoes"
                                            ].append(produto)
                                    motor["apolices"].append(apolice)

                else:
                    if len(dadosEndosso) > 0:
                        for produto in produtos:
                            if produto["codigo"] == codigoProduto:
                                motor["produtoElegivelAutomacoes"].append(produto)
                        motor["apolices"].append(apolice)
                    polices.insert(
                        1,
                        {
                            "numeroApolice": numeroApolice,
                            "numeroBilhete": numeroBilhete,
                            "codigoSegurado": codigoSegurado,
                            "codigoProduto": codigoProduto,
                            "nomeProduto": nomeProduto,
                            "dataInicioVigencia": dataInicioVigencia,
                            "dataFimVigencia": dataFimVigencia,
                            "vigencia": vigencia,
                            "cobertura_contratada": cobertura_contratada,
                            "valor_is": valor_is,
                            "saldo_is": saldo_is,
                            "saldo_excedido": saldo_excedido,
                            "idItem": idItem,
                            "idProdutoCobertura": idProdutoCobertura,
                            "ApoliceSinistrada": False
                        },
                    )

            else:
                if len(dadosEndosso) > 0:
                    for produto in produtos:
                        if produto["codigo"] == codigoProduto:
                            motor["produtoElegivelAutomacoes"].append(produto)
                    motor["apolices"].append(apolice)
                polices.insert(
                    1,
                    {
                        "numeroApolice": numeroApolice,
                        "numeroBilhete": numeroBilhete,
                        "codigoSegurado": codigoSegurado,
                        "codigoProduto": codigoProduto,
                        "nomeProduto": nomeProduto,
                        "dataInicioVigencia": dataInicioVigencia,
                        "dataFimVigencia": dataFimVigencia,
                        "vigencia": vigencia,
                        "cobertura_contratada": cobertura_contratada,
                        "valor_is": valor_is,
                        "saldo_is": saldo_is,
                        "idItem": idItem,
                        "idProdutoCobertura": idProdutoCobertura,
                        "ApoliceSinistrada": False
                    },
                )

    print(f"{protocolo_geral} - Sucesso: Consulta de apólices - {tempo()}")

    return {
        "polices": polices,
        "motor": motor
    }

def consulta_sinistros(aviso, polices):
    lista_apolices = polices.get('polices')
    url = 'http://toovasd09/i4pro_dev1/erpws/run/GetListaSinistros/GetListaSinistros'

    headers = {'Content-Type': 'application/json'}
    payload = json.dumps({"nr_cpf_cnpj": aviso.get('segurado_cpf')})

    response = requests.post(url, headers=headers, data=payload)

    if response.status_code == 200:
        resultado = response.json()

        if resultado["cd_retorno"] == 0:
            print(f"{protocolo_geral} - Sucesso: Consulta de Sinistros - Com resultados")
            sinistros = resultado['GetListaSinistrosTable1']
            for sinistro in sinistros:
                for index, police in enumerate(lista_apolices):
                    if sinistro['numeroApolice'] == police["numeroApolice"]:
                        lista_apolices[index]["ApoliceSinistrada"] = True
        else:
            print(f"{protocolo_geral} - Sucesso: Consulta de Sinistros - Sem resultados - {tempo()}")
    else:
        print(f"{protocolo_geral} - Erro: Consulta de Sinistros - {tempo()}")
        return []

    return {
        "polices": lista_apolices,
        "motor": polices.get('motor')
    }

def processar_motor_recusa(polices):
    apolices_analise = polices.get('polices')
    motor = polices.get('motor')
    body = json.dumps(motor)
    try:
        responseMotor = requests.post(urlMotor, headers=headers, json=motor)
    except requests.exceptions.RequestException as e:
            print(f"{protocolo_geral} - Erro: Processamento no motor de recusa - {e} - {tempo()}")

    if responseMotor.status_code == 200:
        resultado = responseMotor.json()
        for apolice in resultado["Apolices"]:
            for index, police in enumerate(apolices_analise):
                if apolice.get("NumeroApolice") == police["numeroApolice"]:
                    apolices_analise[index]["EnviarParaRegulacaoAutomatica"] = apolice.get("EnviarParaRegulacaoAutomatica")
                    apolices_analise[index]["MotivoRecusa"] = apolice.get("MotivoRecusa")

    print(f"{protocolo_geral} - Sucesso: Processamento no motor de recusa - {tempo()}")

    return {
        "polices": apolices_analise,
        "motor": polices.get('motor')
    }

def inserir_aviso_sinistro(aviso_retorno, police):
    url = 'http://toovasd09/i4pro_dev1/erpws/run/InserirAvisoSinistro/InserirAvisoSinistro'
    nr_sinistro = ""
    dados = {
        "dvAjusteResseguro": True,
        "cdApolice": police.get('numeroApolice'),
        "cdMoeda": 1,
        "cdCausa": 15032,
        "cdTpCausa": aviso_retorno.get('cd_causa'),
        "dtComunicado": aviso_retorno.get('data_comunicado').strftime("%Y-%m-%dT%H:%M:%S"),
        "dtOcorrencia": aviso_retorno.get('data_ocorrencia').strftime("%Y-%m-%dT%H:%M:%S"),
        "hrOcorrencia": "00:00",
        "cdUfOcorrencia": aviso_retorno.get('cd_uf'),
        "nmCidadeOcorrencia": aviso_retorno.get('cidade'),
        "idItem": police.get('idItem'),
        "idProdutoCobertura": police.get('idProdutoCobertura'),
        "idRamo": 77,
        "idReclamante": 308186,
        "idSinistrado": police.get('codigoSegurado'),
        "idSinRelacao": 17,
        "InserirDocumentos": [
            {"dvSolicitar": True, "dtRecebimento": "2024-09-13T18:23:45", "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 314},
            {"dvSolicitar": True, "dtRecebimento": "2024-09-13T18:23:45", "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 355},
            {"dvSolicitar": True, "dtRecebimento": "2024-09-13T18:23:45", "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 412},
            {"dvSolicitar": True, "dtRecebimento": "2024-09-13T18:23:45", "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 124},
            {"dvSolicitar": True, "dtRecebimento": "2024-09-13T18:23:45", "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 396},
            {"dvSolicitar": False, "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 136},
            {"dvSolicitar": False, "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 326},
            {"dvSolicitar": False, "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 357},
            {"dvSolicitar": False, "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 165},
            {"dvSolicitar": False, "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 356},
            {"dvSolicitar": False, "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 163},
            {"dvSolicitar": False, "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 169},
            {"dvSolicitar": False, "dtSolicitacao": "2024-09-13T18:23:45", "idDocumento": 57}
        ],
        "dvJuridico": False,
        "dvLiberaConsistencia": True,
        "nmCepOcorrencia": " ",
        "nmDescricaoSinistro": f"contratoum: {aviso_retorno.get('contrato_num')} - saldodevedorum: {aviso_retorno.get('saldo_devedor')} - datacaixapostal: {aviso_retorno.get('data_comunicado')} - datarecepccao: {aviso_retorno.get('data_comunicado')} -  datacomusinistro: {aviso_retorno.get('data_comunicado')} - origemdocumento: {aviso_retorno.get('origem')} - Pendente de Pré Análise",
        "nrEndosso": 0,
        "dvSinistradoSegurado": True,
        "cdUsuario": "usr_sinistro_motor",
        "vlEstimado": police.get('saldo_is'),
        "idSinJustificativaMovto": 25272
    }

    headers = {'Content-Type': 'application/json'}

    response = requests.post(url, headers=headers, data=json.dumps(dados))

    if response.status_code == 200:
        resultado = response.json()

        if resultado["cd_retorno"] == 0:
            nr_sinistro = resultado["nrSinistro"]
            print(f"{protocolo_geral} - Sucesso: Inserir aviso sinistro")
        else:
            nr_sinistro = re.search(r'Sinistro: (\d+)', resultado["nm_retorno"]).group(1)
            print(f"{protocolo_geral} - Erro: Inserir aviso sinistro - cd_retorno: {resultado['cd_retorno']} - nm_retorno: {resultado['nm_retorno']} - {tempo()}")

    return nr_sinistro

def inserir_follow_analise(aviso_retorno, police):
    url = 'http://toovasd09/i4pro_dev1/erpws/run/InserirFollowupSinistro/InserirFollowupSinistro'
    id_follow = 0
    data_atual = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    dados = {
        "cdOperacao": 1,
        "cdUsuarioDestinatario": "UsoFuturo",
        "dtFollowup": data_atual,
        "idSinTpInformacao": 2,
        "idTpFollowup": 70,
        "nrSinistro": police["nr_sinistro"],
        "cdUsuario": "usr_sinistro_motor",
        "dsFollowup": (
            f"Documentação para aviso de Sinistro - Documentos recebidos: "
            f"- CÓPIA SIMPLES DO RG OU CNH DO SEGURADO - Documento recebido via {aviso_retorno.get('origem')} em: {data_atual} "
            f"- CÓPIA SIMPLES OU NÚMERO DO CPF DO SEGURADO - Documento recebido via {aviso_retorno.get('origem')} em: {data_atual} "
            f"- CÓPIA SIMPLES DA CERTIDÃO DE ÓBITO DO SEGURADO - Documento recebido via {aviso_retorno.get('origem')} em: {data_atual} "
        )
    }

    headers = {'Content-Type': 'application/json'}

    response = requests.post(url, headers=headers, data=json.dumps(dados))

    if response.status_code == 200:
        resultado = response.json()

        if resultado["cd_retorno"] == 0:
            id_follow = resultado["idFollowup"]
            print(f"{protocolo_geral} - Sucesso: Inserir follow analise")
        else:
            print(f"{protocolo_geral} - Erro: Inserir follow analise - cd_retorno: {resultado['cd_retorno']} - nm_retorno: {resultado['nm_retorno']} - {tempo()}")

    return id_follow

def inserir_follow_regulacao(aviso_retorno, police):
    url = 'http://toovasd09/i4pro_dev1/erpws/run/InserirFollowupSinistro/InserirFollowupSinistro'
    id_follow = 0
    data_atual = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    dados = {
        "cdOperacao": 1,
        "cdUsuarioDestinatario": "UsoFuturo",
        "dtFollowup": data_atual,
        "idSinTpInformacao": 2,
        "idTpFollowup": 21,
        "nrSinistro": police["nr_sinistro"],
        "cdUsuario": "usr_sinistro_motor",
        "dsFollowup": (
            f"Trata-se de reclamação de morte. /n"
            f"Conforme documentos apresentados o segurado faleceu em {aviso_retorno.get('data_ocorrencia').strftime('%d/%m/%Y')}, aos {aviso_retorno.get('idade_obito')} anos de idade em decorrência de {aviso_retorno.get('tipo_causa')}. /n"
            f"Causa da morte: {aviso_retorno.get('causa_morte_texto')}  /n"
            f"  /n"
            f"Contrato: {aviso_retorno.get('contrato_num')}  /n"
            f"  /n"
            f"Produto: SEGURO CARTÃO CONSIGNADO A PARTIR 011019 - 7728 /n"
            f"Cobertura: MORTE /n"
            f"DPS: Não, conforme fluxo acordado /n"
            f"Vigência: {police['dataInicioVigencia']}  à {police['dataInicioVigencia']} - OK                                                                /n"
            f"Data do Sinistro: {aviso_retorno.get('data_ocorrencia').strftime('%d/%m/%Y')}                                                                                               /n"
            f"Carência: Não - 2 anos para suicídio /n"
            f"Franquia: Não há       /n"
            f"IS: {police['valor_is']}          /n"
            f"Saldo devedor informado pelo banco:  {aviso_retorno.get('saldo_devedor')}  /n"
            f"Indenização cabível: {police['saldo_is']} /n"
            f"Verba remanescente: Não /n"
            f"  /n"
            f"Beneficiário: BANCO PAN S.A /n"
            f"O BENEFICIÁRIO SERÁ SEMPRE O ESTIPULANTE, ATÉ O LIMITE DO SALDO DEVEDOR DO CARTÃO CONSIGNADO, RESPEITANDO O CAPITAL SEGURADO CONTRATADO. CASO HAJA SALDO REMANESCENTE, O SEGUNDO BENEFICIÁRIO, SERÁ AQUELE PREVIAMENTE INDICADO PELO SEGURADO, OU NA FALTA  DE INDICAÇÃO  EXPRESSA,  OU  SE  POR QUALQUER  MOTIVO  NÃO PREVALECER  A  QUE FOR  FEITA,SERÃO BENEFICIÁRIOS AQUELES INDICADOS EM LEI. /n"
            f"Processo sem irregularidades, documentação completa. /n"
            f"  /n"
            f"Direcionado para aprovação."
        )
    }

    headers = {'Content-Type': 'application/json'}

    response = requests.post(url, headers=headers, data=json.dumps(dados))

    if response.status_code == 200:
        resultado = response.json()

        if resultado["cd_retorno"] == 0:
            id_follow = resultado["idFollowup"]
            print(f"{protocolo_geral} - Sucesso: Inserir follow regulação")
        else:
            print(f"{protocolo_geral} - Erro: Inserir follow regulação - cd_retorno: {resultado['cd_retorno']} - nm_retorno: {resultado['nm_retorno']} - {tempo()}")

    return id_follow

def consulta_pessoa(aviso):
    url = 'http://toovasd09/i4pro_dev1/erpws/run/CadastroPessoaUnificado/PessoaPesquisar'
    headers = {'Content-Type': 'application/json'}
    data = {
        "nr_cnpj_cpf": aviso.get('Segurado', {}).get('CpfCnpj')
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        resposta_json = response.json()

        if resposta_json.get("cd_retorno") == 0:
            pessoa = resposta_json.get("pessoa")[0]
            dt_nascimento = pessoa.get("dt_nascimento")
            cd_uf = pessoa.get("Endereco")[0].get("cd_uf")
            cidade = pessoa.get("Endereco")[0].get("nm_cidade")
            print(f"{protocolo_geral} - Sucesso: Consulta pessoa - {tempo()}")

            return {
                "data_nascimento": parser.isoparse(dt_nascimento).replace(tzinfo=tzutc()),
                "cd_uf": cd_uf,
                "cidade": cidade
              }
        else:
            print(f"{protocolo_geral} - Erro: Consulta pessoa - cd_retorno - {tempo()}")
            return 0

    else:
        print(f"{protocolo_geral} - Erro: Consulta pessoa - {tempo()}")

def adicionar_dias_uteis(data_inicial, dias):

    data_np = np.datetime64(data_inicial).astype('datetime64[D]')
    dias_uteis_final = np.busday_offset(data_np, dias, roll='forward')
    return dias_uteis_final.astype('datetime64[D]').astype(datetime)

def calcular_data_agendamento():

    agora = datetime.now().replace(tzinfo=tzutc())
    if agora.hour >= 17:
        dias_uteis = 3
    else:
        dias_uteis = 2

    data_agendamento = adicionar_dias_uteis(agora, dias_uteis)
    print(f"{protocolo_geral} - Sucesso: Calcular data de pagamento - {tempo()}")
    return data_agendamento.strftime('%Y-%m-%d')

def registrar_documentos(nrSinistro):

    id_documentos = [136, 326, 357, 165, 356, 163, 169, 57]

    data_atual = datetime.now().strftime("%Y-%m-%d")

    url = 'http://toovasd09/i4pro_dev1/erpws/run/RegDocumentos/RegDocumentos'
    headers = {'Content-Type': 'application/json'}

    for idDocumento in id_documentos:
        dados = {
            "nrSinistro": nrSinistro,
            "dvSolicitar": False,
            "dtSolicitacao": data_atual,
            "dtRecebimento": data_atual,
            "cdOperacao": 1,
            "cdUsuario": "usr_sinistro_motor",
            "idDocumento": str(idDocumento),
            "idSinDocumentoClassificacao": "1",
            "nmJustificativa": "documento não requerido"
        }

        response = requests.post(url, headers=headers, json=dados)

        if response.status_code == 200:
            print(f"{protocolo_geral} - Sucesso: Registrar documentos - {tempo()}")
        else:
            print(f"{protocolo_geral} - Erro: Registrar documentos {idDocumento}: {response.status_code}, {response.text} - {tempo()}")

def agendar_pagamento(police):
    url = 'http://toovasd09/i4pro_dev1/erpws/run/RegistrarEventoSinistro/registrarEventoSinistro'
    headers = {'Content-Type': 'application/json'}
    id_movto = 0
    dados = {
        "cdTpIndenizacao": 1,
        "cdEvento": 11001,
        "cdIndicador": 1,
        "dtAgendamento": calcular_data_agendamento(),
        "idMeioPagamento": 3,
        "idPessoaFavorecido": 308186,
        "idProdutoCobertura": police["idProdutoCobertura"],
        "nrAgencia": "0001",
        "nrBanco": 623,
        "nrContaCorrente": "10870",
        "nrDacAgencia": "9",
        "nrDacContaCorrente": "9",
        "numSinistro": police["nr_sinistro"],
        "cdUsuario": "usr_sinistro_motor",
        "vlOperacao": police["saldo_is"]
    }

    response = requests.post(url, headers=headers, data=json.dumps(dados))

    if response.status_code == 200:
        resultado = response.json()

        if resultado["cd_retorno"] == 0:
            print(f"{protocolo_geral} - Sucesso: Agendar pagamento - {tempo()}")
            id_movto = resultado["id_sin_movto"]

        else:
            print(f"{protocolo_geral} - Erro: Agendar pagamento - cd_retorno: {resultado['cd_retorno']} - nm_retorno: {resultado['nm_retorno']} - {tempo()}")

    return id_movto

with open("produtos.json", "r", encoding="utf-8") as produtos:
    produtos = json.load(produtos)
    produtos = convert_keys_to_camel_case(produtos)

with open("request_motor.json", "r", encoding="utf-8") as motor:
    motor = json.load(motor)

for aviso in resultadosAviso:

    aviso_retorno = extrair_informacoes(aviso)

    coberturas_validadas = validar_coberturas(aviso_retorno)

    docs = buscar_documentos(aviso_retorno)

    if not docs['docs_recebidos']:
        print(f"{protocolo_geral} - Erro: documentos obrigatórios não recebidos - {tempo()}")
        break

    apolices = consultar_apolices(aviso_retorno, coberturas_validadas)

    apolices = processar_motor_recusa(apolices)

    apolices = consulta_sinistros(aviso_retorno, apolices)

    for index, police in enumerate(apolices["polices"]):
        if not police["ApoliceSinistrada"] and police["EnviarParaRegulacaoAutomatica"]  and police["codigoProduto"] == 251:

            nr_sinistro = inserir_aviso_sinistro(aviso_retorno, police)
            if nr_sinistro != "":
                apolices["polices"][index]["nr_sinistro"] = nr_sinistro

                registrar_documentos(nr_sinistro)

                id_follow = inserir_follow_analise(aviso_retorno, police)
                if id_follow > 0:
                    apolices["polices"][index]["id_follow"] = id_follow
                else:
                    print(f"{protocolo_geral} - Erro: Criação de follow de análise - {tempo()}")

                id_follow_regulacao = inserir_follow_regulacao(aviso_retorno, police)
                if id_follow_regulacao > 0:
                    apolices["polices"][index]["id_follow_regulacao"] = id_follow_regulacao
                else:
                    print(f"{protocolo_geral} - Erro: Criação de follow de regulação - {tempo()}")

                id_movto = agendar_pagamento(police)
                if id_movto > 0:
                    apolices["polices"][index]["id_movto"] = id_movto
                else:
                    print(f"{protocolo_geral} - Erro: Agendamento de pagamento - {tempo()}")
            else:
                print(f"{protocolo_geral} - Erro: Criação de sinistro - {tempo()}")
        else:
            print(f"{protocolo_geral} - Sucesso: Apolice {police['numeroApolice']} não elegível - {tempo()}")

    print('acabou')

client.close()
