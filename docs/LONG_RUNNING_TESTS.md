# Testes de estabilização temporal

Esta bateria simula dias de operação usando exclusivamente:

- `TemporaryDirectory`;
- SQLite temporário identificado como `SIMULATED_TEST_DATA`;
- produto fictício;
- relógio controlado em `America/Sao_Paulo`;
- coletores injetados e determinísticos.

Ela não abre navegador, não executa o coletor real, não inicia Scheduler
operacional e não importa transportes. Antes e depois da execução, o comando
compara os hashes do `.env` e do banco configurado.

## Execução

```powershell
python -m scripts.run_long_running_tests --quick
python -m scripts.run_long_running_tests --full
```

O modo completo inclui 30 dias, 90 horários agendados, duplicatas, falhas,
retries, outliers e reinícios. Não existe espera real.

Os resultados simulados são escritos somente em
`reports/long_running_tests/` e recebem a marca `SIMULATED_TEST_DATA`.

## Relógio

`ControlledClock` mantém um instante consciente de fuso e oferece avanço por
segundos, minutos, horas e dias. O `sleeper` do Scheduler recebe esse relógio
nos testes, portanto esperas e retries apenas avançam o instante simulado.

O relógio de produção não foi substituído.
