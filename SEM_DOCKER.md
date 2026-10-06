# Área remota: SQLite, painel e IpeaIA sem Docker

O pacote `transferencia/bpc-jud.sqlite.gz` contém todas as tabelas e dados da
aplicação exportados do PostgreSQL local. A cópia de 05/10/2026 tem 2.584
processos e 125.692 movimentos. Não é o SQLite legado do coletor antigo.

## Aqui: enviar o código e o pacote pelo Git

Inclua no commit as alterações de `ingestion/`, a documentação, `.env.example`
e `transferencia/bpc-jud.sqlite.gz`, e faça push. O arquivo `.env` permanece
local. O pacote já foi gerado; não é necessário exportá-lo outra vez.

```powershell
git add ingestion docs .env.example README.md RESTAURAR_BANCO.md PROMPT_REVISAO_IPEAIA.md SEM_DOCKER.md transferencia/bpc-jud.sqlite.gz
git commit -m "Adiciona base SQLite e execucao remota sem Docker"
git push origin main
```

## Lá: instalar e abrir a base

Requisito: Python 3.11 ou superior. Execute na raiz do clone remoto:

```powershell
git pull
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install ./ingestion
.\.venv\Scripts\python.exe -m bpc_ingestion.portable inicializar
```

Se `py` não existir, use `python` no comando de criação do ambiente. O último
comando descompacta a base em `data/bpc-remote.sqlite` e mostra o total de
processos. Ele preserva um arquivo já existente e recusa sobrescrevê-lo.
Não inicialize novamente uma base que já recebeu resultados da IA.

Se ainda não existir `.env`, copie `.env.example` para `.env`. Edite o `.env`
existente ou recém-criado e configure:

```dotenv
DATABASE_URL=sqlite:///./data/bpc-remote.sqlite
IPEAIA_API_TOKEN=SEU_TOKEN_LOCAL
IPEAIA_BASE_URL=https://ipeagpt.ipea.gov.br/api/v1
IPEAIA_MODEL=glm-5.1
IPEAIA_TIMEOUT_SECONDS=600
```

O painel e os comandos leem o `.env` automaticamente. Execute sempre da raiz
do projeto para usar o mesmo arquivo SQLite. Não é necessário instalar
PostgreSQL, Docker ou pgvector no servidor.

## Abrir o painel

```powershell
.\.venv\Scripts\python.exe -m uvicorn bpc_ingestion.api:app --host 127.0.0.1 --port 8000
```

Abra `http://localhost:8000/admin/processos` no navegador da área remota.
O terminal fica ocupado pela API; abra um segundo terminal para os comandos:

```powershell
.\.venv\Scripts\python.exe -m bpc_ingestion resumo
.\.venv\Scripts\python.exe -m bpc_ingestion ipeaia-modelos
.\.venv\Scripts\python.exe -m bpc_ingestion ipeaia-triagem --limit 1
.\.venv\Scripts\python.exe -m bpc_ingestion ipeaia-triagem --limit 1 --executar
```

A saída da IA fica em `extracoes_ia` dentro de `data/bpc-remote.sqlite`, com
status pendente de revisão, e pode ser vista no detalhe do processo no painel.
Sem `--executar`, há somente prévia e nenhuma chamada à IpeaIA.

Para modelos lentos, o tempo limite de rede é 600 segundos por padrão e pode
ser alterado por `IPEAIA_TIMEOUT_SECONDS` ou `--timeout 900`. Um timeout mostra
mensagem específica e não repete automaticamente a geração. Erros de rede
mostram a causa (por exemplo, certificado ou DNS). Atualize o código remoto
com `git pull` e `python -m pip install ./ingestion` antes de usar a nova opção.

## Diagnóstico de respostas rejeitadas

Se a resposta for rejeitada, o comando mostra o campo e o índice da evidência
inválida e salva um diagnóstico em `data/ipeaia_rejeitadas/<id>.json`. O arquivo
contém a entrada enviada, modelo, versão do prompt, erro e resposta da API,
sem token. Ele fica fora do Git. A resposta inválida não entra em `extracoes_ia`;
o processo permanece pendente para nova tentativa. Não há repetição automática.
Este diagnóstico de formato não substitui a revisão humana dos fatos citados.

## Atualizar a cópia no futuro

A origem PostgreSQL permanece na máquina local. O módulo
`bpc_ingestion.portable exportar` lê essa origem e gera um novo pacote SQLite.
Escolha outro caminho de saída para conservar o pacote anterior. A exportação
valida todas as tabelas antes da transferência. Novas classificações feitas no
SQLite remoto ficam no arquivo remoto e não retornam automaticamente à origem.
Nesta etapa, o SQLite armazena embeddings como JSON; a busca vetorial exige
PostgreSQL. Não use Alembic nesta cópia portátil.
