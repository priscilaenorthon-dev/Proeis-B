# Laboratorio de captcha

Este material fica dentro de `tests/` para estudar melhorias sem alterar o sistema original.

## Log analisado

Arquivo: `logs/20260427_145039_gui.log`

O erro ocorreu na consulta da data `2026-04-28`.

Sequencia observada:

- Login: primeira resposta fora do padrao, segunda resposta valida: `7212FD`.
- Consulta de `2026-04-27`: resposta valida: `3BFEDB`.
- Consulta de `2026-04-28`: cinco respostas fora do padrao e a sexta invalida: `9C277`.

O bot fez certo ao rejeitar respostas com menos de 6 caracteres, porque o captcha do PROEIS tem 6 caracteres alfanumericos.

## Gargalo

O gargalo principal e a espera por respostas invalidas do 2captcha.

Quando o servico devolve `B`, `8` ou `9C277`, o sistema precisa reenviar outro captcha e esperar novamente.

## Ideia mais promissora

### Opcao A: envio paralelo controlado para o 2captcha

1. Enviar 2 ou 3 solicitacoes do mesmo captcha.
2. Usar a primeira resposta valida com 6 caracteres.
3. Reportar como ruim as respostas invalidas.
4. Cancelar/ignorar as respostas atrasadas.

Vantagem: reduz o tempo quando uma parte das respostas vem invalida.

Desvantagem: aumenta o consumo de creditos, porque mais de uma solicitacao pode ser enviada para o mesmo captcha.

### Opcao B: trocar a imagem depois de respostas ruins

O site tem o controle:

```text
lnkNewCaptcha - Gerar Nova Imagem
javascript:__doPostBack('lnkNewCaptcha','')
```

Teste feito em `tests/refresh_proeis_captchas.py`:

- Foram geradas 10 imagens pela mesma tela de login.
- Resultado: 10 imagens unicas em 10 tentativas.
- Amostras salvas em `tests/captcha_refresh_samples/`.

Estrategia para testar depois no sistema real:

1. Enviar o captcha atual para o 2captcha.
2. Se voltar resposta invalida, tentar mais uma vez o mesmo captcha.
3. Se der duas invalidas seguidas, clicar/acionar `Gerar Nova Imagem`.
4. Enviar o captcha novo para o 2captcha.

Vantagem: evita gastar 6 tentativas no mesmo captcha que o 2captcha esta lendo mal.

Desvantagem: precisa validar tambem nas telas internas de filtro, porque o teste acima foi feito na tela publica `Default.aspx`.

## Arquivos criados

- `tests/captcha_lab.py`: simulador de estrategias.
- `tests/test_captcha_lab.py`: testes comparando tentativa sequencial e lote paralelo.
- `tests/capture_proeis_captchas.py`: coleta 10 captchas por carregamento da pagina.
- `tests/refresh_proeis_captchas.py`: testa o postback `lnkNewCaptcha` para gerar nova imagem.

Esses arquivos nao sao usados pelo bot. Servem apenas para estudar a estrategia antes de mexer no sistema real.
