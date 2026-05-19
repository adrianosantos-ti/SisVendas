import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
import urllib.parse

# ==========================================
# CONFIGURAÇÃO DE BANCO DE DADOS (NUVEM)
# ==========================================
if 'carrinho' not in st.session_state:
    st.session_state['carrinho'] = []

DATABASE_URL = st.secrets["DATABASE_URL"]

def conectar_banco():
    return psycopg2.connect(DATABASE_URL)

def carregar_dados(query, params=None):
    conn = conectar_banco()
    cursor = conn.cursor()
    if params:
        cursor.execute(query, params)
    else:
        cursor.execute(query)
    
    if cursor.description:
        cols = [desc[0] for desc in cursor.description]
        df = pd.DataFrame(cursor.fetchall(), columns=cols)
    else:
        df = pd.DataFrame()
    
    conn.close()
    return df

# ==========================================
# INTERFACE CONFIG E CONTROLE DE LOGIN
# ==========================================
st.set_page_config(page_title="ERP Multi-Empresas Pro", layout="wide")

if 'logado' not in st.session_state:
    st.session_state['logado'] = False
    st.session_state['perfil'] = ''
    st.session_state['empresa_id'] = None
    st.session_state['usuario_nome'] = ''

# --- TELA DE LOGIN ---
if not st.session_state['logado']:
    st.title("🔐 Acesso ao Sistema")
    with st.container(border=True):
        st.subheader("Identifique-se")
        login_input = st.text_input("Usuário")
        senha_input = st.text_input("Senha", type="password")
        
        if st.button("Entrar no Sistema", type="primary", use_container_width=True):
            conn = conectar_banco()
            cursor = conn.cursor()
            cursor.execute("SELECT id, nome, perfil, empresa_id FROM usuarios WHERE login = %s AND senha = %s", (login_input, senha_input))
            usuario = cursor.fetchone()
            conn.close()
            
            if usuario:
                st.session_state['logado'] = True
                st.session_state['usuario_id'] = usuario[0]
                st.session_state['usuario_nome'] = usuario[1]
                st.session_state['perfil'] = usuario[2]
                st.session_state['empresa_id'] = usuario[3]
                st.rerun()
            else:
                st.error("❌ Usuário ou senha incorretos.")

# --- PAINEL DO ADMINISTRADOR MASTER ---
elif st.session_state['perfil'] == 'master':
    st.title("👑 Painel de Administração Master")
    if st.sidebar.button("🚪 Sair"):
        st.session_state.clear()
        st.rerun()
        
    aba_cad_empresa, aba_cad_usuario, aba_senhas = st.tabs(["🏢 Empresas", "👤 Logins", "🔒 Senhas"])
    
    with aba_cad_empresa:
        st.subheader("Nova Empresa")
        with st.form("form_nova_empresa", clear_on_submit=True):
            nome_emp = st.text_input("Nome Comercial")
            cnpj_emp = st.text_input("CNPJ")
            if st.form_submit_button("Salvar"):
                conn = conectar_banco()
                conn.cursor().execute("INSERT INTO empresas (nome, cnpj) VALUES (%s, %s)", (nome_emp, cnpj_emp))
                conn.commit()
                conn.close()
                st.success(f"Empresa '{nome_emp}' cadastrada!")
                st.rerun()
        st.dataframe(carregar_dados("SELECT id, nome, cnpj FROM empresas ORDER BY id"), use_container_width=True)

    with aba_cad_usuario:
        st.subheader("Novo Login")
        df_emp_list = carregar_dados("SELECT id, nome FROM empresas ORDER BY id")
        dict_empresas = dict(zip(df_emp_list['nome'], df_emp_list['id']))
        with st.form("form_novo_usuario", clear_on_submit=True):
            nome_usu = st.text_input("Nome")
            emp_usu = st.selectbox("Empresa", options=list(dict_empresas.keys()))
            login_usu = st.text_input("Login")
            senha_usu = st.text_input("Senha", type="password")
            if st.form_submit_button("Criar"):
                conn = conectar_banco()
                conn.cursor().execute("INSERT INTO usuarios (nome, login, senha, empresa_id, perfil) VALUES (%s,%s,%s,%s,'comum')", 
                                     (nome_usu, login_usu, senha_usu, dict_empresas[emp_usu]))
                conn.commit()
                conn.close()
                st.rerun()
        st.dataframe(carregar_dados("SELECT u.id, u.nome, u.login, e.nome as empresa FROM usuarios u JOIN empresas e ON u.empresa_id = e.id"), use_container_width=True)

    with aba_senhas:
        st.subheader("Reset de Senhas")
        df_todos_usu = carregar_dados("SELECT id, nome, login FROM usuarios ORDER BY nome")
        dict_todos_usu = {f"{row['nome']} ({row['login']})": row['id'] for _, row in df_todos_usu.iterrows()}
        usu_sel = st.selectbox("Selecione o Usuário", options=list(dict_todos_usu.keys()))
        nova_sen = st.text_input("Nova Senha", type="password")
        if st.button("Confirmar Alteração"):
            conn = conectar_banco()
            conn.cursor().execute("UPDATE usuarios SET senha = %s WHERE id = %s", (nova_sen, dict_todos_usu[usu_sel]))
            conn.commit()
            conn.close()
            st.success("Senha alterada!")

# --- SISTEMA OPERACIONAL (USUÁRIOS COMUNS / EMPRESAS) ---
else:
    emp_id = st.session_state['empresa_id']
    
    # ---------------------------------------------------------
    # NOVO MENU LATERAL DE MÓDULOS
    # ---------------------------------------------------------
    st.sidebar.image("https://cdn-icons-png.flaticon.com/512/1063/1063376.png", width=80)
    st.sidebar.title(f"Módulos")
    modulo = st.sidebar.radio("Navegação Principal:", [
        "📊 Análises", 
        "🗂️ Cadastros", 
        "🔄 Movimentações", 
        "💰 Financeiro"
    ])
    
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"👤 **{st.session_state['usuario_nome']}**")
    
    with st.sidebar.expander("🔒 Alterar Senha"):
        with st.form("f_senha"):
            s_atu = st.text_input("Atual", type="password")
            s_nov = st.text_input("Nova", type="password")
            if st.form_submit_button("Mudar"):
                conn = conectar_banco()
                cursor = conn.cursor()
                cursor.execute("SELECT senha FROM usuarios WHERE id=%s",(st.session_state['usuario_id'],))
                if cursor.fetchone()[0] == s_atu:
                    cursor.execute("UPDATE usuarios SET senha=%s WHERE id=%s",(s_nov, st.session_state['usuario_id']))
                    conn.commit()
                    st.success("OK!")
                else: st.error("Incorreta")
                conn.close()

    if st.sidebar.button("🚪 Sair do Sistema", use_container_width=True):
        st.session_state.clear()
        st.rerun()

    # ==========================================
    # MÓDULO 1: ANÁLISES (Dashboard e Histórico)
    # ==========================================
    if modulo == "📊 Análises":
        st.title("📊 Gestão e Performance")
        aba_dash, aba_hist = st.tabs(["Painel Visual", "Histórico de Movimentação"])
        
        with aba_dash:
            # Reutilizando a lógica do Dashboard anterior com filtro de datas
            query_dash = "SELECT v.data_venda, v.valor_total, v.quantidade, p.nome AS produto, p.categoria FROM vendas v JOIN produtos p ON v.produto_id = p.id WHERE v.empresa_id = %s"
            df_dash = carregar_dados(query_dash, (emp_id,))
            if not df_dash.empty:
                df_dash['Data_Obj'] = pd.to_datetime(df_dash['data_venda'], format='%d/%m/%Y', errors='coerce').dt.date
                st.subheader("🔍 Período de Análise")
                op_per = ["Mês Atual", "Hoje", "Últimos 30 Dias", "Todo o Período", "Personalizado"]
                per_sel = st.selectbox("Filtrar:", op_per)
                hoje = date.today()
                d_ini, d_fim = None, None
                if per_sel == "Hoje": d_ini, d_fim = hoje, hoje
                elif per_sel == "Últimos 30 Dias": d_ini, d_fim = hoje - timedelta(days=30), hoje
                elif per_sel == "Mês Atual": d_ini, d_fim = hoje.replace(day=1), hoje
                elif per_sel == "Personalizado":
                    c1, c2 = st.columns(2)
                    d_ini = c1.date_input("Início", hoje - timedelta(days=30))
                    d_fim = c2.date_input("Fim", hoje)
                
                if d_ini and d_fim:
                    df_dash = df_dash[(df_dash['Data_Obj'] >= d_ini) & (df_dash['Data_Obj'] <= d_fim)]
                
                if not df_dash.empty:
                    col1, col2, col3 = st.columns(3)
                    fat = df_dash['valor_total'].sum()
                    col1.metric("Faturamento", f"R$ {fat:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
                    col2.metric("Vendas", len(df_dash))
                    col3.metric("Ticket Médio", f"R$ {fat/len(df_dash):,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
                    
                    df_fat_dia = df_dash.groupby('Data_Obj')['valor_total'].sum().reset_index()
                    st.plotly_chart(px.line(df_fat_dia, x='Data_Obj', y='valor_total', title="Vendas por Dia", template="plotly_white"), use_container_width=True)
                    
                    c1, c2 = st.columns(2)
                    df_top = df_dash.groupby('produto')['quantidade'].sum().reset_index().sort_values('quantidade', ascending=False).head(5).sort_values('quantidade', ascending=True)
                    df_top['produto_curto'] = df_top['produto'].apply(lambda x: (str(x)[:22] + '...') if len(str(x)) > 22 else str(x))
                    fig_top = px.bar(df_top, x='quantidade', y='produto', orientation='h', text='quantidade', color_discrete_sequence=['#0068c9'], title="Top 5 Produtos")
                    fig_top.update_yaxes(tickmode='array', tickvals=df_top['produto'], ticktext=df_top['produto_curto'])
                    c1.plotly_chart(fig_top, use_container_width=True)
                    c2.plotly_chart(px.pie(df_dash.groupby('categoria')['valor_total'].sum().reset_index(), values='valor_total', names='categoria', hole=0.4, title="Vendas por Categoria"), use_container_width=True)
                else: st.warning("Sem dados no período")
            else: st.info("Faça vendas para ver gráficos.")

        with aba_hist:
            # Reutilizando histórico com Edição e Estorno
            st.subheader("Histórico Geral de Vendas")
            df_hist = carregar_dados("""
                SELECT v.id, v.codigo_venda, COALESCE(c.nome, 'Excluído') as cliente, COALESCE(p.nome, 'Excluído') as produto, v.quantidade, v.valor_total, v.data_venda
                FROM vendas v LEFT JOIN clientes c ON v.cliente_id = c.id LEFT JOIN produtos p ON v.produto_id = p.id WHERE v.empresa_id = %s ORDER BY v.id DESC
            """, (emp_id,))
            if not df_hist.empty:
                st.dataframe(df_hist, use_container_width=True, hide_index=True)
                with st.expander("❌ Cancelar Item"):
                    op_venda = df_hist.apply(lambda x: f"ID {x['id']} | Venda {x['codigo_venda']} | {x['produto']}", axis=1).tolist()
                    sel_del = st.selectbox("Item para estornar:", op_venda)
                    if st.button("Confirmar Estorno", type="primary"):
                        id_del = int(sel_del.split("ID ")[1].split(" |")[0])
                        conn = conectar_banco(); cur = conn.cursor()
                        cur.execute("SELECT produto_id, quantidade, codigo_venda FROM vendas WHERE id=%s AND empresa_id=%s",(id_del, emp_id))
                        inf = cur.fetchone()
                        if inf:
                            cur.execute("UPDATE produtos SET quantidade = quantidade + %s WHERE id=%s",(inf[1], inf[0]))
                            cur.execute("DELETE FROM vendas WHERE id=%s",(id_del,))
                            cur.execute("DELETE FROM contas_receber WHERE venda_codigo=%s AND empresa_id=%s",(inf[2], emp_id))
                            conn.commit(); st.success("Cancelado!"); st.rerun()
                        conn.close()

    # ==========================================
    # MÓDULO 2: CADASTROS (Produtos, Categorias, Clientes, Fornecedores)
    # ==========================================
    elif modulo == "🗂️ Cadastros":
        st.title("🗂️ Central de Cadastros")
        tab_prod, tab_cat, tab_cli, tab_for = st.tabs(["📦 Estoque", "🏷️ Categorias", "👥 Clientes", "🤝 Fornecedores"])
        
        with tab_prod:
            st.subheader("Gerenciar Estoque")
            df_p = carregar_dados("SELECT * FROM produtos WHERE empresa_id=%s ORDER BY nome", (emp_id,))
            df_c = carregar_dados("SELECT nome FROM categorias WHERE empresa_id=%s ORDER BY nome", (emp_id,))
            lista_cat = df_c['nome'].tolist() if not df_c.empty else ["Geral"]
            
            with st.expander("➕ Novo Produto"):
                with st.form("f_novo_p", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    n_p = c1.text_input("Nome do Produto")
                    ref_p = c2.text_input("Referência (Código Fabricante / EAN)")
                    c3, c4, c5 = st.columns(3)
                    q_p = c3.number_input("Qtd Inicial", min_value=0, step=1)
                    v_p = c4.number_input("Valor Venda (R$)", min_value=0.0, format="%.2f")
                    m_p = c5.text_input("Marca", value="Mary Kay")
                    cat_p = st.selectbox("Categoria", lista_cat)
                    if st.form_submit_button("Cadastrar"):
                        conn = conectar_banco(); conn.cursor().execute("INSERT INTO produtos (nome, quantidade, valor, marca, categoria, empresa_id, referencia) VALUES (%s,%s,%s,%s,%s,%s,%s)", (n_p, q_p, v_p, m_p, cat_p, emp_id, ref_p)); conn.commit(); conn.close()
                        st.rerun()
            
            if not df_p.empty:
                st.dataframe(df_p.drop(columns=['empresa_id']), use_container_width=True, hide_index=True)
                val_est = (df_p['quantidade'] * df_p['valor']).sum()
                st.metric("Capital em Estoque (Venda)", f"R$ {val_est:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))

        with tab_cat:
            c1, c2 = st.columns(2)
            with c1:
                cat_n = st.text_input("Nova Categoria")
                if st.button("Salvar Categoria"):
                    conn = conectar_banco(); conn.cursor().execute("INSERT INTO categorias (nome, empresa_id) VALUES (%s,%s)",(cat_n, emp_id)); conn.commit(); conn.close(); st.rerun()
            with c2:
                cat_del = st.selectbox("Excluir:", lista_cat)
                if st.button("Remover", type="primary"):
                    conn = conectar_banco(); conn.cursor().execute("DELETE FROM categorias WHERE nome=%s AND empresa_id=%s",(cat_del, emp_id)); conn.commit(); conn.close(); st.rerun()

        with tab_cli:
            with st.expander("➕ Novo Cliente"):
                with st.form("f_cli", clear_on_submit=True):
                    n_c = st.text_input("Nome")
                    t_c = st.text_input("Telefone")
                    if st.form_submit_button("Salvar"):
                        conn = conectar_banco(); conn.cursor().execute("INSERT INTO clientes (nome, telefone, empresa_id) VALUES (%s,%s,%s)",(n_c, t_c, emp_id)); conn.commit(); conn.close(); st.rerun()
            st.dataframe(carregar_dados("SELECT nome, telefone FROM clientes WHERE empresa_id=%s ORDER BY nome",(emp_id,)), use_container_width=True)

        with tab_for:
            st.subheader("Gestão de Fornecedores")
            with st.expander("➕ Novo Fornecedor"):
                with st.form("f_for", clear_on_submit=True):
                    n_f = st.text_input("Razão Social / Nome")
                    c_f = st.text_input("CNPJ")
                    t_f = st.text_input("Telefone")
                    if st.form_submit_button("Salvar Fornecedor"):
                        conn = conectar_banco(); conn.cursor().execute("INSERT INTO fornecedores (nome, cnpj, telefone, empresa_id) VALUES (%s,%s,%s,%s)",(n_f, c_f, t_f, emp_id)); conn.commit(); conn.close(); st.rerun()
            st.dataframe(carregar_dados("SELECT nome, cnpj, telefone FROM fornecedores WHERE empresa_id=%s ORDER BY nome",(emp_id,)), use_container_width=True)

    # ==========================================
    # MÓDULO 3: MOVIMENTAÇÕES (Vendas e Compras)
    # ==========================================
    elif modulo == "🔄 Movimentações":
        st.title("🔄 Operações Diárias")
        tab_venda, tab_compra = st.tabs(["🛒 PDV (Vendas)", "📥 Entrada de Notas (Compras)"])
        
        with tab_venda:
            # Lógica completa do PDV (Carrinho + WhatsApp)
            st.subheader("🛒 Frente de Caixa")
            df_cli = carregar_dados("SELECT id, nome FROM clientes WHERE empresa_id=%s ORDER BY nome",(emp_id,))
            df_pro = carregar_dados("SELECT id, nome, valor, quantidade FROM produtos WHERE empresa_id=%s ORDER BY nome",(emp_id,))
            
            if not df_cli.empty and not df_pro.empty:
                c1, c2 = st.columns(2)
                cliente_pdv = c1.selectbox("Cliente:", options=df_cli['nome'].tolist())
                f_pag = c2.selectbox("Forma:", ["Pix", "Crédito", "Débito", "Dinheiro", "Crediário"])
                
                st.markdown("---")
                prod_pdv = st.selectbox("Produto:", options=df_pro['nome'].tolist())
                p_info = df_pro[df_pro['nome'] == prod_pdv].iloc[0]
                c3, c4 = st.columns(2)
                q_pdv = c3.number_input("Quantidade:", min_value=1, step=1)
                desc_pdv = c4.number_input("Desconto Un. (R$):", min_value=0.0)
                
                if st.button("➕ Adicionar ao Carrinho"):
                    if p_info['quantidade'] >= q_pdv:
                        st.session_state['carrinho'].append({
                            'id': p_info['id'], 'nome': prod_pdv, 'qtd': q_pdv, 
                            'unit': p_info['valor'], 'desc': desc_pdv, 
                            'total': (p_info['valor'] - desc_pdv) * q_pdv
                        })
                        st.rerun()
                    else: st.error("Estoque insuficiente!")

                if st.session_state['carrinho']:
                    df_car = pd.DataFrame(st.session_state['carrinho'])
                    st.table(df_car[['nome', 'qtd', 'total']])
                    total_pdv = df_car['total'].sum()
                    st.header(f"Total: R$ {total_pdv:.2f}")
                    
                    if st.button("✅ Finalizar Venda", type="primary"):
                        conn = conectar_banco(); cur = conn.cursor()
                        cur.execute("SELECT MAX(codigo_venda) FROM vendas WHERE empresa_id=%s",(emp_id,))
                        novo_cod = (cur.fetchone()[0] or 0) + 1
                        data_v = date.today().strftime("%d/%m/%Y")
                        cli_id_v = df_cli[df_cli['nome'] == cliente_pdv].iloc[0]['id']
                        
                        for it in st.session_state['carrinho']:
                            cur.execute("INSERT INTO vendas (codigo_venda, cliente_id, produto_id, quantidade, data_venda, valor_total, empresa_id, valor_unitario, desconto) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                       (novo_cod, cli_id_v, it['id'], it['qtd'], data_v, it['total'], emp_id, it['unit'], it['desc']))
                            cur.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE id=%s",(it['qtd'], it['id']))
                        
                        # Gera parcela única no financeiro se for venda simples
                        cur.execute("INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                   (novo_cod, cli_id_v, 1, 1, total_pdv, data_v, 'Pago' if f_pag != "Crediário" else "Pendente", emp_id))
                        
                        conn.commit(); conn.close()
                        st.session_state['carrinho'] = []
                        st.success("Venda Finalizada!")
                        st.rerun()
                if st.button("🗑️ Limpar Carrinho"): st.session_state['carrinho'] = []; st.rerun()
            else: st.warning("Cadastre clientes e produtos primeiro.")

        with tab_compra:
            st.subheader("📥 Entrada de Mercadorias")
            st.info("Aqui você poderá importar o XML da NF-e para alimentar o estoque e o contas a pagar automaticamente.")
            
            arquivo_xml = st.file_uploader("Selecione o arquivo XML da Nota Fiscal", type=["xml"])
            if arquivo_xml:
                try:
                    tree = ET.parse(arquivo_xml)
                    root = tree.getroot()
                    # Namespace padrão da NF-e
                    ns = {'nfe': 'http://www.portalfiscal.inf.br/nfe'}
                    
                    # Lógica de leitura básica para teste
                    n_nota = root.find('.//nfe:ide/nfe:nNF', ns).text
                    v_nota = root.find('.//nfe:total/nfe:ICMSTot/nfe:vNF', ns).text
                    emitente = root.find('.//nfe:emit/nfe:xNome', ns).text
                    
                    st.success(f"Nota Fiscal {n_nota} detectada!")
                    st.write(f"**Fornecedor:** {emitente}")
                    st.write(f"**Valor Total:** R$ {v_nota}")
                    
                    if st.button("Confirmar Importação"):
                        # No próximo passo, faremos o loop pelos produtos e o registro no banco
                        st.warning("Processamento detalhado de itens em desenvolvimento para testes.")
                except Exception as e:
                    st.error(f"Erro ao ler XML: {e}")

    # ==========================================
    # MÓDULO 4: FINANCEIRO (Contas a Receber e Pagar)
    # ==========================================
    elif modulo == "💰 Financeiro":
        st.title("💰 Gestão Financeira")
        tab_rec, tab_pag = st.tabs(["🟢 Contas a Receber (Vendas)", "🔴 Contas a Pagar (Despesas)"])
        
        with tab_rec:
            st.subheader("Cobranças e Recebimentos")
            df_r = carregar_dados("""
                SELECT cr.id, c.nome as cliente, cr.valor_parcela, cr.data_vencimento, cr.status 
                FROM contas_receber cr JOIN clientes c ON cr.cliente_id = c.id WHERE cr.empresa_id = %s ORDER BY cr.id DESC
            """, (emp_id,))
            if not df_r.empty:
                st.dataframe(df_r, use_container_width=True)
                with st.expander("💰 Dar Baixa em Recebimento"):
                    pend = df_r[df_r['status'] == 'Pendente']
                    if not pend.empty:
                        op_r = pend.apply(lambda x: f"ID {x['id']} | {x['cliente']} | R$ {x['valor_parcela']}", axis=1).tolist()
                        sel_r = st.selectbox("Parcela recebida:", op_r)
                        if st.button("Confirmar Recebimento"):
                            id_r = int(sel_r.split("ID ")[1].split(" |")[0])
                            conn = conectar_banco(); conn.cursor().execute("UPDATE contas_receber SET status='Pago', data_pagamento=%s WHERE id=%s",(date.today().strftime("%d/%m/%Y"), id_r)); conn.commit(); conn.close(); st.rerun()

        with tab_pag:
            st.subheader("Compromissos e Pagamentos")
            df_p = carregar_dados("""
                SELECT cp.id, f.nome as fornecedor, cp.valor_parcela, cp.data_vencimento, cp.status 
                FROM contas_pagar cp JOIN fornecedores f ON cp.fornecedor_id = f.id WHERE cp.empresa_id = %s ORDER BY cp.id DESC
            """, (emp_id,))
            if not df_p.empty:
                st.dataframe(df_p, use_container_width=True)
                # Lógica de baixa similar ao receber...
            else: st.info("Nenhuma conta a pagar registrada.")
