import os
import pymongo
import requests
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import random
import string
from dotenv import load_dotenv

load_dotenv()

mongo_client = pymongo.MongoClient(os.getenv("PRD_MONGO_SA_EAST"))
dbOCR = mongo_client['OCR']
dbDocumentManagement = mongo_client['DocumentManagement']
dbSinistro = mongo_client['SinistrosMicroService']
session = requests.Session()
session.headers.update({'X-Api-Key': os.getenv("EBOX_API_KEY")})
cache = {}
cont = 0
cont_geral = 0

def obter_ultima_data_importada():
    ultimo_registro = dbDocumentManagement['AnexoDetalhes'].find().sort('DataCriacao', -1).limit(1)
    ultimo_registro = list(ultimo_registro)
    if ultimo_registro:
        ultima_data_criacao = ultimo_registro[0]['DataCriacao']
    else:
        ultima_data_criacao = None
    return ultima_data_criacao

def documentos_novos():
    global cont_geral
    global cont
    cont = 0
    ultima_data_importada = datetime.now() - timedelta(days=30)
    global cont_geral
    cont_geral = dbOCR['AtomicLog'].count_documents({"DataCriacao": {"$gt": ultima_data_importada }})
    print(f"\n\n🚀 Quantidade de itens para inserir: {cont_geral}")
    return  dbOCR['AtomicLog'].find({"DataCriacao": {"$gt": ultima_data_importada} })

def documentos_atualizar():
    global cont_geral

    data_limite = datetime.now() - timedelta(days=30)
    cont_geral = dbDocumentManagement['AnexoDetalhes'].count_documents({"DataCriacao": {"$gte": data_limite} })
    print(f"\n\n🚀 Quantidade de itens para atualizar: {cont_geral}")
    documentos = list(dbDocumentManagement['AnexoDetalhes'].find({"DataCriacao": {"$gte": data_limite} }) )
    random.shuffle(documentos)
    return documentos

def obter_reclassificacao(doc):
    reclassificacao = "Talvez"
    if doc is not None:
        if "NOK" in doc:
            reclassificacao = "Sim"
        else:
            if "OK" in doc:
                reclassificacao = "Não"
    return reclassificacao

def consultar_aviso(doc):
    aviso = dbSinistro['AvisoSinistro'].find_one({'Protocolo': doc['protocolo']})
    if aviso:
        return {
            "sinistros": aviso.get('Sinistros', []),
            "produtos": [produto['Codigo'] for produto in aviso.get('Produtos', [])],
            "coberturas": [cobertura for cobertura in aviso.get('Coberturas', [])],
            "origem": aviso.get('InformacoesComplementares', {}).get('origemdocumento', None)
        }
    else:
        return None

def detalhes_documento(documento):
    return {
        "nome_arquivo": documento['NomeArquivo'],
        "tipificacao_id": documento['TipificacaoId'],
        "data_criacao": documento['DataCriacao'],
        "protocolo": documento['NomeArquivo'].split('_')[0].lower(),
        "tipos_arquivo": obter_tipos_arquivo(documento)
    }

def obter_tipos_arquivo(documento):
    tipos_arquivos = []
    if 'Resposta' in documento and 'Arquivos' in documento['Resposta'] and documento['Resposta']['Arquivos']:
        for arquivo in documento['Resposta']['Arquivos']:
            if len(arquivo['TipoArquivo']) == 0:
                tipos_arquivos.append("Outros")
            for tipo in arquivo['TipoArquivo']:
                tipos_arquivos.append(tipo['NomeTipoArquivo'])
    return tipos_arquivos

def retornar_anexo_dm(nome_arquivo):
    anexo = dbDocumentManagement['Anexo'].find_one({"Anexo.Nome": nome_arquivo})
    if anexo:
        return {
            "IdAnexo": anexo['IdAnexo'],
            "IdProcesso": anexo['IdProcesso']
        }
    else:
        return None

def consultar_observacao_ebox(anexo):
    idProcesso = anexo['IdProcesso']
    global cache
    tipoDocumentoId = 0
    tipoDocumentoCodigoReferenciaCliente = ""
    tipoDocumento = ""
    if idProcesso in cache:
        print(f"{mostrar_loader()} 🔑 Resultado obtido do cache para IdProcesso: {idProcesso}")
        for doc in cache[idProcesso]:
            if str(doc['documentoId']) == anexo['IdAnexo']:
                tipoDocumentoId = doc['tipoDocumentoId']
                tipoDocumentoCodigoReferenciaCliente = doc['tipoDocumentoCodigoReferenciaCliente']
                tipoDocumento = doc['tipoDocumento']
                if 'classificacao' in doc['dadosDinamicos'] and doc['dadosDinamicos']['classificacao'] != '':
                    obs = doc['dadosDinamicos']['classificacao']
                else:
                    obs = doc['observacoes']
                break
        return  {
                "obs": obs,
                "tipoDocumentoId": tipoDocumentoId,
                "tipoDocumentoCodigoReferenciaCliente": tipoDocumentoCodigoReferenciaCliente,
                "tipoDocumento": tipoDocumento
            }

    response = session.get(f'https://api.eboxdigital.com.br/v1/registros/{idProcesso}/documentos')
    obs = None
    if response.status_code == 200:
        documentos_response = response.json()
        cache[idProcesso] = documentos_response
        for doc in documentos_response:
            if str(doc['documentoId']) == anexo['IdAnexo']:
                tipoDocumentoId = doc['tipoDocumentoId']
                tipoDocumentoCodigoReferenciaCliente = doc['tipoDocumentoCodigoReferenciaCliente']
                tipoDocumento = doc['tipoDocumento']
                if 'classificacao' in doc['dadosDinamicos'] and doc['dadosDinamicos']['classificacao'] != '':
                    obs = doc['dadosDinamicos']['classificacao']
                else:
                    obs = doc['observacoes']
                break
    return {
                "obs": obs,
                "tipoDocumentoId": tipoDocumentoId,
                "tipoDocumentoCodigoReferenciaCliente": tipoDocumentoCodigoReferenciaCliente,
                "tipoDocumento": tipoDocumento
            }

def gerar_id_aleatorio(tamanho=24):
    return ''.join(random.choices(string.hexdigits, k=tamanho)).lower()

def inserir_anexo_detalhes(aviso, anexo, doc, detalhes_ebox):
    anexo_detalhes =  {
                "_id": gerar_id_aleatorio(),
                "NomeArquivo": doc['nome_arquivo'],
                "IdProcesso": anexo["IdProcesso"] if anexo is not None else "0",
                "IdAnexo": anexo["IdAnexo"] if anexo is not None else "0",
                "DataCriacao": doc['data_criacao'],
                "TiposArquivo": doc['tipos_arquivo'],
                "TipificacaoId": int(doc['tipificacao_id']),
                "Obs": detalhes_ebox['obs'],
                "Reclassificacao": obter_reclassificacao(detalhes_ebox['obs']),
                "Protocolo": doc['protocolo'],
                "Sinistros": aviso['sinistros'],
                "Produtos": aviso['produtos'],
                "Coberturas": aviso['coberturas'],
                "Origem": aviso['origem'],
                "DataAtualizacao": datetime.now(),
                 "Ebox":
                    {
                        "tipoDocumento": detalhes_ebox['tipoDocumento'],
                        "tipoDocumentoCodigoReferenciaCliente": detalhes_ebox['tipoDocumentoCodigoReferenciaCliente'],
                        "tipoDocumentoId": detalhes_ebox['tipoDocumentoId']
                    },
            }
    dbDocumentManagement['AnexoDetalhes'].insert_one(anexo_detalhes)

def atualizar_anexo_detalhes(documento, detalhes_ebox):
    resultado = dbDocumentManagement['AnexoDetalhes'].update_one(
        {"_id": str(documento['_id'])},
        {
            "$set": {
                "Obs": detalhes_ebox['obs'],
                "Reclassificacao": obter_reclassificacao(detalhes_ebox['obs']),
                "Ebox":
                    {
                        "tipoDocumento": detalhes_ebox['tipoDocumento'],
                        "tipoDocumentoCodigoReferenciaCliente": detalhes_ebox['tipoDocumentoCodigoReferenciaCliente'],
                        "tipoDocumentoId": detalhes_ebox['tipoDocumentoId']
                    },
                "IdAnexo": documento['IdAnexo'],
                "IdProcesso": documento['IdProcesso'],
                "DataAtualizacao": datetime.now()
            }
        }
    )
    return resultado.modified_count

def nao_existe_anexo_detalhes(doc):
    return dbDocumentManagement['AnexoDetalhes'].count_documents({"NomeArquivo": doc['nome_arquivo']}) == 0

def mostrar_loader():
    total_width=20
    percentual =  cont/cont_geral * 100
    filled_length = int(total_width * percentual // 100)
    bar = '#' * filled_length + '-' * (total_width - filled_length)
    for i in range(10):
        return f"\n\n[{bar}] {percentual:.2f}% |"

def processar_novos_documento(documento):
    global cont
    cont += 1
    doc = detalhes_documento(documento)

    if nao_existe_anexo_detalhes(doc):

        aviso = consultar_aviso(doc)

        anexo = retornar_anexo_dm(doc['nome_arquivo'])

        if anexo:
            detalhes_ebox = consultar_observacao_ebox(anexo)
            inserir_anexo_detalhes(aviso, anexo, doc, detalhes_ebox)
        else:
            inserir_anexo_detalhes(aviso, None, doc, None)
        print(f"{mostrar_loader()} 💾 Arquivo {documento['TipificacaoId']} sincronizado com sucesso!")
    else:
        print(f"{mostrar_loader()} 🔍 Arquivo {documento['TipificacaoId']} já sicronizado!")

def processar_atualizacao_documento(documento):
    global cont
    cont += 1
    atualizar = False
    if ('IdProcesso' in documento and documento['IdProcesso'] == "0") or ('IdProcesso' not in documento):
        anexo = retornar_anexo_dm(documento['NomeArquivo'])
        if anexo:
            atualizar = True
            documento['IdAnexo'] = anexo['IdAnexo']
            documento['IdProcesso'] = anexo['IdProcesso']

    if 'IdProcesso' in documento and documento['IdProcesso'] != "0":
        detalhes_ebox = consultar_observacao_ebox(documento)
        if 'Obs' not in documento or documento['Obs'] != detalhes_ebox['obs']:
            atualizar = True

        if atualizar:
            atualizar_anexo_detalhes(documento, detalhes_ebox)
            print(f"{mostrar_loader()} 💾 - Arquivo {documento['TipificacaoId']} atualizado com sucesso!")
        else:
            print(f"{mostrar_loader()} 🔍 - Arquivo {documento['TipificacaoId']} sem atualizações!")

atualizar = documentos_atualizar()
with ThreadPoolExecutor(max_workers=20) as executor:
    executor.map(processar_atualizacao_documento, atualizar)
    print("✅ Documentos atualizados com sucesso!")

inserir = documentos_novos()
with ThreadPoolExecutor(max_workers=20) as executor:
    executor.map(processar_novos_documento, inserir)
    print("✅ Documentos inseridos com sucesso!")
