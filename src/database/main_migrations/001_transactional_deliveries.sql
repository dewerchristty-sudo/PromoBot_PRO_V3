CREATE TABLE IF NOT EXISTS entregas_destino (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chave_entrega TEXT NOT NULL UNIQUE,
    chave_publicacao TEXT NOT NULL,
    alerta_id INTEGER,
    link_original TEXT NOT NULL DEFAULT '',
    assinatura TEXT NOT NULL DEFAULT '',
    canal TEXT NOT NULL,
    destino TEXT NOT NULL,
    origem_decisao TEXT NOT NULL DEFAULT 'legado',
    status TEXT NOT NULL DEFAULT 'pendente' CHECK (
        status IN (
            'pendente',
            'enviando',
            'enviado',
            'falhou',
            'aguardando_nova_tentativa',
            'falha_definitiva',
            'revisao_necessaria'
        )
    ),
    tentativas INTEGER NOT NULL DEFAULT 0 CHECK (tentativas >= 0),
    proxima_tentativa TEXT,
    ultimo_erro TEXT NOT NULL DEFAULT '',
    erro_temporario INTEGER CHECK (
        erro_temporario IS NULL OR erro_temporario IN (0, 1)
    ),
    identificador_externo TEXT NOT NULL DEFAULT '',
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL,
    enviado_em TEXT
);

CREATE TABLE IF NOT EXISTS tentativas_entrega (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entrega_id INTEGER NOT NULL,
    numero_tentativa INTEGER NOT NULL CHECK (numero_tentativa > 0),
    iniciada_em TEXT NOT NULL,
    finalizada_em TEXT,
    status TEXT NOT NULL CHECK (
        status IN (
            'pendente',
            'enviando',
            'enviado',
            'falhou',
            'aguardando_nova_tentativa',
            'falha_definitiva',
            'revisao_necessaria'
        )
    ),
    erro TEXT NOT NULL DEFAULT '',
    erro_temporario INTEGER CHECK (
        erro_temporario IS NULL OR erro_temporario IN (0, 1)
    ),
    identificador_externo TEXT NOT NULL DEFAULT '',
    metadados_sanitizados TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(entrega_id) REFERENCES entregas_destino(id),
    UNIQUE(entrega_id, numero_tentativa)
);

CREATE INDEX IF NOT EXISTS idx_entregas_status_proxima
ON entregas_destino(status, proxima_tentativa);

CREATE INDEX IF NOT EXISTS idx_entregas_publicacao
ON entregas_destino(chave_publicacao);

CREATE INDEX IF NOT EXISTS idx_entregas_canal_destino
ON entregas_destino(canal, destino);

CREATE INDEX IF NOT EXISTS idx_entregas_enviado_em
ON entregas_destino(enviado_em);

CREATE INDEX IF NOT EXISTS idx_tentativas_entrega_numero
ON tentativas_entrega(entrega_id, numero_tentativa);

CREATE INDEX IF NOT EXISTS idx_tentativas_status
ON tentativas_entrega(status, iniciada_em);
