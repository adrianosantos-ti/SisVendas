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
hoje = date.today()
import urllib.parse
import base64
import json
from PIL import Image

# 1. Forçamos a leitura da imagem (use o nome exato do seu arquivo PNG)
icone = Image.open("logo.png") 

# 2. Configuração da página - DEVE SER O PRIMEIRO COMANDO STREAMLIT
st.set_page_config(
    page_title="Apprimory - Inteligência para Gestão", # Deixei mais curto para ficar elegante na aba
    page_icon=icone,
    layout="wide"
)

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

# ==========================================
# CONEXÃO AO BANCO
# Usa uma conexão por execução com reconexão
# automática. Simples, robusto e compatível
# com o PgBouncer do Supabase (porta 6543).
# ==========================================
def conectar_banco():
    return psycopg2.connect(DATABASE_URL)

def devolver_conexao(conn):
    try:
        conn.close()
    except Exception:
        pass

def carregar_dados(query, params=None):
    conn = conectar_banco()
    try:
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
        return df
    finally:
        devolver_conexao(conn)

def executar_escrita(operacoes):
    """
    Executa operações de escrita no banco de forma segura.
    Garante commit ou rollback e fechamento da conexão.
    
    Uso:
        def minhas_operacoes(cur):
            cur.execute("UPDATE ...", (params,))
        executar_escrita(minhas_operacoes)
    """
    conn = conectar_banco()
    try:
        cur = conn.cursor()
        operacoes(cur)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        devolver_conexao(conn)

# ==========================================
# CACHE DE LEITURA (reduz chamadas ao banco)
# TTL de 60s: dados ficam em memória por 1 min.
# Use limpar_cache() após qualquer INSERT/UPDATE/DELETE.
# ==========================================
@st.cache_data(ttl=60, show_spinner=False)
def carregar_dados_cached(query, params=None):
    return carregar_dados(query, params)

def limpar_cache():
    st.cache_data.clear()

# ==========================================
# INTERFACE CONFIG E CONTROLE DE LOGIN
# ==========================================
#st.set_page_config(page_title="Apprimory - Inteligência para Gestão", layout="wide")

if 'logado' not in st.session_state:
    st.session_state['logado'] = False
    st.session_state['perfil'] = ''
    st.session_state['empresa_id'] = None
    st.session_state['usuario_nome'] = ''

# --- TELA DE LOGIN ---
if not st.session_state['logado']:
    # 1. Função para converter a imagem e poder usar no HTML
    def get_base64_image(caminho_imagem):
        import base64
        with open(caminho_imagem, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()

    # 2. Converte a sua logo (verifique se o nome do arquivo está certinho)
    img_base64 = get_base64_image("Apprimory_logo_branca.png")

    # --- APLICAÇÃO DAS COLUNAS INVISÍVEIS PARA CENTRALIZAR O CARD ---
    col_vazia_esq, col_login, col_vazia_dir = st.columns([1, 1.2, 1])

    with col_login:
        # 3. Exibe a imagem centralizada e com tamanho controlado
        st.markdown(
            f"""
            <div style="text-align: center;">
                <img src="data:image/png;base64,{img_base64}" width="350">
            </div>
            """,
            unsafe_allow_html=True
        )
        
        st.write("") # Dá um pequeno espaço extra
        
        # Centralizando também o texto de boas-vindas para acompanhar o design
        st.markdown("<h3 style='text-align: center;'>🔐 Identifique-se</h3>", unsafe_allow_html=True)
        
        with st.container(border=True):
            login_input = st.text_input("Usuário")
            senha_input = st.text_input("Senha", type="password")
            
            if st.button("Entrar no Sistema", type="primary", use_container_width=True):
                conn = conectar_banco()
                cursor = conn.cursor()
                cursor.execute("SELECT id, nome, perfil, empresa_id FROM usuarios WHERE login = %s AND senha = %s", (login_input, senha_input))
                usuario = cursor.fetchone()
                # ==========================================
                # CORREÇÃO NO BLOCO DE LOGIN
                # ==========================================
                if usuario:
                    st.session_state['logado'] = True
                    st.session_state['usuario_id'] = usuario[0]
                    st.session_state['usuario_nome'] = usuario[1]
                    st.session_state['perfil'] = usuario[2]
                    st.session_state['empresa_id'] = usuario[3]
    
                    perfil_usuario = usuario[2]
                    id_usuario_logado = usuario[0]

                    if perfil_usuario in ['admin', 'master']:
                        # Se for admin/master, puxa todas as chaves existentes no sistema
                        cursor.execute("SELECT chave FROM modulos")
                        resultado = cursor.fetchall()
                        # 🌟 ADICIONADO .strip() AQUI PARA LIMPAR ESPAÇOS OCULTOS
                        st.session_state['modulos_permitidos'] = [linha[0].strip() for linha in resultado] if resultado else []
                    else:
                        # Se for usuário comum, cruza com a tabela de permissões
                        cursor.execute("""
                            SELECT m.chave 
                            FROM permissoes_acesso p
                            JOIN modulos m ON p.modulo_id = m.id
                            WHERE p.usuario_id = %s
                        """, (id_usuario_logado,))
                        resultado = cursor.fetchall()
                        # 🌟 ADICIONADO .strip() AQUI TAMBÉM
                        st.session_state['modulos_permitidos'] = [linha[0].strip() for linha in resultado] if resultado else []

                    # Agora sim, com tudo salvo na memória, fechamos o banco e recarregamos a tela
                    devolver_conexao(conn)
                    st.rerun()
                else:
                    devolver_conexao(conn)
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
        
        # --- BLOCO DE CADASTRO ---
        with st.form("form_nova_empresa", clear_on_submit=True):
            nome_emp = st.text_input("Nome Comercial")
            cnpj_emp = st.text_input("CNPJ")
            logo_emp = st.text_input("URL da Logomarca (Opcional)", placeholder="Ex: https://github.com/.../logo.png?raw=true")
            
            if st.form_submit_button("Salvar"):
                conn = conectar_banco()
                conn.cursor().execute(
                    "INSERT INTO empresas (nome, cnpj, logo_url) VALUES (%s, %s, %s)", 
                    (nome_emp, cnpj_emp, logo_emp)
                )
                conn.commit()
                devolver_conexao(conn)
                st.success(f"Empresa '{nome_emp}' cadastrada!")
                limpar_cache()
                st.rerun()
                
        # Carrega os dados uma vez para usar na edição e na tabela
        df_empresas = carregar_dados_cached("SELECT id, nome, cnpj, logo_url FROM empresas ORDER BY id")
        
        # --- NOVO BLOCO DE EDIÇÃO ---
        with st.expander("✏️ Editar Empresa"):
            if not df_empresas.empty:
                opcoes_ed_emp = df_empresas['id'].tolist()
                
                def formatar_empresa(e_id):
                    linha = df_empresas[df_empresas['id'] == e_id].iloc[0]
                    cnpj_display = f" - CNPJ: {linha['cnpj']}" if linha['cnpj'] else ""
                    return f"{linha['nome']} (ID: {linha['id']}){cnpj_display}"
                    
                emp_selecionada = st.selectbox("Selecione a empresa para atualizar:", opcoes_ed_emp, format_func=formatar_empresa)
                
                if emp_selecionada:
                    emp_atual = df_empresas[df_empresas['id'] == emp_selecionada].iloc[0]
                    
                    with st.form("f_edita_emp"):
                        c1, c2 = st.columns(2)
                        e_nome = c1.text_input("Nome Comercial", value=emp_atual['nome'])
                        e_cnpj = c2.text_input("CNPJ", value=emp_atual['cnpj'] if emp_atual['cnpj'] else "")
                        
                        # Previne erros caso a coluna no banco esteja como nula (NULL)
                        val_logo = emp_atual['logo_url'] if 'logo_url' in emp_atual and pd.notna(emp_atual['logo_url']) else ""
                        e_logo = st.text_input("URL da Logomarca", value=val_logo, placeholder="Ex: https://github.com/.../logo.png?raw=true")
                        
                        if st.form_submit_button("💾 Salvar Alterações"):
                            conn = conectar_banco()
                            conn.cursor().execute(
                                "UPDATE empresas SET nome=%s, cnpj=%s, logo_url=%s WHERE id=%s", 
                                (e_nome, e_cnpj, e_logo, int(emp_selecionada))
                            )
                            conn.commit()
                            devolver_conexao(conn)
                            
                            st.success("✅ Cadastro da empresa atualizado com sucesso!")
                            limpar_cache()
                            st.rerun()
            else:
                st.info("Não há empresas cadastradas para editar.")

        # --- TABELA FINAL DE EXIBIÇÃO DE EMPRESAS ---
        st.dataframe(df_empresas, use_container_width=True, hide_index=True)

    with aba_cad_usuario:
        st.subheader("Novo Login e Acessos")
        
        # Carrega lista de empresas para usar nos selects
        df_emp_list = carregar_dados_cached("SELECT id, nome FROM empresas ORDER BY id")
        
        if not df_emp_list.empty:
            dict_empresas = dict(zip(df_emp_list['nome'], df_emp_list['id']))
            lista_nomes_empresas = list(dict_empresas.keys())
        else:
            dict_empresas = {}
            lista_nomes_empresas = []

        # --- 1. BLOCO DE NOVO CADASTRO ---
        with st.form("form_novo_usuario", clear_on_submit=True):
            nome_usu = st.text_input("Nome")
            emp_usu = st.selectbox("Empresa", options=lista_nomes_empresas)
            login_usu = st.text_input("Login")
            senha_usu = st.text_input("Senha", type="password")
            
            perfil_usu = st.selectbox("Perfil de Acesso", ["comum", "admin"], help="Admins têm acesso a todas as telas automaticamente. Comuns precisam de permissões específicas.")
            
            if st.form_submit_button("Criar"):
                conn = conectar_banco()
                conn.cursor().execute(
                    "INSERT INTO usuarios (nome, login, senha, empresa_id, perfil) VALUES (%s,%s,%s,%s,%s)", 
                    (nome_usu, login_usu, senha_usu, dict_empresas[emp_usu], perfil_usu)
                )
                conn.commit()
                devolver_conexao(conn)
                st.success(f"Usuário '{nome_usu}' criado com sucesso! Agora configure as permissões dele na aba abaixo.")
                limpar_cache()
                st.rerun()

        st.divider()
        st.subheader("Usuários Cadastrados")

        # Carrega os dados atualizados
        df_usuarios = carregar_dados_cached("SELECT u.id, u.nome, u.login, u.perfil, u.empresa_id, e.nome as empresa FROM usuarios u JOIN empresas e ON u.empresa_id = e.id ORDER BY u.id")
        
        if not df_usuarios.empty:
            opcoes_usuarios = df_usuarios['id'].tolist()
            
            def formatar_usuario(u_id):
                linha = df_usuarios[df_usuarios['id'] == u_id].iloc[0]
                return f"ID {linha['id']} - {linha['nome']} ({linha['perfil'].upper()}) | Emp: {linha['empresa']}"
            
            # 1. Exibe a caixa de seleção com os usuários formatados
            usuario_selecionado = st.selectbox("Selecione um Usuário", options=opcoes_usuarios, format_func=formatar_usuario)
        else:
            st.info("Nenhum usuário cadastrado ou encontrado no sistema.")
            opcoes_usuarios = []
            
        # --- 2. NOVO BLOCO: GERENCIAR PERMISSÕES ---
        with st.expander("🔐 Gerenciar Permissões de Acesso (Menu)"):
            if not df_usuarios.empty:
                # Puxa quais telas existem no sistema
                df_modulos = carregar_dados_cached("SELECT id, nome, chave FROM modulos ORDER BY id")
                
                if df_modulos.empty:
                    st.error("Nenhum módulo cadastrado no banco. Rode o INSERT na tabela 'modulos' primeiro.")
                else:
                    usu_perm_sel = st.selectbox("Selecione o usuário para configurar os acessos:", opcoes_usuarios, format_func=formatar_usuario, key="sel_perm")
                    
                    if usu_perm_sel:
                        linha_usu = df_usuarios[df_usuarios['id'] == usu_perm_sel].iloc[0]
                        
                        if linha_usu['perfil'] == 'admin' or linha_usu['perfil'] == 'master':
                            st.info(f"O usuário **{linha_usu['nome']}** tem o perfil '{linha_usu['perfil'].upper()}'. Ele já possui acesso liberado a todas as telas do sistema por padrão.")
                        else:
                            st.write(f"Configure quais telas o usuário **{linha_usu['nome']}** pode acessar:")
                            
                            # Puxa do banco quais permissões esse usuário JÁ TEM hoje
                            query_perm_atuais = "SELECT modulo_id FROM permissoes_acesso WHERE usuario_id = %s"
                            df_perm_atuais = carregar_dados_cached(query_perm_atuais, (int(usu_perm_sel),))
                            modulos_ja_permitidos = df_perm_atuais['modulo_id'].tolist() if not df_perm_atuais.empty else []

                            # Formulário de Checkboxes dinâmicos
                            with st.form("f_permissoes"):
                                selecoes = {}
                                for _, mod in df_modulos.iterrows():
                                    tem_acesso = mod['id'] in modulos_ja_permitidos
                                    selecoes[mod['id']] = st.checkbox(f"TELA: {mod['nome']}", value=tem_acesso)
                                
                                if st.form_submit_button("💾 Salvar Permissões"):
                                    conn = conectar_banco()
                                    cursor = conn.cursor()
                                    
                                    # Limpa as permissões antigas do usuário para regravar do zero
                                    cursor.execute("DELETE FROM permissoes_acesso WHERE usuario_id = %s", (int(usu_perm_sel),))
                                    
                                    # Grava apenas os checkboxes marcados
                                    for mod_id, esta_marcado in selecoes.items():
                                        if esta_marcado:
                                            cursor.execute(
                                                "INSERT INTO permissoes_acesso (usuario_id, modulo_id) VALUES (%s, %s)", 
                                                (int(usu_perm_sel), int(mod_id))
                                            )
                                    
                                    conn.commit()
                                    devolver_conexao(conn)
                                    st.success(f"Permissões de {linha_usu['nome']} atualizadas com sucesso!")
            else:
                st.info("Cadastre um usuário primeiro.")

        # --- 3. BLOCO DE EDIÇÃO E EXCLUSÃO ---
        c_edit, c_del = st.columns(2)
        
        with c_edit:
            with st.expander("✏️ Editar Cadastro (Nome/Empresa/Perfil)"):
                if not df_usuarios.empty:
                    usu_ed_sel = st.selectbox("Selecione o usuário:", opcoes_usuarios, format_func=formatar_usuario, key="edit_usu")
                    if usu_ed_sel:
                        usu_atual = df_usuarios[df_usuarios['id'] == usu_ed_sel].iloc[0]
                        with st.form("f_edita_usuario"):
                            e_nome = st.text_input("Nome", value=usu_atual['nome'])
                            e_login = st.text_input("Login", value=usu_atual['login'])
                            e_perfil = st.selectbox("Perfil", ["comum", "admin"], index=0 if usu_atual['perfil'] == 'comum' else 1)
                            
                            try: idx_emp = lista_nomes_empresas.index(usu_atual['empresa'])
                            except ValueError: idx_emp = 0
                            e_emp = st.selectbox("Empresa", options=lista_nomes_empresas, index=idx_emp)
                            
                            if st.form_submit_button("💾 Salvar Alterações"):
                                conn = conectar_banco()
                                conn.cursor().execute(
                                    "UPDATE usuarios SET nome=%s, login=%s, empresa_id=%s, perfil=%s WHERE id=%s", 
                                    (e_nome, e_login, dict_empresas[e_emp], e_perfil, int(usu_ed_sel))
                                )
                                conn.commit()
                                devolver_conexao(conn)
                                st.success("✅ Usuário atualizado com sucesso!")
                                limpar_cache()
                                st.rerun()

        with c_del:
            with st.expander("🗑️ Excluir Login"):
                if not df_usuarios.empty:
                    usu_del_sel = st.selectbox("Selecione o usuário para EXCLUIR:", opcoes_usuarios, format_func=formatar_usuario, key="del_usu")
                    with st.form("f_exclui_usuario"):
                        st.warning("⚠️ O acesso será apagado permanentemente.")
                        if st.form_submit_button("🚨 Confirmar Exclusão"):
                            conn = conectar_banco()
                            conn.cursor().execute("DELETE FROM usuarios WHERE id=%s", (int(usu_del_sel),))
                            conn.commit()
                            devolver_conexao(conn)
                            st.success("🗑️ Usuário excluído!")
                            limpar_cache()
                            st.rerun()

        # --- 4. TABELA FINAL DE EXIBIÇÃO ---
        if not df_usuarios.empty:
            st.dataframe(df_usuarios[['id', 'nome', 'login', 'perfil', 'empresa']], use_container_width=True, hide_index=True)
    
    with aba_senhas:
        st.subheader("Reset de Senhas")
        df_todos_usu = carregar_dados_cached("SELECT id, nome, login FROM usuarios ORDER BY nome")
        if not df_todos_usu.empty:
            dict_todos_usu = {f"{row['nome']} ({row['login']})": row['id'] for _, row in df_todos_usu.iterrows()}
            usu_sel = st.selectbox("Selecione o Usuário", options=list(dict_todos_usu.keys()))
            nova_sen = st.text_input("Nova Senha", type="password")
            if st.button("Confirmar Alteração"):
                conn = conectar_banco()
                conn.cursor().execute("UPDATE usuarios SET senha = %s WHERE id = %s", (nova_sen, dict_todos_usu[usu_sel]))
                conn.commit()
                devolver_conexao(conn)
                st.success("Senha alterada!")
        else:
            st.info("Nenhum usuário para resetar a senha.")
            
# --- SISTEMA OPERACIONAL (USUÁRIOS COMUNS / EMPRESAS) ---
else:
    emp_id = st.session_state['empresa_id']
    
    # ---------------------------------------------------------
    # MENU LATERAL DE MÓDULOS
    # ---------------------------------------------------------
    # 1. A PRIMEIRA coisa do Streamlit no código TEM que ser a configuração da página:
    icone = Image.open("logo.png") 

    # 2. Configuração da página - DEVE SER O PRIMEIRO COMANDO STREAMLIT
    st.set_page_config(
        page_title="Apprimory - Inteligência para Gestão", 
        page_icon=icone,
        layout="wide"
    )

    st.sidebar.image("logo.png", width=100)
    st.sidebar.title(f"Módulos")

    # --- CORREÇÃO: Lê o bilhete ANTES de desenhar o menu ---
    if 'forcar_menu' in st.session_state:
        st.session_state['menu_principal'] = st.session_state['forcar_menu']
        del st.session_state['forcar_menu'] # Apaga o bilhete para não ficar travado
    
    # --- FILTRO DINÂMICO DE PERMISSÕES ---
    meus_acessos = st.session_state.get('modulos_permitidos', [])

    # Mapeamento exato entre as chaves do banco e os textos do seu Radio
    mapeamento_modulos = {
        'mod_dash': "📊 Análises", 
        'mod_produtos': "🗂️ Cadastros", 
        'mod_vendas': "🔄 Movimentações", 
        'mod_financeiro': "💰 Financeiro",
        'mod_crm': "📣 CRM & Pós-Venda"
    }

    # Cria a lista de opções contendo apenas o que o usuário tem permissão para ver
    opcoes_permitidas = [texto for chave, texto in mapeamento_modulos.items() if chave in meus_acessos]

    # Validação crucial: Se o usuário logou e a opção padrão do state não está no pacote dele
    # (ex: o usuário anterior era admin e estava em Financeiro, mas o atual só vê PDV),
    # nós forçamos o state para a primeira opção disponível para evitar quebra no Streamlit.
    if opcoes_permitidas:
        if 'menu_principal' in st.session_state and st.session_state['menu_principal'] not in opcoes_permitidas:
            st.session_state['menu_principal'] = opcoes_permitidas[0]

        # Desenha o Radio contendo APENAS os módulos liberados
        modulo = st.sidebar.radio("Navegação Principal:", options=opcoes_permitidas, key="menu_principal")
    else:
        st.sidebar.warning("⚠️ Nenhum módulo liberado para seu usuário.")
        modulo = None
    
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
                devolver_conexao(conn)

    if st.sidebar.button("🚪 Sair do Sistema", use_container_width=True):
        st.session_state.clear()
        limpar_cache()
        st.rerun()

    # ==========================================
    # CABEÇALHO GLOBAL 100% DINÂMICO E PERSONALIZADO
    # ==========================================
    nome_empresa = "Minha Empresa" 
    logo_customizada = None
    
    try:
        # Puxa o nome e a URL da logo da empresa logada
        df_emp = carregar_dados_cached("SELECT nome, logo_url FROM empresas WHERE id = %s", (emp_id,))
        if not df_emp.empty:
            nome_empresa = df_emp.iloc[0]['nome']
            logo_customizada = df_emp.iloc[0]['logo_url']
    except Exception:
        pass

    # Lógica inteligente para renderizar a logo
    import base64
    import os
    
    logo_html = "<span style='font-size: 28px;'>🏢</span>" # Fallback ajustado
    
    # Cenário A: A empresa possui uma logo cadastrada no banco (URL ou Caminho)
    if logo_customizada:
        if logo_customizada.startswith("http"):
            # Aumentamos o width para 85 (e removemos o height fixo para não distorcer imagens retangulares)
            logo_html = f"<img src='{logo_customizada}' width='85' style='object-fit: contain; border-radius: 4px;'>"
        elif os.path.exists(logo_customizada):
            # Se for um caminho de ficheiro local no servidor, converte para Base64
            with open(logo_customizada, "rb") as img_file:
                img_base64 = base64.b64encode(img_file.read()).decode()
                logo_html = f"<img src='data:image/png;base64,{img_base64}' width='85' style='object-fit: contain;'>"
                
    # Cenário B: Não tem logo cadastrada, tenta usar a logo padrão do sistema ('logo.png')
    elif os.path.exists("logo.png"):
        with open("logo.png", "rb") as img_file:
            img_base64 = base64.b64encode(img_file.read()).decode()
            logo_html = f"<img src='data:image/png;base64,{img_base64}' width='85' style='object-fit: contain;'>"

    # Renderiza o painel com Flexbox (fonte reduzida para 28px e gap aumentado para 20px)
    st.markdown(
        f"""
        <div style="display: flex; align-items: center; gap: 20px; margin-top: -25px; margin-bottom: 5px;">
            {logo_html}
            <h1 style="margin: 0; padding: 0; font-size: 28px; font-weight: 800; line-height: 1.1; color: #1f2937;">
                {nome_empresa}
            </h1>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown('<hr style="margin: 0px 0px 15px 0px; border: none; border-top: 1px solid #ddd;">', unsafe_allow_html=True)
    # ==========================================
    # MÓDULO 1: ANÁLISES (Dashboard e Histórico)
    # ==========================================
    if modulo == "📊 Análises":
        st.markdown("### 📊 Gestão e Performance")
        
        # ==========================================
        # 1. FILTRO GLOBAL (Controla todas as abas)
        # ==========================================
        st.subheader("🔍 Período de Análise")
        op_per = ["Mês Atual", "Hoje", "Últimos 7 Dias", "Últimos 15 Dias", "Últimos 30 Dias", "Mês Anterior", "Todo o Período", "Personalizado"]
        per_sel = st.selectbox("Filtrar:", op_per)
        
        from datetime import date, timedelta
        import pandas as pd
        
        hoje = date.today()
        d_ini, d_fim = None, None
        
        if per_sel == "Hoje": d_ini, d_fim = hoje, hoje
        elif per_sel == "Últimos 7 Dias": d_ini, d_fim = hoje - timedelta(days=7), hoje
        elif per_sel == "Últimos 15 Dias": d_ini, d_fim = hoje - timedelta(days=15), hoje
        elif per_sel == "Últimos 30 Dias": d_ini, d_fim = hoje - timedelta(days=30), hoje
        elif per_sel == "Mês Atual": 
            import calendar
            d_ini = hoje.replace(day=1)
            ultimo_dia_mes = calendar.monthrange(hoje.year, hoje.month)[1]
            d_fim = hoje.replace(day=ultimo_dia_mes)
        elif per_sel == "Mês Anterior":
            p_dia = hoje.replace(day=1)
            d_fim = p_dia - timedelta(days=1)
            d_ini = d_fim.replace(day=1)
        elif per_sel == "Todo o Período":
            # Joga a data inicial bem para o passado e a final bem para o futuro
            d_ini = date(2000, 1, 1)
            d_fim = date(2099, 12, 31)
        elif per_sel == "Personalizado":
            c1, c2 = st.columns(2)
            d_ini = c1.date_input("Início", value=hoje - timedelta(days=30), format="DD/MM/YYYY")
            d_fim = c2.date_input("Fim", value=hoje, format="DD/MM/YYYY")

        # ==========================================
        # 2. ABAS DE ANÁLISE
        # ==========================================
        aba_dash, aba_crm, aba_hist, aba_alertas, aba_app = st.tabs(["📈 Análise de Vendas", "🎯 CRM e Clientes", "📋 Histórico", "🚨 Alertas", "📱 Visão App"])
        
        # --- ABA 1: DASHBOARD DE VENDAS (Seu código original adaptado) ---
        with aba_dash:
            query_dash = "SELECT v.codigo_venda, v.data_venda, v.valor_total, v.quantidade, p.nome AS produto, p.categoria FROM vendas v JOIN produtos p ON v.produto_id = p.id WHERE v.empresa_id = %s"
            df_dash = carregar_dados_cached(query_dash, (emp_id,))
            
            if not df_dash.empty and d_ini and d_fim:
                df_dash['Data_Obj'] = pd.to_datetime(df_dash['data_venda'], format='%d/%m/%Y', errors='coerce').dt.date
                
                # Aplica o filtro global
                df_dash = df_dash[(df_dash['Data_Obj'] >= d_ini) & (df_dash['Data_Obj'] <= d_fim)]
                
                if not df_dash.empty:
                    col1, col2, col3 = st.columns(3)
                    fat = df_dash['valor_total'].sum()
                    qtd_vendas_reais = df_dash['codigo_venda'].nunique()
                    ticket_medio = fat / qtd_vendas_reais if qtd_vendas_reais > 0 else 0
                    
                    col1.metric("Faturamento", f"R$ {fat:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
                    col2.metric("Vendas Fechadas", qtd_vendas_reais)
                    col3.metric("Ticket Médio", f"R$ {ticket_medio:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
                    
                    st.markdown("---")
                    import plotly.express as px
                    
                    df_fat_dia = df_dash.groupby('Data_Obj')['valor_total'].sum().reset_index()
                    st.plotly_chart(px.line(df_fat_dia, x='Data_Obj', y='valor_total', title="Curva de Vendas por Dia", template="plotly_white"), use_container_width=True)
                    
                    c1, c2 = st.columns(2)
                    df_top = df_dash.groupby('produto')['quantidade'].sum().reset_index().sort_values('quantidade', ascending=False).head(5).sort_values('quantidade', ascending=True)
                    df_top['produto_curto'] = df_top['produto'].apply(lambda x: (str(x)[:22] + '...') if len(str(x)) > 22 else str(x))
                    fig_top = px.bar(df_top, x='quantidade', y='produto', orientation='h', text='quantidade', color_discrete_sequence=['#0068c9'], title="Top 5 Produtos Mais Vendidos")
                    fig_top.update_yaxes(tickmode='array', tickvals=df_top['produto'], ticktext=df_top['produto_curto'])
                    c1.plotly_chart(fig_top, use_container_width=True)
                    
                    fig_cat = px.pie(df_dash.groupby('categoria')['valor_total'].sum().reset_index(), values='valor_total', names='categoria', hole=0.4, title="Vendas por Categoria", color_discrete_sequence=px.colors.qualitative.Bold)
                    c2.plotly_chart(fig_cat, use_container_width=True)
                else: 
                    st.warning(f"Sem vendas registradas no período de {d_ini.strftime('%d/%m/%Y')} a {d_fim.strftime('%d/%m/%Y')}.")
            else: 
                st.info("Faça vendas para ver gráficos.")

        # --- ABA 2: CRM E ANIVERSARIANTES ---
        with aba_crm:
            st.markdown("### 🎂 Aniversariantes do Período")
            if per_sel == "Todo o Período":
                st.caption("Exibindo **todos** os clientes cadastrados no Apprimory.")
            else:
                st.caption(f"Exibindo clientes que fazem aniversário entre **{d_ini.strftime('%d/%m/%Y')}** e **{d_fim.strftime('%d/%m/%Y')}**.")
                        
            query_cli = "SELECT nome, telefone, data_nascimento, tipo FROM clientes WHERE empresa_id = %s"
            df_cli = carregar_dados_cached(query_cli, (emp_id,))
            
            if not df_cli.empty and d_ini and d_fim:
                
                # --- A MÁGICA DA NOVA LÓGICA: Tratamento como Texto Flexível ---
                def checar_niver_flexivel(data_banco):
                    if per_sel == "Todo o Período": return True
                    if pd.isnull(data_banco) or str(data_banco).strip() == "": return False
                    
                    data_str = str(data_banco).strip()
                    dia_mes = ""
                    
                    # Se tiver barra (ex: 14/08 ou 14/08/1979)
                    if "/" in data_str:
                        partes = data_str.split("/")
                        if len(partes) >= 2:
                            dia_mes = f"{partes[0].zfill(2)}/{partes[1].zfill(2)}"
                    # Se tiver traço (ex: 1979-08-14)
                    elif "-" in data_str:
                        partes = data_str.split("-")
                        if len(partes) == 3: 
                            dia_mes = f"{partes[2].zfill(2)}/{partes[1].zfill(2)}"
                        elif len(partes) >= 2:
                            dia_mes = f"{partes[0].zfill(2)}/{partes[1].zfill(2)}"
                    
                    if not dia_mes: return False

                    if (d_fim - d_ini).days >= 365: return True
                        
                    # Monta os dias do filtro no formato DD/MM para comparar banana com banana
                    dias_do_periodo = []
                    total_dias = (d_fim - d_ini).days + 1
                    for i in range(total_dias):
                        dia_corrente = d_ini + timedelta(days=i)
                        dias_do_periodo.append(dia_corrente.strftime("%d/%m"))
                    
                    return dia_mes in dias_do_periodo

                # Aplica a lógica sem usar o to_datetime
                df_cli['Faz_Niver'] = df_cli['data_nascimento'].apply(checar_niver_flexivel)
                df_nivers = df_cli[df_cli['Faz_Niver']].copy()
                
                if not df_nivers.empty:
                    
                    # Formata bonitinho para aparecer só DD/MM na tela
                    def formatar_exibicao(data_banco):
                        if pd.isnull(data_banco) or str(data_banco).strip() == "": return "⚠️ Não informado"
                        data_str = str(data_banco).strip()
                        if "/" in data_str:
                            p = data_str.split("/")
                            return f"{p[0].zfill(2)}/{p[1].zfill(2)}"
                        if "-" in data_str:
                            p = data_str.split("-")
                            if len(p) == 3: return f"{p[2].zfill(2)}/{p[1].zfill(2)}"
                        return data_str

                    df_nivers['Aniversário'] = df_nivers['data_nascimento'].apply(formatar_exibicao)
                    
                    # Ordenação Cronológica (transformando DD/MM em MM-DD temporariamente só para a máquina organizar)
                    df_nivers['Ordem_Cronologica'] = df_nivers['Aniversário'].apply(lambda x: f"{x[-2:]}-{x[:2]}" if "/" in x else "99-99")
                    df_nivers = df_nivers.sort_values('Ordem_Cronologica')
                    
                    # 🟢 MÁGICA DO WHATSAPP: Cria o link de mensagem direto
                    def gerar_link_wpp(telefone, nome_cliente):
                        if pd.isnull(telefone) or str(telefone).strip() == "": return None
                        num = ''.join(filter(str.isdigit, str(telefone)))
                        if len(num) >= 10:
                            if len(num) <= 11: num = "55" + num
                            msg = f"""Olá, {nome_cliente}!
                            
Hoje é um dia especial, o seu aniversário! 🥳

E a gente não poderia deixar essa data passar em branco. 💛

Desejamos que o seu novo ciclo seja leve, feliz e cheio de motivos para sorrir. Que não faltem saúde, conquistas, momentos inesquecíveis e pessoas que façam seus dias ainda mais especiais.

Mais do que celebrar uma data, queremos celebrar você e agradecer por fazer parte da nossa história. 
Aproveite cada momento do seu dia, receba todo o carinho que merece e celebre muito!

Feliz aniversário! 🥳✨"""
                            from urllib.parse import quote
                            return f"https://api.whatsapp.com/send?phone={num}&text={quote(msg)}"
                        return None
                    
                    df_nivers['Ação'] = df_nivers.apply(lambda row: gerar_link_wpp(row['telefone'], row['nome']), axis=1)
                    df_nivers = df_nivers.rename(columns={'nome': 'Cliente', 'telefone': 'Contato'})
                    
                    st.dataframe(
                        df_nivers[['Cliente', 'Aniversário', 'Contato', 'Ação']],
                        column_config={
                            "Ação": st.column_config.LinkColumn("📱 Enviar", display_text="Mensagem")
                        },
                        hide_index=True, 
                        use_container_width=True
                    )
                else:
                    st.info("Nenhuma cliente faz aniversário neste período.")
                
            st.markdown("---")
            
            # --- RANKING DE ENGAJAMENTO (Mesmo filtro de data) ---
            st.markdown("### 🏆 Top Clientes (Maior LTV no Período)")
            query_crm_vendas = """
                SELECT 
                    c.nome AS "Cliente", 
                    COUNT(DISTINCT v.codigo_venda) AS "Qtd. Compras",
                    SUM(v.quantidade) AS "Produtos comprados",
                    SUM(v.valor_total) AS "Total Gasto (R$)"
                FROM vendas v
                JOIN clientes c ON v.cliente_id = c.id
                WHERE v.empresa_id = %s 
                  AND TO_DATE(v.data_venda, 'DD/MM/YYYY') >= %s 
                  AND TO_DATE(v.data_venda, 'DD/MM/YYYY') <= %s
                GROUP BY c.id, c.nome
                ORDER BY "Total Gasto (R$)" DESC
                LIMIT 5
            """
            df_ranking_crm = carregar_dados_cached(query_crm_vendas, (emp_id, d_ini, d_fim))
            
            if not df_ranking_crm.empty:
                df_ranking_crm['Total Gasto (R$)'] = df_ranking_crm['Total Gasto (R$)'].apply(lambda x: f"R$ {x:,.2f}".replace('.', 'v').replace(',', '.').replace('v', ','))
                st.dataframe(df_ranking_crm, hide_index=True, use_container_width=True)
            else:
                st.warning("Nenhuma venda para gerar o ranking neste período.")
                
        with aba_hist:
            st.subheader("📜 Histórico Geral e Faturamento")
            
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
            df_todas_vendas = carregar_dados_cached(query_todas_vendas, (emp_id,))
            
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
                                        conn.commit(); devolver_conexao(conn); st.success("Atualizado!"); limpar_cache(); st.rerun()
                            else: devolver_conexao(conn)

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
                                    conn.commit(); devolver_conexao(conn); st.success("Cancelado!"); limpar_cache(); st.rerun()
                                else: devolver_conexao(conn); st.error("Erro.")
                
                #st.markdown("---")

                # ==========================================================
                # EXPANDER DO RECIBO DO WHATSAPP
                # ==========================================================
                with st.expander("📲 Enviar Recibo via WhatsApp", expanded=False):
                    
                    # 1. Filtramos o DataFrame para mostrar cada venda apenas UMA VEZ no selectbox
                    df_vendas_unicas = df_todas_vendas.drop_duplicates(subset=['Nº Venda'])
                    opcoes_recibo = df_vendas_unicas.apply(lambda x: f"Venda Nº {x['Nº Venda']} | Cliente: {x['Cliente']}", axis=1).tolist()
                    
                    venda_recibo_sel = st.selectbox("Selecione a venda para gerar o recibo", options=opcoes_recibo, key="sel_recibo")

                    if venda_recibo_sel:
                        # Extraímos o código da venda a partir do texto do selectbox
                        venda_id_recibo = int(venda_recibo_sel.split("Nº ")[1].split(" |")[0])
                        
                        conn = conectar_banco()
                        cursor = conn.cursor()
                        
                        # 2. Buscamos TODOS os itens daquele codigo_venda
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
                        devolver_conexao(conn)

                        if dados_recibo:
                            tel = dados_recibo[0][0]
                            nome_cli = dados_recibo[0][1]
                            data_v = dados_recibo[0][2]
                            
                            v_ent = dados_recibo[0][6] or 0
                            v_rest = dados_recibo[0][7] or 0
                            forma_pag = dados_recibo[0][8]
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
                                valor_parc = total_venda / qtd_parc
                                valor_parc_str = f"{valor_parc:.2f}".replace('.', ',')
                                msg += f"💳 *Parcelamento:* {qtd_parc}x de R$ {valor_parc_str}\n"
                            else:
                                msg += f"💳 *Forma de Pagto:* {forma_pag}\n"
                                
                            msg += "\nMuito obrigada pela preferência! ✨"
                            
                            st.text_area("Pré-visualização da Mensagem:", value=msg, height=250, disabled=True)

                            if tel:
                                import urllib.parse
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
                
                # ==========================================================
                # NOVA SEÇÃO: FILTROS UNIFICADOS E MÉTRICAS DE CLIENTE
                # ==========================================================
                df_todas_vendas['Data_Filtro'] = pd.to_datetime(df_todas_vendas['Data'], dayfirst=True, errors='coerce').dt.date
                data_min = df_todas_vendas['Data_Filtro'].min() if not pd.isna(df_todas_vendas['Data_Filtro'].min()) else date.today()
                data_max = df_todas_vendas['Data_Filtro'].max() if not pd.isna(df_todas_vendas['Data_Filtro'].max()) else date.today()
                
                st.subheader("🔍 Filtros de Busca")
                col_data1, col_data2, col_cli = st.columns([1, 1, 2])
                
                data_inicio = col_data1.date_input("Data Inicial", value=data_min, format="DD/MM/YYYY")
                data_fim = col_data2.date_input("Data Final", value=data_max, format="DD/MM/YYYY")
                
                # Lista de clientes únicos para o filtro
                lista_clientes_hist = ["Todos os Clientes"] + sorted(df_todas_vendas['Cliente'].dropna().unique().tolist())
                cliente_selecionado = col_cli.selectbox("Filtrar por Cliente", options=lista_clientes_hist)
                
                # Aplicação dos Filtros (Data + Cliente)
                mask_data = (df_todas_vendas['Data_Filtro'] >= data_inicio) & (df_todas_vendas['Data_Filtro'] <= data_fim)
                df_filtrado = df_todas_vendas.loc[mask_data].copy()
                
                if cliente_selecionado != "Todos os Clientes":
                    df_filtrado = df_filtrado[df_filtrado['Cliente'] == cliente_selecionado]
                
                df_filtrado = df_filtrado.drop(columns=['Data_Filtro'], errors='ignore')
                
                if not df_filtrado.empty:
                    # Se um cliente específico for selecionado, mostra as métricas de LTV dele
                    if cliente_selecionado != "Todos os Clientes":
                        total_comprado = df_filtrado['Total (R$)'].sum()
                        qtd_compras = df_filtrado['Nº Venda'].nunique()
                        ticket_medio = total_comprado / qtd_compras if qtd_compras > 0 else 0
                        
                        st.markdown(f"**👤 Resumo do Cliente: {cliente_selecionado} (no período)**")
                        c1, c2, c3 = st.columns(3)
                        c1.metric("🛒 Total Comprado", f"R$ {total_comprado:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                        c2.metric("📦 Qtd. de Pedidos", f"{qtd_compras}")
                        c3.metric("🎯 Ticket Médio", f"R$ {ticket_medio:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                        st.markdown("<br>", unsafe_allow_html=True)

                    colunas_exibicao = ['Nº Venda', 'Cliente', 'Produto', 'Qtd', 'Preço Tabela', 'Desconto Unit', 'Total (R$)', 'Entrada (R$)', 'Restante (R$)', 'Data', 'Pagamento', 'Prazo']
                    st.dataframe(df_filtrado[colunas_exibicao], use_container_width=True, hide_index=True)
                    
                    st.markdown("### 📊 Resumo Geral do Filtro")
                    
                    # Trocamos para 3 colunas e removemos a métrica de "A Receber"
                    col_res1, col_res2, col_res3 = st.columns(3)
                    
                    col_res1.metric("💰 Faturamento", f"R$ {df_filtrado['Total (R$)'].sum():,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                    col_res2.metric("🛒 Vendas", f"{df_filtrado['Nº Venda'].nunique()}")
                    col_res3.metric("🧴 Produtos", f"{df_filtrado['Qtd'].sum()}")
                else: 
                    st.warning("Nenhuma venda encontrada para este filtro.")
            else: 
                st.info("Nenhuma venda registrada.")

        # --- NOVA ABA: ALERTAS DE ESTOQUE ---
        with aba_alertas:
            st.markdown("### 📦 Alertas de Reposição de Estoque")
            
            df_estoque = carregar_dados_cached("""
                SELECT 
                    referencia AS "Ref.", 
                    nome AS "Produto", 
                    marca AS "Marca", 
                    categoria AS "Categoria", 
                    quantidade AS "Qtd Atual"
                FROM produtos
                WHERE empresa_id = %s
                ORDER BY quantidade ASC
            """, (emp_id,))
            
            if not df_estoque.empty:
                limite_critico = 5
                
                df_zerados = df_estoque[df_estoque['Qtd Atual'] == 0]
                df_alerta = df_estoque[(df_estoque['Qtd Atual'] > 0) & (df_estoque['Qtd Atual'] <= limite_critico)]
                qtd_saudavel = len(df_estoque) - len(df_zerados) - len(df_alerta)
                
                col_e1, col_e2, col_e3 = st.columns(3)
                col_e1.metric("🔴 Estoque Zerado", f"{len(df_zerados)} itens")
                col_e2.metric("🟡 Estoque Crítico", f"{len(df_alerta)} itens", help=f"Produtos com {limite_critico} unidades ou menos.")
                col_e3.metric("🟢 Estoque Saudável", f"{qtd_saudavel} itens")
                
                st.markdown("---")
                
                if not df_zerados.empty or not df_alerta.empty:
                    st.subheader("⚠️ Produtos que precisam de reposição")
                    
                    df_criticos_total = pd.concat([df_zerados, df_alerta])
                    
                    def colorir_estoque(val):
                        if pd.isna(val):
                            return ''
                        if val == 0:
                            return 'color: white; background-color: #ff4b4b; font-weight: bold;'
                        elif val <= limite_critico:
                            return 'color: black; background-color: #ffc107; font-weight: bold;'
                        return ''
                    
                    st.dataframe(
                        df_criticos_total.style.map(colorir_estoque, subset=['Qtd Atual']),
                        use_container_width=True,
                        hide_index=True
                    )
                else:
                    st.success("🎉 Tudo certo! Nenhum cosmético com estoque crítico ou zerado no momento.")
            else:
                st.info("Nenhum produto cadastrado.")
                
        # ==========================================
        # NOVA TELA: VISÃO APP (Acompanhamento Rápido)
        # ==========================================
        with aba_app:
            st.markdown("### 📱 Acompanhamento Diário")
            
            from datetime import date
            hoje = date.today()
            
            meses_nomes = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
            
            # Cria uma lista combinada de Mês e Ano (Ex: "Maio de 2026") para ficar idêntico ao app
            opcoes_periodo = []
            for ano in range(2024, hoje.year + 2):
                for m in range(1, 13):
                    opcoes_periodo.append(f"{meses_nomes[m-1]} de {ano}")
            
            # Encontra o mês atual para deixar selecionado por padrão
            periodo_atual = f"{meses_nomes[hoje.month-1]} de {hoje.year}"
            try:
                idx_atual = opcoes_periodo.index(periodo_atual)
            except ValueError:
                idx_atual = 0
            
            # Único campo de seleção (Fica perfeito e limpo no celular)
            periodo_sel = st.selectbox("Período:", opcoes_periodo, index=idx_atual)
            
            # O sistema pega a frase "Maio de 2026" e separa os números para a consulta SQL
            mes_str, ano_str = periodo_sel.split(" de ")
            mes_num = meses_nomes.index(mes_str) + 1
            ano_sel = int(ano_str)
            
            # Consulta SQL Otimizada: Usando SUM para somar todos os itens do carrinho corretamente
            query_app = """
                SELECT 
                    v.codigo_venda,
                    MAX(v.data_venda) AS "Data",
                    MAX(c.nome) AS "Cliente",
                    SUM(v.valor_total) AS "Valor Total (R$)",
                    CASE 
                        WHEN (SELECT COUNT(id) FROM contas_receber WHERE venda_codigo = v.codigo_venda AND status = 'Pendente') = 0 THEN '🟢 QUITADO'
                        WHEN (SELECT COUNT(id) FROM contas_receber WHERE venda_codigo = v.codigo_venda AND status = 'Pendente' AND TO_DATE(data_vencimento, 'DD/MM/YYYY') < CURRENT_DATE) > 0 THEN '🔴 ATRASADO'
                        ELSE '🔵 PENDENTE'
                    END AS "Status"
                FROM vendas v
                LEFT JOIN clientes c ON v.cliente_id = c.id
                WHERE EXTRACT(MONTH FROM TO_DATE(v.data_venda, 'DD/MM/YYYY')) = %s 
                  AND EXTRACT(YEAR FROM TO_DATE(v.data_venda, 'DD/MM/YYYY')) = %s
                  AND v.empresa_id = %s
                GROUP BY v.codigo_venda
                ORDER BY TO_DATE(MAX(v.data_venda), 'DD/MM/YYYY') DESC
            """
            
            # Aqui fazemos a busca (se der erro de data, ajuste o cast de data_venda no SQL)
            df_app = carregar_dados_cached(query_app, (mes_num, ano_sel, emp_id))
            
            if not df_app.empty:
                # Calculadora do rodapé
                total_mes = df_app['Valor Total (R$)'].sum()
                
                # ==========================================
                # OTIMIZAÇÃO VISUAL PARA TELA DE CELULAR
                # ==========================================
                # Criamos um "dataframe espelho" super enxuto com apenas 2 colunas
                df_mobile = pd.DataFrame()
                
                # 1ª Coluna: Junta o Nome e a Data (ex: Jaqueline Corpvs • 31/05)
                df_mobile['Cliente / Data'] = df_app['Cliente'] + " • " + df_app['Data'].str[0:5]
                
                # 2ª Coluna: Mapeamento alterado para Amarelo (🟡) no Pendente
                status_map = {
                    '🟢 QUITADO': '🟢 Pago',
                    '🔴 ATRASADO': '🔴 Atraso',
                    '🔵 PENDENTE': '🟡 Pend.'
                }
                status_curto = df_app['Status'].map(status_map).fillna(df_app['Status'])
                valores_br = df_app['Valor Total (R$)'].apply(lambda x: f"R$ {x:,.2f}".replace('.', 'v').replace(',', '.').replace('v', ','))
                
                # INVERSÃO APLICADA: Valor vem antes do Status agora
                df_mobile['Valor / Status'] = valores_br + " | " + status_curto
                
                # --- EXIBIÇÃO ---
                st.markdown("Selecione uma venda abaixo para abrir o painel de recebimento:")
                
                # Renderiza a tabela de 2 colunas atualizada
                evento_clique = st.dataframe(
                    df_mobile,
                    use_container_width=True,
                    hide_index=True,
                    selection_mode="single-row",
                    on_select="rerun"
                )
                # Rodapé no estilo do App
                total_formatado = f"{total_mes:,.2f}".replace(".", "v").replace(",", ".").replace("v", ",")
                st.markdown(f"""
                    <div style="background-color: #d11181; padding: 15px; border-radius: 10px; text-align: center; color: white; font-size: 20px; font-weight: bold; margin-top: 10px;">
                        Total do Mês: R$ {total_formatado}
                    </div>
                """, unsafe_allow_html=True)
                
                # ---------------------------------------------------------
                # A MÁGICA DO CLIQUE: Captura a seleção e muda de tela
                # ---------------------------------------------------------
                if evento_clique and len(evento_clique["selection"]["rows"]) > 0:
                    # Descobre qual linha o usuário clicou na tela
                    linha_clicada = evento_clique["selection"]["rows"][0]
                    
                    # Puxa o código real da venda diretamente do DataFrame original (df_app)
                    venda_id = int(df_app.iloc[linha_clicada]['codigo_venda'])
                    
                    # Guarda as instruções na memória temporária do sistema (Session State)
                    st.session_state['venda_editando'] = venda_id
                    st.session_state['abrir_expander_recebimento'] = True
                    
                    # Altera o valor do menu lateral para forçar a mudança de tela
                    st.session_state['forcar_menu'] = "💰 Financeiro" 
                    
                    # Recarrega o sistema instantaneamente já na nova tela
                    st.rerun()
            else:
                st.info(f"Nenhuma venda registrada em {periodo_sel}.")
                
    # ==========================================
    # MÓDULO 2: CADASTROS (Produtos, Categorias, Clientes, Fornecedores)
    # ==========================================
    elif modulo == "🗂️ Cadastros":
        st.markdown("### 🗂️ Central de Cadastros")
        tab_prod, tab_serv, tab_cat, tab_cli, tab_for, tab_colab = st.tabs(["📦 Produtos", "💇‍♀️ Serviços", "🏷️ Categorias", "👥 Clientes", "🤝 Fornecedores", "👤 Equipe"])
        # ==========================================
        # ABA: GERENCIAR PRODUTOS (APENAS FÍSICOS)
        # ==========================================
        with tab_prod:
            # --- Buscando apenas PRODUTOS FÍSICOS ('P') ---
            df_p = carregar_dados_cached("SELECT * FROM produtos WHERE empresa_id=%s AND tipo='P' ORDER BY nome", (emp_id,))
            df_c = carregar_dados_cached("SELECT nome FROM categorias WHERE empresa_id=%s ORDER BY nome", (emp_id,))
            lista_cat = df_c['nome'].tolist() if not df_c.empty else ["Geral"]
            
            # --- EXPANDER 1: NOVO PRODUTO ---
            with st.expander("➕ Novo Produto Físico"):
                with st.form("f_novo_p", clear_on_submit=True):
                    
                    st.markdown("**Classificação do Produto**")
                    # O Grande Diferencial: Definição da Classe
                    classe_desc = st.radio(
                        "Qual a finalidade deste produto?", 
                        ["Venda / Comercialização", "Insumo / Consumo Interno"], 
                        horizontal=True,
                        help="Venda: Produtos expostos para a cliente comprar. Insumo: Produtos usados nos procedimentos do salão."
                    )
                    classe_letra = 'Venda' if classe_desc == "Venda / Comercialização" else 'Insumo'
                    
                    st.markdown("---")
                    st.markdown("**Informações Básicas**")
                    c1, c2 = st.columns(2)
                    n_p = c1.text_input("Nome do Produto")
                    ref_p = c2.text_input("Referência / Código Interno", placeholder="Opcional")
                    
                    c3, c4 = st.columns(2)
                    q_p = c3.number_input("Qtd Inicial em Estoque", min_value=0, step=1)
                    m_p = c4.text_input("Marca / Linha", placeholder="Ex: Mary Kay, D'Grava")
                    
                    st.markdown("**Finanças e Precificação**")
                    c5, c6, c7 = st.columns(3)
                    
                    # Se for insumo, o preço de venda deixa de ser obrigatório
                    custo_p = c5.number_input("Preço de Custo (R$)", min_value=0.0, format="%.2f")
                    markup_p = c6.number_input("Markup (%)", min_value=0.0, format="%.2f", disabled=(classe_letra == 'Insumo'), help="Desabilitado para Insumos.")
                    v_p = c7.number_input("Preço de Venda (R$)", min_value=0.0, format="%.2f", disabled=(classe_letra == 'Insumo'), help="Insumos não possuem preço de venda.")
                    
                    cat_p = st.selectbox("Categoria", lista_cat)
                    
                    if st.form_submit_button("💾 Salvar Cadastro"):
                        if not n_p:
                            st.warning("O nome do produto é obrigatório.")
                        else:
                            conn = conectar_banco()
                            conn.cursor().execute(
                                """INSERT INTO produtos 
                                (nome, quantidade, valor, preco_custo, markup, marca, categoria, empresa_id, referencia, tipo, classe) 
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'P',%s)""", 
                                (n_p, q_p, v_p, custo_p, markup_p, m_p, cat_p, emp_id, ref_p, classe_letra)
                            )
                            conn.commit()
                            devolver_conexao(conn)
                            st.success(f"Produto de {classe_letra} cadastrado com sucesso!")
                            limpar_cache()
                            st.rerun()

            # --- EXPANDER 2: EDITAR PRODUTO ---
            with st.expander("✏️ Editar Produto"):
                if not df_p.empty:
                    opcoes_edicao = df_p['id'].tolist()
                    
                    def formatar_produto(prod_id):
                        linha = df_p[df_p['id'] == prod_id].iloc[0]
                        ref = f" (Ref: {linha['referencia']})" if linha['referencia'] else ""
                        classe_tag = "[INVENTÁRIO]" if linha.get('classe', 'Venda') == 'Insumo' else "[REVENDA]"
                        return f"{classe_tag} {linha['nome']}{ref}"
                        
                    prod_id_selecionado = st.selectbox("Selecione o produto que deseja atualizar:", opcoes_edicao, format_func=formatar_produto)
                    
                    if prod_id_selecionado:
                        p_atual = df_p[df_p['id'] == prod_id_selecionado].iloc[0]
                        classe_atual = p_atual.get('classe', 'Venda')
                        
                        # Trocado st.form por st.container para que os campos desabilitem na mesma hora
                        with st.container(border=True):
                            
                            index_classe_atual = 1 if classe_atual == 'Insumo' else 0
                            e_classe_desc = st.selectbox("Finalidade do Produto:", ["Venda / Comercialização", "Insumo / Consumo Interno"], index=index_classe_atual)
                            e_classe_letra = 'Venda' if e_classe_desc == "Venda / Comercialização" else 'Insumo'
                            
                            c1, c2 = st.columns(2)
                            e_nome = c1.text_input("Nome", value=p_atual['nome'])
                            e_ref = c2.text_input("Referência", value=p_atual['referencia'] if p_atual['referencia'] else "")
                            
                            c3, c4 = st.columns(2)
                            e_qtd = c3.number_input("Quantidade em Estoque Atualizada", min_value=0, step=1, value=int(p_atual['quantidade']))
                            e_marca = c4.text_input("Marca / Linha", value=p_atual['marca'])
                            
                            st.markdown("**Finanças e Precificação**")
                            c5, c6, c7 = st.columns(3)
                            
                            val_custo = float(p_atual['preco_custo']) if 'preco_custo' in p_atual and pd.notnull(p_atual['preco_custo']) else 0.0
                            val_markup = float(p_atual['markup']) if 'markup' in p_atual and pd.notnull(p_atual['markup']) else 0.0
                            
                            e_custo = c5.number_input("Preço de Custo (R$)", min_value=0.0, format="%.2f", value=val_custo)
                            e_markup = c6.number_input("Markup (%)", min_value=0.0, format="%.2f", value=val_markup, disabled=(e_classe_letra == 'Insumo'))
                            e_valor = c7.number_input("Preço de Venda (R$)", min_value=0.0, format="%.2f", value=float(p_atual['valor']), disabled=(e_classe_letra == 'Insumo'))
                            
                            try:
                                cat_index = lista_cat.index(p_atual['categoria'])
                            except ValueError:
                                cat_index = 0
                                
                            e_cat = st.selectbox("Categoria", lista_cat, index=cat_index)
                            
                            st.markdown("---")
                            # Botões lado a lado
                            col_btn_salvar, col_btn_excluir = st.columns(2)
                            
                            if col_btn_salvar.button("💾 Salvar Alterações", type="primary", use_container_width=True):
                                conn = conectar_banco()
                                conn.cursor().execute("""
                                    UPDATE produtos 
                                    SET nome=%s, quantidade=%s, valor=%s, preco_custo=%s, markup=%s, marca=%s, categoria=%s, referencia=%s, classe=%s 
                                    WHERE id=%s AND empresa_id=%s
                                """, (e_nome, e_qtd, e_valor, e_custo, e_markup, e_marca, e_cat, e_ref, e_classe_letra, int(prod_id_selecionado), emp_id))
                                conn.commit()
                                devolver_conexao(conn)
                                
                                st.success("Cadastro atualizado com sucesso!")
                                limpar_cache()
                                st.rerun()
                                
                            if col_btn_excluir.button("🗑️ Excluir Produto", use_container_width=True):
                                try:
                                    conn = conectar_banco()
                                    conn.cursor().execute("DELETE FROM produtos WHERE id=%s AND empresa_id=%s", (int(prod_id_selecionado), emp_id))
                                    conn.commit()
                                    devolver_conexao(conn)
                                    
                                    st.success("✅ Produto excluído com sucesso!")
                                    limpar_cache()
                                    st.rerun()
                                except Exception as e:
                                    st.error("⚠️ **Não é possível excluir!** Este produto já possui histórico de vendas ou foi utilizado em serviços vinculados ao seu financeiro.")
                                    if 'conn' in locals(): devolver_conexao(conn)
                else:
                    st.info("Não há produtos cadastrados para editar.")

            # --- EXPANDER 3: MONTAGEM DE KITS PROMOCIONAIS ---
            with st.expander("🎁 Montar Kit Promocional"):
                # Kits promocionais só fazem sentido com produtos de Venda
                df_produtos_base = df_p[(df_p['quantidade'] > 0) & (df_p.get('classe', 'Venda') == 'Venda')] if not df_p.empty else pd.DataFrame()
                
                if not df_produtos_base.empty:
                    st.caption("Monte combos unindo produtos de revenda para atrair mais clientes.")
                    
                    df_produtos_base['display_kit'] = df_produtos_base.apply(lambda x: f"{x['nome']} (Estoque: {int(x['quantidade'])} | R$ {float(x['valor']):.2f})", axis=1)
                    opcoes_kit = df_produtos_base['display_kit'].tolist()
                    
                    with st.form("form_montar_kit", clear_on_submit=True):
                        st.markdown("**1. Selecione os produtos que farão parte do Kit**")
                        itens_selecionados = st.multiselect("Produtos Base:", options=opcoes_kit, placeholder="Selecione dois ou mais produtos...")
                        
                        st.markdown("**2. Detalhes do Novo Kit**")
                        c1, c2 = st.columns(2)
                        nome_kit = c1.text_input("Nome do Kit", placeholder="Ex: Combo Dia das Mães")
                        qtd_kit = c2.number_input("Quantidade de Kits a montar", min_value=1, step=1, help="Esta quantidade será descontada dos produtos base.")
                        
                        c3, c4 = st.columns(2)
                        preco_sugerido = 0.0
                        
                        # Calcula preço sugerido (soma dos valores originais)
                        if itens_selecionados:
                            for item_str in itens_selecionados:
                                # Extrai o ID/Valor baseado no texto selecionado
                                idx = opcoes_kit.index(item_str)
                                p_valor = float(df_produtos_base.iloc[idx]['valor'])
                                preco_sugerido += p_valor
                        
                        st.info(f"💡 Valor Total Original (Sem Desconto): **R$ {preco_sugerido:.2f}**".replace('.', ','))
                        
                        preco_kit = c3.number_input("Preço de Venda do Kit (R$)", min_value=0.0, format="%.2f", value=preco_sugerido)
                        cat_kit = c4.selectbox("Categoria", lista_cat)
                        
                        if st.form_submit_button("📦 Criar Kit Promocional", type="primary"):
                            if len(itens_selecionados) < 2:
                                st.warning("Um kit precisa ter pelo menos 2 produtos.")
                            elif not nome_kit:
                                st.warning("Dê um nome para o seu Kit.")
                            else:
                                erro_estoque = False
                                ids_para_abater = []
                                
                                # Verifica se há estoque suficiente para montar a quantidade de kits desejada
                                for item_str in itens_selecionados:
                                    idx = opcoes_kit.index(item_str)
                                    p_id = int(df_produtos_base.iloc[idx]['id'])
                                    p_estoque = int(df_produtos_base.iloc[idx]['quantidade'])
                                    p_nome = df_produtos_base.iloc[idx]['nome']
                                    
                                    if p_estoque < qtd_kit:
                                        st.error(f"Estoque insuficiente de '{p_nome}' para montar {qtd_kit} kits. (Disponível: {p_estoque})")
                                        erro_estoque = True
                                        break
                                    else:
                                        ids_para_abater.append(p_id)
                                
                                if not erro_estoque:
                                    conn = conectar_banco()
                                    cur = conn.cursor()
                                    
                                    try:
                                        # 1. Cria o Kit como um NOVO produto (da classe Venda)
                                        custo_zerado = 0.0
                                        markup_zerado = 0.0
                                        cur.execute("""
                                            INSERT INTO produtos (nome, quantidade, valor, preco_custo, markup, marca, categoria, empresa_id, tipo, classe) 
                                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'P', 'Venda')
                                        """, (f"[KIT] {nome_kit}", int(qtd_kit), float(preco_kit), custo_zerado, markup_zerado, "Kit Promocional", cat_kit, int(emp_id)))
                                        
                                        # 2. Dá baixa no estoque dos produtos individuais usados para montar os kits
                                        for p_id in ids_para_abater:
                                            cur.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE id = %s", (int(qtd_kit), p_id))
                                            
                                        conn.commit()
                                        st.success(f"Kit '{nome_kit}' criado com sucesso! Estoque dos itens base foi atualizado.")
                                        limpar_cache()
                                        st.rerun()
                                        
                                    except Exception as e:
                                        st.error(f"Erro ao gerar kit: {e}")
                                    finally:
                                        devolver_conexao(conn)
                else:
                    st.info("Não há produtos comerciais de venda com estoque disponível para montar kits.")

            # --- PAINEL DE FILTROS E EXIBIÇÃO DA TABELA ---
            if not df_p.empty:
                st.markdown("---")
                col_f_nome, col_f_cat, col_f_classe = st.columns(3)
                
                classe_filtro = col_f_classe.selectbox("📦 Filtrar por Finalidade:", ["🛒 Todos os Produtos", "🛍️ Apenas Venda/Revenda", "🧴 Apenas Insumos/Consumo"])
                
                # Aplica filtro de classe
                if classe_filtro == "🛍️ Apenas Venda/Revenda":
                    df_filtrado = df_p[df_p.get('classe', 'Venda') == 'Venda'].copy()
                elif classe_filtro == "🧴 Apenas Insumos/Consumo":
                    df_filtrado = df_p[df_p.get('classe', 'Venda') == 'Insumo'].copy()
                else:
                    df_filtrado = df_p.copy()
                
                opcoes_cat = ["📦 Todas as Categorias"] + lista_cat
                cat_selecionada = col_f_cat.selectbox("📑 Filtrar por Categoria:", options=opcoes_cat)
                
                if cat_selecionada != "📦 Todas as Categorias":
                    df_filtrado = df_filtrado[df_filtrado['categoria'] == cat_selecionada]
                
                if not df_filtrado.empty:
                    df_filtrado['display_pesquisa'] = df_filtrado.apply(lambda x: f"{x['nome']} (Estoque: {int(x['quantidade'])})", axis=1)
                    opcoes_busca = ["🔍 Todos os Itens listados"] + df_filtrado['display_pesquisa'].tolist()
                    prod_busca = col_f_nome.selectbox("🔍 Pesquise o Produto:", options=opcoes_busca)
                    
                    if prod_busca != "🔍 Todos os Itens listados":
                        df_final = df_filtrado[df_filtrado['display_pesquisa'] == prod_busca]
                    else:
                        df_final = df_filtrado
                        
                    if not df_final.empty:
                        # Remove colunas de controle interno para a visualização ficar limpa
                        df_exibicao = df_final.drop(columns=['empresa_id', 'display_pesquisa', 'tipo'], errors='ignore')
                        
                        st.dataframe(df_exibicao, use_container_width=True, hide_index=True)
                        
                        # --- NOVAS MÉTRICAS DE CAPITAL DE ESTOQUE ---
                        st.markdown("### 💰 Resumo Financeiro do Estoque")
                        m1, m2 = st.columns(2)
                        
                        # 1. Capital de Venda (Potencial de Faturamento usando Preço de Venda)
                        df_venda_soma = df_final[df_final.get('classe', 'Venda') == 'Venda']
                        val_est_venda = (df_venda_soma['quantidade'] * df_venda_soma['valor']).sum()
                        
                        # 2. Capital de Insumo (Dinheiro parado usando Preço de Custo)
                        df_insumo_soma = df_final[df_final.get('classe', 'Venda') == 'Insumo']
                        
                        # Tratamento de segurança caso o banco tenha produtos antigos sem custo preenchido
                        if not df_insumo_soma.empty:
                            df_insumo_soma['custo_seguro'] = df_insumo_soma['preco_custo'].fillna(0).astype(float)
                            val_est_insumo = (df_insumo_soma['quantidade'] * df_insumo_soma['custo_seguro']).sum()
                        else:
                            val_est_insumo = 0.0
                            
                        m1.metric("🛒 Potencial de Faturamento (Revenda)", f"R$ {val_est_venda:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                        m2.metric("🧴 Capital Imobilizado (Insumos)", f"R$ {val_est_insumo:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                else:
                    st.info("Nenhum produto encontrado com os filtros atuais.")
                    
        # ==========================================
        # ABA: GERENCIAR SERVIÇOS (APENAS SERVIÇOS)
        # ==========================================
        with tab_serv:
            #st.markdown("### 🛠️ Gestão de Serviços Prestados")
            
            # --- Buscando apenas SERVIÇOS ('S') com todas as colunas ---
            df_s = carregar_dados_cached("SELECT * FROM produtos WHERE empresa_id=%s AND tipo='S' ORDER BY nome", (emp_id,))
            
            # Carregando categorias
            df_c_serv = carregar_dados_cached("SELECT nome FROM categorias WHERE empresa_id=%s ORDER BY nome", (emp_id,))
            lista_cat_serv = df_c_serv['nome'].tolist() if not df_c_serv.empty else ["Geral"]

            # --- EXPANDER 1: NOVO SERVIÇO ---
            with st.expander("➕ Novo Serviço"):
                with st.form("f_novo_s", clear_on_submit=True):
                    
                    st.markdown("**Informações Básicas**")
                    c1, c2 = st.columns(2)
                    n_s = c1.text_input("Nome do Serviço")
                    ref_s = c2.text_input("Referência / Código Interno", placeholder="Ex: SRV-001")
                    
                    c3, c4 = st.columns(2)
                    v_s = c3.number_input("Valor Padrão do Serviço (R$)", min_value=0.0, format="%.2f")
                    cat_s = c4.selectbox("Categoria", lista_cat_serv)
                    
                    st.markdown("**Regras de Atendimento e Repasse**")
                    c5, c6 = st.columns(2)
                    t_s = c5.number_input("Tempo de Execução (Minutos)", min_value=0, step=15, help="Tempo bloqueado na agenda do profissional.")
                    com_s = c6.number_input("Comissão do Colaborador (%)", min_value=0.0, format="%.2f", help="Percentual repassado a quem executa o serviço.")
                    
                    if st.form_submit_button("💾 Salvar Serviço"):
                        if not n_s:
                            st.warning("O nome do serviço é obrigatório.")
                        else:
                            conn = conectar_banco()
                            conn.cursor().execute(
                                """INSERT INTO produtos 
                                (nome, valor, categoria, empresa_id, referencia, tipo, quantidade, preco_custo, markup, marca, tempo_minutos, comissao_percentual) 
                                VALUES (%s,%s,%s,%s,%s,'S', 0, 0.0, 0.0, 'Serviço Próprio', %s, %s)""", 
                                (n_s, v_s, cat_s, emp_id, ref_s, t_s, com_s)
                            )
                            conn.commit()
                            devolver_conexao(conn)
                            st.success("Serviço cadastrado com sucesso!")
                            limpar_cache()
                            st.rerun()

            # --- EXPANDER 2: EDITAR SERVIÇO ---
            with st.expander("✏️ Editar Serviço"):
                if not df_s.empty:
                    opcoes_edicao_s = df_s['id'].tolist()
                    
                    def formatar_servico(serv_id):
                        linha = df_s[df_s['id'] == serv_id].iloc[0]
                        return f"{linha['nome']}"
                        
                    serv_id_selecionado = st.selectbox("Selecione o serviço que deseja atualizar:", opcoes_edicao_s, format_func=formatar_servico)
                    
                    if serv_id_selecionado:
                        s_atual = df_s[df_s['id'] == serv_id_selecionado].iloc[0]
                        
                        with st.form("f_edita_s", clear_on_submit=False):
                            st.markdown("**Informações Básicas**")
                            c1, c2 = st.columns(2)
                            e_nome_s = c1.text_input("Nome do Serviço", value=s_atual['nome'])
                            e_ref_s = c2.text_input("Referência", value=s_atual['referencia'] if s_atual['referencia'] else "")
                            
                            c3, c4 = st.columns(2)
                            e_valor_s = c3.number_input("Valor do Serviço (R$)", min_value=0.0, format="%.2f", value=float(s_atual['valor']))
                            
                            try:
                                cat_index_s = lista_cat_serv.index(s_atual['categoria'])
                            except ValueError:
                                cat_index_s = 0
                                
                            e_cat_s = c4.selectbox("Categoria", lista_cat_serv, index=cat_index_s)
                            
                            st.markdown("**Regras de Atendimento e Repasse**")
                            c5, c6 = st.columns(2)
                            
                            val_tempo = int(s_atual['tempo_minutos']) if 'tempo_minutos' in s_atual and pd.notnull(s_atual['tempo_minutos']) else 0
                            val_comissao = float(s_atual['comissao_percentual']) if 'comissao_percentual' in s_atual and pd.notnull(s_atual['comissao_percentual']) else 0.0
                            
                            e_tempo_s = c5.number_input("Tempo de Execução (Minutos)", min_value=0, step=15, value=val_tempo)
                            e_com_s = c6.number_input("Comissão do Colaborador (%)", min_value=0.0, format="%.2f", value=val_comissao)
                            
                            if st.form_submit_button("💾 Salvar Alterações"):
                                conn = conectar_banco()
                                conn.cursor().execute("""
                                    UPDATE produtos 
                                    SET nome=%s, valor=%s, categoria=%s, referencia=%s, tempo_minutos=%s, comissao_percentual=%s
                                    WHERE id=%s AND empresa_id=%s
                                """, (e_nome_s, e_valor_s, e_cat_s, e_ref_s, e_tempo_s, e_com_s, int(serv_id_selecionado), emp_id))
                                conn.commit()
                                devolver_conexao(conn)
                                
                                st.success("Serviço atualizado com sucesso!")
                                limpar_cache()
                                st.rerun()
                else:
                    st.info("Não há serviços cadastrados para editar.")

            # --- PAINEL DE EXIBIÇÃO DA TABELA ---
            if not df_s.empty:
                st.markdown("---")
                st.markdown("📋 **Lista de Serviços Prestados**")
                
                # Prepara o dataframe para exibição, ocultando as colunas inúteis para serviços
                df_exibicao_s = df_s.drop(columns=['empresa_id', 'tipo', 'quantidade', 'preco_custo', 'markup', 'marca'], errors='ignore')
                
                # Formatação de exibição rica
                if 'valor' in df_exibicao_s.columns:
                    df_exibicao_s['valor'] = df_exibicao_s['valor'].apply(lambda x: f"R$ {x:.2f}" if pd.notnull(x) else "R$ 0.00")
                if 'tempo_minutos' in df_exibicao_s.columns:
                    df_exibicao_s['tempo_minutos'] = df_exibicao_s['tempo_minutos'].apply(lambda x: f"{int(x)} min" if pd.notnull(x) else "0 min")
                if 'comissao_percentual' in df_exibicao_s.columns:
                    df_exibicao_s['comissao_percentual'] = df_exibicao_s['comissao_percentual'].apply(lambda x: f"{x:.2f}%" if pd.notnull(x) else "0.00%")
                    
                st.dataframe(df_exibicao_s, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhum serviço cadastrado ainda.")
                
        with tab_cat:
            c1, c2 = st.columns(2)
            with c1:
                cat_n = st.text_input("Nova Categoria")
                if st.button("Salvar Categoria"):
                    conn = conectar_banco(); conn.cursor().execute("INSERT INTO categorias (nome, empresa_id) VALUES (%s,%s)",(cat_n, emp_id)); conn.commit(); devolver_conexao(conn); limpar_cache(); st.rerun()
            with c2:
                cat_del = st.selectbox("Excluir:", lista_cat)
                if st.button("Remover", type="primary"):
                    conn = conectar_banco(); conn.cursor().execute("DELETE FROM categorias WHERE nome=%s AND empresa_id=%s",(cat_del, emp_id)); conn.commit(); devolver_conexao(conn); limpar_cache(); st.rerun()

        with tab_cli:
            #st.subheader("Gerenciamento de Clientes")
            
            from datetime import datetime
            import pytz

            # Força o sistema a usar o fuso horário correto
            fuso_local = pytz.timezone('America/Fortaleza')
            hoje_str = datetime.now(fuso_local).strftime("%d/%m")

            df_aniv = carregar_dados_cached("SELECT nome, telefone FROM clientes WHERE empresa_id=%s AND data_nascimento=%s", (emp_id, hoje_str))
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
                    nome_cli = col1.text_input("Nome do Cliente *")
                    nasc_cli = col2.text_input("Dia de Aniversário (DD/MM)", placeholder="Ex: 25/12", max_chars=5)
                    tel_cli = col3.text_input("Telefone")
                    
                    # --- NOVO CAMPO: Tipo de Cadastro (Padrão: Cliente) ---
                    tipo_cli_desc = st.selectbox("Tipo de Cadastro:", ["Cliente", "Consultora"], index=0)
                    tipo_cli_letra = 'C' if tipo_cli_desc == "Cliente" else 'T'
                    
                    if st.form_submit_button("Cadastrar Cliente") and nome_cli:
                        conn = conectar_banco()
                        # Adicionado a coluna 'tipo' e a variável 'tipo_cli_letra' no final do INSERT
                        conn.cursor().execute(
                            "INSERT INTO clientes (nome, data_nascimento, telefone, empresa_id, tipo) VALUES (%s, %s, %s, %s, %s)", 
                            (nome_cli, nasc_cli, tel_cli, emp_id, tipo_cli_letra)
                        )
                        conn.commit()
                        devolver_conexao(conn)
                        st.success(f"{tipo_cli_desc} cadastrado com sucesso!")
                        limpar_cache()
                        st.rerun()

            df_clientes = carregar_dados_cached("SELECT * FROM clientes WHERE empresa_id = %s ORDER BY nome", (emp_id,))
            
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
                        
                        # --- ADAPTAÇÃO: Carrega o tipo atual e monta o componente de edição ---
                        tipo_atual = cli_atual.get('tipo', 'C') # Garante o padrão 'C' se a coluna estiver nula
                        index_tipo = 0 if tipo_atual == 'C' else 1
                        
                        novo_tipo_desc = st.selectbox("Tipo de Cadastro:", ["Cliente", "Consultora"], index=index_tipo)
                        novo_tipo_letra = 'C' if novo_tipo_desc == "Cliente" else 'T'
                        
                        if st.form_submit_button("Salvar Alterações"):
                            conn = conectar_banco()
                            # Incluído o campo tipo=%s na query SQL e a variável na tupla de parâmetros
                            conn.cursor().execute(
                                "UPDATE clientes SET nome=%s, data_nascimento=%s, telefone=%s, tipo=%s WHERE id=%s AND empresa_id=%s", 
                                (novo_nome_cli, novo_nasc_cli, novo_tel_cli, novo_tipo_letra, cli_id, emp_id)
                            )
                            conn.commit()
                            devolver_conexao(conn)
                            st.success("Atualizado com sucesso!")
                            limpar_cache()
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
                            devolver_conexao(conn)
                            st.success("Excluído com sucesso!")
                            limpar_cache()
                            st.rerun()

            with sub_hist_cli:
                if not df_clientes.empty:
                    clientes_dict_hist = dict(zip(df_clientes['nome'], df_clientes['id']))
                    cli_hist_selecionado = st.selectbox("Selecione o Cliente", options=list(clientes_dict_hist.keys()), key="sel_hist_cli")
                    df_h = carregar_dados_cached("""
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
            #st.subheader("Gestão de Fornecedores")
            with st.expander("➕ Novo Fornecedor"):
                with st.form("f_for", clear_on_submit=True):
                    n_f = st.text_input("Razão Social / Nome")
                    c_f = st.text_input("CNPJ")
                    t_f = st.text_input("Telefone")
                    if st.form_submit_button("Salvar Fornecedor"):
                        conn = conectar_banco(); conn.cursor().execute("INSERT INTO fornecedores (nome, cnpj, telefone, empresa_id) VALUES (%s,%s,%s,%s)",(n_f, c_f, t_f, emp_id)); conn.commit(); devolver_conexao(conn); limpar_cache(); st.rerun()
            st.dataframe(carregar_dados_cached("SELECT nome, cnpj, telefone FROM fornecedores WHERE empresa_id=%s ORDER BY nome",(emp_id,)), use_container_width=True)

        # ==========================================
        # ABA: GERENCIAR COLABORADORES
        # ==========================================
        with tab_colab:
            st.markdown("### 👤 Equipe e Profissionais")
            
            # Carrega a lista atual de colaboradores
            df_colab = carregar_dados_cached("SELECT id, nome, cargo, telefone, ativo FROM colaboradores WHERE empresa_id=%s ORDER BY nome", (emp_id,))
            
            # --- EXPANDER 1: NOVO COLABORADOR ---
            with st.expander("➕ Cadastrar Novo Colaborador"):
                with st.form("form_novo_colab", clear_on_submit=True):
                    c1, c2 = st.columns(2)
                    nome_c = c1.text_input("Nome Completo *")
                    cargo_c = c2.text_input("Cargo / Especialidade", placeholder="Ex: Cabeleireira, Maquiadora...")
                    
                    c3, c4 = st.columns(2)
                    tel_c = c3.text_input("WhatsApp / Telefone", placeholder="(XX) 9XXXX-XXXX")
                    status_c = c4.selectbox("Status Inicial", ["Ativo", "Inativo"])
                    
                    st.markdown("---")
                    if st.form_submit_button("💾 Salvar Colaborador", type="primary"):
                        if not nome_c:
                            st.warning("O nome do colaborador é obrigatório!")
                        else:
                            is_ativo = True if status_c == "Ativo" else False
                            
                            conn = conectar_banco()
                            conn.cursor().execute("""
                                INSERT INTO colaboradores (nome, cargo, telefone, ativo, empresa_id) 
                                VALUES (%s, %s, %s, %s, %s)
                            """, (nome_c, cargo_c, tel_c, is_ativo, emp_id))
                            conn.commit()
                            devolver_conexao(conn)
                            
                            st.success(f"Colaborador(a) {nome_c} cadastrado(a) com sucesso!")
                            limpar_cache()
                            st.rerun()

            # --- EXPANDER 2: EDITAR COLABORADOR ---
            with st.expander("✏️ Editar Cadastro de Colaborador"):
                if not df_colab.empty:
                    # Cria um dicionário para facilitar a busca do ID pelo nome
                    dict_colabs = dict(zip(df_colab['nome'], df_colab['id']))
                    nome_selecionado = st.selectbox("Selecione o profissional para editar:", options=list(dict_colabs.keys()))
                    
                    if nome_selecionado:
                        id_selecionado = dict_colabs[nome_selecionado]
                        dados_atuais = df_colab[df_colab['id'] == id_selecionado].iloc[0]
                        
                        with st.form("form_edita_colab", clear_on_submit=False):
                            c1, c2 = st.columns(2)
                            e_nome = c1.text_input("Nome Completo *", value=dados_atuais['nome'])
                            e_cargo = c2.text_input("Cargo / Especialidade", value=dados_atuais['cargo'] if dados_atuais['cargo'] else "")
                            
                            c3, c4 = st.columns(2)
                            e_tel = c3.text_input("WhatsApp / Telefone", value=dados_atuais['telefone'] if dados_atuais['telefone'] else "")
                            
                            # Define o index do selectbox baseado no status atual do banco
                            index_status = 0 if dados_atuais['ativo'] else 1
                            e_status = c4.selectbox("Status", ["Ativo", "Inativo"], index=index_status)
                            
                            st.markdown("---")
                            if st.form_submit_button("💾 Salvar Alterações"):
                                if not e_nome:
                                    st.warning("O nome não pode ficar em branco.")
                                else:
                                    is_ativo_edit = True if e_status == "Ativo" else False
                                    
                                    conn = conectar_banco()
                                    conn.cursor().execute("""
                                        UPDATE colaboradores 
                                        SET nome=%s, cargo=%s, telefone=%s, ativo=%s 
                                        WHERE id=%s AND empresa_id=%s
                                    """, (e_nome, e_cargo, e_tel, is_ativo_edit, id_selecionado, emp_id))
                                    conn.commit()
                                    devolver_conexao(conn)
                                    
                                    st.success("Cadastro atualizado com sucesso!")
                                    limpar_cache()
                                    st.rerun()
                else:
                    st.info("Não há colaboradores cadastrados para editar.")

            # --- EXIBIÇÃO DA EQUIPE ATUAL ---
            if not df_colab.empty:
                st.markdown("---")
                st.markdown("#### 📋 Equipe Cadastrada")
                
                # Tratamento visual dos dados para a tabela
                df_exibicao = df_colab.copy()
                df_exibicao['ativo'] = df_exibicao['ativo'].apply(lambda x: "🟢 Ativo" if x else "🔴 Inativo")
                df_exibicao = df_exibicao.rename(columns={
                    'nome': 'Nome do Profissional',
                    'cargo': 'Especialidade',
                    'telefone': 'Contato',
                    'ativo': 'Status'
                })
                
                # Removemos o ID da visualização para ficar mais limpo
                df_exibicao = df_exibicao.drop(columns=['id'])
                
                st.dataframe(df_exibicao, use_container_width=True, hide_index=True)
            else:
                st.info("Sua lista de colaboradores está vazia. Adicione o primeiro profissional acima.")
                

    # ==========================================
    # MÓDULO 3: MOVIMENTAÇÕES (Vendas e Compras)
    # ==========================================
    elif modulo == "🔄 Movimentações":
        st.markdown("### 🔄 Operações Diárias")
        
        # 1. Puxa as permissões do usuário logado (A Mochila de Chaves)
        meus_acessos = st.session_state.get('modulos_permitidos', [])

        # --- LINHA TEMPORÁRIA PARA TESTE ---
        # if 'mod_mov_servicos' not in meus_acessos: meus_acessos.append('mod_mov_servicos')

        # 2. Dicionário vinculando as chaves do banco aos nomes das abas na tela
        abas_disponiveis = {
            'mod_mov_vendas': "🛒 Vendas",
            'mod_mov_servicos': "✨ Lançar Serviço",
            'mod_mov_orcamentos': "📋 Orçamentos Salvos",
            'mod_mov_compras': "📥 Entrada de Mercadorias",
            'mod_mov_historico': "📋 Histórico de Entradas",
            'mod_mov_trocas': "🔄 Trocas e Empréstimos",
            'mod_mov_agenda': "📅 Agenda de Atendimentos"
        }

        # 3. Constrói a lista dinâmica de abas apenas com o que o usuário tem acesso
        nomes_abas_liberadas = [nome for chave, nome in abas_disponiveis.items() if chave in meus_acessos]

        # 4. Trava de segurança: Se não tiver acesso a nada, avisa e para a tela
        if not nomes_abas_liberadas:
            st.warning("⚠️ Seu usuário não tem permissão para realizar nenhuma ação de Movimentação.")
            st.stop() # Interrompe a leitura do código aqui para baixo

        # 5. Renderiza APENAS as abas liberadas na tela
        objetos_abas = st.tabs(nomes_abas_liberadas)
        
        # 6. Mapeamento dos objetos visuais (Inicializa tudo como 'None')
        tab_venda = tab_lanca_serv = tab_orcamentos = tab_compra = tab_historico_compras = tab_trocas = tab_agenda = None
        
        # Conecta o objeto renderizado com a variável correta
        for i, nome_aba in enumerate(nomes_abas_liberadas):
            if nome_aba == "🛒 Vendas": tab_venda = objetos_abas[i]
            elif nome_aba == "✨ Lançar Serviço": tab_lanca_serv = objetos_abas[i]
            elif nome_aba == "📋 Orçamentos Salvos": tab_orcamentos = objetos_abas[i]
            elif nome_aba == "📥 Entrada de Mercadorias": tab_compra = objetos_abas[i]
            elif nome_aba == "📋 Histórico de Entradas": tab_historico_compras = objetos_abas[i]
            elif nome_aba == "🔄 Trocas e Empréstimos": tab_trocas = objetos_abas[i]
            elif nome_aba == "📅 Agenda de Atendimentos": tab_agenda = objetos_abas[i]
                
        if tab_venda:
            with tab_venda:
                st.subheader("🛒 Vendas")
            
                # Carrega dados atualizados para o PDV
                df_cli = carregar_dados_cached("SELECT id, nome FROM clientes WHERE empresa_id=%s ORDER BY nome", (emp_id,))
                
                # Traz apenas produtos comerciais de Venda ou Serviços
                df_pro = carregar_dados_cached("SELECT id, nome, valor, quantidade, tipo FROM produtos WHERE empresa_id=%s AND (tipo='S' OR (tipo='P' AND classe='Venda')) ORDER BY nome", (emp_id,))
            
                if not df_cli.empty and not df_pro.empty:
                    # 1. Configurações da Venda
                    c_cli, c_data = st.columns(2)
                    cliente_pdv = c_cli.selectbox("Cliente:", options=df_cli['nome'].tolist(), index=None, placeholder="Selecione o cliente...")
                    data_venda_input = c_data.date_input("Data da Venda", format="DD/MM/YYYY", value=date.today())
                
                    c_pag, c_parc = st.columns(2)
                    f_pag = c_pag.selectbox("Forma de Pagamento:", ["Pix", "Crédito", "Débito", "Dinheiro", "Crediário"], index=None, placeholder="Selecione a forma de pagamento...")
                    
                    # Inicialização padrão para evitar erros de renderização financeira se f_pag estiver vazio
                    qtd_parcelas = 1
                    data_1_venc = date.today()
                    
                    if f_pag:
                        qtd_parcelas = c_parc.number_input("Número de Parcelas:", min_value=1, max_value=12, value=1, step=1)
                        sugestao_venc = date.today() if qtd_parcelas == 1 else date.today() + timedelta(days=30)
                        data_1_venc = st.date_input("Data do 1º Vencimento:", value=sugestao_venc, format="DD/MM/YYYY")
                
                    st.markdown("---")
                
                    # 2. Seleção de Produto com Visão Dinâmica (Produto vs Serviço)
                    tradutor_tipo = {'P': 'Produto', 'S': 'Serviço'}
                    
                    df_pro['display_pesquisa'] = df_pro.apply(
                        lambda x: f"{x['nome']} ({tradutor_tipo.get(x['tipo'], 'Produto')}) - Estoque: {int(x['quantidade'])}" if x['tipo'] == 'P' else f"{x['nome']} (Serviço)", axis=1
                    )
                
                    prod_display = st.selectbox("🔍 Pesquise o Item (Digite o nome):", options=df_pro['display_pesquisa'].tolist(), index=None, placeholder="Digite ou selecione um produto/serviço...")
                
                    # --- INTERRUPTOR DE SEGURANÇA: Só abre o painel se os dados iniciais fundamentais existirem ---
                    if cliente_pdv and f_pag and prod_display:
                        # Resgate das informações baseadas na escolha
                        p_info = df_pro[df_pro['display_pesquisa'] == prod_display].iloc[0]
                        estoque_atual = int(p_info['quantidade'])
                        preco_tabela = float(p_info['valor'])
                        item_tipo = p_info['tipo']
                        
                        profissional_selecionado = None
                        nome_profissional = None
                    
                        # --- PAINEL VISUAL CONDICIONAL ---
                        if item_tipo == 'P':
                            if estoque_atual <= 0:
                                st.error(f"🚨 ESTOQUE ZERADO! | 🏷️ Preço de Tabela: **R$ {preco_tabela:.2f}**".replace('.', ','))
                            elif estoque_atual == 1:
                                st.warning(f"⚠️ ÚLTIMA UNIDADE! | 🏷️ Preço de Tabela: **R$ {preco_tabela:.2f}**".replace('.', ','))
                            elif estoque_atual <= 3:
                                st.warning(f"⚠️ Estoque Baixo: Restam apenas {estoque_atual} unidades. | 🏷️ Preço de Tabela: **R$ {preco_tabela:.2f}**".replace('.', ','))
                            else:
                                st.info(f"📦 Estoque atual: {estoque_atual} unidades | 🏷️ Preço de Tabela: **R$ {preco_tabela:.2f}**".replace('.', ','))
                        
                        elif item_tipo == 'S':
                            st.info(f"🛠️ Serviço Prestado | 🏷️ Preço de Tabela: **R$ {preco_tabela:.2f}**".replace('.', ','))
                            
                            df_colab = carregar_dados_cached("SELECT id, nome FROM colaboradores WHERE ativo = TRUE AND empresa_id = %s", (emp_id,))
                            if not df_colab.empty:
                                lista_nomes = df_colab['nome'].tolist()
                                nome_colab = st.selectbox("👤 Quem executou o serviço?", options=lista_nomes, index=None, placeholder="Selecione o profissional executor...")
                                
                                if nome_colab:
                                    idx_colab = lista_nomes.index(nome_colab)
                                    profissional_selecionado = int(df_colab.iloc[idx_colab]['id'])
                                    nome_profissional = nome_colab
                            else:
                                st.warning("⚠️ Cadastre um colaborador na aba de Cadastros para registrar o serviço.")
                    
                        # --- FORMULÁRIO DE ADIÇÃO AO CARRINHO ---
                        with st.form("form_add_carrinho", clear_on_submit=True):
                            c1, c2, c3, c4 = st.columns(4)
                        
                            limite_qtd = estoque_atual if (item_tipo == 'P' and estoque_atual > 0) else 999
                            q_pdv = c1.number_input("Quantidade:", min_value=1, max_value=limite_qtd, step=1, value=1)
                        
                            preco_custom = c2.number_input("Preço Unitário (R$):", min_value=0.0, value=float(preco_tabela), step=1.0, format="%.2f")
                            desc_rs = c3.number_input("Desconto (R$):", min_value=0.0, step=1.0, format="%.2f")
                            desc_perc = c4.number_input("Desconto (%):", min_value=0.0, max_value=100.0, step=1.0, format="%.1f")
                        
                            # O botão desabilita se for produto sem estoque OU se for serviço sem colaborador selecionado
                            travar_botao = (item_tipo == 'P' and estoque_atual <= 0) or (item_tipo == 'S' and profissional_selecionado is None)
                            
                            if st.form_submit_button("➕ Adicionar ao Carrinho", disabled=travar_botao):
                                if item_tipo == 'S' or estoque_atual >= q_pdv:
                                    desconto_final = preco_custom * (desc_perc / 100.0) if desc_perc > 0 else desc_rs
                                    
                                    nome_carrinho = str(p_info['nome'])
                                    if item_tipo == 'S' and nome_profissional:
                                        nome_carrinho += f" (Executado por: {nome_profissional})"
                                    
                                    st.session_state['carrinho'].append({
                                        'id': int(p_info['id']), 
                                        'nome': nome_carrinho, 
                                        'qtd': int(q_pdv), 
                                        'unit': float(preco_custom), 
                                        'desc': float(desconto_final), 
                                        'total': float((preco_custom - desconto_final) * q_pdv),
                                        'tipo': item_tipo, 
                                        'colab_id': profissional_selecionado
                                    })
                                    st.rerun()
                                else: 
                                    st.error("Estoque insuficiente!")
                    else:
                        st.info("👆 preencha o cliente, a forma de pagamento e selecione um item para configurar a venda.")

                    # 3. Carrinho e Configurações Financeiras
                    if st.session_state['carrinho']:
                        st.markdown("### 🛍️ Itens no Carrinho")
                        
                        # Adicionado gap="small" para aproximar horizontalmente e verticalmente
                        col_c1, col_c2, col_c3, col_c4, col_vazia = st.columns([5, 1, 1.5, 0.5, 3], gap="small")
                        col_c1.markdown("**Item**")
                        col_c2.markdown("**Qtd**")
                        col_c3.markdown("**Subtotal**")
                        
                        # CORREÇÃO CRÍTICA: Linha fina com margem de apenas 4px acima e 8px abaixo
                        st.markdown("<hr style='margin: 4px 0px 8px 0px; opacity: 0.3;'>", unsafe_allow_html=True)
                        
                        total_pdv = 0.0
                        
                        for i, item in enumerate(st.session_state['carrinho']):
                            col_i1, col_i2, col_i3, col_i4, col_ivazia = st.columns([5, 1, 1.5, 0.5, 3], gap="small")
                            col_i1.write(f"▫️ {item['nome']}")
                            col_i2.write(f"{item['qtd']}x")
                            col_i3.write(f"R$ {item['total']:.2f}".replace('.', ','))
                            
                            if col_i4.button("🗑️", key=f"del_pdv_{i}", help="Remover item"):
                                st.session_state['carrinho'].pop(i)
                                st.rerun()
                                
                            total_pdv += float(item['total'])
                        
                        st.markdown("<hr style='margin: 10px 0px 10px 0px; opacity: 0.3;'>", unsafe_allow_html=True)
                        st.header(f"Total Atual: R$ {total_pdv:.2f}".replace('.', ','))
                    
                        st.markdown("---")
                    
                        # --- CONFIGURAÇÃO DE ENTRADA ---
                        valor_entrada = 0.0
                        if f_pag == "Crediário":
                            valor_entrada = st.number_input("Valor da Entrada (R$)", min_value=0.0, max_value=float(total_pdv), value=0.0, step=10.0)
                    
                        valor_restante = float(total_pdv - valor_entrada)
                    
                        # --- EDICÃO DINÂMICA DAS DATAS DAS PARCELAS ---
                        datas_parcelas = []
                        if qtd_parcelas > 1 or f_pag == "Crediário":
                            st.markdown("📅 **Cronograma de Vencimentos (Clique na data para alterar):**")
                        
                            if f_pag == "Crediário" and valor_entrada > 0:
                                datas_parcelas.append(data_venda_input)
                            
                                if qtd_parcelas > 1:
                                    cols_p = st.columns(min(int(qtd_parcelas) - 1, 4))
                                    for i in range(2, int(qtd_parcelas) + 1):
                                        sugestao_p = data_1_venc + timedelta(days=30 * (i - 2))
                                        with cols_p[(i-2) % min(int(qtd_parcelas) - 1, 4)]:
                                            dt_p = st.date_input(f"{i}ª Parc. (Restante)", value=sugestao_p, format="DD/MM/YYYY", key=f"venc_p_{i}")
                                            datas_parcelas.append(dt_p)
                            else:
                                cols_p = st.columns(min(int(qtd_parcelas), 4))
                                for i in range(1, int(qtd_parcelas) + 1):
                                    sugerido = data_1_venc + timedelta(days=30 * (i - 1))
                                    with cols_p[(i-1) % min(int(qtd_parcelas), 4)]:
                                        dt_p = st.date_input(f"{i}ª Parcela", value=sugerido, format="DD/MM/YYYY", key=f"venc_p_{i}")
                                        datas_parcelas.append(dt_p)
                        else:
                            datas_parcelas.append(data_1_venc)

                        if f_pag == "Crediário" and valor_entrada > 0:
                            st.info(f"💵 Entrada: R$ {valor_entrada:.2f} (Paga hoje) | ⏳ Restante: R$ {valor_restante:.2f} lançado em {int(qtd_parcelas - 1)}x de R$ {(valor_restante / (qtd_parcelas - 1)):.2f}".replace('.', ','))
                        elif qtd_parcelas > 1:
                            st.info(f"💳 Parcelamento: {int(qtd_parcelas)}x de R$ {(total_pdv / qtd_parcelas):.2f} ".replace('.', ','))
                    
                        st.markdown("---")             
                    
                        c1_finalizar, c2_orcamento, c3_limpar = st.columns(3)
                    
                        # --- AÇÃO: FINALIZAR VENDA (PERSISTE NO BANCO) ---
                        if c1_finalizar.button("✅ Finalizar Venda", type="primary", use_container_width=True):
                            try:
                                conn = conectar_banco()
                                cur = conn.cursor()
                            
                                cur.execute("SELECT MAX(codigo_venda) FROM vendas WHERE empresa_id=%s", (int(emp_id),))
                                resultado = cur.fetchone()[0]
                                novo_cod = int(resultado + 1) if resultado else 1
                            
                                data_v = data_venda_input.strftime("%d/%m/%Y")
                                cli_id_v = int(df_cli[df_cli['nome'] == cliente_pdv].iloc[0]['id'])
                            
                                for it in st.session_state['carrinho']:
                                    # Inserindo o colaborador_id na tabela de vendas
                                    cur.execute("""INSERT INTO vendas (codigo_venda, cliente_id, produto_id, quantidade, data_venda, valor_total, empresa_id, valor_unitario, desconto, forma_pagamento, valor_entrada, valor_restante, qtd_parcelas, colaborador_id) 
                                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                               (int(novo_cod), int(cli_id_v), int(it['id']), int(it['qtd']), str(data_v), float(it['total']), int(emp_id), float(it['unit']), float(it['desc']), str(f_pag), float(valor_entrada), float(valor_restante), int(qtd_parcelas), it['colab_id']))
                                
                                    # Baixa de estoque APENAS para produtos comerciais
                                    if it['tipo'] == 'P':
                                        cur.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE id=%s", (int(it['qtd']), int(it['id'])))
                            
                                # Inserção no Financeiro / Contas a Receber
                                if f_pag == "Crediário" and valor_entrada > 0:
                                    cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, data_pagamento, empresa_id) 
                                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                               (int(novo_cod), int(cli_id_v), 1, int(qtd_parcelas), float(valor_entrada), datas_parcelas[0].strftime("%d/%m/%Y"), 'Pago', data_v, int(emp_id)))
                                    
                                    if qtd_parcelas > 1:
                                        val_parc_rest = float(valor_restante / (qtd_parcelas - 1))
                                        for i in range(2, int(qtd_parcelas) + 1):
                                            dt_venc = datas_parcelas[i-1]
                                            cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id) 
                                                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                                                       (int(novo_cod), int(cli_id_v), int(i), int(qtd_parcelas), float(val_parc_rest), dt_venc.strftime("%d/%m/%Y"), 'Pendente', int(emp_id)))
                                else:
                                    val_parc = float(total_pdv / qtd_parcelas)
                                    for i in range(1, int(qtd_parcelas) + 1):
                                        dt_venc = datas_parcelas[i-1]
                                        status_venda = 'Pendente' if qtd_parcelas > 1 else ('Pago' if f_pag != "Crediário" else 'Pendente')
                                        data_pag_val = data_v if status_venda == 'Pago' else None
                                        
                                        cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, data_pagamento, empresa_id) 
                                                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                                   (int(novo_cod), int(cli_id_v), int(i), int(qtd_parcelas), float(val_parc), dt_venc.strftime("%d/%m/%Y"), status_venda, data_pag_val, int(emp_id)))                        
                            
                                # Mensagem do WhatsApp
                                cur.execute("SELECT telefone FROM clientes WHERE id = %s", (cli_id_v,))
                                resultado_tel = cur.fetchone()
                                tel_cli = resultado_tel[0] if resultado_tel else None
                            
                                lista_produtos_msg = ""
                                for it in st.session_state['carrinho']:
                                    lista_produtos_msg += f"▫️ {int(it['qtd'])}x {it['nome']} (R$ {it['unit']:.2f})\n".replace('.', ',')
                            
                                msg = f"Olá, {cliente_pdv}! 🌸\n\n"
                                msg += f"Aqui está o resumo do seu pedido do dia *{data_v}*:\n\n"
                                msg += f"🧾 *Pedido Confirmado Nº {novo_cod}*\n\n"
                                msg += f"*Itens:*\n{lista_produtos_msg}\n"
                                msg += f"💰 *Valor Total:* R$ {total_pdv:.2f}\n".replace('.', ',')
                            
                                if qtd_parcelas > 1:
                                    msg += "\n📅 *Datas de Vencimento:*\n"
                                    if f_pag == "Crediário" and valor_entrada > 0:
                                        msg += f"▪️ Entrada: R$ {valor_entrada:.2f} (Paga em {datas_parcelas[0].strftime('%d/%m/%Y')})\n".replace('.', ',')
                                        v_rest_calc = valor_restante / (qtd_parcelas - 1)
                                        for i in range(2, int(qtd_parcelas) + 1):
                                            msg += f"▪️ {i}ª Parcela: R$ {v_rest_calc:.2f} -> {datas_parcelas[i-1].strftime('%d/%m/%Y')}\n".replace('.', ',')
                                    else:
                                        v_parc_calc = total_pdv / qtd_parcelas
                                        for i in range(1, int(qtd_parcelas) + 1):
                                            msg += f"▪️ {i}ª Parcela: R$ {v_parc_calc:.2f} -> {datas_parcelas[i-1].strftime('%d/%m/%Y')}\n".replace('.', ',')
                                else:
                                    msg += f"💳 *Forma de Pagto:* {f_pag}\n"
                                
                                msg += "\n\nMuito obrigada pela preferência! ✨"
                            
                                if tel_cli:
                                    tel_limpo = ''.join(filter(str.isdigit, str(tel_cli)))
                                    if len(tel_limpo) >= 10:
                                        if not tel_limpo.startswith('55'): tel_limpo = '55' + tel_limpo
                                        st.session_state['zap_link'] = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                                        st.session_state['zap_msg'] = msg
                                        st.session_state['zap_codigo'] = f"PEDIDO Nº {novo_cod}"
                                        st.session_state['zap_total'] = total_pdv
                            
                                conn.commit()
                                devolver_conexao(conn)
                                st.session_state['carrinho'] = []
                                st.success(f"Venda {novo_cod} salva com sucesso como PEDIDO!")
                                limpar_cache()
                                st.rerun()
                            
                            except Exception as e:
                                st.error(f"Erro no banco: {e}")
                                if 'conn' in locals(): devolver_conexao(conn)

                        # --- AÇÃO: ORÇAMENTO ---
                        if c2_orcamento.button("📋 Salvar Orçamento", use_container_width=True):
                            try:
                                carrinho_texto = json.dumps(st.session_state['carrinho'])
                                conn = conectar_banco()
                                cur = conn.cursor()
                                data_hoje_str = date.today().strftime('%d/%m/%Y')
                                
                                cur.execute("""INSERT INTO orcamentos (empresa_id, cliente_nome, data_orcamento, valor_total, carrinho_json) 
                                               VALUES (%s,%s,%s,%s,%s)""", 
                                            (int(emp_id), cliente_pdv, data_hoje_str, float(total_pdv), carrinho_texto))
                                conn.commit()
                                devolver_conexao(conn)
                                st.success("Orçamento gravado no sistema com sucesso!")
                            except Exception as e:
                                st.error(f"Erro ao salvar orçamento: {e}")
                                
                            cur_cli = carregar_dados_cached("SELECT telefone FROM clientes WHERE nome=%s AND empresa_id=%s", (cliente_pdv, emp_id))
                            tel_cli = cur_cli.iloc[0]['telefone'] if not cur_cli.empty else None
                        
                            lista_produtos_msg = ""
                            for it in st.session_state['carrinho']:
                                lista_produtos_msg += f"▫️ {int(it['qtd'])}x {it['nome']} (R$ {it['unit']:.2f})\n".replace('.', ',')
                        
                            msg = f"Olá, {cliente_pdv}! 🌸\n\n"
                            msg += f"Segue a simulação do seu *ORÇAMENTO* feito hoje ({date.today().strftime('%d/%m/%Y')}):\n\n"
                            msg += f"*Itens Solicitados:*\n{lista_produtos_msg}\n"
                            msg += f"💰 *Valor Total Estimado:* R$ {total_pdv:.2f}\n".replace('.', ',')
                        
                            if qtd_parcelas > 1:
                                msg += "\n🗓️ *Simulação de Parcelamento:*\n"
                                if f_pag == "Crediário" and valor_entrada > 0:
                                    msg += f"▪️ Entrada sugerida: R$ {valor_entrada:.2f}\n".replace('.', ',')
                                    v_rest_calc = valor_restante / (qtd_parcelas - 1)
                                    for i in range(2, int(qtd_parcelas) + 1):
                                        msg += f"▪️ {i}ª Parcela: R$ {v_rest_calc:.2f} -> {datas_parcelas[i-1].strftime('%d/%m/%Y')}\n".replace('.', ',')
                                else:
                                    v_parc_calc = total_pdv / qtd_parcelas
                                    for i in range(1, int(qtd_parcelas) + 1):
                                        msg += f"▪️ {i}ª Parcela: R$ {v_parc_calc:.2f} -> {datas_parcelas[i-1].strftime('%d/%m/%Y')}\n".replace('.', ',')
                            else:
                                msg += f"💳 *Meio de pagamento simulado:* {f_pag}\n"
                        
                            msg += "\n*Este orçamento é válido por 5 dias.* Tem interesse em fechar o pedido? ✨"
                        
                            if tel_cli:
                                tel_limpo = ''.join(filter(str.isdigit, str(tel_cli)))
                                if len(tel_limpo) >= 10:
                                    if not tel_limpo.startswith('55'): tel_limpo = '55' + tel_limpo
                                    st.session_state['zap_link'] = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                                    st.session_state['zap_msg'] = msg
                                    st.session_state['zap_codigo'] = "ORÇAMENTO EM ABERTO"
                                    st.session_state['zap_total'] = total_pdv
                        
                            st.success("Orçamento gerado! Os dados de estoque e contas a receber permaneceram intactos.")
                            st.rerun()

                        if c3_limpar.button("🗑️ Limpar Carrinho", use_container_width=True): 
                            st.session_state['carrinho'] = []
                            st.rerun()
                else: 
                    st.warning("Cadastre clientes e produtos antes de vender.")
                
                # --- TELA DO RECIBO OU ORÇAMENTO DO WHATSAPP ---
                if 'zap_link' in st.session_state and st.session_state['zap_link']:
                    st.markdown("---")
                    with st.container(border=True):
                        st.success(f"🎉 {st.session_state['zap_codigo']} pronto! Total: R$ {st.session_state['zap_total']:.2f}".replace('.', ','))
                        st.subheader("📲 Enviar Documento via WhatsApp")
                        st.text_area("Visualização da mensagem:", value=st.session_state['zap_msg'], height=180, disabled=True)
                        st.link_button("🟢 Abrir WhatsApp e Enviar", st.session_state['zap_link'], type="primary", use_container_width=True)
                        if st.button("❌ Fechar Painel", use_container_width=True):
                            del st.session_state['zap_link']
                            if 'zap_msg' in st.session_state: del st.session_state['zap_msg']
                            if 'zap_codigo' in st.session_state: del st.session_state['zap_codigo']
                            if 'zap_total' in st.session_state: del st.session_state['zap_total']
                            st.rerun()        

        # Inicializa o carrinho de serviços se não existir
        if 'carrinho_servicos' not in st.session_state:
            st.session_state['carrinho_servicos'] = []

        if tab_lanca_serv:
            with tab_lanca_serv:
                st.subheader("✨ Lançamento de Serviços e Ficha Técnica")
                
                # Carrega dados
                df_cli = carregar_dados_cached("SELECT id, nome FROM clientes WHERE empresa_id=%s ORDER BY nome", (emp_id,))
                df_serv = carregar_dados_cached("SELECT id, nome, valor FROM produtos WHERE empresa_id=%s AND tipo='S' ORDER BY nome", (emp_id,))
                df_prod_insumo = carregar_dados_cached("SELECT id, nome FROM produtos WHERE empresa_id=%s AND tipo='P' AND classe='Insumo' ORDER BY nome", (emp_id,))
                df_colab = carregar_dados_cached("SELECT id, nome FROM colaboradores WHERE ativo = TRUE AND empresa_id = %s", (emp_id,))
            
                if not df_cli.empty and not df_serv.empty and not df_colab.empty:
                    # 1. Configurações do Atendimento
                    c_cli, c_data = st.columns(2)
                    cliente_pdv = c_cli.selectbox("Cliente (Ficha Técnica):", options=df_cli['nome'].tolist(), index=None, placeholder="Selecione a cliente...", key="cli_serv")
                    data_venda_input = c_data.date_input("Data do Serviço", format="DD/MM/YYYY", value=date.today(), key="dt_serv")
                
                    c_pag, c_parc = st.columns(2)
                    f_pag = c_pag.selectbox("Forma de Pagamento:", ["Pix", "Crédito", "Débito", "Dinheiro", "Crediário"], index=None, placeholder="Selecione a forma de pagamento...", key="fpag_serv")
                    
                    # Inicialização padrão para evitar falhas se f_pag não estiver selecionado
                    qtd_parcelas = 1
                    data_1_venc = date.today()
                    
                    if f_pag:
                        qtd_parcelas = c_parc.number_input("Número de Parcelas:", min_value=1, max_value=12, value=1, step=1, key="parc_serv")
                        sugestao_venc = date.today() if qtd_parcelas == 1 else date.today() + timedelta(days=30)
                        data_1_venc = st.date_input("Data do 1º Vencimento:", value=sugestao_venc, format="DD/MM/YYYY", key="venc1_serv")
                
                    st.markdown("---")
                
                    # 2. Seleção do Serviço, Profissional e Insumos
                    st.markdown("**Detalhes do Procedimento**")
                    col_s1, col_s2 = st.columns(2)
                    
                    serv_display = col_s1.selectbox("✨ Selecione o Serviço:", options=df_serv['nome'].tolist(), index=None, placeholder="Escolha o procedimento...")
                    nome_colab = col_s2.selectbox("👤 Quem executou?", options=df_colab['nome'].tolist(), index=None, placeholder="Selecione o profissional executor...")
                    
                    opcoes_insumos = df_prod_insumo['nome'].tolist() if not df_prod_insumo.empty else []
                    msg_placeholder = "Selecione os produtos utilizados (opcional)..." if opcoes_insumos else "⚠️ Nenhum produto classificado como 'Insumo' no banco."
                    insumos_selecionados = st.multiselect("🧴 Produtos/Insumos Utilizados na Sessão (Histórico do Cliente):", options=opcoes_insumos, placeholder=msg_placeholder, help="Estes itens ficarão salvos na ficha da cliente para consultas futuras.")
                
                    # --- NOVO FLUXO: Mostra detalhes do serviço assim que ele for selecionado ---
                    if serv_display:
                        s_info = df_serv[df_serv['nome'] == serv_display].iloc[0]
                        preco_tabela = float(s_info['valor'])
                        
                        st.info(f"🏷️ Preço Base do Serviço: **R$ {preco_tabela:.2f}**".replace('.', ','))
                        
                        # Trocado st.form por st.container para que a validação do botão seja em tempo real
                        with st.container(border=True):
                            c1, c2, c3, c4 = st.columns(4)
                        
                            q_pdv = c1.number_input("Quantidade de Sessões:", min_value=1, step=1, value=1)
                            preco_custom = c2.number_input("Preço do Serviço (R$):", min_value=0.0, value=float(preco_tabela), step=1.0, format="%.2f")
                            desc_rs = c3.number_input("Desconto (R$):", min_value=0.0, step=1.0, format="%.2f", key="d_rs_s")
                            desc_perc = c4.number_input("Desconto (%):", min_value=0.0, max_value=100.0, step=1.0, format="%.1f", key="d_perc_s")
                        
                            trava_add = (cliente_pdv is None) or (f_pag is None) or (nome_colab is None)
                            
                            if trava_add:
                                st.warning("⚠️ Preencha Cliente, Forma de Pagamento e Profissional para habilitar a adição ao carrinho.")
                        
                            if st.button("➕ Adicionar Serviço", type="primary", disabled=trava_add):
                                desconto_final = preco_custom * (desc_perc / 100.0) if desc_perc > 0 else desc_rs
                                
                                idx_colab = df_colab['nome'].tolist().index(nome_colab)
                                profissional_selecionado = int(df_colab.iloc[idx_colab]['id'])
                                
                                insumos_ids = []
                                for ins in insumos_selecionados:
                                    ins_id = df_prod_insumo[df_prod_insumo['nome'] == ins].iloc[0]['id']
                                    insumos_ids.append(int(ins_id))
                                
                                nome_carrinho = f"{serv_display} (Profissional: {nome_colab})"
                                if insumos_selecionados:
                                    nome_carrinho += f" | Insumos: {', '.join(insumos_selecionados)}"
                                
                                st.session_state['carrinho_servicos'].append({
                                    'id': int(s_info['id']), 
                                    'nome': nome_carrinho, 
                                    'qtd': int(q_pdv), 
                                    'unit': float(preco_custom), 
                                    'desc': float(desconto_final), 
                                    'total': float((preco_custom - desconto_final) * q_pdv),
                                    'colab_id': profissional_selecionado,
                                    'insumos_ids': insumos_ids
                                })
                                st.rerun()

                    # 3. Carrinho e Configurações Financeiras
                    if st.session_state['carrinho_servicos']:
                        st.markdown("### 🛍️ Serviços Adicionados")
                        
                        col_c1, col_c2, col_c3, col_c4, col_vazia = st.columns([5, 1, 1.5, 0.5, 3], gap="small")
                        col_c1.markdown("**Procedimento**")
                        col_c2.markdown("**Sessões**")
                        col_c3.markdown("**Subtotal**")
                        
                        st.markdown("<hr style='margin: 4px 0px 8px 0px; opacity: 0.3;'>", unsafe_allow_html=True)
                        
                        total_pdv = 0.0
                        
                        for i, item in enumerate(st.session_state['carrinho_servicos']):
                            col_i1, col_i2, col_i3, col_i4, col_ivazia = st.columns([5, 1, 1.5, 0.5, 3], gap="small")
                            col_i1.write(f"▫️ {item['nome']}")
                            col_i2.write(f"{item['qtd']}x")
                            col_i3.write(f"R$ {item['total']:.2f}".replace('.', ','))
                            
                            if col_i4.button("🗑️", key=f"del_serv_{i}", help="Remover serviço"):
                                st.session_state['carrinho_servicos'].pop(i)
                                st.rerun()
                                
                            total_pdv += float(item['total'])
                        
                        st.markdown("<hr style='margin: 10px 0px 10px 0px; opacity: 0.3;'>", unsafe_allow_html=True)
                        st.header(f"Total a Pagar: R$ {total_pdv:.2f}".replace('.', ','))
                    
                        st.markdown("---")
                    
                        # --- CONFIGURAÇÃO DE ENTRADA E PARCELAS ---
                        valor_entrada = 0.0
                        if f_pag == "Crediário":
                            valor_entrada = st.number_input("Valor da Entrada (R$)", min_value=0.0, max_value=float(total_pdv), value=0.0, step=10.0, key="ent_s")
                    
                        valor_restante = float(total_pdv - valor_entrada)
                    
                        datas_parcelas = []
                        if qtd_parcelas > 1 or f_pag == "Crediário":
                            st.markdown("📅 **Cronograma de Vencimentos:**")
                            if f_pag == "Crediário" and valor_entrada > 0:
                                datas_parcelas.append(data_venda_input)
                                if qtd_parcelas > 1:
                                    cols_p = st.columns(min(int(qtd_parcelas) - 1, 4))
                                    for i in range(2, int(qtd_parcelas) + 1):
                                        sugestao_p = data_1_venc + timedelta(days=30 * (i - 2))
                                        with cols_p[(i-2) % min(int(qtd_parcelas) - 1, 4)]:
                                            dt_p = st.date_input(f"{i}ª Parc.", value=sugestao_p, format="DD/MM/YYYY", key=f"v_p_s_{i}")
                                            datas_parcelas.append(dt_p)
                            else:
                                cols_p = st.columns(min(int(qtd_parcelas), 4))
                                for i in range(1, int(qtd_parcelas) + 1):
                                    sugerido = data_1_venc + timedelta(days=30 * (i - 1))
                                    with cols_p[(i-1) % min(int(qtd_parcelas), 4)]:
                                        dt_p = st.date_input(f"{i}ª Parcela", value=sugerido, format="DD/MM/YYYY", key=f"v_p_s_{i}")
                                        datas_parcelas.append(dt_p)
                        else:
                            datas_parcelas.append(data_1_venc)

                        st.markdown("---")             
                    
                        c1_finalizar, c3_limpar = st.columns([2, 1])
                    
                        # --- AÇÃO: FINALIZAR SERVIÇO (PERSISTE NO BANCO) ---
                        if c1_finalizar.button("✅ Lançar Atendimento e Gerar Financeiro", type="primary", use_container_width=True):
                            try:
                                conn = conectar_banco()
                                cur = conn.cursor()
                            
                                cur.execute("SELECT MAX(codigo_venda) FROM vendas WHERE empresa_id=%s", (int(emp_id),))
                                resultado = cur.fetchone()[0]
                                novo_cod = int(resultado + 1) if resultado else 1
                            
                                data_v = data_venda_input.strftime("%d/%m/%Y")
                                cli_id_v = int(df_cli[df_cli['nome'] == cliente_pdv].iloc[0]['id'])
                            
                                for it in st.session_state['carrinho_servicos']:
                                    cur.execute("""INSERT INTO vendas (codigo_venda, cliente_id, produto_id, quantidade, data_venda, valor_total, empresa_id, valor_unitario, desconto, forma_pagamento, valor_entrada, valor_restante, qtd_parcelas, colaborador_id) 
                                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                               (int(novo_cod), int(cli_id_v), int(it['id']), int(it['qtd']), str(data_v), float(it['total']), int(emp_id), float(it['unit']), float(it['desc']), str(f_pag), float(valor_entrada), float(valor_restante), int(qtd_parcelas), int(it['colab_id'])))
                                    
                                    if it['insumos_ids']:
                                        for insumo_id in it['insumos_ids']:
                                            cur.execute("""INSERT INTO historico_insumos (venda_codigo, cliente_id, produto_id, data_uso, empresa_id) 
                                                           VALUES (%s,%s,%s,%s,%s)""",
                                                        (int(novo_cod), int(cli_id_v), int(insumo_id), data_venda_input, int(emp_id)))
                            
                                if f_pag == "Crediário" and valor_entrada > 0:
                                    cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, data_pagamento, empresa_id) 
                                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                               (int(novo_cod), int(cli_id_v), 1, int(qtd_parcelas), float(valor_entrada), datas_parcelas[0].strftime("%d/%m/%Y"), 'Pago', data_v, int(emp_id)))
                                    
                                    if qtd_parcelas > 1:
                                        val_parc_rest = float(valor_restante / (qtd_parcelas - 1))
                                        for i in range(2, int(qtd_parcelas) + 1):
                                            dt_venc = datas_parcelas[i-1]
                                            cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id) 
                                                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                                                       (int(novo_cod), int(cli_id_v), int(i), int(qtd_parcelas), float(val_parc_rest), dt_venc.strftime("%d/%m/%Y"), 'Pendente', int(emp_id)))
                                else:
                                    val_parc = float(total_pdv / qtd_parcelas)
                                    for i in range(1, int(qtd_parcelas) + 1):
                                        dt_venc = datas_parcelas[i-1]
                                        status_venda = 'Pendente' if qtd_parcelas > 1 else ('Pago' if f_pag != "Crediário" else 'Pendente')
                                        data_pag_val = data_v if status_venda == 'Pago' else None
                                        
                                        cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, data_pagamento, empresa_id) 
                                                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                                   (int(novo_cod), int(cli_id_v), int(i), int(qtd_parcelas), float(val_parc), dt_venc.strftime("%d/%m/%Y"), status_venda, data_pag_val, int(emp_id)))                        
                            
                                cur.execute("SELECT telefone FROM clientes WHERE id = %s", (cli_id_v,))
                                resultado_tel = cur.fetchone()
                                tel_cli = resultado_tel[0] if resultado_tel else None
                            
                                lista_produtos_msg = ""
                                for it in st.session_state['carrinho_servicos']:
                                    lista_produtos_msg += f"▫️ {it['nome'].split(' |')[0]} (R$ {it['unit']:.2f})\n".replace('.', ',')
                            
                                msg = f"Olá, {cliente_pdv}! ✨\n\n"
                                msg += f"Obrigada por escolher nossos serviços hoje ({data_v}). Aqui está o seu recibo:\n\n"
                                msg += f"🧾 *Atendimento Nº {novo_cod}*\n\n"
                                msg += f"*Procedimentos Realizados:*\n{lista_produtos_msg}\n"
                                msg += f"💰 *Valor Total:* R$ {total_pdv:.2f}\n".replace('.', ',')
                                msg += f"💳 *Forma de Pagto:* {f_pag}\n\n"
                                msg += "Foi um prazer atender você. Até a próxima! 🌸"
                            
                                if tel_cli:
                                    tel_limpo = ''.join(filter(str.isdigit, str(tel_cli)))
                                    if len(tel_limpo) >= 10:
                                        if not tel_limpo.startswith('55'): tel_limpo = '55' + tel_limpo
                                        st.session_state['zap_link_serv'] = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                                        st.session_state['zap_msg_serv'] = msg
                                        st.session_state['zap_codigo_serv'] = f"ATENDIMENTO Nº {novo_cod}"
                                        st.session_state['zap_total_serv'] = total_pdv
                            
                                conn.commit()
                                devolver_conexao(conn)
                                st.session_state['carrinho_servicos'] = []
                                st.success(f"Ficha técnica e Atendimento {novo_cod} salvos com sucesso!")
                                limpar_cache()
                                st.rerun()
                            
                            except Exception as e:
                                st.error(f"Erro no banco: {e}")
                                if 'conn' in locals(): devolver_conexao(conn)

                        if c3_limpar.button("🗑️ Limpar Painel", use_container_width=True): 
                            st.session_state['carrinho_servicos'] = []
                            st.rerun()
                else: 
                    st.warning("Cadastre clientes, colaboradores e serviços para habilitar esta tela.")
                
                # --- TELA DO RECIBO DO WHATSAPP ---
                if 'zap_link_serv' in st.session_state and st.session_state['zap_link_serv']:
                    st.markdown("---")
                    with st.container(border=True):
                        st.success(f"🎉 {st.session_state['zap_codigo_serv']} finalizado! Total: R$ {st.session_state['zap_total_serv']:.2f}".replace('.', ','))
                        st.subheader("📲 Enviar Recibo via WhatsApp")
                        st.text_area("Visualização da mensagem:", value=st.session_state['zap_msg_serv'], height=180, disabled=True)
                        st.link_button("🟢 Abrir WhatsApp e Enviar", st.session_state['zap_link_serv'], type="primary", use_container_width=True)
                        if st.button("❌ Fechar Painel", use_container_width=True, key="fechar_zap_s"):
                            del st.session_state['zap_link_serv']
                            if 'zap_msg_serv' in st.session_state: del st.session_state['zap_msg_serv']
                            if 'zap_codigo_serv' in st.session_state: del st.session_state['zap_codigo_serv']
                            if 'zap_total_serv' in st.session_state: del st.session_state['zap_total_serv']
                            st.rerun()         
                            
        if tab_orcamentos:
            with tab_orcamentos:
                st.subheader("📋 Orçamentos Salvos")
                
                # Carrega todos os orçamentos ativos da empresa
                df_orcs = carregar_dados_cached("SELECT id, cliente_nome, data_orcamento, valor_total, carrinho_json FROM orcamentos WHERE empresa_id=%s ORDER BY id DESC", (emp_id,))
                
                if not df_orcs.empty:
                    for index, row in df_orcs.iterrows():
                        orc_id = row['id']
                        
                        # Chaves exclusivas na memória para controlar o estado deste orçamento específico
                        key_modo_edicao = f"modo_edicao_{orc_id}"
                        key_carrinho_edicao = f"carrinho_edicao_{orc_id}"
                        
                        with st.expander(f"Orçamento #{orc_id} - {row['cliente_nome']} | Data: {row['data_orcamento']} | R$ {row['valor_total']:.2f}".replace('.', ',')):
                            
                            # -------------------------------------------------
                            # CENÁRIO A: MODO DE EDIÇÃO ATIVADO
                            # -------------------------------------------------
                            if st.session_state.get(key_modo_edicao, False):
                                st.caption("✏️ **Modo de Edição de Itens**")
                                
                                # Se o carrinho de edição temporário não existir, desempacota o JSON do banco para a memória
                                if key_carrinho_edicao not in st.session_state:
                                    st.session_state[key_carrinho_edicao] = json.loads(row['carrinho_json'])
                                
                                carrinho_atual = st.session_state[key_carrinho_edicao]
                                
                                if carrinho_atual:
                                    novo_total = 0.0
                                    
                                    # Cabeçalho da tabela de edição
                                    col_h1, col_h2, col_h3, col_h4 = st.columns([4, 1.5, 2, 1])
                                    col_h1.markdown("**Item**")
                                    col_h2.markdown("**Qtd**")
                                    col_h3.markdown("**Subtotal**")
                                    st.markdown("---")
                                    
                                    # Lista as linhas com opção de alteração e exclusão pontual
                                    for i, item in enumerate(carrinho_atual):
                                        col_item, col_qtd, col_total, col_del = st.columns([4, 1.5, 2, 1])
                                        
                                        col_item.write(f"▫️ {item['nome']}")
                                        
                                        # Campo dinâmico para alterar a quantidade do item no próprio orçamento
                                        nova_qtd = col_qtd.number_input(
                                            "Qtd", min_value=1, value=int(item['qtd']), step=1, 
                                            key=f"ed_qtd_{orc_id}_{i}", label_visibility="collapsed"
                                        )
                                        
                                        # Recalcula os valores da linha baseado na nova quantidade e descontos prévios
                                        item['qtd'] = nova_qtd
                                        item['total'] = (float(item['unit']) - float(item['desc'])) * nova_qtd
                                        novo_total += item['total']
                                        
                                        col_total.write(f"R$ {item['total']:.2f}".replace('.', ','))
                                        
                                        # O Botão de Lixeira remove apenas o item deste índice da lista na memória
                                        if col_del.button("🗑️", key=f"del_item_{orc_id}_{i}", help="Remover este item do orçamento"):
                                            st.session_state[key_carrinho_edicao].pop(i)
                                            st.rerun()
                                    
                                    st.markdown("---")
                                    st.markdown(f"#### 💰 **Novo Total Calculado: R$ {novo_total:.2f}**".replace('.', ','))
                                    
                                    # Botões de salvamento e cancelamento da edição
                                    c1_ed, c2_ed = st.columns(2)
                                    
                                    if c1_ed.button("💾 Salvar Alterações", key=f"salvar_ed_{orc_id}", type="primary", use_container_width=True):
                                        try:
                                            carrinho_texto = json.dumps(st.session_state[key_carrinho_edicao])
                                            conn = conectar_banco()
                                            cur = conn.cursor()
                                            cur.execute("""
                                                UPDATE orcamentos 
                                                SET valor_total = %s, carrinho_json = %s 
                                                WHERE id = %s AND empresa_id = %s
                                            """, (float(novo_total), carrinho_texto, int(orc_id), int(emp_id)))
                                            conn.commit()
                                            devolver_conexao(conn)
                                            
                                            # Limpa as variáveis de controle de edição da memória
                                            del st.session_state[key_modo_edicao]
                                            del st.session_state[key_carrinho_edicao]
                                            
                                            st.success("✅ Orçamento atualizado com sucesso!")
                                            limpar_cache()
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Erro ao salvar alterações: {e}")
                                            
                                    if c2_ed.button("🔄 Cancelar Edição", key=f"cancelar_ed_{orc_id}", use_container_width=True):
                                        del st.session_state[key_modo_edicao]
                                        if key_carrinho_edicao in st.session_state: 
                                            del st.session_state[key_carrinho_edicao]
                                        st.rerun()
                                else:
                                    st.warning("⚠️ Todos os itens foram removidos. Deseja excluir o orçamento completo?")
                                    if st.button("🗑️ Excluir Orçamento Vazio", key=f"del_vazio_{orc_id}", type="primary", use_container_width=True):
                                        conn = conectar_banco()
                                        cur = conn.cursor()
                                        cur.execute("DELETE FROM orcamentos WHERE id=%s AND empresa_id=%s", (int(orc_id), int(emp_id)))
                                        conn.commit()
                                        devolver_conexao(conn)
                                        del st.session_state[key_modo_edicao]
                                        if key_carrinho_edicao in st.session_state: del st.session_state[key_carrinho_edicao]
                                        limpar_cache()
                                        st.rerun()

                            # -------------------------------------------------
                            # CENÁRIO B: MODO DE VISUALIZAÇÃO PADRÃO
                            # -------------------------------------------------
                            else:
                                itens_orcamento = json.loads(row['carrinho_json'])
                                
                                # Exibe a listagem estática simples dos itens salvos
                                for item in itens_orcamento:
                                    st.write(f"- {item['qtd']}x {item['nome']} (R$ {item['unit']:.2f})")
                                
                                st.markdown("---")
                                
                                # Grade de 3 colunas para as ações principais do gerenciamento
                                c1, c2, c3 = st.columns(3)
                                
                                # Ação 1: Puxa os itens de volta para a Frente de Caixa ativa
                                if c1.button("🛒 Jogar no PDV", key=f"resgatar_{orc_id}", type="primary", use_container_width=True):
                                    st.session_state['carrinho'] = itens_orcamento
                                    st.success("Itens carregados! Mude para a aba '🛒 Vendas' para definir as parcelas e finalizar o pedido.")
                                    st.rerun()
                                    
                                # Ação 2: Ativa as chaves que alternam o expander para o Modo de Edição
                                if c2.button("✏️ Editar Orçamento", key=f"ativar_ed_{orc_id}", use_container_width=True):
                                    st.session_state[key_modo_edicao] = True
                                    st.rerun()
                                    
                                # Ação 3: Remove completamente o registro de orçamento do banco de dados
                                if c3.button("🗑️ Excluir Registro", key=f"excluir_{orc_id}", use_container_width=True):
                                    try:
                                        conn = conectar_banco()
                                        cur = conn.cursor()
                                        cur.execute("DELETE FROM orcamentos WHERE id=%s AND empresa_id=%s", (int(orc_id), int(emp_id)))
                                        conn.commit()
                                        devolver_conexao(conn)
                                        st.success("Orçamento excluído do sistema!")
                                        limpar_cache()
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Erro ao remover orçamento: {e}")
                else:
                    st.info("Nenhum orçamento pendente no momento.")                

        if tab_compra:
            with tab_compra:
                st.subheader("📥 Entrada de Mercadorias e Estoque")
                
                # Seletor inteligente do método de entrada
                metodo_entrada = st.radio(
                    "Escolha a forma de lançamento:",
                    ["📥 Importar via PDF", "✍️ Lançamento Manual"],
                    horizontal=True
                )
                
                # --- FLUXO 1: IMPORTAÇÃO VIA PDF ---
                if metodo_entrada == "📥 Importar via PDF":
                    st.info("Faça o upload do PDF do seu pedido. O sistema vai extrair os produtos e gerar uma planilha para você revisar as quantidades.")
                    arquivo_pdf = st.file_uploader("Selecione o arquivo PDF do Pedido", type=["pdf"], key="uploader_pdf_compras")

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
                                    padrao = r'(\d{8})\s+(.*?)\s+R\$\s*([\d.,]+)\s+(\d+)'
                                    
                                    produtos_extraidos = []
                                    for match in re.finditer(padrao, texto_limpo):
                                        codigo = match.group(1)
                                        nome_produto = match.group(2).strip()
                                        preco_str = match.group(3).replace('.', '').replace(',', '.')
                                        quantidade = int(match.group(4))
                                        
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
                
                # --- FLUXO 2: LANÇAMENTO MANUAL (CRUD PROFISSIONAL INTEGRADO) ---
                else:
                    # Inicia o carrinho da compra na sessão se não existir
                    if 'carrinho_compra' not in st.session_state:
                        st.session_state['carrinho_compra'] = []
                        
                    # Busca todos os produtos e fornecedores cadastrados para os seletores
                    query_prods = "SELECT id, referencia, nome FROM produtos WHERE empresa_id = %s ORDER BY nome"
                    df_produtos = carregar_dados_cached(query_prods, (emp_id,))
                    
                    query_forn = "SELECT id, nome FROM fornecedores WHERE empresa_id = %s ORDER BY nome"
                    df_fornecedores = carregar_dados_cached(query_forn, (emp_id,))
                    
                    col_form, col_resumo = st.columns([2, 1.5], gap="large")
                    
                    with col_form:
                        st.markdown("### 🛒 Adicionar Item à Nota")
                        tipo_item = st.radio("O que você está dando entrada?", ["Produto já cadastrado", "Produto novo (Primeira vez)"], horizontal=True)
                        
                        with st.form("form_add_compra", clear_on_submit=True):
                            if tipo_item == "Produto já cadastrado" and not df_produtos.empty:
                                lista_nomes = df_produtos['nome'].tolist()
                                prod_selecionado = st.selectbox("🔍 Busque o Produto", [""] + lista_nomes)
                                
                                c_qtd, c_preco = st.columns(2)
                                qtd_input = c_qtd.number_input("Quantidade Recebida", min_value=1, step=1)
                                custo_input = c_preco.number_input("Preço de Custo Un. (R$)", min_value=0.0, step=0.10, format="%.2f")
                                
                                if st.form_submit_button("➕ Adicionar à Nota", type="primary", use_container_width=True):
                                    if not prod_selecionado:
                                        st.warning("⚠️ Selecione um produto na lista.")
                                    else:
                                        prod_row = df_produtos[df_produtos['nome'] == prod_selecionado].iloc[0]
                                        
                                        st.session_state['carrinho_compra'].append({
                                            "id": int(prod_row['id']),           # ID direto — nunca é nulo
                                            "Código": prod_row['referencia'],
                                            "Produto": prod_selecionado,
                                            "Quantidade": int(qtd_input),
                                            "Preço Un. (R$)": float(custo_input)
                                        })
                                        st.success(f"✅ {prod_selecionado} adicionado ao lote!")
                                        
                            else:
                                st.caption("Preencha para cadastrar este item no estoque automaticamente ao salvar.")
                                c_cod, c_nome = st.columns([1, 2])
                                novo_cod = c_cod.text_input("Código / Referência")
                                novo_nome = c_nome.text_input("Nome do Produto")
                                
                                c_qtd, c_preco = st.columns(2)
                                qtd_input = c_qtd.number_input("Quantidade Recebida", min_value=1, step=1)
                                custo_input = c_preco.number_input("Preço de Custo Un. (R$)", min_value=0.0, step=0.10, format="%.2f")
                                
                                if st.form_submit_button("➕ Adicionar Novo Produto à Nota", type="primary", use_container_width=True):
                                    if not novo_cod or not novo_nome:
                                        st.warning("⚠️ Código e Nome são obrigatórios para produtos novos.")
                                    else:
                                        st.session_state['carrinho_compra'].append({
                                            "Código": novo_cod,
                                            "Produto": novo_nome,
                                            "Quantidade": int(qtd_input),
                                            "Preço Un. (R$)": float(custo_input)
                                        })
                                        st.success(f"✅ {novo_nome} adicionado ao lote!")

                    with col_resumo:
                        st.markdown("### 📦 Resumo da Nota")
                        numero_nota = st.text_input("Nº do Pedido/NF (Obrigatório):", key="nf_manual_crud")
                        
                        lista_forn = [""] + df_fornecedores['nome'].tolist() if not df_fornecedores.empty else [""]
                        sel_fornecedor = st.selectbox("🏭 Fornecedor (Obrigatório):", lista_forn)
                        
                        # --- DADOS FINANCEIROS DA NOTA ---
                        st.markdown("#### 💳 Condições de Pagamento")
                        c_forma, c_parcelas = st.columns([2, 1])
                        forma_pagamento = c_forma.selectbox("Forma:", ["À Vista", "Boleto Parcelado", "Cartão de Crédito Parcelado", "Pix"])
                        
                        if "Parcelado" in forma_pagamento:
                            qtd_parcelas = c_parcelas.number_input("Parcelas", min_value=2, max_value=24, step=1)
                        else:
                            qtd_parcelas = 1
                        
                        if st.session_state['carrinho_compra']:
                            df_carrinho = pd.DataFrame(st.session_state['carrinho_compra'])
                            df_carrinho['Total (R$)'] = df_carrinho['Quantidade'] * df_carrinho['Preço Un. (R$)']
                            
                            st.dataframe(
                                df_carrinho[['Produto', 'Quantidade', 'Total (R$)']], 
                                hide_index=True, 
                                use_container_width=True
                            )
                            
                            # Conversão estrita para float nativo do Python para evitar erros de tipo no banco
                            total_nota = float(df_carrinho['Total (R$)'].sum())
                            st.metric("Total da Entrada", f"R$ {total_nota:,.2f}".replace('.', 'v').replace(',', '.').replace('v', ','))
                            
                            if st.button("💾 Finalizar Entrada no Estoque", type="primary", use_container_width=True):
                                if not numero_nota:
                                    st.error("⚠️ Digite o número do Pedido ou NF para gravar no histórico.")
                                elif not sel_fornecedor:
                                    st.error("⚠️ Selecione o fornecedor que está emitindo esta nota.")
                                else:
                                    try:
                                        id_forn_salvar = int(df_fornecedores[df_fornecedores['nome'] == sel_fornecedor].iloc[0]['id'])
                                        
                                        conn = conectar_banco()
                                        cur = conn.cursor()
                                        
                                        # 1. Salva a Capa da Compra com as colunas de controle financeiro
                                        cur.execute("""
                                            INSERT INTO compras (numero_pedido, data_entrada, valor_total, empresa_id, fornecedor_id, forma_pagamento, qtd_parcelas) 
                                            VALUES (%s, CURRENT_DATE, %s, %s, %s, %s, %s) RETURNING id
                                        """, (numero_nota, total_nota, emp_id, id_forn_salvar, forma_pagamento, qtd_parcelas))
                                        compra_id = cur.fetchone()[0]
                                        
                                        itens_salvos = 0
                                        
                                        # 2. Salva os Itens e Atualiza as Quantidades do Estoque
                                        for item in st.session_state['carrinho_compra']:
                                            v_cod = str(item['Código']).strip()
                                            v_nome = str(item['Produto']).strip()
                                            v_qtd = int(item['Quantidade'])
                                            v_valor = float(item['Preço Un. (R$)'])
                                            prod_id_direto = item.get('id')  # presente para produtos já cadastrados
                                            
                                            cur.execute("""
                                                INSERT INTO itens_compra (compra_id, produto_referencia, nome_produto, quantidade, preco_custo) 
                                                VALUES (%s, %s, %s, %s, %s)
                                            """, (compra_id, v_cod, v_nome, v_qtd, v_valor))
                                            
                                            if prod_id_direto:
                                                # Produto já cadastrado: atualiza diretamente pelo ID (nunca falha)
                                                cur.execute("""
                                                    UPDATE produtos 
                                                    SET quantidade = quantidade + %s, preco_custo = %s 
                                                    WHERE id = %s
                                                """, (v_qtd, v_valor, prod_id_direto))
                                            else:
                                                # Produto novo: verifica por referência antes de inserir
                                                cur.execute("SELECT id FROM produtos WHERE referencia = %s AND empresa_id = %s", (v_cod, emp_id))
                                                prod_existe = cur.fetchone()
                                                if prod_existe:
                                                    cur.execute("UPDATE produtos SET quantidade = quantidade + %s WHERE id = %s", (v_qtd, prod_existe[0]))
                                                else:
                                                    cur.execute("""
                                                        INSERT INTO produtos (nome, quantidade, valor, marca, categoria, empresa_id, referencia) 
                                                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                                                    """, (v_nome, v_qtd, v_valor, "D'Grava", "Geral", emp_id, v_cod))
                                                
                                            itens_salvos += 1
                                            
                                        # 3. Integração Automática com a Tabela contas_pagar (Campos e Tipos Estritos)
                                        valor_parcela = float(total_nota / qtd_parcelas)
                                        hoje_texto = date.today().strftime('%Y-%m-%d')
                                        
                                        for i in range(1, qtd_parcelas + 1):
                                            if qtd_parcelas == 1:
                                                # Lançamento à Vista: Status 'Pago' e datas preenchidas como texto
                                                cur.execute("""
                                                    INSERT INTO contas_pagar (compra_id, fornecedor_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, data_pagamento, status, empresa_id)
                                                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pago', %s)
                                                """, (compra_id, id_forn_salvar, i, qtd_parcelas, valor_parcela, hoje_texto, hoje_texto, emp_id))
                                            else:
                                                # Lançamento Parcelado: Projeção de vencimentos futuros (texto) e status 'Pendente'
                                                data_venc = date.today() + timedelta(days=30 * i)
                                                venc_texto = data_venc.strftime('%Y-%m-%d')
                                                
                                                cur.execute("""
                                                    INSERT INTO contas_pagar (compra_id, fornecedor_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id)
                                                    VALUES (%s, %s, %s, %s, %s, %s, 'Pendente', %s)
                                                """, (compra_id, id_forn_salvar, i, qtd_parcelas, valor_parcela, venc_texto, emp_id))
                                        
                                        conn.commit()
                                        devolver_conexao(conn)
                                        
                                        st.success(f"🎉 Sucesso! A NF {numero_nota} foi registrada. {itens_salvos} itens entraram no estoque e o financeiro foi atualizado.")
                                        st.session_state['carrinho_compra'] = []
                                        limpar_cache()
                                        st.rerun()
                                        
                                    except Exception as e:
                                        st.error(f"Erro ao salvar no banco: {e}")
                                        if 'conn' in locals(): conn.rollback(); devolver_conexao(conn)
                            
                            if st.button("🗑️ Limpar Carrinho", use_container_width=True):
                                st.session_state['carrinho_compra'] = []
                                st.rerun()
                        else:
                            st.info("Nenhum item adicionado à nota ainda. Use o formulário ao lado para começar.")
                            
        if tab_historico_compras:
            with tab_historico_compras:
                st.subheader("📋 Consulta e Estorno de Notas de Entrada")
                
                # Filtros na parte superior
                c_ini, c_fim = st.columns(2)
                data_ini = c_ini.date_input("De:", value=date.today() - timedelta(days=30), format="DD/MM/YYYY", key="filtro_compra_ini")
                data_fim = c_fim.date_input("Até:", value=date.today(), format="DD/MM/YYYY", key="filtro_compra_fim")
                
                # Busca as compras realizadas no período trazendo o Fornecedor mapeado junto
                query_compras = """
                    SELECT c.id, c.numero_pedido, to_char(c.data_entrada, 'DD/MM/YYYY') as data, f.nome as fornecedor, c.valor_total 
                    FROM compras c
                    LEFT JOIN fornecedores f ON c.fornecedor_id = f.id
                    WHERE c.empresa_id = %s AND c.data_entrada BETWEEN %s AND %s
                    ORDER BY c.data_entrada DESC
                """
                df_historico = carregar_dados_cached(query_compras, (emp_id, data_ini, data_fim))
                
                if not df_historico.empty:
                    st.markdown("### 🔍 Selecione uma Entrada para Ver os Itens")
                    
                    # Monta o dicionário incluindo o nome do fornecedor na visualização
                    opcoes_compra = {
                        row['id']: f"📦 Pedido: {row['numero_pedido']} | Fornecedor: {row['fornecedor'] if row['fornecedor'] else 'Não Informado'} | Data: {row['data']} | Total: R$ {row['valor_total']:.2f}"
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
                        df_itens_compra = carregar_dados_cached(query_itens, (int(compra_selecionada_id),))
                        
                        st.markdown("#### 🛒 Itens desta Entrada")
                        st.dataframe(df_itens_compra, use_container_width=True, hide_index=True)
                        
                        dados_compra = df_historico[df_historico['id'] == compra_selecionada_id].iloc[0]
                        st.metric(label="Valor Total da Nota", value=f"R$ {dados_compra['valor_total']:.2f}")
                        
                        # --- ZONA DE ESTORNO DE ESTOQUE E FINANCEIRO ---
                        st.markdown("---")
                        st.warning("⚠️ **Zona de Perigo:** Ao estornar esta entrada, o sistema irá recalcular o estoque físico (subtraindo os itens) e removerá todas as parcelas em aberto ou pagas do Contas a Pagar.")
                        
                        if st.button("🚨 Estornar e Excluir esta Entrada", type="primary", use_container_width=True):
                            try:
                                conn = conectar_banco()
                                cur = conn.cursor()
                                
                                # 1. Puxa os itens da nota selecionada para fazer o estorno físico no estoque
                                cur.execute("SELECT produto_referencia, quantidade FROM itens_compra WHERE compra_id = %s", (int(compra_selecionada_id),))
                                itens_estorno = cur.fetchall()
                                
                                # 2. Retira as quantidades exatas do estoque atual
                                for ref, qtd in itens_estorno:
                                    cur.execute("""
                                        UPDATE produtos 
                                        SET quantidade = quantidade - %s 
                                        WHERE referencia = %s AND empresa_id = %s
                                    """, (int(qtd), str(ref), emp_id))
                                
                                # 3. Deleta o histórico analítico de itens da nota
                                cur.execute("DELETE FROM itens_compra WHERE compra_id = %s", (int(compra_selecionada_id),))
                                
                                # 4. LIMPEZA FINANCEIRA: Remove todas as parcelas geradas por esta compra no contas a pagar
                                cur.execute("DELETE FROM contas_pagar WHERE compra_id = %s", (int(compra_selecionada_id),))
                                
                                # 5. Deleta a capa do pedido da tabela compras
                                cur.execute("DELETE FROM compras WHERE id = %s", (int(compra_selecionada_id),))
                                
                                conn.commit()
                                devolver_conexao(conn)
                                
                                st.success(f"✅ Sucesso! A Entrada {dados_compra['numero_pedido']} e suas respectivas parcelas financeiras foram completamente removidas do sistema.")
                                limpar_cache()
                                st.rerun()
                                
                            except Exception as e:
                                st.error(f"Erro ao processar estorno no banco de dados: {e}")
                                if 'conn' in locals(): conn.rollback(); devolver_conexao(conn)
                else:
                    st.warning("Nenhuma nota de entrada processada neste período.")   
                    
        # ==========================================
        # ABA: MOVIMENTAÇÕES (TROCAS E EMPRÉSTIMOS)
        # ==========================================
        if tab_trocas:
            with tab_trocas:
                st.subheader("🔄 Trocas")
                
                # --- INICIALIZAÇÃO DOS CARRINHOS DE TROCA ---
                if 'troca_saida' not in st.session_state:
                    st.session_state['troca_saida'] = []
                if 'troca_entrada' not in st.session_state:
                    st.session_state['troca_entrada'] = []

                # 1. SELEÇÃO DA CONSULTORA (Filtra apenas tipo = 'T')
                df_consultoras = carregar_dados_cached("SELECT id, nome FROM clientes WHERE empresa_id=%s AND tipo='T' ORDER BY nome", (emp_id,))
                
                if not df_consultoras.empty:
                    lista_consultoras = df_consultoras['nome'].tolist()
                    consultora_sel = st.selectbox("👤 Selecione a Consultora:", options=lista_consultoras)
                    id_consultora = int(df_consultoras[df_consultoras['nome'] == consultora_sel].iloc[0]['id'])
                    
                    st.markdown("---")
                    
                    # Carrega catálogo de produtos para os lançamentos
                    df_produtos = carregar_dados_cached("SELECT id, nome, valor, quantidade, tipo FROM produtos WHERE empresa_id=%s ORDER BY nome", (emp_id,))
                    
                    if not df_produtos.empty:
                        df_produtos['display'] = df_produtos.apply(lambda x: f"{x['nome']} | R$ {x['valor']:.2f} (Estoque: {int(x['quantidade'])})", axis=1)
                        opcoes_prod = df_produtos['display'].tolist()

                        # 2. INTERFACE DE LANÇAMENTO (ABAS INTERNAS)
                        aba_saida, aba_entrada = st.tabs(["📤 O que está SAINDO (Para Consultora)", "📥 O que está ENTRANDO (Retorno)"])
                        
                        # --- ABA DE SAÍDA ---
                        with aba_saida:
                            st.subheader("Produtos que vão para a Consultora")
                            with st.form("form_add_saida", clear_on_submit=True):
                                c1, c2, c3 = st.columns([2, 1, 1])
                                item_sel_s = c1.selectbox("Produto:", options=opcoes_prod)
                                qtd_s = c2.number_input("Qtd Saída:", min_value=1, step=1, value=1)
                                
                                idx_s = opcoes_prod.index(item_sel_s)
                                preco_base_s = float(df_produtos.iloc[idx_s]['valor'])
                                preco_s = c3.number_input("Valor Unit (R$):", min_value=0.0, value=preco_base_s, step=1.0, format="%.2f")
                                
                                if st.form_submit_button("➕ Adicionar à Saída"):
                                    item_info = df_produtos.iloc[idx_s]
                                    if item_info['tipo'] == 'P' and qtd_s > item_info['quantidade']:
                                        st.error("❌ Estoque insuficiente para esta saída!")
                                    else:
                                        st.session_state['troca_saida'].append({
                                            'id': int(item_info['id']),
                                            'nome': str(item_info['nome']),
                                            'qtd': int(qtd_s),
                                            'unit': float(preco_s),
                                            'total': float(qtd_s * preco_s),
                                            'tipo': str(item_info['tipo'])
                                        })
                                        st.rerun()
                            
                            if st.session_state['troca_saida']:
                                st.table(pd.DataFrame(st.session_state['troca_saida'])[['nome', 'qtd', 'unit', 'total']])
                                if st.button("🗑️ Limpar Lista de Saída", key="limpar_s"):
                                    st.session_state['troca_saida'] = []
                                    st.rerun()

                        # --- ABA DE ENTRADA ---
                        with aba_entrada:
                            st.subheader("Produtos que retornam para o seu estoque")
                            with st.form("form_add_entrada", clear_on_submit=True):
                                c1, c2, c3 = st.columns([2, 1, 1])
                                item_sel_e = c1.selectbox("Produto:", options=opcoes_prod)
                                qtd_e = c2.number_input("Qtd Entrada:", min_value=1, step=1, value=1)
                                
                                idx_e = opcoes_prod.index(item_sel_e)
                                preco_base_e = float(df_produtos.iloc[idx_e]['valor'])
                                preco_e = c3.number_input("Valor Unit (R$):", min_value=0.0, value=preco_base_e, step=1.0, format="%.2f")
                                
                                if st.form_submit_button("➕ Adicionar à Entrada"):
                                    item_info = df_produtos.iloc[idx_e]
                                    st.session_state['troca_entrada'].append({
                                        'id': int(item_info['id']),
                                        'nome': str(item_info['nome']),
                                        'qtd': int(qtd_e),
                                        'unit': float(preco_e),
                                        'total': float(qtd_e * preco_e),
                                        'tipo': str(item_info['tipo'])
                                    })
                                    st.rerun()
                                    
                            if st.session_state['troca_entrada']:
                                st.table(pd.DataFrame(st.session_state['troca_entrada'])[['nome', 'qtd', 'unit', 'total']])
                                if st.button("🗑️ Limpar Lista de Entrada", key="limpar_e"):
                                    st.session_state['troca_entrada'] = []
                                    st.rerun()

                    st.markdown("---")
                    st.subheader("📊 Resumo da Operação Atual")
                    
                    total_s = sum(item['total'] for item in st.session_state['troca_saida']) if st.session_state['troca_saida'] else 0.0
                    total_e = sum(item['total'] for item in st.session_state['troca_entrada']) if st.session_state['troca_entrada'] else 0.0
                    diferenca_balanco = total_s - total_e
                    
                    c_m1, c_m2, c_m3 = st.columns(3)
                    c_m1.metric("Total Saída", f"R$ {total_s:.2f}".replace('.', ','))
                    c_m2.metric("Total Entrada", f"R$ {total_e:.2f}".replace('.', ','))
                    
                    if diferenca_balanco == 0:
                        c_m3.metric("Balanço Provisório", "R$ 0,00", delta="Permuta Perfeita")
                    elif diferenca_balanco > 0:
                        c_m3.metric("Balanço Provisório", f"R$ {diferenca_balanco:.2f}".replace('.', ','), delta="Consultora Deve", delta_color="inverse")
                    else:
                        c_m3.metric("Balanço Provisório", f"R$ {abs(diferenca_balanco):.2f}".replace('.', ','), delta="Empresa Deve")

                    st.info("💡 Ao salvar, as quantidades físicas serão atualizadas imediatamente no estoque e a movimentação ficará em Standby.")

                    # 4. BOTÃO DE CONFIRMAÇÃO E GRAVAÇÃO
                    if st.button("💾 Salvar Movimentação em Standby", type="primary", use_container_width=True):
                        if not st.session_state['troca_saida'] and not st.session_state['troca_entrada']:
                            st.error("Adicione pelo menos um item em uma das listas para processar.")
                        else:
                            try:
                                conn = conectar_banco()
                                cur = conn.cursor()
                                
                                cur.execute("""
                                    INSERT INTO trocas (empresa_id, cliente_id, total_saida, total_entrada, diferenca, status_financeiro)
                                    VALUES (%s, %s, %s, %s, %s, 'Em Aberto') RETURNING id
                                """, (emp_id, id_consultora, total_s, total_e, diferenca_balanco))
                                id_troca_gerada = cur.fetchone()[0]
                                
                                for item in st.session_state['troca_saida']:
                                    cur.execute("INSERT INTO trocas_itens (troca_id, produto_id, quantidade, valor_unitario, sentido) VALUES (%s, %s, %s, %s, 'S')",
                                                (id_troca_gerada, item['id'], item['qtd'], item['unit']))
                                    if item['tipo'] == 'P':
                                        cur.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE id=%s", (item['qtd'], item['id']))
                                        
                                for item in st.session_state['troca_entrada']:
                                    cur.execute("INSERT INTO trocas_itens (troca_id, produto_id, quantidade, valor_unitario, sentido) VALUES (%s, %s, %s, %s, 'E')",
                                                (id_troca_gerada, item['id'], item['qtd'], item['unit']))
                                    if item['tipo'] == 'P':
                                        cur.execute("UPDATE produtos SET quantidade = quantidade + %s WHERE id=%s", (item['qtd'], item['id']))
                                
                                conn.commit()
                                devolver_conexao(conn)
                                
                                st.session_state['troca_saida'] = []
                                st.session_state['troca_entrada'] = []
                                st.success(f"Troca Nº {id_troca_gerada} enviada para o Standby! Estoque físico atualizado.")
                                limpar_cache()
                                st.rerun()
                                
                            except Exception as e:
                                st.error(f"Erro ao processar transação: {e}")
                                if 'conn' in locals(): devolver_conexao(conn)

                    # ==========================================
                    # VISÃO APP: ACOMPANHAMENTO DE TROCAS EM STANDBY
                    # ==========================================
                    st.markdown("---")
                    st.subheader("📱 Visão App: Trocas em Standby (Abertas)")
                    
                    df_trocas_abertas = carregar_dados_cached("""
                        SELECT t.id, t.data_movimentacao, c.nome AS consultora, t.total_saida, t.total_entrada, t.cliente_id
                        FROM trocas t 
                        JOIN clientes c ON t.cliente_id = c.id 
                        WHERE t.empresa_id = %s AND t.status_financeiro = 'Em Aberto'
                        ORDER BY t.data_movimentacao DESC
                    """, (emp_id,))
                    
                    if not df_trocas_abertas.empty:
                        for idx, troca_aberta in df_trocas_abertas.iterrows():
                            id_t = troca_aberta['id']
                            nome_con = troca_aberta['consultora']
                            data_t = troca_aberta['data_movimentacao']
                            
                            with st.container(border=True):
                                st.markdown(f"🔄 **Troca Nº {id_t} - {nome_con}**")
                                st.caption(f"📅 Aberta em: {data_t}")
                                
                                with st.expander("🔍 Ver Detalhes e Finalizar Acerto", expanded=False):
                                    df_itens_t = carregar_dados_cached("""
                                        SELECT ti.quantidade, ti.valor_unitario, ti.sentido, p.nome 
                                        FROM trocas_itens ti 
                                        JOIN produtos p ON ti.produto_id = p.id 
                                        WHERE ti.troca_id = %s
                                    """, (id_t,))
                                    
                                    if not df_itens_t.empty:
                                        df_s = df_itens_t[df_itens_t['sentido'] == 'S']
                                        if not df_s.empty:
                                            st.markdown("**📤 Saíram para a Consultora:**")
                                            for _, it in df_s.iterrows():
                                                st.caption(f"▪️ {it['quantidade']}x {it['nome']} (R$ {it['valor_unitario']:.2f})")
                                                
                                        df_e = df_itens_t[df_itens_t['sentido'] == 'E']
                                        if not df_e.empty:
                                            st.markdown("**📥 Retornaram dela:**")
                                            for _, it in df_e.iterrows():
                                                st.caption(f"▪️ {it['quantidade']}x {it['nome']} (R$ {it['valor_unitario']:.2f})")
                                    
                                    t_saida = float(troca_aberta['total_saida'])
                                    t_entrada = float(troca_aberta['total_entrada'])
                                    dif = t_saida - t_entrada
                                    
                                    st.markdown("---")
                                    st.markdown(f"**Balanço:** Saída R$ {t_saida:.2f} | Entrada R$ {t_entrada:.2f}".replace('.', ','))
                                    
                                    if dif == 0:
                                        st.success("⚖️ Valores equivalentes (Permuta Perfeita)")
                                    elif dif > 0:
                                        st.warning(f"⚠️ Consultora pendente em: **R$ {dif:.2f}**".replace('.', ','))
                                    else:
                                        st.info(f"ℹ️ Empresa pendente em: **R$ {abs(dif):.2f}**".replace('.', ','))
                                        
                                    if st.button("🏁 Finalizar e Fechar Troca", key=f"btn_fechar_{id_t}", use_container_width=True, type="primary"):
                                        try:
                                            conn = conectar_banco()
                                            cur = conn.cursor()
                                            
                                            if dif > 0:
                                                status_fin = 'Pendente Consultora'
                                                cur.execute("""
                                                    INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id)
                                                    VALUES (%s, %s, 1, 1, %s, %s, 'Pendente', %s)
                                                """, (int(id_t + 90000), int(troca_aberta['cliente_id']), float(dif), date.today().strftime("%d/%m/%Y"), emp_id))
                                            else:
                                                status_fin = 'Compensado'
                                                
                                            cur.execute("UPDATE trocas SET status_financeiro = %s, diferenca = %s WHERE id = %s", (status_fin, dif, id_t))
                                            conn.commit()
                                            devolver_conexao(conn)
                                            st.success(f"Troca Nº {id_t} finalizada e resolvida financeiramente!")
                                            limpar_cache()
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Erro ao finalizar: {e}")
                                            if 'conn' in locals(): devolver_conexao(conn)
                    else:
                        st.info("Não há nenhuma movimentação de troca em standby no momento.")
                        
                else:
                    st.warning("Nenhuma Consultora cadastrada no sistema. Vá em Cadastros e altere o tipo de um registro para 'Consultora'.")

        # ==========================================
        # ABA: AGENDA DE ATENDIMENTOS
        # ==========================================
        if tab_agenda:
            with tab_agenda:
                st.subheader("📅 Agenda de Atendimentos")
                
                # Criamos duas sub-abas internas para organizar o espaço no celular
                aba_ver_agenda, aba_novo_agendamento = st.tabs(["📱 Visualizar Agenda", "➕ Marcar Horário"])
                
                # ---------------------------------------------------------
                # SUB-ABA 1: VISUALIZAR AGENDA (TIMELINE COM FILTROS AVANÇADOS)
                # ---------------------------------------------------------
                with aba_ver_agenda:
                    from datetime import date, timedelta
                    import datetime
                    hoje = date.today()
                    
                    st.markdown("**🔍 Filtros de Busca:**")
                    
                    # Primeira linha de filtros: Datas (Espremedinhas em 2 colunas)
                    c_dt1, c_dt2 = st.columns(2)
                    dt_inicio = c_dt1.date_input("📅 De:", value=hoje, format="DD/MM/YYYY")
                    dt_fim = c_dt2.date_input("📅 Até:", value=hoje + timedelta(days=7), format="DD/MM/YYYY")
                    
                    # Busca as listas de clientes e colaboradoras no banco para preencher os seletores
                    df_cli_filtro = carregar_dados_cached("SELECT id, nome FROM clientes WHERE empresa_id=%s ORDER BY nome", (emp_id,))
                    df_col_filtro = carregar_dados_cached("SELECT id, nome FROM colaboradores WHERE empresa_id=%s ORDER BY nome", (emp_id,))
                    
                    lista_clientes = ["Todos"] + df_cli_filtro['nome'].tolist() if not df_cli_filtro.empty else ["Todos"]
                    lista_colaboradoras = ["Todos"] + df_col_filtro['nome'].tolist() if not df_col_filtro.empty else ["Todos"]
                    
                    # Segunda linha de filtros: Pessoas
                    c_pes1, c_pes2 = st.columns(2)
                    filtro_cli = c_pes1.selectbox("👤 Cliente:", options=lista_clientes)
                    filtro_col = c_pes2.selectbox("💇‍♀️ Profissional:", options=lista_colaboradoras)
                    
                    # Busca TODOS os agendamentos do período selecionado
                    query_agenda = """
                        SELECT 
                            a.id,
                            a.data_agendamento,
                            a.hora_inicio,
                            c.nome AS cliente,
                            col.nome AS colaboradora,
                            p.nome AS servico,
                            p.valor,
                            a.status
                        FROM agendamentos a
                        JOIN clientes c ON a.cliente_id = c.id
                        JOIN colaboradores col ON a.colaboradora_id = col.id
                        JOIN produtos p ON a.servico_id = p.id
                        WHERE a.empresa_id = %s 
                          AND a.data_agendamento >= %s 
                          AND a.data_agendamento <= %s
                        ORDER BY a.data_agendamento ASC, a.hora_inicio ASC
                    """
                    df_compromissos = carregar_dados_cached(query_agenda, (emp_id, dt_inicio, dt_fim))
                    
                    # MÁGICA DOS NOVOS FILTROS: Corta o DataFrame se você tiver selecionado alguém específico
                    if not df_compromissos.empty:
                        if filtro_cli != "Todos":
                            df_compromissos = df_compromissos[df_compromissos['cliente'] == filtro_cli]
                            
                        if filtro_col != "Todos":
                            df_compromissos = df_compromissos[df_compromissos['colaboradora'] == filtro_col]
                    
                    st.markdown('<hr style="margin: 5px 0px 15px 0px; border: none; border-top: 1px solid #ddd;">', unsafe_allow_html=True)
                    
                    if not df_compromissos.empty:
                        # Pegamos as datas únicas onde há atendimento para criar os Expanders
                        datas_com_agenda = df_compromissos['data_agendamento'].unique()
                        
                        for data_alvo in datas_com_agenda:
                            # Separa apenas os agendamentos deste dia específico
                            df_dia = df_compromissos[df_compromissos['data_agendamento'] == data_alvo]
                            qtd_atendimentos = len(df_dia)
                            
                            # Formata a data para o padrão brasileiro
                            try:
                                data_br = data_alvo.strftime('%d/%m/%Y')
                            except:
                                data_br = str(data_alvo)
                            
                            # Mágica de Usabilidade: Se a data do bloco for HOJE, o expander já vem aberto
                            eh_hoje = (data_br == hoje.strftime('%d/%m/%Y'))
                            
                            # Cria a caixinha inteligente do dia
                            with st.expander(f"📅 {data_br} — {qtd_atendimentos} atendimento(s)", expanded=eh_hoje):
                                
                                for _, compromisso in df_dia.iterrows():
                                    id_agendamento = compromisso['id']
                                    hora_formatada = str(compromisso['hora_inicio'])[0:5]
                                    status_atual = compromisso['status']
                                    
                                    cor_status = "🔵" if status_atual == "Agendado" else "🟢" if status_atual == "Concluído" else "🔴"
                                    
                                    # Card de atendimento
                                    with st.container(border=True):
                                        st.markdown(f"{cor_status} **{hora_formatada}** — 👤 **{compromisso['cliente']}**")
                                        st.markdown(f"💇‍♀️ **Profissional:** {compromisso['colaboradora']} | 🛠️ **Serviço:** {compromisso['servico']}")
                                        st.markdown(f"💰 **Valor:** R$ {compromisso['valor']:.2f}".replace('.', ','))
                                        
                                        # Botões de ação (só aparecem se o status for 'Agendado')
                                        c_btn1, c_btn2, c_btn3 = st.columns(3)
                                        
                                        if status_atual == "Agendado":
                                            if c_btn1.button("✅ Concluir", key=f"btn_concluir_{id_agendamento}", use_container_width=True):
                                                try:
                                                    conn = conectar_banco()
                                                    cur = conn.cursor()
                                                    cur.execute("UPDATE agendamentos SET status = 'Concluído' WHERE id = %s", (id_agendamento,))
                                                    conn.commit()
                                                    devolver_conexao(conn)
                                                    st.success("Atendimento concluído!")
                                                    limpar_cache()
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Erro: {e}")
                                            
                                            if c_btn2.button("❌ Cancelar", key=f"btn_cancelar_{id_agendamento}", use_container_width=True):
                                                try:
                                                    conn = conectar_banco()
                                                    cur = conn.cursor()
                                                    cur.execute("UPDATE agendamentos SET status = 'Cancelado' WHERE id = %s", (id_agendamento,))
                                                    conn.commit()
                                                    devolver_conexao(conn)
                                                    st.warning("Agendamento cancelado.")
                                                    limpar_cache()
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Erro: {e}")
                                        else:
                                            # Se já finalizou, apenas exibe o status na primeira coluna
                                            with c_btn1:
                                                st.caption(f"Status da operação: **{status_atual}**")
                                                
                                        # O botão de Excluir fica sempre visível na terceira coluna
                                        if c_btn3.button("🗑️ Excluir", key=f"btn_excluir_{id_agendamento}", use_container_width=True):
                                            try:
                                                conn = conectar_banco()
                                                cur = conn.cursor()
                                                cur.execute("DELETE FROM agendamentos WHERE id = %s AND empresa_id = %s", (id_agendamento, emp_id))
                                                conn.commit()
                                                devolver_conexao(conn)
                                                st.success("Agendamento excluído!")
                                                limpar_cache()
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Erro: {e}")
                    else:
                        st.info(f"🌴 Nenhum atendimento encontrado no período de {dt_inicio.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')}.")

                # ---------------------------------------------------------
                # SUB-ABA 2: MARCAR NOVO HORÁRIO (AGENDA DINÂMICA)
                # ---------------------------------------------------------
                with aba_novo_agendamento:
                    st.markdown("### 📝 Agendar Novo Serviço")
                    
                    # Carrega as listas necessárias. 
                    df_cli_ag = carregar_dados_cached("SELECT id, nome FROM clientes WHERE empresa_id=%s ORDER BY nome", (emp_id,))
                    df_col_ag = carregar_dados_cached("SELECT id, nome FROM colaboradores WHERE empresa_id=%s ORDER BY nome", (emp_id,))
                    df_ser_ag = carregar_dados_cached("SELECT id, nome, valor, COALESCE(tempo_minutos, 30) AS tempo_estimado FROM produtos WHERE empresa_id=%s AND tipo='S' ORDER BY nome", (emp_id,))
                    
                    if not df_cli_ag.empty and not df_col_ag.empty and not df_ser_ag.empty:
                        
                        # SUBSTITUÍMOS O st.form POR UM st.container PARA A TELA FICAR DINÂMICA
                        with st.container(border=True):
                            
                            # Formata o serviço mostrando o preço e a duração ao lado
                            df_ser_ag['display'] = df_ser_ag.apply(lambda x: f"{x['nome']} (R$ {x['valor']:.2f} | ⏱️ {int(x['tempo_estimado'])} min)", axis=1)
                            sel_servico = st.selectbox("🛠️ Primeiro, selecione o Serviço:", options=df_ser_ag['display'].tolist(), index=None, placeholder="Escolha o procedimento para calcular a grade...")
                            
                            if sel_servico:
                                st.markdown("---")
                                sel_cliente = st.selectbox("👤 Selecione a Cliente:", options=df_cli_ag['nome'].tolist(), index=None, placeholder="Escolha a cliente...")
                                sel_colaboradora = st.selectbox("💇‍♀️ Escolha a Profissional:", options=df_col_ag['nome'].tolist(), index=None, placeholder="Escolha a profissional executora...")
                                
                                c_data, c_hora = st.columns(2)
                                data_escolhida = c_data.date_input("📅 Data do Agendamento:", value=hoje, format="DD/MM/YYYY")
                                
                                # --- O CÁLCULO DINÂMICO DE HORÁRIOS ---
                                idx_ser = df_ser_ag['display'].tolist().index(sel_servico)
                                duracao = int(df_ser_ag.iloc[idx_ser]['tempo_estimado'])
                                if duracao <= 0: duracao = 30 # Proteção extra
                                
                                # Define o horário de funcionamento (Ex: 08:00 às 20:00)
                                hora_abertura = datetime.time(8, 0)
                                hora_fechamento = datetime.time(20, 0)
                                
                                dt_atual = datetime.datetime.combine(data_escolhida, hora_abertura)
                                dt_limite = datetime.datetime.combine(data_escolhida, hora_fechamento)
                                
                                lista_horarios = []
                                while dt_atual <= dt_limite:
                                    lista_horarios.append(dt_atual.strftime("%H:%M"))
                                    dt_atual += datetime.timedelta(minutes=duracao)
                                
                                hora_escolhida = c_hora.selectbox("⏰ Horários Sequenciais Livres:", options=lista_horarios, index=None, placeholder="Selecione o horário de início...")
                                
                                obs_ag = st.text_input("📝 Alguma observação? (Opcional)")
                                
                                # O botão trava (fica cinza) enquanto os campos essenciais não estiverem preenchidos
                                trava_botao = (sel_cliente is None) or (sel_colaboradora is None) or (hora_escolhida is None)
                                
                                # AGORA É UM st.button NORMAL (Vai obedecer à validação da tela perfeitamente)
                                if st.button("🗓️ Confirmar Agendamento", type="primary", use_container_width=True, disabled=trava_botao):
                                    
                                    id_cli_ag = int(df_cli_ag[df_cli_ag['nome'] == sel_cliente].iloc[0]['id'])
                                    id_col_ag = int(df_col_ag[df_col_ag['nome'] == sel_colaboradora].iloc[0]['id'])
                                    id_ser_ag = int(df_ser_ag.iloc[idx_ser]['id'])
                                    
                                    try:
                                        conn = conectar_banco()
                                        cur = conn.cursor()
                                        
                                        # 🔍 O GUARDIÃO
                                        query_verificar_conflito = """
                                            SELECT id 
                                            FROM agendamentos 
                                            WHERE empresa_id = %s 
                                              AND colaboradora_id = %s 
                                              AND data_agendamento = %s 
                                              AND hora_inicio = %s
                                              AND status != 'Cancelado'
                                        """
                                        cur.execute(query_verificar_conflito, (emp_id, id_col_ag, data_escolhida, hora_escolhida))
                                        conflito = cur.fetchone()
                                        
                                        if conflito:
                                            st.error(f"⚠️ **Conflito de Agenda!** A profissional selecionada já possui um compromisso marcado para o dia {data_escolhida.strftime('%d/%m/%Y')} exatamente às {hora_escolhida}.")
                                            devolver_conexao(conn)
                                        else:
                                            cur.execute("""
                                                INSERT INTO agendamentos (empresa_id, cliente_id, colaboradora_id, servico_id, data_agendamento, hora_inicio, observacao)
                                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                            """, (emp_id, id_cli_ag, id_col_ag, id_ser_ag, data_escolhida, hora_escolhida, obs_ag))
                                            conn.commit()
                                            devolver_conexao(conn)
                                            
                                            st.success("🎯 Horário reservado com sucesso!")
                                            limpar_cache()
                                            st.rerun()
                                            
                                    except Exception as e:
                                        st.error(f"Erro ao salvar agendamento: {e}")
                                        if 'conn' in locals(): devolver_conexao(conn)
                            else:
                                st.info("👆 Selecione o procedimento que a cliente deseja para que o sistema monte a grade de horários compatível com o tempo de duração.")
                    else:
                        st.warning("⚠️ Para usar a agenda, certifique-se de ter Clientes, Colaboradoras e Serviços (tipo='S') cadastrados no sistema.")
    
    # ==========================================
    # MÓDULO 4: FINANCEIRO (Contas a Receber e Pagar COMPLETOS)
    # ==========================================
    elif modulo == "💰 Financeiro":
        # Reduz o espaçamento superior e inferior dos blocos de métricas (st.metric)
        st.markdown(
            """
            <style>
            [data-testid="stMetric"] {
                margin-top: -5px;
                margin-bottom: -10px;
            }
            </style>
            """,
            unsafe_allow_html=True
        )
        st.markdown("### 💰 Gestão Financeira")
        
        # --- MUDANÇA: Adicionamos a aba_fluxo_caixa aqui na lista de abas ---
        tab_rec, tab_pag, aba_fluxo_caixa = st.tabs(["🟢 Contas a Receber (Vendas)", "🔴 Contas a Pagar (Despesas)", "💸 Fluxo de Caixa"])
        
        # --- CONTAS A RECEBER 100% RESTAURADO ---
        with tab_rec:
            st.markdown("### 💰 Controle de Parcelas")
            # Adicionado c.telefone na consulta para puxarmos o número do WhatsApp
            df_financeiro = carregar_dados_cached("""
                SELECT cr.id AS "ID Parcela", cr.venda_codigo AS "Nº Venda", c.nome AS "Cliente", c.telefone AS "Telefone",
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
                
                # --- ENVELOPAMENTO DA MATRIZ DE CARD FINANCEIRO ---
                # O resumo inicia compactado para abrir espaço para o painel de baixa no mobile
                with st.expander("📊 Ver Resumo Geral (Recebidos, No Prazo e Atrasos)", expanded=False):
                    col_met1, col_met2, col_met3 = st.columns(3)
                    col_met1.metric("✅ Total Já Recebido", f"R$ {v_rec:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                    col_met2.metric("⏳ A Receber (No Prazo)", f"R$ {(v_pend - v_atr):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                    col_met3.metric("🚨 Pagamentos Atrasados", f"R$ {v_atr:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), delta="- Atenção" if v_atr > 0 else "Tudo em dia!", delta_color="inverse")
                
                #st.markdown("---")
                
                df_p = df_financeiro[df_financeiro['Status'] == 'Pendente']
                
                # --- LÓGICA DE REGISTRAR PAGAMENTO REFORMULADA (CARD LAYOUT MOBILE) ---
                
                # 1. Captura os comandos vindos lá do clique da Visão App
                abrir_recebimento = st.session_state.get('abrir_expander_recebimento', False)
                venda_id_alvo = st.session_state.get('venda_editando', None)
                
                # 2. O expander obedece ao gatilho automático de abertura
                with st.expander("✅ Registrar Recebimento de Parcela", expanded=abrir_recebimento):
                    if not df_p.empty:
                        
                        # 3. FILTRAGEM INTELIGENTE: Descobre quais parcelas exibir
                        if venda_id_alvo is not None:
                            # Se veio o clique da Visão App, filtra apenas as parcelas dessa venda específica
                            df_filtrado = df_p[df_p['Nº Venda'].astype(int) == int(venda_id_alvo)]
                            st.markdown(f"✨ **Mostrando parcelas da Venda Nº {venda_id_alvo}**")
                        else:
                            # Se abriu manualmente, mostra um seletor limpo e curto apenas para escolher a Venda/Cliente
                            df_p['venda_display'] = df_p['Nº Venda'].astype(str) + " - " + df_p['Cliente']
                            opcoes_vendas = sorted(list(df_p['venda_display'].unique()))
                            venda_escolhida = st.selectbox("Escolha a Venda / Cliente:", options=opcoes_vendas)
                            cod_venda_sel = venda_escolhida.split(" - ")[0]
                            df_filtrado = df_p[df_p['Nº Venda'].astype(int) == int(cod_venda_sel)]
                        
                        if not df_filtrado.empty:
                            # Linha divisória em HTML com as margens (espaçamentos) espremidas
                            st.markdown('<hr style="margin: 5px 0px 10px 0px; border: none; border-top: 1px solid #ddd;">', unsafe_allow_html=True)
                            
                            # Campo de data único no topo do painel
                            data_pag_real = st.date_input("📅 Data do Recebimento:", value=hoje, format="DD/MM/YYYY")
                            
                            # 4. RENDERIZAÇÃO DOS CARDS EXCLUSIVOS (Perfeito para leitura no celular)
                            for _, row in df_filtrado.iterrows():
                                idx_b = row['ID Parcela']
                                num_parc = row['Parcela']
                                total_parc = row['De']
                                valor_parc = row['Valor (R$)']
                                venc_parc = row['Vencimento']
                                cliente_nome = row['Cliente']
                                
                                # Cada parcela vira um cartão visual mais compacto
                                with st.container(border=True):
                                    # Linha 1: Cliente e qual é a parcela
                                    st.markdown(f"👤 **{cliente_nome}** — Parc. **{num_parc}/{total_parc}**")
                                    
                                    # Linha 2: Valor e Data lado a lado com fonte em tamanho normal
                                    valor_formatado = f"R$ {valor_parc:.2f}".replace('.', ',')
                                    st.markdown(f"💰 **Valor:** {valor_formatado} &nbsp; | &nbsp; 📅 **Venc:** {venc_parc}")
                                    
                                    # Botão de ação direta
                                    if st.button(f"✅ Confirmar Baixa da Parcela {num_parc}", key=f"btn_baixar_{idx_b}", use_container_width=True):
                                        try:
                                            conn = conectar_banco()
                                            cur = conn.cursor()
                                            
                                            # Executa a baixa cirúrgica pelo ID único da parcela
                                            cur.execute("""
                                                UPDATE contas_receber 
                                                SET status = 'Pago', data_pagamento = %s 
                                                WHERE id = %s AND empresa_id = %s
                                            """, (data_pag_real.strftime("%d/%m/%Y"), idx_b, emp_id))
                                            
                                            conn.commit()
                                            devolver_conexao(conn)
                                            
                                            # Limpa completamente a memória de controle após o sucesso
                                            st.session_state['venda_editando'] = None
                                            st.session_state['abrir_expander_recebimento'] = False
                                            
                                            st.success("Pagamento registrado com sucesso!")
                                            limpar_cache()
                                            st.rerun()
                                            
                                        except Exception as e:
                                            st.error(f"Erro ao salvar no banco: {e}")
                                            if 'conn' in locals(): devolver_conexao(conn)
                            
                            # Botão extra para caso você queira fechar o painel sem baixar nada
                            st.markdown("---")
                            if st.button("❌ Cancelar / Fechar Seleção", use_container_width=True):
                                st.session_state['venda_editando'] = None
                                st.session_state['abrir_expander_recebimento'] = False
                                st.rerun()
                        else:
                            st.info("Nenhuma parcela pendente encontrada para este registro.")
                    else:
                        st.success("🎉 Nenhuma parcela pendente! Todos os clientes estão em dia.")
                        
                # --- NOVO EXPANDER DE LEMBRETE DO WHATSAPP ---
                with st.expander("📲 Enviar Lembrete via WhatsApp", expanded=False):
                    if not df_p.empty:
                        import urllib.parse
                        
                        op_lembrete = df_p.apply(lambda x: f"Venda {x['Nº Venda']} | {x['Cliente']} | Parc {x['Parcela']}/{x['De']} | R$ {x['Valor (R$)']:.2f} | Venc: {x['Vencimento']}", axis=1).tolist()
                        lembrete_sel = st.selectbox("Selecione a parcela para enviar lembrete:", options=op_lembrete, key="sel_lembrete")
                        
                        if lembrete_sel:
                            idx_l = op_lembrete.index(lembrete_sel)
                            linha_sel = df_p.iloc[idx_l]
                            
                            nome_cli = linha_sel['Cliente']
                            telefone_cli = linha_sel['Telefone']
                            valor_parc = linha_sel['Valor (R$)']
                            data_venc = linha_sel['Vencimento']
                            
                            valor_formatado = f"{valor_parc:.2f}".replace('.', ',')
                            
                            msg = f"Olá, {nome_cli}! 🌸 Tudo bem com você?\n\n"
                            msg += f"Passando aqui rapidinho só para deixar um lembrete sobre a sua parcela de R$ {valor_formatado} referente aos seus produtinhos, com vencimento para o dia {data_venc}.\n\n"
                            msg += "Qualquer dúvida ou se precisar de algo, estou à disposição! Um ótimo dia para você! ✨"

                            st.text_area("Pré-visualização da Mensagem:", value=msg, height=180, disabled=True)

                            if pd.notna(telefone_cli) and str(telefone_cli).strip() != "":
                                tel_limpo = ''.join(filter(str.isdigit, str(telefone_cli)))
                                if len(tel_limpo) >= 10:
                                    if not tel_limpo.startswith('55'): tel_limpo = '55' + tel_limpo 
                                    link_wpp = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                                    st.link_button("🟢 Enviar Lembrete no WhatsApp", link_wpp, type="primary", use_container_width=True)
                                else: 
                                    st.warning("⚠️ Telefone incompleto no cadastro (precisa ter DDD).")
                            else: 
                                st.warning("⚠️ Cliente sem telefone cadastrado.")
                    else:
                        st.success("🎉 Nenhuma parcela pendente para cobrar!")
                
                #st.markdown("---")

                # --- LÓGICA PARA REAJUSTE DE PARCELAS E DATAS ---
                with st.expander("⚖️ Reajustar Valores e Datas das Parcelas"):
                    st.markdown("Use esta opção quando precisar alterar o valor ou a data de vencimento das parcelas (o total da venda deve ser mantido).")
    
                    venda_ajuste = st.number_input("Digite o Nº da Venda (ex: 36)", min_value=1, step=1, key="num_ajuste_venda")
    
                    if st.button("Buscar Parcelas"):
                        st.session_state['venda_editando'] = venda_ajuste
        
                    if 'venda_editando' in st.session_state:
                        v_id = st.session_state['venda_editando']
        
                        df_parc = carregar_dados_cached("SELECT * FROM contas_receber WHERE venda_codigo=%s AND empresa_id=%s ORDER BY num_parcela", (v_id, emp_id))
        
                        if not df_parc.empty:
                            total_original = float(df_parc['valor_parcela'].sum())
                            st.info(f"💰 **Valor Total Original da Venda:** R$ {total_original:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
            
                            with st.form(f"f_reajuste_{v_id}"):
                                novos_dados = {}
                                import datetime
                
                                for index, row in df_parc.iterrows():
                                    st.write(f"**Parcela {row['num_parcela']} de {row['total_parcelas']}** - Status: {row['status']}")
                                    
                                    # Converte a data string do banco (DD/MM/YYYY) para objeto date do Python
                                    try:
                                        data_atual = datetime.datetime.strptime(row['data_vencimento'], "%d/%m/%Y").date()
                                    except:
                                        data_atual = datetime.date.today() # Proteção anti-erro
                                        
                                    # Coloca o Valor e a Data lado a lado
                                    col_val, col_dat = st.columns(2)
                                    
                                    novo_val = col_val.number_input(
                                        f"Novo Valor (R$)", 
                                        value=float(row['valor_parcela']), 
                                        min_value=0.0, 
                                        format="%.2f",
                                        key=f"val_{row['id']}"
                                    )
                                    
                                    nova_data = col_dat.date_input(
                                        "Nova Data de Vencimento",
                                        value=data_atual,
                                        format="DD/MM/YYYY",
                                        key=f"dat_{row['id']}"
                                    )
                                    
                                    # Guarda o valor e a data formatada de volta para string
                                    novos_dados[row['id']] = {
                                        'valor': novo_val, 
                                        'data': nova_data.strftime("%d/%m/%Y")
                                    }
                                    
                                    st.markdown("---")
                
                                if st.form_submit_button("💾 Validar e Salvar Reajuste"):
                                    # Soma os novos valores dentro do dicionário
                                    soma_novas_parcelas = sum(item['valor'] for item in novos_dados.values())
                    
                                    if round(soma_novas_parcelas, 2) != round(total_original, 2):
                                        st.error(f"❌ **Operação Bloqueada:** A soma das novas parcelas (R$ {soma_novas_parcelas:.2f}) é diferente do total da venda (R$ {total_original:.2f}). A diferença é de R$ {abs(total_original - soma_novas_parcelas):.2f}.")
                                    else:
                                        conn = conectar_banco()
                                        for parcela_id, dados in novos_dados.items():
                                            # Atualiza agora o valor_parcela E a data_vencimento no banco
                                            conn.cursor().execute(
                                                "UPDATE contas_receber SET valor_parcela=%s, data_vencimento=%s WHERE id=%s AND empresa_id=%s", 
                                                (dados['valor'], dados['data'], parcela_id, emp_id)
                                            )
                                        conn.commit()
                                        devolver_conexao(conn)
                        
                                        st.success("✅ Valores e datas reajustados com sucesso!")
                                        del st.session_state['venda_editando']
                                        limpar_cache()
                                        st.rerun()
                        else:
                            st.warning("Nenhuma parcela encontrada para esta venda.")

            # --- TABELA DE LEITURA COMPLETA (COM FILTRO DE CLIENTE E STATUS) ---
            st.subheader("📋 Relatório de Parcelas e Boletos")
            
            # 1. Busca os dados no banco e cria a variável df_receber_geral
            df_receber_geral = carregar_dados_cached("""
                SELECT cr.venda_codigo AS "Nº Venda",
                       c.nome AS "Cliente",
                       cr.num_parcela AS "Parcela",
                       cr.total_parcelas AS "De",
                       cr.valor_parcela AS "Valor (R$)",
                       cr.data_vencimento AS "Vencimento",
                       cr.status AS "Status"
                FROM contas_receber cr
                LEFT JOIN clientes c ON cr.cliente_id = c.id
                WHERE cr.empresa_id = %s
                ORDER BY TO_DATE(cr.data_vencimento, 'DD/MM/YYYY') DESC
            """, (emp_id,))
            
            if not df_receber_geral.empty:
                import datetime
                hoje = datetime.date.today()
                
                # Cria uma coluna de data real (oculta) para a matemática de atrasos funcionar
                df_receber_geral['Data_Venc_Obj'] = pd.to_datetime(df_receber_geral['Vencimento'], format='%d/%m/%Y', errors='coerce').dt.date
                
                col_f1, col_f2 = st.columns([1, 2])
                
                # 2. Filtro de Cliente (Busca os nomes únicos no dataframe)
                lista_clientes = ["Todos os Clientes"] + sorted(df_receber_geral['Cliente'].dropna().unique().tolist())
                cliente_selecionado = col_f1.selectbox("🔍 Buscar por Cliente:", options=lista_clientes)
                
                # 3. Filtro de Status
                filtro_status_receber = col_f2.radio("Filtrar por Status da Parcela:", ["Todos", "Pendentes", "Pagos", "Atrasados"], horizontal=True, key="rad_status_receber")
                
                st.markdown("---")
                
                # 4. Aplica o filtro de cliente e calcula as métricas individuais
                df_view_receber = df_receber_geral.copy()
                
                if cliente_selecionado != "Todos os Clientes":
                    df_view_receber = df_view_receber[df_view_receber['Cliente'] == cliente_selecionado]
                    
                    # Calcula as métricas exclusivas do cliente selecionado
                    v_pago_cli = df_view_receber[df_view_receber['Status'] == 'Pago']['Valor (R$)'].sum()
                    v_aberto_cli = df_view_receber[df_view_receber['Status'] == 'Pendente']['Valor (R$)'].sum()
                    mask_atraso_cli = (df_view_receber['Status'] == 'Pendente') & (df_view_receber['Data_Venc_Obj'] < hoje)
                    v_atraso_cli = df_view_receber[mask_atraso_cli]['Valor (R$)'].sum()
                    v_no_prazo_cli = v_aberto_cli - v_atraso_cli
                    
                    st.markdown(f"**👤 Resumo Financeiro: {cliente_selecionado}**")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("✅ Total Já Pago", f"R$ {v_pago_cli:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                    c2.metric("⏳ A Pagar (No Prazo)", f"R$ {v_no_prazo_cli:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                    c3.metric("🚨 Pagamentos Atrasados", f"R$ {v_atraso_cli:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), delta="- Dívida" if v_atraso_cli > 0 else "Tudo em dia!", delta_color="inverse")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                
                # 5. Aplica o filtro de status em cima do resultado (geral ou por cliente)
                if filtro_status_receber == "Pendentes":
                    df_view_receber = df_view_receber[df_view_receber['Status'] == 'Pendente']
                elif filtro_status_receber == "Pagos":
                    df_view_receber = df_view_receber[df_view_receber['Status'] == 'Pago']
                elif filtro_status_receber == "Atrasados":
                    df_view_receber = df_view_receber[(df_view_receber['Status'] == 'Pendente') & (df_view_receber['Data_Venc_Obj'] < hoje)]
                
                # 6. Exibe a tabela final
                df_exibicao_receber = df_view_receber.drop(columns=['Data_Venc_Obj'], errors='ignore')
                st.dataframe(df_exibicao_receber, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhuma conta a receber registrada.")    
                
        # --- CONTAS A PAGAR COMPLETÃO (CRUD + BAIXA) ---
        with tab_pag:
            st.markdown("### 🔴 Controle de Compromissos e Despesas")
            
            # 1. Carrega todas as contas a pagar ordenando nativamente pelo texto YYYY-MM-DD
            df_pagar_geral = carregar_dados_cached("""
                SELECT cp.id AS "ID", f.nome AS "Fornecedor", cp.num_parcela AS "Parcela", 
                       cp.total_parcelas AS "De", cp.valor_parcela AS "Valor (R$)", 
                       cp.data_vencimento AS "Vencimento", cp.status AS "Status", cp.data_pagamento AS "Data Pagto"
                FROM contas_pagar cp 
                JOIN fornecedores f ON cp.fornecedor_id = f.id 
                WHERE cp.empresa_id = %s 
                ORDER BY cp.data_vencimento ASC
            """, (emp_id,))
            
            # 2. Carrega a lista de fornecedores para os formulários de cadastro/edição
            df_forn_select = carregar_dados_cached("SELECT id, nome FROM fornecedores WHERE empresa_id = %s ORDER BY nome", (emp_id,))
            
            hoje = date.today()
            
            # --- CARDS DE MÉTRICAS DO CONTAS A PAGAR ---
            if not df_pagar_geral.empty:
                # O Pandas infere a data automaticamente, independente de como veio do banco
                df_pagar_geral['Data_Venc_Obj'] = pd.to_datetime(df_pagar_geral['Vencimento'], errors='coerce').dt.date
                
                v_pago = df_pagar_geral[df_pagar_geral['Status'] == 'Pago']['Valor (R$)'].sum()
                v_pend_pag = df_pagar_geral[df_pagar_geral['Status'] == 'Pendente']['Valor (R$)'].sum()
                mask_atraso_pag = (df_pagar_geral['Status'] == 'Pendente') & (df_pagar_geral['Data_Venc_Obj'] < hoje)
                v_atr_pag = df_pagar_geral[mask_atraso_pag]['Valor (R$)'].sum()
                
                col_p1, col_p2, col_p3 = st.columns(3)
                col_p1.metric("✅ Total Já Pago", f"R$ {v_pago:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                col_p2.metric("⏳ A Pagar (No Prazo)", f"R$ {(v_pend_pag - v_atr_pag):,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
                col_p3.metric("🚨 Despesas Atrasadas", f"R$ {v_atr_pag:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."), delta="- Alerta" if v_atr_pag > 0 else "Tudo em dia!", delta_color="inverse")
            else:
                col_p1, col_p2, col_p3 = st.columns(3)
                col_p1.metric("✅ Total Já Pago", "R$ 0,00")
                col_p2.metric("⏳ A Pagar (No Prazo)", "R$ 0,00")
                col_p3.metric("🚨 Despesas Atrasadas", "R$ 0,00", delta="Tudo em dia!")

            st.markdown("---")
            
            # --- OPERAÇÃO 1: 💰 REGISTRAR PAGAMENTO (DAR BAIXA) ---
            with st.expander("💰 Dar Baixa em Despesa (Marcar como Paga)", expanded=False):
                if not df_pagar_geral.empty:
                    df_p_pendentes = df_pagar_geral[df_pagar_geral['Status'] == 'Pendente']
                    if not df_p_pendentes.empty:
                        with st.form("form_baixa_pagar"):
                            # Ajuste de exibição da data para o Dropdown
                            df_p_pendentes_view = df_p_pendentes.copy()
                            df_p_pendentes_view['Venc_BR'] = pd.to_datetime(df_p_pendentes_view['Vencimento']).dt.strftime('%d/%m/%Y')
                            
                            op_baixa_p = df_p_pendentes_view.apply(lambda x: f"ID {x['ID']} | {x['Fornecedor']} | Parc {x['Parcela']}/{x['De']} | R$ {x['Valor (R$)']:.2f} | Venc: {x['Venc_BR']}", axis=1).tolist()
                            despesa_sel = st.selectbox("Selecione a despesa que foi paga:", options=op_baixa_p)
                            
                            c_b1, c_b2 = st.columns([1, 2])
                            data_pagto_real = c_b1.date_input("Data do Pagamento Efetivo", value=hoje, format="DD/MM/YYYY", key="dt_pagto_desp")
                            
                            if st.form_submit_button("🔴 Confirmar Pagamento", type="primary"):
                                id_desp_baixa = int(despesa_sel.split("ID ")[1].split(" |")[0])
                                conn = conectar_banco()
                                # Salva como YYYY-MM-DD
                                conn.cursor().execute("UPDATE contas_pagar SET status = 'Pago', data_pagamento = %s WHERE id = %s AND empresa_id = %s", (data_pagto_real.strftime("%Y-%m-%d"), id_desp_baixa, emp_id))
                                conn.commit()
                                devolver_conexao(conn)
                                st.success("Despesa baixada com sucesso no fluxo financeiro!")
                                limpar_cache()
                                st.rerun()
                    else:
                        st.success("🎉 Não há nenhuma conta a pagar pendente! Tudo quitado.")
                else:
                    st.info("Nenhum lançamento encontrado para dar baixa.")
            
            # --- OPERAÇÃO 2: ➕ LANÇAR NOVA DESPESA MANUAL (C DO CRUD) ---
            with st.expander("➕ Lançar Nova Despesa Manual", expanded=False):
                if not df_forn_select.empty:
                    with st.form("form_novo_contas_pagar", clear_on_submit=True):
                        forn_nome_sel = st.selectbox("Fornecedor / Origem da Despesa:", options=df_forn_select['nome'].tolist())
                        
                        col_l1, col_l2, col_l3 = st.columns(3)
                        valor_total_manual = col_l1.number_input("Valor por Parcela (R$):", min_value=0.01, format="%.2f")
                        tot_parc_manual = col_l2.number_input("Total de Parcelas:", min_value=1, max_value=36, value=1, step=1)
                        data_1_venc_manual = col_l3.date_input("Data do 1º Vencimento:", value=hoje, format="DD/MM/YYYY")
                        
                        if st.form_submit_button("💾 Salvar Lançamento"):
                            id_forn_manual = int(df_forn_select[df_forn_select['nome'] == forn_nome_sel].iloc[0]['id'])
                            conn = conectar_banco()
                            cur = conn.cursor()
                            
                            for i in range(1, int(tot_parc_manual) + 1):
                                venc_parc_manual = data_1_venc_manual + timedelta(days=30 * (i - 1))
                                cur.execute("""
                                    INSERT INTO contas_pagar (fornecedor_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id)
                                    VALUES (%s, %s, %s, %s, %s, 'Pendente', %s)
                                """, (id_forn_manual, i, int(tot_parc_manual), float(valor_total_manual), venc_parc_manual.strftime("%Y-%m-%d"), emp_id))
                            
                            conn.commit()
                            devolver_conexao(conn)
                            st.success(f"Despesa com {tot_parc_manual} parcela(s) lançada com sucesso!")
                            limpar_cache()
                            st.rerun()
                else:
                    st.warning("⚠️ Cadastre pelo menos um Fornecedor na aba anterior antes de lançar despesas manuais.")

            # --- OPERAÇÃO 3: ✏️ EDITAR OU 🗑️ EXCLUIR LANÇAMENTO (U & D DO CRUD) ---
            with st.expander("✏️ Editar ou 🗑️ Cancelar Lançamento", expanded=False):
                if not df_pagar_geral.empty:
                    # Ajuste visual para edição
                    df_edicao_view = df_pagar_geral.copy()
                    df_edicao_view['Venc_BR'] = pd.to_datetime(df_edicao_view['Vencimento']).dt.strftime('%d/%m/%Y')
                    op_edicao_p = df_edicao_view.apply(lambda x: f"ID {x['ID']} | {x['Fornecedor']} | Parc {x['Parcela']}/{x['De']} | R$ {x['Valor (R$)']:.2f} [{x['Status']}]", axis=1).tolist()
                    
                    desp_edicao_sel = st.selectbox("Selecione a despesa para alterar ou remover:", options=op_edicao_p, key="sel_crud_desp")
                    id_desp_crud = int(desp_edicao_sel.split("ID ")[1].split(" |")[0])
                    
                    linha_atual_desp = df_pagar_geral[df_pagar_geral['ID'] == id_desp_crud].iloc[0]
                    
                    col_cr1, col_cr2 = st.columns(2)
                    
                    # Sub-Formulário de Edição (Update)
                    with col_cr1:
                        st.markdown("**✏️ Formulário de Edição**")
                        try: date_v_form = datetime.strptime(str(linha_atual_desp['Vencimento']), "%Y-%m-%d").date()
                        except: date_v_form = hoje
                        
                        with st.form("form_update_despesa_individual"):
                            novo_v_desp = st.number_input("Valor da Parcela (R$)", min_value=0.01, value=float(linha_atual_desp['Valor (R$)']), format="%.2f")
                            novo_venc_desp = st.date_input("Data de Vencimento", value=date_v_form, format="DD/MM/YYYY")
                            
                            novo_pagto_desp_val = linha_atual_desp['Data Pagto']
                            if linha_atual_desp['Status'] == 'Pago':
                                try: date_p_form = datetime.strptime(str(linha_atual_desp['Data Pagto']), "%Y-%m-%d").date()
                                except: date_p_form = hoje
                                dt_p_input = st.date_input("Data do Pagamento", value=date_p_form, format="DD/MM/YYYY")
                                novo_pagto_desp_val = dt_p_input.strftime("%Y-%m-%d")
                            
                            if st.form_submit_button("💾 Atualizar Dados"):
                                conn = conectar_banco()
                                conn.cursor().execute("""
                                    UPDATE contas_pagar 
                                    SET valor_parcela = %s, data_vencimento = %s, data_pagamento = %s 
                                    WHERE id = %s AND empresa_id = %s
                                """, (float(novo_v_desp), novo_venc_desp.strftime("%Y-%m-%d"), novo_pagto_desp_val, id_desp_crud, emp_id))
                                conn.commit()
                                devolver_conexao(conn)
                                st.success("Lançamento atualizado com sucesso!")
                                limpar_cache()
                                st.rerun()
                                
                    # Sub-Formulário de Exclusão (Delete)
                    with col_cr2:
                        st.markdown("**🗑️ Exclusão Definitiva**")
                        st.warning("Atenção: A remoção deste compromisso financeiro apagará o histórico permanentemente.")
                        with st.form("form_delete_despesa_individual"):
                            st.write(f"Confirma a exclusão da despesa ID {id_desp_crud}?")
                            if st.form_submit_button("🚨 Excluir Permanentemente", type="primary"):
                                conn = conectar_banco()
                                conn.cursor().execute("DELETE FROM contas_pagar WHERE id = %s AND empresa_id = %s", (id_desp_crud, emp_id))
                                conn.commit()
                                devolver_conexao(conn)
                                st.success("Despesa removida com sucesso!")
                                limpar_cache()
                                st.rerun()
                else:
                    st.info("Nenhuma despesa disponível para alteração.")

            st.markdown("---")
            
            # --- TABELA DE LEITURA COMPLETA (R DO CRUD) ---
            st.subheader("📋 Relatório Estatístico de Despesas")
            if not df_pagar_geral.empty:
                filtro_status_pagar = st.radio("Filtrar por Status do Compromisso:", ["Todos", "Pendentes", "Pagos", "Atrasados"], horizontal=True, key="rad_status_pagar")
                
                df_view_pagar = df_pagar_geral.copy()
                if filtro_status_pagar == "Pendentes":
                    df_view_pagar = df_view_pagar[df_view_pagar['Status'] == 'Pendente']
                elif filtro_status_pagar == "Pagos":
                    df_view_pagar = df_view_pagar[df_view_pagar['Status'] == 'Pago']
                elif filtro_status_pagar == "Atrasados":
                    df_view_pagar = df_view_pagar[(df_view_pagar['Status'] == 'Pendente') & (df_view_pagar['Data_Venc_Obj'] < hoje)]
                
                # Oculta a coluna de objeto e formata as datas para DD/MM/YYYY para o usuário final
                df_exibicao_pagar = df_view_pagar.drop(columns=['Data_Venc_Obj'], errors='ignore')
                df_exibicao_pagar['Vencimento'] = pd.to_datetime(df_exibicao_pagar['Vencimento']).dt.strftime('%d/%m/%Y')
                
                # Mascara o Data Pagto se for nulo
                df_exibicao_pagar['Data Pagto'] = pd.to_datetime(df_exibicao_pagar['Data Pagto']).dt.strftime('%d/%m/%Y').fillna('-')

                st.dataframe(df_exibicao_pagar, use_container_width=True, hide_index=True)
            else:
                st.info("Nenhuma conta a pagar registrada.")
                
        # --- FLUXO DE CAIXA (NOVO BLOCO) ---
        with aba_fluxo_caixa:
            st.subheader("💸 Fluxo de Caixa")
            
            query_fluxo = """
                SELECT 
                    cr.data_pagamento AS data_movimento,
                    'Entrada' AS tipo,
                    'Recbto Venda #' || cr.venda_codigo || ' (Parc ' || cr.num_parcela || '/' || cr.total_parcelas || ')' AS descricao,
                    cr.valor_parcela AS valor
                FROM contas_receber cr
                WHERE cr.empresa_id = %s AND cr.status = 'Pago'
                
                UNION ALL
                
                SELECT 
                    cp.data_pagamento AS data_movimento,
                    'Saída' AS tipo,
                    'Pgto Fornecedor (Parc ' || cp.num_parcela || '/' || cp.total_parcelas || ')' AS descricao,
                    cp.valor_parcela AS valor
                FROM contas_pagar cp
                WHERE cp.empresa_id = %s AND cp.status = 'Pago'
            """
            
            df_fluxo = carregar_dados_cached(query_fluxo, (emp_id, emp_id))
            
            if not df_fluxo.empty:
                df_fluxo = df_fluxo.dropna(subset=['data_movimento'])
                df_fluxo['Data_Obj'] = pd.to_datetime(df_fluxo['data_movimento'], format='%d/%m/%Y', errors='coerce').dt.date
                
                st.write("### 🔍 Período do Fluxo")
                c1, c2 = st.columns(2)
                hoje = date.today()
                d_ini = c1.date_input("Data Inicial", value=hoje.replace(day=1), format="DD/MM/YYYY", key="fluxo_ini")
                d_fim = c2.date_input("Data Final", value=hoje, format="DD/MM/YYYY", key="fluxo_fim")                
                if d_ini and d_fim:
                    df_filtrado = df_fluxo[(df_fluxo['Data_Obj'] >= d_ini) & (df_fluxo['Data_Obj'] <= d_fim)]
                    
                    if not df_filtrado.empty:
                        total_entradas = float(df_filtrado[df_filtrado['tipo'] == 'Entrada']['valor'].sum())
                        total_saidas = float(df_filtrado[df_filtrado['tipo'] == 'Saída']['valor'].sum())
                        saldo = total_entradas - total_saidas
                        
                        st.write("---")
                        col_ent, col_sai, col_sal = st.columns(3)
                        col_ent.metric("Entradas (+)", f"R$ {total_entradas:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
                        col_sai.metric("Saídas (-)", f"R$ {total_saidas:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
                        col_sal.metric("Saldo do Período", f"R$ {saldo:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
                        
                        st.write("---")
                        
                        df_grafico = df_filtrado.groupby(['Data_Obj', 'tipo'])['valor'].sum().reset_index()
                        cores = {'Entrada': '#00b050', 'Saída': '#ff0000'}
                        
                        fig_fluxo = px.bar(
                            df_grafico, 
                            x='Data_Obj', 
                            y='valor', 
                            color='tipo', 
                            barmode='group',
                            title="Movimentação Diária",
                            color_discrete_map=cores
                        )
                        st.plotly_chart(fig_fluxo, use_container_width=True)
                        
                        # --- TABELA DE EXTRATO DETALHADO ---
                        st.write("### 📄 Extrato Detalhado")
                        
                        # 1º: Ordena os dados enquanto a coluna 'Data_Obj' ainda existe no DataFrame
                        df_filtrado = df_filtrado.sort_values(by=['Data_Obj'], ascending=False)
                        
                        # 2º: Copia apenas as colunas que queremos mostrar
                        df_extrato = df_filtrado[['data_movimento', 'tipo', 'descricao', 'valor']].copy()
                        
                        # Formata o valor para dinheiro
                        df_extrato['valor'] = df_extrato['valor'].apply(lambda x: f"R$ {float(x):,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
                        
                        # Renomeia as colunas para ficar bonito na tela
                        df_extrato.rename(columns={
                            'data_movimento': 'Data',
                            'tipo': 'Tipo',
                            'descricao': 'Descrição',
                            'valor': 'Valor'
                        }, inplace=True)
                        
                        st.dataframe(df_extrato, use_container_width=True, hide_index=True)                        
                    else:
                        st.warning("Não há movimentações financeiras concluídas (pagas/recebidas) no período selecionado.")
            else:
                st.info("Ainda não há dados de contas pagas ou recebidas para gerar o fluxo de caixa.")
                
    # ==========================================================
    # MÓDULO 5: CRM (COM FILTRO DINÂMICO DE ENVIO)
    # ==========================================================
    elif modulo == "📣 CRM & Pós-Venda":
        # Reduz o espaçamento superior e inferior dos blocos de métricas (st.metric)
        st.markdown(
            """
            <style>
            [data-testid="stMetric"] {
                margin-top: -25px;
                margin-bottom: -10px;
            }
            </style>
            """,
            unsafe_allow_html=True
        )
        st.markdown("### 📣 Gestão de Relacionamento: Método 2+2+2")
        st.markdown("Acompanhe o ciclo de vida dos seus clientes e gere recompras automáticas.")
        
        # 1. A SUPER QUERY DO CRM: Filtra e esconde quem já recebeu a mensagem daquela etapa
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
                ((CURRENT_DATE - TO_DATE(v.data_venda, 'DD/MM/YYYY')) BETWEEN 2 AND 5
                  AND NOT EXISTS (SELECT 1 FROM crm_contatos cc WHERE cc.venda_codigo = v.codigo_venda AND cc.tipo_contato = '2d' AND cc.empresa_id = v.empresa_id))
                OR
                ((CURRENT_DATE - TO_DATE(v.data_venda, 'DD/MM/YYYY')) BETWEEN 14 AND 20
                  AND NOT EXISTS (SELECT 1 FROM crm_contatos cc WHERE cc.venda_codigo = v.codigo_venda AND cc.tipo_contato = '2s' AND cc.empresa_id = v.empresa_id))
                OR
                ((CURRENT_DATE - TO_DATE(v.data_venda, 'DD/MM/YYYY')) >= 60
                  AND NOT EXISTS (SELECT 1 FROM crm_contatos cc WHERE cc.venda_codigo = v.codigo_venda AND cc.tipo_contato = '2m' AND cc.empresa_id = v.empresa_id))
            )
            GROUP BY c.id, c.nome, c.telefone, v.codigo_venda, v.data_venda
            ORDER BY dias_passados ASC
        """
        
        df_crm = carregar_dados_cached(query_crm, (emp_id,))
        
        # 2. Inicializando as listas vazias
        df_2_dias = pd.DataFrame()
        df_2_semanas = pd.DataFrame()
        df_2_meses = pd.DataFrame()
        
        if not df_crm.empty:
            # Separando os lotes com base nos dias passados
            df_2_dias = df_crm[(df_crm['dias_passados'] >= 2) & (df_crm['dias_passados'] <= 5)]
            df_2_semanas = df_crm[(df_crm['dias_passados'] >= 14) & (df_crm['dias_passados'] <= 20)]
            df_2_meses = df_crm[(df_crm['dias_passados'] >= 60)]
            
        # 3. --- CARDS DE MÉTRICAS DINÂMICAS ---
        st.markdown("---")
        c1, c2, c3 = st.columns(3)
        c1.metric("🟢 2 Dias (Satisfação)", f"{len(df_2_dias)} clientes")
        c2.metric("🟡 2 Semanas (Acompanhamento)", f"{len(df_2_semanas)} clientes")
        c3.metric("🔴 2 Meses (Reposição)", f"{len(df_2_meses)} clientes")
        #st.markdown("---")
        
        # 4. --- ABAS DE INTERAÇÃO ---
        tab_2d, tab_2s, tab_2m = st.tabs(["🟢 Contatos de 2 Dias", "🟡 Contatos de 2 Semanas", "🔴 Contatos de 2 Meses"])
        
        # FUNÇÃO ATUALIZADA: Agora gera os botões lado a lado e grava a baixa no banco
        def gerar_linha_contato(row, mensagem_padrao, tipo_contato):
            st.markdown(f"**Cliente:** {row['cliente']} | **Venda:** Nº {row['codigo_venda']} | **Data:** {row['data_venda']} ({row['dias_passados']} dias atrás)")
            tel_cli = row['telefone']
            
            if tel_cli:
                tel_limpo = ''.join(filter(str.isdigit, str(tel_cli)))
                if len(tel_limpo) >= 10:
                    if not tel_limpo.startswith('55'): tel_limpo = '55' + tel_limpo
                    link_wpp = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(mensagem_padrao)}"
                    
                    # Layout Lado a Lado (Link e Ação de Conclusão)
                    col_wpp, col_done = st.columns(2)
                    
                    with col_wpp:
                        st.link_button(f"💬 Abrir WhatsApp de {row['cliente'].split()[0]}", link_wpp, use_container_width=True)
                    
                    with col_done:
                        if st.button(f"✅ Marcar como Enviado", key=f"check_{tipo_contato}_{row['codigo_venda']}", use_container_width=True):
                            conn = conectar_banco()
                            conn.cursor().execute("""
                                INSERT INTO crm_contatos (venda_codigo, tipo_contato, empresa_id) 
                                VALUES (%s, %s, %s)
                            """, (int(row['codigo_venda']), tipo_contato, emp_id))
                            conn.commit()
                            devolver_conexao(conn)
                            st.success("Registrado!")
                            time.sleep(0.4)
                            limpar_cache()
                            st.rerun()
                else:
                    st.warning("⚠️ Telefone mal formatado.")
            else:
                st.warning("⚠️ Sem telefone cadastrado.")
            st.markdown("<hr style='margin: 0.5em 0px; opacity: 0.3'>", unsafe_allow_html=True)

        # Aba 2 Dias
        with tab_2d:
            if not df_2_dias.empty:
                for _, row in df_2_dias.iterrows():
                    msg_2d = f"Olá, {row['cliente'].split()[0]}! 🌸 Passando rapidinho para saber se já conseguiu testar os produtos da sua compra do dia {row['data_venda']}. Como foi a primeira impressão? Se tiver qualquer dúvida sobre como usar, estou por aqui! ✨"
                    gerar_linha_contato(row, msg_2d, "2d")
            else:
                st.info("Nenhum cliente na janela de 2 dias pendente de envio.")
                
        # Aba 2 Semanas
        with tab_2s:
            if not df_2_semanas.empty:
                for _, row in df_2_semanas.iterrows():
                    msg_2s = f"Oi, {row['cliente'].split()[0]}! Tudo bem? 🌸 Já faz umas duas semaninhas que você está com seus produtos, né? Passando só para confirmar se está dando tudo certo com o uso e se os resultados estão dentro do esperado. Me conta depois! ✨"
                    gerar_linha_contato(row, msg_2s, "2s")
            else:
                st.info("Nenhum cliente na janela de 2 semanas pendente de envio.")
                
        # Aba 2 Meses
        with tab_2m:
            if not df_2_meses.empty:
                for _, row in df_2_meses.iterrows():
                    msg_2m = f"Olá, {row['cliente'].split()[0]}! 🌸 Dei uma olhadinha aqui e vi que já faz um tempinho desde a nossa última conversa. Como estão os seus produtinhos? Provavelmente alguns já estão pedindo reposição, né? Posso te mandar as novidades e promoções que chegaram essa semana? ✨"
                    gerar_linha_contato(row, msg_2m, "2m")
            else:
                st.info("Nenhum cliente na janela de 2 meses pendente de envio.")
