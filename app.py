"""
app.py — Interface do Vitrine & Caixa (Python + Streamlit + SQLite).

Projeto de Extensão III — Ciência da Computação (Anhanguera / Unic Cuiabá)
Autor: Rafael Maria Iamin
Público: pequenos empreendedores da Associação Comunitária do Bairro Parque da Liberdade (Cuiabá/MT).

Telas:
  • Vitrine / Caixa — catálogo, carrinho, registrar venda (baixa estoque) e pedido pelo WhatsApp
  • Produtos        — cadastro, edição, reposição, exclusão e alerta de estoque baixo
  • Relatórios      — dia e mês: total, nº de vendas, ticket médio, mais vendidos e gráfico
  • Ajustes         — dados do negócio, link público da vitrine, backup CSV, troca de PIN
  • Avaliar         — questionário de validação (sem PIN), gravado no SQLite
  • Pesquisador     — resumo das avaliações (contagens, médias) e exportação CSV

Links especiais (parâmetros na URL):
  ?loja=<codigo>    vitrine pública da loja (para clientes, sem PIN)
  ?pagina=avaliar   abre direto o questionário de avaliação
"""
from __future__ import annotations

import base64
import csv
import hmac
import html
import io
import os
import time
import zipfile
from datetime import date, datetime, timedelta
from urllib.parse import quote

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps

import db

st.set_page_config(page_title="Vitrine & Caixa", page_icon="🛍️", layout="centered",
                   initial_sidebar_state="collapsed")

CSS = """
<style>
  :root { --cor:#0f766e; --zap:#16a34a; }
  .block-container { padding-top: 1rem; padding-bottom: 4rem; max-width: 720px; }
  header[data-testid="stHeader"] { display: none; }
  .topo { background:#0f766e; color:#fff; border-radius:14px; padding:12px 16px; margin-bottom:10px; }
  .topo h1 { font-size:1.2rem; margin:0; padding:0; color:#fff; }
  .topo p { margin:2px 0 0; color:#ccfbf1; font-size:.85rem; }
  .card { display:flex; gap:12px; align-items:center; background:#fff; border:1px solid #e2e8f0;
          border-radius:14px; padding:10px; margin:6px 0 2px; }
  .card .foto { width:64px; height:64px; flex:0 0 64px; border-radius:10px; background:#ccfbf1; color:#0f766e;
                display:flex; align-items:center; justify-content:center; font-weight:700; font-size:1.2rem; overflow:hidden; }
  .card .foto img { width:100%; height:100%; object-fit:cover; }
  .card .nome { font-weight:600; line-height:1.2; }
  .card .preco { color:#0f766e; font-weight:700; }
  .card .suave, .suave { color:#64748b; font-size:.85rem; }
  .baixo { color:#b45309; font-weight:600; }
  .alerta { background:#fef3c7; border:1px solid #fcd34d; color:#78350f; border-radius:12px; padding:10px 12px; margin:6px 0 10px; }
  .total { background:#0f766e; color:#fff; border-radius:12px; padding:10px 14px; font-size:1.05rem; margin:8px 0; }
  div.stButton > button, div.stDownloadButton > button, div.stLinkButton > a, div.stFormSubmitButton > button { min-height:44px; }
  [data-testid="stMetricValue"] { font-size:1.4rem; }
  /* no celular, manter colunas lado a lado (botões Editar/Repor/Excluir etc.) */
  [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: .5rem; }
  [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { min-width: 0 !important; width: auto !important; flex: 1 1 0 !important; }
  [data-testid="InputInstructions"] { display: none; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


@st.cache_resource
def _iniciar() -> bool:
    db.iniciar_banco()  # cria o arquivo e as tabelas na primeira execução
    return True


_iniciar()
ss = st.session_state
ss.setdefault("loja_id", None)
ss.setdefault("carrinho_v", 0)        # versão dos campos de quantidade (para zerar o carrinho)
ss.setdefault("tentativas", 0)
ss.setdefault("bloqueado_ate", 0.0)
ss.setdefault("admin_ok", False)


# --------------------------------------------------------------------------
# Utilitários de interface
# --------------------------------------------------------------------------
def esc(s) -> str:
    return html.escape(str(s or ""))


def topo(titulo: str, sub: str = "") -> None:
    st.markdown(f'<div class="topo"><h1>🛍️ {esc(titulo)}</h1>{f"<p>{esc(sub)}</p>" if sub else ""}</div>',
                unsafe_allow_html=True)


def url_base() -> str:
    """Endereço do app (para montar links). Pode ser fixado em secrets/variável APP_URL."""
    fixo = os.environ.get("APP_URL") or _segredo("APP_URL")
    if fixo:
        return fixo.rstrip("/") + "/"
    try:
        u = st.context.url  # Streamlit >= 1.46
        return u.split("?")[0].rstrip("/") + "/"
    except Exception:
        return "http://localhost:8501/"


def _segredo(chave: str) -> str:
    try:
        return str(st.secrets.get(chave, "") or "")
    except Exception:  # sem arquivo secrets.toml
        return ""


def iniciais(nome: str) -> str:
    partes = [p for p in nome.split() if len(p) > 2] or nome.split()
    return "".join(p[0] for p in partes[:2]).upper() or "?"


def cartao_produto(p: dict, mostrar_estoque_baixo: bool = False) -> str:
    if p.get("foto"):
        b64 = base64.b64encode(p["foto"]).decode()
        foto = f'<img src="data:{esc(p.get("foto_mime") or "image/jpeg")};base64,{b64}" alt="">'
    else:
        foto = esc(iniciais(p["nome"]))
    est = p["estoque"]
    if est <= 0:
        disp = '<span class="baixo">Esgotado</span>'
    elif mostrar_estoque_baixo and est <= p["estoque_minimo"]:
        disp = f'<span class="baixo">⚠️ {est} em estoque (mínimo {p["estoque_minimo"]})</span>'
    else:
        disp = f'{est} disponíve{"l" if est == 1 else "is"}'
    cat = f' · {esc(p["categoria"])}' if p.get("categoria") else ""
    return (f'<div class="card"><div class="foto">{foto}</div><div>'
            f'<div class="nome">{esc(p["nome"])}</div><div class="preco">{db.moeda(p["preco_centavos"])}</div>'
            f'<div class="suave">{disp}{cat}</div></div></div>')


def preparar_foto(arquivo) -> tuple[bytes, str] | None:
    """Reduz a foto para no máx. 480 px (economiza espaço no banco) e converte para JPEG."""
    if arquivo is None:
        return None
    try:
        img = ImageOps.exif_transpose(Image.open(arquivo)).convert("RGB")
    except Exception:
        st.error("Não consegui abrir essa imagem. Tente uma foto JPG ou PNG.")
        return None
    img.thumbnail((480, 480))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue(), "image/jpeg"


def link_whatsapp(numero: str, texto: str) -> str:
    return f"https://wa.me/{numero}?text={quote(texto)}" if numero else f"https://wa.me/?text={quote(texto)}"


def para_csv(linhas: list[dict]) -> bytes:
    buf = io.StringIO()
    if linhas:
        w = csv.DictWriter(buf, fieldnames=list(linhas[0].keys()), delimiter=";")
        w.writeheader()
        for linha in linhas:  # decimal com vírgula, padrão do Excel em português
            w.writerow({k: f"{v:.2f}".replace(".", ",") if isinstance(v, float) else v for k, v in linha.items()})
    return ("\ufeff" + buf.getvalue()).encode("utf-8")  # BOM: o Excel abre com acentos corretos


def fmt_telefone(numero: str) -> str:
    """'5565990000000' -> '(65) 99000-0000'"""
    d = numero[2:] if numero.startswith("55") else numero
    if len(d) == 11:
        return f"({d[:2]}) {d[2:7]}-{d[7:]}"
    if len(d) == 10:
        return f"({d[:2]}) {d[2:6]}-{d[6:]}"
    return d


def fmt_data(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")


MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
         "setembro", "outubro", "novembro", "dezembro"]


# --------------------------------------------------------------------------
# Carrinho (vitrine pública e caixa do dono)
# --------------------------------------------------------------------------
def tela_catalogo(loja: dict, modo_dono: bool) -> None:
    produtos = db.listar_produtos(loja["id"], somente_vitrine=not modo_dono)
    if modo_dono:
        baixos = db.produtos_estoque_baixo(loja["id"])
        if baixos:
            nomes = ", ".join(f"{b['nome']} ({b['estoque']})" for b in baixos[:4]) + ("…" if len(baixos) > 4 else "")
            st.markdown(f'<div class="alerta"><b>⚠️ {len(baixos)} produto{"s" if len(baixos) > 1 else ""} com estoque baixo:</b> '
                        f'{esc(nomes)}</div>', unsafe_allow_html=True)
    if not produtos:
        st.info("Nenhum produto cadastrado ainda." + (" Vá em **📦 Produtos** para cadastrar o primeiro." if modo_dono else ""))
        return
    busca = st.text_input("Buscar", placeholder="🔎 Buscar produto ou categoria", label_visibility="collapsed")
    if busca:
        t = db.unicodedata.normalize("NFD", busca).encode("ascii", "ignore").decode().lower()
        norm = lambda s: db.unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()  # noqa: E731
        produtos_vis = [p for p in produtos if t in norm(p["nome"]) or t in norm(p["categoria"])]
    else:
        produtos_vis = produtos
    v = ss.carrinho_v
    for p in produtos_vis:
        st.markdown(cartao_produto(p, mostrar_estoque_baixo=modo_dono), unsafe_allow_html=True)
        if p["estoque"] > 0:
            st.number_input(f"Quantidade de {p['nome']}", min_value=0, max_value=int(p["estoque"]), step=1,
                            key=f"q_{loja['id']}_{p['id']}_{v}", label_visibility="collapsed")
    if busca and not produtos_vis:
        st.caption("Nada encontrado.")

    # monta o carrinho a partir dos campos (inclusive de produtos escondidos pela busca)
    itens = []
    for p in produtos:
        q = int(ss.get(f"q_{loja['id']}_{p['id']}_{v}") or 0)
        if q > 0:
            itens.append((p, q))
    st.divider()
    if not itens:
        st.caption("Escolha as quantidades acima para montar o " + ("pedido / venda." if modo_dono else "pedido."))
        return
    total = sum(p["preco_centavos"] * q for p, q in itens)
    n = sum(q for _, q in itens)
    st.markdown(f'<div class="total">🛒 {n} ite{"m" if n == 1 else "ns"} · <b>{db.moeda(total)}</b></div>',
                unsafe_allow_html=True)
    for p, q in itens:
        st.markdown(f"- {q} × {p['nome']} — {db.moeda(p['preco_centavos'] * q)}")

    linhas = [f"*Pedido — {loja['nome']}*", ""] + [
        f"• {q}x {p['nome']} — {db.moeda(p['preco_centavos'] * q)}" for p, q in itens] + [
        "", f"*Total: {db.moeda(total)}*"]
    if not modo_dono:
        nome_cli = st.text_input("Seu nome (opcional)")
        obs = st.text_input("Observação (opcional)", placeholder="Ex.: entregar à tarde")
        if nome_cli:
            linhas.append(f"Nome: {nome_cli}")
        if obs:
            linhas.append(f"Obs.: {obs}")
        if loja["whatsapp"]:
            st.link_button("📲 Enviar pedido pelo WhatsApp", link_whatsapp(loja["whatsapp"], "\n".join(linhas)),
                           type="primary", width="stretch")
        else:
            st.warning("Esta loja ainda não informou o WhatsApp para pedidos.")
        if st.button("Limpar pedido", width="stretch"):
            ss.carrinho_v += 1
            st.rerun()
        return

    # modo dono: registrar a venda (baixa o estoque) e/ou mandar pelo WhatsApp
    forma = st.selectbox("Forma de pagamento", ["Dinheiro", "Pix", "Cartão de débito", "Cartão de crédito", "Fiado", "Outro"])
    obs = st.text_input("Observação (opcional)", key=f"obs_{v}")
    c1, c2 = st.columns(2)
    if c1.button("✅ Registrar venda", type="primary", width="stretch"):
        try:
            vid = db.registrar_venda(loja["id"], {p["id"]: q for p, q in itens}, forma, obs)
        except (db.ErroEstoque, db.ErroValidacao) as e:
            st.error(str(e))
        else:
            ss.carrinho_v += 1
            ss.msg = f"Venda nº {vid} registrada: {db.moeda(total)}. Estoque atualizado."
            st.rerun()
    c2.link_button("📲 Enviar pelo WhatsApp", link_whatsapp("", "\n".join(linhas)), width="stretch")
    st.caption("“Registrar venda” grava a venda e baixa o estoque. “Enviar pelo WhatsApp” manda o resumo para um cliente.")


# --------------------------------------------------------------------------
# Produtos
# --------------------------------------------------------------------------
@st.dialog("Produto")
def dialogo_produto(loja: dict, p: dict | None) -> None:
    with st.form("form_produto", border=False):
        nome = st.text_input("Nome *", value=p["nome"] if p else "", max_chars=80, placeholder="Ex.: Bolo de pote de chocolate")
        categoria = st.text_input("Categoria", value=p["categoria"] if p else "", placeholder="Ex.: Doces")
        preco = st.text_input("Preço (R$) *", value=db.moeda(p["preco_centavos"])[3:] if p else "", placeholder="12,50")
        c1, c2 = st.columns(2)
        estoque = c1.number_input("Estoque *", min_value=0, step=1, value=int(p["estoque"]) if p else 0)
        minimo = c2.number_input("Avisar quando chegar a", min_value=0, step=1,
                                 value=int(p["estoque_minimo"]) if p else int(loja["estoque_minimo_padrao"]))
        na_vitrine = st.checkbox("Mostrar na vitrine", value=bool(p["na_vitrine"]) if p else True)
        foto = st.file_uploader("Foto (opcional)", type=["jpg", "jpeg", "png", "webp"])
        remover = st.checkbox("Remover foto atual") if p and p.get("foto") else False
        ok = st.form_submit_button("💾 Salvar", type="primary", width="stretch")
    if ok:
        try:
            centavos = db.parse_preco(preco)
            f = preparar_foto(foto)
            db.salvar_produto(loja["id"], nome, categoria, centavos, int(estoque), int(minimo), na_vitrine,
                              foto=f[0] if f else None, foto_mime=f[1] if f else None,
                              produto_id=p["id"] if p else None, remover_foto=bool(remover))
        except db.ErroValidacao as e:
            st.error(str(e))
        else:
            ss.msg = f"Produto “{nome.strip()}” salvo."
            st.rerun()


@st.dialog("Repor estoque")
def dialogo_repor(loja: dict, p: dict) -> None:
    st.write(f"**{p['nome']}** — estoque atual: {p['estoque']}")
    qtd = st.number_input("Quantidade que chegou", min_value=1, step=1, value=1)
    if st.button("➕ Adicionar ao estoque", type="primary", width="stretch"):
        db.repor_estoque(loja["id"], p["id"], int(qtd))
        ss.msg = f"Estoque de “{p['nome']}” agora é {p['estoque'] + int(qtd)}."
        st.rerun()


@st.dialog("Excluir produto")
def dialogo_excluir(loja: dict, p: dict) -> None:
    st.write(f"Tem certeza que quer excluir **{p['nome']}**? As vendas antigas continuam no relatório.")
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Excluir", type="primary", width="stretch"):
        db.excluir_produto(loja["id"], p["id"])
        ss.msg = f"Produto “{p['nome']}” excluído."
        st.rerun()
    if c2.button("Cancelar", width="stretch"):
        st.rerun()


def tela_produtos(loja: dict) -> None:
    st.subheader("Produtos e estoque")
    if st.button("➕ Novo produto", type="primary", width="stretch"):
        dialogo_produto(loja, None)
    baixos = db.produtos_estoque_baixo(loja["id"])
    if baixos:
        st.markdown('<div class="alerta"><b>⚠️ Repor estoque:</b><br>' + "<br>".join(
            f"• {esc(b['nome'])}: {b['estoque']} (mínimo {b['estoque_minimo']})" for b in baixos) + "</div>",
            unsafe_allow_html=True)
    produtos = db.listar_produtos(loja["id"])
    if not produtos:
        st.info("Nenhum produto ainda. Toque em **➕ Novo produto**.")
        return
    st.caption(f"{len(produtos)} produto{'s' if len(produtos) > 1 else ''} · "
               f"valor em estoque: {db.moeda(sum(p['preco_centavos'] * p['estoque'] for p in produtos))}")
    for p in produtos:
        oculto = "" if p["na_vitrine"] else ' <span class="suave">(fora da vitrine)</span>'
        st.markdown(cartao_produto(p, mostrar_estoque_baixo=True).replace("</div></div></div>", f"{oculto}</div></div></div>", 1),
                    unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        if c1.button("✏️ Editar", key=f"ed_{p['id']}", width="stretch"):
            dialogo_produto(loja, p)
        if c2.button("➕ Repor", key=f"rp_{p['id']}", width="stretch"):
            dialogo_repor(loja, p)
        if c3.button("🗑️ Excluir", key=f"ex_{p['id']}", width="stretch"):
            dialogo_excluir(loja, p)


# --------------------------------------------------------------------------
# Relatórios
# --------------------------------------------------------------------------
@st.dialog("Cancelar venda")
def dialogo_cancelar_venda(loja: dict, venda: dict) -> None:
    st.write(f"Cancelar a venda nº {venda['id']} de {db.moeda(venda['total_centavos'])}? Os itens voltam para o estoque.")
    if st.button("Sim, cancelar venda", type="primary", width="stretch"):
        db.cancelar_venda(loja["id"], venda["id"])
        ss.msg = f"Venda nº {venda['id']} cancelada e estoque devolvido."
        st.rerun()


def tela_relatorios(loja: dict) -> None:
    st.subheader("Relatório de vendas")
    hoje = datetime.now(db.FUSO).date()
    periodo = st.segmented_control("Período", ["Dia", "Mês"], default="Dia", key="periodo",
                                   label_visibility="collapsed") or "Dia"
    if periodo == "Dia":
        dia = st.date_input("Dia", value=hoje, format="DD/MM/YYYY", max_value=hoje)
        inicio, fim = dia, dia + timedelta(days=1)
        rotulo = "Hoje" if dia == hoje else dia.strftime("%d/%m/%Y")
    else:
        opcoes = []
        a, m = hoje.year, hoje.month
        for _ in range(12):
            opcoes.append((a, m))
            a, m = (a, m - 1) if m > 1 else (a - 1, 12)
        a, m = st.selectbox("Mês", opcoes, format_func=lambda am: f"{MESES[am[1] - 1]} de {am[0]}")
        inicio = date(a, m, 1)
        fim = date(a + (m == 12), m % 12 + 1, 1)
        rotulo = f"{MESES[m - 1]} de {a}"

    r = db.resumo_periodo(loja["id"], inicio, fim)
    st.metric(f"Total vendido — {rotulo}", db.moeda(r["total_centavos"]))
    c1, c2, c3 = st.columns(3)
    c1.metric("Vendas", r["n_vendas"])
    c2.metric("Ticket médio", db.moeda(r["ticket_medio_centavos"]))
    c3.metric("Itens", r["n_itens"])
    if not r["n_vendas"]:
        st.info("Nenhuma venda neste período.")
        return

    st.markdown("**🏆 Mais vendidos**")
    st.dataframe(pd.DataFrame([{"Produto": x["produto"], "Qtd.": x["quantidade"], "Valor": db.moeda(x["total_centavos"])}
                               for x in r["mais_vendidos"]]), hide_index=True, width="stretch")

    if periodo == "Mês":
        st.markdown("**📈 Vendas por dia (R$)**")
        dias = pd.date_range(inicio, fim - timedelta(days=1)).strftime("%d").tolist()
        valores = {d["dia"][8:10]: d["total_centavos"] / 100 for d in r["por_dia"]}
        df = pd.DataFrame({"Dia": dias, "R$": [valores.get(d, 0.0) for d in dias]}).set_index("Dia")
    else:
        st.markdown("**📈 Vendas por hora (R$)**")
        df = pd.DataFrame({"Hora": [f"{h['hora']}h" for h in r["por_hora"]],
                           "R$": [h["total_centavos"] / 100 for h in r["por_hora"]]}).set_index("Hora")
    st.bar_chart(df, color="#0f766e", height=220)

    with st.expander(f"🧾 Vendas do período ({r['n_vendas']})"):
        for v in db.listar_vendas(loja["id"], inicio, fim):
            itens = ", ".join(f"{i['quantidade']}× {i['nome_produto']}" for i in v["itens"])
            st.markdown(f"**Nº {v['id']}** · {fmt_data(v['data_hora'])} · {db.moeda(v['total_centavos'])} · "
                        f"{v['forma_pagamento']}<br><span class='suave'>{esc(itens)}</span>", unsafe_allow_html=True)
            if st.button("Cancelar esta venda", key=f"cv_{v['id']}"):
                dialogo_cancelar_venda(loja, v)


# --------------------------------------------------------------------------
# Ajustes
# --------------------------------------------------------------------------
def tela_ajustes(loja: dict) -> None:
    st.subheader("Ajustes")
    with st.form("form_loja"):
        st.markdown("**Seu negócio**")
        nome = st.text_input("Nome do negócio", value=loja["nome"], max_chars=60)
        zap = st.text_input("WhatsApp que recebe os pedidos", value=fmt_telefone(loja["whatsapp"]),
                            placeholder="(65) 99999-9999", help="Com DDD. O app adiciona o 55 do Brasil sozinho.")
        minimo = st.number_input("Estoque mínimo padrão (alerta) para novos produtos", min_value=0, step=1,
                                 value=int(loja["estoque_minimo_padrao"]))
        if st.form_submit_button("💾 Salvar ajustes", type="primary", width="stretch"):
            try:
                db.atualizar_loja(loja["id"], nome, zap, int(minimo))
            except db.ErroValidacao as e:
                st.error(str(e))
            else:
                ss.msg = "Ajustes salvos."
                st.rerun()

    st.markdown("**🔗 Link da sua vitrine para clientes**")
    link = f"{url_base()}?loja={loja['slug']}"
    st.code(link, language=None, wrap_lines=True)
    st.caption("Mande esse link no WhatsApp ou no status. O cliente vê os produtos, monta o pedido e envia para o seu "
               "WhatsApp. Os preços e o estoque ficam sempre atualizados.")
    st.link_button("📲 Compartilhar link no WhatsApp",
                   link_whatsapp("", f"Confira os produtos da {loja['nome']} e faça seu pedido: {link}"),
                   width="stretch")

    st.markdown("**💾 Backup em planilha (CSV)**")
    dados = db.dados_backup(loja["id"])
    hoje = datetime.now(db.FUSO).strftime("%Y-%m-%d")
    pacote = io.BytesIO()
    with zipfile.ZipFile(pacote, "w", zipfile.ZIP_DEFLATED) as z:
        for nome_arq, linhas in dados.items():
            z.writestr(f"{nome_arq}.csv", para_csv(linhas))
    st.download_button("⬇️ Backup completo (.zip com 3 planilhas)", pacote.getvalue(),
                       file_name=f"backup_{loja['slug']}_{hoje}.zip", mime="application/zip", width="stretch")
    c1, c2 = st.columns(2)
    c1.download_button("⬇️ Produtos (CSV)", para_csv(dados["produtos"]), file_name=f"produtos_{hoje}.csv",
                       mime="text/csv", width="stretch", disabled=not dados["produtos"])
    c2.download_button("⬇️ Vendas (CSV)", para_csv(dados["vendas"]), file_name=f"vendas_{hoje}.csv",
                       mime="text/csv", width="stretch", disabled=not dados["vendas"])
    st.caption("O CSV abre no Excel, no Google Planilhas e no LibreOffice.")

    with st.expander("🔑 Trocar PIN"):
        with st.form("form_pin", clear_on_submit=True):
            atual = st.text_input("PIN atual", type="password", max_chars=4)
            novo = st.text_input("Novo PIN (4 números)", type="password", max_chars=4)
            if st.form_submit_button("Trocar PIN"):
                try:
                    db.trocar_pin(loja["id"], atual, novo)
                except db.ErroValidacao as e:
                    st.error(str(e))
                else:
                    st.success("PIN trocado.")


# --------------------------------------------------------------------------
# Avaliação (questionário de validação — sem PIN)
# --------------------------------------------------------------------------
def tela_avaliar() -> None:
    st.subheader("★ Avaliar o aplicativo")
    if ss.get("avaliacao_enviada"):
        st.success("Obrigado! Sua avaliação foi registrada. 🙏")
        if st.button("Responder outra avaliação (outra pessoa)"):
            ss.avaliacao_enviada = False
            st.rerun()
        return
    st.caption("Projeto de Extensão III – Ciência da Computação (Anhanguera / Unic Cuiabá). Responsável: Rafael Maria "
               "Iamin. Sua participação é voluntária e anônima; as respostas serão usadas somente no relatório "
               "acadêmico. Não é preciso escrever seu nome.")
    with st.form("form_avaliar"):
        consent = st.checkbox("Li e concordo em participar.")
        st.markdown("**Parte 1 – Perfil**")
        atividade = st.text_input("1. Qual é a sua atividade ou tipo de negócio?", placeholder="Ex.: doces, manicure, roupas")
        tempo = st.radio("2. Há quanto tempo você empreende?", db.TEMPO_EMPREENDE, index=None)
        controle = st.radio("3. Como você controla vendas e estoque hoje?", db.CONTROLE_ATUAL, index=None)
        controle_outro = st.text_input("Se marcou “Outro”, qual?")
        usa_zap = st.radio("4. Você já usa o WhatsApp para vender ou receber pedidos?", db.SIM_NAO, index=None, horizontal=True)
        st.markdown("**Parte 2 – Teste do aplicativo** (marque depois de testar)")
        tarefas = {c: st.radio(rot, db.RESULTADO_TAREFA, index=None, horizontal=True) for c, rot in db.TAREFAS}
        st.markdown("**Parte 3 – Opinião**")
        facil = st.radio("10. O aplicativo foi fácil de usar? (1 = muito difícil · 5 = muito fácil)", [1, 2, 3, 4, 5],
                         index=None, horizontal=True)
        util = st.radio("11. O aplicativo seria útil para o seu negócio? (1 = nada útil · 5 = muito útil)", [1, 2, 3, 4, 5],
                        index=None, horizontal=True)
        st.write("12. Quais funções você usaria? (pode marcar mais de uma)")
        funcoes = [f for i, f in enumerate(db.FUNCOES) if st.checkbox(f, key=f"fn_{i}")]
        pretende = st.radio("13. Você pretende usar o aplicativo no dia a dia?", db.PRETENDE_USAR, index=None, horizontal=True)
        dificuldades = st.text_area("14. O que foi mais difícil ou confuso?", height=80)
        sugestoes = st.text_area("15. Sugestões de melhoria:", height=80)
        depoimento = st.text_area("16. Deixe um depoimento sobre o aplicativo (opcional)", height=80)
        autoriza = st.radio("Autorizo o uso do depoimento no relatório", db.SIM_NAO, index=None, horizontal=True)
        ident = st.text_input("Como quer ser identificado(a) (opcional)", placeholder="Ex.: Ana, doceira")
        enviar = st.form_submit_button("Enviar avaliação", type="primary", width="stretch")
    if enviar:
        faltando = [n for n, v in (("2", tempo), ("3", controle), ("4", usa_zap), ("13", pretende)) if v is None]
        faltando += [rot.split(".")[0] for c, rot in db.TAREFAS if tarefas[c] is None]
        if not consent:
            st.error("Marque “Li e concordo em participar” para enviar.")
        elif facil is None or util is None:
            st.error("Escolha as notas de 1 a 5 das perguntas 10 e 11.")
        elif faltando:
            st.error("Responda também as perguntas: " + ", ".join(sorted(faltando, key=int)) + ".")
        else:
            db.salvar_avaliacao({
                "consentimento": True, "atividade": atividade, "tempo_empreende": tempo,
                "controle_atual": f"Outro: {controle_outro.strip()}" if controle == "Outro" and controle_outro.strip() else controle,
                "usa_whatsapp": usa_zap, **tarefas, "facilidade": facil, "utilidade": util, "funcoes": funcoes,
                "pretende_usar": pretende, "dificuldades": dificuldades, "sugestoes": sugestoes,
                "depoimento": depoimento, "autoriza_depoimento": autoriza or "", "identificacao": ident,
            })
            ss.avaliacao_enviada = True
            st.rerun()


# --------------------------------------------------------------------------
# Painel do pesquisador (resumo das avaliações)
# --------------------------------------------------------------------------
def tela_pesquisador() -> None:
    st.subheader("📋 Painel do pesquisador")
    senha_cfg = os.environ.get("ADMIN_SENHA") or _segredo("ADMIN_SENHA")
    if not senha_cfg:
        st.warning("Painel desativado: defina a senha ADMIN_SENHA nos *Secrets* do Streamlit Cloud "
                   "(ou na variável de ambiente ADMIN_SENHA) para liberar. Veja o README.")
        return
    if not ss.admin_ok:
        with st.form("form_admin"):
            s = st.text_input("Senha do pesquisador", type="password")
            if st.form_submit_button("Entrar", type="primary"):
                if hmac.compare_digest(s.encode(), senha_cfg.encode()):
                    ss.admin_ok = True
                    st.rerun()
                time.sleep(1)
                st.error("Senha incorreta.")
        return

    r = db.resumo_avaliacoes()
    st.caption(f"Link do questionário: {url_base()}?pagina=avaliar")
    if not r["n"]:
        st.info("Nenhuma avaliação recebida ainda.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("Respostas", r["n"])
    st.caption("Facilidade e utilidade: médias das notas de 1 a 5.")
    c2.metric("Facilidade (1–5)", f"{r['media_facilidade']:.2f}".replace(".", ","))
    c3.metric("Utilidade (1–5)", f"{r['media_utilidade']:.2f}".replace(".", ","))

    def tabela(titulo: str, contagem: dict) -> None:
        st.markdown(f"**{titulo}**")
        st.dataframe(pd.DataFrame([{"Resposta": k, "Qtd.": v, "%": f"{100 * v / r['n']:.0f}%"} for k, v in contagem.items()]),
                     hide_index=True, width="stretch")

    st.markdown("**Distribuição das notas**")
    st.bar_chart(pd.DataFrame({"Facilidade": r["dist_facilidade"], "Utilidade": r["dist_utilidade"]}),
                 stack=False, height=220)
    st.markdown("**Tarefas (Parte 2)**")
    st.dataframe(pd.DataFrame([{"Tarefa": t, **c} for t, c in r["tarefas"].items()]), hide_index=True,
                 width="stretch")
    tabela("12. Funções que usariam", r["funcoes"])
    tabela("13. Pretende usar no dia a dia", r["pretende_usar"])
    tabela("2. Tempo como empreendedor", r["tempo_empreende"])
    tabela("3. Controle atual", r["controle_atual"])
    tabela("4. Já usa WhatsApp para vender", r["usa_whatsapp"])
    if r["comentarios"]:
        st.markdown("**Comentários**")
        for c in r["comentarios"]:
            quem = c["identificacao"] or "Anônimo"
            partes = [f"**#{c['id']} · {fmt_data(c['data_hora'])} · {esc(c['atividade']) or '—'}**"]
            if c["dificuldades"]:
                partes.append(f"Dificuldade: {esc(c['dificuldades'])}")
            if c["sugestoes"]:
                partes.append(f"Sugestão: {esc(c['sugestoes'])}")
            if c["depoimento"]:
                aut = "autorizado" if c["autoriza_depoimento"] == "Sim" else "NÃO autorizado para o relatório"
                partes.append(f"Depoimento ({esc(quem)}, {aut}): “{esc(c['depoimento'])}”")
            st.markdown("<br>".join(partes), unsafe_allow_html=True)
    st.download_button("⬇️ Baixar todas as respostas (CSV)", para_csv(db.listar_avaliacoes()),
                       file_name=f"avaliacoes_{datetime.now(db.FUSO):%Y-%m-%d}.csv", mime="text/csv",
                       width="stretch")
    if st.button("Sair do painel"):
        ss.admin_ok = False
        st.rerun()


# --------------------------------------------------------------------------
# Entrar / criar loja
# --------------------------------------------------------------------------
def tela_entrar() -> None:
    lojas = db.listar_lojas()
    if not lojas:
        st.info("Nenhuma loja cadastrada ainda. Use **Criar minha loja**.")
        return
    bloqueio = ss.bloqueado_ate - time.time()
    with st.form("form_entrar"):
        loja = st.selectbox("Sua loja", lojas, format_func=lambda l: l["nome"], index=None, placeholder="Escolha sua loja…")
        pin = st.text_input("PIN (4 números)", type="password", max_chars=4)
        ok = st.form_submit_button("Entrar", type="primary", width="stretch")
    if ok:
        if bloqueio > 0:
            st.error(f"Muitas tentativas. Aguarde {int(bloqueio) + 1} segundos.")
        elif loja is None:
            st.error("Escolha sua loja.")
        elif db.verificar_pin(loja["id"], pin):
            ss.loja_id, ss.tentativas = loja["id"], 0
            st.rerun()
        else:
            ss.tentativas += 1
            if ss.tentativas >= 5:
                ss.bloqueado_ate, ss.tentativas = time.time() + 60, 0
            st.error("PIN incorreto.")


def tela_criar() -> None:
    with st.form("form_criar"):
        nome = st.text_input("Nome do negócio", max_chars=60, placeholder="Ex.: Doces da Ana")
        zap = st.text_input("WhatsApp para receber pedidos (opcional)", placeholder="(65) 99999-9999")
        pin = st.text_input("Crie um PIN de 4 números", type="password", max_chars=4)
        pin2 = st.text_input("Repita o PIN", type="password", max_chars=4)
        ok = st.form_submit_button("Criar minha loja", type="primary", width="stretch")
    st.caption("O PIN protege seus dados: cada empreendedor vê só os produtos e vendas da própria loja. "
               "Guarde bem o seu PIN.")
    if ok:
        if pin != pin2:
            st.error("Os dois PINs não são iguais.")
            return
        try:
            loja = db.criar_loja(nome, pin, zap)
        except db.ErroValidacao as e:
            st.error(str(e))
        else:
            ss.loja_id = loja["id"]
            ss.msg = f"Loja “{loja['nome']}” criada! Comece cadastrando seus produtos."
            ss.nav = "📦 Produtos"
            st.rerun()


# --------------------------------------------------------------------------
# Roteamento
# --------------------------------------------------------------------------
def mostrar_msg() -> None:
    if ss.get("msg"):
        st.success(ss.msg)
        ss.msg = None


qp = st.query_params

# 1) Vitrine pública: ?loja=codigo
if qp.get("loja"):
    loja_pub = db.obter_loja_por_slug(qp["loja"])
    if not loja_pub:
        topo("Vitrine & Caixa")
        st.error("Loja não encontrada. Confira o link.")
    else:
        topo(loja_pub["nome"], "Escolha os produtos e envie o pedido pelo WhatsApp")
        tela_catalogo(loja_pub, modo_dono=False)
        st.caption("Feito com Vitrine & Caixa — Projeto de Extensão (Anhanguera / Unic Cuiabá)")
    st.stop()

# 2) Questionário direto: ?pagina=avaliar
if qp.get("pagina") == "avaliar":
    topo("Vitrine & Caixa", "Avaliação do aplicativo")
    tela_avaliar()
    st.stop()

loja_atual = db.obter_loja(ss.loja_id) if ss.loja_id else None

if loja_atual is None:
    ss.loja_id = None
    topo("Vitrine & Caixa", "Vendas, estoque e pedidos pelo WhatsApp para pequenos negócios")
    pagina = st.segmented_control("Menu", ["Entrar", "Criar minha loja", "★ Avaliar", "📋 Pesquisador"],
                                  default="Entrar", key="nav_publica", label_visibility="collapsed") or "Entrar"
    mostrar_msg()
    {"Entrar": tela_entrar, "Criar minha loja": tela_criar, "★ Avaliar": tela_avaliar,
     "📋 Pesquisador": tela_pesquisador}[pagina]()
else:
    topo(loja_atual["nome"], "Vitrine & Caixa")
    ss.setdefault("nav", "🛍️ Vitrine")
    pagina = st.segmented_control("Menu", ["🛍️ Vitrine", "📦 Produtos", "📊 Relatórios", "⚙️ Ajustes", "★ Avaliar"],
                                  key="nav", label_visibility="collapsed") or "🛍️ Vitrine"
    mostrar_msg()
    if pagina == "🛍️ Vitrine":
        st.subheader("Vitrine e caixa")
        tela_catalogo(loja_atual, modo_dono=True)
    elif pagina == "📦 Produtos":
        tela_produtos(loja_atual)
    elif pagina == "📊 Relatórios":
        tela_relatorios(loja_atual)
    elif pagina == "⚙️ Ajustes":
        tela_ajustes(loja_atual)
        st.divider()
        if st.button("🚪 Sair da loja", width="stretch"):
            for k in list(ss.keys()):
                del ss[k]
            st.rerun()
    else:
        tela_avaliar()
