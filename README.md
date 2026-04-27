# PROEIS Bot — Automação de Marcação

Bot para marcação automática de vagas no sistema PROEIS com interface gráfica, agendamento por horário e resolução automática de captcha.

---

## Requisitos

- Windows 10 ou 11
- Conta ativa no [PROEIS](https://www.proeis.rj.gov.br)
- Conta no [2captcha.com](https://2captcha.com) com créditos (serviço pago, baixo custo)

---

## Instalação

### 1. Baixe os arquivos

Clique em **Code → Download ZIP** nesta página, extraia a pasta em qualquer lugar do seu computador.

### 2. Configure suas credenciais

Dentro da pasta extraída, localize o arquivo `.env.example`.

- **Renomeie** para `.env`
- Abra com o Bloco de Notas e preencha:

```
PROEIS_LOGIN=seu_numero_de_matricula
PROEIS_PASSWORD=sua_senha
TWOCAPTCHA_API_KEY=sua_chave_do_2captcha
```

> **Como obter a chave do 2captcha:**
> 1. Acesse [2captcha.com](https://2captcha.com) e crie uma conta
> 2. Adicione créditos (alguns centavos por captcha)
> 3. Vá em **Dashboard → API Key** e copie sua chave

### 3. Instale as dependências

Clique duas vezes em **`instalar.bat`**.

O instalador vai:
- Verificar se Python está instalado (instala automaticamente se não tiver)
- Instalar os pacotes necessários (`requests`, `beautifulsoup4`)
- Abrir o painel automaticamente ao terminar

---

## Como usar

Abra **`abrir_painel.bat`** (ou use o `instalar.bat` que já abre ao final).

### Painel principal

| Campo | Descrição |
|---|---|
| **Convênio** | Selecione seu batalhão/convênio |
| **Data do Evento** | Data específica (DD/MM/AAAA) ou vazio para varrer todas |
| **CPA** | Selecione seu CPA |
| **Tipo de vaga** | `reserva` ou `nao-reserva` |
| **Quantidade** | Quantas vagas deseja marcar |

### Botões

| Botão | O que faz |
|---|---|
| **Testar** | Busca e lista as vagas disponíveis **sem confirmar** nada |
| **Marcar** | Encontra a vaga e clica em **Eu Vou** automaticamente |
| **Cancelar** | Para a execução ou cancela o agendamento |
| **Salvar como padrão** | Salva os filtros atuais para próximas sessões |

### Aba Vagas Encontradas

Mostra todas as vagas disponíveis em uma tabela com Nome, Hora, Turno, Endereço e Disponibilidade.
- Verde = vaga de **reserva**
- Azul = vaga **normal**

### Aba Log de Execução

Mostra em tempo real tudo que o bot está fazendo: login, captcha, navegação, resultado.
Cada execução salva um arquivo de log na pasta `logs/`.

---

## Agendamento automático

Para o bot rodar sozinho em um horário específico:

1. Marque a caixa **"Agendar execucao automatica"**
2. Preencha a **Data de inicio** e o **Horario de inicio**
3. Clique em **Marcar**
4. Confirme — o painel mostra a contagem regressiva
5. **Deixe o computador ligado** até o horário

> O bot faz login **90 segundos antes** do horário marcado para já estar autenticado e pronto para marcar no segundo exato.

---

## Estrutura dos arquivos

```
PROEIS-Bot/
├── abrir_painel.bat          # Abre o sistema
├── instalar.bat              # Instala dependências e abre o painel
├── proeis_gui.py             # Interface gráfica
├── proeis_http.py            # Automação HTTP e captcha
├── .env.example              # Modelo de configuração (renomeie para .env)
├── .env                      # Suas credenciais (NAO sobe ao GitHub)
└── config/
    └── proeis_options.json   # Lista de convênios e CPAs
```

---

## Observações

- O arquivo `.env` **nunca é enviado ao GitHub** — suas credenciais ficam só no seu computador
- Logs ficam em `logs/` (também ignorados pelo GitHub)
- O captcha é resolvido automaticamente via 2captcha — cada resolução custa frações de centavo
- Para marcar múltiplas vagas, aumente a **Quantidade** — o bot repete o ciclo até completar

---

## Problemas comuns

| Problema | Solução |
|---|---|
| `python` não reconhecido após instalar | Feche e reabra o `instalar.bat` |
| Captcha rejeitado repetidamente | Verifique o saldo na conta 2captcha |
| Login recusado | Confirme login e senha no site PROEIS manualmente |
| Nenhuma vaga encontrada | Tente com a data vazia para varrer todas as datas |
