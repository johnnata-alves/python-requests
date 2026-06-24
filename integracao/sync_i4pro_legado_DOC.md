# Sincronização de Sinistros Legado (I4Pro → ClaimEngine)

`sync_i4pro_legado.py`

## 1. Visão Geral

Script de carga em massa que migra sinistros do sistema legado **I4Pro (SQL Server)** para a plataforma **ClaimEngine (MongoDB)**. Para cada sinistro, gera os documentos legados nas coleções `LegacyClaim`, `LegacyDocument` e `LegacyAttachment`, enriquecendo os dados com informações do **AvisoSinistro** (MongoDB `SinistrosMicroService`).

O objetivo é disponibilizar o histórico de sinistros do legado dentro da nova plataforma, com status fixo **"Importado"**, sem reprocessar regras de negócio do fluxo atual.

## 2. Contexto de Negócio

- Sinistros antigos vivem no I4Pro e não estão visíveis na nova plataforma.
- A migração cria registros "legado" que permitem consulta histórica no ClaimEngine.
- Dados de segurado, reclamante, protocolo e anexos vêm do **AvisoSinistro** quando existe; quando não existe, o sinistro é importado mesmo assim, com esses campos vazios.
- O status é sempre **"Importado"** — o script não interpreta nem altera o ciclo de vida do sinistro.

## 3. Fontes e Destinos

### Origem
| Fonte | Sistema | Uso |
|-------|---------|-----|
| `corp_sinistro` + joins | I4Pro (SQL Server) | Dados do sinistro, segurado, reclamante, coberturas |
| `corp_sin_documento` | I4Pro (SQL Server) | Documentos do sinistro |
| `AvisoSinistro` | MongoDB `SinistrosMicroService` | Protocolo, segurado, reclamante, origem do documento |
| `AvisoSinistroAnexo` | MongoDB `SinistrosMicroService` | Anexos por protocolo |

### Destino (MongoDB `ClaimEngine`)
| Coleção | Conteúdo |
|---------|----------|
| `LegacyClaim` | Documento principal do sinistro importado |
| `LegacyDocument` | Documentos do sinistro |
| `LegacyAttachment` | Anexos vinculados ao protocolo |

### Coleções de apoio (somente leitura)
- `Coverage` — mapeamento de cobertura
- `Relationship` — mapeamento de relacionamento do reclamante
- `DocumentTypeMappings` — nome do tipo de documento por código ERP

## 4. Pré-requisitos

- Python 3.10+
- Pacotes: `pyodbc`, `pymongo`, `python-dotenv`
- Driver: **ODBC Driver 17 for SQL Server**
- Acesso de rede ao SQL Server do I4Pro e aos clusters MongoDB (VPN se necessário)
- Arquivo `.env` na raiz do projeto com as variáveis abaixo

## 5. Variáveis de Ambiente (.env)

O script lê as conexões via `os.getenv`. **Por padrão está apontando para HML.** Para rodar em produção, troque pelas variáveis de PRD.

### Configuração atual (HML)
```python
SQL_CONNECTION       = os.getenv("SQL_CONNECTION_I4PRO_HML")
MONGO_CONNECTION     = os.getenv("HML_MONGO_URI")
MONGO_AVISO_CONNECTION = os.getenv("HML_MONGO_URI")
```

### Configuração para PRODUÇÃO
Editar o topo do script para usar as variáveis de PRD:
```python
SQL_CONNECTION       = os.getenv("SQL_CONNECTION_I4PRO_PRD")
MONGO_CONNECTION     = os.getenv("PRD_MONGO_CLAIM_ENGINE")
MONGO_AVISO_CONNECTION = os.getenv("PRD_MONGO_SA_EAST")
```

### Variáveis necessárias no `.env`
| Variável | Ambiente | Descrição |
|----------|----------|-----------|
| `SQL_CONNECTION_I4PRO_HML` | HML | String de conexão ODBC do I4Pro HML |
| `HML_MONGO_URI` | HML | URI do MongoDB HML (ClaimEngine e SinistrosMicroService) |
| `SQL_CONNECTION_I4PRO_PRD` | PRD | String de conexão ODBC do I4Pro PRD |
| `PRD_MONGO_CLAIM_ENGINE` | PRD | URI do MongoDB PRD do ClaimEngine |
| `PRD_MONGO_SA_EAST` | PRD | URI do MongoDB PRD do SinistrosMicroService (AvisoSinistro) |

> **Importante:** o `.env` contém credenciais e **não deve ser versionado**. Já está no `.gitignore`.

### Parâmetros opcionais de performance
| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `WORKERS` | `16` | Número de threads paralelas |
| `SQL_BATCH` | `500` | Quantidade de sinistros por lote de query SQL |

## 6. Janela de Corte (Filtro de Importação)

O conjunto de sinistros a importar é definido por:

```python
WHERE_FILTRO = "csin.id_ramo not in (33) and csin.dt_sistema > '2025-01-01'"
```

- `csin.dt_sistema > '2025-01-01'` → **tempo de corte**: importa apenas sinistros criados após esta data. Ajustar conforme a necessidade da carga.
- `csin.id_ramo not in (33)` → exclui o ramo 33 da importação.

Esse filtro é aplicado tanto na listagem de sinistros quanto serve de base para o volume total processado.

## 7. Como Executar

Na raiz do projeto:

```cmd
python integracao\sync_i4pro_legado.py
```

Com ajuste de lote e paralelismo:

```cmd
set SQL_BATCH=500 & set WORKERS=16 & python integracao\sync_i4pro_legado.py
```

## 8. Fluxo de Execução (Técnico)

1. **Lista de sinistros** — query única (`SINISTRO_LIST_QUERY`) aplica o `WHERE_FILTRO` e retorna todos os `nr_sinistro` candidatos.
2. **Mapas de apoio** — carrega `Coverage`, `Relationship` e `DocumentTypeMappings` inteiros em memória (dicionários), evitando consultas repetidas.
3. **Pré-carga de existentes** — `distinct("claimNumber")` em `LegacyClaim` e `Claim`. Sinistros já presentes são descartados antes do processamento (idempotência).
4. **Divisão em lotes** — os sinistros pendentes são divididos em lotes de `SQL_BATCH`.
5. **Processamento paralelo** (`ThreadPoolExecutor`, `WORKERS` threads), por lote:
   - `DETAIL_QUERY` e `DOC_QUERY` rodam com cláusula `IN (...)` apenas dos sinistros do lote (conexão SQL por thread).
   - `AvisoSinistro` e `AvisoSinistroAnexo` são buscados em lote via `$in`.
   - Monta os documentos e insere em massa com `insert_many` (`ordered=False`) em `LegacyClaim`, `LegacyDocument`, `LegacyAttachment`.
6. **Relatório final** — totais de sincronizados, sem detalhes, já existentes, erros e duração.

## 9. Regras de Negócio Aplicadas

- **Status fixo**: `status = "Importado"` em todas as `LegacyClaim`.
- **Sem AvisoSinistro**: importa mesmo assim; segurado e reclamante ficam vazios.
- **Protocolo**: quando o AvisoSinistro não tem protocolo (ou não existe), é gerado no formato `SIN-{claimNumber}` na `LegacyClaim` e nas `LegacyDocument`.
- **Idempotência**: sinistro já existente em `Claim` ou `LegacyClaim` é pulado.
- **Origem**: `notificationOrigin` e `updatedOrigin` recebem o `origemdocumento` do AvisoSinistro.
- **Coberturas**: deduplicadas por (cobertura, grupo, ramo).
- **Relacionamento**: `OTHER` quando não há `IdRelacao` ou mapeamento.
- **CPF**: normalizado para 11 dígitos com zeros à esquerda.
- **Datas**: convertidas de `dd/mm/yyyy` (SQL) para `datetime`.

## 10. Performance

Otimizações aplicadas para volume de ~110 mil registros:
- Queries SQL em lote (`IN`) em vez de uma por sinistro.
- Busca Mongo em lote (`$in`) para AvisoSinistro e Anexos.
- Mapas de apoio carregados uma única vez.
- Inserts em massa (`insert_many`).
- Processamento paralelo por lotes.

### Índices recomendados (criar antes da carga)
**ClaimEngine**
```js
db.LegacyClaim.createIndex({ claimNumber: 1 })
db.Claim.createIndex({ claimNumber: 1 })
db.Coverage.createIndex({ groupCoverageCodes: 1 })
db.Coverage.createIndex({ coverageCodes: 1 })
db.Relationship.createIndex({ RelationshipCode: 1 })
db.DocumentTypeMappings.createIndex({ ERPDocumentId: 1 })
```
**SinistrosMicroService**
```js
db.AvisoSinistro.createIndex({ Sinistros: 1 })
db.AvisoSinistroAnexo.createIndex({ Protocolo: 1 })
```

## 11. Relatório de Saída

Ao final imprime:
- Total de sinistros encontrados
- Sincronizados
- Sem detalhes / pulados (sem retorno no SQL de detalhe)
- Já existentes (descartados)
- Erros
- Duração total (segundos)

## 12. Observações e Cuidados

- Confirmar o ambiente (HML x PRD) **antes** de executar — a configuração padrão é HML.
- Ajustar a data de corte em `WHERE_FILTRO` conforme o escopo da carga.
- `WORKERS` alto pode esgotar o limite de conexões do SQL Server; calibrar.
- A carga é **aditiva**: não atualiza nem remove registros existentes, apenas insere os ausentes.
- Recomenda-se rodar primeiro em HML para validar volume e amostras antes de PRD.

## 13. Job Complementar: Atualização de Protocolo

`atualizar_protocolo_legacy.py`

Corrige registros legados que ficaram **sem protocolo** (importados antes da regra de fallback, ou sem AvisoSinistro).

### O que faz
- Percorre todas as `LegacyClaim` sem protocolo (campo inexistente, `null` ou vazio).
- Define `protocol = "SIN-{claimNumber}"` na `LegacyClaim`.
- Atualiza o mesmo `protocol` em todas as `LegacyDocument` do mesmo `claimNumber`.

### Características técnicas
- Operações em massa (`UpdateOne` / `UpdateMany`) em lotes de `BATCH_SIZE` (padrão 1000).
- Aponta para HML por padrão (`HML_MONGO_URI`). Para PRD, trocar por `PRD_MONGO_CLAIM_ENGINE`.

### Variáveis
| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `HML_MONGO_URI` / `PRD_MONGO_CLAIM_ENGINE` | — | URI do MongoDB do ClaimEngine |
| `BATCH_SIZE` | `1000` | Tamanho do lote de atualização |

### Execução
```cmd
python integracao\atualizar_protocolo_legacy.py
```

### Relatório
- Total de `LegacyClaim` sem protocolo
- `LegacyClaim` atualizados
- `LegacyDocument` atualizados
- Duração total
