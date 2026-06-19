import pandas as pd
import requests
from datetime import datetime
import json
import time

arquivo_excel = 'base1.xlsx'
df = pd.read_excel(arquivo_excel)
session = requests.Session()

urlMotor = 'https://sinistro-node-red-prod-interno.tooseguros.com.br/api/sinistro/cancelamento-automatico'
headers = {
    'Content-Type': 'application/json',
}

def pascal_to_camel(pascal_case_str):
    if not pascal_case_str:
        return pascal_case_str  
    return pascal_case_str[0].lower() + pascal_case_str[1:]

def convert_keys_to_camel_case(data):
    if isinstance(data, dict):
        return {pascal_to_camel(key): convert_keys_to_camel_case(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [convert_keys_to_camel_case(item) for item in data]
    else:
        return data

with open('result.txt', 'w', encoding='utf-8', newline='') as arquivo:
    for index, row in df.iterrows():
        cpf = row['CPF']
        data_ocorrencia = row['Data Obito']
        saldo_devedor = row['SALDO DEVEDOR']
        nome = row['nmtitular']
        print(f"{index}/{len(df)} - CPF {cpf}")        
        
        url = f"http://toovasd09/i4pro_dev1/erpws/run/ConsultaDadosApolice/dadosApolice?numCnpjCpfSegurado={cpf}"
        
        start_time = time.time()  
        response = session.get(url)
        end_time = time.time()  
        elapsed_time = end_time - start_time
        print(f"- chamada i4pro: {elapsed_time:.2f} segundos")
        
        polices = []        
        with open('request_motor.json', 'r', encoding='utf-8') as json_motor:
            motor = json.load(json_motor)
       

        with open('produtos.json', 'r', encoding='utf-8') as produtos:
            produtos = json.load(produtos)
        produtos = convert_keys_to_camel_case(produtos)
        
        motor['avisoSinistro']['dataOcorrencia'] = pd.Timestamp(data_ocorrencia).strftime('%Y-%m-%d')
        motor['avisoSinistro']['segurado']['cpfCnpj'] = cpf
        motor['avisoSinistro']['segurado']['nome'] = nome

        if response.status_code == 200:
            dados = response.json()  
                
            
            for apolice in dados.get('dadosApolice', []):       
                
                codigoProduto = apolice.get('codigoProduto')
                numeroApolice = apolice.get('numeroApolice')
                numeroBilhete = apolice.get('numeroBilhete')
                nomeProduto = apolice.get('nomeProduto')
                dadosEndosso = apolice.get('endosso').get('dadosEndosso',[])               
                dataInicioVigencia = datetime.strptime(apolice.get('dt_inicio_vigencia_item'), '%Y-%m-%dT%H:%M:%S')
                dataFimVigencia = datetime.strptime(apolice.get('dt_fim_vigencia_item'), '%Y-%m-%dT%H:%M:%S')

                if dataInicioVigencia <= data_ocorrencia <= dataFimVigencia:
                    vigencia= 'sim'
                else:    
                    vigencia= 'não'
                cobertura_contratada = 'não'  
                valor_is = 0
                is_excedida = ''                

                for endosso in dadosEndosso:   
                    dataInicioVigencia = datetime.strptime(endosso.get('dataInicioVigencia'), '%Y-%m-%dT%H:%M:%S')
                    dataFimVigencia = datetime.strptime(endosso.get('dataFimVigencia'), '%Y-%m-%dT%H:%M:%S')
                    if dataInicioVigencia <= data_ocorrencia <= dataFimVigencia:
                        vigencia= 'sim'
                    else:    
                        vigencia= 'não'

                    for dadosItem in endosso.get('item').get('dadosItem'):
                        for dadosCobertura in dadosItem.get('cobertura').get('dadosCobertura'):
                            valor_is = dadosCobertura.get('valorIS')
                            if valor_is < saldo_devedor:
                                is_excedida = 'sim'
                            else:
                                is_excedida = 'não'                                   

                            for gruposCobertura in dadosCobertura.get('grupo').get('gruposCobertura'):
                                if gruposCobertura.get('idGrupoCobertura') == 5:
                                    cobertura_contratada = 'sim'                                          
                                    break       
                            if cobertura_contratada == 'sim':
                                break
                        if cobertura_contratada == 'sim':
                            break
                    

                if len(polices) > 0:
                    for index, police in enumerate(polices):
                        encontrado = 0
                        if police['numeroApolice'] == numeroApolice: 
                            encontrado = 1    
                            break

                    if encontrado == 1:
                        if vigencia == 'sim':
                            polices[index]['valor_is'] = valor_is            
                            polices[index]['is_excedida'] = is_excedida              
                            polices[index]['vigencia'] = vigencia              
                            polices[index]['cobertura_contratada'] = cobertura_contratada 
                            for index, original in enumerate(motor['apolices']):  
                                if original['numeroApolice'] == numeroApolice:
                                    del motor['apolices'][index]  
                                    if len(dadosEndosso) > 0:
                                        for produto in produtos:
                                            if produto['codigo'] == codigoProduto:
                                                motor['produtoElegivelAutomacoes'].append(produto) 
                                        motor['apolices'].append(apolice) 
                                        

                    else:
                        if len(dadosEndosso) > 0:
                            for produto in produtos:
                                if produto['codigo'] == codigoProduto:
                                    motor['produtoElegivelAutomacoes'].append(produto) 
                            motor['apolices'].append(apolice)                            
                        polices.insert(1, {'cpf': cpf,'numeroApolice': numeroApolice,'numeroBilhete': numeroBilhete,'codigoProduto': codigoProduto,'nomeProduto': nomeProduto,'dataInicioVigencia': dataInicioVigencia,'dataFimVigencia': dataFimVigencia,'vigencia': vigencia,'cobertura_contratada': cobertura_contratada,'valor_is': valor_is,'is_excedida': is_excedida}) 

                else:
                    if len(dadosEndosso) > 0:
                        for produto in produtos:
                            if produto['codigo'] == codigoProduto:
                                motor['produtoElegivelAutomacoes'].append(produto) 
                        motor['apolices'].append(apolice)
                    polices.insert(1, {'cpf': cpf,'numeroApolice': numeroApolice,'numeroBilhete': numeroBilhete,'codigoProduto': codigoProduto,'nomeProduto': nomeProduto,'dataInicioVigencia': dataInicioVigencia,'dataFimVigencia': dataFimVigencia,'vigencia': vigencia,'cobertura_contratada': cobertura_contratada,'valor_is': valor_is,'is_excedida': is_excedida}) 

     

            try: 
                start_time = time.time()  
                response = requests.post(urlMotor, headers=headers, json=motor)            
                end_time = time.time()  
                elapsed_time = end_time - start_time
                print(f"- chamada motor: {elapsed_time:.2f} segundos")

                if response.status_code == 200:
                    for apolice in response.json().get('Apolices'):
                        for index, police in enumerate(polices):
                            if apolice.get('NumeroApolice') == police['numeroApolice']:
                                polices[index]['EnviarParaRegulacaoAutomatica'] = apolice.get('EnviarParaRegulacaoAutomatica')      
                                polices[index]['MotivoRecusa'] = apolice.get('MotivoRecusa')   
            
            except requests.exceptions.RequestException as e:
                print(f"Ocorreu um erro: {e}")

            for police in polices:
                arquivo.write(f"{police.get('cpf')};{police.get('numeroApolice')};{police.get('numeroBilhete')};{police.get('codigoProduto')};{police.get('nomeProduto')};{police.get('dataInicioVigencia')};{police.get('dataFimVigencia')};{police.get('vigencia')};{police.get('cobertura_contratada')};{police.get('valor_is')};{police.get('is_excedida')};{police.get('EnviarParaRegulacaoAutomatica')};{police.get('MotivoRecusa')}\n")                         
                
            del polices[:]
                                    
                
        else:
            print(f"Falha ao consultar dados para CPF {cpf}. Status code: {response.status_code}")

print(f"acabou!")
