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

## Interface local

Há uma interface local para escolher a data, informar termos opcionais e ver
os PDFs e textos de ocorrência salvos. Ela não inicia uma coleta sozinha.

```powershell
python web/server.py
```

Abra `http://127.0.0.1:8000` no navegador. Deixe as palavras-chave em branco
para usar `config.KEYWORDS`; uma palavra por linha substitui essa lista apenas
na coleta atual. A opção **Mostrar o navegador** executa a coleta com
`--headed`.

O servidor só atende o endereço local e executa `main.py` em um processo filho
sem usar shell. Enquanto a coleta estiver ativa, a página mostra o andamento,
o tempo decorrido e o horário do último log; ela também atualiza a lista de
arquivos da data selecionada. PDFs abrem no navegador e os
arquivos `.txt` em `ocorrencias` exibem as páginas encontradas.

## Verificação

```powershell
python -m unittest -v
```
