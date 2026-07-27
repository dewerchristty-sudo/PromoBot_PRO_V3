# Scheduler Inteligente — ativação canary

O Scheduler Inteligente é opt-in. A configuração padrão mantém o PromoBot
inteiramente no fluxo legado:

```env
OFFER_INTELLIGENT_SCHEDULER_ENABLED=False
OFFER_COMPARE_WITH_LEGACY=True
OFFER_CANARY_PERCENT=0
OFFER_MIN_SCORE_TO_SEND=85
OFFER_MAX_SEND_PER_HOUR=3
OFFER_MAX_SEND_PER_DAY=12
OFFER_ENABLE_ROLLBACK=True
```

## Ativação recomendada

1. Mantenha `OFFER_INTELLIGENT_SCHEDULER_ENABLED=False` e valide o Dashboard.
2. Ative a flag com `OFFER_CANARY_PERCENT=0`. O envio ainda será 100% legado.
3. Avance gradualmente por 5%, 10%, 25%, 50%, 75% e 100%.
4. Observe comparações, diferenças, rollbacks e envios no Dashboard.
5. Para desligar instantaneamente, use:

```env
OFFER_INTELLIGENT_SCHEDULER_ENABLED=False
```

Não é necessário remover dados nem desfazer migrações.

## Seleção e segurança

O percentual é calculado de forma determinística pela identidade da oferta.
Assim, o mesmo produto não muda aleatoriamente de grupo entre ciclos.

Uma oferta atribuída ao Scheduler Inteligente precisa:

- possuir análise no banco inteligente;
- atingir o score mínimo;
- ter sido aprovada pelos filtros;
- não ser duplicada;
- respeitar os limites por hora e por dia.

Ofertas não selecionadas ou rejeitadas permanecem pendentes. O `Notifier`
legado continua sendo o único componente que acessa os canais de envio.

## Rollback

Falhas de decisão antes do transporte devolvem o lote completo ao Scheduler
legado. Falhas depois do início do transporte não provocam reenvio imediato,
evitando duplicidade em uma entrega parcial; elas seguem pela fila normal de
recuperação.

Cada decisão registra produto, loja, categoria, score, Scheduler responsável,
decisões legado e inteligente, diferenças, flags, percentual, resultado,
tempo e motivo de rollback.

