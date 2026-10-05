[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Exportar', 'Restaurar')]
    [string]$Modo
)

$ErrorActionPreference = 'Stop'
$repoBpc = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pastaPacote = Join-Path $repoBpc 'transferencia'
$dumpLocal = Join-Path $pastaPacote 'bpc-jud.dump'
$dumpContainer = '/tmp/bpc-transfer-' + [Guid]::NewGuid().ToString('N') + '.dump'
$apiParada = $false
$containerDisponivel = $false

function Assert-NativeSuccess([string]$Etapa) {
    if ($LASTEXITCODE -ne 0) { throw "$Etapa falhou (codigo $LASTEXITCODE)." }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker nao encontrado. Instale/inicie o Docker Desktop.'
}

Push-Location $repoBpc
try {
    # Falha cedo, antes de criar arquivos, quando Docker nao estiver iniciado.
    & docker info --format '{{.ServerVersion}}' | Out-Null
    Assert-NativeSuccess 'Conexao ao Docker'
    if ($Modo -eq 'Restaurar' -and -not (Test-Path -LiteralPath $dumpLocal -PathType Leaf)) {
        throw 'Dump nao encontrado. Faca git pull com transferencia/bpc-jud.dump.'
    }

    & docker compose up -d --wait db
    Assert-NativeSuccess 'Inicializacao do banco'
    $containerDisponivel = $true
    $usuarioBpc = (& docker compose exec -T db printenv POSTGRES_USER).Trim()
    Assert-NativeSuccess 'Leitura do usuario do banco'
    $nomeBpc = (& docker compose exec -T db printenv POSTGRES_DB).Trim()
    Assert-NativeSuccess 'Leitura do nome do banco'

    if ($Modo -eq 'Exportar') {
        $quantidadeBpc = & docker compose exec -T db psql -U $usuarioBpc -d $nomeBpc -At -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM processos;'
        Assert-NativeSuccess 'Verificacao da base de origem'
        if ([long]$quantidadeBpc -eq 0) { throw 'A base de origem esta vazia; dump cancelado.' }
        Write-Host "Exportando $quantidadeBpc processos."
        & docker compose exec -T db pg_dump -U $usuarioBpc -d $nomeBpc -Fc -Z9 -f $dumpContainer
        Assert-NativeSuccess 'Geracao do dump'
        New-Item -ItemType Directory -Path $pastaPacote -Force | Out-Null
        & docker compose cp "db:$dumpContainer" $dumpLocal
        Assert-NativeSuccess 'Copia do dump'
        $tamanhoBpc = (Get-Item -LiteralPath $dumpLocal).Length
        Write-Host ('Dump pronto: transferencia/bpc-jud.dump ({0:N1} MiB).' -f ($tamanhoBpc / 1MB))
        if ($tamanhoBpc -gt 100MB) {
            throw 'Dump maior que 100 MiB: o GitHub exige Git LFS para este arquivo.'
        }
    } else {
        # Apenas bancos vazios ou com tabelas de migracao vazias sao aceitos.
        $apiEstavaRodando = & docker compose ps --status running -q api
        Assert-NativeSuccess 'Verificacao da API'
        if ($apiEstavaRodando) {
            & docker compose stop api
            Assert-NativeSuccess 'Pausa da API'
            $apiParada = $true
        }
        $sqlBpc = @'
SELECT format('SELECT %L, count(*) FROM %I.%I;', tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version';
\gexec
'@
        $contagensBpc = @($sqlBpc | & docker compose exec -T db psql -U $usuarioBpc -d $nomeBpc -At -v ON_ERROR_STOP=1)
        Assert-NativeSuccess 'Verificacao do destino'
        foreach ($linhaBpc in $contagensBpc) {
            if ($linhaBpc -notmatch '^([^|]+)\|([0-9]+)$') {
                throw "Nao foi possivel verificar o destino: $linhaBpc"
            }
            if ([long]$Matches[2] -gt 0) {
                throw "Destino possui dados na tabela $($Matches[1]). Restauracao cancelada; nada foi apagado."
            }
        }

        & docker compose cp $dumpLocal "db:$dumpContainer"
        Assert-NativeSuccess 'Copia para o container remoto'
        # --clean so e usado depois de confirmar que todas as tabelas de dados estao vazias.
        # --single-transaction reverte a restauracao inteira em caso de erro.
        & docker compose exec -T db pg_restore -U $usuarioBpc -d $nomeBpc --clean --if-exists --no-owner --no-privileges --single-transaction $dumpContainer
        Assert-NativeSuccess 'Restauracao do banco'
        & docker compose exec -T db psql -U $usuarioBpc -d $nomeBpc -c 'SELECT count(*) AS processos_restaurados FROM processos;'
        Assert-NativeSuccess 'Conferencia dos processos'
        Write-Host 'Banco restaurado. Os dados agora estao no volume PostgreSQL desta maquina.'
    }
} finally {
    if ($containerDisponivel) {
        # Remove apenas o arquivo temporario com nome aleatorio criado nesta execucao.
        & docker compose exec -T db rm -f -- $dumpContainer | Out-Null
    }
    if ($apiParada) {
        & docker compose start api
        if ($LASTEXITCODE -ne 0) { Write-Warning 'Banco preservado, mas a API nao iniciou. Consulte docker compose logs api.' }
    }
    Pop-Location
}
