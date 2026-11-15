"""
app.py — Interface do Vitrine & Caixa (Python + Streamlit + SQLite).

Projeto de Extensão III — Ciência da Computação (Anhanguera / Unic Cuiabá)
Autor: Rafael Maria Iamin
Público: pequenos empreendedores da Associação Comunitária do Bairro Parque da Liberdade (Cuiabá/MT).

Telas:
  • Vendas          — painel DIA/MÊS: faturamento, recebido, a receber (fiado), ticket médio, lista de vendas
                      com etiquetas de pagamento, marcar fiado como pago, cancelar venda e gráficos de rosca
  • Nova venda      — catálogo/caixa, carrinho, registrar venda (baixa estoque) e pedido pelo WhatsApp
  • Estoque         — cadastro, edição, reposição, exclusão e alerta de estoque baixo
  • Opções          — dados do negócio, link público da vitrine, backup CSV, troca de PIN
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
import plotly.graph_objects as go
import streamlit as st
from PIL import Image, ImageOps

import db

st.set_page_config(page_title="Vitrine & Caixa", page_icon="🛍️", layout="wide",
                   initial_sidebar_state="auto")

# Paleta (roxo/magenta + verde de destaque)
ROXO, MAGENTA, VERDE, LARANJA = "#9b1fe8", "#c026d3", "#16a34a", "#f59e0b"
PALETA = ["#9b1fe8", "#c026d3", "#22c55e", "#f59e0b", "#3b82f6", "#ef4444", "#14b8a6", "#a3a3a3"]

CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap');
  :root { --roxo:#9b1fe8; --magenta:#c026d3; --verde:#16a34a; --texto:#1f1534; --suave:#6b6880;
          --borda:#ece8f3; --sombra:0 4px 18px rgba(46,16,101,.07); }
  html, body, .stApp, .stMarkdown, p, label, input, textarea, button, h1, h2, h3, h4 { font-family:'Poppins', sans-serif; }
  .stApp { background:#f6f5fa; }
  .block-container { padding-top:1.4rem; padding-bottom:9rem; max-width:1240px; }
  [data-testid="stHeader"] { background:transparent; }
  [data-testid="stToolbar"], [data-testid="stDecoration"] { display:none; }
  [data-testid="InputInstructions"] { display:none; }

  /* ---------- barra lateral ---------- */
  section[data-testid="stSidebar"] { background:#fff; border-right:1px solid var(--borda); }
  section[data-testid="stSidebar"] .block-container, section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding-top:1rem; }
  .logo { display:flex; align-items:center; gap:10px; margin:0 0 6px 2px; }
  .logo b { font-size:1.08rem; color:var(--texto); font-weight:700; letter-spacing:-.2px; }
  .logo b span { color:var(--magenta); }
  .logo small { display:block; color:var(--suave); font-size:.72rem; font-weight:400; margin-top:-2px; }
  .lojanome { background:#f6f0ff; color:#5b1a99; border-radius:12px; padding:8px 12px; font-size:.82rem; margin:10px 0 14px; }
  .lojanome b { display:block; font-size:.92rem; color:var(--texto); }
  section[data-testid="stSidebar"] .stButton button > div { justify-content:flex-start; width:100%; }
  [data-testid="stSidebarHeader"] { height:2.2rem; min-height:0; }
  @media (min-width: 768px) { .block-container { padding-left:2.2rem; padding-right:2.2rem; padding-top:1.6rem; } }
  section[data-testid="stSidebar"] .stButton button { justify-content:flex-start; border-radius:12px; min-height:46px;
       padding:0 14px; font-weight:500; }
  section[data-testid="stSidebar"] .stButton button[kind="tertiary"] { color:#4b4760; }
  section[data-testid="stSidebar"] .stButton button[kind="tertiary"]:hover { background:#f6f0ff; color:var(--roxo); }
  section[data-testid="stSidebar"] .stButton button[kind="primary"] { background:linear-gradient(90deg,#f3e8ff,#fae8ff);
       color:var(--roxo); border:none; box-shadow:inset 3px 0 0 var(--roxo); font-weight:600; }
  .st-key-sair button { color:#b42318 !important; }

  /* ---------- botões ---------- */
  .stButton button, .stDownloadButton button, .stLinkButton a, .stFormSubmitButton button { min-height:44px; border-radius:999px; font-weight:500; }
  .stButton button[kind="primary"], .stFormSubmitButton button[kind="primaryFormSubmit"], .stLinkButton a[kind="primary"] {
       background:linear-gradient(90deg,var(--roxo),var(--magenta)); border:none; color:#fff; box-shadow:0 6px 16px rgba(155,31,232,.25); }
  .stButton button[kind="secondary"], .stDownloadButton button, .stLinkButton a[kind="secondary"] { background:#fff; border:1px solid #e3dcef; }
  .st-key-fab, .st-key-registrar, .st-key-zap { }
  .st-key-registrar button, .st-key-zap a, .st-key-fab button {
       background:linear-gradient(90deg,#16a34a,#22c55e) !important; color:#fff !important; border:none !important;
       box-shadow:0 8px 20px rgba(22,163,74,.30) !important; font-weight:600; letter-spacing:.3px; }
  .st-key-fab { position:fixed; right:32px; bottom:28px; z-index:1000; width:auto !important; }
  .st-key-fab button { min-height:54px; padding:0 26px; text-transform:uppercase; font-size:.95rem; }

  /* ---------- cartões ---------- */
  [class*="st-key-card"] { background:#fff; border:1px solid var(--borda); border-radius:18px; box-shadow:var(--sombra);
       padding:16px 18px; }
  .ctitle { font-weight:600; font-size:1rem; color:var(--texto); margin:0 0 2px; }
  .csub { color:var(--suave); font-size:.8rem; margin:0 0 6px; }
  .cab { margin:2px 0 12px; }
  .cab h2 { font-size:1.55rem; font-weight:700; color:var(--texto); margin:0; padding:0; letter-spacing:-.4px; }
  .cab p { margin:0; color:var(--suave); font-size:.9rem; }
  .suave { color:var(--suave); font-size:.85rem; }
  .baixo { color:#b45309; font-weight:600; }
  .alerta { background:#fff7e6; border:1px solid #fcd9a0; color:#7a3e00; border-radius:14px; padding:10px 14px; margin:4px 0 12px; font-size:.9rem; }

  /* produto */
  .pcard { display:flex; gap:12px; align-items:center; }
  .pcard .foto { width:64px; height:64px; flex:0 0 64px; border-radius:14px; background:linear-gradient(135deg,#f3e8ff,#fae8ff);
       color:var(--roxo); display:flex; align-items:center; justify-content:center; font-weight:700; font-size:1.15rem; overflow:hidden; }
  .pcard .foto img { width:100%; height:100%; object-fit:cover; }
  .pcard .nome { font-weight:600; line-height:1.25; color:var(--texto); }
  .pcard .preco { color:var(--roxo); font-weight:700; }
  .tag { display:inline-block; background:#f3f1f8; color:#5c5873; border-radius:999px; padding:1px 9px; font-size:.72rem; margin-left:2px; }

  /* KPIs */
  .kpis { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:14px; margin:6px 0 16px; }
  .kpi { background:#fff; border:1px solid var(--borda); border-radius:18px; box-shadow:var(--sombra); padding:16px; display:flex; gap:12px; align-items:center; }
  .kpi .ic { width:46px; height:46px; flex:0 0 46px; border-radius:14px; display:flex; align-items:center; justify-content:center; }
  .kpi .kl { color:var(--suave); font-size:.8rem; }
  .kpi .kv { color:var(--texto); font-size:1.28rem; font-weight:700; line-height:1.25; white-space:nowrap; }
  .kpi .ks { color:var(--suave); font-size:.74rem; }

  /* lista de vendas */
  [class*="st-key-venda_"] { background:#fff; border:1px solid var(--borda); border-radius:16px; padding:10px 8px 10px 14px; }
  .vrow { display:flex; gap:12px; align-items:center; }
  .vrow .av { width:42px; height:42px; flex:0 0 42px; border-radius:50%; background:linear-gradient(135deg,var(--roxo),var(--magenta));
       color:#fff; display:flex; align-items:center; justify-content:center; font-weight:600; font-size:.85rem; }
  .vrow .vi { flex:1 1 auto; min-width:0; }
  .vrow .vt { font-weight:600; color:var(--texto); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .vrow .vs { color:var(--suave); font-size:.8rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .vrow .vr { text-align:right; flex:0 0 auto; }
  .vrow .vv { font-weight:700; color:var(--texto); }
  .vrow .vp { margin-top:3px; }
  table.top { width:100%; border-collapse:collapse; font-size:.85rem; margin-top:6px; border:none !important; }
  table.top th, table.top td { border-left:none !important; border-right:none !important; border-top:none !important; background:transparent !important; }
  table.top th { text-align:left; color:var(--suave); font-weight:500; font-size:.75rem; padding:4px 6px; border-bottom:1px solid var(--borda); }
  table.top td { padding:7px 6px; border-bottom:1px solid #f3f0f8; color:var(--texto); }
  table.top th:nth-child(n+2), table.top td:nth-child(n+2) { text-align:right; white-space:nowrap; }
  table.top .rk { display:inline-flex; width:20px; height:20px; border-radius:50%; background:#f3e8ff; color:var(--roxo);
       font-size:.7rem; font-weight:700; align-items:center; justify-content:center; margin-right:8px; }
  .pill { display:inline-block; border-radius:999px; padding:2px 10px; font-size:.68rem; font-weight:600; letter-spacing:.4px; margin-right:4px; }
  .st-key-navpub button[aria-checked="true"] { background:var(--roxo) !important; color:#fff !important; border-color:var(--roxo) !important; }
  .st-key-navpub button { background:#fff; }
  .p-ok { background:#dcfce7; color:#15803d; }  .p-rec { background:#ffedd5; color:#c2410c; }
  .p-pix { background:#ccfbf1; color:#0f766e; } .p-din { background:#ecfccb; color:#4d7c0f; }
  .p-car { background:#dbeafe; color:#1d4ed8; } .p-fia { background:#fae8ff; color:#a21caf; } .p-out { background:#f1f5f9; color:#475569; }

  /* legenda das roscas */
  .leg { display:flex; flex-direction:column; gap:6px; margin-top:4px; }
  .leg div { display:flex; align-items:center; gap:8px; font-size:.82rem; color:#3f3b52; }
  .leg i { width:10px; height:10px; border-radius:50%; flex:0 0 10px; }
  .leg span.n { flex:1 1 auto; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .leg b { font-weight:600; color:var(--texto); }
  .leg .suave { white-space:nowrap; font-size:.76rem; }
  [class*="st-key-card_donut"] { min-height:400px; }
  @media (max-width: 767.98px) { [class*="st-key-card_donut"] { min-height:0; } }

  /* abas DIA / MÊS e chips de data */
  .st-key-periodo [data-testid="stButtonGroup"] { background:#fff; border-radius:999px; padding:4px; border:1px solid var(--borda); width:fit-content; }
  .st-key-periodo button { border:none !important; border-radius:999px !important; text-transform:uppercase; font-weight:600; letter-spacing:.6px; min-width:96px; }
  .st-key-periodo button[aria-checked="true"] { background:linear-gradient(90deg,var(--roxo),var(--magenta)) !important; color:#fff !important; }
  .st-key-chips [data-testid="stButtonGroup"], .st-key-chips [data-testid="stButtonGroup"] > div { flex-wrap:nowrap !important; overflow-x:auto; padding-bottom:6px; scrollbar-width:thin; }
  .st-key-chips button { flex:0 0 auto !important; max-width:none !important; border-radius:14px !important; background:#fff; border:1px solid var(--borda) !important; white-space:nowrap; min-height:40px; }
  .st-key-chips button[aria-checked="true"] { background:var(--roxo) !important; color:#fff !important; border-color:var(--roxo) !important; }

  /* total do carrinho */
  .total { background:linear-gradient(90deg,var(--roxo),var(--magenta)); color:#fff; border-radius:16px; padding:12px 16px; font-size:1.05rem; margin:4px 0 8px; }
  .hero { background:linear-gradient(120deg,var(--roxo),var(--magenta)); color:#fff; border-radius:22px; padding:20px 22px; margin-bottom:14px; box-shadow:0 10px 30px rgba(155,31,232,.25); }
  .hero h1 { color:#fff; font-size:1.45rem; margin:0; padding:0; font-weight:700; }
  .hero p { color:#f5e9ff; margin:2px 0 0; font-size:.9rem; }

  /* linhas de botões sempre lado a lado (também no celular) */
  [class*="st-key-acoes"] [data-testid="stHorizontalBlock"], [class*="st-key-venda_"] [data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important; gap:.5rem; }
  [class*="st-key-acoes"] [data-testid="stColumn"], [class*="st-key-venda_"] [data-testid="stColumn"] { min-width:0 !important; width:auto !important; }
  [class*="st-key-venda_"] [data-testid="stColumn"]:last-child { flex:0 0 48px !important; }

  /* menu do celular: aparece só em telas pequenas; a barra lateral fica no computador */
  .st-key-navmob { display:none; }
  @media (max-width: 767.98px) {
    .block-container { padding-top:.6rem; padding-left:.8rem; padding-right:.8rem; }
    [data-testid="stHeader"], section[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] { display:none; }
    .st-key-navmob { display:block; position:sticky; top:0; z-index:999; background:#f6f5fa; padding:4px 0 6px; }
    .st-key-navmob [data-testid="stButtonGroup"], .st-key-navmob [data-testid="stButtonGroup"] > div { flex-wrap:nowrap !important; overflow-x:auto; }
    .st-key-navmob .stElementContainer, .st-key-navmob [data-testid="stButtonGroup"], .st-key-navmob [data-testid="stButtonGroup"] > div { width:100% !important; max-width:100% !important; gap:4px; }
    .st-key-navmob button { flex:1 1 0 !important; max-width:none !important; white-space:nowrap; min-height:54px; padding:4px 2px !important;
         font-size:.72rem; border-radius:14px !important; }
    .st-key-navmob button > div > span { display:flex; flex-direction:column; align-items:center; gap:1px; }
    .st-key-navmob button [data-testid="stIconMaterial"] { font-size:1.25rem; margin:0; }
    .st-key-navmob button p { font-size:.72rem; }
    .st-key-navmob button[aria-checked="true"] { background:var(--roxo) !important; color:#fff !important; }
    .kpis { grid-template-columns:repeat(2, minmax(0,1fr)); gap:10px; }
    .kpi { padding:12px; gap:10px; flex-direction:column; align-items:flex-start; }
    .kpi .ic { width:38px; height:38px; flex-basis:38px; }
    .kpi .kv { font-size:1.08rem; }
    .cab h2 { font-size:1.3rem; }
    .st-key-fab { right:16px; bottom:16px; }
    [class*="st-key-card"] { padding:12px 12px; }
  }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

LOGO_SVG = (
    '<svg width="40" height="40" viewBox="0 0 40 40" aria-hidden="true"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">'
    '<stop offset="0" stop-color="#9b1fe8"/><stop offset="1" stop-color="#c026d3"/></linearGradient></defs>'
    '<rect width="40" height="40" rx="12" fill="url(#lg)"/>'
    '<path d="M11 17h18l-1.7-5.3a1.4 1.4 0 0 0-1.3-.9H14a1.4 1.4 0 0 0-1.3.9z M12.5 17v11.2c0 .5.4.8.8.8h13.4c.4 0 .8-.3.8-.8V17" '
    'fill="none" stroke="#fff" stroke-width="2.2" stroke-linejoin="round"/>'
    '<path d="M17.5 29v-5.5h5V29" fill="none" stroke="#fff" stroke-width="2.2" stroke-linejoin="round"/></svg>')
ICONE_MOEDAS = ('<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round"><ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/>'
                '<path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/></svg>')
ICONE_RECIBO = ('<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h12v20l-3-2-3 2-3-2-3 2z"/><path d="M9 7h6M9 11h6M9 15h4"/></svg>')
ICONE_RELOGIO = ('<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" '
                 'stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>')
ICONE_CHECK = ('<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.2" '
               'stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></svg>')


@st.cache_resource
def _iniciar() -> bool:
    db.iniciar_banco()  # cria o arquivo e as tabelas na primeira execução (e migra bancos antigos)
    return True


_iniciar()
ss = st.session_state
ss.setdefault("loja_id", None)
ss.setdefault("carrinho_v", 0)        # versão dos campos de quantidade (para zerar o carrinho)
ss.setdefault("tentativas", 0)
ss.setdefault("bloqueado_ate", 0.0)
ss.setdefault("admin_ok", False)
ss.setdefault("pagina", "vendas")


# --------------------------------------------------------------------------
# Utilitários de interface
# --------------------------------------------------------------------------
def esc(s) -> str:
    return html.escape(str(s or ""))


def cabecalho(titulo: str, sub: str = "") -> None:
    """Título da página (área logada)."""
    st.markdown(f'<div class="cab"><h2>{esc(titulo)}</h2>{f"<p>{esc(sub)}</p>" if sub else ""}</div>',
                unsafe_allow_html=True)


def topo(titulo: str, sub: str = "") -> None:
    """Faixa colorida com logo (telas públicas)."""
    st.markdown(f'<div class="hero"><div style="display:flex;gap:12px;align-items:center">'
                f'<div style="background:#fff;border-radius:14px;padding:3px;display:flex">{LOGO_SVG}</div>'
                f'<div><h1>{esc(titulo)}</h1>{f"<p>{esc(sub)}</p>" if sub else ""}</div></div></div>',
                unsafe_allow_html=True)


def largura_max(px: int) -> None:
    st.markdown(f"<style>.block-container {{ max-width:{px}px; }}</style>", unsafe_allow_html=True)


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


def cartao_produto(p: dict, mostrar_estoque_baixo: bool = False, extra: str = "") -> str:
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
    cat = f' <span class="tag">{esc(p["categoria"])}</span>' if p.get("categoria") else ""
    return (f'<div class="pcard"><div class="foto">{foto}</div><div>'
            f'<div class="nome">{esc(p["nome"])}</div><div class="preco">{db.moeda(p["preco_centavos"])}</div>'
            f'<div class="suave">{disp}{cat}{extra}</div></div></div>')


def kpis(cartoes: list[tuple[str, str, str, str, str]]) -> None:
    """cartoes = [(rótulo, valor, subtítulo, ícone_svg, cor)]"""
    partes = []
    for rotulo, valor, sub, icone, cor in cartoes:
        partes.append(f'<div class="kpi"><div class="ic" style="background:{cor}1a;color:{cor}">{icone}</div><div>'
                      f'<div class="kl">{esc(rotulo)}</div><div class="kv">{esc(valor)}</div>'
                      f'<div class="ks">{esc(sub)}</div></div></div>')
    st.markdown(f'<div class="kpis">{"".join(partes)}</div>', unsafe_allow_html=True)


CLASSE_FORMA = {"Pix": "p-pix", "Dinheiro": "p-din", "Cartão de débito": "p-car", "Cartão de crédito": "p-car",
                "Fiado": "p-fia"}
ROTULO_FORMA = {"Cartão de débito": "DÉBITO", "Cartão de crédito": "CRÉDITO", "Dinheiro": "À VISTA"}


def pills_venda(v: dict) -> str:
    forma = v.get("forma_pagamento") or ""
    p = ""
    if forma:
        p += f'<span class="pill {CLASSE_FORMA.get(forma, "p-out")}">{esc(ROTULO_FORMA.get(forma, forma.upper()))}</span>'
    status = db.status_venda(v)
    p += f'<span class="pill {"p-ok" if status == "PAGO" else "p-rec"}">{status}</span>'
    return p


def donut(titulo: str, dados: list[tuple[str, int]], chave: str) -> None:
    """Gráfico de rosca (valores em centavos) com legenda e porcentagens."""
    dados = [(k, v) for k, v in dados if v > 0]
    with st.container(key=f"card_donut_{chave}"):
        st.markdown(f'<div class="ctitle">{esc(titulo)}</div>', unsafe_allow_html=True)
        if not dados:
            st.caption("Sem vendas no período.")
            return
        if len(dados) > len(PALETA):  # agrupa o excesso em "Outros"
            dados = dados[:len(PALETA) - 1] + [("Outros", sum(v for _, v in dados[len(PALETA) - 1:]))]
        total = sum(v for _, v in dados)
        cores = PALETA[:len(dados)]
        fig = go.Figure(go.Pie(
            labels=[k for k, _ in dados], values=[v / 100 for _, v in dados], hole=.66, sort=False,
            marker=dict(colors=cores, line=dict(color="#ffffff", width=2)), textinfo="none",
            hovertemplate="%{label}<br>R$ %{value:,.2f} · %{percent}<extra></extra>"))
        fig.update_layout(height=190, margin=dict(l=0, r=0, t=6, b=6), showlegend=False, separators=",.",
                          paper_bgcolor="rgba(0,0,0,0)", font=dict(family="Poppins, sans-serif"),
                          annotations=[dict(text=f"<b>{db.moeda(total)}</b><br><span style='font-size:11px;color:#6b6880'>total</span>",
                                            showarrow=False, font=dict(size=14, color="#1f1534"))])
        st.plotly_chart(fig, config={"displayModeBar": False}, key=f"pl_{chave}")
        leg = "".join(f'<div><i style="background:{c}"></i><span class="n">{esc(k)}</span>'
                      f'<b>{100 * v / total:.0f}%</b><span class="suave">{db.moeda(v)}</span></div>'
                      for (k, v), c in zip(dados, cores))
        st.markdown(f'<div class="leg">{leg}</div>', unsafe_allow_html=True)


def grafico_barras(rotulos: list[str], valores: list[float], altura: int = 230, cor: str = ROXO, chave: str = "") -> None:
    fig = go.Figure(go.Bar(x=rotulos, y=valores, marker=dict(color=cor, cornerradius=6),
                           hovertemplate="%{x}: R$ %{y:,.2f}<extra></extra>"))
    fig.update_layout(height=altura, margin=dict(l=0, r=0, t=6, b=0), separators=",.", bargap=.35,
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Poppins, sans-serif", size=11),
                      xaxis=dict(type="category", showgrid=False), yaxis=dict(gridcolor="#eee9f5", tickprefix="R$ "))
    st.plotly_chart(fig, config={"displayModeBar": False}, key=f"bar_{chave}")


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
DIAS_SEMANA = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def em_grade(itens: list, colunas: int = 2):
    """Distribui itens em linhas de N colunas (no celular as colunas empilham)."""
    for i in range(0, len(itens), colunas):
        cols = st.columns(colunas)
        for c, item in zip(cols, itens[i:i + colunas]):
            yield c, item


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
        st.info("Nenhum produto cadastrado ainda." + (" Vá em **Estoque e cadastros** para cadastrar o primeiro." if modo_dono else ""))
        return
    col_prod, col_cart = st.columns([1.55, 1], gap="large")
    with col_prod:
        busca = st.text_input("Buscar", placeholder="🔎 Buscar produto ou categoria", label_visibility="collapsed")
        if busca:
            t = db.unicodedata.normalize("NFD", busca).encode("ascii", "ignore").decode().lower()
            norm = lambda s: db.unicodedata.normalize("NFD", s or "").encode("ascii", "ignore").decode().lower()  # noqa: E731
            produtos_vis = [p for p in produtos if t in norm(p["nome"]) or t in norm(p["categoria"])]
        else:
            produtos_vis = produtos
        v = ss.carrinho_v
        for col, p in em_grade(produtos_vis, 2):
            with col, st.container(key=f"card_prod_{p['id']}"):
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
    with col_cart, st.container(key="card_carrinho"):
        st.markdown('<div class="ctitle">🛒 ' + ("Venda atual" if modo_dono else "Seu pedido") + "</div>", unsafe_allow_html=True)
        if not itens:
            st.caption("Escolha as quantidades ao lado para montar o " + ("pedido / venda." if modo_dono else "pedido."))
            return
        total = sum(p["preco_centavos"] * q for p, q in itens)
        n = sum(q for _, q in itens)
        st.markdown(f'<div class="total">{n} ite{"m" if n == 1 else "ns"} · <b>{db.moeda(total)}</b></div>',
                    unsafe_allow_html=True)
        st.markdown("\n".join(f"- {q} × {p['nome']} — {db.moeda(p['preco_centavos'] * q)}" for p, q in itens))

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
                with st.container(key="zap"):
                    st.link_button("📲 Enviar pedido pelo WhatsApp", link_whatsapp(loja["whatsapp"], "\n".join(linhas)),
                                   width="stretch")
            else:
                st.warning("Esta loja ainda não informou o WhatsApp para pedidos.")
            if st.button("Limpar pedido", width="stretch"):
                ss.carrinho_v += 1
                st.rerun()
            return

        # modo dono: registrar a venda (baixa o estoque) e/ou mandar pelo WhatsApp
        cliente = st.text_input("Cliente (opcional)", key=f"cli_{v}", placeholder="Ex.: Dona Maria")
        forma = st.selectbox("Forma de pagamento", db.FORMAS_PAGAMENTO, key=f"forma_{v}",
                             help="“Fiado” fica como A RECEBER até você marcar como pago em Vendas.")
        obs = st.text_input("Observação (opcional)", key=f"obs_{v}")
        if cliente:
            linhas.append(f"Cliente: {cliente}")
        with st.container(key="registrar"):
            registrar = st.button("✅ Registrar venda", width="stretch")
        if registrar:
            try:
                vid = db.registrar_venda(loja["id"], {p["id"]: q for p, q in itens}, forma, obs, cliente=cliente)
            except (db.ErroEstoque, db.ErroValidacao) as e:
                st.error(str(e))
            else:
                ss.carrinho_v += 1
                ss.msg = f"Venda nº {vid} registrada: {db.moeda(total)}. Estoque atualizado."
                st.rerun()
        st.link_button("📲 Enviar pelo WhatsApp", link_whatsapp("", "\n".join(linhas)), width="stretch")
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
    c1, c2 = st.columns([3, 1.2], vertical_alignment="bottom")
    with c1:
        cabecalho("Estoque e cadastros", "Produtos, preços, fotos e alerta de reposição")
    with c2:
        if st.button("➕ Novo produto", type="primary", width="stretch"):
            dialogo_produto(loja, None)
    produtos = db.listar_produtos(loja["id"])
    baixos = db.produtos_estoque_baixo(loja["id"])
    if produtos:
        kpis([
            ("Produtos cadastrados", str(len(produtos)), f"{sum(1 for p in produtos if p['na_vitrine'])} na vitrine", ICONE_RECIBO, ROXO),
            ("Valor em estoque", db.moeda(sum(p["preco_centavos"] * p["estoque"] for p in produtos)), "preço × quantidade",
             ICONE_MOEDAS, MAGENTA),
            ("Unidades em estoque", str(sum(p["estoque"] for p in produtos)), "somando todos os produtos", ICONE_CHECK, VERDE),
            ("Estoque baixo", str(len(baixos)), "precisam de reposição" if baixos else "tudo em dia", ICONE_RELOGIO, LARANJA),
        ])
    if baixos:
        st.markdown('<div class="alerta"><b>⚠️ Repor estoque:</b><br>' + "<br>".join(
            f"• {esc(b['nome'])}: {b['estoque']} (mínimo {b['estoque_minimo']})" for b in baixos) + "</div>",
            unsafe_allow_html=True)
    if not produtos:
        st.info("Nenhum produto ainda. Toque em **➕ Novo produto**.")
        return
    for col, p in em_grade(produtos, 2):
        oculto = "" if p["na_vitrine"] else ' <span class="tag">fora da vitrine</span>'
        with col, st.container(key=f"card_cad_{p['id']}"):
            st.markdown(cartao_produto(p, mostrar_estoque_baixo=True, extra=oculto), unsafe_allow_html=True)
            with st.container(key=f"acoes_{p['id']}"):
                b1, b2, b3 = st.columns(3)
                if b1.button("✏️ Editar", key=f"ed_{p['id']}", width="stretch"):
                    dialogo_produto(loja, p)
                if b2.button("➕ Repor", key=f"rp_{p['id']}", width="stretch"):
                    dialogo_repor(loja, p)
                if b3.button("🗑️ Excluir", key=f"ex_{p['id']}", width="stretch"):
                    dialogo_excluir(loja, p)


# --------------------------------------------------------------------------
# Vendas (painel: dia / mês)
# --------------------------------------------------------------------------
@st.dialog("Cancelar venda")
def dialogo_cancelar_venda(loja: dict, venda: dict) -> None:
    st.write(f"Cancelar a venda nº {venda['id']} de {db.moeda(venda['total_centavos'])}? Os itens voltam para o estoque.")
    if st.button("Sim, cancelar venda", type="primary", width="stretch"):
        db.cancelar_venda(loja["id"], venda["id"])
        ss.msg = f"Venda nº {venda['id']} cancelada e estoque devolvido."
        st.rerun()


def _escolher_periodo(hoje: date) -> tuple[str, date, date, str]:
    periodo = st.segmented_control("Período", ["Dia", "Mês"], default="Dia", key="periodo",
                                   label_visibility="collapsed") or "Dia"
    with st.container(key="chips"):
        if periodo == "Dia":
            dias = [hoje - timedelta(days=i) for i in range(14)] + ["outra"]

            def rot(d):
                if d == "outra":
                    return "📅 Outra data"
                if d == hoje:
                    return f"Hoje {d.day:02d}"
                if d == hoje - timedelta(days=1):
                    return f"Ontem {d.day:02d}"
                return f"{DIAS_SEMANA[d.weekday()]} {d.day:02d}/{d.month:02d}"
            esc_dia = st.pills("Dia", dias, default=hoje, format_func=rot, key="chip_dia", label_visibility="collapsed")
            if esc_dia == "outra":
                dia = st.date_input("Dia", value=hoje, format="DD/MM/YYYY", max_value=hoje)
            else:
                dia = esc_dia or hoje
            rotulo = "hoje" if dia == hoje else dia.strftime("%d/%m/%Y")
            return periodo, dia, dia + timedelta(days=1), rotulo
        opcoes = []  # "AAAA-MM" dos últimos 12 meses
        a, m = hoje.year, hoje.month
        for _ in range(12):
            opcoes.append(f"{a}-{m:02d}")
            a, m = (a, m - 1) if m > 1 else (a - 1, 12)
        am = st.pills("Mês", opcoes, default=opcoes[0], key="chip_mes", label_visibility="collapsed",
                      format_func=lambda x: f"{MESES[int(x[5:]) - 1][:3].capitalize()}/{x[2:4]}") or opcoes[0]
        a, m = int(am[:4]), int(am[5:])
        return periodo, date(a, m, 1), date(a + (m == 12), m % 12 + 1, 1), f"{MESES[m - 1]} de {a}"


def linha_venda(loja: dict, v: dict, mostrar_dia: bool) -> None:
    itens = ", ".join(f"{i['quantidade']}× {i['nome_produto']}" for i in v["itens"])
    quem = v.get("cliente") or f"Venda nº {v['id']}"
    hora = datetime.fromisoformat(v["data_hora"]).strftime("%d/%m %H:%M" if mostrar_dia else "%H:%M")
    av = iniciais(v["cliente"]) if v.get("cliente") else "#"
    sub = f"nº {v['id']} · " if v.get("cliente") else ""
    with st.container(key=f"venda_{v['id']}"):
        c1, c2 = st.columns([12, 1], vertical_alignment="center")
        c1.markdown(f'<div class="vrow"><div class="av">{esc(av)}</div><div class="vi"><div class="vt">{esc(quem)}</div>'
                    f'<div class="vs">{esc(sub)}{esc(itens)}</div><div class="vp">{pills_venda(v)}</div></div><div class="vr"><div class="vv">'
                    f'{db.moeda(v["total_centavos"])}</div><div class="vs">{hora}</div></div></div>',
                    unsafe_allow_html=True)
        with c2.popover("⋮", help="Ações da venda"):
            st.caption(f"Venda nº {v['id']} · {fmt_data(v['data_hora'])}" + (f" · Obs.: {v['observacao']}" if v.get("observacao") else ""))
            if v.get("pago", 1):
                if v.get("forma_pagamento") in db.FORMAS_A_PRAZO and st.button("Voltar para a receber", key=f"ar_{v['id']}"):
                    db.marcar_venda_paga(loja["id"], v["id"], False)
                    st.rerun()
            elif st.button("✅ Marcar como pago", key=f"pg_{v['id']}", type="primary"):
                db.marcar_venda_paga(loja["id"], v["id"], True)
                ss.msg = f"Venda nº {v['id']} marcada como paga."
                st.rerun()
            if st.button("Cancelar esta venda", key=f"cv_{v['id']}"):
                dialogo_cancelar_venda(loja, v)


def tela_vendas(loja: dict) -> None:
    cabecalho("Vendas", f"Resumo de vendas da {loja['nome']}")
    hoje = datetime.now(db.FUSO).date()
    periodo, inicio, fim, rotulo = _escolher_periodo(hoje)
    r = db.resumo_periodo(loja["id"], inicio, fim)
    kpis([
        ("Faturamento bruto", db.moeda(r["total_centavos"]),
         f"Total vendido · {r['n_vendas']} venda{'s' if r['n_vendas'] != 1 else ''}", ICONE_MOEDAS, ROXO),
        ("Recebido", db.moeda(r["recebido_centavos"]), "vendas pagas", ICONE_CHECK, VERDE),
        ("A receber (fiado)", db.moeda(r["a_receber_centavos"]), "ainda não pagas", ICONE_RELOGIO, LARANJA),
        ("Ticket médio", db.moeda(r["ticket_medio_centavos"]), f"{r['n_itens']} ite{'m' if r['n_itens'] == 1 else 'ns'} vendidos",
         ICONE_RECIBO, MAGENTA),
    ])
    with st.container(key="fab"):
        if st.button("Nova venda", icon=":material/add:", key="btn_fab"):
            ss.pagina = "caixa"
            st.rerun()
    if not r["n_vendas"]:
        st.info("Nenhuma venda neste período. Toque em **+ NOVA VENDA** para registrar.")
        return

    esq, dir_ = st.columns([1.35, 1], gap="medium")
    with esq, st.container(key="card_lista"):
        vendas = db.listar_vendas(loja["id"], inicio, fim)
        st.markdown(f'<div class="ctitle">🧾 Vendas — {esc(rotulo)} ({len(vendas)})</div>'
                    f'<div class="csub">Toque em ⋮ para marcar como pago ou cancelar</div>', unsafe_allow_html=True)
        lista = st.container(height=520, border=False) if len(vendas) > 6 else st.container(border=False)
        with lista:
            for v in vendas:
                linha_venda(loja, v, mostrar_dia=periodo == "Mês")
    with dir_:
        with st.container(key="card_mais"):
            linhas = "".join(f'<tr><td><span class="rk">{i}</span>{esc(x["produto"])}</td><td>{x["quantidade"]}</td>'
                             f'<td>{db.moeda(x["total_centavos"])}</td></tr>' for i, x in enumerate(r["mais_vendidos"], 1))
            st.markdown('<div class="ctitle">🏆 Mais vendidos</div><table class="top"><thead><tr><th>Produto</th><th>Qtd.</th>'
                        f'<th>Valor</th></tr></thead><tbody>{linhas}</tbody></table>', unsafe_allow_html=True)
        with st.container(key="card_barras"):
            if periodo == "Mês":
                st.markdown('<div class="ctitle">📈 Vendas por dia (R$)</div>', unsafe_allow_html=True)
                dias = pd.date_range(inicio, fim - timedelta(days=1)).strftime("%d").tolist()
                valores = {d["dia"][8:10]: d["total_centavos"] / 100 for d in r["por_dia"]}
                grafico_barras(dias, [valores.get(d, 0.0) for d in dias], chave="mes")
            else:
                st.markdown('<div class="ctitle">📈 Vendas por hora (R$)</div>', unsafe_allow_html=True)
                valores = {int(h["hora"]): h["total_centavos"] / 100 for h in r["por_hora"]}
                horas = sorted(set(range(7, 21)) | set(valores))  # horário comercial + horas com venda
                grafico_barras([f"{h:02d}h" for h in horas], [valores.get(h, 0.0) for h in horas], chave="dia")

    d1, d2, d3 = st.columns(3, gap="medium")
    soma_top = sum(x["total_centavos"] for x in r["mais_vendidos"])
    por_produto = [(x["produto"], x["total_centavos"]) for x in r["mais_vendidos"]]
    if r["total_centavos"] - soma_top > 0:
        por_produto.append(("Outros", r["total_centavos"] - soma_top))
    with d1:
        donut("Vendas por produto", por_produto, "produto")
    with d2:
        donut("Vendas por categoria", [(x["grupo"], x["total_centavos"]) for x in r["por_categoria"]], "categoria")
    with d3:
        donut("Vendas por forma de pagamento", [(x["grupo"], x["total_centavos"]) for x in r["por_forma"]], "forma")


# --------------------------------------------------------------------------
# Opções (ajustes)
# --------------------------------------------------------------------------
def tela_ajustes(loja: dict) -> None:
    cabecalho("Opções", "Dados do negócio, link da vitrine, backup e PIN")
    c_esq, c_dir = st.columns(2, gap="medium")
    with c_esq, st.container(key="card_negocio"):
        with st.form("form_loja", border=False):
            st.markdown('<div class="ctitle">🏪 Seu negócio</div>', unsafe_allow_html=True)
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
        with st.expander("🔑 Trocar PIN"):
            with st.form("form_pin", clear_on_submit=True, border=False):
                atual = st.text_input("PIN atual", type="password", max_chars=4)
                novo = st.text_input("Novo PIN (4 números)", type="password", max_chars=4)
                if st.form_submit_button("Trocar PIN"):
                    try:
                        db.trocar_pin(loja["id"], atual, novo)
                    except db.ErroValidacao as e:
                        st.error(str(e))
                    else:
                        st.success("PIN trocado.")

    with c_dir:
        with st.container(key="card_link"):
            st.markdown('<div class="ctitle">🔗 Link da sua vitrine para clientes</div>', unsafe_allow_html=True)
            link = f"{url_base()}?loja={loja['slug']}"
            st.code(link, language=None, wrap_lines=True)
            st.caption("Mande esse link no WhatsApp ou no status. O cliente vê os produtos, monta o pedido e envia para o seu "
                       "WhatsApp. Os preços e o estoque ficam sempre atualizados.")
            with st.container(key="zap"):
                st.link_button("📲 Compartilhar link no WhatsApp",
                               link_whatsapp("", f"Confira os produtos da {loja['nome']} e faça seu pedido: {link}"),
                               width="stretch")
        with st.container(key="card_backup"):
            st.markdown('<div class="ctitle">💾 Backup em planilha (CSV)</div>', unsafe_allow_html=True)
            dados = db.dados_backup(loja["id"])
            hoje = datetime.now(db.FUSO).strftime("%Y-%m-%d")
            pacote = io.BytesIO()
            with zipfile.ZipFile(pacote, "w", zipfile.ZIP_DEFLATED) as z:
                for nome_arq, linhas in dados.items():
                    z.writestr(f"{nome_arq}.csv", para_csv(linhas))
            st.download_button("⬇️ Backup completo (.zip com 3 planilhas)", pacote.getvalue(),
                               file_name=f"backup_{loja['slug']}_{hoje}.zip", mime="application/zip", width="stretch")
            with st.container(key="acoes_backup"):
                c1, c2 = st.columns(2)
                c1.download_button("⬇️ Produtos (CSV)", para_csv(dados["produtos"]), file_name=f"produtos_{hoje}.csv",
                                   mime="text/csv", width="stretch", disabled=not dados["produtos"])
                c2.download_button("⬇️ Vendas (CSV)", para_csv(dados["vendas"]), file_name=f"vendas_{hoje}.csv",
                                   mime="text/csv", width="stretch", disabled=not dados["vendas"])
            st.caption("O CSV abre no Excel, no Google Planilhas e no LibreOffice.")


# --------------------------------------------------------------------------
# Avaliação (questionário de validação — sem PIN)
# --------------------------------------------------------------------------
def tela_avaliar() -> None:
    with st.container(key="card_avaliar"):
        st.markdown('<div class="cab"><h2>★ Avaliar o aplicativo</h2></div>', unsafe_allow_html=True)
        if ss.get("avaliacao_enviada"):
            st.success("Obrigado! Sua avaliação foi registrada. 🙏")
            if st.button("Responder outra avaliação (outra pessoa)"):
                ss.avaliacao_enviada = False
                st.rerun()
            return
        st.caption("Projeto de Extensão III – Ciência da Computação (Anhanguera / Unic Cuiabá). Responsável: Rafael Maria "
                   "Iamin. Sua participação é voluntária e anônima; as respostas serão usadas somente no relatório "
                   "acadêmico. Não é preciso escrever seu nome.")
        with st.form("form_avaliar", border=False):
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
    st.markdown('<div class="cab"><h2>📋 Painel do pesquisador</h2><p>Resumo das avaliações recebidas</p></div>',
                unsafe_allow_html=True)
    senha_cfg = os.environ.get("ADMIN_SENHA") or _segredo("ADMIN_SENHA")
    if not senha_cfg:
        st.warning("Painel desativado: defina a senha ADMIN_SENHA nos *Secrets* do Streamlit Cloud "
                   "(ou na variável de ambiente ADMIN_SENHA) para liberar. Veja o README.")
        return
    if not ss.admin_ok:
        with st.container(key="card_admin"), st.form("form_admin", border=False):
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
        if st.button("Sair do painel"):
            ss.admin_ok = False
            st.rerun()
        return
    f2 = lambda x: f"{x:.2f}".replace(".", ",")  # noqa: E731
    sim = r["pretende_usar"].get("Sim", 0)
    kpis([
        ("Respostas", str(r["n"]), "avaliações gravadas", ICONE_RECIBO, ROXO),
        ("Facilidade (1–5)", f2(r["media_facilidade"]), "média das notas", ICONE_CHECK, VERDE),
        ("Utilidade (1–5)", f2(r["media_utilidade"]), "média das notas", ICONE_MOEDAS, MAGENTA),
        ("Pretendem usar", f"{100 * sim / r['n']:.0f}%", f"{sim} de {r['n']} responderam “Sim”", ICONE_RELOGIO, LARANJA),
    ])
    st.caption("Facilidade e utilidade: médias das notas de 1 a 5.")

    def tabela(titulo: str, contagem: dict) -> None:
        with st.container(key=f"card_tab_{abs(hash(titulo))}"):
            st.markdown(f'<div class="ctitle">{esc(titulo)}</div>', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame([{"Resposta": k, "Qtd.": v, "%": f"{100 * v / r['n']:.0f}%"} for k, v in contagem.items()]),
                         hide_index=True, width="stretch")

    c1, c2 = st.columns([1.4, 1], gap="medium")
    with c1, st.container(key="card_notas"):
        st.markdown('<div class="ctitle">Distribuição das notas</div>', unsafe_allow_html=True)
        notas = [str(k) for k in range(1, 6)]
        fig = go.Figure([go.Bar(name="Facilidade", x=notas, y=[r["dist_facilidade"][k] for k in range(1, 6)], marker_color=ROXO),
                         go.Bar(name="Utilidade", x=notas, y=[r["dist_utilidade"][k] for k in range(1, 6)], marker_color=VERDE)])
        fig.update_layout(height=250, barmode="group", margin=dict(l=0, r=0, t=6, b=0), paper_bgcolor="rgba(0,0,0,0)",
                          plot_bgcolor="rgba(0,0,0,0)", font=dict(family="Poppins, sans-serif", size=11),
                          legend=dict(orientation="h", y=1.12), yaxis=dict(gridcolor="#eee9f5", dtick=1),
                          xaxis=dict(type="category", title="nota"))
        st.plotly_chart(fig, config={"displayModeBar": False}, key="pl_notas")
    with c2:
        with st.container(key="card_pretende"):
            st.markdown('<div class="ctitle">13. Pretende usar no dia a dia</div>', unsafe_allow_html=True)
            dados = [(k, v) for k, v in r["pretende_usar"].items() if v]
            fig = go.Figure(go.Pie(labels=[k for k, _ in dados], values=[v for _, v in dados], hole=.62, sort=False,
                                   marker=dict(colors=[VERDE, LARANJA, "#ef4444"][:len(dados)], line=dict(color="#fff", width=2)),
                                   textinfo="percent", textfont=dict(color="#fff")))
            fig.update_layout(height=220, margin=dict(l=0, r=0, t=6, b=6), paper_bgcolor="rgba(0,0,0,0)",
                              font=dict(family="Poppins, sans-serif"), legend=dict(orientation="h", y=-0.05))
            st.plotly_chart(fig, config={"displayModeBar": False}, key="pl_pretende")
    with st.container(key="card_tarefas"):
        st.markdown('<div class="ctitle">Tarefas (Parte 2)</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"Tarefa": t, **c} for t, c in r["tarefas"].items()]), hide_index=True,
                     width="stretch")
    c1, c2 = st.columns(2, gap="medium")
    with c1:
        tabela("12. Funções que usariam", r["funcoes"])
        tabela("2. Tempo como empreendedor", r["tempo_empreende"])
    with c2:
        tabela("13. Pretende usar no dia a dia", r["pretende_usar"])
        tabela("3. Controle atual", r["controle_atual"])
        tabela("4. Já usa WhatsApp para vender", r["usa_whatsapp"])
    if r["comentarios"]:
        with st.container(key="card_coment"):
            st.markdown('<div class="ctitle">Comentários</div>', unsafe_allow_html=True)
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
    with st.container(key="card_entrar"), st.form("form_entrar", border=False):
        st.markdown('<div class="ctitle">Entrar na minha loja</div><div class="csub">Escolha sua loja e digite o PIN</div>',
                    unsafe_allow_html=True)
        loja = st.selectbox("Sua loja", lojas, format_func=lambda l: l["nome"], index=None, placeholder="Escolha sua loja…")
        pin = st.text_input("PIN (4 números)", type="password", max_chars=4)
        ok = st.form_submit_button("Entrar", type="primary", width="stretch")
    if ok:
        if bloqueio > 0:
            st.error(f"Muitas tentativas. Aguarde {int(bloqueio) + 1} segundos.")
        elif loja is None:
            st.error("Escolha sua loja.")
        elif db.verificar_pin(loja["id"], pin):
            ss.loja_id, ss.tentativas, ss.pagina = loja["id"], 0, "vendas"
            st.rerun()
        else:
            ss.tentativas += 1
            if ss.tentativas >= 5:
                ss.bloqueado_ate, ss.tentativas = time.time() + 60, 0
            st.error("PIN incorreto.")


def tela_criar() -> None:
    with st.container(key="card_criar"):
        with st.form("form_criar", border=False):
            st.markdown('<div class="ctitle">Criar minha loja</div><div class="csub">Leva 1 minuto e é grátis</div>',
                        unsafe_allow_html=True)
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
            ss.pagina = "produtos"
            st.rerun()


# --------------------------------------------------------------------------
# Roteamento
# --------------------------------------------------------------------------
def mostrar_msg() -> None:
    if ss.get("msg"):
        st.success(ss.msg)
        ss.msg = None


# chave -> (ícone, nome no menu lateral, nome curto no menu do celular)
PAGINAS = {
    "vendas": (":material/monitoring:", "Vendas", "Vendas"),
    "caixa": (":material/point_of_sale:", "Nova venda (caixa)", "Caixa"),
    "produtos": (":material/inventory_2:", "Estoque e cadastros", "Estoque"),
    "opcoes": (":material/settings:", "Opções", "Opções"),
    "avaliar": (":material/star:", "Avaliar o app", "Avaliar"),
}


def _ir(pagina: str) -> None:
    ss.pagina = pagina


def _ir_mobile() -> None:
    if ss.get("nav_mob"):
        ss.pagina = ss.nav_mob


def sair() -> None:
    for k in list(ss.keys()):
        del ss[k]


def menu(loja: dict) -> str:
    if ss.pagina not in PAGINAS:
        ss.pagina = "vendas"
    with st.sidebar:
        st.markdown(f'<div class="logo">{LOGO_SVG}<div><b>Vitrine <span>&amp;</span> Caixa</b>'
                    f'<small>vendas · estoque · WhatsApp</small></div></div>'
                    f'<div class="lojanome">Loja conectada<b>{esc(loja["nome"])}</b></div>', unsafe_allow_html=True)
        for chave, (icone, nome, _) in PAGINAS.items():
            st.button(nome, icon=icone, key=f"nav_{chave}", width="stretch", on_click=_ir, args=(chave,),
                      type="primary" if chave == ss.pagina else "tertiary")
        st.divider()
        with st.container(key="sair"):
            if st.button("Sair", icon=":material/logout:", key="nav_sair", width="stretch", type="tertiary"):
                sair()
                st.rerun()
    ss.nav_mob = ss.pagina  # mantém o menu do celular igual ao da barra lateral
    with st.container(key="navmob"):
        st.segmented_control("Menu", list(PAGINAS), key="nav_mob", on_change=_ir_mobile, label_visibility="collapsed",
                             format_func=lambda k: f"{PAGINAS[k][0]} {PAGINAS[k][2]}")
    return ss.pagina


qp = st.query_params

# 1) Vitrine pública: ?loja=codigo
if qp.get("loja"):
    largura_max(1080)
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
    largura_max(820)
    topo("Vitrine & Caixa", "Avaliação do aplicativo")
    tela_avaliar()
    st.stop()

loja_atual = db.obter_loja(ss.loja_id) if ss.loja_id else None

if loja_atual is None:
    ss.loja_id = None
    publica = ss.get("nav_publica") or "Entrar"
    largura_max(1080 if publica == "📋 Pesquisador" else 820)
    topo("Vitrine & Caixa", "Vendas, estoque e pedidos pelo WhatsApp para pequenos negócios")
    with st.container(key="navpub"):
        pagina = st.segmented_control("Menu", ["Entrar", "Criar minha loja", "★ Avaliar", "📋 Pesquisador"],
                                      default="Entrar", key="nav_publica", label_visibility="collapsed") or "Entrar"
    mostrar_msg()
    {"Entrar": tela_entrar, "Criar minha loja": tela_criar, "★ Avaliar": tela_avaliar,
     "📋 Pesquisador": tela_pesquisador}[pagina]()
else:
    pagina = menu(loja_atual)
    mostrar_msg()
    if pagina == "vendas":
        tela_vendas(loja_atual)
    elif pagina == "caixa":
        cabecalho("Nova venda", "Escolha os produtos, registre a venda e o estoque baixa sozinho")
        tela_catalogo(loja_atual, modo_dono=True)
    elif pagina == "produtos":
        tela_produtos(loja_atual)
    elif pagina == "opcoes":
        tela_ajustes(loja_atual)
        st.divider()
        if st.button("🚪 Sair da loja", width="stretch"):
            sair()
            st.rerun()
    else:
        largura_max(820)
        tela_avaliar()
