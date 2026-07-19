import re
import sqlite3
import sys
import threading
import json
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

from src.scraper import Parser


class Database:

    SENSITIVE_ENV_MARKERS = (
        "TOKEN",
        "KEY",
        "SECRET",
        "PASSWORD",
        "PHONE",
        "GROUP",
        "AFFILIATE",
    )

    def __init__(self, db_path=None):

        self.db = Path(db_path) if db_path else self.default_db_path()

        self.lock = threading.RLock()

        self.conn = sqlite3.connect(
            self.db,
            check_same_thread=False
        )

        self.conn.row_factory = sqlite3.Row

        self.cursor = self.conn.cursor()

        self.criar_tabelas()
        self.criar_backup_diario()

    # ============================================

    def default_db_path(self):

        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "promobot.db"

        return Path("promobot.db")

    # ============================================

    def criar_backup_diario(self):

        backup_dir = self.db.resolve().parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        suffix = date.today().isoformat()
        database_backup = backup_dir / f"promobot_{suffix}.db"

        if not database_backup.exists():
            backup_connection = sqlite3.connect(database_backup)
            try:
                with self.lock:
                    self.conn.backup(backup_connection)
            finally:
                backup_connection.close()

        config_path = self.db.resolve().parent / ".env"
        config_backup = backup_dir / f"promobot_env_{suffix}.redacted"

        if config_path.exists() and not config_backup.exists():
            content = config_path.read_text(encoding="utf-8")
            config_backup.write_text(
                self.redact_env_content(content),
                encoding="utf-8",
            )

        return database_backup

    @classmethod
    def redact_env_content(cls, content):

        redacted = []
        for line in str(content or "").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in line:
                redacted.append(line)
                continue
            key, value = line.split("=", 1)
            normalized_key = key.strip().upper()
            if any(marker in normalized_key for marker in cls.SENSITIVE_ENV_MARKERS):
                value = "<redacted>" if value.strip() else ""
            redacted.append(f"{key}={value}")
        return "\n".join(redacted) + "\n"

    def verificar_integridade(self):

        with self.lock:
            self.cursor.execute("PRAGMA integrity_check")
            return self.cursor.fetchone()[0]

    # ============================================

    def criar_tabelas(self):

        with self.lock:

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS produtos(

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                loja TEXT,

                titulo TEXT,

                preco TEXT,

                preco_valor REAL DEFAULT 0,

                promocao INTEGER DEFAULT 0,

                link TEXT UNIQUE,

                imagem TEXT,

                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS historico_precos(

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                produto_id INTEGER,

                loja TEXT,

                titulo TEXT,

                preco TEXT,

                preco_valor REAL DEFAULT 0,

                link TEXT,

                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY(produto_id) REFERENCES produtos(id)

            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS alertas(

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                termo TEXT,

                preco_alvo REAL,

                ativo INTEGER DEFAULT 1,

                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS monitoramentos(

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                termo TEXT,

                intervalo_minutos INTEGER DEFAULT 30,

                lojas TEXT,

                ativo INTEGER DEFAULT 1,

                ultima_execucao TIMESTAMP,

                ultimo_total INTEGER DEFAULT 0,

                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS notificacoes_enviadas(

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                alerta_id INTEGER,

                link TEXT,

                assinatura TEXT,

                preco_valor REAL DEFAULT 0,

                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(alerta_id, link)

            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS links_afiliados(

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                loja TEXT NOT NULL,

                link_original TEXT NOT NULL UNIQUE,

                link_afiliado TEXT NOT NULL,

                etiqueta TEXT DEFAULT '',

                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS historico_envios(

                id INTEGER PRIMARY KEY AUTOINCREMENT,
                loja TEXT,
                titulo TEXT,
                link_original TEXT,
                link_afiliado TEXT,
                etiqueta TEXT,
                canal TEXT,
                destino TEXT,
                status TEXT,
                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS notificacoes_manuais(

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                link_original TEXT NOT NULL UNIQUE,

                assinatura TEXT,

                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS categorias_whatsapp(

                categoria TEXT PRIMARY KEY,
                palavras TEXT NOT NULL DEFAULT '',
                atualizado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP

            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS metricas_grupos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                destino TEXT NOT NULL,
                cliques INTEGER DEFAULT 0,
                vendas INTEGER DEFAULT 0,
                comissao REAL DEFAULT 0,
                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS fila_notificacoes(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chave TEXT NOT NULL UNIQUE,
                alerta_json TEXT NOT NULL,
                tentativas INTEGER DEFAULT 0,
                ultimo_erro TEXT DEFAULT '',
                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ultima_tentativa TIMESTAMP
            )
            """)

            self.cursor.execute("""
            CREATE TABLE IF NOT EXISTS eventos_sistema(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nivel TEXT NOT NULL,
                componente TEXT NOT NULL,
                mensagem TEXT NOT NULL,
                data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            self.conn.commit()

            self.migrar_tabelas()

    # ============================================

    def migrar_tabelas(self):

        self.cursor.execute("PRAGMA table_info(produtos)")
        colunas = {coluna["name"] for coluna in self.cursor.fetchall()}

        if "preco_valor" not in colunas:
            self.cursor.execute(
                "ALTER TABLE produtos ADD COLUMN preco_valor REAL DEFAULT 0"
            )

        if "promocao" not in colunas:
            self.cursor.execute(
                "ALTER TABLE produtos ADD COLUMN promocao INTEGER DEFAULT 0"
            )

        self.cursor.execute("PRAGMA table_info(links_afiliados)")
        colunas_links = {coluna["name"] for coluna in self.cursor.fetchall()}

        if "etiqueta" not in colunas_links:
            self.cursor.execute(
                "ALTER TABLE links_afiliados ADD COLUMN etiqueta TEXT DEFAULT ''"
            )

        self.cursor.execute("PRAGMA table_info(notificacoes_manuais)")
        colunas_manuais = {coluna["name"] for coluna in self.cursor.fetchall()}

        if "assinatura" not in colunas_manuais:
            self.cursor.execute(
                "ALTER TABLE notificacoes_manuais ADD COLUMN assinatura TEXT"
            )

        self.cursor.execute("""

        UPDATE notificacoes_manuais

        SET assinatura = (
            SELECT lower(trim(p.loja)) || '|' || lower(trim(p.titulo))
            FROM produtos p
            WHERE p.link = notificacoes_manuais.link_original
            LIMIT 1
        )

        WHERE assinatura IS NULL

        """)

        self.cursor.execute("PRAGMA table_info(notificacoes_enviadas)")
        colunas_notificacoes = {
            coluna["name"] for coluna in self.cursor.fetchall()
        }

        if "assinatura" not in colunas_notificacoes:
            self.cursor.execute(
                "ALTER TABLE notificacoes_enviadas ADD COLUMN assinatura TEXT"
            )

        self.cursor.execute("""

        UPDATE notificacoes_enviadas

        SET assinatura = (
            SELECT lower(trim(p.loja)) || '|' || lower(trim(p.titulo))
            FROM produtos p
            WHERE p.link = notificacoes_enviadas.link
            LIMIT 1
        )

        WHERE assinatura IS NULL

        """)

        self.cursor.execute("""

        DELETE FROM notificacoes_enviadas

        WHERE assinatura IS NOT NULL
        AND id NOT IN (
            SELECT MIN(id)
            FROM notificacoes_enviadas
            WHERE assinatura IS NOT NULL
            GROUP BY alerta_id, assinatura
        )

        """)

        self.cursor.execute("""

        DELETE FROM produtos

        WHERE link IN (
            SELECT link
            FROM produtos
            WHERE link <> ''
            GROUP BY link
            HAVING COUNT(*) > 1
        )
        AND id NOT IN (
            SELECT MIN(id)
            FROM produtos
            WHERE link <> ''
            GROUP BY link
        )

        """)

        self.cursor.execute("""

        CREATE UNIQUE INDEX IF NOT EXISTS idx_produtos_link_unique

        ON produtos(link)

        """)

        self.cursor.execute("""

        CREATE UNIQUE INDEX IF NOT EXISTS idx_notificacoes_assinatura_unique

        ON notificacoes_enviadas(alerta_id, assinatura)

        WHERE assinatura IS NOT NULL

        """)

        self.conn.commit()

    # ============================================

    def salvar_produto(self, produto):

        try:

            with self.lock:

                preco = produto.get("preco", "")
                preco_valor = Parser.price_to_float(preco)
                promocao = 1 if self.detectar_promocao(produto, preco_valor) else 0

                self.cursor.execute("""

                INSERT INTO produtos(

                    loja,

                    titulo,

                    preco,

                    preco_valor,

                    promocao,

                    link,

                    imagem

                )

                VALUES(?,?,?,?,?,?,?)

                ON CONFLICT(link) DO UPDATE SET
                    loja = excluded.loja,
                    titulo = excluded.titulo,
                    preco = excluded.preco,
                    preco_valor = excluded.preco_valor,
                    promocao = excluded.promocao,
                    imagem = excluded.imagem

                """, (

                    produto.get("loja", ""),

                    produto.get("titulo", ""),

                    preco,

                    preco_valor,

                    promocao,

                    produto.get("link", ""),

                    produto.get("imagem", "")

                ))

                self.cursor.execute(
                    "SELECT id FROM produtos WHERE link = ?",
                    (produto.get("link", ""),)
                )
                produto_salvo = self.cursor.fetchone()

                if produto_salvo:
                    self.salvar_historico_preco(
                        produto_salvo["id"],
                        produto,
                        preco,
                        preco_valor
                    )

                self.conn.commit()

        except Exception:

            pass

    # ============================================

    def salvar_historico_preco(self, produto_id, produto, preco, preco_valor):

        if preco_valor <= 0:
            return

        self.cursor.execute("""

        INSERT INTO historico_precos(
            produto_id,
            loja,
            titulo,
            preco,
            preco_valor,
            link
        )

        VALUES(?,?,?,?,?,?)

        """, (
            produto_id,
            produto.get("loja", ""),
            produto.get("titulo", ""),
            preco,
            preco_valor,
            produto.get("link", ""),
        ))

    # ============================================

    def detectar_promocao(self, produto, preco_valor):

        titulo = Parser.clean_text(produto.get("titulo", "")).lower()

        palavras = (
            "promo",
            "oferta",
            "desconto",
            "liquidacao",
            "liquidação",
            "cupom",
            "black",
            "imperdivel",
            "imperdível",
            "menor preço",
            "preço baixo",
            "queima",
            "saldão",
        )

        if any(palavra in titulo for palavra in palavras):
            return True

        if preco_valor <= 0:
            return False

        link = produto.get("link", "")

        self.cursor.execute("""

        SELECT MAX(preco_valor)

        FROM historico_precos

        WHERE link = ?
            AND preco_valor > 0

        """, (link,))

        maior_preco = self.cursor.fetchone()[0] or 0

        return maior_preco > 0 and preco_valor <= maior_preco * 0.9

    # ============================================

    def salvar_lista(self, lista):

        for produto in lista:

            self.salvar_produto(produto)

    # ============================================

    def salvar_link_afiliado(
        self,
        loja,
        link_original,
        link_afiliado,
        etiqueta="promobotwhatsapp",
    ):

        loja = str(loja or "").strip()
        link_original = str(link_original or "").strip()
        link_afiliado = str(link_afiliado or "").strip()
        etiqueta = str(etiqueta or "").strip()

        if not loja or not link_original or not link_afiliado:
            raise ValueError("Preencha loja, link original e link afiliado.")

        with self.lock:

            self.cursor.execute("""

            INSERT INTO links_afiliados(
                loja, link_original, link_afiliado, etiqueta
            )

            VALUES(?,?,?,?)

            ON CONFLICT(link_original) DO UPDATE SET
                loja = excluded.loja,
                link_afiliado = excluded.link_afiliado,
                etiqueta = excluded.etiqueta,
                data = CURRENT_TIMESTAMP

            """, (loja, link_original, link_afiliado, etiqueta))

            self.conn.commit()

    # ============================================

    def buscar_link_afiliado(self, link_original):

        with self.lock:

            self.cursor.execute("""

            SELECT link_afiliado

            FROM links_afiliados

            WHERE link_original = ?

            LIMIT 1

            """, (str(link_original or "").strip(),))

            resultado = self.cursor.fetchone()

            return resultado["link_afiliado"] if resultado else ""

    # ============================================

    def listar_produtos_marketplace(self, somente_promocoes=False):

        filtro_promocao = "AND p.promocao = 1" if somente_promocoes else ""

        with self.lock:

            self.cursor.execute(f"""

            SELECT
                p.*,
                (
                    SELECT MAX(h.preco_valor)
                    FROM historico_precos h
                    WHERE h.produto_id = p.id
                ) AS maior_preco

            FROM produtos p

            WHERE (
                lower(trim(p.loja)) IN ('shopee', 'mercado livre')
                OR lower(p.link) LIKE '%shopee.com.br%'
                OR lower(p.link) LIKE '%mercadolivre.com%'
                OR lower(p.link) LIKE '%mercadolivre.com.br%'
            )

            {filtro_promocao}

            ORDER BY p.id DESC

            """)

            return self.cursor.fetchall()

    # ============================================

    def total_links_afiliados(self):

        with self.lock:
            self.cursor.execute("SELECT COUNT(*) FROM links_afiliados")
            return self.cursor.fetchone()[0]

    # ============================================

    def etiqueta_link_afiliado(self, link_original):

        with self.lock:
            self.cursor.execute(
                "SELECT etiqueta FROM links_afiliados WHERE link_original = ?",
                (str(link_original or "").strip(),),
            )
            result = self.cursor.fetchone()
            return result["etiqueta"] if result else ""

    # ============================================

    def registrar_envio(
        self,
        loja,
        titulo,
        link_original,
        link_afiliado,
        etiqueta,
        canal,
        destino,
        status="enviado",
    ):

        with self.lock:
            self.cursor.execute("""

            INSERT INTO historico_envios(
                loja, titulo, link_original, link_afiliado, etiqueta,
                canal, destino, status
            )

            VALUES(?,?,?,?,?,?,?,?)

            """, (
                loja,
                titulo,
                link_original,
                link_afiliado,
                etiqueta,
                canal,
                destino,
                status,
            ))
            self.conn.commit()

    # ============================================

    def listar_historico_envios(self, limite=30):

        with self.lock:
            self.cursor.execute("""

            SELECT * FROM historico_envios

            ORDER BY id DESC

            LIMIT ?

            """, (max(int(limite), 1),))
            return self.cursor.fetchall()

    # ============================================

    def contar_envios_recentes(self, minutos=60, canal="WhatsApp"):

        with self.lock:
            self.cursor.execute("""

            SELECT COUNT(*)

            FROM historico_envios

            WHERE canal = ?
                AND status = 'enviado'
                AND data >= datetime('now', ?)

            """, (canal, f"-{max(int(minutos), 1)} minutes"))
            return self.cursor.fetchone()[0]

    def contar_envios_destino_recentes(
        self, destino, minutos=60, canal="WhatsApp"
    ):

        with self.lock:
            self.cursor.execute("""
            SELECT COUNT(*) FROM historico_envios
            WHERE canal = ? AND destino = ? AND status = 'enviado'
                AND data >= datetime('now', ?)
            """, (canal, destino, f"-{max(int(minutos), 1)} minutes"))
            return self.cursor.fetchone()[0]

    def relatorio_envios_por_destino(self, dias=30):

        with self.lock:
            self.cursor.execute("""
            SELECT destino, COUNT(*) AS total,
                   COUNT(DISTINCT link_original) AS produtos,
                   MAX(data) AS ultimo_envio
            FROM historico_envios
            WHERE canal = 'WhatsApp' AND status = 'enviado'
                AND data >= datetime('now', ?)
            GROUP BY destino ORDER BY total DESC
            """, (f"-{max(int(dias), 1)} days",))
            return self.cursor.fetchall()

    def salvar_palavras_categoria(self, categoria, palavras):

        with self.lock:
            self.cursor.execute("""
            INSERT INTO categorias_whatsapp(categoria, palavras, atualizado_em)
            VALUES(?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(categoria) DO UPDATE SET
                palavras=excluded.palavras,
                atualizado_em=CURRENT_TIMESTAMP
            """, (str(categoria).strip(), str(palavras).strip()))
            self.conn.commit()

    def listar_palavras_categorias(self):

        with self.lock:
            self.cursor.execute(
                "SELECT categoria, palavras FROM categorias_whatsapp"
            )
            return {
                row["categoria"]: [
                    word.strip() for word in row["palavras"].split(",")
                    if word.strip()
                ]
                for row in self.cursor.fetchall()
            }

    def registrar_metricas_grupo(self, destino, cliques=0, vendas=0, comissao=0):

        with self.lock:
            self.cursor.execute("""
            INSERT INTO metricas_grupos(destino, cliques, vendas, comissao)
            VALUES(?,?,?,?)
            """, (destino, int(cliques), int(vendas), float(comissao)))
            self.conn.commit()

    def relatorio_metricas_grupos(self, dias=30):

        with self.lock:
            self.cursor.execute("""
            SELECT destino, SUM(cliques) AS cliques, SUM(vendas) AS vendas,
                   SUM(comissao) AS comissao
            FROM metricas_grupos WHERE data >= datetime('now', ?)
            GROUP BY destino
            """, (f"-{max(int(dias), 1)} days",))
            return {row["destino"]: row for row in self.cursor.fetchall()}

    def enfileirar_notificacoes(self, alertas, erro=""):

        with self.lock:
            for alerta in alertas:
                item = dict(alerta)
                chave = str(item.get("link") or item.get("assinatura") or "").strip()
                if not chave:
                    continue
                self.cursor.execute("""
                INSERT INTO fila_notificacoes(chave, alerta_json, tentativas, ultimo_erro)
                VALUES(?,?,1,?)
                ON CONFLICT(chave) DO UPDATE SET
                    alerta_json=excluded.alerta_json,
                    tentativas=fila_notificacoes.tentativas + 1,
                    ultimo_erro=excluded.ultimo_erro,
                    ultima_tentativa=CURRENT_TIMESTAMP
                """, (chave, json.dumps(item, ensure_ascii=False, default=str), str(erro)[:500]))
            self.conn.commit()

    def listar_fila_notificacoes(self, limite=20):

        with self.lock:
            self.cursor.execute(
                "SELECT * FROM fila_notificacoes ORDER BY id LIMIT ?",
                (max(int(limite), 1),),
            )
            rows = self.cursor.fetchall()
            return [(row, json.loads(row["alerta_json"])) for row in rows]

    def remover_fila_notificacoes(self, ids):

        ids = [int(item) for item in ids]
        if not ids:
            return
        with self.lock:
            marks = ",".join("?" for _ in ids)
            self.cursor.execute(f"DELETE FROM fila_notificacoes WHERE id IN ({marks})", ids)
            self.conn.commit()

    def total_fila_notificacoes(self):

        with self.lock:
            self.cursor.execute("SELECT COUNT(*) FROM fila_notificacoes")
            return self.cursor.fetchone()[0]

    def registrar_evento_sistema(self, nivel, componente, mensagem):

        with self.lock:
            self.cursor.execute("""
            INSERT INTO eventos_sistema(nivel, componente, mensagem) VALUES(?,?,?)
            """, (nivel, componente, str(mensagem)[:1000]))
            self.cursor.execute("""
            DELETE FROM eventos_sistema WHERE id NOT IN (
                SELECT id FROM eventos_sistema ORDER BY id DESC LIMIT 1000
            )
            """)
            self.conn.commit()

    def listar_eventos_sistema(self, limite=20):

        with self.lock:
            self.cursor.execute(
                "SELECT * FROM eventos_sistema ORDER BY id DESC LIMIT ?",
                (max(int(limite), 1),),
            )
            return self.cursor.fetchall()

    # ============================================

    def produto_ja_notificado(self, link_original, loja="", titulo=""):

        link_original = str(link_original or "").strip()
        assinatura = self.normalizar_assinatura(loja) + "|" + self.normalizar_assinatura(titulo)
        assinatura = assinatura if assinatura != "|" else ""

        with self.lock:

            self.cursor.execute("""

            SELECT 1 FROM notificacoes_manuais
            WHERE link_original = ? OR assinatura = ?

            UNION ALL

            SELECT 1 FROM notificacoes_enviadas
            WHERE link = ? OR assinatura = ?

            LIMIT 1

            """, (link_original, assinatura, link_original, assinatura))

            if self.cursor.fetchone() is not None:
                return True

            if not titulo:
                return False

            self.cursor.execute("""
            SELECT titulo FROM historico_envios
            WHERE lower(trim(loja)) = lower(trim(?)) AND status = 'enviado'
            ORDER BY id DESC LIMIT 1000
            """, (str(loja or ""),))
            return any(
                self.titulos_semelhantes(titulo, row["titulo"])
                for row in self.cursor.fetchall()
            )

    def titulos_semelhantes(self, primeiro, segundo):

        first = self.normalizar_titulo_produto(primeiro)
        second = self.normalizar_titulo_produto(segundo)
        if not first or not second:
            return False
        if SequenceMatcher(None, first, second).ratio() >= 0.88:
            return True
        first_tokens = set(first.split())
        second_tokens = set(second.split())
        union = first_tokens | second_tokens
        return bool(union) and len(first_tokens & second_tokens) / len(union) >= 0.78

    def normalizar_titulo_produto(self, texto):

        text = self.normalizar_assinatura(texto)
        text = re.sub(r"\b(preto|branco|azul|vermelho|rosa|cinza|novo|oferta)\b", " ", text)
        text = re.sub(r"\b\d+\s*(gb|tb|ml|l|kg|w|v|polegadas?)\b", " ", text)
        return re.sub(r"[^a-z0-9áàâãéêíóôõúç]+", " ", text).strip()

    # ============================================

    def marcar_notificacao_manual(self, link_original, loja="", titulo=""):

        assinatura = self.normalizar_assinatura(loja) + "|" + self.normalizar_assinatura(titulo)
        assinatura = assinatura if assinatura != "|" else None

        with self.lock:

            self.cursor.execute("""

            INSERT OR IGNORE INTO notificacoes_manuais(link_original, assinatura)

            VALUES(?,?)

            """, (str(link_original or "").strip(), assinatura))

            self.conn.commit()

    # ============================================

    def criar_alerta(self, termo, preco_alvo):

        termo = termo.strip()
        preco_texto = str(preco_alvo or "").strip()
        preco_alvo = (
            float(preco_texto.replace(",", "."))
            if preco_texto
            else None
        )

        if preco_alvo is not None and preco_alvo <= 0:
            return

        with self.lock:

            self.cursor.execute("""

            INSERT INTO alertas(termo, preco_alvo, ativo)

            VALUES(?,?,1)

            """, (termo, preco_alvo))

            self.conn.commit()

    # ============================================

    def listar_alertas(self, somente_ativos=False):

        where = "WHERE ativo = 1" if somente_ativos else ""

        with self.lock:

            self.cursor.execute(f"""

            SELECT *

            FROM alertas

            {where}

            ORDER BY ativo DESC, id DESC

            """)

            return self.cursor.fetchall()

    # ============================================

    def alternar_alerta(self, alerta_id):

        with self.lock:

            self.cursor.execute("""

            UPDATE alertas

            SET ativo = CASE WHEN ativo = 1 THEN 0 ELSE 1 END

            WHERE id = ?

            """, (alerta_id,))

            self.conn.commit()

    # ============================================

    def remover_alerta(self, alerta_id):

        with self.lock:

            self.cursor.execute("""

            DELETE FROM alertas

            WHERE id = ?

            """, (alerta_id,))

            self.conn.commit()

    # ============================================

    def alertas_disparados(self):

        with self.lock:

            self.cursor.execute("""

            SELECT
                a.id AS alerta_id,
                a.termo,
                a.preco_alvo,
                p.loja,
                p.titulo,
                p.preco,
                p.preco_valor,
                p.data,
                lower(trim(p.loja)) || '|' || lower(trim(p.titulo)) AS assinatura,
                (
                    SELECT MAX(h.preco_valor)
                    FROM historico_precos h
                    WHERE h.produto_id = p.id
                ) AS maior_preco,
                p.link,
                p.imagem

            FROM alertas a

            JOIN produtos p
                ON (
                    a.termo = ''
                    OR p.titulo LIKE '%' || a.termo || '%'
                )
                AND p.preco_valor > 0
                AND (
                    (
                        a.preco_alvo IS NOT NULL
                        AND p.preco_valor <= a.preco_alvo
                    )
                    OR (
                        a.preco_alvo IS NULL
                        AND p.promocao = 1
                    )
                )

            WHERE a.ativo = 1

            ORDER BY
                (a.preco_alvo - p.preco_valor) DESC,
                p.preco_valor ASC

            """)

            return self.cursor.fetchall()

    # ============================================

    def alertas_pendentes(self):

        with self.lock:

            self.cursor.execute("""

            SELECT
                a.id AS alerta_id,
                a.termo,
                a.preco_alvo,
                p.loja,
                p.titulo,
                p.preco,
                p.preco_valor,
                p.data,
                lower(trim(p.loja)) || '|' || lower(trim(p.titulo)) AS assinatura,
                (
                    SELECT MAX(h.preco_valor)
                    FROM historico_precos h
                    WHERE h.produto_id = p.id
                ) AS maior_preco,
                p.link,
                p.imagem

            FROM alertas a

            JOIN produtos p
                ON (
                    a.termo = ''
                    OR p.titulo LIKE '%' || a.termo || '%'
                )
                AND p.preco_valor > 0
                AND (
                    (
                        a.preco_alvo IS NOT NULL
                        AND p.preco_valor <= a.preco_alvo
                    )
                    OR (
                        a.preco_alvo IS NULL
                        AND p.promocao = 1
                    )
                )

            LEFT JOIN notificacoes_enviadas n
                ON (
                    n.link = p.link
                    OR n.assinatura = lower(trim(p.loja)) || '|' || lower(trim(p.titulo))
                )

            WHERE a.ativo = 1
                AND n.id IS NULL

            GROUP BY lower(trim(p.loja)), lower(trim(p.titulo))

            ORDER BY
                p.preco_valor ASC,
                p.id DESC

            """)

            return self.filtrar_alertas_pendentes(self.cursor.fetchall())

    # ============================================

    def marcar_notificacoes_enviadas(self, alertas):

        with self.lock:

            for alerta in alertas:

                alerta_id = alerta["alerta_id"]
                link = alerta["link"]
                preco_valor = alerta["preco_valor"]
                assinatura = self.assinatura_notificacao(alerta)

                if not alerta_id or (not link and not assinatura):
                    continue

                self.cursor.execute("""

                INSERT OR IGNORE INTO notificacoes_enviadas(
                    alerta_id,
                    link,
                    assinatura,
                    preco_valor
                )

                VALUES(?,?,?,?)

                """, (alerta_id, link, assinatura, preco_valor))

            self.conn.commit()

    # ============================================

    def filtrar_alertas_pendentes(self, alertas):

        pendentes = []
        vistos = set()

        for alerta in alertas:
            assinatura = self.assinatura_notificacao(alerta)
            chave = assinatura or alerta["link"]

            if chave in vistos:
                continue

            if self.notificacao_ja_enviada(alerta, assinatura):
                continue

            vistos.add(chave)
            pendentes.append(alerta)

        return pendentes

    # ============================================

    def notificacao_ja_enviada(self, alerta, assinatura=None):

        assinatura = assinatura or self.assinatura_notificacao(alerta)

        self.cursor.execute("""

        SELECT 1

        FROM notificacoes_enviadas

        WHERE (
                link = ?
                OR assinatura = ?
            )

        LIMIT 1

        """, (alerta["link"], assinatura))

        return self.cursor.fetchone() is not None

    # ============================================

    def assinatura_notificacao(self, alerta):

        loja = self.normalizar_assinatura(alerta["loja"])
        titulo = self.normalizar_assinatura(alerta["titulo"])

        if not loja and not titulo:
            return ""

        return f"{loja}|{titulo}"

    # ============================================

    def normalizar_assinatura(self, texto):

        texto = Parser.clean_text(str(texto or "")).lower().strip()
        texto = re.sub(r"\s+", " ", texto)

        return texto

    # ============================================

    def criar_monitoramento(self, termo, intervalo_minutos=30, lojas=""):

        termo = termo.strip()
        intervalo_minutos = int(intervalo_minutos)

        if not termo or intervalo_minutos <= 0:
            return

        with self.lock:

            self.cursor.execute("""

            SELECT id

            FROM monitoramentos

            WHERE lower(termo) = lower(?)

            LIMIT 1

            """, (termo,))

            existente = self.cursor.fetchone()

            if existente:
                return existente["id"]

            self.cursor.execute("""

            INSERT INTO monitoramentos(
                termo,
                intervalo_minutos,
                lojas,
                ativo
            )

            VALUES(?,?,?,1)

            """, (termo, intervalo_minutos, lojas))

            self.conn.commit()

            return self.cursor.lastrowid

    # ============================================

    def criar_monitoramentos_padrao(self, intervalo_minutos=60, lojas=""):

        termos = [
            "oferta do dia",
            "promoção",
            "notebook",
            "smartphone",
            "iphone",
            "samsung galaxy",
            "tv 50 polegadas",
            "smart tv",
            "air fryer",
            "geladeira",
            "maquina de lavar",
            "microondas",
            "fone bluetooth",
            "monitor gamer",
            "cadeira gamer",
            "placa de video",
            "ssd 1tb",
            "tablet",
            "console ps5",
            "xbox",
        ]

        termos.extend([
            "promoção",
            "liquidação",
            "cupom",
            "black friday",
            "achadinhos",
            "xiaomi",
            "caixa de som bluetooth",
            "memoria ram",
            "processador",
            "placa mae",
            "mouse gamer",
            "teclado mecanico",
            "nintendo switch",
            "alexa",
            "echo dot",
            "kindle",
            "smartwatch",
            "aspirador robo",
            "cafeteira",
            "panela eletrica",
            "ar condicionado",
            "ventilador",
            "camera seguranca",
            "roteador wifi",
            "impressora",
            "mochila",
            "tenis",
            "perfume",
        ])

        criados = 0

        for termo in termos:

            antes = len(self.listar_monitoramentos())
            self.criar_monitoramento(termo, intervalo_minutos, lojas)
            depois = len(self.listar_monitoramentos())

            if depois > antes:
                criados += 1

        return criados

    # ============================================

    def listar_monitoramentos(self, somente_ativos=False):

        where = "WHERE ativo = 1" if somente_ativos else ""

        with self.lock:

            self.cursor.execute(f"""

            SELECT *

            FROM monitoramentos

            {where}

            ORDER BY ativo DESC, id DESC

            """)

            return self.cursor.fetchall()

    # ============================================

    def alternar_monitoramento(self, monitoramento_id):

        with self.lock:

            self.cursor.execute("""

            UPDATE monitoramentos

            SET ativo = CASE WHEN ativo = 1 THEN 0 ELSE 1 END

            WHERE id = ?

            """, (monitoramento_id,))

            self.conn.commit()

    # ============================================

    def remover_monitoramento(self, monitoramento_id):

        with self.lock:

            self.cursor.execute("""

            DELETE FROM monitoramentos

            WHERE id = ?

            """, (monitoramento_id,))

            self.conn.commit()

    # ============================================

    def registrar_execucao_monitoramento(self, monitoramento_id, total):

        with self.lock:

            self.cursor.execute("""

            UPDATE monitoramentos

            SET
                ultima_execucao = CURRENT_TIMESTAMP,
                ultimo_total = ?

            WHERE id = ?

            """, (total, monitoramento_id))

            self.conn.commit()

    # ============================================

    def listar_produtos(self):

        with self.lock:

            self.cursor.execute("""

            SELECT *

            FROM produtos

            ORDER BY id DESC

            """)

            return self.cursor.fetchall()

    # ============================================

    def listar_recentes(self, limite=15):

        with self.lock:

            self.cursor.execute("""

            SELECT *

            FROM produtos

            ORDER BY data DESC, id DESC

            LIMIT ?

            """, (limite,))

            return self.cursor.fetchall()

    # ============================================

    def buscar_produtos(
        self,
        termo="",
        preco_min=None,
        preco_max=None,
        somente_promocoes=False,
        ordenar="recentes"
    ):

        filtros = []
        parametros = []

        if termo.strip():

            termo_like = f"%{termo.strip()}%"
            filtros.append("(titulo LIKE ? OR loja LIKE ? OR preco LIKE ?)")
            parametros.extend([termo_like, termo_like, termo_like])

        if preco_min not in (None, ""):

            filtros.append("preco_valor >= ?")
            parametros.append(float(preco_min))

        if preco_max not in (None, ""):

            filtros.append("preco_valor <= ?")
            parametros.append(float(preco_max))

        if somente_promocoes:

            filtros.append("promocao = 1")

        where = ""

        if filtros:
            where = "WHERE " + " AND ".join(filtros)

        ordenacoes = {
            "recentes": "id DESC",
            "menor_preco": "preco_valor ASC, id DESC",
            "maior_preco": "preco_valor DESC, id DESC",
            "loja": "loja ASC, preco_valor ASC",
        }

        order_by = ordenacoes.get(ordenar, ordenacoes["recentes"])

        with self.lock:

            self.cursor.execute(f"""

            SELECT *

            FROM produtos

            {where}

            ORDER BY {order_by}

            """, parametros)

            return self.cursor.fetchall()

    # ============================================

    def total_produtos(self):

        with self.lock:

            self.cursor.execute("""

            SELECT COUNT(*)

            FROM produtos

            """)

            return self.cursor.fetchone()[0]

    # ============================================

    def total_lojas(self):

        with self.lock:

            self.cursor.execute("""

            SELECT COUNT(DISTINCT loja)

            FROM produtos

            WHERE loja <> ''

            """)

            return self.cursor.fetchone()[0]

    # ============================================

    def total_promocoes(self):

        with self.lock:

            self.cursor.execute("""

            SELECT COUNT(*)

            FROM produtos

            WHERE promocao = 1

            """)

            return self.cursor.fetchone()[0]

    # ============================================

    def menor_preco(self):

        with self.lock:

            self.cursor.execute("""

            SELECT *

            FROM produtos

            WHERE preco_valor > 0

            ORDER BY preco_valor ASC

            LIMIT 1

            """)

            return self.cursor.fetchone()

    # ============================================

    def ofertas(self, limite=20):

        with self.lock:

            self.cursor.execute("""

            SELECT *

            FROM produtos

            WHERE preco_valor > 0

            ORDER BY preco_valor ASC, id DESC

            LIMIT ?

            """, (limite,))

            return self.cursor.fetchall()

    # ============================================

    def ofertas_com_variacao(self, limite=30):

        with self.lock:

            self.cursor.execute("""

            SELECT
                p.*,
                (
                    SELECT MAX(h.preco_valor)
                    FROM historico_precos h
                    WHERE h.produto_id = p.id
                ) AS maior_preco,
                (
                    SELECT MIN(h.preco_valor)
                    FROM historico_precos h
                    WHERE h.produto_id = p.id
                ) AS menor_historico,
                (
                    SELECT COUNT(*)
                    FROM historico_precos h
                    WHERE h.produto_id = p.id
                ) AS coletas

            FROM produtos p

            WHERE p.preco_valor > 0

            ORDER BY
                CASE
                    WHEN (
                        SELECT MAX(h.preco_valor)
                        FROM historico_precos h
                        WHERE h.produto_id = p.id
                    ) > p.preco_valor
                    THEN (
                        (
                            SELECT MAX(h.preco_valor)
                            FROM historico_precos h
                            WHERE h.produto_id = p.id
                        ) - p.preco_valor
                    )
                    ELSE 0
                END DESC,
                p.preco_valor ASC,
                p.id DESC

            LIMIT ?

            """, (limite,))

            return self.cursor.fetchall()

    # ============================================

    def historico_produto(self, produto_id, limite=20):

        with self.lock:

            self.cursor.execute("""

            SELECT *

            FROM historico_precos

            WHERE produto_id = ?

            ORDER BY data DESC, id DESC

            LIMIT ?

            """, (produto_id, limite))

            return self.cursor.fetchall()

    # ============================================

    def total_coletas_preco(self):

        with self.lock:

            self.cursor.execute("""

            SELECT COUNT(*)

            FROM historico_precos

            """)

            return self.cursor.fetchone()[0]

    # ============================================

    def resumo_por_loja(self):

        with self.lock:

            self.cursor.execute("""

            SELECT loja, COUNT(*) AS total, MAX(data) AS ultima_data

            FROM produtos

            GROUP BY loja

            ORDER BY total DESC, loja ASC

            """)

            return self.cursor.fetchall()

    # ============================================

    def limpar(self):

        with self.lock:

            self.cursor.execute("""

            DELETE FROM historico_precos

            """)

            self.cursor.execute("""

            DELETE FROM alertas

            """)

            self.cursor.execute("""

            DELETE FROM monitoramentos

            """)

            self.cursor.execute("""

            DELETE FROM produtos

            """)

            self.conn.commit()

    # ============================================

    def fechar(self):

        with self.lock:

            self.conn.close()
