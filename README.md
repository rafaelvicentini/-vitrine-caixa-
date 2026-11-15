# Vitrine & Caixa — Python + Streamlit + SQLite

Aplicativo web para pequenos empreendedores controlarem **produtos, estoque e vendas** e receberem
**pedidos pelo WhatsApp**. Desenvolvido por **Rafael Maria Iamin** (Ciência da Computação — Anhanguera / Unic Cuiabá)
no **Projeto de Extensão III**, para os empreendedores da **Associação Comunitária do Bairro Parque da Liberdade
(Cuiabá/MT)**.

## Funcionalidades

| Tela | O que faz |
|---|---|
| **Entrar / Criar minha loja** | Cada empreendedor cria a sua loja com um **PIN de 4 números**. O PIN é guardado só como hash (PBKDF2‑SHA256 com sal). Cada loja vê apenas os próprios dados. |
| **🛍️ Vitrine (caixa)** | Catálogo com foto, preço e estoque. Escolhe as quantidades, **registra a venda** (baixa o estoque automaticamente) ou envia o resumo pelo WhatsApp. Mostra **alerta de estoque baixo**. |
| **📦 Produtos** | Cadastrar, **editar**, **repor estoque** e **excluir** produtos (nome, categoria, preço, estoque, alerta de estoque mínimo, foto opcional, mostrar ou não na vitrine). |
| **📊 Relatórios** | **Dia** ou **mês**: total vendido, nº de vendas, ticket médio, itens, **mais vendidos** e gráfico (por hora ou por dia). Lista as vendas e permite **cancelar** uma venda (o estoque volta). |
| **⚙️ Ajustes** | Nome do negócio, **WhatsApp** que recebe pedidos, estoque mínimo padrão, **link público da vitrine**, **backup em CSV** (produtos, vendas, movimentos de estoque) e troca de PIN. |
| **Vitrine do cliente** (`?loja=codigo`) | Link que o empreendedor manda aos clientes: eles montam o pedido e enviam para o WhatsApp da loja (`wa.me`). Não precisa de PIN. |
| **★ Avaliar** (`?pagina=avaliar`) | Questionário de validação (as mesmas 16 perguntas do questionário impresso). Não precisa de PIN; as respostas são gravadas no SQLite. |
| **📋 Pesquisador** | Resumo das avaliações (nº de respostas, médias de facilidade e utilidade, contagem de cada resposta, tarefas, comentários) e **exportação CSV**. Protegido pela senha `ADMIN_SENHA`. |

## Estrutura

```
app.py              interface (Streamlit)
db.py               banco de dados (sqlite3) e regras de negócio
tests/test_db.py    testes automáticos (pytest)
requirements.txt    dependências
.streamlit/config.toml               tema (cores) e configurações
.streamlit/secrets.toml.example      modelo da senha do painel do pesquisador
```

Tabelas do SQLite: `lojas`, `produtos`, `vendas`, `itens_venda`, `movimentos_estoque`, `avaliacoes`.
Valores em dinheiro são guardados em **centavos** (inteiros); todas as consultas usam **parâmetros** (`?`),
o que evita injeção de SQL; cada venda é gravada numa **transação** (venda, itens e baixa de estoque juntos).
O arquivo `vitrine_caixa.db` é criado sozinho na primeira execução.

## Como rodar no computador

Requisitos: Python 3.10 ou mais novo.

```bash
cd extensao_streamlit
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

O navegador abre em `http://localhost:8501`. Para testar no celular na mesma rede Wi‑Fi, use o endereço
“Network URL” que aparece no terminal.

Para ativar o **Painel do pesquisador**, copie `.streamlit/secrets.toml.example` para `.streamlit/secrets.toml`
e defina `ADMIN_SENHA` (ou rode com a variável de ambiente `ADMIN_SENHA=...`).

Testes automáticos: `pip install pytest` e `python -m pytest -q`.

## Como publicar no Streamlit Community Cloud (gratuito)

1. Crie um repositório no **GitHub** (pode ser público) e envie estes arquivos
   (o `.gitignore` já impede enviar o banco `.db` e o `secrets.toml`).
2. Entre em **https://share.streamlit.io** com a conta do GitHub e clique em **Create app**.
3. Escolha o repositório, a branch `main` e o arquivo principal **`app.py`**.
4. Em **Advanced settings → Secrets**, cole:
   ```toml
   ADMIN_SENHA = "uma-senha-forte"
   ```
5. Clique em **Deploy**. O endereço fica parecido com `https://vitrine-caixa.streamlit.app`.
6. Links para divulgar:
   - app para os empreendedores: `https://SEU-APP.streamlit.app`
   - questionário de avaliação: `https://SEU-APP.streamlit.app/?pagina=avaliar`
   - vitrine de cada loja: aparece em **⚙️ Ajustes** de cada loja.

### Atenção: onde ficam os dados

No Streamlit Community Cloud o SQLite fica no disco do servidor, que **não é permanente**: quando o app é
reiniciado, atualizado (novo commit) ou “acorda” depois de dias sem uso, o banco pode voltar vazio.
Por isso:

- **Depois de cada sessão de teste, baixe o CSV das avaliações** no Painel do pesquisador.
- Oriente os empreendedores a usar **⚙️ Ajustes → Backup (CSV)** com frequência.
- Para uso definitivo, o próximo passo é trocar o SQLite por um banco hospedado (ex.: PostgreSQL),
  mudando só o `db.py`.

## Privacidade

- O questionário é anônimo e voluntário; pede consentimento antes de gravar.
- O PIN nunca é guardado em texto; só o hash.
- Os dados de cada loja só aparecem para quem tem o PIN, exceto a vitrine pública (produtos marcados
  como “Mostrar na vitrine”).
