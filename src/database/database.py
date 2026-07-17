import sqlite3
import sys
import threading
from pathlib import Path

from src.scraper import Parser


class Database:

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

    # ============================================

    def default_db_path(self):

        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "promobot.db"

        return Path("promobot.db")

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

        titulo = produto.get("titulo", "").lower()

        palavras = (
            "promo",
            "oferta",
            "desconto",
            "liquidacao",
            "cupom",
            "black",
            "imperdivel",
        )

        if any(palavra in titulo for palavra in palavras):
            return True

        return preco_valor > 0

    # ============================================

    def salvar_lista(self, lista):

        for produto in lista:

            self.salvar_produto(produto)

    # ============================================

    def criar_alerta(self, termo, preco_alvo):

        termo = termo.strip()
        preco_alvo = float(str(preco_alvo).replace(",", "."))

        if not termo or preco_alvo <= 0:
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
                p.link,
                p.imagem

            FROM alertas a

            JOIN produtos p
                ON p.titulo LIKE '%' || a.termo || '%'
                AND p.preco_valor > 0
                AND p.preco_valor <= a.preco_alvo

            WHERE a.ativo = 1

            ORDER BY
                (a.preco_alvo - p.preco_valor) DESC,
                p.preco_valor ASC

            """)

            return self.cursor.fetchall()

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
