"""Testes automáticos das regras de negócio (rodar: python -m pytest -q)."""
import os
import sqlite3
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


@pytest.fixture()
def banco(tmp_path):
    caminho = str(tmp_path / "teste.db")
    db.iniciar_banco(caminho)
    return caminho


def test_dinheiro():
    assert db.parse_preco("12,50") == 1250
    assert db.parse_preco("R$ 1.234,56") == 123456
    assert db.parse_preco("10") == 1000
    assert db.parse_preco("0.1") == 10
    with pytest.raises(db.ErroValidacao):
        db.parse_preco("abc")
    assert db.moeda(123456) == "R$ 1.234,56"


def test_whatsapp():
    assert db.normalizar_whatsapp("(65) 99999-0000") == "5565999990000"
    assert db.normalizar_whatsapp("+55 65 3333-0000") == "556533330000"
    assert db.normalizar_whatsapp("123") == ""


def test_pin_hash_e_isolamento(banco):
    a = db.criar_loja("Loja A", "1234", caminho=banco)
    b = db.criar_loja("Loja B", "9876", caminho=banco)
    with sqlite3.connect(banco) as con:
        hashes = [r[0] for r in con.execute("SELECT pin_hash FROM lojas")]
    assert "1234" not in hashes and all(len(h) == 64 for h in hashes)
    assert db.verificar_pin(a["id"], "1234", banco)
    assert not db.verificar_pin(a["id"], "9876", banco)
    assert not db.verificar_pin(a["id"], "' OR 1=1 --", banco)
    db.salvar_produto(a["id"], "Bolo", "Doces", 1000, 5, 2, caminho=banco)
    assert db.listar_produtos(b["id"], caminho=banco) == []
    with pytest.raises(db.ErroValidacao):
        db.criar_loja("X", "12a4", caminho=banco)


def test_venda_baixa_estoque_e_alerta(banco):
    loja = db.criar_loja("Loja", "1111", caminho=banco)
    bolo = db.salvar_produto(loja["id"], "Bolo", "Doces", 1200, 5, 3, caminho=banco)
    suco = db.salvar_produto(loja["id"], "Suco", "Bebidas", 600, 10, 2, caminho=banco)
    assert db.produtos_estoque_baixo(loja["id"], banco) == []
    vid = db.registrar_venda(loja["id"], {bolo: 2, suco: 1}, "Pix", caminho=banco)
    est = {p["nome"]: p["estoque"] for p in db.listar_produtos(loja["id"], caminho=banco)}
    assert est == {"Bolo": 3, "Suco": 9}
    assert [p["nome"] for p in db.produtos_estoque_baixo(loja["id"], banco)] == ["Bolo"]  # 3 <= 3
    with pytest.raises(db.ErroEstoque):
        db.registrar_venda(loja["id"], {bolo: 4}, caminho=banco)
    assert db.listar_produtos(loja["id"], caminho=banco)[0]["estoque"] == 3  # nada mudou (transação)
    hoje = datetime.now(db.FUSO).date()
    r = db.resumo_periodo(loja["id"], hoje, hoje + timedelta(days=1), banco)
    assert r["n_vendas"] == 1 and r["total_centavos"] == 3000 and r["ticket_medio_centavos"] == 3000 and r["n_itens"] == 3
    assert r["mais_vendidos"][0] == {"produto": "Bolo", "quantidade": 2, "total_centavos": 2400}
    mes = db.resumo_periodo(loja["id"], hoje.replace(day=1), hoje + timedelta(days=1), banco)
    assert mes["total_centavos"] == 3000
    db.cancelar_venda(loja["id"], vid, banco)
    est = {p["nome"]: p["estoque"] for p in db.listar_produtos(loja["id"], caminho=banco)}
    assert est == {"Bolo": 5, "Suco": 10}


def test_edicao_reposicao_exclusao(banco):
    loja = db.criar_loja("Loja", "1111", caminho=banco)
    pid = db.salvar_produto(loja["id"], "Bolo", "", 1000, 1, 2, caminho=banco)
    db.repor_estoque(loja["id"], pid, 4, banco)
    db.salvar_produto(loja["id"], "Bolo de pote", "Doces", 1500, 6, 2, na_vitrine=False, produto_id=pid, caminho=banco)
    p = db.listar_produtos(loja["id"], caminho=banco)[0]
    assert (p["nome"], p["preco_centavos"], p["estoque"], p["na_vitrine"]) == ("Bolo de pote", 1500, 6, 0)
    assert db.listar_produtos(loja["id"], somente_vitrine=True, caminho=banco) == []
    mov = db.dados_backup(loja["id"], banco)["movimentos_estoque"]
    assert [m["quantidade"] for m in mov] == [1, 4, 1]
    db.excluir_produto(loja["id"], pid, banco)
    assert db.listar_produtos(loja["id"], caminho=banco) == []


def test_avaliacoes(banco):
    base = {"consentimento": True, "tempo_empreende": "De 1 a 3 anos", "controle_atual": "Caderno/anotações",
            "usa_whatsapp": "Sim", "t5_cadastrou_produto": "Consegui sozinho(a)", "pretende_usar": "Sim"}
    db.salvar_avaliacao({**base, "facilidade": 4, "utilidade": 5, "funcoes": [db.FUNCOES[0], db.FUNCOES[2]]}, banco)
    db.salvar_avaliacao({**base, "facilidade": 5, "utilidade": 4, "funcoes": [db.FUNCOES[0]], "sugestoes": "x"}, banco)
    with pytest.raises(db.ErroValidacao):
        db.salvar_avaliacao({**base, "facilidade": 6, "utilidade": 4}, banco)
    with pytest.raises(db.ErroValidacao):
        db.salvar_avaliacao({**base, "consentimento": False, "facilidade": 3, "utilidade": 4}, banco)
    r = db.resumo_avaliacoes(banco)
    assert r["n"] == 2 and r["media_facilidade"] == 4.5 and r["media_utilidade"] == 4.5
    assert r["funcoes"][db.FUNCOES[0]] == 2 and r["funcoes"][db.FUNCOES[2]] == 1
    assert r["tarefas"]["5. Cadastrei um produto ou serviço"]["Consegui sozinho(a)"] == 2
    assert len(r["comentarios"]) == 1


ESQUEMA_V1_VENDAS = """
CREATE TABLE lojas (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, slug TEXT NOT NULL UNIQUE,
    pin_hash TEXT NOT NULL, pin_sal TEXT NOT NULL, whatsapp TEXT NOT NULL DEFAULT '',
    estoque_minimo_padrao INTEGER NOT NULL DEFAULT 3, criado_em TEXT NOT NULL);
CREATE TABLE vendas (id INTEGER PRIMARY KEY AUTOINCREMENT, loja_id INTEGER NOT NULL REFERENCES lojas(id) ON DELETE CASCADE,
    data_hora TEXT NOT NULL, total_centavos INTEGER NOT NULL, forma_pagamento TEXT NOT NULL DEFAULT '',
    observacao TEXT NOT NULL DEFAULT '');
INSERT INTO lojas (nome, slug, pin_hash, pin_sal, criado_em) VALUES ('Antiga', 'antiga-0000', 'x', '00', '2026-11-01 10:00:00');
INSERT INTO vendas (loja_id, data_hora, total_centavos, forma_pagamento) VALUES (1, '2026-11-01 10:00:00', 1000, 'Pix');
INSERT INTO vendas (loja_id, data_hora, total_centavos, forma_pagamento) VALUES (1, '2026-11-01 11:00:00', 500, 'Fiado');
"""


def test_migracao_banco_antigo(tmp_path):
    """Banco da 1ª versão (sem cliente/pago) ganha as colunas novas sem perder vendas."""
    caminho = str(tmp_path / "antigo.db")
    with sqlite3.connect(caminho) as con:
        con.executescript(ESQUEMA_V1_VENDAS)
    db.iniciar_banco(caminho)
    db.iniciar_banco(caminho)  # idempotente
    with sqlite3.connect(caminho) as con:
        linhas = con.execute("SELECT total_centavos, forma_pagamento, cliente, pago FROM vendas ORDER BY id").fetchall()
    assert linhas == [(1000, "Pix", "", 1), (500, "Fiado", "", 0)]
    r = db.resumo_periodo(1, datetime(2026, 11, 1).date(), datetime(2026, 11, 2).date(), caminho)
    assert r["total_centavos"] == 1500 and r["recebido_centavos"] == 1000 and r["a_receber_centavos"] == 500


def test_fiado_cliente_e_graficos(banco):
    loja = db.criar_loja("Loja", "1111", caminho=banco)
    bolo = db.salvar_produto(loja["id"], "Bolo", "Doces", 1200, 10, 1, caminho=banco)
    suco = db.salvar_produto(loja["id"], "Suco", "", 600, 10, 1, caminho=banco)
    db.registrar_venda(loja["id"], {bolo: 1}, "Pix", caminho=banco, cliente="Ana")
    fiado = db.registrar_venda(loja["id"], {bolo: 1, suco: 2}, "Fiado", caminho=banco, cliente=" João ")
    hoje = datetime.now(db.FUSO).date()
    vendas = {v["id"]: v for v in db.listar_vendas(loja["id"], hoje, hoje + timedelta(days=1), banco)}
    assert vendas[fiado]["cliente"] == "João" and db.status_venda(vendas[fiado]) == "A RECEBER"
    r = db.resumo_periodo(loja["id"], hoje, hoje + timedelta(days=1), banco)
    assert (r["total_centavos"], r["recebido_centavos"], r["a_receber_centavos"]) == (3600, 1200, 2400)
    assert r["por_forma"] == [{"grupo": "Fiado", "total_centavos": 2400}, {"grupo": "Pix", "total_centavos": 1200}]
    assert r["por_categoria"] == [{"grupo": "Doces", "total_centavos": 2400}, {"grupo": "Sem categoria", "total_centavos": 1200}]
    db.marcar_venda_paga(loja["id"], fiado, caminho=banco)
    r = db.resumo_periodo(loja["id"], hoje, hoje + timedelta(days=1), banco)
    assert r["a_receber_centavos"] == 0 and r["recebido_centavos"] == 3600
    outra = db.criar_loja("Outra", "2222", caminho=banco)
    with pytest.raises(db.ErroValidacao):
        db.marcar_venda_paga(outra["id"], fiado, caminho=banco)  # não mexe em venda de outra loja
    assert {v["situacao"] for v in db.dados_backup(loja["id"], banco)["vendas"]} == {"pago"}
