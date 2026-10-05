# BPC Jud

Pipeline reprodutível para estudar a judicialização do Benefício de Prestação
Continuada (BPC) a partir de dados públicos do Judiciário e de fontes oficiais
de contexto social e previdenciário.

O projeto coleta metadados processuais e movimentações no DataJud, procura atos
publicados no Comunica PJe, importa as Tabelas Processuais Unificadas (TPU) e
cataloga conjuntos de dados abertos do INSS. Os dados são preservados em camada
bruta auditável e também normalizados no PostgreSQL para análise estatística e
uso posterior de IA com validação humana.

## Estado atual

- Coleta paginada e retomável no DataJud para TRF1–TRF6 e STJ.
- Varredura exploratória opcional dos 27 Tribunais de Justiça.
- Assuntos BPC iniciais: `6114`, `11946` e `11947`.
- Captura completa dos campos públicos ou modo essencial mais leve.
- Enriquecimento por número processual no Comunica PJe.
- Importação das referências TPU existentes no repositório.
- Catálogo automático de arquivos oficiais do INSS.
- Indicadores mensais agregados de BPC por município da CGU/Portal da Transparência.
- Painel web para executar e acompanhar todas as operações.
- Proveniência por coleta, checkpoint versionado e camada Bronze comprimida.
- Suíte automatizada com 35 testes.

## Arquitetura

```text
DataJud ───────────────┐
                      ├──> Bronze NDJSON.gz ──> PostgreSQL + pgvector
Comunica PJe ─────────┘                                │
                                                      ├──> API FastAPI
TPU CNJ ──────────────────────────────────────────────┤
                                                      ├──> Painel web
Catálogo INSS ────────────────────────────────────────┘
```

O PostgreSQL mantém entidades normalizadas, JSONB e a estrutura destinada a
embeddings. A camada Bronze conserva as respostas originais para auditoria e
reprocessamento. Cada hit DataJud é associado à execução que o observou.

Mais detalhes estão em [docs/ARQUITETURA.md](docs/ARQUITETURA.md) e
[docs/CONTRATOS.md](docs/CONTRATOS.md). O recorte DF/RIDE e a avaliação das
fontes estão em [docs/ESCOPO_PESQUISA.md](docs/ESCOPO_PESQUISA.md). Os pilotos
de fontes sem credencial estão em [docs/FONTES_ABERTAS.md](docs/FONTES_ABERTAS.md).

## Tecnologias

- Python 3.12, FastAPI, SQLAlchemy e Alembic
- PostgreSQL 18 com pgvector 0.8.6
- Docker Compose
- NDJSON compactado com gzip
- HTML, CSS e JavaScript sem framework no painel

## Pré-requisitos

- Docker Desktop com Docker Compose
- Uma chave pública vigente da API DataJud
- Portas locais `5432` e `8000` disponíveis, ou outras definidas no `.env`

## Início rápido

Para levar a base existente ao servidor remoto pelo Git, siga
[RESTAURAR_BANCO.md](RESTAURAR_BANCO.md): exportação em `.dump` e
restauração por script. O banco não acompanha um clone comum do repositório.

No PowerShell, a partir da raiz do projeto:

```powershell
Copy-Item .env.example .env
notepad .env
```

Preencha `DATAJUD_API_KEY` e troque a senha local do PostgreSQL. Nunca versione
o arquivo `.env`.

Suba o banco, aplique as migrações e inicie a API:

```powershell
docker compose up --build -d db api
```

Abra:

- Painel: <http://localhost:8000/>
- Explorador de processos: <http://localhost:8000/admin/processos>
- Documentação da API: <http://localhost:8000/docs>
- Verificação de saúde: <http://localhost:8000/health>

## Operações pelo painel

O painel permite:

1. Importar ou atualizar as tabelas TPU.
2. Selecionar tribunais e executar pilotos ou coletas completas no DataJud.
3. Acompanhar logs e retomar a paginação por checkpoint.
4. Buscar publicações no Comunica PJe.
5. Atualizar o catálogo oficial de recursos do INSS.
6. Examinar cobertura e assuntos encontrados junto aos códigos BPC.
7. Pesquisar cada processo, abrir seus registros DataJud, movimentações, atos
   publicados no Comunica PJe e eventuais extrações de IA, com origem explícita.

Comece sempre com um limite pequeno. A opção dos 27 TJs é exploratória e pode
gerar uma coleta extensa.

## Operações pela linha de comando

### Importar TPUs

```powershell
docker compose run --rm ingestion importar-tpu
```

### Piloto DataJud no TRF1

```powershell
docker compose run --rm ingestion datajud `
  --tribunais TRF1 `
  --page-size 50 `
  --max-records 100 `
  --restart
```

Para o recorte inicial de órgãos de Brasília em primeiro grau e JEF:

```powershell
docker compose run --rm ingestion datajud `
  --tribunais TRF1 --municipio-codigos 743 --graus G1 JE `
  --page-size 100 --max-records 1000
```

O código `743` refere-se ao município do órgão julgador no DataJud; não
identifica a residência do requerente nem cobre sozinho toda a RIDE.

### Piloto no STJ

```powershell
docker compose run --rm ingestion datajud `
  --tribunais STJ `
  --max-records 100 `
  --restart
```

### Piloto exploratório nos TJs

```powershell
docker compose run --rm ingestion datajud `
  --tribunais TRF1 `
  --include-state-courts `
  --max-records 100 `
  --restart
```

Por padrão, todos os campos públicos retornados são preservados. Use
`--source-mode essencial` para uma coleta mais leve. Remova `--max-records`
somente após validar o piloto. Ao retomar uma coleta interrompida, não use
`--restart`.

### Consultar o Comunica PJe

```powershell
docker compose run --rm ingestion comunica --limit 100
```

Para repetir falhas temporárias:

```powershell
docker compose run --rm ingestion comunica --limit 100 --retry-errors
```

### Catalogar recursos do INSS

```powershell
docker compose run --rm ingestion catalogar-inss
```

Esse comando registra metadados, formatos e URLs oficiais; ele não baixa todas
as planilhas automaticamente.

### Coletar indicadores municipais de BPC

Com `PORTAL_TRANSPARENCIA_API_TOKEN` preenchido no `.env`:

```powershell
docker compose run --rm ingestion transparencia-bpc `
  --municipios 5300108 --mes-inicial 202601 --mes-final 202607
```

Use códigos IBGE de sete dígitos; cada execução aceita até 120 combinações de
município e mês. A coleta preserva as páginas originais na camada Bronze e
atualiza, sem duplicar, `indicadores_bpc_municipio`. São quantidades de
beneficiados e valores mensais agregados, não concessões novas, pessoas
identificáveis ou resultados de processos. O município desse indicador não é
necessariamente o município do órgão julgador no DataJud.

### Consultar o resumo

```powershell
docker compose run --rm ingestion resumo
```

### Piloto de triagem com IpeaIA

Na área remota autorizada, configure `IPEAIA_API_TOKEN` no `.env`. A API
documentada pelo Ipea é compatível com chat completions, mas a integração
envia apenas dados processuais minimizados e não usa documentos ou partes.

```powershell
docker compose run --rm ingestion ipeaia-modelos
docker compose run --rm ingestion ipeaia-triagem --limit 1
docker compose run --rm ingestion ipeaia-triagem --limit 1 --executar
```

`--model ID` substitui o modelo de `IPEAIA_MODEL`. A execução exige
`--executar`; respostas válidas ficam em `extracoes_ia` como pendentes de
revisão humana. Para transferir o banco à área remota e entender a taxonomia,
consulte [PROMPT_REVISAO_IPEAIA.md](PROMPT_REVISAO_IPEAIA.md). Um clone do Git
não inclui o banco nem a camada de dados brutos.

## Endpoints úteis

- `GET /resumo`
- `GET /processos?tribunal=TRF1&limit=50`
- `GET /processos/{numero_cnj}`
- `GET /admin/api/processos?numero=...&tribunal=TRF1&limit=25&offset=0`
- `GET /admin/api/processos/{numero_cnj}`
- `GET /analises/cobertura-comunica`
- `GET /analises/assuntos-relacionados`
- `GET /fontes/inss`
- `GET /tarefas`

## Organização do repositório

```text
.
├── compose.yaml                 # serviços locais
├── ingestion/                   # coletor, API, painel, migrações e testes
│   ├── src/bpc_ingestion/
│   ├── migrations/
│   └── tests/
├── datajud/                     # submódulo com implementação legada recebida
├── jeferson/                    # submódulo do coletor Comunica PJe de referência
├── docs/                        # arquitetura e contratos de dados
└── apresentacao_bpc_jud.html    # apresentação do projeto de pesquisa
```

Arquivos coletados, bancos locais e exportações processuais estão ignorados pelo
Git. As tabelas TPU mínimas utilizadas pela aplicação permanecem versionadas.
Os repositórios de referência são mantidos como submódulos para preservar sua
autoria e histórico.

## Persistência e segurança

- Respostas brutas: `data/raw/`
- Checkpoints: `data/state/datajud-checkpoints.json`
- Banco: volume Docker `bpc-jud_postgres_data`
- Credenciais: `.env`, nunca incluído no Git

Para parar os serviços preservando o banco:

```powershell
docker compose down
```

Não execute `docker compose down -v` sem backup: a opção `-v` remove o volume
do PostgreSQL.

## Testes

```powershell
docker compose run --rm --entrypoint python ingestion `
  -m unittest discover -s tests -v
```

## Limitações metodológicas

- O DataJud fornece metadados e movimentos, não o inteiro teor dos autos.
- O Comunica PJe contém atos publicados e não garante cobertura de todo processo.
- A mesma ação pode possuir registros em diferentes graus; a unidade de análise
  deve ser definida explicitamente para evitar dupla contagem.
- Dados administrativos do INSS e indicadores municipais devem ser cruzados de
  forma agregada, não por identificação pessoal.
- Classificações feitas por IA precisam de amostra rotulada, métricas de erro e
  revisão humana antes de serem usadas em resultados acadêmicos.
- Dumps brutos podem conter dados pessoais publicamente disponibilizados e não
  devem ser publicados no repositório.

## Fontes oficiais

- [API Pública do DataJud](https://www.cnj.jus.br/sistemas/datajud/api-publica/)
- [Endpoints DataJud](https://datajud-wiki.cnj.jus.br/api-publica/endpoints/)
- [Padrões de API do PJe](https://docs.pje.jus.br/manuais-basicos/padroes-de-api-do-pje/)
- [Dados Abertos do INSS](https://www.gov.br/inss/pt-br/acesso-a-informacao/dados-abertos/dados-abertos)
- [API do Portal da Transparência](https://portaldatransparencia.gov.br/api-de-dados)

## Próximos passos

- Baixar e normalizar apenas os conjuntos do INSS relevantes ao BPC.
- Avaliar indicadores municipais complementares do IBGE/SIDRA e do MDS.
- Produzir camada analítica Gold, com uma linha por processo/coorte.
- Construir taxonomia de eventos a partir das TPUs.
- Validar extrações assistidas por IA em amostra anotada.
