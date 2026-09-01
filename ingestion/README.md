# Ingestão BPC

Este pacote é o núcleo de coleta do projeto. A execução oficial usa PostgreSQL
com pgvector pelo `compose.yaml` da raiz.

Comandos disponíveis:

```text
python -m bpc_ingestion datajud
python -m bpc_ingestion comunica
python -m bpc_ingestion importar-tpu
python -m bpc_ingestion resumo
```

Consulte o [README principal](../README.md) para instalação e exemplos.

O SQLite foi mantido somente como compatibilidade para testes pequenos com
`datajud --storage sqlite`; ele não representa o esquema analítico oficial.
