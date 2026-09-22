# Fontes abertas adicionais — avaliação inicial (22/09/2026)

O recorte principal continua sendo o de [ESCOPO_PESQUISA.md](ESCOPO_PESQUISA.md).
Estas fontes não substituem o DataJud e não devem ser ligadas a uma pessoa ou
processo sem identificador e autorização adequados.

## DJEN / Comunica PJe

- A consulta pública `GET /api/v1/comunicacao` por número CNJ, já implementada,
  respondeu sem autenticação. No piloto de 50 processos ainda não consultados,
  estratificados em 10 por ano de ajuizamento de 2021 a 2025 no recorte
  TRF1/órgão de Brasília/G1 ou JE, 3 tiveram resultado e 47 não tiveram.
  Foram persistidas 7 comunicações (intimações, despacho e ato ordinatório),
  nenhuma tipificada como sentença. O piloto não estima cobertura universal.
- A [API pública documenta](https://hcomunicaapi.cnj.jus.br/swagger/djen.yml)
  busca por tribunal, data e texto, além do caderno por tribunal/data/meio.
  A consulta experimental de texto `BPC` retornou HTTP 500; não foi usada
  para ingestão. Um caderno TRF1/D de 21/09/2026 respondeu sem credencial,
  mas anuncia 51.030 comunicações e 197.903.371 bytes. A ingestão indiscriminada
  de cadernos inteiros não se justifica antes de medir a cobertura e o custo.
- Comunicações são atos publicados, não inteiro teor dos autos. O endpoint
  `POST` e a autenticação do CNJ são de uso dos tribunais, não deste projeto.

## TRF1

- A [consulta processual antiga](https://processual.trf1.jus.br/consultaProcessual/)
  apresenta metadados e, em alguns processos, links de “Inteiro Teor”. Uma
  tentativa de consulta automatizada de um processo de 2018 do nosso recorte
  recebeu a página de verificação anti-robô. Não contornar essa proteção.
- O [PJe atual](https://www.trf1.jus.br/trf1/processual/consulta-processual)
  limita a consulta pública, e não foi identificada API pública de coleta em
  lote de sentenças. Acesso sistemático a documentos exige diálogo institucional
  com o tribunal. Uma amostra manual autorizada pode medir a disponibilidade.

## INSS — bases mensais

- O catálogo oficial [CKAN do INSS](https://dadosabertos.inss.gov.br/) responde
  sem credencial. As buscas por “beneficios indeferidos” e “beneficios concedidos”
  catalogaram respectivamente 102 e 106 recursos nesta rodada. Esses números
  contam metadados de arquivos, não benefícios importados. A tabela
  `recursos_externos` contém o catálogo e mantém URL e metadados da fonte.
- No arquivo [Benefícios Indeferidos — julho/2026](https://dadosabertos.inss.gov.br/dataset/beneficios-indeferidos-plano-de-dados-abertos-jun-2023-a-jun-2025),
  a leitura experimental encontrou 935.123 linhas. Para `UF = Distrito Federal`,
  foram 5.200 indeferimentos da espécie 87 (BPC pessoa com deficiência) e 462
  da 88 (BPC idoso). Há coluna de motivo, mas não de número CNJ nem município
  de residência nessa planilha. Esses totais **não** representam processos nem
  requerentes únicos e não devem ser comparados diretamente à amostra DataJud.
  Não houve persistência de microdados; a cópia temporária foi removida.
- Próxima implementação: importador de indicadores agregados por competência,
  UF, espécie e motivo, com hash e URL do arquivo de origem, dicionário de
  categorias e controle de qualidade. Criar o contrato da nova tabela antes da
  migração. Para análise municipal, usar fonte que explicite a geografia e sua
  unidade (residência, APS ou município pagador).

## Portal da Transparência/CGU — integrado

- O pesquisador configurou localmente o token da
  [API do Portal da Transparência](https://portaldatransparencia.gov.br/api-de-dados).
  Ele permanece no `.env` e não deve ir ao Git nem a mensagens. A coleta usa
  `GET /api-de-dados/bpc-por-municipio` com `mesAno`, `codigoIbge` e `pagina`,
  autenticado pelo cabeçalho `chave-api-dados`.
- Uma chamada real para Brasília (`5300108`) em julho/2026 retornou
  `quantidadeBeneficiados = 70480` e `valor = 131276767.55`, além de
  `dataReferencia`, município e tipo BPC. O comando `transparencia-bpc` grava
  a resposta original na Bronze e o indicador em `indicadores_bpc_municipio`.
  A série de Brasília de janeiro/2019 a julho/2026 foi coletada: 91 competências,
  todas com resposta, e uma reexecução não duplicou a competência já existente.
  Esses dados são agregados mensais; não representam novas concessões,
  pessoas identificadas nem decisões judiciais. Não equiparar o município
  retornado ao município do órgão julgador do DataJud sem validação geográfica.

## Fontes que exigem participação do pesquisador
- Dados individuais do INSS/CadÚnico ou inteiro teor em lote no PJe exigem
  autorização institucional e revisão da governança de dados. Não presumir que
  o caráter público de um processo autoriza extração irrestrita de seus dados.
