QUERY = """
      
                
IF OBJECT_ID('tempdb..#contracts') IS NOT NULL DROP TABLE #contracts                  
IF OBJECT_ID('tempdb..#contracts_coverages') IS NOT NULL DROP TABLE #contracts_coverages                                
IF OBJECT_ID('tempdb..#phones') IS NOT NULL DROP TABLE #phones                  
IF OBJECT_ID('tempdb..#broker_phones') IS NOT NULL DROP TABLE #broker_phones                  
IF OBJECT_ID('tempdb..#accounts') IS NOT NULL DROP TABLE #accounts                 
                
SELECT                  
DISTINCT                                
csin.nr_sinistro as contract,                                       
(CONVERT(DATE, csin.dt_ocorrencia)) AS occurrenceDate,                  
(CONVERT(DATE, csin.dt_comunicado)) AS communicationDate,                        
(CONVERT(DATE, csin.dt_sistema)) AS sendDate,                  
id_endosso as endorsementId,                  
csin.nr_item as itemNumber,                    
IIF(csin.cd_status IN ('448', '471', '473', '474', '469'), 'Desocupado',                      
IIF(csin.cd_status IN ('466', '467'), 'Ocupado', 'Outros')) as propertySituation,                  
csin.cd_status as status_code,          
cs.nm_status as status_name,                  
'' as beneficiaryName,                  
'' as beneficiaryTaxPayerId                  
INTO                 
#contracts                    
FROM                   
i4pro_erp..corp_sinistro csin (NOLOCK)                
inner join i4pro_erp..corp_status cs (NOLOCK) on csin.cd_status = cs.cd_status                  
WHERE                       
csin.id_ramo = 33       
and csin.nr_sinistro in (1004600022744)
                
                  
-- Pessoa Locatario                  
ALTER TABLE            
#contracts                  
ADD                   
tenantId bigint                  
                
update                 
ct                
set                 
tenantId = loc.tenantId                
from                 
#contracts ct                 
inner join (                
SELECT                    
ct.contract,                
MIN(cfl.id_pessoa_locatario) as tenantId                  
FROM                   
#contracts ct                
inner join i4pro_erp..corp_fianca_locatario cfl (NOLOCK) on ct.itemNumber = cfl.id_item and cfl.dv_principal = 1                   
group by                
ct.contract) as loc on ct.contract = loc.contract                
                
                
-- Pessoa Locatario  (caso não tenha inquilino principal)                
update ct                
set                 
tenantId = loc.tenantId                
from                 
#contracts ct                 
inner join (                
SELECT                    
ct.contract,                
MIN(cfl.id_pessoa_locatario) as tenantId                  
FROM                   
#contracts ct                
inner join i4pro_erp..corp_fianca_locatario cfl (NOLOCK) on                 
ct.itemNumber = cfl.id_item and                      
ct.tenantId is null                
group by                
ct.contract) as loc on ct.contract = loc.contract                
                
                
update ct                
set                 
propertySituation = 'Ocupado'                   
from                 
#contracts ct                 
inner join (                
select contract, max(fl.id_folowup) id                
from                
#contracts  ct                
inner join i4pro_erp..corp_sin_folowup fl (nolock) on ct.contract = fl.nr_sinistro                
where                 
propertySituation = 'Outros'                
group by contract) as last_follow on ct.contract = last_follow.contract                
inner join i4pro_erp..corp_sin_folowup fl on last_follow.id = fl.id_folowup                 
where fl.id_tp_followup in (41, 40)                
                
                
update ct                
set                 
propertySituation = 'Desocupado'                   
from                 
#contracts ct                 
inner join (                
select contract, max(fl.id_folowup) id                
from                
#contracts  ct                
inner join i4pro_erp..corp_sin_folowup fl (nolock) on ct.contract = fl.nr_sinistro                
where                 
propertySituation = 'Outros'                
group by contract) as last_follow on ct.contract = last_follow.contract                
inner join i4pro_erp..corp_sin_folowup fl on last_follow.id = fl.id_folowup                 
where fl.id_tp_followup in (45, 46, 43, 53,55)                
                
                  
--DADOS PESSOA (LOCATARIO)                  
ALTER TABLE                   
#contracts                  
ADD                   
document varchar(100),                   
personalInfo_name varchar(255),                   
personalInfo_document varchar(100),                   
personalInfo_birthdate date,                   
personalInfo_gender varchar(30),                   
personalInfo_clientType varchar(30),                  
segmentId int                  
                  
update                   
ct                  
set                 
ct.document =                   
case when len(ploc.nr_cnpj_cpf) > 11                 
then right(replicate('0',14) + convert(varchar(20),ploc.nr_cnpj_cpf),14)                 
else right(replicate('0',11) + convert(varchar(20),ploc.nr_cnpj_cpf),11)                 
end,                  
ct.personalInfo_document =                   
case when len(ploc.nr_cnpj_cpf) > 11                 
then right(replicate('0',14) + convert(varchar(20),ploc.nr_cnpj_cpf),14)                 
else right(replicate('0',11) + convert(varchar(20),ploc.nr_cnpj_cpf),11)                 
end,                  
personalInfo_name = ploc.nm_pessoa,                  
personalInfo_birthdate = ploc.dt_nascimento,                  
personalInfo_gender =                
CASE                   
WHEN ploc.id_sexo = 1 THEN 'Masculino'                   
WHEN ploc.id_sexo = 2 THEN 'Feminino'                   
ELSE NULL                  
END,                  
personalInfo_clientType =                 
CASE                   
WHEN ploc.cd_tipo_pessoa = 1 THEN 'PF'                   
ELSE 'PJ'                   
END,                  
segmentId = ploc.id_ramo_atividade                  
FROM                   
#contracts ct                   
inner join i4pro_erp.cad.t_pessoas ploc (NOLOCK) on ct.tenantId = ploc.id_pessoa        
        
--RAMO ATIVIDADE                  
ALTER TABLE                   
#contracts                  
ADD                   
segment varchar(255)                  
                  
update                   
ct                   
set              
ct.segment = ramo.nm_ramo_atividade                  
from                 
#contracts ct                   
inner join  i4pro_erp..corp_ramo_atividade ramo (NOLOCK) on ct.segmentId = ramo.id_ramo_atividade                  
                  
                   
--ENDERECO                  
ALTER TABLE                   
#contracts                  
ADD                   
personalInfo_address_buildingIdentification varchar(255),                   
personalInfo_address_city varchar(255),                   
personalInfo_address_complement varchar(255),                   
personalInfo_address_neighborhood varchar(255),             
personalInfo_address_state varchar(255),                  
personalInfo_address_street varchar(255),                  
personalInfo_address_zipCode varchar(255)                 
                  
update                   
ct                  
set                  
ct.personalInfo_address_buildingIdentification = ender.nr_rua_endereco,                  
ct.personalInfo_address_city = ender.nm_cidade,                  
ct.personalInfo_address_complement = ender.nm_complemento,                  
ct.personalInfo_address_neighborhood = ender.nm_bairro,                  
ct.personalInfo_address_state = uf.nm_estado,                  
ct.personalInfo_address_street = ender.nm_endereco,                  
ct.personalInfo_address_zipCode = ender.nm_cep                  
FROM                   
#contracts ct                   
inner join i4pro_erp..corp_endereco ender (NOLOCK) on ender.id_pessoa = ct.tenantId and ender.dv_endereco_padrao = 1                  
inner join i4pro_erp..corp_uf uf (nolock) on ender.cd_uf = uf.cd_uf                  
                  
                  
                  
--PHONE                  
ALTER TABLE                   
#contracts                  
ADD                   
personalInfo_phones_areaCode varchar(10),                  
personalInfo_phones_phoneNumber varchar(100)                  
                
select                 
contract, phone.nr_ddd, phone.nm_meio_comunicacao, dv_principal                
into                
#phones                
from                
#contracts ct                   
inner join  i4pro_erp.cad.t_pessoas_meio_comunicacao phone (NOLOCK) on ct.tenantId = phone.id_pessoa                  
WHERE                   
cd_tp_meio_comunicacao  in(1,2,3) and                  
nm_meio_comunicacao IS NOT NULL    AND                      
nm_meio_comunicacao <> '0'     AND         
nr_ddd IS NOT NULL                      
order by  dv_principal desc                
                  
                 
                 
update                   
ct                   
set                  
ct.personalInfo_phones_areaCode = phones.nr_ddd,                  
ct.personalInfo_phones_phoneNumber = phones.nm_meio_comunicacao                  
from                 
#contracts ct                
inner join #phones phones on ct.contract = phones.contract                
                
                  
                
--EMAIL                  
ALTER TABLE                 
#contracts                  
ADD                  
personalInfo_emails varchar(255)                  
                
update                   
ct                   
set                  
ct.personalInfo_emails = email.nm_meio_comunicacao                  
from                 
#contracts ct inner join                   
i4pro_erp.cad.t_pessoas_meio_comunicacao email (NOLOCK) on    ct.tenantId = email.id_pessoa                  
WHERE                
cd_tp_meio_comunicacao  = '4'                   
AND                      
nm_meio_comunicacao NOT LIKE '%teste@%' AND                    
nm_meio_comunicacao NOT LIKE '%testes@%' AND                
nm_meio_comunicacao IS NOT NULL AND                            
nm_meio_comunicacao LIKE '%@%.%'                   
                       
                 
--VALOR AVISO                  
SELECT                          
ct.contract,            
cpc.id_cobertura as  coverage_code,
cpc.nm_comercial as coverage,                      
SUM(vl_operacao)  AS coverage_value                     
into                  
#contracts_coverages                  
FROM                 
#contracts ct                   
inner join i4pro_erp..corp_sin_movto mvto (NOLOCK) on ct.contract = mvto.nr_sinistro                  
inner join i4pro_erp..corp_produto_cobertura cpc (NOLOCK) on mvto.id_produto_cobertura = cpc.id_produto_cobertura                  
WHERE                       
cd_evento IN ('10101')                      
GROUP BY                 
ct.contract,cpc.id_cobertura, cpc.nm_comercial                  
                               
                  
ALTER TABLE                   
#contracts                  
ADD                   
curveValue decimal(10,2),                  
lateInstallmentsValue decimal(10,2),                  
installments_curveValue decimal(10,2),                  
installments_principalValue decimal(10,2),                  
totalValue decimal(10,2),                
principalValue decimal(10,2)                  
                  
update                   
ct                  
set                  
ct.curveValue = ccc.curveValue,                  
ct.lateInstallmentsValue = ccc.curveValue,                  
ct.installments_curveValue = ccc.curveValue,                  
installments_principalValue = ccc.curveValue,                  
totalValue = ccc.curveValue,                  
principalValue= ccc.curveValue                  
from                  
#contracts ct                  
inner join      
(SELECT                   
ct.contract,                  
sum(coverage_value) as curveValue                  
FROM                   
#contracts ct                  
inner join #contracts_coverages cc  on ct.contract = cc.contract                  
group by                  
ct.contract) as ccc on ct.contract = ccc.contract                  
                  
                  
--APOLICE                  
ALTER TABLE                   
#contracts                  
ADD                    
policyNumber varchar(100),                  
startInsuranceDate date,                  
endInsuranceDate date,                  
insured_id bigint                  
                  
update                   
ct                  
set                  
ct.policyNumber = ca.cd_apolice,                  
ct.startInsuranceDate = ce.dt_inicio_vigencia,                  
ct.endInsuranceDate = ce.dt_fim_vigencia,                  
ct.insured_id = ca.id_pessoa_cliente                  
from                  
#contracts ct                  
inner join i4pro_erp..corp_endosso ce (nolock) on ct.endorsementId = ce.id_endosso                
inner join i4pro_erp..corp_sub_estipulante cse (nolock) on cse.id_sub = ce.id_sub                  
inner join i4pro_erp..corp_apolice ca (nolock) on ca.id_apolice = cse.id_apolice                  
                    
                  
                    
--DADOS PESSOA (SEGURADO)                  
ALTER TABLE                 
#contracts                  
ADD                   
insured_document varchar(100),                   
insured_name varchar(255)                   
                  
update                   
ct                  
set                  
ct.insured_document = ploc.nr_cnpj_cpf,                  
ct.insured_name = ploc.nm_pessoa                  
FROM                   
#contracts ct                   
inner join i4pro_erp.cad.t_pessoas ploc (NOLOCK) on ct.insured_id = ploc.id_pessoa                  
                  
                   
--DADOS PESSOA (IMOBILIARIA)                  
ALTER TABLE                   
#contracts                  
ADD                   
realEstate_document varchar(100),                   
realEstate_name varchar(255)                   
                  
update                   
ct                  
set                  
ct.realEstate_document = ploc.nr_cnpj_cpf,                  
ct.realEstate_name = ploc.nm_pessoa                  
FROM                   
#contracts ct                   
inner join i4pro_erp..corp_fianca_itens cfi (nolock) on cfi.id_endosso = ct.endorsementId                  
inner join i4pro_erp.cad.t_pessoas ploc (NOLOCK) on cfi.id_pessoa_imobiliaria = ploc.id_pessoa                  
                   
                  
                   
--DADOS PESSOA (CORRETOR)                  
ALTER TABLE                   
#contracts                  
ADD                   
broker_document varchar(100),                 
broker_name varchar(255),                   
broker_id varchar(255),                   
broker_phone varchar(255),                   
broker_email varchar(255)                  
   
update                   
ct                  
set                  
ct.broker_document = ploc.nr_cnpj_cpf,       
ct.broker_name = ploc.nm_pessoa,                  
ct.broker_id = cfi.id_pessoa_corretor                  
FROM                   
#contracts ct                   
inner join i4pro_erp..corp_sub_corretor cfi (nolock) on cfi.id_endosso = ct.endorsementId                  
inner join i4pro_erp.cad.t_pessoas ploc (NOLOCK) on cfi.id_pessoa_corretor = ploc.id_pessoa                    
                
                  
select                 
contract, phone.nr_ddd, phone.nm_meio_comunicacao, dv_principal                
into                
#broker_phones                
from                
#contracts ct                   
inner join  i4pro_erp.cad.t_pessoas_meio_comunicacao phone (NOLOCK) on ct.broker_id = phone.id_pessoa                  
WHERE                   
cd_tp_meio_comunicacao  in(1,2,3) and                 nm_meio_comunicacao IS NOT NULL AND                          
nm_meio_comunicacao <> '0'     AND                       
nr_ddd IS NOT NULL                      
order by  dv_principal desc                
                  
update                   
ct                   
set                  
ct.broker_phone = phone.nr_ddd + phone.nm_meio_comunicacao                  
from                 
#contracts ct                   
inner join  #broker_phones phone (NOLOCK) on ct.contract = phone.contract                     
                  
                   
update                   
ct                   
set                  
ct.broker_email = email.nm_meio_comunicacao                  
from                 
#contracts ct inner join                   
i4pro_erp.cad.t_pessoas_meio_comunicacao email (NOLOCK) on  ct.broker_id = email.id_pessoa                  
WHERE                   
cd_tp_meio_comunicacao  = '4'AND                      
nm_meio_comunicacao NOT LIKE '%teste@%' AND                 
nm_meio_comunicacao NOT LIKE '%@tooseguros.com%'      
 

select distinct 
ct.contract
, pess.nr_cnpj_cpf as account_document
, pess.nm_pessoa as account_name 
, mvto.nr_banco as account_bank
, mvto.nr_agencia as account_agency
, mvto.nr_conta_corrente as account_number
into
#accounts
from 
#contracts ct
inner join i4pro_erp..corp_sin_movto mvto on ct.contract = mvto.nr_sinistro
inner join i4pro_erp..corp_pessoas  pess on mvto.id_pessoa_favorecido = pess.id_pessoa	
where 
mvto.id_pessoa_favorecido is not null
and mvto.cd_evento = 11001
         
select ct.*, cc.coverage_code, cc.coverage, cc.coverage_value, acc.account_document, acc.account_name, acc.account_bank, acc.account_agency, acc.account_number 
from                 
#contracts ct
inner join #contracts_coverages cc on ct.contract = cc.contract
left join #accounts acc on ct.contract = acc.contract
     

"""
