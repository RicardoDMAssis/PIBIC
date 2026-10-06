# Contrato de dados BPC Jud — v0.3

Este documento substitui o contrato v0.1 baseado em SQLite/MongoDB.

## Fontes

- DataJud: universo de processos e movimentos dos assuntos 6114, 11946 e 11947;
- Comunica PJe: comunicações e atos publicados consultados por número CNJ;
- TPU local: nomes e hierarquias de assuntos, classes e movimentos do CNJ.
- Catálogo CKAN do INSS: metadados de recursos em `recursos_externos`; os
  arquivos mensais de benefícios ainda não integram a camada Silver.
- Portal da Transparência/CGU: `GET /api-de-dados/bpc-por-municipio`, indicadores
  mensais agregados de BPC por código IBGE, autenticados pelo cabeçalho
  `chave-api-dados`. O token vem do ambiente, nunca do código ou do payload.

## Identidades

- Entidade processo: `processos.numero_processo`, CNJ formatado e único;
- Hit DataJud: par `registros_datajud.datajud_index + datajud_id`;
- Comunicação: par `processo_id + hash_conteudo`;
- Hit e processo não são sinônimos: um processo pode possuir mais de um registro
  por grau, índice ou atualização.

## Camadas

### Bronze

Respostas imutáveis em `data/raw/<fonte>/<particao>/<data>/<execucao>.ndjson.gz`.
O conteúdo deve permanecer igual ao recebido.

### Silver

PostgreSQL normalizado:

- `coletas`;
- `tarefas_painel`;
- `processos`;
- `registros_datajud`;
- `assuntos` e `registro_assuntos`;
- `movimentos`;
- `consultas_pje`;
- `comunicacoes_pje`;
- `referencias_tpu`;
- `documento_chunks`;
- `extracoes_ia`.
- `recursos_externos` (catálogo de fontes, não indicadores importados).
- `indicadores_bpc_municipio` (agregados da CGU; não são processos).

O payload bruto também fica em JSONB, mas os campos usados em filtros e junções
devem possuir colunas tipadas.

### Contrato de `indicadores_bpc_municipio`

Um registro por `fonte + mes_ano + codigo_ibge + tipo_id`:

| Campo | Tipo | Significado |
| --- | --- | --- |
| `fonte` | `varchar(30)` | `portal_transparencia` |
| `mes_ano` | `integer` | Competência `AAAAMM` pedida na API |
| `data_referencia` | `date` | Data retornada pela API |
| `codigo_ibge` | `varchar(7)` | Município do indicador, não do órgão julgador |
| `municipio_nome`, `uf` | `text`, `varchar(2)` | Rótulos retornados pela API |
| `tipo_id` | `integer` | Identificador do tipo BPC retornado |
| `quantidade_beneficiados` | `bigint` | Estoque de beneficiados informado no mês |
| `valor` | `numeric(18,2)` | Valor monetário nominal informado no mês |
| `payload` | `jsonb` | Objeto original da API, sem token |
| `coleta_id`, `coletado_em` | `uuid`, `timestamptz` | Última coleta que confirmou o indicador |

As páginas completas da API, inclusive respostas vazias, ficam na Bronze sob
`data/raw/transparencia_bpc/municipios/`. Uma repetição atualiza a mesma chave
sem duplicar. O indicador não pode ser unido diretamente a uma pessoa ou ação
judicial; município do indicador e município do órgão julgador são conceitos
distintos. Não usar a quantidade como denominador de taxa de procedência.

### Gold

As views iniciais são:

- `vw_resumo_tribunais`;
- `vw_processos_analiticos`;
- `vw_cobertura_comunica`.

Novas métricas devem registrar fórmula, população, tratamento de ausências e
versão da pipeline.

## IA

### Execução portátil sem Docker (05/10/2026)

A base PostgreSQL pode ser exportada para SQLite mantendo as mesmas tabelas,
colunas, chaves, vínculos e dados da aplicação. O módulo `bpc_ingestion.portable`
confere contagens de todas as tabelas, integridade e chaves estrangeiras antes
de publicar `transferencia/bpc-jud.sqlite.gz`. `alembic_version` é metadado
específico do PostgreSQL e não acompanha a cópia; as três views analíticas são
recriadas com sintaxe SQLite. O antigo `SqliteStore` de `processos_raw` é legado
e não deve ser usado para esta cópia.

No SQLite, JSONB usa JSON, UUID usa representação hexadecimal e os IDs usam
INTEGER de 64 bits com geração automática. Campos monetários mantêm o contrato
de duas casas, com a representação NUMERIC do SQLite. Embeddings, se existentes,
são listas JSON; busca vetorial pgvector continua restrita ao PostgreSQL.
Datas seguem o contrato UTC, com leitura sem informação de fuso no SQLite.
O painel e `ipeaia-triagem` usam a cópia definida em `DATABASE_URL` e gravam
`extracoes_ia` nesse mesmo arquivo. A cópia é destinada ao piloto de pesquisa
no ambiente remoto; alterações não sincronizam automaticamente com a origem.
Não executar as migrações Alembic PostgreSQL nesta cópia SQLite.

Todo chunk deve registrar texto, hash, modelo de embedding, dimensão e versão da
pipeline. Toda extração deve registrar modelo, versão do prompt, resultado JSON
e status de validação. A dimensão vetorial será definida quando o modelo for
selecionado; a coluna `vector` aceita armazenamento antes da criação de um índice
específico por dimensão/modelo.

O piloto IpeaIA usa `extracoes_ia.tipo_extracao = triagem_bpc`,
`versao_prompt = bpc_triagem_api_v1.0`, `resultado` JSONB validado e
`status_validacao = pendente`. O modelo vem de `IPEAIA_MODEL` ou `--model`.
Envia apenas campos normalizados de registros públicos TRF1/G1/JE do órgão de
Brasília: classe, órgão, assuntos e movimentos sem complementos, com indicação
de truncamento. Não envia `payload_original`, partes, CPF nem documentos. O
desfecho permanece `indeterminado` sem texto decisório. Cada combinação de
processo, tipo, modelo e versão do prompt é única; uma nova metodologia requer
nova versão, não sobrescrita silenciosa. A classificação não está validada até
revisão humana.

## Regras de qualidade

- Datas normalizadas em UTC;
- Payload Bronze nunca corrigido ou sobrescrito;
- Correção de encoding somente nos campos normalizados;
- Checkpoint avança após Bronze e transação PostgreSQL;
- `sem_resultado` no Comunica é diferente de erro;
- Reexecução não cria duplicatas;
- Não inferir concessão ou negativa apenas pela existência do movimento Sentença;
- Não versionar chaves nem o `.env`. Para a transferência solicitada pelo
  pesquisador, `transferencia/bpc-jud.dump` e `transferencia/bpc-jud.sqlite.gz`
  são as cópias autorizadas a
  acompanhar o Git, sem criptografia. Arquivos Bronze continuam fora do Git.

## Log de decisões

| Data | Decisão | Consequência |
| --- | --- | --- |
| 05/10/2026 | Usar cópia SQLite no servidor remoto sem Docker; manter PostgreSQL na origem. | Mesmas tabelas e dados da aplicação; extrações de IA persistidas em `data/bpc-remote.sqlite`. Embeddings armazenados como JSON, sem busca pgvector nesse ambiente. |
