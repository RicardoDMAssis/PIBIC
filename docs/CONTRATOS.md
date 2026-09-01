# Contrato de dados BPC Jud — v0.2

Este documento substitui o contrato v0.1 baseado em SQLite/MongoDB.

## Fontes

- DataJud: universo de processos e movimentos dos assuntos 6114, 11946 e 11947;
- Comunica PJe: comunicações e atos publicados consultados por número CNJ;
- TPU local: nomes e hierarquias de assuntos, classes e movimentos do CNJ.

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

O payload bruto também fica em JSONB, mas os campos usados em filtros e junções
devem possuir colunas tipadas.

### Gold

As views iniciais são:

- `vw_resumo_tribunais`;
- `vw_processos_analiticos`;
- `vw_cobertura_comunica`.

Novas métricas devem registrar fórmula, população, tratamento de ausências e
versão da pipeline.

## IA

Todo chunk deve registrar texto, hash, modelo de embedding, dimensão e versão da
pipeline. Toda extração deve registrar modelo, versão do prompt, resultado JSON
e status de validação. A dimensão vetorial será definida quando o modelo for
selecionado; a coluna `vector` aceita armazenamento antes da criação de um índice
específico por dimensão/modelo.

## Regras de qualidade

- Datas normalizadas em UTC;
- Payload Bronze nunca corrigido ou sobrescrito;
- Correção de encoding somente nos campos normalizados;
- Checkpoint avança após Bronze e transação PostgreSQL;
- `sem_resultado` no Comunica é diferente de erro;
- Reexecução não cria duplicatas;
- Não inferir concessão ou negativa apenas pela existência do movimento Sentença;
- Não versionar chaves, dumps brutos ou dados pessoais.
