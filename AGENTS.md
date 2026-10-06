# Instruções de desenvolvimento

## Escopo e fontes

Este projeto coleta resultados oficiais agregados EA20 do TSE para o ciclo `ele2026`, mantém os consolidados atuais em SQLite e oferece API e dashboard. A navegação abrange Brasil, UF, município e zona. Os cargos e suas abrangências são descobertos no catálogo oficial, incluindo conselho distrital quando disponível.

- EA11 fornece eleições, cargos e templates de caminhos; EA12 fornece abrangências; EA20 fornece candidatos, votos e progresso oficial.
- Preserve a identidade completa: dataset, eleição/turno, cargo e circunscrição. Um número de candidato isolado não identifica a candidatura.
- Preserve zeros à esquerda: município TSE com cinco dígitos e zona com quatro. Códigos TSE e IBGE são distintos; use o relacionamento explícito da geografia.
- Presidente tem circunscrição nacional; cargos estaduais usam UF; cargos municipais usam UF e município.
- Resultados indisponíveis têm votos desconhecidos, não zero. Mantenha separados votos nominais, de legenda, brancos, nulos e demais categorias informadas.
- Totais de seções e seções totalizadas são métricas do EA20, não evidência de download de boletins individuais.

## Ambiente e execução

- Antes de trabalhar, leia `AGENTS.md` ou `Agents.md` aplicável.
- Use UTF-8 e preserve acentos e Unicode em português. ASCII é apropriado apenas para IDs, slugs, URLs e requisitos técnicos explícitos.
- Use PDM para Python 3.11+ e dependências. Para Node.js, use o ambiente instalado do `fnm`.
- Comandos usuais: `pdm install`, `pdm run test`, `pdm run collect --once --uf ac`, `pdm run collect`, `pdm run api`.
- Testes automatizados usam HTTP local e bancos temporários. Uma validação real no TSE deve ser limitada e respeitar o cooldown existente.

## Organização

- `apuracao/collector/cli.py`: argumentos e ponto de entrada.
- `apuracao/collector/config.py`: leitura e validação do TOML.
- `apuracao/collector/service.py`: execução dos ciclos e endpoints fixos.
- `apuracao/collector/http.py`: requisições, validação condicional, consolidados e limite de requisições.
- `apuracao/collector/client.py`: catálogo eleitoral, templates de URL, identidade de fase e pausa persistente.
- `apuracao/collector/results.py`: descoberta e execução da coleta EA20 por nível.
- `apuracao/collector/result_schedule.py`: prioridades territoriais e progresso das passagens.
- `apuracao/database.py`, `schema.sql`: abertura e inicialização do banco.
- `apuracao/metadata_store.py`: catálogo restrito a 2026 e geografia.
- `apuracao/official_store.py`: atualização transacional dos consolidados.
- `apuracao/official.py`: interpretação e consultas de resultados oficiais atuais e regiões.
- `apuracao/api/`: API de leitura, consultas do dashboard, geografia e cache dos mapas.
- `frontend/`: dashboard React/TypeScript. Operação em `docs/dashboard.md`.
- `docs/collection.md`: regras de agendamento, persistência e limites da coleta.

## Persistência e operação

- Guarde apenas o consolidado atual, com URL, hash, instante da coleta e horário fornecido pela fonte. Não armazene snapshots nem JSON integral.
- Uma resposta válida substitui os votos do recorte atomicamente. Respostas idênticas não recriam os votos.
- Use transações para alterações relacionadas. Preserve bancos existentes e dados já coletados; arquivos em `data/` não são fixtures descartáveis.
- Migrações criam outro arquivo e preservam o banco original. O banco ativo contém somente os consolidados EA20 de 2026.
- A identidade do payload deve corresponder ao recorte solicitado, incluindo eleição, turno, fase, cargo e abrangência. Rejeite divergências sem substituir o último consolidado válido. Uma resposta 304 só conclui a tentativa se a identidade persistida for válida.
- Marque `results.completed` somente com votos disponíveis e contagens válidas iguais de seções totalizadas e totais, com total positivo. Ignore recortes completos em coletas futuras; não propague a conclusão para filhos, cargos ou turnos distintos.
- A ordem da passagem é Brasil → UFs → municípios → zonas, pulando níveis desativados em `[results.levels]`. Retome recortes pendentes sem repetir os concluídos na mesma passagem.
- Municípios: UFs com menos municípios distintos primeiro. Zonas: total municipal decrescente para a mesma eleição e cargo; ausência de total fica depois de zero.
- Falhas ficam pendentes; 403, 404 e 429 interrompem o ciclo e persistem o cooldown. Preserve esse estado em reinícios e respeite o limite configurado. A operação pressupõe um coletor por banco.
- O intervalo entre ciclos não garante atualização nacional completa. Mostre horários, pendências e indisponibilidade com fidelidade à fonte.
- Mantenha dados sintéticos restritos a testes ou demonstrações identificadas. Ao alterar formatos ou endpoints externos, confira a documentação oficial e registre limitações.

## Testes

- Alterações no código de produção, por si só, não exigem novos testes.
- Adicione ou modifique testes quando protegerem comportamento observável relevante, uma invariante ou fronteira não trivial, ou uma regressão concreta.
- Antes de adicionar um teste, identifique a regressão realista que ele detectaria e por que a cobertura existente não a detecta.
- Não crie testes apenas por cobertura, simetria ou porque o código mudou.
- Não crie testes cujo único propósito seja garantir que código, rotas, campos ou funcionalidades removidos continuem ausentes.
- Testes negativos são apropriados quando a falha ou ausência integra um contrato atual de API, segurança ou persistência.
- Evite testes que apenas reproduzam valores literais, mapeamentos declarativos, fluxo óbvio ou detalhes de implementação.
- Para diagnósticos e saídas estruturadas visíveis ao usuário, prefira a cobertura de interface, snapshots ou integração já estabelecida, em vez de asserções redundantes sobre fragmentos de texto.
- Prefira ampliar um teste existente na fronteira de comportamento adequada a criar novos arquivos, fixtures, helpers ou abstrações exclusivas de teste.
- Não crie infraestrutura de testes mais complexa ou frágil que o comportamento protegido.
- Ao corrigir um bug real, acrescente cobertura focada de regressão no nível em que ele foi observado, quando viável.
- Evite endurecimento excessivo para falhas hipotéticas. Priorize riscos realistas.
- Mantenha os testes automatizados independentes da disponibilidade do TSE. Use o servidor HTTP local e bancos temporários existentes quando forem adequados.
- Execute as verificações pertinentes e confirme seus resultados antes de declarar uma alteração validada. Para alterações apenas documentais, a leitura e conferência do conteúdo podem ser suficientes.

## Comentários e documentação

- Não adicione comentários que apenas repitam o código, o nome de um símbolo, o nome de um teste, a finalidade óbvia de um módulo ou o fluxo de controle.
- Prefira nomes claros e boa estrutura a comentários explicativos desnecessários.
- Use comentários para explicar motivos não óbvios, invariantes, restrições de segurança, requisitos de compatibilidade, particularidades externas ou por que uma alternativa mais simples seria incorreta.
- Mantenha os comentários corretos e remova os que ficaram desatualizados.
- Quando documentação pública de API for necessária, descreva contrato, semântica, erros, invariantes e exemplos úteis; não apenas parafraseie a assinatura.
- Atualize a documentação operacional quando comandos, formatos, contratos ou limitações mudarem. Não transforme contagens momentâneas de candidatos ou seções em regras permanentes.
