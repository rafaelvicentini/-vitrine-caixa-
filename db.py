"""
db.py — Camada de dados do Vitrine & Caixa (versão Python + SQLite).

Toda a comunicação com o banco passa por este módulo. A interface (app.py)
nunca escreve SQL: ela chama as funções daqui.

Decisões de projeto:
- Valores em dinheiro são guardados em CENTAVOS (inteiros), evitando erros de
  ponto flutuante (0.1 + 0.2 = 0.30000000000000004).
- Todas as consultas usam parâmetros (?) — nunca concatenação de texto — o que
  impede injeção de SQL.
- Cada loja (empreendedor) tem um PIN de 4 dígitos. O PIN não é guardado: só
  o seu hash PBKDF2-SHA256 com "sal" aleatório.
- Uma venda é gravada numa TRANSAÇÃO: ou grava a venda, os itens, a baixa de
  estoque e os movimentos, ou não grava nada (atomicidade).
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Cuiaba")
CAMINHO_PADRAO = os.environ.get(
    "VITRINE_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "vitrine_caixa.db")
)

ESQUEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS lojas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    nome          TEXT NOT NULL,
    slug          TEXT NOT NULL UNIQUE,          -- usado no link público da vitrine
    pin_hash      TEXT NOT NULL,
    pin_sal       TEXT NOT NULL,
    whatsapp      TEXT NOT NULL DEFAULT '',      -- só dígitos, com DDI 55
    estoque_minimo_padrao INTEGER NOT NULL DEFAULT 3,
    criado_em     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS produtos (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id        INTEGER NOT NULL REFERENCES lojas(id) ON DELETE CASCADE,
    nome           TEXT NOT NULL,
    categoria      TEXT NOT NULL DEFAULT '',
    preco_centavos INTEGER NOT NULL CHECK (preco_centavos > 0),
    estoque        INTEGER NOT NULL DEFAULT 0 CHECK (estoque >= 0),
    estoque_minimo INTEGER NOT NULL DEFAULT 3 CHECK (estoque_minimo >= 0),
    foto           BLOB,
    foto_mime      TEXT,
    na_vitrine     INTEGER NOT NULL DEFAULT 1,
    ativo          INTEGER NOT NULL DEFAULT 1,   -- 0 = excluído (mantém histórico das vendas)
    criado_em      TEXT NOT NULL,
    atualizado_em  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_produtos_loja ON produtos(loja_id, ativo);

CREATE TABLE IF NOT EXISTS vendas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id         INTEGER NOT NULL REFERENCES lojas(id) ON DELETE CASCADE,
    data_hora       TEXT NOT NULL,               -- horário de Cuiabá, ISO 8601
    total_centavos  INTEGER NOT NULL,
    forma_pagamento TEXT NOT NULL DEFAULT '',
    observacao      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_vendas_loja_data ON vendas(loja_id, data_hora);

CREATE TABLE IF NOT EXISTS itens_venda (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    venda_id             INTEGER NOT NULL REFERENCES vendas(id) ON DELETE CASCADE,
    produto_id           INTEGER REFERENCES produtos(id),
    nome_produto         TEXT NOT NULL,          -- cópia do nome no momento da venda
    quantidade           INTEGER NOT NULL CHECK (quantidade > 0),
    preco_unit_centavos  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS movimentos_estoque (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    loja_id     INTEGER NOT NULL REFERENCES lojas(id) ON DELETE CASCADE,
    produto_id  INTEGER NOT NULL REFERENCES produtos(id),
    data_hora   TEXT NOT NULL,
    tipo        TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida_venda', 'ajuste')),
    quantidade  INTEGER NOT NULL,                -- positivo entra, negativo sai
    venda_id    INTEGER REFERENCES vendas(id) ON DELETE SET NULL,
    observacao  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS avaliacoes (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    data_hora             TEXT NOT NULL,
    consentimento         INTEGER NOT NULL,
    atividade             TEXT NOT NULL DEFAULT '',
    tempo_empreende       TEXT NOT NULL DEFAULT '',
    controle_atual        TEXT NOT NULL DEFAULT '',
    usa_whatsapp          TEXT NOT NULL DEFAULT '',
    t5_cadastrou_produto  TEXT NOT NULL DEFAULT '',
    t6_pedido_whatsapp    TEXT NOT NULL DEFAULT '',
    t7_venda_estoque      TEXT NOT NULL DEFAULT '',
    t8_relatorio          TEXT NOT NULL DEFAULT '',
    t9_link_vitrine       TEXT NOT NULL DEFAULT '',
    facilidade            INTEGER NOT NULL CHECK (facilidade BETWEEN 1 AND 5),
    utilidade             INTEGER NOT NULL CHECK (utilidade BETWEEN 1 AND 5),
    funcoes               TEXT NOT NULL DEFAULT '',  -- separadas por " | "
    pretende_usar         TEXT NOT NULL DEFAULT '',
    dificuldades          TEXT NOT NULL DEFAULT '',
    sugestoes             TEXT NOT NULL DEFAULT '',
    depoimento            TEXT NOT NULL DEFAULT '',
    autoriza_depoimento   TEXT NOT NULL DEFAULT '',
    identificacao         TEXT NOT NULL DEFAULT ''
);
"""

# Opções do questionário (iguais às do questionário impresso)
TEMPO_EMPREENDE = ["Menos de 1 ano", "De 1 a 3 anos", "Mais de 3 anos"]
CONTROLE_ATUAL = ["Caderno/anotações", "Planilha", "De cabeça / não controlo", "Outro aplicativo", "Outro"]
SIM_NAO = ["Sim", "Não"]
RESULTADO_TAREFA = ["Consegui sozinho(a)", "Consegui com ajuda", "Não consegui", "Não testei"]
TAREFAS = [
    ("t5_cadastrou_produto", "5. Cadastrei um produto ou serviço"),
    ("t6_pedido_whatsapp", "6. Montei um pedido e enviei pelo WhatsApp"),
    ("t7_venda_estoque", "7. Registrei uma venda e vi o estoque baixar"),
    ("t8_relatorio", "8. Consultei o relatório de vendas"),
    ("t9_link_vitrine", "9. Gerei o link da minha vitrine"),
]
FUNCOES = [
    "Vitrine/catálogo com pedido pelo WhatsApp",
    "Controle de estoque e alerta de reposição",
    "Registro de vendas",
    "Relatório de vendas do dia/mês",
    "Backup em planilha (CSV)",
]
PRETENDE_USAR = ["Sim", "Talvez", "Não"]


class ErroValidacao(ValueError):
    """Erro de dado inválido, com mensagem pronta para mostrar ao usuário."""


class ErroEstoque(ValueError):
    """Venda com quantidade maior que o estoque disponível."""


# --------------------------------------------------------------------------
# Conexão
# --------------------------------------------------------------------------
def agora() -> str:
    return datetime.now(FUSO).replace(microsecond=0).isoformat(sep=" ")[:19]


@contextmanager
def conectar(caminho: str | None = None):
    """Abre uma conexão, cria as tabelas se preciso e faz commit/rollback."""
    con = sqlite3.connect(caminho or CAMINHO_PADRAO, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def iniciar_banco(caminho: str | None = None) -> None:
    with conectar(caminho) as con:
        con.executescript(ESQUEMA)


# --------------------------------------------------------------------------
# Utilitários
# --------------------------------------------------------------------------
def parse_preco(texto) -> int:
    """'12,50' / '12.50' / 'R$ 1.234,56' / '10' -> centavos. Erro se inválido."""
    s = re.sub(r"R\$|\s", "", str(texto or "")).strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
        raise ErroValidacao("Informe um preço válido (ex.: 12,50).")
    return round(float(s) * 100)


def moeda(centavos: int | None) -> str:
    """1250 -> 'R$ 12,50'"""
    v = (centavos or 0) / 100
    txt = f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {txt}"


def so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def normalizar_whatsapp(numero: str) -> str:
    """'(65) 99999-0000' -> '5565999990000'. Vazio se inválido."""
    d = so_digitos(numero)
    if len(d) in (10, 11):
        d = "55" + d
    return d if 12 <= len(d) <= 13 else ""


def gerar_slug(nome: str) -> str:
    s = unicodedata.normalize("NFD", nome).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:30] or "loja"
    return f"{s}-{secrets.token_hex(2)}"


def _hash_pin(pin: str, sal: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(sal), 200_000).hex()


def validar_pin(pin: str) -> None:
    if not re.fullmatch(r"\d{4}", pin or ""):
        raise ErroValidacao("O PIN deve ter exatamente 4 números.")


# --------------------------------------------------------------------------
# Lojas
# --------------------------------------------------------------------------
def criar_loja(nome: str, pin: str, whatsapp: str = "", caminho=None) -> dict:
    nome = (nome or "").strip()
    if not nome:
        raise ErroValidacao("Informe o nome do negócio.")
    if len(nome) > 60:
        raise ErroValidacao("O nome deve ter no máximo 60 caracteres.")
    validar_pin(pin)
    zap = normalizar_whatsapp(whatsapp)
    if whatsapp and not zap:
        raise ErroValidacao("WhatsApp inválido. Use DDD + número, ex.: (65) 99999-0000.")
    sal = secrets.token_hex(16)
    with conectar(caminho) as con:
        cur = con.execute(
            "INSERT INTO lojas (nome, slug, pin_hash, pin_sal, whatsapp, criado_em) VALUES (?, ?, ?, ?, ?, ?)",
            (nome, gerar_slug(nome), _hash_pin(pin, sal), sal, zap, agora()),
        )
        return obter_loja(cur.lastrowid, caminho, con=con)


def obter_loja(loja_id: int, caminho=None, con=None) -> dict | None:
    if con is None:
        with conectar(caminho) as c:
            return obter_loja(loja_id, con=c)
    r = con.execute(
        "SELECT id, nome, slug, whatsapp, estoque_minimo_padrao, criado_em FROM lojas WHERE id = ?", (loja_id,)
    ).fetchone()
    return dict(r) if r else None


def obter_loja_por_slug(slug: str, caminho=None) -> dict | None:
    with conectar(caminho) as con:
        r = con.execute(
            "SELECT id, nome, slug, whatsapp, estoque_minimo_padrao FROM lojas WHERE slug = ?", (slug,)
        ).fetchone()
        return dict(r) if r else None


def listar_lojas(caminho=None) -> list[dict]:
    with conectar(caminho) as con:
        return [dict(r) for r in con.execute("SELECT id, nome, slug FROM lojas ORDER BY nome COLLATE NOCASE")]


def verificar_pin(loja_id: int, pin: str, caminho=None) -> bool:
    with conectar(caminho) as con:
        r = con.execute("SELECT pin_hash, pin_sal FROM lojas WHERE id = ?", (loja_id,)).fetchone()
    if not r or not re.fullmatch(r"\d{4}", pin or ""):
        return False
    return hmac.compare_digest(r["pin_hash"], _hash_pin(pin, r["pin_sal"]))


def atualizar_loja(loja_id: int, nome: str, whatsapp: str, estoque_minimo_padrao: int, caminho=None) -> None:
    nome = (nome or "").strip()
    if not nome:
        raise ErroValidacao("Informe o nome do negócio.")
    zap = normalizar_whatsapp(whatsapp)
    if whatsapp and not zap:
        raise ErroValidacao("WhatsApp inválido. Use DDD + número, ex.: (65) 99999-0000.")
    if estoque_minimo_padrao < 0:
        raise ErroValidacao("O estoque mínimo padrão não pode ser negativo.")
    with conectar(caminho) as con:
        con.execute(
            "UPDATE lojas SET nome = ?, whatsapp = ?, estoque_minimo_padrao = ? WHERE id = ?",
            (nome, zap, int(estoque_minimo_padrao), loja_id),
        )


def trocar_pin(loja_id: int, pin_atual: str, pin_novo: str, caminho=None) -> None:
    if not verificar_pin(loja_id, pin_atual, caminho):
        raise ErroValidacao("PIN atual incorreto.")
    validar_pin(pin_novo)
    sal = secrets.token_hex(16)
    with conectar(caminho) as con:
        con.execute("UPDATE lojas SET pin_hash = ?, pin_sal = ? WHERE id = ?", (_hash_pin(pin_novo, sal), sal, loja_id))


# --------------------------------------------------------------------------
# Produtos
# --------------------------------------------------------------------------
def _validar_produto(nome, preco_centavos, estoque, estoque_minimo):
    erros = []
    if not (nome or "").strip():
        erros.append("Informe o nome do produto.")
    elif len(nome.strip()) > 80:
        erros.append("O nome deve ter no máximo 80 caracteres.")
    if not isinstance(preco_centavos, int) or preco_centavos <= 0:
        erros.append("Informe um preço maior que zero.")
    if not isinstance(estoque, int) or estoque < 0:
        erros.append("O estoque deve ser um número inteiro maior ou igual a zero.")
    if not isinstance(estoque_minimo, int) or estoque_minimo < 0:
        erros.append("O alerta de estoque mínimo deve ser maior ou igual a zero.")
    if erros:
        raise ErroValidacao(" ".join(erros))


def salvar_produto(loja_id: int, nome: str, categoria: str, preco_centavos: int, estoque: int,
                   estoque_minimo: int, na_vitrine: bool = True, foto: bytes | None = None,
                   foto_mime: str | None = None, produto_id: int | None = None,
                   remover_foto: bool = False, caminho=None) -> int:
    """Cria (produto_id=None) ou atualiza um produto. Retorna o id."""
    _validar_produto(nome, preco_centavos, estoque, estoque_minimo)
    nome, categoria, t = nome.strip(), (categoria or "").strip(), agora()
    with conectar(caminho) as con:
        if produto_id is None:
            cur = con.execute(
                """INSERT INTO produtos (loja_id, nome, categoria, preco_centavos, estoque, estoque_minimo,
                       foto, foto_mime, na_vitrine, criado_em, atualizado_em)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (loja_id, nome, categoria, preco_centavos, estoque, estoque_minimo,
                 foto, foto_mime, int(na_vitrine), t, t),
            )
            pid = cur.lastrowid
            if estoque > 0:
                con.execute(
                    "INSERT INTO movimentos_estoque (loja_id, produto_id, data_hora, tipo, quantidade, observacao) VALUES (?, ?, ?, 'entrada', ?, ?)",
                    (loja_id, pid, t, estoque, "Estoque inicial"),
                )
            return pid
        atual = con.execute(
            "SELECT estoque FROM produtos WHERE id = ? AND loja_id = ? AND ativo = 1", (produto_id, loja_id)
        ).fetchone()
        if not atual:
            raise ErroValidacao("Produto não encontrado.")
        con.execute(
            """UPDATE produtos SET nome = ?, categoria = ?, preco_centavos = ?, estoque = ?, estoque_minimo = ?,
                   na_vitrine = ?, atualizado_em = ? WHERE id = ? AND loja_id = ?""",
            (nome, categoria, preco_centavos, estoque, estoque_minimo, int(na_vitrine), t, produto_id, loja_id),
        )
        if foto is not None:
            con.execute("UPDATE produtos SET foto = ?, foto_mime = ? WHERE id = ? AND loja_id = ?",
                        (foto, foto_mime, produto_id, loja_id))
        elif remover_foto:
            con.execute("UPDATE produtos SET foto = NULL, foto_mime = NULL WHERE id = ? AND loja_id = ?",
                        (produto_id, loja_id))
        dif = estoque - atual["estoque"]
        if dif:
            con.execute(
                "INSERT INTO movimentos_estoque (loja_id, produto_id, data_hora, tipo, quantidade, observacao) VALUES (?, ?, ?, 'ajuste', ?, ?)",
                (loja_id, produto_id, t, dif, "Ajuste na edição do produto"),
            )
        return produto_id


def repor_estoque(loja_id: int, produto_id: int, quantidade: int, caminho=None) -> None:
    if not isinstance(quantidade, int) or quantidade <= 0:
        raise ErroValidacao("Informe uma quantidade maior que zero.")
    with conectar(caminho) as con:
        cur = con.execute(
            "UPDATE produtos SET estoque = estoque + ?, atualizado_em = ? WHERE id = ? AND loja_id = ? AND ativo = 1",
            (quantidade, agora(), produto_id, loja_id),
        )
        if cur.rowcount != 1:
            raise ErroValidacao("Produto não encontrado.")
        con.execute(
            "INSERT INTO movimentos_estoque (loja_id, produto_id, data_hora, tipo, quantidade, observacao) VALUES (?, ?, ?, 'entrada', ?, ?)",
            (loja_id, produto_id, agora(), quantidade, "Reposição"),
        )


def excluir_produto(loja_id: int, produto_id: int, caminho=None) -> None:
    """Exclusão lógica: some das telas, mas as vendas antigas continuam no relatório."""
    with conectar(caminho) as con:
        con.execute(
            "UPDATE produtos SET ativo = 0, na_vitrine = 0, foto = NULL, atualizado_em = ? WHERE id = ? AND loja_id = ?",
            (agora(), produto_id, loja_id),
        )


def listar_produtos(loja_id: int, somente_vitrine: bool = False, com_foto: bool = True, caminho=None) -> list[dict]:
    colunas = "id, nome, categoria, preco_centavos, estoque, estoque_minimo, na_vitrine, foto_mime" + (", foto" if com_foto else "")
    sql = f"SELECT {colunas} FROM produtos WHERE loja_id = ? AND ativo = 1"
    if somente_vitrine:
        sql += " AND na_vitrine = 1"
    sql += " ORDER BY nome COLLATE NOCASE"
    with conectar(caminho) as con:
        return [dict(r) for r in con.execute(sql, (loja_id,))]


def produtos_estoque_baixo(loja_id: int, caminho=None) -> list[dict]:
    with conectar(caminho) as con:
        return [dict(r) for r in con.execute(
            """SELECT id, nome, estoque, estoque_minimo FROM produtos
               WHERE loja_id = ? AND ativo = 1 AND estoque <= estoque_minimo
               ORDER BY estoque, nome COLLATE NOCASE""", (loja_id,))]


# --------------------------------------------------------------------------
# Vendas
# --------------------------------------------------------------------------
def registrar_venda(loja_id: int, itens: dict[int, int], forma_pagamento: str = "", observacao: str = "",
                    caminho=None) -> int:
    """itens = {produto_id: quantidade}. Baixa o estoque numa única transação."""
    itens = {int(k): int(v) for k, v in itens.items() if int(v) > 0}
    if not itens:
        raise ErroValidacao("Adicione pelo menos um produto à venda.")
    with conectar(caminho) as con:
        con.execute("BEGIN IMMEDIATE")  # trava escrita: evita duas vendas do mesmo estoque ao mesmo tempo
        marcadores = ",".join("?" * len(itens))
        prods = {r["id"]: r for r in con.execute(
            f"SELECT id, nome, preco_centavos, estoque FROM produtos WHERE loja_id = ? AND ativo = 1 AND id IN ({marcadores})",
            (loja_id, *itens.keys()))}
        faltando = []
        for pid, qtd in itens.items():
            p = prods.get(pid)
            if p is None:
                raise ErroValidacao("Um dos produtos da venda não existe mais.")
            if qtd > p["estoque"]:
                faltando.append(f"{p['nome']} (disponível: {p['estoque']})")
        if faltando:
            raise ErroEstoque("Estoque insuficiente: " + ", ".join(faltando))
        total = sum(prods[pid]["preco_centavos"] * q for pid, q in itens.items())
        t = agora()
        venda_id = con.execute(
            "INSERT INTO vendas (loja_id, data_hora, total_centavos, forma_pagamento, observacao) VALUES (?, ?, ?, ?, ?)",
            (loja_id, t, total, forma_pagamento or "", (observacao or "").strip()),
        ).lastrowid
        for pid, qtd in itens.items():
            p = prods[pid]
            con.execute(
                "INSERT INTO itens_venda (venda_id, produto_id, nome_produto, quantidade, preco_unit_centavos) VALUES (?, ?, ?, ?, ?)",
                (venda_id, pid, p["nome"], qtd, p["preco_centavos"]),
            )
            con.execute("UPDATE produtos SET estoque = estoque - ?, atualizado_em = ? WHERE id = ? AND loja_id = ?",
                        (qtd, t, pid, loja_id))
            con.execute(
                "INSERT INTO movimentos_estoque (loja_id, produto_id, data_hora, tipo, quantidade, venda_id, observacao) VALUES (?, ?, ?, 'saida_venda', ?, ?, '')",
                (loja_id, pid, t, -qtd, venda_id),
            )
        return venda_id


def cancelar_venda(loja_id: int, venda_id: int, caminho=None) -> None:
    """Exclui a venda e devolve os itens ao estoque."""
    with conectar(caminho) as con:
        con.execute("BEGIN IMMEDIATE")
        v = con.execute("SELECT id FROM vendas WHERE id = ? AND loja_id = ?", (venda_id, loja_id)).fetchone()
        if not v:
            raise ErroValidacao("Venda não encontrada.")
        t = agora()
        for it in con.execute("SELECT produto_id, quantidade FROM itens_venda WHERE venda_id = ?", (venda_id,)).fetchall():
            if it["produto_id"] is None:
                continue
            con.execute("UPDATE produtos SET estoque = estoque + ? WHERE id = ? AND loja_id = ?",
                        (it["quantidade"], it["produto_id"], loja_id))
            con.execute(
                "INSERT INTO movimentos_estoque (loja_id, produto_id, data_hora, tipo, quantidade, observacao) VALUES (?, ?, ?, 'ajuste', ?, ?)",
                (loja_id, it["produto_id"], t, it["quantidade"], f"Venda nº {venda_id} cancelada"),
            )
        con.execute("DELETE FROM vendas WHERE id = ? AND loja_id = ?", (venda_id, loja_id))


def _intervalo(inicio: date, fim_exclusivo: date) -> tuple[str, str]:
    return inicio.isoformat() + " 00:00:00", fim_exclusivo.isoformat() + " 00:00:00"


def listar_vendas(loja_id: int, inicio: date, fim_exclusivo: date, caminho=None) -> list[dict]:
    a, b = _intervalo(inicio, fim_exclusivo)
    with conectar(caminho) as con:
        vendas = [dict(r) for r in con.execute(
            "SELECT * FROM vendas WHERE loja_id = ? AND data_hora >= ? AND data_hora < ? ORDER BY data_hora DESC",
            (loja_id, a, b))]
        for v in vendas:
            v["itens"] = [dict(r) for r in con.execute(
                "SELECT nome_produto, quantidade, preco_unit_centavos FROM itens_venda WHERE venda_id = ?", (v["id"],))]
        return vendas


def resumo_periodo(loja_id: int, inicio: date, fim_exclusivo: date, caminho=None) -> dict:
    """Total vendido, nº de vendas, ticket médio, mais vendidos e total por dia."""
    a, b = _intervalo(inicio, fim_exclusivo)
    with conectar(caminho) as con:
        tot = con.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(total_centavos), 0) AS total FROM vendas WHERE loja_id = ? AND data_hora >= ? AND data_hora < ?",
            (loja_id, a, b)).fetchone()
        itens = con.execute(
            """SELECT COALESCE(SUM(i.quantidade), 0) FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
               WHERE v.loja_id = ? AND v.data_hora >= ? AND v.data_hora < ?""", (loja_id, a, b)).fetchone()[0]
        mais = [dict(r) for r in con.execute(
            """SELECT i.nome_produto AS produto, SUM(i.quantidade) AS quantidade,
                      SUM(i.quantidade * i.preco_unit_centavos) AS total_centavos
               FROM itens_venda i JOIN vendas v ON v.id = i.venda_id
               WHERE v.loja_id = ? AND v.data_hora >= ? AND v.data_hora < ?
               GROUP BY i.nome_produto ORDER BY quantidade DESC, total_centavos DESC, produto LIMIT 10""",
            (loja_id, a, b))]
        por_dia = [dict(r) for r in con.execute(
            """SELECT substr(data_hora, 1, 10) AS dia, COUNT(*) AS vendas, SUM(total_centavos) AS total_centavos
               FROM vendas WHERE loja_id = ? AND data_hora >= ? AND data_hora < ?
               GROUP BY dia ORDER BY dia""", (loja_id, a, b))]
        por_hora = [dict(r) for r in con.execute(
            """SELECT substr(data_hora, 12, 2) AS hora, SUM(total_centavos) AS total_centavos
               FROM vendas WHERE loja_id = ? AND data_hora >= ? AND data_hora < ?
               GROUP BY hora ORDER BY hora""", (loja_id, a, b))]
    n, total = tot["n"], tot["total"]
    return {"n_vendas": n, "total_centavos": total, "ticket_medio_centavos": round(total / n) if n else 0, "n_itens": itens,
            "mais_vendidos": mais, "por_dia": por_dia, "por_hora": por_hora}


# --------------------------------------------------------------------------
# Backup (dados para CSV)
# --------------------------------------------------------------------------
def dados_backup(loja_id: int, caminho=None) -> dict[str, list[dict]]:
    with conectar(caminho) as con:
        q = lambda sql: [dict(r) for r in con.execute(sql, (loja_id,))]  # noqa: E731
        return {
            "produtos": q("""SELECT id, nome, categoria, preco_centavos/100.0 AS preco, estoque, estoque_minimo,
                                    na_vitrine, criado_em, atualizado_em FROM produtos WHERE loja_id = ? AND ativo = 1
                             ORDER BY nome COLLATE NOCASE"""),
            "vendas": q("""SELECT v.id AS venda_id, v.data_hora, v.forma_pagamento, i.nome_produto AS produto,
                                  i.quantidade, i.preco_unit_centavos/100.0 AS preco_unit,
                                  i.quantidade*i.preco_unit_centavos/100.0 AS subtotal, v.total_centavos/100.0 AS total_venda,
                                  v.observacao
                           FROM vendas v JOIN itens_venda i ON i.venda_id = v.id WHERE v.loja_id = ?
                           ORDER BY v.data_hora, v.id"""),
            "movimentos_estoque": q("""SELECT m.data_hora, p.nome AS produto, m.tipo, m.quantidade, m.venda_id, m.observacao
                                       FROM movimentos_estoque m JOIN produtos p ON p.id = m.produto_id
                                       WHERE m.loja_id = ? ORDER BY m.data_hora, m.id"""),
        }


# --------------------------------------------------------------------------
# Avaliações (questionário de validação)
# --------------------------------------------------------------------------
CAMPOS_AVALIACAO = [
    "consentimento", "atividade", "tempo_empreende", "controle_atual", "usa_whatsapp",
    *[c for c, _ in TAREFAS], "facilidade", "utilidade", "funcoes", "pretende_usar",
    "dificuldades", "sugestoes", "depoimento", "autoriza_depoimento", "identificacao",
]


def salvar_avaliacao(resp: dict, caminho=None) -> int:
    if not resp.get("consentimento"):
        raise ErroValidacao("Marque que leu e concorda em participar.")
    for campo, nome in (("facilidade", "facilidade de uso"), ("utilidade", "utilidade")):
        if resp.get(campo) not in (1, 2, 3, 4, 5):
            raise ErroValidacao(f"Escolha uma nota de 1 a 5 para {nome}.")
    valores = dict(resp)
    if isinstance(valores.get("funcoes"), (list, tuple)):
        valores["funcoes"] = " | ".join(valores["funcoes"])
    valores["consentimento"] = 1
    linha = [valores.get(c) if valores.get(c) is not None else "" for c in CAMPOS_AVALIACAO]
    for i, c in enumerate(CAMPOS_AVALIACAO):
        if isinstance(linha[i], str):
            linha[i] = linha[i].strip()[:2000]
    with conectar(caminho) as con:
        cur = con.execute(
            f"INSERT INTO avaliacoes (data_hora, {', '.join(CAMPOS_AVALIACAO)}) VALUES (?, {', '.join('?' * len(CAMPOS_AVALIACAO))})",
            (agora(), *linha),
        )
        return cur.lastrowid


def listar_avaliacoes(caminho=None) -> list[dict]:
    with conectar(caminho) as con:
        return [dict(r) for r in con.execute("SELECT * FROM avaliacoes ORDER BY data_hora, id")]


def resumo_avaliacoes(caminho=None) -> dict:
    """Contagens e médias para o painel do pesquisador. Nada é estimado: tudo vem das respostas gravadas."""
    av = listar_avaliacoes(caminho)
    n = len(av)

    def contar(campo, opcoes):
        c = {o: 0 for o in opcoes}
        for a in av:
            if a[campo]:
                c[a[campo]] = c.get(a[campo], 0) + 1
        return c

    funcoes = {f: 0 for f in FUNCOES}
    for a in av:
        for f in filter(None, (x.strip() for x in a["funcoes"].split("|"))):
            funcoes[f] = funcoes.get(f, 0) + 1
    media = lambda campo: round(sum(a[campo] for a in av) / n, 2) if n else None  # noqa: E731
    return {
        "n": n,
        "media_facilidade": media("facilidade"),
        "media_utilidade": media("utilidade"),
        "dist_facilidade": {k: sum(1 for a in av if a["facilidade"] == k) for k in range(1, 6)},
        "dist_utilidade": {k: sum(1 for a in av if a["utilidade"] == k) for k in range(1, 6)},
        "tempo_empreende": contar("tempo_empreende", TEMPO_EMPREENDE),
        "controle_atual": contar("controle_atual", CONTROLE_ATUAL),
        "usa_whatsapp": contar("usa_whatsapp", SIM_NAO),
        "tarefas": {rot: contar(c, RESULTADO_TAREFA) for c, rot in TAREFAS},
        "funcoes": funcoes,
        "pretende_usar": contar("pretende_usar", PRETENDE_USAR),
        "comentarios": [
            {k: a[k] for k in ("id", "data_hora", "atividade", "dificuldades", "sugestoes", "depoimento",
                               "autoriza_depoimento", "identificacao")}
            for a in av if a["dificuldades"] or a["sugestoes"] or a["depoimento"]
        ],
    }
