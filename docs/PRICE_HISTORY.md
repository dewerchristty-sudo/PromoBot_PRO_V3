# Histórico real de preços

O Score permanece conservador enquanto não há observações reais suficientes em
datas distintas. Repetir uma coleta várias vezes no mesmo dia não substitui a
passagem do tempo e não aumenta artificialmente a confiança.

Defaults:

- 5 observações válidas;
- pelo menos 3 dias distintos;
- intervalo mínimo de 60 minutos;
- duplicatas iguais ignoradas por 60 minutos;
- estabilidade avaliada após 7 dias;
- variações superiores a 50% ficam como outlier até revisão;
- queda mínima de 2% e R$ 1,00 para ser considerada real.

## Coleta manual

No PowerShell, na raiz do PromoBot:

```powershell
.\.venv\Scripts\Activate.ps1
python -m scripts.collect_price_history --store mercado_livre --product-key MLB50957106
python -m scripts.inspect_price_history --product-key MLB50957106
```

Para validar sem gravar uma observação:

```powershell
python -m scripts.collect_price_history --store mercado_livre --product-key MLB50957106 --dry-run
```

Faça no máximo uma coleta planejada por período e repita em dias diferentes.
Não altere datas, não crie preços e não reduza os requisitos. Quando houver
histórico suficiente, os mesmos campos já consumidos pelo Offer Score receberão
evidência real (`historical_minimum`, referência histórica e desconto
verificado). O grupo piloto só poderá avançar se o produto atingir o Threshold
pelas regras normais.

Nenhum desses comandos chama Notifier, WhatsApp, Evolution, Scheduler ou
Canary.
