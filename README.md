# Apuração 2026

Coletor Python de resultados oficiais EA20 do TSE, com consolidados atuais em SQLite, API de leitura e dashboard React. O sistema acompanha Brasil, UFs, municípios e zonas no ciclo `ele2026`.

## Executar

Requer Python 3.11+ e PDM. Na raiz do projeto:

```sh
pdm install
pdm run collect --once --uf ac
pdm run collect
pdm run api
```

`--once` executa um ciclo e encerra; sem ele, o coletor permanece ativo até Ctrl+C. Abrir a API ou o dashboard não inicia a coleta. Para o frontend, consulte [execução e uso do dashboard](docs/dashboard.md).

```sh
pdm run collect --config outro-config.toml --once
pdm run collect --once --uf ce --uf pe
pdm run collect --once --json-only
```

`--uf` limita a coleta territorial, preservando o recorte nacional quando habilitado. `--json-only` consulta apenas os endpoints fixos. O caminho do banco é relativo ao arquivo de configuração.

## Configuração da coleta

`config.toml` define o banco, intervalo, timeout e o pleito. Os níveis são independentes:

```toml
[results.levels]
brasil = true
ufs = true
municipios = true
zonas = false
```

Os quatro níveis são suportados; a configuração atual deixa zonas desativadas. Chaves omitidas assumem `true`. Nomes desconhecidos e valores diferentes de `true`/`false` são rejeitados. Reinicie o coletor para aplicar alterações.

A passagem segue Brasil → UFs → municípios → zonas. Nos municípios, UFs com menos municípios distintos no catálogo vêm primeiro. Nas zonas, a prioridade é o total municipal de votos, do maior para o menor, sempre para a mesma eleição e cargo. Totais desconhecidos ficam depois de zero. Se municípios estiverem desativados, a prioridade das zonas usa apenas dados já presentes no banco.

O progresso fica persistido entre ciclos e reinícios. Brasil e UFs são consultados antes dos recortes locais; `max_local_results_per_cycle` limita o total de tentativas de municípios e zonas por ciclo. Cada passagem só recomeça depois de concluir todos os recortes habilitados. Falhas permanecem pendentes e impedem avançar à etapa seguinte.

O limite atual é de 20 requisições por segundo e 1.000 recortes locais por ciclo, com pausa de 30 segundos entre ciclos. Esses limites abrangem catálogos e resultados; a pausa não representa o prazo de atualização do país. Respostas 403, 404 e 429 interrompem a coleta e persistem um cooldown de pelo menos 610 segundos.

No modo de resultados, endpoints fixos terminados em `-u.json` são atendidos pelo agendamento EA20, evitando duplicação e desrespeito aos toggles. Outros endpoints fixos continuam ao final do ciclo. Em `--json-only`, todos os endpoints fixos são consultados.

`ufs = []` inclui as UFs disponíveis e o exterior (`zz`), quando aplicável ao cargo. Eleições, cargos e caminhos vêm do EA11; municípios e zonas vêm do EA12. O catálogo é persistido somente para `ele2026`. A migração inclui apenas datasets do ciclo de 2026.

Detalhes: [coleta e persistência](docs/collection.md).

## Consolidados e dados

Cada resposta válida atualiza o consolidado da eleição, cargo e território na mesma transação. Os votos anteriores são substituídos, sem snapshots, versões ou JSON armazenado. URL, hash e horários da última resposta ficam em `sources`.

O banco usa 11 tabelas:

| Estrutura | Função |
|---|---|
| `datasets`, `elections`, `offices` | Ambiente, pleito, eleições/turnos e cargos por abrangência |
| `territories` | UFs, municípios e zonas do catálogo |
| `candidates` | Cadastro único de candidaturas |
| `sources` | Estado HTTP e origem dos consolidados |
| `results` | Totais atuais e flag `completed` por recorte |
| `candidate_votes`, `party_votes`, `vote_categories` | Votos atuais por candidato, partido e categoria |
| `collection_state` | Passagem corrente, recortes consultados e cooldown |

`completed=1` exige identidade válida, votos disponíveis e seções totalizadas iguais ao total, maior que zero. O agendamento deixa de consultar esse recorte, inclusive após reinício. A conclusão é independente por eleição, cargo e território: uma UF concluída não dispensa buscar seus municípios ou zonas habilitados. Recortes incompletos continuam nas próximas passagens.

Ausência de resultado significa dado pendente, não zero votos. Confira `available` antes de usar totais. Não some diferentes níveis territoriais. Preserve eleição, turno, cargo e circunscrição ao identificar candidatos.

### Migrar um banco anterior

Pare o coletor e a API. A conversão cria outro arquivo e preserva integralmente o original:

```sh
pdm run migrate --source data/apuracao-2026.sqlite3 --output data/apuracao-consolidada.sqlite3
```

Depois altere `database` no TOML para o novo caminho e reinicie os serviços. A migração escolhe o último resultado com identidade válida para cada recorte, preserva votos, metadados, origem e cooldown e verifica a integridade do destino. Bancos com a antiga coluna `snapshots.payload` não são aceitos por essa migração. O histórico permanece somente no arquivo original; a aplicação passa a consultar apenas os consolidados.

## Organização

- `collector/cli.py`: argumentos de linha de comando.
- `collector/config.py`: leitura e validação do TOML.
- `collector/service.py`: execução dos ciclos.
- `collector/http.py`: HTTP, limitador e atualização dos consolidados.
- `collector/client.py`: catálogo, templates de URL e cooldown persistente.
- `collector/results.py` e `result_schedule.py`: descoberta, ordem e progresso da coleta.
- `official_store.py`: normalização e gravação de resultados.
- `metadata_store.py`: persistência do catálogo e geografia.
- `official.py`: interpretação e consultas oficiais.
- `database.py` e `schema.sql`: inicialização do SQLite.
- `api/`: dashboard, opções territoriais, mapas e cache.

Os caminhos Python acima ficam em `apuracao/`. A entrada alternativa `pdm run python -m apuracao` também inicia o coletor.

## Dashboard e validação

A interface apresenta resultados oficiais, partidos, candidatos, regiões e progresso informado pelo TSE. A navegação termina na zona; o mapa cobre país, UF e município. A interface mostra somente o estado atual. Os números de seções totalizadas e totais são indicadores agregados do EA20.

O cache do mapa usa ETag e detecta alterações dos consolidados; uma simples consulta HTTP 304 não altera os votos. Veja [geografia](docs/geography.md) para códigos municipais e malhas.

```sh
pdm run test
```

Os testes usam servidor HTTP local e bancos temporários. Para testes e build do frontend, use Node.js pelo ambiente `fnm` e os comandos de `frontend/package.json`.

As evidências em `docs/implementation/` e os planos antigos em `docs/superpowers/` registram versões anteriores; não definem a operação atual.
