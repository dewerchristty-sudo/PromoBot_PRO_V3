# PromoBot_PRO_V3

Aplicativo desktop em Python para pesquisar produtos em lojas online, salvar os
resultados em SQLite e exportar a lista para CSV.

## Funcionalidades

- Busca principal em Mercado Livre, Amazon e Kabum.
- Lojas opcionais/experimentais: Terabyte, Americanas, Pichau, Magalu,
  Casas Bahia e Shopee.
- Salvamento automatico dos produtos encontrados em `promobot.db`.
- Dashboard com total de produtos, lojas e itens recentes.
- Tela de produtos com filtro, atualizacao, exportacao CSV e limpeza do banco.
- Filtros por faixa de preco, ordenacao por menor/maior preco e modo ofertas.
- Tela de ofertas com menor preco, coletas e queda estimada.
- Historico de preco por coleta para detectar baixas reais ao longo do tempo.
- Alertas de preco por termo e valor alvo.
- Notificacoes por Telegram e WhatsApp via webhook/API.
- Monitoramento automatico por termo e intervalo em minutos.
- Historico com resumo por loja e ultimos produtos salvos.
- Configuracao de tema da interface.
- Testes automatizados para banco e parser.

## Instalar

Crie e ative um ambiente virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Instale as dependencias:

```powershell
pip install -r requirements.txt
playwright install chromium
```

## Executar

```powershell
python main.py
```

## Testar

```powershell
python -m unittest discover -s tests -v
```

## Gerar executavel

```powershell
.\scripts\build_exe.ps1
```

O executavel sera criado em:

```text
dist\PromoBot_PRO_V3\PromoBot_PRO_V3.exe
```

## Criar atalho na area de trabalho

```powershell
.\scripts\create_shortcut.ps1
```

## Notificacoes

Copie `.env.example` para `.env` e preencha os dados do WhatsApp. Depois use
`Notificar agora` na tela Alertas. O envio por WhatsApp esta preparado para
Evolution API local, Z-API e webhook/API generico.

Para usar seu computador como servidor, rode a Evolution API localmente,
conecte o WhatsApp pelo QR Code e preencha:

```env
WHATSAPP_PROVIDER=evolution
EVOLUTION_API_URL=http://localhost:8080
EVOLUTION_INSTANCE=promobot
EVOLUTION_API_KEY=
WHATSAPP_PHONES=5511999999999,5527999999999
```

Use ate 10 numeros separados por virgula, sempre no formato `55 + DDD + numero`.

Depois de instalar o Docker Desktop, inicie a Evolution API local com:

```powershell
.\scripts\start_evolution.ps1
```

Para parar:

```powershell
.\scripts\stop_evolution.ps1
```

Para Z-API, crie uma instancia, conecte o WhatsApp pelo QR Code e preencha:

```env
WHATSAPP_PROVIDER=zapi
ZAPI_INSTANCE_ID=
ZAPI_INSTANCE_TOKEN=
ZAPI_CLIENT_TOKEN=
WHATSAPP_PHONES=5511999999999,5527999999999
```

## Scripts de inspecao manual

Os scripts em `scripts/` abrem o navegador para conferir seletores e diagnosticar
mudancas nas paginas das lojas:

```powershell
python scripts\inspect_kabum.py
python scripts\inspect_shopee.py
python scripts\validate_search.py "ssd 1tb"
python scripts\health_check.py "ssd 1tb"
```

Veja tambem [docs/LOJAS.md](docs/LOJAS.md) para prioridades de integracao.

## Observacoes

Scraping de e-commerce pode variar conforme bloqueios, layout da pagina e
disponibilidade da loja. Se uma loja falhar, o app registra o erro e continua a
busca nas demais.

Para gerar dados melhores de promocao, pesquise o mesmo produto mais de uma vez
ao longo do tempo. O app atualiza o produto pelo link e registra cada preco na
tabela `historico_precos`.

Use a tela Monitor para cadastrar buscas recorrentes. O monitor usa as lojas
confiaveis por padrao e salva cada coleta no historico.

Para monitorar varios tipos de produto, use o botao `Categorias padrao` na tela
Monitor. Ele cadastra termos amplos como notebook, smartphone, TV, air fryer,
geladeira, fone bluetooth, monitor gamer, placa de video e outros.

Validacao real feita com `ssd 1tb`:

- Mercado Livre: retornando resultados.
- Amazon: retornando resultados.
- Kabum: retornando resultados.
- Terabyte: integrada para busca em hardware e promocoes gamer.
- Americanas: retornando resultados.
- Pichau: retornou manutencao/bloqueio temporario.
- Magalu: retornou erro 403.
- Casas Bahia: pagina abriu, mas retornou nenhum produto para os termos testados.
- Shopee: a pagina/API retornou bloqueio ou HTML vazio no ambiente de teste.
