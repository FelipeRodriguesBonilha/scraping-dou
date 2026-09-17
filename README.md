# scraping-dou

Scrapers dos Diários Oficiais estaduais para pesquisar todas as palavras em
`config.KEYWORDS` usando texto exato, baixar as edições públicas encontradas e
registrar suas páginas de ocorrência em arquivos de texto. Na BA e em SE, onde
o download não é público nas mesmas condições da leitura, o sistema registra os
trechos encontrados e o link do leitor oficial sem tentar cadastrar usuário ou
efetuar pagamento.

## Instalação

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Uso

```powershell
python main.py
```

Por padrão, a busca usa a data atual definida em `config.DATE`, roda sem abrir
uma janela e grava os arquivos nesta estrutura. Cada edição repetida na mesma
busca é consolidada em um único PDF:

```text
downloads/{UF}/{YYYY-MM-DD}/{palavra-chave}/pdf/{nome-do-diário}.pdf
downloads/{UF}/{YYYY-MM-DD}/{palavra-chave}/ocorrencias/{nome-do-diário}__ocorrencias.txt
```

Cada edição gera, no máximo, um PDF e um relatório `.txt`. Mesmo quando o
portal entrega uma página de ocorrência por vez, todas as páginas daquela
edição são reunidas no mesmo relatório, ordenadas pelo número da página.
Quando duas *edições diferentes* tiverem o mesmo nome remoto, os arquivos
recebem os sufixos `-2`, `-3` e assim por diante. PDFs digitalizados sem camada
de texto não permitem identificar as páginas de ocorrência sem OCR. BA e SE
geram somente o arquivo em `ocorrencias`, com os trechos e o endereço da leitura
pública.

Quando um portal não oferece filtro de data no próprio servidor, o scraper
confere a data exibida no resultado (ou na URL oficial da edição) antes de
baixar. Portanto, os arquivos gravados correspondem somente à data configurada.

Alguns exemplos úteis:

```powershell
python main.py --date 10/08/2026
python main.py --keyword "vistoria veicular" --state AC --state PR
python main.py --headed
```

O primeiro comando usa outra data; o segundo restringe a busca a uma palavra e
duas UFs; o terceiro mostra o navegador.

## Cobertura

| Modalidade | UFs |
| --- | --- |
| PDF do portal e relatório de ocorrências | AC, AL, AM, AP, CE, DF, ES, GO, MA, MG, MS, MT, PA, PB, PE, PI, PR, RJ, RN, RO, RR, RS, SC, SP e TO |
| Leitura pública e relatório de ocorrências, sem download do PDF | BA e SE |

BA e SE são pesquisados sem login pelo leitor público. Para essas UFs, o
sistema grava um arquivo `.txt` com as páginas encontradas, os trechos e o link
oficial de leitura. Em SE, o download oferecido pelo portal exige cadastro e
pagamento. A eventual cobrança para download na BA ainda está em verificação.

No RJ, o scraper obtém o documento integral carregado pelo visualizador e
confere a quantidade de páginas antes de salvá-lo. PE usa a busca pública da
CEPE.

## Roteiro de validação

Entre 15 e 17/09/2026, a busca por `Detran` em `2026-06-02` foi executada nos portais
incluídos ou corrigidos nesta alteração:

```powershell
python main.py --state UF --date 2026-06-02 --keyword Detran
```

| UF | Resultado observado |
| --- | --- |
| BA | relatório `.txt`, ocorrências nas páginas 5 e 6 e link para leitura HTML |
| CE | dois cadernos completos, com 76 e 60 páginas, e relatórios de ocorrências |
| ES | edição completa de 99 páginas e relatório de ocorrências |
| GO | edição completa de 79 páginas e relatório de ocorrências |
| MG | edição completa de 105 páginas e relatório de ocorrências |
| MS | edição completa de 319 páginas e relatório de ocorrências |
| PB | edição completa de 60 páginas e relatório de ocorrências |
| RJ | dois cadernos completos, com 6 e 61 páginas, e relatórios de ocorrências |
| RN | edição completa de 52 páginas e relatório de ocorrências |
| RO | edição completa de 369 páginas e relatório de ocorrências |
| SC | edição completa de 94 páginas e relatório de ocorrências |
| SE | relatório `.txt`, ocorrência na página 55 e link para leitura no Flip |
| SP | dez PDFs completos conferidos; cinco com ocorrências, de 126, 199, 311, 25 e 113 páginas |

Após a execução geral de 17/09/2026, as três UFs que haviam falhado foram
revalidadas. MA concluiu as cinco palavras padrão e teve PDFs e relatórios
confirmados em buscas com resultados. MS consultou a edição principal de 149
páginas e o suplemento de 268 páginas da data, pesquisando todos os termos no
texto integral em uma única passagem; uma busca separada por `Detran` confirmou
ocorrências em ambos. SP consultou seis PDFs completos nas quatro seções
indicadas pela busca das palavras padrão; cinco continham `vistoria`. AC passou
a resumir as edições fora da data, e PI teve PDF e relatório confirmados sem a
navegação inicial desnecessária.

As demais UFs mantêm as combinações de validação abaixo. Use o mesmo comando,
trocando data e palavra-chave, para repeti-las.

| UF | Data | Palavra-chave |
| --- | --- | --- |
| AC | 2026-08-12 | vistoria |
| AL | 2026-08-12 | vistoria |
| AM | 2026-08-11 | governo |
| AP | 2026-08-11 | vistoria |
| DF | 2026-08-12 | vistoria |
| MA | 2026-08-11 | portaria |
| MT | 2026-08-11 | portaria |
| PA | 2026-06-29 | governo |
| PE | 2026-08-12 | detran |
| PI | 2026-03-13 | vistoria |
| PR | 2026-08-11 | portaria |
| RR | 2025-08-12 | vistoria |
| RS | 2026-08-11 | portaria |
| TO | 2026-08-11 | vistoria |

## Interface web e publicação

A interface permite escolher a data, informar termos opcionais e ver os PDFs e
textos de ocorrência salvos. Ela executa as coletas sem abrir o navegador no
servidor.

Antes de iniciá-la, defina um usuário e uma senha em variáveis de ambiente. Não
inclua a senha em `config.py`, no repositório ou em arquivos públicos.

```powershell
$env:DOU_WEB_USERNAME = "alfa"
$env:DOU_WEB_PASSWORD = "troque-por-uma-senha-forte-e-unica"
python web/server.py
```

Abra `http://127.0.0.1:8000` no navegador e informe essas credenciais quando
solicitado. A autenticação protege a página, a API e os arquivos baixados.
Deixe as palavras-chave em branco para usar `config.KEYWORDS`; uma palavra por
linha substitui essa lista apenas na coleta atual.

Para desenvolvimento local sem senha, use explicitamente
`python web/server.py --no-auth`. Essa opção só funciona em endereços locais e
não pode ser usada ao expor o serviço na rede.

Para publicar, use a configuração Docker incluída neste projeto. Ela mantém a
porta do Python fora da internet, persiste os resultados e usa o Caddy para
HTTPS. A autenticação Basic só protege a senha em trânsito quando a conexão
externa usa HTTPS.

Enquanto a coleta estiver ativa, a página mostra o andamento, o tempo decorrido
e o horário do último log; ela também atualiza a lista de arquivos da data
selecionada. PDFs abrem no navegador e os arquivos `.txt` em `ocorrencias`
exibem as páginas encontradas.

### Retenção automática dos resultados

Não é necessário configurar um cron no host ou no EasyPanel. Enquanto a
interface estiver em execução, ela limpa o volume `downloads` ao iniciar e
diariamente às 03:15, no horário de Brasília. Por padrão, são preservadas as
últimas 15 datas-calendário, incluindo hoje; por exemplo, em 14/08 são mantidos
os resultados de 31/07 a 14/08 e as pastas até 30/07 são removidas.

A remoção é feita pela pasta completa da edição (`UF/AAAA-MM-DD`), portanto PDF
e relatório de ocorrências são apagados juntos. Diretórios com nomes fora do
formato de data e links simbólicos são ignorados. Caso uma coleta esteja em
andamento para uma data antiga, essa data é preservada até a próxima limpeza.

Para mudar a janela, defina `DOU_RETENTION_DAYS` entre 1 e 365 no EasyPanel ou
no `.env` do Docker. O padrão já é 15. Para pré-visualizar manualmente o que
seria excluído, sem apagar nada:

```bash
python cleanup_downloads.py --keep-days 15
```

Use `--apply` apenas quando quiser executar a remoção manualmente.

### Publicação com Docker em uma VPS

A configuração de produção usa esta arquitetura:

```text
Internet HTTPS -> Caddy (portas 80/443) -> interface Python (rede Docker)
                                                 |
                                          volume `downloads`
```

A porta `8000` não é publicada no host: somente o Caddy recebe tráfego externo.
Antes da instalação, crie um registro DNS `A` (por exemplo,
`dou.seudominio.com`) apontando para o IP público da VPS. Se houver um registro
`AAAA`, ele também deve apontar corretamente para a VPS ou ser removido. Libere
as portas TCP `22`, `80` e `443` no firewall da Hostinger e da VPS; **não abra a
porta 8000**.

Em uma VPS Ubuntu, instale o Docker Engine e o plugin Docker Compose conforme a
[documentação oficial do Docker](https://docs.docker.com/engine/install/ubuntu/).
Depois, execute:

```bash
git clone https://github.com/FelipeRodriguesBonilha/scraping-dou.git
cd scraping-dou
cp .env.example .env
nano .env
```

No `.env`, informe o domínio público e um e-mail para os avisos de renovação do
certificado:

```dotenv
DOU_DOMAIN=dou.seudominio.com
ACME_EMAIL=infra@seudominio.com
```

Crie as credenciais da interface fora do Git. Elas são montadas como segredos
somente no container da aplicação:

```bash
sudo install -d -m 700 secrets
sudo nano secrets/dou_web_username
sudo nano secrets/dou_web_password
sudo chmod 600 secrets/dou_web_username secrets/dou_web_password
```

Use uma senha longa e exclusiva. Em seguida, valide e inicie os containers:

```bash
sudo docker compose config --quiet
sudo docker compose build --pull
sudo docker compose up -d --remove-orphans
sudo docker compose ps
sudo docker compose logs -f scraping-dou caddy
```

Com o DNS e as portas `80`/`443` ativos, o Caddy emite e renova o certificado
HTTPS automaticamente. Abra `https://dou.seudominio.com` e entre com o usuário
e a senha criados acima. Os PDFs continuam no volume Docker `downloads`, mesmo
se o container for recriado.

Para atualizar a aplicação na VPS:

```bash
git pull --ff-only
sudo docker compose build --pull
sudo docker compose up -d --remove-orphans
```

Para trocar a senha, altere o arquivo `secrets/dou_web_password` e recrie apenas
o serviço da aplicação:

```bash
sudo docker compose up -d --force-recreate scraping-dou
```

O Chromium roda sem interface gráfica no container. A imagem instala a mesma
versão do navegador exigida pelo `playwright` do projeto e executa a coleta como
usuário sem privilégios. Veja também a [documentação do Playwright para
Docker](https://playwright.dev/python/docs/docker) e a [documentação do Caddy
sobre HTTPS automático](https://caddyserver.com/docs/automatic-https).

## Verificação

```powershell
python -m compileall -q main.py scrapers web cleanup_downloads.py
python main.py --help
```
