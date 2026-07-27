# Motor de Inteligência de Ofertas

A Sprint 18 adiciona uma camada analítica, somente de leitura, sobre as
observações válidas do histórico real de preços.

Ela calcula estatísticas, volatilidade, tendência, frequência de movimentos,
tempos desde eventos relevantes, estabilidade, confiança e raridade. Valores
que ainda não possuem amostra suficiente são apresentados como `null`, sem
estimativas artificiais.

## Estados

- `UNKNOWN`: não existe histórico válido.
- `INSUFFICIENT_HISTORY`: existe somente uma observação.
- `BUILDING_HISTORY`: a amostra ainda está sendo formada.
- `STABLE`: histórico maduro ou baixa volatilidade.
- `HIGH_CONFIDENCE` e `LOW_CONFIDENCE`: confiança estatística da amostra.
- `RARE_PRICE` e `COMMON_PRICE`: posição do preço atual na distribuição.

Um produto possui um estado principal de maturidade e pode apresentar estados
complementares no campo `states`.

## Inspeção

```powershell
python -m scripts.inspect_offer_intelligence --product-key MLB50957106
```

Os relatórios são gravados em `reports/offer_intelligence/`.

## Isolamento operacional

A camada não importa nem chama Offer Score, Scheduler, Pilot,
AffiliateManager, Notifier, WhatsApp ou Evolution. O campo
`operational_effect` permanece `NONE`. Nenhuma métrica desta Sprint é
consumida por uma decisão operacional.
