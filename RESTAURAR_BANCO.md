# Levar o banco pelo Git

O `git pull` baixa o arquivo `.dump`. A restauracao acontece ao executar o
script. O resultado e uma copia do PostgreSQL local no servidor
remoto, incluindo processos, movimentos, publicacoes e extracoes de IA existentes
no momento da exportacao. Novas alteracoes em uma maquina nao sincronizam
automaticamente com a outra.

## Preparacao nas duas maquinas

Use PowerShell e Docker Desktop ligado. Todos os comandos seguintes sao na
raiz do projeto. Nao ha senha de arquivo nem dependencia do 7-Zip.

## Aqui: exportar e enviar

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\transferir-banco.ps1 -Modo Exportar
```

O script gera `transferencia/bpc-jud.dump`, comprimido pelo PostgreSQL.

Adicione o dump, script e documentacao:

```powershell
git add .gitignore scripts/transferir-banco.ps1 RESTAURAR_BANCO.md transferencia/bpc-jud.dump
git commit -m "Adiciona copia do banco BPC para o servidor remoto"
git push
```

As alteracoes do cliente IpeaIA tambem precisam estar commitadas e enviadas para
aparecerem no clone remoto. O `.env` permanece local em cada maquina.

## La: baixar e restaurar

No PowerShell da area remota, na raiz do clone:

```powershell
git pull
git submodule update --init --recursive
```

Se ainda nao houver `.env`, copie `.env.example` para `.env` e defina
`POSTGRES_PASSWORD` e `IPEAIA_API_TOKEN`. Preserve um `.env` ja configurado.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\transferir-banco.ps1 -Modo Restaurar
```

O script inicia o banco, verifica o destino, restaura e exibe a quantidade de processos. Ele
recusa restaurar sobre tabelas que ja tenham dados. Se ocorrer um erro durante
o `pg_restore`, a transacao da restauracao e revertida.

Depois, construa e inicie a aplicacao atualizada:

```powershell
docker compose up --build -d api
docker compose build ingestion
curl.exe http://localhost:8000/resumo
docker compose run --rm ingestion ipeaia-modelos
docker compose run --rm ingestion ipeaia-triagem --limit 1 --executar
```

A resposta da IA fica em `extracoes_ia` no PostgreSQL remoto. O dump e uma
copia pontual da base; nao e necessario restaurar novamente a cada `git pull`.
Arquivos Bronze em `data/raw/` nao integram o pacote, mas os dados persistidos
no PostgreSQL integram. Se o dump ultrapassar 100 MiB, sera necessario Git LFS
para envia-lo ao GitHub.
