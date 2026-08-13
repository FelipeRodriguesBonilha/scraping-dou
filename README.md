# scraping-dou

Scrapers dos Diários Oficiais estaduais para pesquisar todas as palavras em
`config.KEYWORDS` usando texto exato, baixar uma vez cada edição encontrada e
registrar suas páginas de ocorrência em arquivos de texto quando o PDF permitir
extração.

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
de texto permanecem em `pdf`, mas não podem ter suas páginas identificadas sem
OCR.

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

| Situação | UFs |
| --- | --- |
| Coleta pública | AC, AL, AM, AP, DF, MA, MT, PA, PE, PI, PR, RJ, RR, RS e TO |
| Login necessário | BA e SE |

PE usa a busca pública da CEPE. BA e SE são ignorados até que exista uma
integração de autenticação autorizada.

## Roteiro de validação

Estas combinações produziram pelo menos um PDF na validação de 12/08/2026.
Use `python main.py --state UF --date AAAA-MM-DD --keyword termo` para repetir
qualquer uma delas.

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
| RJ | 2026-08-11 | portaria |
| RR | 2025-08-12 | vistoria |
| RS | 2026-08-11 | portaria |
| TO | 2026-08-11 | vistoria |

BA e SE não aparecem no roteiro porque continuam dependendo de login.

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
python -m unittest -v
```
