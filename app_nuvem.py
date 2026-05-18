import streamlit as st
import psycopg2
import pandas as pd
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
        
    aba_cad_empresa, aba_cad_usuario = st.tabs(["🏢 Empresas Cadastradas", "👤 Logins de Funcionários"])
    
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

# --- TELA OPERACIONAL DO ERP (FUNCIONÁRIOS / EMPRESAS) ---
else:
    emp_id = st.session_state['empresa_id']
    
    st.sidebar.markdown(f"👤 **Operador:** {st.session_state['usuario_nome']}")
    if st.sidebar.button("🚪 Sair do Sistema"):
        st.session_state.clear()
        st.rerun()
        
    st.title("📦 Sistema de Gestão Comercial")
    
    # Carregando dados filtrados exclusivamente pela empresa logada
    df_produtos = carregar_dados("SELECT * FROM produtos WHERE empresa_id = %s ORDER BY nome", (emp_id,))
    df_clientes = carregar_dados("SELECT * FROM clientes WHERE empresa_id = %s ORDER BY nome", (emp_id,))
    df_categorias = carregar_dados("SELECT * FROM categorias WHERE empresa_id = %s ORDER BY nome", (emp_id,))

    lista_categorias = df_categorias['nome'].tolist() if not df_categorias.empty else ["Geral"]

    aba_estoque, aba_clientes, aba_vendas, aba_historico, aba_categorias, aba_financeiro = st.tabs([
        "📦 Estoque de Produtos", 
        "👥 Clientes", 
        "🛒 Registrar Venda (PDV)", 
        "📜 Histórico Geral",
        "🏷️ Categorias",
        "💰 Financeiro"
    ])

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
            st.dataframe(df_produtos.drop(columns=['empresa_id']), use_container_width=True, hide_index=True)

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
        st.header("📜 Histórico Geral")
        df_todas_vendas = carregar_dados("""
            SELECT v.id AS "ID Item", v.codigo_venda AS "Nº Venda", c.nome AS "Cliente", p.nome AS "Produto", v.quantidade AS "Qtd", v.valor_total AS "Total (R$)", v.data_venda AS "Data"
            FROM vendas v JOIN clientes c ON v.cliente_id = c.id JOIN produtos p ON v.produto_id = p.id WHERE v.empresa_id = %s ORDER BY v.codigo_venda DESC
        """, (emp_id,))
        
        if not df_todas_vendas.empty:
            with st.expander("❌ Cancelar / Estornar Item", expanded=False):
                with st.form("form_del_venda"):
                    opcoes_venda_del = df_todas_vendas.apply(lambda x: f"Venda {x['Nº Venda']} (Item {x['ID Item']}) | {x['Cliente']} - {x['Produto']}", axis=1).tolist()
                    venda_para_apagar = st.selectbox("Selecione o item lançado por engano", options=opcoes_venda_del)
                    
                    if st.form_submit_button("🚨 Confirmar Cancelamento", type="primary"):
                        venda_id_del = int(venda_para_apagar.split("Item ")[1].split(")")[0])
                        conn = conectar_banco()
                        cursor = conn.cursor()
                        cursor.execute("SELECT produto_id, quantidade, codigo_venda FROM vendas WHERE id = %s AND empresa_id = %s", (venda_id_del, emp_id))
                        v_info = cursor.fetchone()
                        
                        if v_info:
                            p_id, p_qtd, cod_venda = v_info
                            cursor.execute("UPDATE produtos SET quantidade = quantidade + %s WHERE id = %s AND empresa_id = %s", (p_qtd, p_id, emp_id))
                            cursor.execute("DELETE FROM vendas WHERE id = %s AND empresa_id = %s", (venda_id_del, emp_id))
                            cursor.execute("DELETE FROM contas_receber WHERE venda_codigo = %s AND empresa_id = %s", (cod_venda, emp_id))
                            conn.commit()
                            st.success("Item e pendências financeiras removidos!")
                        conn.close()
                        st.rerun()
            st.dataframe(df_todas_vendas, use_container_width=True, hide_index=True)

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
            mask_atraso = (df_financeiro['Status'] == 'Pendente') & (df_financeiro['Data_Venc_Obj'] < hoje)
            v_atr = df_financeiro[mask_atraso]['Valor (R$)'].sum()
            
            cm1, cm2 = st.columns(2)
            cm1.metric("✅ Total Recebido", f"R$ {v_rec:.2f}")
            cm2.metric("🚨 Atrasado (Inadimplência)", f"R$ {v_atr:.2f}")
            
            df_p = df_financeiro[df_financeiro['Status'] == 'Pendente']
            if not df_p.empty:
                with st.expander("✅ Registrar Recebimento de Parcela", expanded=True):
                    with st.form("form_baixa"):
                        op_b = df_p.apply(lambda x: f"Venda {x['Nº Venda']} | {x['Cliente']} | Parc {x['Parcela']}/{x['De']} | R$ {x['Valor (R$)']:.2f}", axis=1).tolist()
                        p_sel = st.selectbox("Selecione a parcela paga:", options=op_b)
                        idx_b = df_p['ID Parcela'].tolist()[op_b.index(p_sel)]
                        
                        if st.form_submit_button("💰 Confirmar Baixa", type="primary"):
                            conn = conectar_banco()
                            conn.cursor().execute("UPDATE contas_receber SET status = 'Pago', data_pagamento = %s WHERE id = %s AND empresa_id = %s", (hoje.strftime("%d/%m/%Y"), idx_b, emp_id))
                            conn.commit()
                            conn.close()
                            st.success("Registrado!")
                            st.rerun()
            
            st.dataframe(df_financeiro.drop(columns=['Data_Venc_Obj', 'ID Parcela']), use_container_width=True, hide_index=True)
