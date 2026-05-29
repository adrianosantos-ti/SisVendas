import os
import time

# Força o servidor inteiro a rodar no fuso correto
os.environ['TZ'] = 'America/Fortaleza'
time.tzset()

import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
import xml.etree.ElementTree as ET
from datetime import datetime, date, timedelta
import urllib.parse
import base64

# Código para esconder o "Running indicator" (bonequinho correndo)
st.markdown(
    """
    <style>
    [data-testid="stStatusWidget"] {
        visibility: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True
)

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
st.set_page_config(page_title="Apprimory", layout="wide")

if 'logado' not in st.session_state:
    st.session_state['logado'] = False
    st.session_state['perfil'] = ''
    st.session_state['empresa_id'] = None
    st.session_state['usuario_nome'] = ''

# --- TELA DE LOGIN ---
if not st.session_state['logado']:
    # 1. Função para converter a imagem e poder usar no HTML
    def get_base64_image(caminho_imagem):
        with open(caminho_imagem, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()

    # 2. Converte a sua logo (verifique se o nome do arquivo está certinho)
    img_base64 = get_base64_image("Apprimory_logo_nova.png")

    # 3. Exibe a imagem centralizada e com tamanho controlado (200px)
    st.markdown(
        f"""
        <div style="text-align: center;">
            <img src="data:image/png;base64,{img_base64}" width="200">
        </div>
        """,
        unsafe_allow_html=True
    )
    st.write("") # Dá um pequeno espaço extra
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
    # 1. A PRIMEIRA coisa do Streamlit no código TEM que ser a configuração da página:
    st.set_page_config(
        page_title="Apprimory",
        page_icon="🛍️", # Pode usar 🛒, 🛍️, 👗, etc.
        layout="wide"
     )

    st.sidebar.image("logo.png", width=100)
    # st.sidebar.image("https://cdn-icons-png.flaticon.com/512/1063/1063376.png", width=80)
    st.sidebar.title(f"Módulos")
    modulo = st.sidebar.radio("Navegação Principal:", [
        "📊 Análises", 
        "🗂️ Cadastros", 
        "🔄 Movimentações", 
        "💰 Financeiro",
        "📣 CRM & Pós-Venda"
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
                
                # 1. Filtramos o DataFrame para mostrar cada venda apenas UMA VEZ no selectbox
                df_vendas_unicas = df_todas_vendas.drop_duplicates(subset=['Nº Venda'])
                opcoes_recibo = df_vendas_unicas.apply(lambda x: f"Venda Nº {x['Nº Venda']} | Cliente: {x['Cliente']}", axis=1).tolist()
                
                venda_recibo_sel = st.selectbox("Selecione a venda para gerar o recibo", options=opcoes_recibo, key="sel_recibo")

                if venda_recibo_sel:
                    # Extraímos o código da venda a partir do texto do selectbox
                    venda_id_recibo = int(venda_recibo_sel.split("Nº ")[1].split(" |")[0])
                    
                    conn = conectar_banco()
                    cursor = conn.cursor()
                    
                    # 2. Buscamos TODOS os itens daquele codigo_venda# 1. Adicionamos a coluna das parcelas no SELECT (ex: v.qtd_parcelas)
                    cursor.execute("""
                        SELECT c.telefone, c.nome, v.data_venda, p.nome, v.quantidade, 
                               v.valor_total, v.valor_entrada, v.valor_restante, 
                               v.forma_pagamento, v.valor_unitario, v.qtd_parcelas
                        FROM vendas v 
                        JOIN clientes c ON v.cliente_id = c.id 
                        JOIN produtos p ON v.produto_id = p.id 
                        WHERE v.codigo_venda = %s AND v.empresa_id = %s
                    """, (venda_id_recibo, emp_id))
                    
                    dados_recibo = cursor.fetchall()
                    conn.close()

                    if dados_recibo:
                        tel = dados_recibo[0][0]
                        nome_cli = dados_recibo[0][1]
                        data_v = dados_recibo[0][2]
                        
                        v_ent = dados_recibo[0][6] or 0
                        v_rest = dados_recibo[0][7] or 0
                        forma_pag = dados_recibo[0][8]
                        # 2. Capturamos a quantidade de parcelas no índice 10
                        qtd_parc = dados_recibo[0][10] or 1 
                        
                        lista_produtos_msg = ""
                        total_venda = 0
                        subtotal_recibo = 0.0 
                        
                        for item in dados_recibo:
                            nome_prod = item[3]
                            qtd = item[4]
                            v_total_item = item[5]
                            v_unitario = item[9]
                            
                            subtotal_item = float(v_unitario) * int(qtd)
                            subtotal_recibo += subtotal_item
                            
                            preco_formatado = f"{v_unitario:.2f}".replace('.', ',')
                            lista_produtos_msg += f"▫️ {int(qtd)}x {nome_prod} (R$ {preco_formatado})\n"
                            total_venda += v_total_item

                        total_str = f"{total_venda:.2f}".replace('.', ',')
                        v_ent_str = f"{v_ent:.2f}".replace('.', ',')
                        v_rest_str = f"{v_rest:.2f}".replace('.', ',')

                        msg = f"Olá, {nome_cli}! 🌸\n\n"
                        msg += f"Aqui está o resumo da sua compra do dia *{data_v}*:\n\n"
                        msg += f"🧾 *Venda Nº {venda_id_recibo}*\n\n"
                        msg += f"*Produtos:*\n{lista_produtos_msg}\n"
                        
                        if subtotal_recibo > total_venda:
                            valor_desconto = subtotal_recibo - total_venda
                            subtotal_str = f"{subtotal_recibo:.2f}".replace('.', ',')
                            desconto_str = f"{valor_desconto:.2f}".replace('.', ',')
                            msg += f"🏷️ *Subtotal:* R$ {subtotal_str}\n"
                            msg += f"🎁 *Desconto:* - R$ {desconto_str}\n"
                        
                        msg += f"💰 *Valor Total:* R$ {total_str}\n"
                        
                        # --- 3. DETALHAMENTO DO CREDIÁRIO COM PARCELAS ---
                        if forma_pag == "Crediário":
                            if v_ent > 0: 
                                msg += f"💸 *Entrada Paga:* R$ {v_ent_str}\n"
                                msg += f"⏳ *Restante:* R$ {v_rest_str} (em {qtd_parc}x)\n"
                            elif qtd_parc > 1:
                                valor_parc = total_venda / qtd_parc
                                valor_parc_str = f"{valor_parc:.2f}".replace('.', ',')
                                msg += f"💳 *Crediário:* {qtd_parc}x de R$ {valor_parc_str}\n"
                            else:
                                msg += f"💳 *Forma de Pagto:* Crediário\n"
                        elif qtd_parc > 1:
                            # Serve também para cartão de crédito parcelado
                            valor_parc = total_venda / qtd_parc
                            valor_parc_str = f"{valor_parc:.2f}".replace('.', ',')
                            msg += f"💳 *Parcelamento:* {qtd_parc}x de R$ {valor_parc_str}\n"
                        else:
                            msg += f"💳 *Forma de Pagto:* {forma_pag}\n"
                            
                        msg += "\nMuito obrigada pela preferência! ✨"
                        
                        st.text_area("Pré-visualização da Mensagem:", value=msg, height=250, disabled=True)

                        if tel:
                            tel_limpo = ''.join(filter(str.isdigit, str(tel)))
                            if len(tel_limpo) >= 10:
                                if not tel_limpo.startswith('55'): tel_limpo = '55' + tel_limpo 
                                link_wpp = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                                st.link_button("🟢 Abrir no WhatsApp", link_wpp, type="primary", use_container_width=True)
                            else: 
                                st.warning("⚠️ Telefone incompleto.")
                        else: 
                            st.warning("⚠️ Cliente sem telefone.")                                           
                            
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
            
            from datetime import datetime
            import pytz

            # Força o sistema a usar o fuso horário correto
            fuso_local = pytz.timezone('America/Fortaleza')
            hoje_str = datetime.now(fuso_local).strftime("%d/%m")

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
        tab_venda, tab_compra, tab_historico_compras = st.tabs(["🛒 Frente de Caixa", "📥 Entrada de Mercadorias", "📋 Histórico de Entradas"])        
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
                
                # 2. Seleção de Produto com Visão Dinâmica de Estoque
                df_pro['display_pesquisa'] = df_pro.apply(
                    lambda x: f"{x['nome']} (Estoque: {int(x['quantidade'])})", axis=1
                )
                
                prod_display = st.selectbox("🔍 Pesquise o Produto (Digite o nome):", options=df_pro['display_pesquisa'].tolist())
                
                # Resgate das informações baseadas na escolha do menu de busca
                p_info = df_pro[df_pro['display_pesquisa'] == prod_display].iloc[0]
                estoque_atual = int(p_info['quantidade'])
                preco_tabela = float(p_info['valor'])
                
                # --- PAINEL VISUAL DE ESTOQUE E PREÇO FIXO ---
                if estoque_atual <= 0:
                    st.error(f"🚨 ESTOQUE ZERADO! | 🏷️ Preço de Tabela: **R$ {preco_tabela:.2f}**".replace('.', ','))
                elif estoque_atual == 1:
                    st.warning(f"⚠️ ÚLTIMA UNIDADE! | 🏷️ Preço de Tabela: **R$ {preco_tabela:.2f}**".replace('.', ','))
                elif estoque_atual <= 3:
                    st.warning(f"⚠️ Estoque Baixo: Restam apenas {estoque_atual} unidades. | 🏷️ Preço de Tabela: **R$ {preco_tabela:.2f}**".replace('.', ','))
                else:
                    st.info(f"📦 Estoque atual: {estoque_atual} unidades | 🏷️ Preço de Tabela: **R$ {preco_tabela:.2f}**".replace('.', ','))
                
                # --- FORMULÁRIO DE ADIÇÃO AO CARRINHO COM OPÇÃO DUPLA DE DESCONTO ---
                with st.form("form_add_carrinho", clear_on_submit=True):
                    c1, c2, c3 = st.columns(3)
                    
                    limite_qtd = estoque_atual if estoque_atual > 0 else 1
                    q_pdv = c1.number_input("Quantidade:", min_value=1, max_value=limite_qtd, step=1, value=1)
                    
                    # Campos independentes de desconto (Valor líquido ou Porcentagem)
                    desc_rs = c2.number_input("Desconto (R$):", min_value=0.0, step=1.0, format="%.2f")
                    desc_perc = c3.number_input("Desconto (%):", min_value=0.0, max_value=100.0, step=1.0, format="%.1f")
                    
                    if st.form_submit_button("➕ Adicionar ao Carrinho", disabled=(estoque_atual <= 0)):
                        if estoque_atual >= q_pdv:
                            
                            # Lógica inteligente de prioridade: Porcentagem calcula por cima do preço de tabela
                            if desc_perc > 0:
                                desconto_final = preco_tabela * (desc_perc / 100.0)
                            else:
                                desconto_final = desc_rs
                                
                            st.session_state['carrinho'].append({
                                'id': int(p_info['id']), 
                                'nome': str(p_info['nome']), 
                                'qtd': int(q_pdv), 
                                'unit': float(preco_tabela), 
                                'desc': float(desconto_final), 
                                'total': float((preco_tabela - desconto_final) * q_pdv)
                            })
                            st.rerun()
                        else: 
                            st.error("Estoque insuficiente!")

                # 3. Carrinho e Finalização Operacional
                if st.session_state['carrinho']:
                    df_car = pd.DataFrame(st.session_state['carrinho'])
                    st.table(df_car[['nome', 'qtd', 'unit', 'desc', 'total']])
                    
                    # Forçamos a soma a ser um float primitivo do Python para banir o tipo np.float64
                    total_pdv = float(df_car['total'].sum())
                    st.header(f"Total da Venda: R$ {total_pdv:.2f}".replace('.', ','))
                    
                    st.markdown("---")
                    
                    # --- OPÇÕES DE ENTRADA E RESUMO ---
                    valor_entrada = 0.0

                    if f_pag == "Crediário":
                        valor_entrada = st.number_input("Valor da Entrada (R$)", min_value=0.0, max_value=float(total_pdv), value=0.0, step=10.0)
                    
                    valor_restante = float(total_pdv - valor_entrada)
                    
                    # Painel visual informativo do parcelamento para o operador do caixa
                    if valor_entrada > 0:
                        st.info(f"💵 Entrada: R$ {valor_entrada:.2f} (Paga hoje) | ⏳ Restante: R$ {valor_restante:.2f} lançado em {int(qtd_parcelas)}x de R$ {(valor_restante / qtd_parcelas):.2f}".replace('.', ','))
                    elif qtd_parcelas > 1:
                        st.info(f"💳 Parcelamento: {int(qtd_parcelas)}x de R$ {(total_pdv / qtd_parcelas):.2f} ".replace('.', ','))
                    
                    st.markdown("---")              
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
                            
                            # Gravação dos itens expurgando tipos nativos do Pandas/NumPy
                            for it in st.session_state['carrinho']:
                                cur.execute("""INSERT INTO vendas (codigo_venda, cliente_id, produto_id, quantidade, data_venda, valor_total, empresa_id, valor_unitario, desconto, forma_pagamento, valor_entrada, valor_restante, qtd_parcelas) 
                                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                           (
                                               int(novo_cod), 
                                               int(cli_id_v), 
                                               int(it['id']), 
                                               int(it['qtd']), 
                                               str(data_v), 
                                               float(it['total']), 
                                               int(emp_id), 
                                               float(it['unit']), 
                                               float(it['desc']), 
                                               str(f_pag), 
                                               float(valor_entrada), 
                                               float(valor_restante), 
                                               int(qtd_parcelas)
                                           ))
                                
                                cur.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE id=%s", (int(it['qtd']), int(it['id'])))
                            
                            # --- Inserção no Financeiro com Regra de Entrada ---
                            val_parc_rest = 0.0
                            if f_pag == "Crediário" and valor_entrada > 0:
                                # 1ª Parcela: Valor da Entrada (Lançada como Paga na data de hoje)
                                cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id) 
                                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                                           (int(novo_cod), int(cli_id_v), 1, int(qtd_parcelas), float(valor_entrada), data_venda_input.strftime("%d/%m/%Y"), 'Pago', int(emp_id)))
                                
                                # Processamento do saldo restante nas parcelas seguintes
                                if qtd_parcelas > 1:
                                    valor_restante = total_pdv - valor_entrada
                                    val_parc_rest = float(valor_restante / (qtd_parcelas - 1))
                                    
                                    for i in range(2, int(qtd_parcelas) + 1):
                                        dt_venc = data_1_venc + timedelta(days=30 * (i - 2))
                                        cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id) 
                                                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                                                   (int(novo_cod), int(cli_id_v), int(i), int(qtd_parcelas), float(val_parc_rest), dt_venc.strftime("%d/%m/%Y"), 'Pendente', int(emp_id)))
                            else:
                                # FLUXO PADRÃO: Vendas sem entrada ou outras formas de pagamento
                                val_parc = float(total_pdv / qtd_parcelas)
                                dt_venc = data_1_venc
                                for i in range(1, int(qtd_parcelas) + 1):
                                    status_venda = 'Pendente' if qtd_parcelas > 1 else ('Pago' if f_pag != "Crediário" else 'Pendente')
                                    cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id) 
                                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                                               (int(novo_cod), int(cli_id_v), int(i), int(qtd_parcelas), float(val_parc), dt_venc.strftime("%d/%m/%Y"), status_venda, int(emp_id)))
                                    dt_venc += timedelta(days=30)
                            
                            # --- CAPTURA E MONTAGEM DO LINK DO WHATSAPP ---
                            cur.execute("SELECT telefone FROM clientes WHERE id = %s", (cli_id_v,))
                            resultado_tel = cur.fetchone()
                            tel_cli = resultado_tel[0] if resultado_tel else None
                            
                            lista_produtos_msg = ""
                            subtotal_recibo = 0.0
                            
                            for it in st.session_state['carrinho']:
                                preco_unit = float(it['unit'])
                                subtotal_item = preco_unit * int(it['qtd'])
                                subtotal_recibo += subtotal_item
                                
                                preco_formatado = f"{preco_unit:.2f}".replace('.', ',')
                                lista_produtos_msg += f"▫️ {int(it['qtd'])}x {it['nome']} (R$ {preco_formatado})\n"
                            
                            msg = f"Olá, {cliente_pdv}! 🌸\n\n"
                            msg += f"Aqui está o resumo da sua compra do dia *{data_v}*:\n\n"
                            msg += f"🧾 *Venda Nº {novo_cod}*\n\n"
                            msg += f"*Produtos:*\n{lista_produtos_msg}\n"
                            
                            # Se o subtotal for maior que o total pago, mostramos o desconto de forma clara
                            if subtotal_recibo > total_pdv:
                                valor_desconto = subtotal_recibo - total_pdv
                                subtotal_str = f"{subtotal_recibo:.2f}".replace('.', ',')
                                desconto_str = f"{valor_desconto:.2f}".replace('.', ',')
                                msg += f"🏷️ *Subtotal:* R$ {subtotal_str}\n"
                                msg += f"🎁 *Desconto:* - R$ {desconto_str}\n"
                                
                            total_str = f"{total_pdv:.2f}".replace('.', ',')
                            msg += f"💰 *Valor Total:* R$ {total_str}\n"
                            
                            # Exibição dos detalhes de parcelamento e crediário com quebras corretas
                            if f_pag == "Crediário":
                                if valor_entrada > 0:
                                    v_ent_str = f"{valor_entrada:.2f}".replace('.', ',')
                                    v_rest_str = f"{valor_restante:.2f}".replace('.', ',')
                                    msg += f"💸 *Entrada Paga:* R$ {v_ent_str}\n"
                                    msg += f"💳 *Restante:* {int(qtd_parcelas)}x de R$ {(valor_restante / qtd_parcelas):.2f}\n".replace('.', ',')
                                elif qtd_parcelas > 1:
                                    msg += f"💳 *Crediário:* {int(qtd_parcelas)}x de R$ {(total_pdv / qtd_parcelas):.2f}\n".replace('.', ',')
                                else:
                                    msg += f"💳 *Forma de Pagto:* Crediário (Sem entrada)\n"
                            elif qtd_parcelas > 1:
                                msg += f"💳 *Parcelamento:* {int(qtd_parcelas)}x de R$ {(total_pdv / qtd_parcelas):.2f}\n".replace('.', ',')
                            else:
                                msg += f"💳 *Forma de Pagto:* {f_pag}\n"
                                
                            msg += "\n\nMuito obrigada pela preferência! ✨"
                            
                            # Salvamento dos estados na sessão para persistência pós-rerun
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
                    st.success(f"🎉 Venda Nº {st.session_state['zap_codigo']} registrada com sucesso! Total: R$ {st.session_state['zap_total']:.2f}".replace('.', ','))
                    st.subheader("📲 Enviar Recibo via WhatsApp")
                    st.text_area("Prévia do texto:", value=st.session_state['zap_msg'], height=180, disabled=True)
                    st.link_button("🟢 Abrir WhatsApp e Enviar", st.session_state['zap_link'], type="primary", use_container_width=True)
                    if st.button("❌ Fechar Painel do Recibo", use_container_width=True):
                        del st.session_state['zap_link']
                        if 'zap_msg' in st.session_state: del st.session_state['zap_msg']
                        if 'zap_codigo' in st.session_state: del st.session_state['zap_codigo']
                        if 'zap_total' in st.session_state: del st.session_state['zap_total']
                        st.rerun()
                        
        with tab_compra:
            st.subheader("📥 Entrada de Mercadorias (via PDF Direto)")
            st.info("Faça o upload do PDF do seu pedido. O sistema vai extrair os produtos e gerar uma planilha para você revisar as quantidades.")

            arquivo_pdf = st.file_uploader("Selecione o arquivo PDF do Pedido", type=["pdf"])

            if arquivo_pdf:
                if st.button("🔍 Processar PDF do Pedido", type="primary"):
                    import pdfplumber
                    import re
                    
                    try:
                        texto_extraido = ""
                        with pdfplumber.open(arquivo_pdf) as pdf:
                            for pagina in pdf.pages:
                                texto_extraido += pagina.extract_text() + " "
                        
                        if texto_extraido:
                            texto_limpo = texto_extraido.replace('\n', ' ')
                            
                            # NOVO PADRÃO: Ajustado exatamente para o que o pdfplumber extraiu
                            # Busca: 8 dígitos -> Nome -> R$ Preço -> Quantidade
                            padrao = r'(\d{8})\s+(.*?)\s+R\$\s*([\d.,]+)\s+(\d+)'
                            
                            produtos_extraidos = []
                            for match in re.finditer(padrao, texto_limpo):
                                codigo = match.group(1)
                                nome_produto = match.group(2).strip()
                                preco_str = match.group(3).replace('.', '').replace(',', '.')
                                quantidade = int(match.group(4))
                                
                                # Filtro para evitar lixo
                                if "Desconto" not in nome_produto and "Folheto" not in nome_produto:
                                    produtos_extraidos.append({
                                        "Código": codigo,
                                        "Produto": nome_produto,
                                        "Preço Un. (R$)": float(preco_str),
                                        "Quantidade": quantidade
                                    })
                            
                            if produtos_extraidos:
                                st.session_state['produtos_pedido'] = produtos_extraidos
                                st.success(f"📊 {len(produtos_extraidos)} produtos identificados! Ajuste-os abaixo.")
                            else:
                                st.error("❌ Não encontramos produtos no padrão. Verifique se é o PDF oficial do pedido.")
                                with st.expander("Ver texto extraído (Debug)"):
                                    st.write(texto_extraido[:1000])
                        else:
                            st.error("❌ Não foi possível extrair texto do documento.")
                            
                    except Exception as erro_leitura:
                        st.error(f"Erro ao processar o arquivo PDF: {erro_leitura}")

            # Exibição da planilha interativa
            if 'produtos_pedido' in st.session_state and st.session_state['produtos_pedido']:
                st.markdown("### ✏️ Planilha de Ajuste de Estoque")
                st.caption("Dê um duplo clique na célula de 'Quantidade' para alterar. Para remover um item, clique no número à esquerda da linha e aperte 'Delete'.")
                
                df_original = pd.DataFrame(st.session_state['produtos_pedido'])
                
                df_editado = st.data_editor(
                    df_original,
                    num_rows="dynamic",
                    use_container_width=True,
                    key="editor_pedido_estoque"
                )
                
                # Adicionamos um campo para você digitar o número da nota/pedido antes de salvar
                numero_nota = st.text_input("Número do Pedido ou NF (Obrigatório para o Histórico):", placeholder="Ex: 134655")
                
                if st.button("💾 Confirmar e Dar Entrada no Estoque", type="primary", use_container_width=True):
                    if not numero_nota:
                        st.warning("⚠️ Por favor, informe o número do pedido ou nota fiscal antes de salvar.")
                    else:
                        try:
                            conn = conectar_banco()
                            cur = conn.cursor()
                            
                            # 1. Calcula o total da nota com base nos itens da tabela editada
                            valor_total_nota = sum([float(row['Preço Un. (R$)']) * int(row['Quantidade']) for _, row in df_editado.iterrows()])
                            
                            # 2. Cria o registro principal na tabela 'compras' e pega o ID gerado
                            cur.execute("""
                                INSERT INTO compras (numero_pedido, data_entrada, valor_total, empresa_id) 
                                VALUES (%s, CURRENT_DATE, %s, %s) RETURNING id
                            """, (numero_nota, valor_total_nota, emp_id))
                            compra_id = cur.fetchone()[0]
                            
                            itens_salvos = 0
                            
                            # 3. Processa cada item da planilha
                            for _, row in df_editado.iterrows():
                                v_cod = str(row['Código'])
                                v_nome = str(row['Produto'])
                                v_qtd = int(row['Quantidade'])
                                v_valor = float(row['Preço Un. (R$)'])
                                
                                # Grava o histórico detalhado na tabela 'itens_compra'
                                cur.execute("""
                                    INSERT INTO itens_compra (compra_id, produto_referencia, nome_produto, quantidade, preco_custo) 
                                    VALUES (%s, %s, %s, %s, %s)
                                """, (compra_id, v_cod, v_nome, v_qtd, v_valor))
                                
                                # Verifica se o produto já existe no estoque geral
                                cur.execute("SELECT id FROM produtos WHERE referencia = %s AND empresa_id = %s", (v_cod, emp_id))
                                prod_existe = cur.fetchone()
                                
                                if prod_existe:
                                    # Soma a quantidade ao estoque existente
                                    cur.execute("UPDATE produtos SET quantidade = quantidade + %s WHERE id = %s", (v_qtd, prod_existe[0]))
                                else:
                                    # Cadastra produto novo automaticamente
                                    cur.execute("""
                                        INSERT INTO produtos (nome, quantidade, valor, marca, categoria, empresa_id, referencia) 
                                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                                    """, (v_nome, v_qtd, v_valor, "D'Grava", "Geral", emp_id, v_cod))
                                
                                itens_salvos += 1
                            
                            # 4. (Opcional) Lançar no Financeiro - Contas a Pagar
                            # cur.execute("INSERT INTO contas_pagar (descricao, valor, data_vencimento, status, empresa_id) VALUES (%s, %s, CURRENT_DATE, 'Pago', %s)", (f"Pedido/NF: {numero_nota}", valor_total_nota, emp_id))
                            
                            conn.commit()
                            conn.close()
                            
                            st.success(f"✅ Sucesso! Entrada {numero_nota} processada. {itens_salvos} itens atualizados no estoque.")
                            del st.session_state['produtos_pedido']
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"Erro ao salvar dados no banco: {e}")
                            if 'conn' in locals(): conn.rollback(); conn.close()

                if st.button("❌ Cancelar Importação", use_container_width=True):
                    del st.session_state['produtos_pedido']
                    st.rerun() 
                    
        with tab_historico_compras:
            st.subheader("📋 Consulta de Notas e Pedidos de Entrada")
            
            # Filtros na parte superior
            c_ini, c_fim = st.columns(2)
            data_ini = c_ini.date_input("De:", value=date.today() - timedelta(days=30), format="DD/MM/YYYY", key="filtro_compra_ini")
            data_fim = c_fim.date_input("Até:", value=date.today(), format="DD/MM/YYYY", key="filtro_compra_fim")
            
            # Busca as compras realizadas no período
            query_compras = """
                SELECT id, numero_pedido, to_char(data_entrada, 'DD/MM/YYYY') as data, valor_total 
                FROM compras 
                WHERE empresa_id = %s AND data_entrada BETWEEN %s AND %s
                ORDER BY data_entrada DESC
            """
            df_historico = carregar_dados(query_compras, (emp_id, data_ini, data_fim))
            
            if not df_historico.empty:
                st.markdown("### 🔍 Selecione uma Entrada para Ver os Itens")
                
                opcoes_compra = {
                    row['id']: f"📦 Pedido: {row['numero_pedido']} | Data: {row['data']} | Total: R$ {row['valor_total']:.2f}"
                    for _, row in df_historico.iterrows()
                }
                
                compra_selecionada_id = st.selectbox(
                    "Escolha a nota/pedido para inspecionar:", 
                    options=list(opcoes_compra.keys()), 
                    format_func=lambda x: opcoes_compra[x]
                )
                
                if compra_selecionada_id:
                    query_itens = """
                        SELECT produto_referencia as "Código", nome_produto as "Produto", 
                               quantidade as "Quantidade", preco_custo as "Preço Un. (R$)",
                               (quantidade * preco_custo) as "Subtotal (R$)"
                        FROM itens_compra 
                        WHERE compra_id = %s
                    """
                    df_itens_compra = carregar_dados(query_itens, (int(compra_selecionada_id),))
                    
                    st.markdown("#### 🛒 Itens desta Entrada")
                    st.dataframe(df_itens_compra, use_container_width=True, hide_index=True)
                    
                    dados_compra = df_historico[df_historico['id'] == compra_selecionada_id].iloc[0]
                    st.metric(label="Valor Total da Nota", value=f"R$ {dados_compra['valor_total']:.2f}")
            else:
                st.warning("Nenhuma nota de entrada processada neste período.")
    
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

    # ==========================================================
    # MÓDULO 5: CRM
    # ==========================================================
    elif modulo == "📣 CRM & Pós-Venda":
        st.subheader("📣 Gestão de Relacionamento: Método 2+2+2")
        st.markdown("Acompanhe o ciclo de vida dos seus clientes e gere recompras automáticas.")
        
        # 1. Busca das Vendas e Cálculo dos Dias Passados
        # Damos uma pequena janela (ex: 2 a 5 dias) para garantir que você não perca o cliente 
        # caso não abra o sistema exatamente no segundo dia.
        query_crm = """
            SELECT 
                c.id as cliente_id,
                c.nome as cliente, 
                c.telefone, 
                v.codigo_venda,
                v.data_venda,
                (CURRENT_DATE - TO_DATE(v.data_venda, 'DD/MM/YYYY')) as dias_passados
            FROM vendas v
            JOIN clientes c ON v.cliente_id = c.id
            WHERE v.empresa_id = %s
            AND (
                (CURRENT_DATE - TO_DATE(v.data_venda, 'DD/MM/YYYY')) BETWEEN 2 AND 5
                OR (CURRENT_DATE - TO_DATE(v.data_venda, 'DD/MM/YYYY')) BETWEEN 14 AND 20
                OR (CURRENT_DATE - TO_DATE(v.data_venda, 'DD/MM/YYYY')) >= 60
            )
            GROUP BY c.id, c.nome, c.telefone, v.codigo_venda, v.data_venda
            ORDER BY dias_passados ASC
        """
        
        df_crm = carregar_dados(query_crm, (emp_id,))
        
        # 2. Inicializando as listas vazias
        df_2_dias = pd.DataFrame()
        df_2_semanas = pd.DataFrame()
        df_2_meses = pd.DataFrame()
        
        if not df_crm.empty:
            # Categorizando os clientes baseados nos dias passados
            df_2_dias = df_crm[(df_crm['dias_passados'] >= 2) & (df_crm['dias_passados'] <= 5)]
            df_2_semanas = df_crm[(df_crm['dias_passados'] >= 14) & (df_crm['dias_passados'] <= 20)]
            df_2_meses = df_crm[(df_crm['dias_passados'] >= 60)]
            
        # 3. --- DESENHANDO OS 3 CARDS DE MÉTRICAS ---
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("🟢 2 Dias (Satisfação)", f"{len(df_2_dias)} clientes")
        c2.metric("🟡 2 Semanas (Acompanhamento)", f"{len(df_2_semanas)} clientes")
        c3.metric("🔴 2 Meses (Reposição)", f"{len(df_2_meses)} clientes")
        st.markdown("---")
        
        # 4. --- ABAS PARA EXIBIR AS LISTAS E OS BOTÕES DE WHATSAPP ---
        tab_2d, tab_2s, tab_2m = st.tabs(["🟢 Contatos de 2 Dias", "🟡 Contatos de 2 Semanas", "🔴 Contatos de 2 Meses"])
        
        # Função interna rápida para gerar o botão do Zap
        def gerar_linha_contato(row, mensagem_padrao):
            st.markdown(f"**Cliente:** {row['cliente']} | **Venda:** Nº {row['codigo_venda']} | **Data:** {row['data_venda']} ({row['dias_passados']} dias atrás)")
            tel_cli = row['telefone']
            
            if tel_cli:
                tel_limpo = ''.join(filter(str.isdigit, str(tel_cli)))
                if len(tel_limpo) >= 10:
                    if not tel_limpo.startswith('55'): tel_limpo = '55' + tel_limpo
                    link_wpp = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(mensagem_padrao)}"
                    st.link_button(f"💬 Enviar Script para {row['cliente'].split()[0]}", link_wpp, use_container_width=True)
                else:
                    st.warning("⚠️ Telefone mal formatado.")
            else:
                st.warning("⚠️ Sem telefone cadastrado.")
            st.markdown("<hr style='margin: 0.5em 0px; opacity: 0.3'>", unsafe_allow_html=True)

        # Preenchendo a Aba 2 Dias
        with tab_2d:
            if not df_2_dias.empty:
                for _, row in df_2_dias.iterrows():
                    msg_2d = f"Olá, {row['cliente'].split()[0]}! 🌸 Passando rapidinho para saber se já conseguiu testar os produtos da sua compra do dia {row['data_venda']}. Como foi a primeira impressão? Se tiver qualquer dúvida sobre como usar, estou por aqui! ✨"
                    gerar_linha_contato(row, msg_2d)
            else:
                st.info("Nenhum cliente na janela de 2 dias hoje.")
                
        # Preenchendo a Aba 2 Semanas
        with tab_2s:
            if not df_2_semanas.empty:
                for _, row in df_2_semanas.iterrows():
                    msg_2s = f"Oi, {row['cliente'].split()[0]}! Tudo bem? 🌸 Já faz umas duas semaninhas que você está com seus produtos, né? Passando só para confirmar se está dando tudo certo com o uso e se os resultados estão dentro do esperado. Me conta depois! ✨"
                    gerar_linha_contato(row, msg_2s)
            else:
                st.info("Nenhum cliente na janela de 2 semanas hoje.")
                
        # Preenchendo a Aba 2 Meses
        with tab_2m:
            if not df_2_meses.empty:
                for _, row in df_2_meses.iterrows():
                    msg_2m = f"Olá, {row['cliente'].split()[0]}! 🌸 Dei uma olhadinha aqui e vi que já faz um tempinho desde a nossa última conversa. Como estão os seus produtinhos? Provavelmente alguns já estão pedindo reposição, né? Posso te mandar as novidades e promoções que chegaram essa semana? ✨"
                    gerar_linha_contato(row, msg_2m)
            else:
                st.info("Nenhum cliente na janela de 2 meses hoje.")
