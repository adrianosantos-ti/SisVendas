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
    # MENU LATERAL DE MÓDULOS
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
            query_dash = "SELECT v.data_venda, v.valor_total, v.quantidade, p.nome AS produto, p.categoria FROM vendas v JOIN produtos p ON v.produto_id = p.id WHERE v.empresa_id = %s"
            df_dash = carregar_dados(query_dash, (emp_id,))
            if not df_dash.empty:
                df_dash['Data_Obj'] = pd.to_datetime(df_dash['data_venda'], format='%d/%m/%Y', errors='coerce').dt.date
                st.subheader("🔍 Período de Análise")
                op_per = ["Mês Atual", "Hoje", "Últimos 7 Dias", "Últimos 15 Dias", "Últimos 30 Dias", "Mês Anterior", "Todo o Período", "Personalizado"]
                per_sel = st.selectbox("Filtrar:", op_per)
                hoje = date.today()
                d_ini, d_fim = None, None
                if per_sel == "Hoje": d_ini, d_fim = hoje, hoje
                elif per_sel == "Últimos 7 Dias": d_ini, d_fim = hoje - timedelta(days=7), hoje
                elif per_sel == "Últimos 15 Dias": d_ini, d_fim = hoje - timedelta(days=15), hoje
                elif per_sel == "Últimos 30 Dias": d_ini, d_fim = hoje - timedelta(days=30), hoje
                elif per_sel == "Mês Atual": d_ini, d_fim = hoje.replace(day=1), hoje
                elif per_sel == "Mês Anterior":
                    p_dia = hoje.replace(day=1)
                    d_fim = p_dia - timedelta(days=1)
                    d_ini = d_fim.replace(day=1)
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
                    
                    fig_cat = px.pie(df_dash.groupby('categoria')['valor_total'].sum().reset_index(), values='valor_total', names='categoria', hole=0.4, title="Vendas por Categoria", color_discrete_sequence=px.colors.qualitative.Bold)
                    c2.plotly_chart(fig_cat, use_container_width=True)
                else: st.warning("Sem dados no período")
            else: st.info("Faça vendas para ver gráficos.")

        with aba_hist:
            st.header("📜 Histórico Geral e Faturamento")
            
            query_todas_vendas = """
                SELECT v.id AS "ID Item", v.codigo_venda AS "Nº Venda", COALESCE(c.nome, 'Cliente Excluído') AS "Cliente", 
                       COALESCE(p.nome, 'Produto Excluído') AS "Produto", v.quantidade AS "Qtd",
                       v.valor_unitario AS "Preço Tabela", v.desconto AS "Desconto Unit",
                       v.valor_total AS "Total (R$)", v.valor_entrada AS "Entrada (R$)", v.valor_restante AS "Restante (R$)",
                       v.data_venda AS "Data", v.forma_pagamento AS "Pagamento", v.prazo AS "Prazo" 
                FROM vendas v 
                LEFT JOIN clientes c ON v.cliente_id = c.id 
                LEFT JOIN produtos p ON v.produto_id = p.id 
                WHERE v.empresa_id = %s
                ORDER BY v.codigo_venda DESC, v.id DESC
            """
            df_todas_vendas = carregar_dados(query_todas_vendas, (emp_id,))
            
            if not df_todas_vendas.empty:
                col_opcoes1, col_opcoes2 = st.columns(2)
                
                with col_opcoes1:
                    with st.expander("✏️ Editar Item de Venda", expanded=False):
                        opcoes_venda_edit = df_todas_vendas.apply(lambda x: f"Venda {x['Nº Venda']} (Item {x['ID Item']}) | {x['Cliente']} - {x['Produto']}", axis=1).tolist()
                        venda_edit_selecionada = st.selectbox("Selecione a venda para editar", options=opcoes_venda_edit, key="sel_edit_venda")
                        
                        if venda_edit_selecionada:
                            venda_id_edit = int(venda_edit_selecionada.split("Item ")[1].split(")")[0])
                            conn = conectar_banco()
                            cursor = conn.cursor()
                            cursor.execute("SELECT data_venda, forma_pagamento, prazo, valor_unitario, desconto, valor_entrada, quantidade FROM vendas WHERE id = %s AND empresa_id = %s", (venda_id_edit, emp_id))
                            dados_v_edit = cursor.fetchone()
                            
                            if dados_v_edit:
                                v_data_str, v_pag, v_prazo, v_tabela, v_desc, v_ent, v_qtd = dados_v_edit
                                try: v_data_obj = datetime.strptime(v_data_str, "%d/%m/%Y").date()
                                except: v_data_obj = date.today()
                                    
                                with st.form("form_update_venda"):
                                    c1, c2, c3 = st.columns(3)
                                    nova_data = c1.date_input("Data da Venda", value=v_data_obj, format="DD/MM/YYYY")
                                    
                                    lista_pag = ["Pix", "Cartão de Crédito", "Cartão de Débito", "Dinheiro"]
                                    idx_pag = lista_pag.index(v_pag) if v_pag in lista_pag else 0
                                    novo_pag = c2.selectbox("Pagamento", lista_pag, index=idx_pag)
                                    
                                    lista_prazo = ["À vista", "30 dias", "60 dias", "3x sem juros", "A Combinar"]
                                    idx_prazo = lista_prazo.index(v_prazo) if v_prazo in lista_prazo else 0
                                    novo_prazo = c3.selectbox("Prazo", lista_prazo, index=idx_prazo)
                                    
                                    c4, c5, c6 = st.columns(3)
                                    novo_tabela = c4.number_input("Preço Tabela (R$)", min_value=0.0, value=float(v_tabela), step=1.0, format="%.2f")
                                    novo_desc = c5.number_input("Desconto Unit. (R$)", min_value=0.0, value=float(v_desc), step=1.0, format="%.2f")
                                    nova_entrada = c6.number_input("Entrada Total (R$)", min_value=0.0, value=float(v_ent), step=10.0, format="%.2f")
                                    
                                    if st.form_submit_button("💾 Salvar Alterações"):
                                        novo_total = (novo_tabela - novo_desc) * v_qtd
                                        novo_restante = novo_total - nova_entrada
                                        cursor.execute("UPDATE vendas SET data_venda=%s, forma_pagamento=%s, prazo=%s, valor_unitario=%s, desconto=%s, valor_total=%s, valor_entrada=%s, valor_restante=%s WHERE id=%s AND empresa_id=%s", 
                                                     (nova_data.strftime("%d/%m/%Y"), novo_pag, novo_prazo, novo_tabela, novo_desc, novo_total, nova_entrada, novo_restante, venda_id_edit, emp_id))
                                        conn.commit(); conn.close(); st.success("Atualizado!"); st.rerun()
                            else: conn.close()

                with col_opcoes2:
                    with st.expander("❌ Cancelar / Estornar Item", expanded=False):
                        with st.form("form_del_venda"):
                            opcoes_venda_del = df_todas_vendas.apply(lambda x: f"Venda {x['Nº Venda']} (Item {x['ID Item']}) | {x['Cliente']} - {x['Produto']}", axis=1).tolist()
                            venda_para_apagar = st.selectbox("Selecione o item lançado por engano", options=opcoes_venda_del, key="sel_del_venda")
                            
                            if st.form_submit_button("🚨 Confirmar Cancelamento", type="primary"):
                                venda_id_del = int(venda_para_apagar.split("Item ")[1].split(")")[0])
                                conn = conectar_banco()
                                cursor = conn.cursor()
                                cursor.execute("SELECT produto_id, quantidade, codigo_venda FROM vendas WHERE id = %s AND empresa_id = %s", (venda_id_del, emp_id))
                                venda_info = cursor.fetchone()
                                
                                if venda_info:
                                    p_id, p_qtd, cod_venda = venda_info
                                    cursor.execute("UPDATE produtos SET quantidade = quantidade + %s WHERE id = %s AND empresa_id = %s", (p_qtd, p_id, emp_id))
                                    cursor.execute("DELETE FROM vendas WHERE id = %s AND empresa_id = %s", (venda_id_del, emp_id))
                                    cursor.execute("DELETE FROM contas_receber WHERE venda_codigo = %s AND empresa_id = %s", (cod_venda, emp_id))
                                    conn.commit(); conn.close(); st.success("Cancelado!"); st.rerun()
                                else: conn.close(); st.error("Erro.")
                
                st.markdown("---")

                st.subheader("📲 Enviar Recibo via WhatsApp")
                opcoes_recibo = df_todas_vendas.apply(lambda x: f"Venda {x['Nº Venda']} (Item {x['ID Item']}) | {x['Cliente']} - {x['Produto']}", axis=1).tolist()
                venda_recibo_sel = st.selectbox("Selecione a venda para gerar o recibo", options=opcoes_recibo, key="sel_recibo")

                if venda_recibo_sel:
                    venda_id_recibo = int(venda_recibo_sel.split("Item ")[1].split(")")[0])
                    conn = conectar_banco(); cursor = conn.cursor()
                    cursor.execute("SELECT c.telefone, c.nome, v.data_venda, p.nome, v.quantidade, v.valor_total, v.valor_entrada, v.valor_restante, v.forma_pagamento FROM vendas v JOIN clientes c ON v.cliente_id = c.id JOIN produtos p ON v.produto_id = p.id WHERE v.id = %s AND v.empresa_id = %s", (venda_id_recibo, emp_id))
                    dados_recibo = cursor.fetchone()
                    conn.close()

                    if dados_recibo:
                        tel, nome_cli, data_v, nome_prod, qtd, v_total, v_ent, v_rest, forma_pag = dados_recibo
                        msg = f"Olá, {nome_cli}! 🌸\n\nAqui está o resumo da sua compra do dia *{data_v}*:\n\n"
                        msg += f"🛍️ *Produto:* {qtd}x {nome_prod}\n💰 *Valor Total:* R$ {v_total:.2f}\n"
                        if v_ent > 0: msg += f"💸 *Entrada Paga:* R$ {v_ent:.2f}\n⏳ *Restante:* R$ {v_rest:.2f}\n"
                        msg += f"💳 *Forma de Pagto:* {forma_pag}\n\nMuito obrigada pela preferência! ✨"
                        st.text_area("Pré-visualização da Mensagem:", value=msg, height=200, disabled=True)

                        if tel:
                            tel_limpo = ''.join(filter(str.isdigit, str(tel)))
                            if len(tel_limpo) >= 10:
                                if not tel_limpo.startswith('55'): tel_limpo = '55' + tel_limpo 
                                link_wpp = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                                st.link_button("🟢 Abrir no WhatsApp", link_wpp, type="primary")
                            else: st.warning("⚠️ Telefone incompleto.")
                        else: st.warning("⚠️ Cliente sem telefone.")
                            
                st.markdown("---")
                
                df_todas_vendas['Data_Filtro'] = pd.to_datetime(df_todas_vendas['Data'], dayfirst=True, errors='coerce').dt.date
                data_min = df_todas_vendas['Data_Filtro'].min() if not pd.isna(df_todas_vendas['Data_Filtro'].min()) else date.today()
                data_max = df_todas_vendas['Data_Filtro'].max() if not pd.isna(df_todas_vendas['Data_Filtro'].max()) else date.today()
                
                st.subheader("🔍 Filtrar Tabela por Período")
                col_data1, col_data2 = st.columns(2)
                data_inicio = col_data1.date_input("Data Inicial", value=data_min, format="DD/MM/YYYY")
                data_fim = col_data2.date_input("Data Final", value=data_max, format="DD/MM/YYYY")
                
                mask = (df_todas_vendas['Data_Filtro'] >= data_inicio) & (df_todas_vendas['Data_Filtro'] <= data_fim)
                df_filtrado = df_todas_vendas.loc[mask].drop(columns=['Data_Filtro'])
                
                if not df_filtrado.empty:
                    colunas_exibicao = ['Nº Venda', 'Cliente', 'Produto', 'Qtd', 'Preço Tabela', 'Desconto Unit', 'Total (R$)', 'Entrada (R$)', 'Restante (R$)', 'Data', 'Pagamento', 'Prazo']
                    st.dataframe(df_filtrado[colunas_exibicao], use_container_width=True, hide_index=True)
                    
                    st.markdown("### 📊 Resumo do Período Filtrado")
                    col_res1, col_res2, col_res3, col_res4 = st.columns(4)
                    col_res1.metric("💰 Faturamento", f"R$ {df_filtrado['Total (R$)'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                    col_res2.metric("⏳ A Receber", f"R$ {df_filtrado['Restante (R$)'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                    col_res3.metric("🛒 Vendas", f"{df_filtrado['Nº Venda'].nunique()}")
                    col_res4.metric("🧴 Produtos", f"{df_filtrado['Qtd'].sum()}")
                else: st.warning("Nenhuma venda neste período.")
            else: st.info("Nenhuma venda registrada.")

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
            st.header("Gerenciamento de Clientes")
            
            hoje_str = date.today().strftime("%d/%m")
            df_aniv = carregar_dados("SELECT nome, telefone FROM clientes WHERE empresa_id=%s AND data_nascimento=%s", (emp_id, hoje_str))
            if not df_aniv.empty:
                st.success(f"🎉 Temos {len(df_aniv)} aniversariante(s) hoje ({hoje_str})!")
                st.dataframe(df_aniv, use_container_width=True, hide_index=True)
            else:
                st.info(f"Nenhum aniversariante hoje ({hoje_str}).")
            
            st.markdown("---")
            
            sub_add_cli, sub_edit_cli, sub_del_cli, sub_hist_cli = st.tabs(["➕ Cadastrar", "✏️ Editar", "❌ Excluir", "🛍️ Histórico de Compras"])
            
            with sub_add_cli:
                with st.form("form_cliente", clear_on_submit=True):
                    col1, col2, col3 = st.columns(3)
                    nome_cli = col1.text_input("Nome do Cliente")
                    nasc_cli = col2.text_input("Dia de Aniversário (DD/MM)", placeholder="Ex: 25/12", max_chars=5)
                    tel_cli = col3.text_input("Telefone")
                    if st.form_submit_button("Cadastrar Cliente") and nome_cli:
                        conn = conectar_banco()
                        conn.cursor().execute("INSERT INTO clientes (nome, data_nascimento, telefone, empresa_id) VALUES (%s, %s, %s, %s)", (nome_cli, nasc_cli, tel_cli, emp_id))
                        conn.commit()
                        conn.close()
                        st.success("Cliente cadastrado!")
                        st.rerun()

            df_clientes = carregar_dados("SELECT * FROM clientes WHERE empresa_id = %s ORDER BY nome", (emp_id,))
            
            with sub_edit_cli:
                if not df_clientes.empty:
                    clientes_dict = dict(zip(df_clientes['nome'], df_clientes['id']))
                    cli_selecionado = st.selectbox("Selecione o Cliente", options=list(clientes_dict.keys()), key="sel_edit_cli")
                    cli_id = clientes_dict[cli_selecionado]
                    cli_atual = df_clientes[df_clientes['id'] == cli_id].iloc[0]
                    
                    with st.form("form_edit_cliente"):
                        col1, col2, col3 = st.columns(3)
                        novo_nome_cli = col1.text_input("Nome", value=cli_atual['nome'])
                        novo_nasc_cli = col2.text_input("Aniversário", value=cli_atual['data_nascimento'], max_chars=5)
                        novo_tel_cli = col3.text_input("Telefone", value=cli_atual['telefone'])
                        if st.form_submit_button("Salvar Alterações"):
                            conn = conectar_banco()
                            conn.cursor().execute("UPDATE clientes SET nome=%s, data_nascimento=%s, telefone=%s WHERE id=%s AND empresa_id=%s", (novo_nome_cli, novo_nasc_cli, novo_tel_cli, cli_id, emp_id))
                            conn.commit()
                            conn.close()
                            st.success("Atualizado com sucesso!")
                            st.rerun()

            with sub_del_cli:
                if not df_clientes.empty:
                    clientes_dict = dict(zip(df_clientes['nome'], df_clientes['id']))
                    cli_del_selecionado = st.selectbox("Selecione para excluir", options=list(clientes_dict.keys()), key="sel_del_cli")
                    with st.form("form_del_cliente"):
                        if st.form_submit_button("Excluir Cliente", type="primary"):
                            conn = conectar_banco()
                            conn.cursor().execute("DELETE FROM clientes WHERE id=%s AND empresa_id=%s", (clientes_dict[cli_del_selecionado], emp_id))
                            conn.commit()
                            conn.close()
                            st.success("Excluído com sucesso!")
                            st.rerun()

            with sub_hist_cli:
                if not df_clientes.empty:
                    clientes_dict_hist = dict(zip(df_clientes['nome'], df_clientes['id']))
                    cli_hist_selecionado = st.selectbox("Selecione o Cliente", options=list(clientes_dict_hist.keys()), key="sel_hist_cli")
                    df_h = carregar_dados("""
                        SELECT v.codigo_venda AS "Nº Venda", p.nome AS "Produto", v.quantidade AS "Qtd", v.valor_total AS "Total (R$)", v.data_venda AS "Data"
                        FROM vendas v JOIN produtos p ON v.produto_id = p.id WHERE v.cliente_id = %s AND v.empresa_id = %s ORDER BY v.id DESC
                    """, (clientes_dict_hist[cli_hist_selecionado], emp_id))
                    if not df_h.empty:
                        st.dataframe(df_h, use_container_width=True, hide_index=True)
                    else:
                        st.info("Nenhuma compra registrada para este cliente ainda.")

            if not df_clientes.empty:
                st.markdown("---")
                st.subheader("Lista de Clientes Cadastrados")
                st.dataframe(df_clientes.drop(columns=['empresa_id']), use_container_width=True, hide_index=True)

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
            st.subheader("🛒 Frente de Caixa")
            
            # Carrega dados atualizados para o PDV
            df_cli = carregar_dados("SELECT id, nome FROM clientes WHERE empresa_id=%s ORDER BY nome", (emp_id,))
            df_pro = carregar_dados("SELECT id, nome, valor, quantidade FROM produtos WHERE empresa_id=%s ORDER BY nome", (emp_id,))
            
            if not df_cli.empty and not df_pro.empty:
                # 1. Configurações da Venda
                c_cli, c_data = st.columns(2)
                cliente_pdv = c_cli.selectbox("Cliente:", options=df_cli['nome'].tolist())
                data_venda_input = c_data.date_input("Data da Venda", format="DD/MM/YYYY", value=date.today())
                
                c_pag, c_parc = st.columns(2)
                f_pag = c_pag.selectbox("Forma de Pagamento:", ["Pix", "Crédito", "Débito", "Dinheiro", "Crediário"])
                qtd_parcelas = c_parc.number_input("Número de Parcelas:", min_value=1, max_value=12, value=1, step=1)
                
                sugestao_venc = date.today() if qtd_parcelas == 1 else date.today() + timedelta(days=30)
                data_1_venc = st.date_input("Data do 1º Vencimento:", value=sugestao_venc, format="DD/MM/YYYY")
                
                st.markdown("---")
                
                # 2. Seleção de Produto e Preço de Tabela
                prod_pdv = st.selectbox("Produto:", options=df_pro['nome'].tolist())
                p_info = df_pro[df_pro['nome'] == prod_pdv].iloc[0]
                st.info(f"🏷️ Preço de Tabela: **R$ {p_info['valor']:.2f}**")
                
                with st.form("form_add_carrinho", clear_on_submit=True):
                    c3, c4 = st.columns(2)
                    q_pdv = c3.number_input("Quantidade:", min_value=1, step=1, value=1)
                    desc_pdv = c4.number_input("Desconto Unitário (R$):", min_value=0.0, step=1.0, format="%.2f")
                    
                    if st.form_submit_button("➕ Adicionar ao Carrinho"):
                        if (p_info['quantidade']) >= q_pdv:
                            st.session_state['carrinho'].append({
                                'id': p_info['id'], 'nome': prod_pdv, 'qtd': q_pdv, 
                                'unit': p_info['valor'], 'desc': desc_pdv, 
                                'total': (p_info['valor'] - desc_pdv) * q_pdv
                            })
                            st.rerun()
                        else: st.error("Estoque insuficiente!")

                # 3. Carrinho e Finalização
                if st.session_state['carrinho']:
                    df_car = pd.DataFrame(st.session_state['carrinho'])
                    st.table(df_car[['nome', 'qtd', 'unit', 'desc', 'total']])
                    total_pdv = df_car['total'].sum()
                    st.header(f"Total da Venda: R$ {total_pdv:.2f}")
                    
                    c1_finalizar, c2_limpar = st.columns(2)
                    
                    if c1_finalizar.button("✅ Finalizar Venda", type="primary", use_container_width=True):
                        try:
                            conn = conectar_banco()
                            cur = conn.cursor()
                            
                            cur.execute("SELECT MAX(codigo_venda) FROM vendas WHERE empresa_id=%s", (int(emp_id),))
                            resultado = cur.fetchone()[0]
                            novo_cod = int(resultado + 1) if resultado else 1
                            
                            data_v = data_venda_input.strftime("%d/%m/%Y")
                            cli_id_v = int(df_cli[df_cli['nome'] == cliente_pdv].iloc[0]['id'])
                            
                            # Inserção de itens
                            for it in st.session_state['carrinho']:
                                cur.execute("""INSERT INTO vendas (codigo_venda, cliente_id, produto_id, quantidade, data_venda, valor_total, empresa_id, valor_unitario, desconto, forma_pagamento) 
                                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                           (novo_cod, cli_id_v, int(it['id']), int(it['qtd']), data_v, float(it['total']), int(emp_id), float(it['unit']), float(it['desc']), f_pag))
                                
                                cur.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE id=%s", (int(it['qtd']), int(it['id'])))
                            
                            # Inserção no Financeiro
                            val_parc = float(total_pdv / qtd_parcelas)
                            dt_venc = data_1_venc
                            for i in range(1, int(qtd_parcelas) + 1):
                                status_venda = 'Pendente' if qtd_parcelas > 1 else ('Pago' if f_pag != "Crediário" else 'Pendente')
                                cur.execute("INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                           (novo_cod, cli_id_v, int(i), int(qtd_parcelas), val_parc, dt_venc.strftime("%d/%m/%Y"), status_venda, int(emp_id)))
                                dt_venc += timedelta(days=30)
                            
                            # --- CAPTURA E MONTAGEM DO LINK DO WHATSAPP ---
                            cur.execute("SELECT telefone FROM clientes WHERE id = %s", (cli_id_v,))
                            tel_cli = cur.fetchone()[0]
                            
                            msg = f"Olá, {cliente_pdv}! 🌸\n\nResumo da sua compra (*{data_v}*):\n🧾 *Venda Nº {novo_cod}*\n💰 *Total:* R$ {total_pdv:.2f}\n"
                            if qtd_parcelas > 1:
                                msg += f"💳 *Parcelamento:* {qtd_parcelas}x de R$ {val_parc:.2f}\n"
                            else:
                                msg += f"💳 *Forma de Pagto:* {f_pag}\n"
                            msg += "\nMuito obrigada pela preferência! ✨"
                            
                            if tel_cli:
                                tel_limpo = ''.join(filter(str.isdigit, str(tel_cli)))
                                if len(tel_limpo) >= 10:
                                    if not tel_limpo.startswith('55'): tel_limpo = '55' + tel_limpo
                                    st.session_state['zap_link'] = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                                    st.session_state['zap_msg'] = msg
                                    st.session_state['zap_codigo'] = novo_cod
                                    st.session_state['zap_total'] = total_pdv
                            
                            conn.commit()
                            conn.close()
                            
                            st.session_state['carrinho'] = []
                            st.success(f"Venda {novo_cod} Finalizada com sucesso!")
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"ERRO REVELADO DO BANCO DE DADOS: {e}")
                            if 'conn' in locals():
                                conn.rollback()
                                conn.close()

                    if c2_limpar.button("🗑️ Limpar Carrinho", use_container_width=True): 
                        st.session_state['carrinho'] = []
                        st.rerun()
            else: 
                st.warning("Cadastre clientes e produtos antes de vender.")
                
            # --- TELA DO RECIBO DO WHATSAPP (APARECE APÓS O RECARREGAMENTO) ---
            if 'zap_link' in st.session_state and st.session_state['zap_link']:
                st.markdown("---")
                with st.container(border=True):
                    st.success(f"🎉 Venda Nº {st.session_state['zap_codigo']} registrada com sucesso! Total: R$ {st.session_state['zap_total']:.2f}")
                    st.subheader("📲 Enviar Recibo via WhatsApp")
                    st.text_area("Prévia do texto:", value=st.session_state['zap_msg'], height=150, disabled=True)
                    st.link_button("🟢 Abrir WhatsApp e Enviar", st.session_state['zap_link'], type="primary", use_container_width=True)
                    if st.button("❌ Fechar Painel do Recibo", use_container_width=True):
                        del st.session_state['zap_link']
                        if 'zap_msg' in st.session_state: del st.session_state['zap_msg']
                        if 'zap_codigo' in st.session_state: del st.session_state['zap_codigo']
                        if 'zap_total' in st.session_state: del st.session_state['zap_total']
                        st.rerun()                
        with tab_compra:
            st.subheader("📥 Entrada de Mercadorias (via PDF Direto)")
            st.info("Faça o upload do PDF do seu pedido para processar as mercadorias automaticamente. Você poderá ajustar as quantidades antes de confirmar a entrada.")

            # Componente de upload configurado exclusivamente para arquivos PDF
            arquivo_pdf = st.file_uploader("Selecione o arquivo PDF do Pedido", type=["pdf"])

            if arquivo_pdf:
                if st.button("🔍 Processar PDF do Pedido", type="secondary"):
                    import pdfplumber
                    import re
                    
                    try:
                        texto_extraido = ""
                        # O pdfplumber lê o arquivo carregado diretamente da memória
                        with pdfplumber.open(arquivo_pdf) as pdf:
                            for pagina in pdf.pages:
                                texto_pagina = pagina.extract_text()
                                if texto_pagina:
                                    texto_extraido += texto_pagina + "\n"
                        
                        if texto_extraido:
                            linhas = [l.strip() for l in texto_extraido.split('\n') if l.strip()]
                            produtos_extraidos = []
                            
                            # Varre o texto aplicando a regra de extração com base no padrão visual
                            for i, linha in enumerate(linhas):
                                match_codigo = re.match(r'^(\d{8})', linha)
                                if match_codigo:
                                    codigo = match_codigo.group(1)
                                    nome_produto = linha[8:].strip()
                                    preco_unitario = 0.0
                                    quantidade = 1
                                    
                                    # Captura informações complementares nas linhas imediatamente seguintes
                                    for j in range(i + 1, min(i + 6, len(linhas))):
                                        if 'R$' in linhas[j] and 'Pontos' not in linhas[j] and not re.match(r'^\d+\s+R\$', linhas[j]):
                                            preco_str = linhas[j].replace('R$', '').replace('.', '').replace(',', '.').strip()
                                            try: preco_unitario = float(preco_str)
                                            except: pass
                                        elif re.match(r'^(\d+)\s+R\$', linhas[j]):
                                            match_qtd = re.match(r'^(\d+)\s+R\$', linhas[j])
                                            quantidade = int(match_qtd.group(1))
                                            break
                                        elif not linhas[j].startswith('Pontos') and 'R$' not in linhas[j] and not re.match(r'^\d{8}', linhas[j]) and "Total" not in linhas[j]:
                                            nome_produto += " " + linhas[j]
                                    
                                    if "Folheto" not in nome_produto and "Preço com Desconto" not in nome_produto:
                                        produtos_extraidos.append({
                                            "Código": codigo,
                                            "Produto": nome_produto.strip(),
                                            "Preço Un. (R$)": preco_unitario,
                                            "Quantidade": quantidade
                                        })
                            
                            if produtos_extraidos:
                                st.session_state['produtos_pedido'] = produtos_extraidos
                                st.success(f"📊 {len(produtos_extraidos)} produtos identificados com sucesso! Ajuste-os abaixo.")
                            else:
                                st.error("❌ O arquivo foi lido, mas nenhum item foi identificado no formato padrão de pedidos.")
                        else:
                            st.error("❌ Não foi possível extrair texto do documento. Certifique-se de que não é um PDF digitalizado como imagem.")
                            
                    except Exception as erro_leitura:
                        st.error(f"Erro ao processar o arquivo PDF: {erro_leitura}")

            # Exibição da planilha interativa caso os dados estejam carregados
            if 'produtos_pedido' in st.session_state and st.session_state['produtos_pedido']:
                st.markdown("### ✏️ Planilha de Ajuste de Estoque")
                st.caption("Dê um duplo clique na célula de quantidade para alterar o valor. Para remover um item, selecione a linha correspondente e pressione 'Delete'.")
                
                df_original = pd.DataFrame(st.session_state['produtos_pedido'])
                
                # Exibe a tabela editável
                df_editado = st.data_editor(
                    df_original,
                    num_rows="dynamic",
                    use_container_width=True,
                    key="editor_pedido_estoque"
                )
                
                if st.button("💾 Confirmar e Dar Entrada no Estoque", type="primary"):
                    try:
                        conn = conectar_banco()
                        cur = conn.cursor()
                        
                        itens_salvos = 0
                        for _, row in df_editado.iterrows():
                            v_cod = str(row['Código'])
                            v_nome = str(row['Produto'])
                            v_qtd = int(row['Quantidade'])
                            v_valor = float(row['Preço Un. (R$)'])
                            
                            # Verifica duplicidade para somar ao estoque existente ou abrir novo cadastro
                            cur.execute("SELECT id FROM produtos WHERE referencia = %s AND empresa_id = %s", (v_cod, emp_id))
                            prod_existe = cur.fetchone()
                            
                            if prod_existe:
                                cur.execute("UPDATE produtos SET quantidade = quantidade + %s WHERE id = %s", (v_qtd, prod_existe[0]))
                            else:
                                cur.execute("""INSERT INTO produtos (nome, quantidade, valor, marca, categoria, empresa_id, referencia) 
                                               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                                           (v_nome, v_qtd, v_valor, "Mary Kay", "Geral", emp_id, v_cod))
                            itens_salvos += 1
                        
                        conn.commit()
                        conn.close()
                        
                        st.success(f"✅ Sucesso! Estoque atualizado para {itens_salvos} itens.")
                        del st.session_state['produtos_pedido']
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Erro ao salvar dados no banco: {e}")
                        if 'conn' in locals(): conn.rollback(); conn.close()

                if st.button("❌ Cancelar Importação"):
                    del st.session_state['produtos_pedido']
                    st.rerun()
    # ==========================================
    # MÓDULO 4: FINANCEIRO (Contas a Receber e Pagar COMPLETOS)
    # ==========================================
    elif modulo == "💰 Financeiro":
        st.title("💰 Gestão Financeira")
        tab_rec, tab_pag = st.tabs(["🟢 Contas a Receber (Vendas)", "🔴 Contas a Pagar (Despesas)"])
        
        # --- CONTAS A RECEBER 100% RESTAURADO ---
        with tab_rec:
            st.header("💰 Controle Financeiro de Parcelas")
            df_financeiro = carregar_dados("""
                SELECT cr.id AS "ID Parcela", cr.venda_codigo AS "Nº Venda", c.nome AS "Cliente",
                       cr.num_parcela AS "Parcela", cr.total_parcelas AS "De",
                       cr.valor_parcela AS "Valor (R$)", cr.data_vencimento AS "Vencimento", cr.status AS "Status"
                FROM contas_receber cr JOIN clientes c ON cr.cliente_id = c.id WHERE cr.empresa_id = %s ORDER BY TO_DATE(cr.data_vencimento, 'DD/MM/YYYY') ASC
            """, (emp_id,))
            
            if not df_financeiro.empty:
                df_financeiro['Data_Venc_Obj'] = pd.to_datetime(df_financeiro['Vencimento'], format='%d/%m/%Y', errors='coerce').dt.date
                hoje = date.today()
                
                v_rec = df_financeiro[df_financeiro['Status'] == 'Pago']['Valor (R$)'].sum()
                v_pend = df_financeiro[df_financeiro['Status'] == 'Pendente']['Valor (R$)'].sum()
                mask_atraso = (df_financeiro['Status'] == 'Pendente') & (df_financeiro['Data_Venc_Obj'] < hoje)
                v_atr = df_financeiro[mask_atraso]['Valor (R$)'].sum()
                
                col_met1, col_met2, col_met3 = st.columns(3)
                col_met1.metric("✅ Total Já Recebido", f"R$ {v_rec:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                col_met2.metric("⏳ A Receber (No Prazo)", f"R$ {(v_pend - v_atr):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                col_met3.metric("🚨 Pagamentos Atrasados", f"R$ {v_atr:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), delta="- Atenção" if v_atr > 0 else "Tudo em dia!", delta_color="inverse")
                
                st.markdown("---")
                
                df_p = df_financeiro[df_financeiro['Status'] == 'Pendente']
                with st.expander("✅ Registrar Recebimento de Parcela", expanded=True):
                    if not df_p.empty:
                        with st.form("form_baixa"):
                            op_b = df_p.apply(lambda x: f"Venda {x['Nº Venda']} | {x['Cliente']} | Parc {x['Parcela']}/{x['De']} | R$ {x['Valor (R$)']:.2f} | Venc: {x['Vencimento']}", axis=1).tolist()
                            p_sel = st.selectbox("Selecione a parcela paga:", options=op_b)
                            
                            col_b1, col_b2 = st.columns([1, 2])
                            data_pag_real = col_b1.date_input("Data do Pagamento", value=hoje, format="DD/MM/YYYY")
                            
                            if st.form_submit_button("💰 Confirmar Baixa", type="primary"):
                                idx_b = df_p['ID Parcela'].tolist()[op_b.index(p_sel)]
                                conn = conectar_banco()
                                conn.cursor().execute("UPDATE contas_receber SET status = 'Pago', data_pagamento = %s WHERE id = %s AND empresa_id = %s", (data_pag_real.strftime("%d/%m/%Y"), idx_b, emp_id))
                                conn.commit()
                                conn.close()
                                st.success("Pagamento registrado com sucesso!")
                                st.rerun()
                    else:
                        st.success("🎉 Nenhuma parcela pendente! Todos os clientes estão em dia.")
                
                st.markdown("---")
                
                st.subheader("📋 Relatório de Parcelas e Boletos")
                filtro_status = st.radio("Filtrar por Status:", ["Todos", "Pendentes", "Pagos", "Atrasados"], horizontal=True)
                
                df_view = df_financeiro.copy()
                if filtro_status == "Pendentes":
                    df_view = df_view[df_view['Status'] == 'Pendente']
                elif filtro_status == "Pagos":
                    df_view = df_view[df_view['Status'] == 'Pago']
                elif filtro_status == "Atrasados":
                    df_view = df_view[(df_view['Status'] == 'Pendente') & (df_view['Data_Venc_Obj'] < hoje)]
                    
                st.dataframe(df_view.drop(columns=['Data_Venc_Obj', 'ID Parcela']), use_container_width=True, hide_index=True)
            else:
                st.info("Nenhuma movimentação financeira registrada ainda. Faça sua primeira venda para alimentar o caixa!")

        # --- CONTAS A PAGAR ---
        with tab_pag:
            st.subheader("Compromissos e Pagamentos")
            df_p = carregar_dados("""
                SELECT cp.id, f.nome as fornecedor, cp.valor_parcela, cp.data_vencimento, cp.status 
                FROM contas_pagar cp JOIN fornecedores f ON cp.fornecedor_id = f.id WHERE cp.empresa_id = %s ORDER BY cp.id DESC
            """, (emp_id,))
            if not df_p.empty:
                st.dataframe(df_p, use_container_width=True)
            else: st.info("Nenhuma conta a pagar registrada.")
