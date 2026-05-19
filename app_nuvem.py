import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
from datetime import datetime, date, timedelta

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
st.set_page_config(page_title="Sistema de Gestão Multi-Empresas", layout="wide")

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

# --- TELA DO ADMINISTRADOR MASTER ---
elif st.session_state['perfil'] == 'master':
    st.title("👑 Painel de Administração Master")
    st.caption("Gerenciamento global de empresas parceiras e contas de usuários.")
    
    if st.sidebar.button("🚪 Sair do Sistema"):
        st.session_state.clear()
        st.rerun()
        
    aba_cad_empresa, aba_cad_usuario, aba_senhas = st.tabs(["🏢 Empresas Cadastradas", "👤 Logins de Funcionários", "🔒 Gerenciar Senhas"])
    
    with aba_cad_empresa:
        st.subheader("Cadastrar Nova Empresa Parceira")
        with st.form("form_nova_empresa", clear_on_submit=True):
            nome_emp = st.text_input("Nome Comercial / Marca")
            cnpj_emp = st.text_input("CNPJ ou Identificação (Opcional)")
            if st.form_submit_button("Salvar Empresa") and nome_emp:
                conn = conectar_banco()
                conn.cursor().execute("INSERT INTO empresas (nome, cnpj) VALUES (%s, %s)", (nome_emp, cnpj_emp))
                conn.commit()
                conn.close()
                st.success(f"Empresa '{nome_emp}' configurada com sucesso no servidor!")
                st.rerun()
                
        st.markdown("---")
        df_empresas = carregar_dados("SELECT id AS \"ID\", nome AS \"Empresa\", cnpj AS \"CNPJ\" FROM empresas ORDER BY id")
        st.dataframe(df_empresas, use_container_width=True, hide_index=True)

    with aba_cad_usuario:
        st.subheader("Criar Credenciais de Acesso")
        df_emp_list = carregar_dados("SELECT * FROM empresas ORDER BY id")
        if not df_emp_list.empty:
            dict_empresas = dict(zip(df_emp_list['nome'], df_emp_list['id']))
            
            with st.form("form_novo_usuario", clear_on_submit=True):
                nome_usu = st.text_input("Nome do Profissional")
                emp_usu = st.selectbox("Vincular à Empresa", options=list(dict_empresas.keys()))
                col_u1, col_u2 = st.columns(2)
                login_usu = col_u1.text_input("Login de Entrada")
                senha_usu = col_u2.text_input("Senha Provisória", type="password")
                
                if st.form_submit_button("Criar Conta") and login_usu and senha_usu:
                    emp_id_selecionada = dict_empresas[emp_usu]
                    try:
                        conn = conectar_banco()
                        conn.cursor().execute("INSERT INTO usuarios (nome, login, senha, empresa_id, perfil) VALUES (%s, %s, %s, %s, 'comum')", 
                                             (nome_usu, login_usu, senha_usu, emp_id_selecionada))
                        conn.commit()
                        conn.close()
                        st.success(f"Acesso criado! O usuário '{login_usu}' agora responde pela empresa '{emp_usu}'.")
                        st.rerun()
                    except:
                        st.error("Erro: Este login já está sendo utilizado por outra pessoa no sistema.")
        else:
            st.warning("Cadastre ao menos uma empresa antes de criar contas de acesso.")
            
        st.markdown("---")
        st.subheader("Todos os Usuários do Sistema")
        df_usuarios = carregar_dados("""
            SELECT u.id AS "ID", u.nome AS "Nome", u.login AS "Login", e.nome AS "Empresa", u.perfil AS "Perfil" 
            FROM usuarios u JOIN empresas e ON u.empresa_id = e.id ORDER BY e.nome, u.nome
        """)
        
        if not df_usuarios.empty:
            st.dataframe(df_usuarios, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhum usuário cadastrado ainda.")

    with aba_senhas:
        st.subheader("Alterar Senha de Contas")
        st.caption("Como Administrador Master, você pode redefinir a senha de qualquer conta do sistema.")
        df_todos_usu = carregar_dados("SELECT id, nome, login FROM usuarios ORDER BY nome")
        
        if not df_todos_usu.empty:
            dict_todos_usu = {f"{row['nome']} ({row['login']})": row['id'] for _, row in df_todos_usu.iterrows()}
            usu_sel_senha = st.selectbox("Selecione o Usuário para Alterar a Senha", options=list(dict_todos_usu.keys()))
            id_usu_senha = dict_todos_usu[usu_sel_senha]
            
            with st.form("form_master_alterar_senha", clear_on_submit=True):
                nova_senha_master = st.text_input("Nova Senha", type="password")
                if st.form_submit_button("Confirmar Alteração de Senha"):
                    conn = conectar_banco()
                    cursor = conn.cursor()
                    cursor.execute("UPDATE usuarios SET senha = %s WHERE id = %s", (nova_senha_master, id_usu_senha))
                    conn.commit()
                    conn.close()
                    st.success("Senha atualizada com sucesso!")
        else:
            st.info("Nenhum usuário encontrado.")

# --- TELA OPERACIONAL DO ERP (FUNCIONÁRIOS / EMPRESAS) ---
else:
    emp_id = st.session_state['empresa_id']
    
    st.sidebar.markdown(f"👤 **Operador:** {st.session_state['usuario_nome']}")
    
    with st.sidebar.expander("🔒 Alterar Minha Senha"):
        with st.form("form_alterar_senha_propria", clear_on_submit=True):
            senha_atual = st.text_input("Senha Atual", type="password")
            nova_senha = st.text_input("Nova Senha", type="password")
            if st.form_submit_button("Atualizar Senha"):
                conn = conectar_banco()
                cursor = conn.cursor()
                cursor.execute("SELECT senha FROM usuarios WHERE id = %s", (st.session_state['usuario_id'],))
                senha_banco = cursor.fetchone()[0]
                if senha_banco == senha_atual:
                    cursor.execute("UPDATE usuarios SET senha = %s WHERE id = %s", (nova_senha, st.session_state['usuario_id']))
                    conn.commit()
                    st.success("Senha alterada com sucesso!")
                else:
                    st.error("Senha atual incorreta.")
                conn.close()

    if st.sidebar.button("🚪 Sair do Sistema"):
        st.session_state.clear()
        st.rerun()
        
    st.title("📦 Sistema de Gestão Comercial")
    
    df_produtos = carregar_dados("SELECT * FROM produtos WHERE empresa_id = %s ORDER BY nome", (emp_id,))
    df_clientes = carregar_dados("SELECT * FROM clientes WHERE empresa_id = %s ORDER BY nome", (emp_id,))
    df_categorias = carregar_dados("SELECT * FROM categorias WHERE empresa_id = %s ORDER BY nome", (emp_id,))

    lista_categorias = df_categorias['nome'].tolist() if not df_categorias.empty else ["Geral"]

    aba_dashboard, aba_estoque, aba_clientes, aba_vendas, aba_historico, aba_categorias, aba_financeiro = st.tabs([
        "📊 Dashboard",
        "📦 Estoque de Produtos", 
        "👥 Clientes", 
        "🛒 Registrar Venda (PDV)", 
        "📜 Histórico Geral",
        "🏷️ Categorias",
        "💰 Financeiro"
    ])

    # ==========================================
    # ABA 0: DASHBOARD E MÉTRICAS
    # ==========================================
    with aba_dashboard:
        st.header("📊 Painel de Desempenho")
        
        query_dash = """
            SELECT v.data_venda, v.valor_total, v.quantidade, p.nome AS produto, p.categoria 
            FROM vendas v 
            JOIN produtos p ON v.produto_id = p.id 
            WHERE v.empresa_id = %s
        """
        df_dash = carregar_dados(query_dash, (emp_id,))
        
        if not df_dash.empty:
            df_dash['Data_Obj'] = pd.to_datetime(df_dash['data_venda'], format='%d/%m/%Y', errors='coerce').dt.date
            df_dash = df_dash.dropna(subset=['Data_Obj'])
            df_dash = df_dash.sort_values('Data_Obj')
            
            st.markdown("### 🔍 Período de Análise")
            opcoes_periodo = ["Mês Atual", "Hoje", "Últimos 7 Dias", "Últimos 15 Dias", "Últimos 30 Dias", "Mês Anterior", "Todo o Período", "Personalizado"]
            periodo_selecionado = st.selectbox("Selecione o filtro:", opcoes_periodo)
            
            hoje = date.today()
            if periodo_selecionado == "Hoje":
                d_ini, d_fim = hoje, hoje
            elif periodo_selecionado == "Últimos 7 Dias":
                d_ini, d_fim = hoje - timedelta(days=7), hoje
            elif periodo_selecionado == "Últimos 15 Dias":
                d_ini, d_fim = hoje - timedelta(days=15), hoje
            elif periodo_selecionado == "Últimos 30 Dias":
                d_ini, d_fim = hoje - timedelta(days=30), hoje
            elif periodo_selecionado == "Mês Atual":
                d_ini, d_fim = hoje.replace(day=1), hoje
            elif periodo_selecionado == "Mês Anterior":
                primeiro_dia_mes_atual = hoje.replace(day=1)
                d_fim = primeiro_dia_mes_atual - timedelta(days=1)
                d_ini = d_fim.replace(day=1)
            elif periodo_selecionado == "Personalizado":
                col_d_ini, col_d_fim = st.columns(2)
                d_ini = col_d_ini.date_input("Data Inicial (Dashboard)", value=hoje - timedelta(days=30), format="DD/MM/YYYY")
                d_fim = col_d_fim.date_input("Data Final (Dashboard)", value=hoje, format="DD/MM/YYYY")
            else:
                d_ini, d_fim = None, None
                
            if d_ini and d_fim:
                mask_dash = (df_dash['Data_Obj'] >= d_ini) & (df_dash['Data_Obj'] <= d_fim)
                df_dash = df_dash.loc[mask_dash]
                
            st.markdown("---")
            
            if not df_dash.empty:
                faturamento_total = df_dash['valor_total'].sum()
                total_vendas = len(df_dash)
                ticket_medio = faturamento_total / total_vendas if total_vendas > 0 else 0
                
                col_d1, col_d2, col_d3 = st.columns(3)
                col_d1.metric("💰 Faturamento do Período", f"R$ {faturamento_total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                col_d2.metric("🛍️ Total de Vendas (Itens)", f"{total_vendas}")
                col_d3.metric("🎯 Ticket Médio", f"R$ {ticket_medio:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                
                st.markdown("---")
                
                st.subheader("📈 Evolução de Faturamento Diário")
                df_fat_dia = df_dash.groupby('Data_Obj')['valor_total'].sum().reset_index()
                fig_fat = px.line(df_fat_dia, x='Data_Obj', y='valor_total', markers=True, 
                                  labels={'Data_Obj': 'Data', 'valor_total': 'Faturamento (R$)'},
                                  template='plotly_white', line_shape='spline')
                fig_fat.update_traces(line_color='#0068c9', line_width=3)
                st.plotly_chart(fig_fat, use_container_width=True)
                
                st.markdown("---")
                
                col_graf1, col_graf2 = st.columns(2)
                
                with col_graf1:
                    st.subheader("🏆 Top Produtos")
                    df_top_prod = df_dash.groupby('produto')['quantidade'].sum().reset_index()
                    df_top_prod = df_top_prod.sort_values('quantidade', ascending=False).head(5)
                    df_top_prod = df_top_prod.sort_values('quantidade', ascending=True) 
                    
                    df_top_prod['produto_curto'] = df_top_prod['produto'].apply(lambda x: (str(x)[:22] + '...') if len(str(x)) > 22 else str(x))
                    
                    # CORREÇÃO DE COR: Usando cor vibrante sólida e removendo o "esmaecimento" (fading)
                    fig_top = px.bar(df_top_prod, x='quantidade', y='produto', orientation='h',
                                     labels={'quantidade': 'Qtd', 'produto': ''},
                                     template='plotly_white',
                                     text='quantidade',
                                     custom_data=['produto'],
                                     color_discrete_sequence=['#0068c9']) # Azul vibrante puro!
                    
                    fig_top.update_yaxes(tickmode='array', tickvals=df_top_prod['produto'], ticktext=df_top_prod['produto_curto'])
                    fig_top.update_traces(hovertemplate="<b>%{customdata[0]}</b><br>Unidades vendidas: %{x}", textposition='outside')
                    fig_top.update_layout(margin=dict(l=0, r=20, t=30, b=0))
                    
                    st.plotly_chart(fig_top, use_container_width=True)
                    
                with col_graf2:
                    st.subheader("🍕 Vendas por Categoria")
                    df_cat = df_dash.groupby('categoria')['valor_total'].sum().reset_index()
                    
                    # CORREÇÃO DE COR: Usando uma paleta mais viva (Bold)
                    fig_cat = px.pie(df_cat, values='valor_total', names='categoria', hole=0.4,
                                     template='plotly_white',
                                     color_discrete_sequence=px.colors.qualitative.Bold) 
                                     
                    fig_cat.update_traces(textposition='inside', textinfo='percent+label')
                    fig_cat.update_layout(margin=dict(l=0, r=0, t=30, b=0), showlegend=False)
                    st.plotly_chart(fig_cat, use_container_width=True)
            else:
                st.warning(f"Não há vendas registradas para o período selecionado ({periodo_selecionado}).")
                
        else:
            st.info("📊 Não há dados de vendas suficientes para gerar os gráficos. Registre suas primeiras vendas para acompanhar seu desempenho!")

    # ABA: CATEGORIAS
    with aba_categorias:
        st.header("Gerenciamento de Categorias")
        col_add_cat, col_del_cat = st.columns(2)
        
        with col_add_cat:
            with st.expander("➕ Nova Categoria", expanded=True):
                with st.form("form_categoria", clear_on_submit=True):
                    nova_cat_nome = st.text_input("Nome da Categoria")
                    if st.form_submit_button("Cadastrar Categoria") and nova_cat_nome:
                        try:
                            conn = conectar_banco()
                            conn.cursor().execute("INSERT INTO categorias (nome, empresa_id) VALUES (%s, %s)", (nova_cat_nome.strip(), emp_id))
                            conn.commit()
                            conn.close()
                            st.success(f"Categoria '{nova_cat_nome}' adicionada!")
                            st.rerun()
                        except:
                            st.error("Erro ao salvar categoria.")
        
        with col_del_cat:
            with st.expander("❌ Excluir Categoria", expanded=True):
                with st.form("form_del_categoria"):
                    cat_para_excluir = st.selectbox("Selecione para excluir", options=lista_categorias)
                    if st.form_submit_button("Excluir Categoria", type="primary"):
                        conn = conectar_banco()
                        conn.cursor().execute("DELETE FROM categorias WHERE nome=%s AND empresa_id=%s", (cat_para_excluir, emp_id))
                        conn.commit()
                        conn.close()
                        st.success("Categoria excluída!")
                        st.rerun()

    # ABA: ESTOQUE DE PRODUTOS
    with aba_estoque:
        st.header("Gerenciamento de Estoque")
        sub_add_prod, sub_edit_prod, sub_del_prod = st.tabs(["➕ Cadastrar", "✏️ Editar", "❌ Excluir"])
        
        with sub_add_prod:
            with st.form("form_produto", clear_on_submit=True):
                nome = st.text_input("Nome do Produto")
                c1, c2 = st.columns(2)
                qtd = c1.number_input("Quantidade Inicial", min_value=1, step=1)
                valor = c2.number_input("Valor Unitário (R$)", min_value=0.01, step=0.10, format="%.2f")
                c3, c4 = st.columns(2)
                marca = c3.text_input("Marca", value="Mary Kay")
                categoria = c4.selectbox("Categoria", options=lista_categorias)
                
                if st.form_submit_button("Cadastrar Produto") and nome:
                    conn = conectar_banco()
                    conn.cursor().execute("INSERT INTO produtos (nome, quantidade, valor, marca, categoria, empresa_id) VALUES (%s, %s, %s, %s, %s, %s)", (nome, qtd, valor, marca, categoria, emp_id))
                    conn.commit()
                    conn.close()
                    st.success(f"Produto '{nome}' cadastrado com sucesso!")
                    st.rerun()

        with sub_edit_prod:
            if not df_produtos.empty:
                produtos_dict = dict(zip(df_produtos['nome'], df_produtos['id']))
                prod_selecionado = st.selectbox("Selecione o Produto", options=list(produtos_dict.keys()), key="sel_edit_prod")
                prod_id = produtos_dict[prod_selecionado]
                prod_atual = df_produtos[df_produtos['id'] == prod_id].iloc[0]
                
                try:
                    index_cat_atual = lista_categorias.index(prod_atual['categoria'])
                except:
                    index_cat_atual = 0

                with st.form("form_edit_produto"):
                    novo_nome = st.text_input("Nome", value=prod_atual['nome'])
                    c1, c2 = st.columns(2)
                    nova_qtd = c1.number_input("Quantidade Total em Estoque", min_value=0, step=1, value=int(prod_atual['quantidade']))
                    novo_valor = c2.number_input("Valor Unitário (R$)", min_value=0.01, step=0.10, value=float(prod_atual['valor']), format="%.2f")
                    c3, c4 = st.columns(2)
                    nova_marca = c3.text_input("Marca", value=prod_atual['marca'])
                    nova_categoria = c4.selectbox("Categoria", options=lista_categorias, index=index_cat_atual)
                    
                    if st.form_submit_button("Salvar Alterações"):
                        conn = conectar_banco()
                        conn.cursor().execute("UPDATE produtos SET nome=%s, quantidade=%s, valor=%s, marca=%s, categoria=%s WHERE id=%s AND empresa_id=%s", (novo_nome, nova_qtd, novo_valor, nova_marca, nova_categoria, prod_id, emp_id))
                        conn.commit()
                        conn.close()
                        st.success("Produto atualizado!")
                        st.rerun()

        with sub_del_prod:
            if not df_produtos.empty:
                produtos_dict = dict(zip(df_produtos['nome'], df_produtos['id']))
                prod_del_selecionado = st.selectbox("Selecione para excluir", options=list(produtos_dict.keys()), key="sel_del_prod")
                with st.form("form_del_produto"):
                    if st.form_submit_button("Confirmar Exclusão", type="primary"):
                        conn = conectar_banco()
                        conn.cursor().execute("DELETE FROM produtos WHERE id=%s AND empresa_id=%s", (produtos_dict[prod_del_selecionado], emp_id))
                        conn.commit()
                        conn.close()
                        st.success("Produto excluído!")
                        st.rerun()
                        
        if not df_produtos.empty:
            st.markdown("---")
            st.subheader("Tabela de Estoque Atual")
            st.dataframe(df_produtos.drop(columns=['empresa_id']), use_container_width=True, hide_index=True)
            
            total_itens = int(df_produtos['quantidade'].sum())
            valor_total_estoque = float((df_produtos['quantidade'] * df_produtos['valor']).sum())
            
            st.markdown("---")
            col_m1, col_m2 = st.columns(2)
            col_m1.metric("📦 Quantidade Total (Unidades)", f"{total_itens}")
            col_m2.metric("💰 Valor Total Investido no Estoque", f"R$ {valor_total_estoque:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        else:
            st.info("Estoque vazio.")

    # ABA: CLIENTES
    with aba_clientes:
        st.header("Gerenciamento de Clientes")
        sub_add_cli, sub_edit_cli, sub_del_cli, sub_hist_cli = st.tabs(["➕ Cadastrar", "✏️ Editar", "❌ Excluir", "🛍️ Histórico"])
        
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
                    if st.form_submit_button("Salvar"):
                        conn = conectar_banco()
                        conn.cursor().execute("UPDATE clientes SET nome=%s, data_nascimento=%s, telefone=%s WHERE id=%s AND empresa_id=%s", (novo_nome_cli, novo_nasc_cli, novo_tel_cli, cli_id, emp_id))
                        conn.commit()
                        conn.close()
                        st.success("Atualizado!")
                        st.rerun()

        with sub_del_cli:
            if not df_clientes.empty:
                clientes_dict = dict(zip(df_clientes['nome'], df_clientes['id']))
                cli_del_selecionado = st.selectbox("Selecione para excluir", options=list(clientes_dict.keys()), key="sel_del_cli")
                with st.form("form_del_cliente"):
                    if st.form_submit_button("Excluir", type="primary"):
                        conn = conectar_banco()
                        conn.cursor().execute("DELETE FROM clientes WHERE id=%s AND empresa_id=%s", (clientes_dict[cli_del_selecionado], emp_id))
                        conn.commit()
                        conn.close()
                        st.success("Excluído!")
                        st.rerun()

        with sub_hist_cli:
            if not df_clientes.empty:
                clientes_dict_hist = dict(zip(df_clientes['nome'], df_clientes['id']))
                cli_hist_selecionado = st.selectbox("Selecione o Cliente", options=list(clientes_dict_hist.keys()))
                df_h = carregar_dados("""
                    SELECT v.codigo_venda AS "Nº Venda", p.nome AS "Produto", v.quantidade AS "Qtd", v.valor_total AS "Total (R$)", v.data_venda AS "Data"
                    FROM vendas v JOIN produtos p ON v.produto_id = p.id WHERE v.cliente_id = %s AND v.empresa_id = %s ORDER BY v.id DESC
                """, (clientes_dict_hist[cli_hist_selecionado], emp_id))
                if not df_h.empty:
                    st.dataframe(df_h, use_container_width=True, hide_index=True)

        if not df_clientes.empty:
            st.markdown("---")
            st.dataframe(df_clientes.drop(columns=['empresa_id']), use_container_width=True, hide_index=True)

    # ABA: REGISTRAR VENDA (PDV)
    with aba_vendas:
        st.header("🛒 Registrar Venda (PDV)")
        
        if 'zap_link' in st.session_state:
            st.success(f"🎉 Venda Nº {st.session_state['zap_codigo']} registrada! Total: R$ {st.session_state['zap_total']:.2f}")
            with st.container(border=True):
                st.subheader("📲 Enviar Recibo via WhatsApp")
                st.text_area("Prévias:", value=st.session_state['zap_msg'], height=220, disabled=True, key="msg_pdv_imediata")
                st.link_button("🟢 Abrir WhatsApp e Enviar", st.session_state['zap_link'], type="primary", use_container_width=True)
            st.markdown("---")

        if df_produtos.empty or df_clientes.empty:
            st.warning("É necessário ter clientes e produtos cadastrados.")
        else:
            col_cli, col_data = st.columns(2)
            clientes_dict = dict(zip(df_clientes['nome'], df_clientes['id']))
            cliente_selecionado = col_cli.selectbox("Cliente", options=list(clientes_dict.keys()))
            data_venda_input = col_data.date_input("Data da Venda", format="DD/MM/YYYY", value=date.today())
            
            col_pag, col_parc = st.columns(2)
            forma_pag = col_pag.selectbox("Forma de Pagamento", ["Pix", "Cartão de Crédito", "Cartão de Débito", "Dinheiro", "Crediário/Fiado"])
            qtd_parcelas = col_parc.number_input("Número de Parcelas", min_value=1, max_value=12, value=1, step=1)
            
            sugestao_venc = date.today() if qtd_parcelas == 1 else date.today() + timedelta(days=30)
            data_1_vencimento = st.date_input("Data de Vencimento (ou do 1º vencimento se parcelado)", format="DD/MM/YYYY", value=sugestao_venc)
            
            st.markdown("---")
            produtos_dict = dict(zip(df_produtos['nome'], df_produtos['id']))
            precos_dict = dict(zip(df_produtos['nome'], df_produtos['valor']))
            produto_selecionado = st.selectbox("Selecione o Produto", options=list(produtos_dict.keys()))
            preco_tabela = precos_dict[produto_selecionado]
            st.info(f"🏷️ Preço de Tabela: **R$ {preco_tabela:.2f}**")
            
            with st.form("form_add_carrinho", clear_on_submit=True):
                col_p1, col_p2 = st.columns(2)
                qtd_venda = col_p1.number_input("Quantidade", min_value=1, step=1)
                desconto_unit = col_p2.number_input("Desconto Unitário (R$)", min_value=0.0, step=1.0, format="%.2f")
                
                if st.form_submit_button("➕ Adicionar ao Carrinho"):
                    prod_id = produtos_dict[produto_selecionado]
                    estoque_atual = int(df_produtos.loc[df_produtos['id'] == prod_id, 'quantidade'].values[0])
                    qtd_no_carrinho = sum([item['quantidade'] for item in st.session_state['carrinho'] if item['produto_id'] == prod_id])
                    
                    if estoque_atual < (qtd_venda + qtd_no_carrinho):
                        st.error("Estoque insuficiente!")
                    elif (preco_tabela - desconto_unit) < 0:
                        st.error("Desconto incorreto!")
                    else:
                        if 'zap_link' in st.session_state:
                            del st.session_state['zap_link']
                        st.session_state['carrinho'].append({
                            'produto_id': prod_id, 'Produto': produto_selecionado, 'quantidade': qtd_venda,
                            'Valor Original (R$)': preco_tabela, 'Desconto (R$)': desconto_unit,
                            'Subtotal (R$)': (preco_tabela - desconto_unit) * qtd_venda
                        })
                        st.rerun()

            if st.session_state['carrinho']:
                st.markdown("---")
                df_carrinho = pd.DataFrame(st.session_state['carrinho'])
                st.dataframe(df_carrinho[['Produto', 'quantidade', 'Subtotal (R$)']], use_container_width=True, hide_index=True)
                total_venda = float(df_carrinho['Subtotal (R$)'].sum())
                
                with st.container(border=True):
                    st.markdown(f"## 💰 Total da Venda: R$ {total_venda:.2f}")
                    valor_entrada = st.number_input("💸 Valor da Entrada (R$)", min_value=0.0, max_value=total_venda, format="%.2f")
                    valor_restante = total_venda - valor_entrada
                    
                    col_finalizar, col_limpar = st.columns([2, 1])
                    if col_finalizar.button("✅ Finalizar Venda", type="primary", use_container_width=True):
                        cli_id = clientes_dict[cliente_selecionado]
                        data_venda_formatada = data_venda_input.strftime("%d/%m/%Y")
                        
                        conn = conectar_banco()
                        cursor = conn.cursor()
                        cursor.execute("SELECT MAX(codigo_venda) FROM vendas WHERE empresa_id = %s", (emp_id,))
                        res_m = cursor.fetchone()[0]
                        novo_codigo_venda = (res_m if res_m is not None else 0) + 1
                        
                        for item in st.session_state['carrinho']:
                            prop = item['Subtotal (R$)'] / total_venda if total_venda > 0 else 0
                            cursor.execute("""
                                INSERT INTO vendas (codigo_venda, cliente_id, produto_id, quantidade, data_venda, valor_total, valor_entrada, valor_restante, valor_unitario, desconto, forma_pagamento, prazo, empresa_id)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (novo_codigo_venda, cli_id, item['produto_id'], item['quantidade'], data_venda_formatada, item['Subtotal (R$)'], valor_entrada*prop, (item['Subtotal (R$)']-(valor_entrada*prop)), item['Valor Original (R$)'], item['Desconto (R$)'], forma_pag, f"{qtd_parcelas}x", emp_id))
                            cursor.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE id = %s AND empresa_id = %s", (item['quantidade'], item['produto_id'], emp_id))
                        
                        if valor_restante == 0:
                            cursor.execute("INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, data_pagamento, empresa_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)", (novo_codigo_venda, cli_id, 1, 1, total_venda, data_venda_formatada, 'Pago', data_venda_formatada, emp_id))
                        else:
                            val_parc = valor_restante / qtd_parcelas
                            dt_venc = data_1_vencimento
                            for i in range(1, qtd_parcelas + 1):
                                cursor.execute("INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (novo_codigo_venda, cli_id, i, qtd_parcelas, val_parc, dt_venc.strftime("%d/%m/%Y"), 'Pendente', emp_id))
                                dt_venc += timedelta(days=30)
                                
                        cursor.execute("SELECT telefone FROM clientes WHERE id = %s", (cli_id,))
                        tel_cliente = cursor.fetchone()[0]
                        conn.commit()
                        conn.close()
                        
                        msg = f"Olá, {cliente_selecionado}! 🌸\n\nResumo da sua compra (*{data_venda_formatada}*):\n🧾 *Venda Nº {novo_codigo_venda}*\n"
                        msg += f"💰 *Total:* R$ {total_venda:.2f}\n"
                        if valor_restante > 0:
                            msg += f"💳 *Plano:* {qtd_parcelas}x de R$ {valor_restante/qtd_parcelas:.2f}\n"
                        else:
                            msg += "✅ Quitado à vista.\n"
                        
                        import urllib.parse
                        tel_limpo = ''.join(filter(str.isdigit, str(tel_cliente or '')))
                        if tel_limpo and not tel_limpo.startswith('55'): tel_limpo = '55' + tel_limpo
                        st.session_state['zap_link'] = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                        st.session_state['zap_msg'] = msg
                        st.session_state['zap_codigo'] = novo_codigo_venda
                        st.session_state['zap_total'] = total_venda
                        st.session_state['carrinho'] = []
                        st.rerun()

                    if col_limpar.button("🗑️ Esvaziar", use_container_width=True):
                        st.session_state['carrinho'] = []
                        st.rerun()

    # ABA: HISTÓRICO GERAL DE VENDAS E EDIÇÃO
    with aba_historico:
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
                with st.expander("✏️ Editar Item de Venda (Valores e Datas)", expanded=False):
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
                            
                            try:
                                v_data_obj = datetime.strptime(v_data_str, "%d/%m/%Y").date()
                            except:
                                v_data_obj = date.today()
                                
                            with st.form("form_update_venda"):
                                c1, c2, c3 = st.columns(3)
                                nova_data = c1.date_input("Data da Venda", value=v_data_obj, format="DD/MM/YYYY")
                                
                                lista_pag = ["Pix", "Cartão de Crédito", "Cartão de Débito", "Dinheiro"]
                                idx_pag = lista_pag.index(v_pag) if v_pag in lista_pag else 0
                                novo_pag = c2.selectbox("Pagamento", lista_pag, index=idx_pag)
                                
                                lista_prazo = ["À vista", "30 dias", "60 dias", "3x sem juros", "A Combinar"]
                                idx_prazo = lista_prazo.index(v_prazo) if v_prazo in lista_prazo else 0
                                novo_prazo = c3.selectbox("Prazo", lista_prazo, index=idx_prazo)
                                
                                st.caption(f"Quantidade vendida nesta linha: {v_qtd}")
                                
                                c4, c5, c6 = st.columns(3)
                                novo_tabela = c4.number_input("Preço Tabela (R$)", min_value=0.0, value=float(v_tabela), step=1.0, format="%.2f")
                                novo_desc = c5.number_input("Desconto Unit. (R$)", min_value=0.0, value=float(v_desc), step=1.0, format="%.2f")
                                nova_entrada = c6.number_input("Entrada Total (R$)", min_value=0.0, value=float(v_ent), step=10.0, format="%.2f")
                                
                                if st.form_submit_button("💾 Salvar Alterações"):
                                    novo_total = (novo_tabela - novo_desc) * v_qtd
                                    novo_restante = novo_total - nova_entrada
                                    
                                    cursor.execute("UPDATE vendas SET data_venda=%s, forma_pagamento=%s, prazo=%s, valor_unitario=%s, desconto=%s, valor_total=%s, valor_entrada=%s, valor_restante=%s WHERE id=%s AND empresa_id=%s", 
                                                 (nova_data.strftime("%d/%m/%Y"), novo_pag, novo_prazo, novo_tabela, novo_desc, novo_total, nova_entrada, novo_restante, venda_id_edit, emp_id))
                                    conn.commit()
                                    conn.close()
                                    st.success("Item atualizado com sucesso!")
                                    st.rerun()
                        else:
                            conn.close()

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
                                conn.commit()
                                conn.close()
                                st.success("Item cancelado, estoque atualizado e pendências removidas!")
                            else:
                                conn.close()
                                st.error("Erro ao encontrar os dados da venda.")
                            st.rerun()
            
            st.markdown("---")

            # --- RECIBO VIA WHATSAPP NO HISTÓRICO ---
            st.subheader("📲 Enviar Recibo via WhatsApp")
            opcoes_recibo = df_todas_vendas.apply(lambda x: f"Venda {x['Nº Venda']} (Item {x['ID Item']}) | {x['Cliente']} - {x['Produto']}", axis=1).tolist()
            venda_recibo_sel = st.selectbox("Selecione a venda para gerar o recibo", options=opcoes_recibo, key="sel_recibo")

            if venda_recibo_sel:
                venda_id_recibo = int(venda_recibo_sel.split("Item ")[1].split(")")[0])
                
                conn = conectar_banco()
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT c.telefone, c.nome, v.data_venda, p.nome, v.quantidade, v.valor_total, v.valor_entrada, v.valor_restante, v.forma_pagamento
                    FROM vendas v JOIN clientes c ON v.cliente_id = c.id JOIN produtos p ON v.produto_id = p.id
                    WHERE v.id = %s AND v.empresa_id = %s
                """, (venda_id_recibo, emp_id))
                dados_recibo = cursor.fetchone()
                conn.close()

                if dados_recibo:
                    tel, nome_cli, data_v, nome_prod, qtd, v_total, v_ent, v_rest, forma_pag = dados_recibo

                    msg = f"Olá, {nome_cli}! 🌸\n\nAqui está o resumo da sua compra do dia *{data_v}*:\n\n"
                    msg += f"🛍️ *Produto:* {qtd}x {nome_prod}\n💰 *Valor Total:* R$ {v_total:.2f}\n"
                    if v_ent > 0:
                        msg += f"💸 *Entrada Paga:* R$ {v_ent:.2f}\n⏳ *Restante:* R$ {v_rest:.2f}\n"
                    msg += f"💳 *Forma de Pagto:* {forma_pag}\n\nMuito obrigada pela preferência! ✨"

                    st.text_area("Pré-visualização da Mensagem:", value=msg, height=200, disabled=True)

                    if tel:
                        tel_limpo = ''.join(filter(str.isdigit, str(tel)))
                        if len(tel_limpo) >= 10:
                            if not tel_limpo.startswith('55'):
                                tel_limpo = '55' + tel_limpo 
                            import urllib.parse
                            link_wpp = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                            st.link_button("🟢 Abrir no WhatsApp", link_wpp, type="primary")
                        else:
                            st.warning("⚠️ O telefone do cliente parece incompleto.")
                    else:
                        st.warning("⚠️ Este cliente não possui telefone cadastrado.")
                        
            st.markdown("---")
            
            # --- FILTRO POR DATA E TABELA ---
            df_todas_vendas['Data_Filtro'] = pd.to_datetime(df_todas_vendas['Data'], dayfirst=True, errors='coerce').dt.date
            data_min = df_todas_vendas['Data_Filtro'].min() if not pd.isna(df_todas_vendas['Data_Filtro'].min()) else date.today()
            data_max = df_todas_vendas['Data_Filtro'].max() if not pd.isna(df_todas_vendas['Data_Filtro'].max()) else date.today()
            
            st.subheader("🔍 Filtrar por Período")
            col_data1, col_data2 = st.columns(2)
            data_inicio = col_data1.date_input("Data Inicial", value=data_min, format="DD/MM/YYYY")
            data_fim = col_data2.date_input("Data Final", value=data_max, format="DD/MM/YYYY")
            
            mask = (df_todas_vendas['Data_Filtro'] >= data_inicio) & (df_todas_vendas['Data_Filtro'] <= data_fim)
            df_filtrado = df_todas_vendas.loc[mask].drop(columns=['Data_Filtro'])
            
            if not df_filtrado.empty:
                colunas_exibicao = ['Nº Venda', 'Cliente', 'Produto', 'Qtd', 'Preço Tabela', 'Desconto Unit', 'Total (R$)', 'Entrada (R$)', 'Restante (R$)', 'Data', 'Pagamento', 'Prazo']
                st.dataframe(df_filtrado[colunas_exibicao], use_container_width=True, hide_index=True)
                
                st.markdown("### 📊 Resumo do Período")
                col_res1, col_res2, col_res3, col_res4 = st.columns(4)
                col_res1.metric("💰 Faturamento Total", f"R$ {df_filtrado['Total (R$)'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                col_res2.metric("⏳ A Receber", f"R$ {df_filtrado['Restante (R$)'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                col_res3.metric("🛒 Total de Vendas", f"{df_filtrado['Nº Venda'].nunique()}")
                col_res4.metric("🧴 Produtos Vendidos", f"{df_filtrado['Qtd'].sum()}")
            else:
                st.warning("Nenhuma venda encontrada para este período.")
                
        else:
            st.info("Nenhuma venda registrada no sistema até o momento.")

    # ABA: CONTROLE FINANCEIRO (CONTAS A RECEBER)
    with aba_financeiro:
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
