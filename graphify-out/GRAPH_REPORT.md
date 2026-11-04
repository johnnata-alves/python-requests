# Graph Report - python-requests  (2026-10-05)

## Corpus Check
- 181 files · ~103,797 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 5 file(s) not represented in the graph (top: .checkpoint 2, .example 1, (none) 1)

## Summary
- 1111 nodes · 2559 edges · 68 communities (54 shown, 14 thin omitted)
- Extraction: 98% EXTRACTED · 2% INFERRED · 0% AMBIGUOUS · INFERRED: 51 edges (avg confidence: 0.85)
- Token cost: 60,061 input · 0 output

## Community Hubs (Navigation)
- IA Regulador de Sinistros
- Ajuste de Metadados Mongo
- Importação eBox S3
- Migração Legado I4Pro
- Notificação com Anexos
- Automação e Protocolos
- OCR Document IA
- Sync I4Pro v4
- Migração Garantia Mecânica
- Template Meta e RabbitMQ
- Origem Documento BTG
- Cancelamento BPM e CSV
- GM Meta File
- Anexos Legado Pendentes
- Gerador de Prompt OCR
- Migração PRD→HML
- Conciliador de Tipificação
- Enriquecimento Sinistro CSV
- eBox Import e Tags S3
- Partner Webhook v5
- Received Date Claims
- PanProtege Meta File
- Atualização em Massa
- Vida Individual Meta File
- Migração em Massa
- RCF Meta File
- Categorização e Liquidação
- Vincular Sinistros a Aviso
- Docs Pendentes Excel
- Correção Saldo Automação
- Migração Partner Webhook
- Relatório Attachments IA
- Inserir Aviso por Planilha
- Setup de Produtos
- Received Date Legado
- Saldo Devedor Grafana v2
- Criar Sinistro em Lote
- Template Coletivo Meta
- Ajuste Anexo Óbito
- Saldo Devedor Grafana
- Arrasto de Sinistro
- Protocolo SIN Legado
- Copilot Chat
- Copilot DirectLine Tester
- Copilot Comprovante S3
- Template GM Meta
- Dashboard Previsão Notificações
- Saldo Devedor Planilha
- Copilot Tester v2
- Divergências Gerais
- Relatório Legacy Importado
- Protocolo SIN via API
- Update Document Herdeiros
- Sessão Sinistro Camel
- RCF Sync Base
- Vida Individual Sync Base
- Migrar Claim Score
- Saldo Devedor Mongo
- Dashboard Attachments
- Atualizar OCR
- Relatório Coberturas Produto
- Relatório Sem Template

## God Nodes (most connected - your core abstractions)
1. `log()` - 16 edges
2. `build_payload()` - 16 edges
3. `tempo()` - 15 edges
4. `normalize_text()` - 14 edges
5. `_build_claim_opened_payload()` - 12 edges
6. `process_sinistro()` - 11 edges
7. `normalize_text()` - 10 edges
8. `build_payload()` - 10 edges
9. `normalize_text()` - 10 edges
10. `process_notification()` - 9 edges

## Surprising Connections (you probably didn't know these)
- `Camada de Normalização de CPF e Números Bancários` --semantically_similar_to--> `Normalização de CPF (11 dígitos)`  [INFERRED] [semantically similar]
  ia/analise_attachments_ia.md → integracao/sync_i4pro_legado_DOC.md
- `processar_motor_recusa()` --indirect_call--> `headers()`  [INFERRED]
  ia/regulador_v2.py → integracao/remover_documentos_sinistro.py
- `Document Typification sem DocumentTypeMapping` --conceptually_related_to--> `DocumentTypeMappings (coleção de apoio)`  [INFERRED]
  ia/analise_attachments_ia.md → integracao/sync_i4pro_legado_DOC.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Fluxo de migração legado I4Pro → ClaimEngine** — integracao_sync_i4pro_legado, integracao_sync_i4pro_legado_doc_i4pro, integracao_sync_i4pro_legado_doc_avisosinistro, integracao_sync_i4pro_legado_doc_legacyclaim, integracao_atualizar_protocolo_legacy [EXTRACTED 1.00]
- **Plano de melhoria da validação de attachments IA** — ia_analise_attachments_ia_plano_acao, ia_analise_attachments_ia_mapeamento_additional_required, ia_analise_attachments_ia_normalizacao_cpf_bancario, ia_analise_attachments_ia_business_rules_adaptativo, ia_analise_attachments_ia_limite_paginas_tenant [EXTRACTED 1.00]

## Communities (68 total, 14 thin omitted)

### Community 0 - "IA Regulador de Sinistros"
Cohesion: 0.06
Nodes (46): adicionar_dias_uteis(), agendar_pagamento(), buscar_documentos(), calcular_data_agendamento(), classificar_obito(), consulta_pessoa(), consulta_sinistros(), consultar_apolices() (+38 more)

### Community 2 - "Importação eBox S3"
Cohesion: 0.05
Nodes (13): AdaptiveRateLimiter, buscar_registros(), download_to_s3(), extrair_chave_ebox(), main(), metrics_display_loop(), normalizar_nome_arquivo(), parse_doc_date() (+5 more)

### Community 3 - "Migração Legado I4Pro"
Cohesion: 0.07
Nodes (34): Análise de Attachments IA (Tipificação e Validação), Document Typification sem DocumentTypeMapping, Exames / Relatórios Médicos (4%), Extrato Bancário (pior desempenho, 7%), Falhas de Tipificação de Documento, Falhas de Validação de Metadados, Limite de 20 páginas por tenant, Taxa de Sucesso de Validação (21,4%) (+26 more)

### Community 4 - "Notificação com Anexos"
Cohesion: 0.09
Nodes (24): api_headers(), build_attachment_payload(), build_filtro_indexado(), build_notification_payload(), carregar_checkpoint(), Contexto, create_notification(), criar_sinistro_com_anexos() (+16 more)

### Community 5 - "Automação e Protocolos"
Cohesion: 0.07
Nodes (12): _fix_collection(), _get_protocol_by_claim_number(), main(), extrair_blocos(), verificar_e_atualizar(), extrair_nome_lote(), main(), make_col() (+4 more)

### Community 6 - "OCR Document IA"
Cohesion: 0.10
Nodes (21): CopilotDirectLineClient, generate_variations(), get_row_value(), is_blank(), normalize(), normalize_list(), to_int_if_possible(), build_cache_key() (+13 more)

### Community 7 - "Sync I4Pro v4"
Cohesion: 0.12
Nodes (27): dedupe_dict_list(), format_birthdate(), get_sql_connection(), log_step(), main(), normalize_cpf(), parse_date(), process_sinistro() (+19 more)

### Community 8 - "Migração Garantia Mecânica"
Cohesion: 0.09
Nodes (11): check_file_paths_exists(), execute_proc_lista(), fetch_batch_from_sql(), get_last_processed_apolice(), get_total_count(), init_connections(), main(), print_progress() (+3 more)

### Community 9 - "Template Meta e RabbitMQ"
Cohesion: 0.12
Nodes (15): build_connection(), drain_queue(), main(), parse_args(), build_pending_filter(), load_sql_data(), main(), process_one() (+7 more)

### Community 10 - "Origem Documento BTG"
Cohesion: 0.09
Nodes (10): main(), make_db_notification(), make_db_sinistro(), processar_aviso(), build_payload(), enviar_documentos(), ler_protocolos(), main() (+2 more)

### Community 11 - "Cancelamento BPM e CSV"
Cohesion: 0.13
Nodes (19): converter(), detectar_sep(), main(), abortar_bpm(), consultar_caso(), main(), abortar_bpm(), cancelar_caso() (+11 more)

### Community 12 - "GM Meta File"
Cohesion: 0.25
Nodes (23): append_unique(), build_corretor(), build_payload(), build_pending_filter(), build_sub_estipulante(), build_veiculo(), collect_coberturas(), collect_estipulantes() (+15 more)

### Community 13 - "Anexos Legado Pendentes"
Cohesion: 0.10
Nodes (9): main(), processar_protocolo(), main(), processar_protocolo(), atualizar_protocolo(), main(), get_connections(), main() (+1 more)

### Community 14 - "Gerador de Prompt OCR"
Cohesion: 0.13
Nodes (18): append_unique_metadatas(), build_generation_prompt(), build_match_entry(), build_output_example(), bump_patch_version(), clean_prompt_text(), CopilotDirectLineClient, document_matches_source() (+10 more)

### Community 15 - "Migração PRD→HML"
Cohesion: 0.19
Nodes (22): copiar_s3(), ja_migrado(), main(), migrar_attachments(), migrar_collection(), migrar_documents(), migrar_notification(), migrar_relacionadas() (+14 more)

### Community 16 - "Conciliador de Tipificação"
Cohesion: 0.14
Nodes (13): atualizar_anexo_detalhes(), consultar_aviso(), consultar_observacao_ebox(), detalhes_documento(), gerar_id_aleatorio(), inserir_anexo_detalhes(), mostrar_loader(), nao_existe_anexo_detalhes() (+5 more)

### Community 17 - "Enriquecimento Sinistro CSV"
Cohesion: 0.12
Nodes (3): build_document(), main(), to_int_if_possible()

### Community 18 - "eBox Import e Tags S3"
Cohesion: 0.15
Nodes (10): buscar_registros(), download_to_s3(), extrair_chave_ebox(), main(), normalizar_nome_arquivo(), parse_doc_date(), processar_registro(), s3_file_exists() (+2 more)

### Community 20 - "Partner Webhook v5"
Cohesion: 0.26
Nodes (17): _build_claim_opened_payload(), _build_legacy_document_requested_payload(), consultar_detalhes_sinistro(), _first_present(), main(), _pick_principal(), _resolve_claim_contract_date(), _resolve_claim_coverage_code() (+9 more)

### Community 21 - "Received Date Claims"
Cohesion: 0.12
Nodes (4): load_destino_index(), main(), process_batch(), main()

### Community 22 - "PanProtege Meta File"
Cohesion: 0.31
Nodes (13): build_payload(), build_pending_filter(), collect_coberturas(), collect_estipulantes(), collect_prolaboristas(), decimal_to_json(), first_value(), main() (+5 more)

### Community 23 - "Atualização em Massa"
Cohesion: 0.24
Nodes (16): already_exists(), build_attachment_payload(), build_notification_payload(), create_notification(), download_s3_base64(), format_filename(), get_token(), main() (+8 more)

### Community 24 - "Vida Individual Meta File"
Cohesion: 0.29
Nodes (11): build_payload(), build_pending_filter(), collect_coberturas(), collect_estipulantes(), decimal_to_json(), main(), normalize_text(), parse_date() (+3 more)

### Community 25 - "Migração em Massa"
Cohesion: 0.24
Nodes (16): already_exists(), build_attachment_payload(), build_notification_payload(), create_notification(), download_s3_base64(), format_filename(), get_token(), main() (+8 more)

### Community 26 - "RCF Meta File"
Cohesion: 0.35
Nodes (12): build_payload(), build_pending_filter(), collect_coberturas(), collect_prolaboristas(), decimal_to_json(), main(), normalize_nullable(), normalize_text() (+4 more)

### Community 28 - "Vincular Sinistros a Aviso"
Cohesion: 0.27
Nodes (14): buscar_por_cpf(), carregar_relatorio_existente(), construir_query(), data_sem_hora(), ja_vinculado(), main(), processar_registro(), match_caso_1() (+6 more)

### Community 29 - "Docs Pendentes Excel"
Cohesion: 0.22
Nodes (11): avaliar_aviso(), carregar_protocolos_pendentes(), console_log(), consultar_detalhe_sinistro(), consultar_sinistro_status_alvo(), normalizar_protocolo(), buscar_anexos(), buscar_protocolos() (+3 more)

### Community 30 - "Correção Saldo Automação"
Cohesion: 0.20
Nodes (7): buscar_saldo(), carregar_checkpoint(), main(), processar(), normalizar_contrato(), saldo_vazio(), saldos_diferentes()

### Community 31 - "Migração Partner Webhook"
Cohesion: 0.27
Nodes (12): claim_batch(), detalhes_dict(), extract_id_pagamento(), is_eligible(), main(), map_event(), process_batch(), reader_loop() (+4 more)

### Community 32 - "Relatório Attachments IA"
Cohesion: 0.26
Nodes (7): coletar_dados(), CopilotClient, enviar_para_ia(), gerar_html(), gerar_resumo_estatistico(), main(), markdown_to_html()

### Community 33 - "Inserir Aviso por Planilha"
Cohesion: 0.26
Nodes (9): build_payload(), coverage_morte(), enviar(), find_apolice(), fmt_date(), main(), processar_linha(), to_float() (+1 more)

### Community 34 - "Setup de Produtos"
Cohesion: 0.27
Nodes (7): build_allowed_cause_ids_map(), build_coverage_docs(), build_coverages(), build_product_document(), get_steps_template(), main(), to_int_or_none()

### Community 35 - "Received Date Legado"
Cohesion: 0.24
Nodes (6): coletar_protocolos_sem_received(), main(), run_legacy(), run_nc(), processar_legacy_claim(), processar_notification_claim()

### Community 36 - "Saldo Devedor Grafana v2"
Cohesion: 0.25
Nodes (5): etapa1_baixar_logs(), etapa2_processar(), extrair_contratos_do_log(), main(), query_grafana_hora()

### Community 37 - "Criar Sinistro em Lote"
Cohesion: 0.29
Nodes (7): alterar_sinistro(), build_payload(), buscar_dados_prd(), enviar_erp(), fmt_date(), main(), processar_item()

### Community 38 - "Template Coletivo Meta"
Cohesion: 0.44
Nodes (7): build_pending_filter(), load_sql_data(), main(), process_one(), normalize_key(), parse_dt_emissao(), process_apolice()

### Community 40 - "Saldo Devedor Grafana"
Cohesion: 0.31
Nodes (4): get_grafana_range(), main(), query_grafana(), query_grafana_with_retry()

### Community 42 - "Arrasto de Sinistro"
Cohesion: 0.36
Nodes (6): format_date_br(), format_date_sql(), format_decimal_br(), main(), process_cpf(), query_sql()

### Community 43 - "Protocolo SIN Legado"
Cohesion: 0.36
Nodes (4): carregar_cobertura_config(), main(), match_cobertura(), processar_claim()

### Community 44 - "Copilot Chat"
Cohesion: 0.36
Nodes (4): aguardar_resposta(), criar_conversa(), enviar_mensagem(), main()

### Community 47 - "Template GM Meta"
Cohesion: 0.32
Nodes (6): build_pending_filter(), load_sql_data(), main(), process_one(), normalize_key(), process_apolice()

### Community 48 - "Dashboard Previsão Notificações"
Cohesion: 0.46
Nodes (7): calcular_previsao_por_semana(), coletar_contagem_diaria(), gerar_html(), main(), montar_payload(), montar_serie_diaria(), salvar_artefatos()

### Community 49 - "Saldo Devedor Planilha"
Cohesion: 0.43
Nodes (3): main(), norm(), processar_cpf()

### Community 51 - "Divergências Gerais"
Cohesion: 0.29
Nodes (3): buscar_dados_politica(), create_mongo_connection(), get_pipeline()

### Community 52 - "Relatório Legacy Importado"
Cohesion: 0.38
Nodes (3): buscar_sql_lote(), get_ultimo_anexo_batch(), main()

### Community 53 - "Protocolo SIN via API"
Cohesion: 0.47
Nodes (3): gerar_protocolo(), main(), processar_claim()

### Community 54 - "Update Document Herdeiros"
Cohesion: 0.47
Nodes (3): coverage_has_heirs(), documentation_has_erp_id(), main()

### Community 55 - "Sessão Sinistro Camel"
Cohesion: 0.40
Nodes (3): convert_keys_to_camel_case(), get_session(), pascal_to_camel()

### Community 56 - "RCF Sync Base"
Cohesion: 0.47
Nodes (3): load_destino_index(), main(), process_batch()

### Community 57 - "Vida Individual Sync Base"
Cohesion: 0.47
Nodes (3): load_destino_index(), main(), process_batch()

### Community 58 - "Migrar Claim Score"
Cohesion: 0.47
Nodes (3): adicionar_prefixo_9(), main(), remover_prefixo_9()

### Community 61 - "Dashboard Attachments"
Cohesion: 0.70
Nodes (4): coletar_dados(), gerar_html(), main(), processar_dados()

### Community 62 - "Atualizar OCR"
Cohesion: 1.00
Nodes (3): atualizar_tipo_arquivo(), atualizar_todos_os_documentos(), connect_to_mongo()

### Community 63 - "Relatório Coberturas Produto"
Cohesion: 0.83
Nodes (3): enrich_with_sql(), get_mongo_data(), main()

## Knowledge Gaps
- **5 isolated node(s):** `Exames / Relatórios Médicos (4%)`, `I4Pro (SQL Server legado)`, `ClaimEngine (MongoDB)`, `AvisoSinistro / AvisoSinistroAnexo (SinistrosMicroService)`, `WHERE_FILTRO (Janela de Corte)`
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 265 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **14 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What connects `Exames / Relatórios Médicos (4%)`, `I4Pro (SQL Server legado)`, `ClaimEngine (MongoDB)` to the rest of the system?**
  _5 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `IA Regulador de Sinistros` be split into smaller, more focused modules?**
  _Cohesion score 0.06398730830248546 - nodes in this community are weakly interconnected._
- **Should `Ajuste de Metadados Mongo` be split into smaller, more focused modules?**
  _Cohesion score 0.08484848484848485 - nodes in this community are weakly interconnected._
- **Should `Importação eBox S3` be split into smaller, more focused modules?**
  _Cohesion score 0.051207729468599035 - nodes in this community are weakly interconnected._
- **Should `Migração Legado I4Pro` be split into smaller, more focused modules?**
  _Cohesion score 0.07198228128460686 - nodes in this community are weakly interconnected._
- **Should `Notificação com Anexos` be split into smaller, more focused modules?**
  _Cohesion score 0.08961593172119488 - nodes in this community are weakly interconnected._
- **Should `Automação e Protocolos` be split into smaller, more focused modules?**
  _Cohesion score 0.06756756756756757 - nodes in this community are weakly interconnected._