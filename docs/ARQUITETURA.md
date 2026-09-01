# Arquitetura

```text
DataJud TRF1–TRF6/STJ/TJs ─→ Bronze NDJSON.gz ─→ PostgreSQL
                                              │
                         número CNJ ──────────┤
                                              ↓
Comunica PJe ───────→ Bronze NDJSON.gz ──→ comunicações
                                              │
                                              ↓
                                  chunks, embeddings e IA
                                              │
                                              ↓
                                  views, API e relatórios

INSS (catálogo oficial) ────────────────→ recursos_externos
```

Toda consulta DataJud possui manifesto e impressão digital. O checkpoint usa
essa impressão digital, e `coleta_registros_datajud` registra quais hits foram
observados em cada execução.

PostgreSQL é a fonte oficial do estado normalizado. Parquet/DuckDB poderá ser
adicionado para snapshots analíticos grandes. ClickHouse será avaliado somente
com métricas que demonstrem gargalo em agregações; não é fonte transacional.

O serviço `migrate` aplica Alembic antes da API. O serviço `ingestion` é efêmero:
cada `docker compose run --rm ingestion ...` executa um trabalho e termina. O
banco usa volume nomeado e a camada Bronze usa `./data` montado no host.

O painel servido pela própria API cria registros em `tarefas_painel` e executa
os mesmos comandos CLI em segundo plano. Parâmetros são validados por schemas
Pydantic; não existe endpoint para executar comandos arbitrários. Logs, status e
códigos de saída sobrevivem ao recarregamento da página. Banco e API são
publicados somente em `127.0.0.1` no ambiente Docker local.
