import streamlit as st
import psycopg2
import pandas as pd
from datetime import datetime, date

# ==========================================
# CONFIGURAÇÃO DE MEMÓRIA E BANCO DE DADOS (NUVEM)
# ==========================================
if 'carrinho' not in st.session_state:
    st.session_state['carrinho'] = []

# COLE A SUA SENHA NO LUGAR DE "SUA_SENHA_AQUI" (Sem os colchetes)
DATABASE_URL = st.secrets["DATABASE_URL"]

def conectar_banco():
    return psycopg2.connect(DATABASE_URL)

# Função auxiliar para carregar dados do Postgres direto para o Pandas
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

def inicializar_banco():
    conn = conectar_banco()
    cursor = conn.cursor()
    
    # Criando as tabelas no formato PostgreSQL
    cursor.execute('''CREATE TABLE IF NOT EXISTS categorias (id SERIAL PRIMARY KEY, nome TEXT UNIQUE)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS produtos (id SERIAL PRIMARY KEY, nome TEXT, quantidade INTEGER, valor REAL, marca TEXT, categoria TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS clientes (id SERIAL PRIMARY KEY, nome TEXT, data_nascimento TEXT, telefone TEXT)''')
    
    # Tabela de vendas já completa
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS vendas (
            id SERIAL PRIMARY KEY, 
            codigo_venda INTEGER DEFAULT 0, 
            cliente_id INTEGER, 
            produto_id INTEGER, 
            quantidade INTEGER, 
            data_venda TEXT, 
            valor_total REAL, 
            valor_entrada REAL DEFAULT 0, 
            valor_restante REAL DEFAULT 0, 
            valor_unitario REAL DEFAULT 0, 
            desconto REAL DEFAULT 0, 
            forma_pagamento TEXT, 
            prazo TEXT
        )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM categorias")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO categorias (nome) VALUES ('Geral')")
        
    conn.commit()
    conn.close()

inicializar_banco()

# ==========================================
# INTERFACE WEB - STREAMLIT
# ==========================================
st.set_page_config(page_title="Sistema de Cosméticos", layout="wide")
st.title("📦 Sistema de Gestão - Nuvem")

# Carregando dados
df_produtos = carregar_dados("SELECT * FROM produtos ORDER BY nome")
df_clientes = carregar_dados("SELECT * FROM clientes ORDER BY nome")
df_categorias = carregar_dados("SELECT * FROM categorias ORDER BY nome")

lista_categorias = df_categorias['nome'].tolist() if not df_categorias.empty else ["Geral"]

aba_estoque, aba_clientes, aba_vendas, aba_historico, aba_categorias = st.tabs([
    "📦 Estoque de Produtos", 
    "👥 Clientes", 
    "🛒 Registrar Venda (PDV)", 
    "📜 Histórico Geral",
    "🏷️ Categorias"
])

# ==========================================
# ABA 5: CATEGORIAS
# ==========================================
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
                        conn.cursor().execute("INSERT INTO categorias (nome) VALUES (%s)", (nova_cat_nome.strip(),))
                        conn.commit()
                        conn.close()
                        st.success(f"Categoria '{nova_cat_nome}' adicionada!")
                        st.rerun()
                    except psycopg2.IntegrityError:
                        st.error("Esta categoria já existe!")
    
    with col_del_cat:
        with st.expander("❌ Excluir Categoria", expanded=True):
            with st.form("form_del_categoria"):
                cat_para_excluir = st.selectbox("Selecione para excluir", options=lista_categorias)
                st.warning("Nota: Produtos que já usam essa categoria manterão o nome nela.")
                if st.form_submit_button("Excluir Categoria", type="primary"):
                    conn = conectar_banco()
                    conn.cursor().execute("DELETE FROM categorias WHERE nome=%s", (cat_para_excluir,))
                    conn.commit()
                    conn.close()
                    st.success("Categoria excluída!")
                    st.rerun()
                    
    st.markdown("---")
    st.subheader("Categorias Cadastradas")
    if not df_categorias.empty:
        st.dataframe(df_categorias, use_container_width=True, hide_index=True)


# ==========================================
# ABA 1: ESTOQUE DE PRODUTOS
# ==========================================
with aba_estoque:
    st.header("Gerenciamento de Estoque")
    sub_add_prod, sub_edit_prod, sub_del_prod = st.tabs(["➕ Cadastrar", "✏️ Editar", "❌ Excluir"])
    
    with sub_add_prod:
        with st.form("form_produto", clear_on_submit=True):
            st.subheader("Novo Produto")
            nome = st.text_input("Nome do Produto")
            c1, c2 = st.columns(2)
            qtd = c1.number_input("Quantidade Inicial", min_value=1, step=1)
            valor = c2.number_input("Valor Unitário (R$)", min_value=0.01, step=0.10, format="%.2f")
            c3, c4 = st.columns(2)
            
            marca = c3.text_input("Marca", value="Mary Kay")
            categoria = c4.selectbox("Categoria", options=lista_categorias)
            
            if st.form_submit_button("Cadastrar Produto") and nome:
                conn = conectar_banco()
                conn.cursor().execute("INSERT INTO produtos (nome, quantidade, valor, marca, categoria) VALUES (%s, %s, %s, %s, %s)", (nome, qtd, valor, marca, categoria))
                conn.commit()
                conn.close()
                st.success(f"Produto '{nome}' cadastrado com sucesso!")
                st.rerun()

    with sub_edit_prod:
        st.subheader("Editar Produto Existente")
        if not df_produtos.empty:
            produtos_dict = dict(zip(df_produtos['nome'], df_produtos['id']))
            prod_selecionado = st.selectbox("Selecione o Produto", options=list(produtos_dict.keys()), key="sel_edit_prod")
            prod_id = produtos_dict[prod_selecionado]
            prod_atual = df_produtos[df_produtos['id'] == prod_id].iloc[0]
            
            try:
                index_cat_atual = lista_categorias.index(prod_atual['categoria'])
            except ValueError:
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
                    conn.cursor().execute("UPDATE produtos SET nome=%s, quantidade=%s, valor=%s, marca=%s, categoria=%s WHERE id=%s", (novo_nome, nova_qtd, novo_valor, nova_marca, nova_categoria, prod_id))
                    conn.commit()
                    conn.close()
                    st.success("Produto atualizado!")
                    st.rerun()
        else:
            st.info("Estoque vazio.")

    with sub_del_prod:
        st.subheader("Excluir Produto")
        if not df_produtos.empty:
            produtos_dict = dict(zip(df_produtos['nome'], df_produtos['id']))
            prod_del_selecionado = st.selectbox("Selecione para excluir", options=list(produtos_dict.keys()), key="sel_del_prod")
            with st.form("form_del_produto"):
                st.warning(f"Excluir '{prod_del_selecionado}' permanentemente?")
                if st.form_submit_button("Confirmar Exclusão", type="primary"):
                    conn = conectar_banco()
                    conn.cursor().execute("DELETE FROM produtos WHERE id=%s", (produtos_dict[prod_del_selecionado],))
                    conn.commit()
                    conn.close()
                    st.success("Produto excluído!")
                    st.rerun()
        else:
            st.info("Estoque vazio.")

    st.markdown("---")
    st.subheader("Tabela de Estoque Atual")
    if not df_produtos.empty:
        st.dataframe(df_produtos, use_container_width=True, hide_index=True)
        
        total_itens = int(df_produtos['quantidade'].sum())
        valor_total_estoque = float((df_produtos['quantidade'] * df_produtos['valor']).sum())
        
        st.markdown("---")
        col_m1, col_m2 = st.columns(2)
        col_m1.metric("📦 Quantidade Total (Unidades)", f"{total_itens}")
        col_m2.metric("💰 Valor Total Investido no Estoque", f"R$ {valor_total_estoque:.2f}")
        
    else:
        st.info("Nenhum produto cadastrado no estoque.")


# ==========================================
# ABA 2: CLIENTES
# ==========================================
with aba_clientes:
    st.header("Gerenciamento de Clientes")
    
    if not df_clientes.empty:
        hoje_dia_mes = date.today().strftime("%d/%m")
        df_aniversariantes = df_clientes[df_clientes['data_nascimento'].str.startswith(hoje_dia_mes, na=False)]
        
        if not df_aniversariantes.empty:
            st.success(f"🎉 Temos {len(df_aniversariantes)} cliente(s) fazendo aniversário hoje ({hoje_dia_mes})!")
            st.dataframe(df_aniversariantes[['nome', 'telefone', 'data_nascimento']], use_container_width=True, hide_index=True)
        else:
            with st.expander("🎈 Aniversariantes do Dia", expanded=False):
                st.write(f"Nenhum cliente cadastrado faz aniversário hoje ({hoje_dia_mes}).")
                
    st.markdown("---")
    
    sub_add_cli, sub_edit_cli, sub_del_cli, sub_hist_cli = st.tabs(["➕ Cadastrar", "✏️ Editar", "❌ Excluir", "🛍️ Histórico de Compras"])
    
    with sub_add_cli:
        with st.form("form_cliente", clear_on_submit=True):
            st.subheader("Novo Cliente")
            col1, col2, col3 = st.columns(3)
            nome_cli = col1.text_input("Nome do Cliente")
            nasc_cli = col2.text_input("Dia de Aniversário (DD/MM)", placeholder="Ex: 25/12", max_chars=5)
            tel_cli = col3.text_input("Telefone")
            
            if st.form_submit_button("Cadastrar Cliente") and nome_cli:
                conn = conectar_banco()
                conn.cursor().execute("INSERT INTO clientes (nome, data_nascimento, telefone) VALUES (%s, %s, %s)", (nome_cli, nasc_cli, tel_cli))
                conn.commit()
                conn.close()
                st.success(f"Cliente '{nome_cli}' cadastrado com sucesso!")
                st.rerun()

    with sub_edit_cli:
        st.subheader("Editar Cliente")
        if not df_clientes.empty:
            clientes_dict = dict(zip(df_clientes['nome'], df_clientes['id']))
            cli_selecionado = st.selectbox("Selecione o Cliente", options=list(clientes_dict.keys()), key="sel_edit_cli")
            cli_id = clientes_dict[cli_selecionado]
            cli_atual = df_clientes[df_clientes['id'] == cli_id].iloc[0]
            
            nasc_atual_texto = cli_atual['data_nascimento'][:5] if isinstance(cli_atual['data_nascimento'], str) else ""

            with st.form("form_edit_cliente"):
                col1, col2, col3 = st.columns(3)
                novo_nome_cli = col1.text_input("Nome", value=cli_atual['nome'])
                novo_nasc_cli = col2.text_input("Dia de Aniversário (DD/MM)", value=nasc_atual_texto, max_chars=5)
                novo_tel_cli = col3.text_input("Telefone", value=cli_atual['telefone'])
                
                if st.form_submit_button("Salvar Alterações"):
                    conn = conectar_banco()
                    conn.cursor().execute("UPDATE clientes SET nome=%s, data_nascimento=%s, telefone=%s WHERE id=%s", (novo_nome_cli, novo_nasc_cli, novo_tel_cli, cli_id))
                    conn.commit()
                    conn.close()
                    st.success("Dados atualizados!")
                    st.rerun()
        else:
            st.info("Nenhum cliente cadastrado.")

    with sub_del_cli:
        st.subheader("Excluir Cliente")
        if not df_clientes.empty:
            clientes_dict = dict(zip(df_clientes['nome'], df_clientes['id']))
            cli_del_selecionado = st.selectbox("Selecione para excluir", options=list(clientes_dict.keys()), key="sel_del_cli")
            with st.form("form_del_cliente"):
                st.warning(f"Excluir o cliente '{cli_del_selecionado}'?")
                if st.form_submit_button("Confirmar Exclusão", type="primary"):
                    conn = conectar_banco()
                    conn.cursor().execute("DELETE FROM clientes WHERE id=%s", (clientes_dict[cli_del_selecionado],))
                    conn.commit()
                    conn.close()
                    st.success("Cliente excluído!")
                    st.rerun()

    with sub_hist_cli:
        st.subheader("Histórico de Compras por Cliente")
        if not df_clientes.empty:
            clientes_dict_hist = dict(zip(df_clientes['nome'], df_clientes['id']))
            cli_hist_selecionado = st.selectbox("Selecione o Cliente", options=list(clientes_dict_hist.keys()), key="sel_hist_cli_view")
            cli_id_hist = clientes_dict_hist[cli_hist_selecionado]
            
            query_hist_cli = """
                SELECT v.codigo_venda AS "Nº Venda", COALESCE(p.nome, 'Produto Excluído') AS "Produto", v.quantidade AS "Qtd", 
                       v.valor_total AS "Total (R$)", v.valor_restante AS "Restante (R$)",
                       v.data_venda AS "Data", v.forma_pagamento AS "Pagamento" 
                FROM vendas v 
                LEFT JOIN produtos p ON v.produto_id = p.id 
                WHERE v.cliente_id = %s
                ORDER BY v.codigo_venda DESC, v.id DESC
            """
            df_hist_cli = carregar_dados(query_hist_cli, (cli_id_hist,))
            
            if not df_hist_cli.empty:
                st.dataframe(df_hist_cli, use_container_width=True, hide_index=True)
                total_comprado = df_hist_cli['Total (R$)'].sum()
                st.markdown(f"**Total acumulado em compras: R$ {total_comprado:.2f}**")
            else:
                st.info("Este cliente ainda não realizou nenhuma compra.")
        else:
            st.info("Nenhum cliente cadastrado.")

    st.markdown("---")
    st.subheader("Lista de Clientes")
    if not df_clientes.empty:
        st.dataframe(df_clientes, use_container_width=True, hide_index=True)


# ==========================================
# ABA 3: REGISTRAR VENDA (PDV)
# ==========================================
with aba_vendas:
    st.header("🛒 Registrar Venda (PDV)")
    
    # --- NOVO: EXIBIR RECIBO DO WHATSAPP SE A VENDA FOI FINALIZADA ---
    if 'zap_link' in st.session_state:
        st.success(f"🎉 Venda Nº {st.session_state['zap_codigo']} finalizada com sucesso! Total: R$ {st.session_state['zap_total']:.2f}")
        
        with st.container(border=True):
            st.subheader("📲 Enviar Recibo via WhatsApp")
            st.text_area("Pré-visualização da Mensagem:", value=st.session_state['zap_msg'], height=220, disabled=True, key="msg_pdv_imediata")
            
            col_zap1, col_zap2 = st.columns([2, 1])
            col_zap1.link_button("🟢 Abrir WhatsApp e Enviar", st.session_state['zap_link'], type="primary", use_container_width=True)
            
            if col_zap2.button(" Nova Venda", use_container_width=True):
                del st.session_state['zap_link']
                del st.session_state['zap_msg']
                del st.session_state['zap_codigo']
                del st.session_state['zap_total']
                st.rerun()
        st.markdown("---")
    # --- FIM DO BLOCO DE EXIBIÇÃO ---

    if df_produtos.empty or df_clientes.empty:
        st.warning("É necessário ter clientes e produtos cadastrados.")
    else:
        st.subheader("1. Dados Gerais")
        col_cli, col_data = st.columns(2)
        clientes_dict = dict(zip(df_clientes['nome'], df_clientes['id']))
        cliente_selecionado = col_cli.selectbox("Cliente", options=list(clientes_dict.keys()))
        data_venda_input = col_data.date_input("Data da Venda", format="DD/MM/YYYY", value=date.today())
        
        col_pag, col_prazo = st.columns(2)
        forma_pag = col_pag.selectbox("Pagamento", ["Pix", "Cartão de Crédito", "Cartão de Débito", "Dinheiro"])
        prazo = col_prazo.selectbox("Prazo", ["À vista", "30 dias", "60 dias", "3x sem juros", "A Combinar"])
        
        st.markdown("---")
        st.subheader("2. Adicionar Produtos")
        
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
                qtd_total_desejada = qtd_venda + qtd_no_carrinho
                
                valor_com_desconto = preco_tabela - desconto_unit
                
                if estoque_atual < qtd_total_desejada:
                    st.error(f"Estoque insuficiente! Você tem {estoque_atual} no estoque e {qtd_no_carrinho} no carrinho.")
                elif valor_com_desconto < 0:
                    st.error("O desconto não pode ser maior que o valor do produto!")
                else:
                    st.session_state['carrinho'].append({
                        'produto_id': prod_id,
                        'Produto': produto_selecionado,
                        'quantidade': qtd_venda,
                        'Valor Original (R$)': preco_tabela,
                        'Desconto (R$)': desconto_unit,
                        'Subtotal (R$)': valor_com_desconto * qtd_venda
                    })
                    st.success(f"{qtd_venda}x '{produto_selecionado}' adicionado(s) ao carrinho!")
                    st.rerun()

        st.markdown("---")
        st.subheader("3. Resumo da Venda e Pagamento")
        
        if st.session_state['carrinho']:
            df_carrinho = pd.DataFrame(st.session_state['carrinho'])
            st.dataframe(df_carrinho[['Produto', 'quantidade', 'Valor Original (R$)', 'Desconto (R$)', 'Subtotal (R$)']], use_container_width=True, hide_index=True)
            
            total_venda = float(df_carrinho['Subtotal (R$)'].sum())
            
            with st.container(border=True):
                st.markdown(f"## 💰 Total da Venda: R$ {total_venda:.2f}")
                
                col_ent1, col_ent2 = st.columns(2)
                valor_entrada = col_ent1.number_input("💸 Valor da Entrada (R$) (Se houver)", min_value=0.0, max_value=total_venda, step=10.0, format="%.2f")
                valor_restante = total_venda - valor_entrada
                
                if valor_entrada > 0:
                    col_ent2.success(f"⏳ Ficará um restante a receber de: **R$ {valor_restante:.2f}**")
                else:
                    col_ent2.info("Nenhuma entrada registrada. O valor ficará pendente ou será pago integralmente no prazo.")
                
                st.markdown("<br>", unsafe_allow_html=True)
                col_finalizar, col_limpar = st.columns([2, 1])
                
                if col_finalizar.button("✅ Finalizar Venda", type="primary", use_container_width=True):
                    cli_id = clientes_dict[cliente_selecionado]
                    data_venda_formatada = data_venda_input.strftime("%d/%m/%Y")
                    
                    conn = conectar_banco()
                    cursor = conn.cursor()
                    
                    cursor.execute("SELECT MAX(codigo_venda) FROM vendas")
                    resultado_max = cursor.fetchone()[0]
                    novo_codigo_venda = (resultado_max if resultado_max is not None else 0) + 1
                    
                    for item in st.session_state['carrinho']:
                        proporcao = item['Subtotal (R$)'] / total_venda if total_venda > 0 else 0
                        item_entrada = valor_entrada * proporcao
                        item_restante = item['Subtotal (R$)'] - item_entrada
                        
                        cursor.execute("""
                            INSERT INTO vendas (codigo_venda, cliente_id, produto_id, quantidade, data_venda, valor_total, valor_entrada, valor_restante, valor_unitario, desconto, forma_pagamento, prazo) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (novo_codigo_venda, cli_id, item['produto_id'], item['quantidade'], data_venda_formatada, item['Subtotal (R$)'], item_entrada, item_restante, item['Valor Original (R$)'], item['Desconto (R$)'], forma_pag, prazo))
                        
                        cursor.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE id = %s", (item['quantidade'], item['produto_id']))
                    
                    # --- NOVO: BUSCAR TELEFONE E MONTAR TEXTO COMPLETO DO CARRINHO ANTES DE LIMPAR ---
                    cursor.execute("SELECT telefone FROM clientes WHERE id = %s", (cli_id,))
                    dados_cli = cursor.fetchone()
                    tel_cliente = dados_cli[0] if dados_cli else None
                    
                    conn.commit()
                    conn.close()
                    
                    # Montar o detalhamento de itens para o texto do WhatsApp
                    msg = f"Olá, {cliente_selecionado}! 🌸\n\n"
                    msg += f"Aqui está o recibo da sua compra realizada em *{data_venda_formatada}*:\n"
                    msg += f"🧾 *Venda Nº {novo_codigo_venda}*\n\n"
                    msg += "🛍️ *Produtos adicionados:*\n"
                    
                    for item in st.session_state['carrinho']:
                        msg += f"• {item['quantidade']}x {item['Produto']} — R$ {item['Subtotal (R$)']:.2f}\n"
                    
                    msg += f"\n💰 *Valor Total:* R$ {total_venda:.2f}\n"
                    if valor_entrada > 0:
                        msg += f"💸 *Entrada Paga:* R$ {valor_entrada:.2f}\n"
                        msg += f"⏳ *Restante a receber:* R$ {valor_restante:.2f}\n"
                    msg += f"💳 *Forma de Pagto:* {forma_pag} ({prazo})\n\n"
                    msg += "Muito obrigada pela preferência e confiança! ✨"
                    
                    # Tratar o link com o número de celular
                    import urllib.parse
                    msg_url = urllib.parse.quote(msg)
                    if tel_cliente:
                        tel_limpo = ''.join(filter(str.isdigit, str(tel_cliente)))
                        if len(tel_limpo) >= 10 and not tel_limpo.startswith('55'):
                            tel_limpo = '55' + tel_limpo
                        link_wpp = f"https://wa.me/{tel_limpo}?text={msg_url}"
                    else:
                        link_wpp = f"https://wa.me/?text={msg_url}"
                    
                    # Guardar na memória para exibir após o rerun
                    st.session_state['zap_link'] = link_wpp
                    st.session_state['zap_msg'] = msg
                    st.session_state['zap_codigo'] = novo_codigo_venda
                    st.session_state['zap_total'] = total_venda
                    
                    # Reseta o carrinho e recarrega para mostrar o recibo estruturado lá em cima
                    st.session_state['carrinho'] = []
                    st.rerun()
                    
                if col_limpar.button("🗑️ Esvaziar Carrinho", use_container_width=True):
                    st.session_state['carrinho'] = []
                    st.rerun()
        else:
            st.info("O carrinho está vazio. Adicione produtos acima para continuar e abrir as opções de pagamento.")


# ==========================================
# ABA 4: HISTÓRICO GERAL DE VENDAS E EDIÇÃO
# ==========================================
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
        ORDER BY v.codigo_venda DESC, v.id DESC
    """
    df_todas_vendas = carregar_dados(query_todas_vendas)
    
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
                    cursor.execute("SELECT data_venda, forma_pagamento, prazo, valor_unitario, desconto, valor_entrada, quantidade FROM vendas WHERE id = %s", (venda_id_edit,))
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
                                
                                cursor.execute("UPDATE vendas SET data_venda=%s, forma_pagamento=%s, prazo=%s, valor_unitario=%s, desconto=%s, valor_total=%s, valor_entrada=%s, valor_restante=%s WHERE id=%s", 
                                             (nova_data.strftime("%d/%m/%Y"), novo_pag, novo_prazo, novo_tabela, novo_desc, novo_total, nova_entrada, novo_restante, venda_id_edit))
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
                        cursor.execute("SELECT produto_id, quantidade FROM vendas WHERE id = %s", (venda_id_del,))
                        venda_info = cursor.fetchone()
                        
                        if venda_info:
                            p_id, p_qtd = venda_info
                            cursor.execute("UPDATE produtos SET quantidade = quantidade + %s WHERE id = %s", (p_qtd, p_id))
                            cursor.execute("DELETE FROM vendas WHERE id = %s", (venda_id_del,))
                            conn.commit()
                            conn.close()
                            st.success("Item cancelado e devolvido ao estoque.")
                        else:
                            conn.close()
                            st.error("Erro ao encontrar os dados da venda.")
                        st.rerun()
        
        st.markdown("---")

# --- NOVO BLOCO: RECIBO VIA WHATSAPP ---
        st.subheader("📲 Enviar Recibo via WhatsApp")
        opcoes_recibo = df_todas_vendas.apply(lambda x: f"Venda {x['Nº Venda']} (Item {x['ID Item']}) | {x['Cliente']} - {x['Produto']}", axis=1).tolist()
        venda_recibo_sel = st.selectbox("Selecione a venda para gerar o recibo", options=opcoes_recibo, key="sel_recibo")

        if venda_recibo_sel:
            venda_id_recibo = int(venda_recibo_sel.split("Item ")[1].split(")")[0])
            
            # Buscar detalhes da venda e telefone do cliente
            conn = conectar_banco()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.telefone, c.nome, v.data_venda, p.nome, v.quantidade, v.valor_total, v.valor_entrada, v.valor_restante, v.forma_pagamento
                FROM vendas v
                JOIN clientes c ON v.cliente_id = c.id
                JOIN produtos p ON v.produto_id = p.id
                WHERE v.id = %s
            """, (venda_id_recibo,))
            dados_recibo = cursor.fetchone()
            conn.close()

            if dados_recibo:
                tel, nome_cli, data_v, nome_prod, qtd, v_total, v_ent, v_rest, forma_pag = dados_recibo

                # Montar a mensagem com emojis
                msg = f"Olá, {nome_cli}! 🌸\n\n"
                msg += f"Aqui está o resumo da sua compra do dia *{data_v}*:\n\n"
                msg += f"🛍️ *Produto:* {qtd}x {nome_prod}\n"
                msg += f"💰 *Valor Total:* R$ {v_total:.2f}\n"
                if v_ent > 0:
                    msg += f"💸 *Entrada Paga:* R$ {v_ent:.2f}\n"
                    msg += f"⏳ *Restante:* R$ {v_rest:.2f}\n"
                msg += f"💳 *Forma de Pagto:* {forma_pag}\n\n"
                msg += "Muito obrigada pela preferência! ✨"

                # Mostrar a mensagem na tela para você conferir antes de enviar
                st.text_area("Pré-visualização da Mensagem:", value=msg, height=250, disabled=True)

                # Tratamento do número e criação do link
                if tel:
                    # Limpa o telefone deixando só os números
                    tel_limpo = ''.join(filter(str.isdigit, str(tel)))
                    
                    if len(tel_limpo) >= 10: # Verifica se tem pelo menos DDD + Número
                        if not tel_limpo.startswith('55'):
                            tel_limpo = '55' + tel_limpo # Adiciona o código do Brasil se não tiver
                        
                        import urllib.parse
                        msg_url = urllib.parse.quote(msg)
                        link_wpp = f"https://wa.me/{tel_limpo}?text={msg_url}"
                        
                        st.link_button("🟢 Abrir no WhatsApp", link_wpp, type="primary")
                    else:
                        st.warning("⚠️ O telefone do cliente parece incompleto. Corrija na aba de Clientes (precisa ter DDD).")
                else:
                    st.warning("⚠️ Este cliente não possui telefone cadastrado.")
                    
        st.markdown("---")
        # --- FIM DO BLOCO WPP ---
       
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
            
            faturamento_total = df_filtrado['Total (R$)'].sum()
            total_pendente = df_filtrado['Restante (R$)'].sum()
            
            qtd_pedidos = df_filtrado['Nº Venda'].nunique()
            qtd_produtos = df_filtrado['Qtd'].sum()
            
            st.markdown("### 📊 Resumo do Período")
            col_res1, col_res2, col_res3, col_res4 = st.columns(4)
            col_res1.metric("💰 Faturamento Total", f"R$ {faturamento_total:.2f}")
            col_res2.metric("⏳ A Receber", f"R$ {total_pendente:.2f}")
            col_res3.metric("🛒 Total de Vendas (Pedidos)", f"{qtd_pedidos}")
            col_res4.metric("🧴 Produtos Vendidos", f"{qtd_produtos}")
            
        else:
            st.warning("Nenhuma venda encontrada para este período.")
            
    else:
        st.info("Nenhuma venda registrada no sistema até o momento.")
