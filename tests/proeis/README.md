# Dataset de captcha PROEIS

Esta pasta e um laboratorio isolado. Nada aqui e usado pela automacao principal.

## Por que existem dois modos

`Gerar Nova Imagem` gera novas imagens de captcha, mas nao entrega a resposta correta.
Para treinar um modelo, precisamos de imagem + resposta.

Para um captcha ser considerado **validado pelo PROEIS**, o script precisa:

1. carregar o captcha em uma sessao nova;
2. obter uma resposta candidata;
3. enviar login/senha/captcha ao PROEIS;
4. salvar a imagem e o rotulo somente se o PROEIS aceitar o login.

## Scripts

- `collect_refresh_images.py`: coleta imagens sem rotulo, usando `Gerar Nova Imagem`.
- `collect_validated_2captcha.py`: coleta imagem + resposta validada pelo PROEIS, usando 2captcha como candidato.

## Exemplos

Coletar 100 imagens sem rotulo:

```powershell
py tests\proeis\collect_refresh_images.py --count 100
```

Coletar 100 captchas rotulados e validados pelo PROEIS:

```powershell
py tests\proeis\collect_validated_2captcha.py --target 100
```

O segundo modo consome creditos do 2captcha e faz tentativas reais de login no PROEIS.
