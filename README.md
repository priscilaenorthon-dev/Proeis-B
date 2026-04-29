# PROEIS Bot - Automacao Local

Bot local para consultar e marcar vagas no sistema PROEIS com interface grafica, agendamento por horario e captcha resolvido pelo 2captcha.

## Requisitos

- Windows 10 ou 11
- Python 3.12 ou superior
- Conta ativa no PROEIS
- Conta no 2captcha com creditos

## Instalacao

1. Baixe ou extraia a pasta do projeto.
2. Renomeie `.env.example` para `.env`.
3. Preencha suas credenciais no arquivo `.env`:

```env
PROEIS_LOGIN=seu_numero_de_matricula
PROEIS_PASSWORD=sua_senha
TWOCAPTCHA_API_KEY=sua_chave_do_2captcha
```

4. Execute `instalar.bat`.

O instalador verifica o Python, instala as dependencias do `requirements.txt` e abre o painel ao final.

## Dependencias

As dependencias oficiais ficam em `requirements.txt`:

- `requests`: chamadas HTTP para PROEIS e 2captcha
- `beautifulsoup4`: leitura das paginas HTML
- `truststore`: usa os certificados do Windows para reduzir erro de SSL em rede corporativa

O OCR local foi removido. O sistema usa somente 2captcha.

Quando o 2captcha retorna respostas invalidas repetidas para a mesma imagem, o bot tenta gerar uma nova imagem de captcha no PROEIS antes de continuar. O padrao e trocar a imagem depois de 2 respostas invalidas seguidas.

## Como abrir

Use:

```bat
abrir_painel.bat
```

Se `python` nao estiver no PATH, o arquivo tenta usar `py`.

## Campos principais

| Campo | Funcao |
|---|---|
| Convenio | Convenio/batalhao desejado |
| Data do Evento | Data especifica ou vazio para varrer datas disponiveis |
| CPA | CPA desejado |
| Tipo de vaga | `reserva` ou `nao-reserva (Titular)` |
| Quantidade | Quantidade de vagas que o bot deve tentar marcar |

## Botoes

| Botao | Funcao |
|---|---|
| Consultar Filtros | Consulta vagas com os filtros atuais sem clicar em Eu Vou |
| Marcar | Tenta marcar vagas clicando em Eu Vou |
| Listar Vagas | Varre as datas disponiveis do convenio/CPA e mostra tudo encontrado |
| Cancelar | Interrompe a execucao atual |
| Salvar como padrao | Salva os filtros para a proxima abertura |
| Limpar lista | Limpa a tabela de vagas |
| Limpar log | Limpa o log exibido na tela |

## Tabela de vagas

A aba `Vagas Encontradas` mostra:

- Data do Evento
- Nome do Evento
- Hora
- Turno
- Endereco
- Disponivel
- Acao

A coluna `Acao` indica se a linha foi apenas visualizada ou se o bot clicou em `Eu Vou`.

## Agendamento automatico

Quando `Agendar execucao automatica` estiver marcado:

1. O bot faz login antes do horario configurado.
2. No horario exato, inicia a marcacao.
3. Se a Data do Evento estiver vazia, ele varre as datas disponiveis.
4. A varredura tenta completar a quantidade configurada.

Com Data do Evento vazia, a logica de varredura e:

- Consulta as datas em ordem.
- Como o CPROEIS deixa exibir/marcar apenas um servico por dia, apos confirmar uma vaga o bot avanca para a proxima data.
- Se nao houver vaga compativel na data atual, tambem avanca para a proxima data.
- Se chegar ao fim das datas sem completar a quantidade, faz uma segunda varredura desde o inicio.
- Se ainda assim nao completar, para com a quantidade que conseguiu marcar e registra no log.

Essa regra vale somente para `Marcar` e `Agendar execucao automatica`. `Consultar Filtros` e `Listar Vagas` continuam apenas consultando/listando as vagas encontradas.

Se `Data do Evento` estiver preenchida e `Quantidade` for maior que 1, essa data sera usada como data inicial: depois da primeira marcacao confirmada, o bot procura as proximas vagas em datas posteriores.

## Logs e tempo

O sistema mostra o tempo de execucao na tela e grava logs em `logs/`.

Arquivos de log comuns:

- `*_gui.log`: log da interface
- `*_http.log`: log da automacao HTTP

## Estrutura dos arquivos

```text
PROEIS-Bot/
  abrir_painel.bat
  instalar.bat
  proeis_gui.py
  proeis_http.py
  timing_utils.py
  requirements.txt
  .env.example
  config/
    proeis_options.json
  tests/
```

O arquivo `.env` guarda credenciais locais e nao deve ser enviado ao GitHub.

## Testes

A pasta `tests` nao e obrigatoria para usar o sistema, mas ajuda a validar mudancas.

Para rodar:

```powershell
py -m unittest discover tests
```

## Problemas comuns

| Problema | O que verificar |
|---|---|
| Python nao encontrado | Execute `instalar.bat` ou instale Python manualmente |
| Erro ao instalar dependencia | Verifique internet, proxy ou bloqueio corporativo |
| Captcha recusado | Verifique saldo no 2captcha e tente novamente |
| 2captcha retorna respostas curtas | O bot tenta gerar nova imagem apos respostas invalidas repetidas |
| Login recusado | Teste login e senha manualmente no site PROEIS |
| Nenhuma vaga encontrada | Use Data do Evento vazia ou clique em Listar Vagas |
| Erro SSL/rede | Confirme que `truststore` esta instalado pelo `requirements.txt` |
