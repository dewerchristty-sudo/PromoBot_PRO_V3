# Agendador de coleta de preços

O agendador executa exclusivamente a coleta real de preços. Ele não importa nem
chama Notifier, WhatsApp, Evolution, Scheduler de ofertas, Canary ou grupo
piloto.

Por padrão está desativado. Para preparar uma execução agendada, revise
manualmente as variáveis `PRICE_COLLECTION_*` documentadas no `.env.example` e
defina `PRICE_COLLECTION_ENABLED=True` no `.env`.

Iniciar:

```powershell
.\.venv\Scripts\Activate.ps1
python -m scripts.run_price_scheduler
```

O terminal mostra o próximo horário em `America/Sao_Paulo`. Cada sessão é
finita: executa no máximo a quantidade de horários configurados e encerra.

Parar antes disso:

```text
Ctrl+C
```

Executar uma única coleta imediata:

```powershell
python -m scripts.run_price_scheduler --once
```

Falhas recuperáveis recebem no máximo uma tentativa adicional após o intervalo
configurado. CAPTCHA, perda de sessão, banco ou navegador indisponível são
registrados nos relatórios e não provocam loop infinito.

Relatórios ficam em `reports/collector_scheduler/`.
