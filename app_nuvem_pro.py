import os
import sys
import re
import json
import base64
import calendar
import urllib.parse
import time as time_module  # renomeado para não conflitar com datetime.time

# Força o servidor inteiro a rodar no fuso correto
os.environ['TZ'] = 'America/Fortaleza'
time_module.tzset()

import streamlit as st
import psycopg2
import pandas as pd
import plotly.express as px
import pdfplumber
import pytz
import xml.etree.ElementTree as ET
from datetime import datetime, date, time, timedelta
from PIL import Image

hoje = date.today()
PERF_RUN_START = time_module.perf_counter()

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
def conectar_banco(tentativas=3, espera=0.7):
    """Abre conexão com retry para reduzir falhas temporárias no Streamlit Cloud/Supabase."""
    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            return psycopg2.connect(DATABASE_URL, connect_timeout=10)
        except psycopg2.OperationalError as e:
            ultimo_erro = e
            if tentativa < tentativas:
                time_module.sleep(espera)
            else:
                raise ultimo_erro

def devolver_conexao(conn):
    try:
        if conn:
            conn.close()
    except Exception:
        pass

def carregar_dados(query, params=None):
    conn = conectar_banco()
    inicio_sql = time_module.perf_counter()
    try:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)

        registrar_sql_perf(query, time_module.perf_counter() - inicio_sql, "SELECT")

        if cursor.description:
            cols = [desc[0] for desc in cursor.description]
            df = pd.DataFrame(cursor.fetchall(), columns=cols)
        else:
            df = pd.DataFrame()
        return df
    except Exception:
        registrar_sql_perf(query, time_module.perf_counter() - inicio_sql, "SELECT_ERRO")
        raise
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
    inicio_sql = time_module.perf_counter()
    try:
        cur = conn.cursor()
        operacoes(cur)
        conn.commit()
        registrar_sql_perf("TRANSAÇÃO DE ESCRITA", time_module.perf_counter() - inicio_sql, "WRITE")
    except Exception:
        conn.rollback()
        registrar_sql_perf("TRANSAÇÃO DE ESCRITA COM ERRO", time_module.perf_counter() - inicio_sql, "WRITE_ERRO")
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
# TELEMETRIA DE PERFORMANCE (MODO DEV)
# Mede tempo SQL, quantidade de consultas e tempo total de renderização.
# Visível apenas para perfis admin/master.
# ==========================================
def obter_perf():
    """Inicializa e retorna o painel de telemetria da execução atual."""
    perf = st.session_state.get('_perf_run')
    if not perf or perf.get('run_start') != PERF_RUN_START:
        perf = {
            'run_start': PERF_RUN_START,
            'sql_count': 0,
            'sql_time': 0.0,
            'write_count': 0,
            'write_time': 0.0,
            'queries': []
        }
        st.session_state['_perf_run'] = perf
    return perf

def normalizar_sql_para_perf(query):
    """Compacta SQL para exibição curta no painel de performance."""
    try:
        sql = " ".join(str(query).split())
        return sql[:180] + ("..." if len(sql) > 180 else "")
    except Exception:
        return "SQL não identificado"

def registrar_sql_perf(query, tempo, tipo="SELECT"):
    """Registra uma consulta ou escrita executada durante o rerun."""
    try:
        perf = obter_perf()
        if tipo == "WRITE":
            perf['write_count'] += 1
            perf['write_time'] += tempo
        else:
            perf['sql_count'] += 1
            perf['sql_time'] += tempo

        perf['queries'].append({
            'tipo': tipo,
            'tempo': float(tempo),
            'sql': normalizar_sql_para_perf(query)
        })
    except Exception:
        # Telemetria nunca deve quebrar o ERP.
        pass

def exibir_telemetria_performance():
    """Mostra resumo de performance no sidebar para administradores."""
    try:
        if not st.session_state.get('logado'):
            return
        if st.session_state.get('perfil') not in ['admin', 'master']:
            return

        perf = obter_perf()
        tempo_total = time_module.perf_counter() - PERF_RUN_START
        tempo_banco = perf.get('sql_time', 0.0) + perf.get('write_time', 0.0)
        tempo_render = max(tempo_total - tempo_banco, 0.0)

        with st.sidebar.expander("🛠️ Performance", expanded=False):
            st.caption(f"Tela: {st.session_state.get('menu_principal', 'N/A')}")
            c1, c2 = st.columns(2)
            c1.metric("Total", f"{tempo_total:.2f}s")
            c2.metric("Banco", f"{tempo_banco:.2f}s")
            c3, c4 = st.columns(2)
            c3.metric("Render", f"{tempo_render:.2f}s")
            c4.metric("SQL", f"{perf.get('sql_count', 0) + perf.get('write_count', 0)}")

            consultas = sorted(perf.get('queries', []), key=lambda x: x.get('tempo', 0), reverse=True)
            if consultas:
                st.caption("Consultas mais lentas:")
                for item in consultas[:5]:
                    st.caption(f"{item.get('tipo', 'SQL')} • {item.get('tempo', 0):.2f}s")
                    st.code(item.get('sql', ''), language="sql")
            else:
                st.caption("Nenhuma consulta registrada neste rerun.")
    except Exception:
        pass

@st.cache_data(show_spinner=False)
def carregar_imagem_base64(caminho_imagem):
    """Lê imagens locais uma única vez por cache, evitando I/O repetido em reruns."""
    with open(caminho_imagem, "rb") as img_file:
        return base64.b64encode(img_file.read()).decode()

def executar_comando(query, params=None):
    """Executa um único INSERT/UPDATE/DELETE com commit, rollback e fechamento seguro."""
    def _operacao(cur):
        cur.execute(query, params or ())
    executar_escrita(_operacao)

def buscar_linha(query, params=None):
    """Executa uma consulta e retorna apenas a primeira linha, sempre fechando a conexão."""
    conn = conectar_banco()
    inicio_sql = time_module.perf_counter()
    try:
        cur = conn.cursor()
        cur.execute(query, params or ())
        registrar_sql_perf(query, time_module.perf_counter() - inicio_sql, "SELECT")
        return cur.fetchone()
    except Exception:
        registrar_sql_perf(query, time_module.perf_counter() - inicio_sql, "SELECT_ERRO")
        raise
    finally:
        devolver_conexao(conn)


# ==========================================
# PAINEL DE AVALIAÇÕES (visível no sistema)
# ==========================================
def exibir_painel_avaliacoes(emp_id):
    st.subheader("⭐ Avaliações de Atendimento")
    
    df_aval = carregar_dados_cached("""
        SELECT venda_codigo, cliente_nome, nota, comentario, data_avaliacao
        FROM avaliacoes
        WHERE empresa_id = %s
        ORDER BY data_avaliacao DESC
    """, (emp_id,))
    
    if df_aval.empty:
        st.info("Nenhuma avaliação recebida ainda.")
        return
    
    media = df_aval['nota'].mean()
    total = len(df_aval)
    col1, col2, col3 = st.columns(3)
    col1.metric("⭐ Nota Média", f"{media:.1f} / 5.0")
    col2.metric("📋 Total de Avaliações", total)
    col3.metric("😊 Satisfeitos (4-5 ⭐)", f"{len(df_aval[df_aval['nota'] >= 4])} ({len(df_aval[df_aval['nota'] >= 4])*100//total}%)")
    
    st.markdown("---")
    
    dist = df_aval['nota'].value_counts().sort_index(ascending=False)
    labels = {5: "⭐⭐⭐⭐⭐", 4: "⭐⭐⭐⭐", 3: "⭐⭐⭐", 2: "⭐⭐", 1: "⭐"}
    for nota, qtd in dist.items():
        barra = "█" * qtd + "░" * (total - qtd)
        st.markdown(f"`{labels.get(nota, nota)}` {barra} **{qtd}**")
    
    st.markdown("---")
    
    st.markdown("**💬 Comentários Recentes:**")
    comentarios = df_aval[df_aval['comentario'].notna() & (df_aval['comentario'] != '')]
    if comentarios.empty:
        st.caption("Nenhum comentário recebido ainda.")
    else:
        for _, row in comentarios.head(10).iterrows():
            estrelas_str = "⭐" * int(row['nota'])
            st.markdown(f"{estrelas_str} **{row['cliente_nome']}** — *Atend. Nº {row['venda_codigo']}*")
            st.caption(f"_{row['comentario']}_")
            st.markdown("<hr style='margin: 0.3em 0; opacity:0.2'>", unsafe_allow_html=True)

# ==========================================
# TELA PÚBLICA DE AVALIAÇÃO
# Deve vir ANTES do login para interceptar
# o cliente sem exigir autenticação.
# URL: ?avaliacao=CODIGO&empresa=ID
# ==========================================
params = st.query_params
if "avaliacao" in params and "empresa" in params:
    cod_aval = params["avaliacao"]
    emp_aval = params["empresa"]
    nome_cliente = urllib.parse.unquote(params.get("cliente", "Cliente"))

    st.markdown("""
        <style>
        .block-container { max-width: 600px; margin: auto; padding-top: 2rem; }
        </style>
    """, unsafe_allow_html=True)

    # Tela de agradecimento após envio
    if st.session_state.get('avaliacao_enviada'):
        st.markdown(f"""
            <div style='text-align: center; padding: 3rem 1rem;'>
                <div style='font-size: 5rem;'>🌸</div>
                <h1 style='color: #7c3aed;'>Obrigada, {nome_cliente.split()[0]}!</h1>
                <p style='font-size: 1.2rem; color: #555;'>
                    Sua avaliação foi registrada com sucesso.<br>
                    Ela nos ajuda a melhorar cada vez mais! 💜
                </p>
                <p style='font-size: 1rem; color: #888; margin-top: 2rem;'>
                    Você já pode fechar esta página.
                </p>
            </div>
        """, unsafe_allow_html=True)
        st.stop()

    df_ja_avaliou = carregar_dados(
        "SELECT id FROM avaliacoes WHERE venda_codigo = %s AND empresa_id = %s",
        (int(cod_aval), int(emp_aval))
    )

    if not df_ja_avaliou.empty:
        st.success("✅ Você já enviou sua avaliação para este atendimento. Obrigada! 🌸")
        st.stop()

    st.title("⭐ Avalie seu Atendimento")
    st.markdown(f"Olá, **{nome_cliente.split()[0]}**! Atendimento Nº {cod_aval}")
    st.markdown("Sua opinião é muito importante para continuarmos melhorando! 💜")
    st.markdown("---")

    estrelas = {
        "⭐⭐⭐⭐⭐ — Muito satisfatório": 5,
        "⭐⭐⭐⭐ — Satisfatório": 4,
        "⭐⭐⭐ — Regular": 3,
        "⭐⭐ — Insatisfatório": 2,
        "⭐ — Muito insatisfatório": 1,
    }

    nota_desc = st.radio(
        "Como você avalia seu atendimento/serviço?",
        options=list(estrelas.keys()),
        index=0
    )
    nota_valor = estrelas[nota_desc]

    comentario = st.text_area(
        "Deixe seu comentário (opcional):",
        placeholder="Conte como foi sua experiência...",
        height=120
    )

    if st.button("📨 Enviar Avaliação", type="primary", use_container_width=True):
        try:
            executar_comando("""
                INSERT INTO avaliacoes (empresa_id, venda_codigo, cliente_nome, nota, comentario)
                VALUES (%s, %s, %s, %s, %s)
            """, (int(emp_aval), int(cod_aval), nome_cliente, nota_valor, comentario))
            st.session_state['avaliacao_enviada'] = True
            st.rerun()
        except Exception as e:
            st.error(f"Erro ao salvar avaliação: {e}")

    st.stop()

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
    # Converte a logo com cache para evitar leitura repetida a cada rerun.
    img_base64 = carregar_imagem_base64("Apprimory_logo_branca.png")

    # ADS 2.1 — Welcome Experience
    # Somente UI/UX: a autenticação, permissões e fechamento da conexão foram preservados.
    st.markdown(
        """
        <style>
        .stApp {
            background:
                radial-gradient(circle at 50% 8%, rgba(37, 99, 235, 0.08), transparent 34%),
                linear-gradient(180deg, #f8fafc 0%, #ffffff 100%);
        }

        .block-container {
            max-width: 1180px;
            padding-top: 1.2rem;
            padding-bottom: 1rem;
        }

        .ap-login-brand {
            text-align: center;
            margin: 0 auto 0.55rem auto;
        }

        .ap-login-brand img {
            width: min(330px, 78vw);
            height: auto;
            display: block;
            margin: 0 auto;
        }

        .ap-login-title {
            margin: 0;
            color: #0f172a;
            font-size: 1.42rem;
            font-weight: 760;
            line-height: 1.2;
            text-align: center;
        }

        .ap-login-subtitle {
            margin: 0.28rem 0 0.85rem 0;
            color: #64748b;
            font-size: 0.90rem;
            line-height: 1.45;
            text-align: center;
        }

        .ap-login-signature {
            margin: 0.7rem 0 0 0;
            color: #2563eb;
            font-size: 0.78rem;
            font-weight: 650;
            letter-spacing: 0.01em;
            text-align: center;
        }

        .ap-login-footer {
            margin-top: 0.85rem;
            color: #94a3b8;
            font-size: 0.72rem;
            text-align: center;
        }

        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: rgba(255, 255, 255, 0.96);
            border: 1px solid #e2e8f0 !important;
            border-radius: 16px !important;
            box-shadow: 0 14px 38px rgba(15, 23, 42, 0.08);
        }

        div[data-testid="stVerticalBlockBorderWrapper"] > div {
            padding: 0.85rem 1rem 0.95rem 1rem;
        }

        div[data-testid="stTextInput"] label p {
            font-size: 0.82rem;
            font-weight: 650;
            color: #334155;
        }

        div[data-testid="stTextInput"] input {
            min-height: 2.55rem;
            border-radius: 10px;
            font-size: 0.90rem;
        }

        div[data-testid="stButton"] button {
            min-height: 2.65rem;
            border-radius: 10px;
            font-size: 0.90rem;
            font-weight: 700;
        }

        @media (max-width: 640px) {
            .block-container {
                padding-top: 0.55rem;
                padding-left: 0.85rem;
                padding-right: 0.85rem;
            }

            .ap-login-brand img {
                width: min(245px, 76vw);
            }

            .ap-login-title {
                font-size: 1.18rem;
            }

            .ap-login-subtitle {
                font-size: 0.82rem;
                margin-bottom: 0.65rem;
            }

            div[data-testid="stVerticalBlockBorderWrapper"] > div {
                padding: 0.7rem 0.8rem 0.8rem 0.8rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Colunas invisíveis mantêm o card centralizado no desktop e fluido no celular.
    col_vazia_esq, col_login, col_vazia_dir = st.columns([1.05, 1.15, 1.05])

    with col_login:
        st.markdown(
            f"""
            <div class="ap-login-brand">
                <img src="data:image/png;base64,{img_base64}" alt="Apprimory">
            </div>
            <h1 class="ap-login-title">Bem-vindo ao Apprimory</h1>
            <p class="ap-login-subtitle">Entre para continuar sua gestão.</p>
            """,
            unsafe_allow_html=True
        )

        with st.container(border=True):
            login_input = st.text_input(
                "👤 Usuário",
                placeholder="Digite seu usuário...",
                key="login_usuario_ads21"
            )
            senha_input = st.text_input(
                "🔒 Senha",
                type="password",
                placeholder="Digite sua senha...",
                key="login_senha_ads21"
            )

            if st.button("Entrar no Apprimory", type="primary", use_container_width=True):
                conn = None
                if not login_input.strip() or not senha_input:
                    st.warning("Informe o usuário e a senha para continuar.")
                else:
                    try:
                        with st.spinner("Entrando..."):
                            conn = conectar_banco()
                            cursor = conn.cursor()
                            cursor.execute(
                                "SELECT id, nome, perfil, empresa_id FROM usuarios WHERE login = %s AND senha = %s",
                                (login_input, senha_input)
                            )
                            usuario = cursor.fetchone()

                            if usuario:
                                st.session_state['logado'] = True
                                st.session_state['usuario_id'] = usuario[0]
                                st.session_state['usuario_nome'] = usuario[1]
                                st.session_state['perfil'] = usuario[2]
                                st.session_state['empresa_id'] = usuario[3]

                                perfil_usuario = usuario[2]
                                id_usuario_logado = usuario[0]

                                if perfil_usuario in ['admin', 'master']:
                                    cursor.execute("SELECT chave FROM modulos")
                                    resultado = cursor.fetchall()
                                    st.session_state['modulos_permitidos'] = [
                                        linha[0].strip() for linha in resultado
                                    ] if resultado else []
                                else:
                                    cursor.execute("""
                                        SELECT m.chave
                                        FROM permissoes_acesso p
                                        JOIN modulos m ON p.modulo_id = m.id
                                        WHERE p.usuario_id = %s
                                    """, (id_usuario_logado,))
                                    resultado = cursor.fetchall()
                                    st.session_state['modulos_permitidos'] = [
                                        linha[0].strip() for linha in resultado
                                    ] if resultado else []

                                st.rerun()
                            else:
                                st.error("❌ Usuário ou senha incorretos.")
                    except Exception as e:
                        st.error(f"Erro ao tentar entrar no sistema: {e}")
                    finally:
                        devolver_conexao(conn)

        st.markdown(
            """
            <p class="ap-login-signature">Transformando dados em decisões.</p>
            <p class="ap-login-footer">Apprimory 2.0 · Inteligência para Gestão</p>
            """,
            unsafe_allow_html=True
        )


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
                executar_comando(
                    "INSERT INTO empresas (nome, cnpj, logo_url) VALUES (%s, %s, %s)", 
                    (nome_emp, cnpj_emp, logo_emp)
                )
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
                            executar_comando(
                                "UPDATE empresas SET nome=%s, cnpj=%s, logo_url=%s WHERE id=%s", 
                                (e_nome, e_cnpj, e_logo, int(emp_selecionada))
                            )
                            
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
                executar_comando(
                    "INSERT INTO usuarios (nome, login, senha, empresa_id, perfil) VALUES (%s,%s,%s,%s,%s)", 
                    (nome_usu, login_usu, senha_usu, dict_empresas[emp_usu], perfil_usu)
                )
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
                                    def _salvar_permissoes(cur):
                                        # Limpa as permissões antigas do usuário para regravar do zero
                                        cur.execute("DELETE FROM permissoes_acesso WHERE usuario_id = %s", (int(usu_perm_sel),))

                                        # Grava apenas os checkboxes marcados
                                        for mod_id, esta_marcado in selecoes.items():
                                            if esta_marcado:
                                                cur.execute(
                                                    "INSERT INTO permissoes_acesso (usuario_id, modulo_id) VALUES (%s, %s)", 
                                                    (int(usu_perm_sel), int(mod_id))
                                                )

                                    executar_escrita(_salvar_permissoes)
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
                                executar_comando(
                                    "UPDATE usuarios SET nome=%s, login=%s, empresa_id=%s, perfil=%s WHERE id=%s", 
                                    (e_nome, e_login, dict_empresas[e_emp], e_perfil, int(usu_ed_sel))
                                )
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
                            executar_comando("DELETE FROM usuarios WHERE id=%s", (int(usu_del_sel),))
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
                executar_comando("UPDATE usuarios SET senha = %s WHERE id = %s", (nova_sen, dict_todos_usu[usu_sel]))
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
                senha_atual = buscar_linha("SELECT senha FROM usuarios WHERE id=%s", (st.session_state['usuario_id'],))
                if senha_atual and senha_atual[0] == s_atu:
                    executar_comando("UPDATE usuarios SET senha=%s WHERE id=%s", (s_nov, st.session_state['usuario_id']))
                    st.success("OK!")
                else:
                    st.error("Incorreta")

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
    
    logo_html = "<span style='font-size: 28px;'>🏢</span>" # Fallback ajustado
    
    # Cenário A: A empresa possui uma logo cadastrada no banco (URL ou Caminho)
    if logo_customizada:
        if logo_customizada.startswith("http"):
            # Aumentamos o width para 85 (e removemos o height fixo para não distorcer imagens retangulares)
            logo_html = f"<img src='{logo_customizada}' width='85' style='object-fit: contain; border-radius: 4px;'>"
        elif os.path.exists(logo_customizada):
            # Se for um caminho de ficheiro local no servidor, converte para Base64
            img_base64 = carregar_imagem_base64(logo_customizada)
            logo_html = f"<img src='data:image/png;base64,{img_base64}' width='85' style='object-fit: contain;'>"
                
    # Cenário B: Não tem logo cadastrada, tenta usar a logo padrão do sistema ('logo.png')
    elif os.path.exists("logo.png"):
        img_base64 = carregar_imagem_base64("logo.png")
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
        
        
        hoje = date.today()
        d_ini, d_fim = None, None
        
        if per_sel == "Hoje": d_ini, d_fim = hoje, hoje
        elif per_sel == "Últimos 7 Dias": d_ini, d_fim = hoje - timedelta(days=7), hoje
        elif per_sel == "Últimos 15 Dias": d_ini, d_fim = hoje - timedelta(days=15), hoje
        elif per_sel == "Últimos 30 Dias": d_ini, d_fim = hoje - timedelta(days=30), hoje
        elif per_sel == "Mês Atual": 
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
            query_dash = """
                SELECT v.codigo_venda, v.data_venda, v.valor_total, v.quantidade, p.nome AS produto, p.categoria
                FROM vendas v
                JOIN produtos p ON v.produto_id = p.id
                WHERE v.empresa_id = %s
                  AND TO_DATE(v.data_venda, 'DD/MM/YYYY') >= %s
                  AND TO_DATE(v.data_venda, 'DD/MM/YYYY') <= %s
            """
            df_dash = carregar_dados_cached(query_dash, (emp_id, d_ini, d_fim))
            
            if not df_dash.empty and d_ini and d_fim:
                df_dash['Data_Obj'] = pd.to_datetime(df_dash['data_venda'], format='%d/%m/%Y', errors='coerce').dt.date
                
                if not df_dash.empty:
                    col1, col2, col3 = st.columns(3)
                    fat = df_dash['valor_total'].sum()
                    qtd_vendas_reais = df_dash['codigo_venda'].nunique()
                    ticket_medio = fat / qtd_vendas_reais if qtd_vendas_reais > 0 else 0
                    
                    col1.metric("Faturamento", f"R$ {fat:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
                    col2.metric("Vendas Fechadas", qtd_vendas_reais)
                    col3.metric("Ticket Médio", f"R$ {ticket_medio:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
                    
                    st.markdown("---")
                    
                    # FEATURE 002 — Curva de Vendas por Dia
                    # Objetivo: exibir somente dias com vendas, sem horários no eixo X,
                    # mantendo linha + marcadores para facilitar a leitura de picos e quedas.
                    df_fat_dia = (
                        df_dash.groupby('Data_Obj')['valor_total']
                        .sum()
                        .reset_index()
                        .dropna(subset=['Data_Obj'])
                        .sort_values('Data_Obj')
                    )

                    if not df_fat_dia.empty:
                        df_fat_dia['Dia'] = df_fat_dia['Data_Obj'].apply(lambda d: d.strftime('%d/%m/%Y'))

                        fig_fat_dia = px.line(
                            df_fat_dia,
                            x='Dia',
                            y='valor_total',
                            markers=True,
                            title="Curva de Vendas por Dia",
                            template="plotly_white"
                        )

                        fig_fat_dia.update_traces(
                            mode="lines+markers",
                            line=dict(width=3),
                            marker=dict(size=8),
                            hovertemplate=(
                                "<b>%{x}</b><br>"
                                "Faturamento: R$ %{y:,.2f}"
                                "<extra></extra>"
                            )
                        )

                        fig_fat_dia.update_xaxes(
                            type='category',
                            title_text="Dia",
                            tickangle=-35
                        )

                        fig_fat_dia.update_yaxes(
                            title_text="Faturamento (R$)"
                        )

                        fig_fat_dia.update_layout(
                            height=420,
                            margin=dict(l=40, r=40, t=60, b=80)
                        )

                        st.plotly_chart(fig_fat_dia, use_container_width=True)
                    else:
                        st.info("Sem vendas suficientes para gerar a curva diária.")
                    
                    c1, c2 = st.columns(2)

                    # FEATURE 001.1 — Ranking Inteligente de Produtos
                    # Objetivo: nomes completos, ranking configurável, barras mais finas e tooltip gerencial.
                    with c1:
                        opcoes_ranking_produtos = ["Top 5", "Top 10", "Top 20", "Todos"]
                        ranking_produtos_sel = st.radio(
                            "🏆 Ranking de produtos:",
                            options=opcoes_ranking_produtos,
                            index=0,
                            horizontal=True,
                            key="feature0011_ranking_produtos"
                        )

                        df_ranking_produtos = (
                            df_dash.groupby('produto')
                            .agg(
                                quantidade=('quantidade', 'sum'),
                                faturamento=('valor_total', 'sum')
                            )
                            .reset_index()
                            .sort_values('quantidade', ascending=False)
                        )

                        total_qtd_ranking = df_ranking_produtos['quantidade'].sum()
                        df_ranking_produtos['participacao_pct'] = (
                            df_ranking_produtos['quantidade'] / total_qtd_ranking * 100
                        ) if total_qtd_ranking else 0
                        df_ranking_produtos['ranking'] = range(1, len(df_ranking_produtos) + 1)

                        if ranking_produtos_sel == "Todos":
                            df_top = df_ranking_produtos.copy()
                            titulo_ranking = "🏆 Ranking Completo dos Produtos Mais Vendidos"
                        else:
                            qtd_top = int(ranking_produtos_sel.replace("Top ", ""))
                            df_top = df_ranking_produtos.head(qtd_top).copy()
                            titulo_ranking = f"🏆 {ranking_produtos_sel} Produtos Mais Vendidos"

                        df_top = df_top.sort_values('quantidade', ascending=True)
                        df_top['faturamento_fmt'] = df_top['faturamento'].apply(
                            lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                        )
                        df_top['participacao_fmt'] = df_top['participacao_pct'].apply(lambda x: f"{x:.1f}%")
                        df_top['rotulo_barra'] = df_top.apply(
                            lambda row: f"{int(row['quantidade'])} • {row['participacao_fmt']}",
                            axis=1
                        )

                        altura_ranking = max(420, len(df_top) * 42)
                        max_qtd_ranking = df_top['quantidade'].max() if not df_top.empty else 0

                        fig_top = px.bar(
                            df_top,
                            x='quantidade',
                            y='produto',
                            orientation='h',
                            text='rotulo_barra',
                            title=titulo_ranking,
                            custom_data=['ranking', 'faturamento_fmt', 'participacao_fmt']
                        )

                        fig_top.update_traces(
                            width=0.42,
                            textposition='outside',
                            cliponaxis=False,
                            hovertemplate=(
                                "<b>%{y}</b><br><br>"
                                "Ranking: #%{customdata[0]}<br>"
                                "Quantidade vendida: %{x}<br>"
                                "Faturamento: %{customdata[1]}<br>"
                                "Participação: %{customdata[2]}"
                                "<extra></extra>"
                            )
                        )

                        fig_top.update_layout(
                            xaxis_title="Quantidade vendida",
                            yaxis_title="",
                            height=altura_ranking,
                            margin=dict(l=320, r=80, t=70, b=40),
                            showlegend=False
                        )

                        fig_top.update_xaxes(range=[0, max_qtd_ranking * 1.20 if max_qtd_ranking else 1])
                        fig_top.update_yaxes(automargin=True)

                        st.plotly_chart(fig_top, use_container_width=True)

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
                            return f"https://api.whatsapp.com/send?phone={num}&text={urllib.parse.quote(msg)}"
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
            
            st.markdown("---")
            
            # --- PAINEL DE AVALIAÇÕES ---
            exibir_painel_avaliacoes(emp_id)
                
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
                  AND TO_DATE(v.data_venda, 'DD/MM/YYYY') >= %s
                  AND TO_DATE(v.data_venda, 'DD/MM/YYYY') <= %s
                ORDER BY v.codigo_venda DESC, v.id DESC
            """
            df_todas_vendas = carregar_dados_cached(query_todas_vendas, (emp_id, d_ini, d_fim))
            
            if not df_todas_vendas.empty:
                col_opcoes1, col_opcoes2 = st.columns(2)
                
                with col_opcoes1:
                    with st.expander("✏️ Editar Item de Venda", expanded=False):
                        opcoes_venda_edit = df_todas_vendas.apply(lambda x: f"Venda {x['Nº Venda']} (Item {x['ID Item']}) | {x['Cliente']} - {x['Produto']}", axis=1).tolist()
                        venda_edit_selecionada = st.selectbox("Selecione a venda para editar", options=opcoes_venda_edit, key="sel_edit_venda")
                        
                        if venda_edit_selecionada:
                            venda_id_edit = int(venda_edit_selecionada.split("Item ")[1].split(")")[0])
                            dados_v_edit = buscar_linha(
                                "SELECT data_venda, forma_pagamento, prazo, valor_unitario, desconto, valor_entrada, quantidade FROM vendas WHERE id = %s AND empresa_id = %s",
                                (venda_id_edit, emp_id)
                            )
                            
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
                                        executar_comando(
                                            "UPDATE vendas SET data_venda=%s, forma_pagamento=%s, prazo=%s, valor_unitario=%s, desconto=%s, valor_total=%s, valor_entrada=%s, valor_restante=%s WHERE id=%s AND empresa_id=%s",
                                            (nova_data.strftime("%d/%m/%Y"), novo_pag, novo_prazo, novo_tabela, novo_desc, novo_total, nova_entrada, novo_restante, venda_id_edit, emp_id)
                                        )
                                        st.success("Atualizado!"); limpar_cache(); st.rerun()

                with col_opcoes2:
                    with st.expander("❌ Cancelar / Estornar Item", expanded=False):
                        with st.form("form_del_venda"):
                            opcoes_venda_del = df_todas_vendas.apply(lambda x: f"Venda {x['Nº Venda']} (Item {x['ID Item']}) | {x['Cliente']} - {x['Produto']}", axis=1).tolist()
                            venda_para_apagar = st.selectbox("Selecione o item lançado por engano", options=opcoes_venda_del, key="sel_del_venda")
                            
                            if st.form_submit_button("🚨 Confirmar Cancelamento", type="primary"):
                                venda_id_del = int(venda_para_apagar.split("Item ")[1].split(")")[0])
                                try:
                                    def _cancelar_venda(cur):
                                        cur.execute("SELECT produto_id, quantidade, codigo_venda FROM vendas WHERE id = %s AND empresa_id = %s", (venda_id_del, emp_id))
                                        venda_info = cur.fetchone()
                                        if not venda_info:
                                            raise ValueError("Venda não encontrada para cancelamento.")
                                        p_id, p_qtd, cod_venda = venda_info
                                        cur.execute("UPDATE produtos SET quantidade = quantidade + %s WHERE id = %s AND empresa_id = %s", (p_qtd, p_id, emp_id))
                                        cur.execute("DELETE FROM vendas WHERE id = %s AND empresa_id = %s", (venda_id_del, emp_id))
                                        cur.execute("DELETE FROM contas_receber WHERE venda_codigo = %s AND empresa_id = %s", (cod_venda, emp_id))
                                    executar_escrita(_cancelar_venda)
                                    st.success("Cancelado!"); limpar_cache(); st.rerun()
                                except Exception as e:
                                    st.error(f"Erro ao cancelar venda: {e}")
                
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
                        
                        try:
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
                        except Exception as e:
                            dados_recibo = []
                            st.error("Erro ao buscar dados do recibo. Tente novamente em alguns segundos.")
                        finally:
                            if 'conn' in locals():
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
                WHERE empresa_id = %s AND tipo='P'
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
            
            # Consulta SQL Otimizada: soma vendas e calcula status financeiro em um único agrupamento
            ultimo_dia_app = calendar.monthrange(ano_sel, mes_num)[1]
            app_ini = date(ano_sel, mes_num, 1)
            app_fim = date(ano_sel, mes_num, ultimo_dia_app)

            query_app = """
                WITH cr_status AS (
                    SELECT
                        venda_codigo,
                        empresa_id,
                        COUNT(*) FILTER (WHERE status = 'Pendente') AS pendentes,
                        COUNT(*) FILTER (
                            WHERE status = 'Pendente'
                              AND TO_DATE(data_vencimento, 'DD/MM/YYYY') < CURRENT_DATE
                        ) AS atrasadas
                    FROM contas_receber
                    WHERE empresa_id = %s
                    GROUP BY venda_codigo, empresa_id
                )
                SELECT 
                    v.codigo_venda,
                    MAX(v.data_venda) AS "Data",
                    MAX(c.nome) AS "Cliente",
                    SUM(v.valor_total) AS "Valor Total (R$)",
                    CASE 
                        WHEN COALESCE(MAX(cr.pendentes), 0) = 0 THEN '🟢 QUITADO'
                        WHEN COALESCE(MAX(cr.atrasadas), 0) > 0 THEN '🔴 ATRASADO'
                        ELSE '🔵 PENDENTE'
                    END AS "Status"
                FROM vendas v
                LEFT JOIN clientes c ON v.cliente_id = c.id
                LEFT JOIN cr_status cr ON cr.venda_codigo = v.codigo_venda AND cr.empresa_id = v.empresa_id
                WHERE TO_DATE(v.data_venda, 'DD/MM/YYYY') >= %s
                  AND TO_DATE(v.data_venda, 'DD/MM/YYYY') <= %s
                  AND v.empresa_id = %s
                GROUP BY v.codigo_venda
                ORDER BY TO_DATE(MAX(v.data_venda), 'DD/MM/YYYY') DESC
            """
            
            # Aqui fazemos a busca (se der erro de data, ajuste o cast de data_venda no SQL)
            df_app = carregar_dados_cached(query_app, (emp_id, app_ini, app_fim, emp_id))
            
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
            df_p = carregar_dados_cached("""
                SELECT id, referencia, nome, marca, categoria, valor, preco_custo, markup, quantidade, classe, tipo, empresa_id
                FROM produtos
                WHERE empresa_id=%s AND tipo='P'
                ORDER BY nome
            """, (emp_id,))
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
                        
                    prod_id_selecionado = st.selectbox("Selecione o produto que deseja atualizar:", opcoes_edicao, format_func=formatar_produto, key="sel_editar_produto")
                    
                    if prod_id_selecionado:
                        p_atual = df_p[df_p['id'] == prod_id_selecionado].iloc[0]
                        classe_atual = p_atual.get('classe', 'Venda')
                        
                        # Tratamento seguro de nulos para todos os campos
                        val_nome   = str(p_atual['nome']) if pd.notnull(p_atual['nome']) else ""
                        val_ref    = str(p_atual['referencia']) if pd.notnull(p_atual['referencia']) else ""
                        val_marca  = str(p_atual['marca']) if pd.notnull(p_atual['marca']) else ""
                        val_qtd    = int(p_atual['quantidade']) if pd.notnull(p_atual['quantidade']) else 0
                        val_custo  = float(p_atual['preco_custo']) if pd.notnull(p_atual.get('preco_custo')) else 0.0
                        val_markup = float(p_atual['markup']) if pd.notnull(p_atual.get('markup')) else 0.0
                        val_valor  = float(p_atual['valor']) if pd.notnull(p_atual['valor']) else 0.0
                        
                        # Chave única por produto — força o Streamlit a limpar os campos ao trocar de produto
                        key_prefix = f"edit_prod_{prod_id_selecionado}"
                        
                        with st.container(border=True):
                            
                            index_classe_atual = 1 if classe_atual == 'Insumo' else 0
                            e_classe_desc = st.selectbox("Finalidade do Produto:", ["Venda / Comercialização", "Insumo / Consumo Interno"], index=index_classe_atual, key=f"{key_prefix}_classe")
                            e_classe_letra = 'Venda' if e_classe_desc == "Venda / Comercialização" else 'Insumo'
                            
                            c1, c2 = st.columns(2)
                            e_nome = c1.text_input("Nome", value=val_nome, key=f"{key_prefix}_nome")
                            e_ref  = c2.text_input("Referência", value=val_ref, key=f"{key_prefix}_ref")
                            
                            c3, c4 = st.columns(2)
                            e_qtd   = c3.number_input("Quantidade em Estoque Atualizada", min_value=0, step=1, value=val_qtd, key=f"{key_prefix}_qtd")
                            e_marca = c4.text_input("Marca / Linha", value=val_marca, key=f"{key_prefix}_marca")
                            
                            st.markdown("**Finanças e Precificação**")
                            c5, c6, c7 = st.columns(3)
                            
                            e_custo  = c5.number_input("Preço de Custo (R$)", min_value=0.0, format="%.2f", value=val_custo, key=f"{key_prefix}_custo")
                            e_markup = c6.number_input("Markup (%)", min_value=0.0, format="%.2f", value=val_markup, disabled=(e_classe_letra == 'Insumo'), key=f"{key_prefix}_markup")
                            e_valor  = c7.number_input("Preço de Venda (R$)", min_value=0.0, format="%.2f", value=val_valor, disabled=(e_classe_letra == 'Insumo'), key=f"{key_prefix}_valor")
                            
                            try:
                                cat_index = lista_cat.index(p_atual['categoria'])
                            except (ValueError, TypeError):
                                cat_index = 0
                                
                            e_cat = st.selectbox("Categoria", lista_cat, index=cat_index, key=f"{key_prefix}_cat")
                            
                            st.markdown("---")
                            col_btn_salvar, col_btn_excluir = st.columns(2)
                            
                            if col_btn_salvar.button("💾 Salvar Alterações", type="primary", use_container_width=True, key=f"{key_prefix}_salvar"):
                                try:
                                    conn = conectar_banco()
                                    cur = conn.cursor()
                                    cur.execute("""
                                        UPDATE produtos 
                                        SET nome=%s, quantidade=%s, valor=%s, preco_custo=%s, markup=%s, marca=%s, categoria=%s, referencia=%s, classe=%s 
                                        WHERE id=%s AND empresa_id=%s
                                    """, (e_nome, e_qtd, e_valor, e_custo, e_markup, e_marca, e_cat, e_ref, e_classe_letra, int(prod_id_selecionado), emp_id))
                                    cur.close()
                                    conn.commit()
                                    devolver_conexao(conn)
                                    st.success("Cadastro atualizado com sucesso!")
                                    limpar_cache()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Erro ao salvar: {e}")
                                    if 'conn' in locals(): devolver_conexao(conn)
                                
                            if col_btn_excluir.button("🗑️ Excluir Produto", use_container_width=True, key=f"{key_prefix}_excluir"):
                                try:
                                    conn = conectar_banco()
                                    cur = conn.cursor()
                                    cur.execute("DELETE FROM produtos WHERE id=%s AND empresa_id=%s", (int(prod_id_selecionado), emp_id))
                                    cur.close()
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
            df_s = carregar_dados_cached("SELECT id, referencia, nome, categoria, valor, tempo_minutos, tipo, empresa_id FROM produtos WHERE empresa_id=%s AND tipo='S' ORDER BY nome", (emp_id,))
            
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

            df_clientes = carregar_dados_cached("SELECT id, nome, data_nascimento, telefone, tipo, empresa_id FROM clientes WHERE empresa_id = %s ORDER BY nome", (emp_id,))
            
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
        # ==========================================================
        # ADS 2.0 — PADRÃO VISUAL DO MÓDULO DE MOVIMENTAÇÕES
        # Alteração exclusivamente de UI/UX. Nenhuma regra de negócio,
        # consulta SQL, cálculo ou gravação foi modificada.
        # ==========================================================
        st.markdown("""
            <style>
            /* Área de trabalho compacta para desktop e celular */
            .block-container {
                padding-top: 1.1rem;
                padding-bottom: 1.5rem;
            }

            /* Abas do módulo */
            div[data-baseweb="tab-list"] {
                gap: .20rem;
                overflow-x: auto;
                scrollbar-width: thin;
            }
            button[data-baseweb="tab"] {
                min-height: 2.25rem;
                padding: .35rem .65rem;
                font-size: .82rem;
                white-space: nowrap;
            }

            /* Formulários e textos mais compactos */
            div[data-testid="stWidgetLabel"] p,
            .stSelectbox label p, .stTextInput label p,
            .stNumberInput label p, .stDateInput label p,
            .stTimeInput label p, .stTextArea label p {
                font-size: .79rem !important;
                font-weight: 650 !important;
            }
            div[data-baseweb="select"] > div,
            .stTextInput input, .stNumberInput input,
            .stDateInput input, .stTimeInput input {
                min-height: 2.25rem;
                font-size: .84rem;
            }
            .stButton > button, .stLinkButton > a {
                min-height: 2.30rem;
                padding: .38rem .72rem;
                font-size: .82rem;
                font-weight: 750;
                border-radius: 9px;
            }
            div[data-testid="stForm"],
            div[data-testid="stVerticalBlockBorderWrapper"] {
                border-radius: 12px;
            }
            div[data-testid="stExpander"] details {
                border-radius: 10px;
            }
            div[data-testid="stMetric"] {
                padding: .55rem .65rem;
            }
            div[data-testid="stMetricLabel"] p { font-size: .76rem; }
            div[data-testid="stMetricValue"] { font-size: 1.28rem; }
            .stDataFrame { font-size: .80rem; }

            /* Componentes ADS locais */
            .ads-mov-header {
                display:flex; align-items:center; justify-content:space-between;
                gap:.75rem; padding:.10rem 0 .55rem 0;
                margin:-.20rem 0 .55rem 0;
                border-bottom:1px solid #e5e7eb;
            }
            .ads-mov-title {
                font-size:1.02rem; font-weight:850; color:#111827;
                line-height:1.15; margin:0;
            }
            .ads-mov-context {
                font-size:.73rem; color:#64748b; text-align:right;
                line-height:1.15; white-space:nowrap;
            }
            .ads-screen-title {
                font-size:.98rem; font-weight:850; color:#1f2937;
                margin:.15rem 0 .45rem 0; line-height:1.2;
            }
            .ads-screen-caption {
                font-size:.76rem; color:#64748b; margin:-.25rem 0 .55rem 0;
            }
            .ads-panel-title {
                font-size:.94rem; font-weight:900; color:#1f2937;
                margin:0 0 .18rem 0; line-height:1.2;
            }
            .ads-panel-caption {
                font-size:.74rem; color:#64748b;
                margin:0 0 .48rem 0; line-height:1.25;
            }
            .ads-context-title {
                font-size:.82rem; font-weight:850; color:#1f2937;
                margin:.05rem 0 .20rem 0; line-height:1.2;
            }

            @media (max-width: 768px) {
                .block-container { padding-left:.75rem; padding-right:.75rem; padding-top:.65rem; }
                .ads-mov-header { align-items:flex-start; margin-top:0; }
                .ads-mov-title { font-size:.92rem; }
                .ads-mov-context { font-size:.66rem; white-space:normal; max-width:44%; }
                button[data-baseweb="tab"] { font-size:.74rem; padding:.30rem .48rem; }
                .stButton > button, .stLinkButton > a { font-size:.78rem; }
                div[data-testid="stMetricValue"] { font-size:1.10rem; }
            }
            </style>
            <div class="ads-mov-header">
                <div class="ads-mov-title">🔄 Movimentações</div>
                <div class="ads-mov-context">Operações diárias · Apprimory 2.0</div>
            </div>
        """, unsafe_allow_html=True)
        
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
                # ==========================================================
                # PDV 2.0 — Tela de Vendas redesenhada
                # Mantém a lógica de negócio original e reorganiza a experiência.
                # ==========================================================
                # PDV 2.1 — Cabeçalho compacto e ergonomia mobile
                # Reduz textos, espaçamentos e fontes para melhorar a navegação em desktop e celular.
                st.markdown("""
                    <style>
                    .pdv2-header {
                        border-bottom: 1px solid #e5e7eb;
                        padding: 2px 0 8px 0;
                        margin: -4px 0 10px 0;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 10px;
                    }
                    .pdv2-title {
                        font-size: 1.05rem;
                        font-weight: 900;
                        color: #111827;
                        line-height: 1.15;
                    }
                    .pdv2-subtitle {
                        color: #64748b;
                        font-size: 0.78rem;
                        line-height: 1.2;
                        text-align: right;
                        white-space: nowrap;
                    }
                    .pdv2-section-title {
                        font-weight: 900;
                        color: #1f2937;
                        font-size: 0.94rem;
                        margin-bottom: 4px;
                    }
                    .pdv2-total-box {
                        border-radius: 14px;
                        padding: 12px 14px;
                        margin: 4px 0 10px 0;
                        background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
                        border: 1px solid #dbeafe;
                    }
                    .pdv2-total-label {
                        font-size: 0.76rem;
                        color: #475569;
                        font-weight: 800;
                        text-transform: uppercase;
                        letter-spacing: .035em;
                    }
                    .pdv2-total-value {
                        font-size: 1.8rem;
                        color: #0f172a;
                        font-weight: 950;
                        line-height: 1.0;
                        margin-top: 2px;
                    }
                    .pdv2-small-note {
                        color: #64748b;
                        font-size: 0.78rem;
                    }
                    div[data-testid="stVerticalBlock"] {
                        gap: 0.55rem;
                    }
                    @media (max-width: 768px) {
                        .pdv2-header {
                            display: block;
                            padding: 0 0 6px 0;
                            margin: -8px 0 8px 0;
                        }
                        .pdv2-title {
                            font-size: 0.98rem;
                        }
                        .pdv2-subtitle {
                            text-align: left;
                            white-space: normal;
                            font-size: 0.72rem;
                            margin-top: 2px;
                        }
                        .pdv2-section-title {
                            font-size: 0.88rem;
                        }
                        .pdv2-total-box {
                            padding: 10px 12px;
                            border-radius: 12px;
                        }
                        .pdv2-total-value {
                            font-size: 1.55rem;
                        }
                        .stButton button, .stDownloadButton button, .stLinkButton a {
                            min-height: 2.25rem;
                            padding: 0.25rem 0.6rem;
                            font-size: 0.85rem;
                        }
                        div[data-testid="stMetricValue"] {
                            font-size: 1.25rem;
                        }
                    }
                    </style>
                """, unsafe_allow_html=True)

                if 'pdv_reset' not in st.session_state:
                    st.session_state['pdv_reset'] = 0
                if 'reset_prod' not in st.session_state:
                    st.session_state['reset_prod'] = 0

                # Painel de pós-venda/WhatsApp fica no topo para o operador não precisar rolar a tela.
                if 'zap_link' in st.session_state and st.session_state['zap_link']:
                    with st.container(border=True):
                        st.success(f"🎉 {st.session_state['zap_codigo']} pronto! Total: R$ {st.session_state['zap_total']:.2f}".replace('.', ','))
                        st.markdown("#### 📲 Recibo pelo WhatsApp")
                        st.text_area("Mensagem preparada:", value=st.session_state['zap_msg'], height=120, disabled=True)
                        col_zap1, col_zap2 = st.columns([2, 1])
                        col_zap1.link_button("🟢 Abrir WhatsApp e Enviar", st.session_state['zap_link'], type="primary", use_container_width=True)
                        if col_zap2.button("➕ Nova venda", use_container_width=True):
                            for chave in ['zap_link', 'zap_msg', 'zap_codigo', 'zap_total']:
                                if chave in st.session_state:
                                    del st.session_state[chave]
                            st.session_state['carrinho'] = []
                            st.session_state['pdv_reset'] += 1
                            st.session_state['reset_prod'] += 1
                            st.rerun()
                    st.markdown("---")

                st.markdown("""
                    <div class="pdv2-header">
                        <div class="pdv2-title">🛒 Nova Venda</div>
                        <div class="pdv2-subtitle">Cliente → produto → carrinho → fechamento</div>
                    </div>
                """, unsafe_allow_html=True)

                # Carrega dados atualizados para o PDV
                df_cli = carregar_dados_cached("SELECT id, nome FROM clientes WHERE empresa_id=%s ORDER BY nome", (emp_id,))
                df_pro = carregar_dados_cached("SELECT id, nome, valor, quantidade, tipo FROM produtos WHERE empresa_id=%s AND tipo='P' AND classe='Venda' ORDER BY nome", (emp_id,))

                if not df_cli.empty and not df_pro.empty:
                    reset_key = st.session_state['pdv_reset']
                    df_pro = df_pro.copy()
                    df_pro['display_pesquisa'] = df_pro.apply(
                        lambda x: f"{x['nome']} - Estoque: {int(x['quantidade'])}", axis=1
                    )

                    col_operacao, col_carrinho = st.columns([1.08, 1], gap="large")

                    with col_operacao:
                        with st.container(border=True):
                            st.markdown('<div class="pdv2-section-title">👤 Dados da venda</div>', unsafe_allow_html=True)
                            cliente_pdv = st.selectbox(
                                "Cliente",
                                options=df_cli['nome'].tolist(),
                                index=None,
                                placeholder="Selecione o cliente...",
                                key=f"pdv_cliente_{reset_key}"
                            )

                            c_data, c_pag, c_parc = st.columns([1, 1.25, 0.85])
                            data_venda_input = c_data.date_input(
                                "Data",
                                format="DD/MM/YYYY",
                                value=date.today(),
                                key=f"pdv_data_{reset_key}"
                            )
                            f_pag = c_pag.selectbox(
                                "Pagamento",
                                ["Pix", "Crédito", "Débito", "Dinheiro", "Crediário"],
                                index=None,
                                placeholder="Forma...",
                                key=f"pdv_pagamento_{reset_key}"
                            )

                            qtd_parcelas = 1
                            data_1_venc = date.today()
                            if f_pag:
                                qtd_parcelas = c_parc.number_input(
                                    "Parcelas",
                                    min_value=1,
                                    max_value=12,
                                    value=1,
                                    step=1,
                                    key=f"pdv_parcelas_{reset_key}"
                                )
                                sugestao_venc = date.today() if qtd_parcelas == 1 else date.today() + timedelta(days=30)
                                data_1_venc = st.date_input(
                                    "Data do 1º vencimento",
                                    value=sugestao_venc,
                                    format="DD/MM/YYYY",
                                    key=f"pdv_vencimento_{reset_key}"
                                )

                        with st.container(border=True):
                            st.markdown('<div class="pdv2-section-title">🔎 Produto</div>', unsafe_allow_html=True)
                            prod_display = st.selectbox(
                                "Pesquisar produto",
                                options=df_pro['display_pesquisa'].tolist(),
                                index=None,
                                placeholder="Digite ou selecione um produto...",
                                key=f"busca_produto_pdv_{st.session_state['reset_prod']}"
                            )

                            if not cliente_pdv or not f_pag:
                                st.info("Selecione cliente e forma de pagamento para adicionar produtos.")
                            elif prod_display:
                                p_info = df_pro[df_pro['display_pesquisa'] == prod_display].iloc[0]
                                estoque_atual = int(p_info['quantidade'])
                                preco_tabela = float(p_info['valor'])

                                if estoque_atual <= 0:
                                    st.error(f"🚨 Estoque zerado | Preço: R$ {preco_tabela:.2f}".replace('.', ','))
                                elif estoque_atual == 1:
                                    st.warning(f"⚠️ Última unidade | Preço: R$ {preco_tabela:.2f}".replace('.', ','))
                                elif estoque_atual <= 3:
                                    st.warning(f"⚠️ Estoque baixo: {estoque_atual} unidades | Preço: R$ {preco_tabela:.2f}".replace('.', ','))
                                else:
                                    st.info(f"📦 Estoque: {estoque_atual} unidades | 🏷️ Preço: R$ {preco_tabela:.2f}".replace('.', ','))

                                with st.form("form_add_carrinho", clear_on_submit=True):
                                    c_qtd, c_preco, c_desc_rs, c_desc_perc = st.columns([0.8, 1, 1, 1])
                                    limite_qtd = estoque_atual if estoque_atual > 0 else 999
                                    q_pdv = c_qtd.number_input("Qtde", min_value=1, max_value=limite_qtd, step=1, value=1)
                                    preco_custom = c_preco.number_input("Preço un. (R$)", min_value=0.0, value=float(preco_tabela), step=1.0, format="%.2f")
                                    desc_rs = c_desc_rs.number_input("Desc. R$", min_value=0.0, step=1.0, format="%.2f")
                                    desc_perc = c_desc_perc.number_input("Desc. %", min_value=0.0, max_value=100.0, step=1.0, format="%.1f")

                                    if st.form_submit_button("➕ ADICIONAR AO CARRINHO", disabled=(estoque_atual <= 0), use_container_width=True):
                                        if estoque_atual >= q_pdv:
                                            desconto_final = preco_custom * (desc_perc / 100.0) if desc_perc > 0 else desc_rs
                                            st.session_state['carrinho'].append({
                                                'id': int(p_info['id']),
                                                'nome': str(p_info['nome']),
                                                'qtd': int(q_pdv),
                                                'unit': float(preco_custom),
                                                'desc': float(desconto_final),
                                                'total': float((preco_custom - desconto_final) * q_pdv),
                                                'tipo': 'P',
                                                'colab_id': None
                                            })
                                            st.session_state['reset_prod'] += 1
                                            st.rerun()
                                        else:
                                            st.error("Estoque insuficiente!")
                            else:
                                st.caption("Após selecionar um produto, você poderá definir quantidade, preço e desconto.")

                    with col_carrinho:
                        with st.container(border=True):
                            st.markdown('<div class="pdv2-section-title">🛒 Carrinho</div>', unsafe_allow_html=True)

                            total_pdv = 0.0
                            desconto_total_pdv = 0.0
                            qtd_itens_pdv = 0

                            if st.session_state['carrinho']:
                                col_h1, col_h2, col_h3, col_h4 = st.columns([4, 1, 1.6, 0.6], gap="small")
                                col_h1.markdown("**Item**")
                                col_h2.markdown("**Qtd**")
                                col_h3.markdown("**Total**")
                                st.markdown("<hr style='margin: 4px 0 8px 0; opacity: .25;'>", unsafe_allow_html=True)

                                for i, item in enumerate(st.session_state['carrinho']):
                                    item_total = float(item['total'])
                                    item_qtd = int(item['qtd'])
                                    item_desc = float(item.get('desc', 0)) * item_qtd
                                    total_pdv += item_total
                                    desconto_total_pdv += item_desc
                                    qtd_itens_pdv += item_qtd

                                    col_i1, col_i2, col_i3, col_i4 = st.columns([4, 1, 1.6, 0.6], gap="small")
                                    col_i1.write(f"▫️ {item['nome']}")
                                    col_i2.write(f"{item_qtd}x")
                                    col_i3.write(f"R$ {item_total:.2f}".replace('.', ','))
                                    if col_i4.button("🗑️", key=f"del_pdv_{i}", help="Remover item"):
                                        st.session_state['carrinho'].pop(i)
                                        st.rerun()
                            else:
                                st.info("Carrinho vazio. Adicione produtos para iniciar a venda.")

                            subtotal_bruto = total_pdv + desconto_total_pdv
                            total_pdv_fmt = f"R$ {total_pdv:.2f}".replace('.', ',')
                            subtotal_fmt = f"R$ {subtotal_bruto:.2f}".replace('.', ',')
                            desconto_fmt = f"R$ {desconto_total_pdv:.2f}".replace('.', ',')

                            st.markdown("---")
                            st.markdown(f"""
                                <div class="pdv2-total-box">
                                    <div class="pdv2-total-label">Total da venda</div>
                                    <div class="pdv2-total-value">{total_pdv_fmt}</div>
                                    <div class="pdv2-small-note">{qtd_itens_pdv} item(ns) • Subtotal {subtotal_fmt} • Descontos {desconto_fmt}</div>
                                </div>
                            """, unsafe_allow_html=True)

                            valor_entrada = 0.0
                            valor_restante = float(total_pdv)
                            datas_parcelas = []

                            if st.session_state['carrinho']:
                                if f_pag == "Crediário":
                                    valor_entrada = st.number_input(
                                        "Valor da entrada (R$)",
                                        min_value=0.0,
                                        max_value=float(total_pdv),
                                        value=0.0,
                                        step=10.0,
                                        key=f"pdv_entrada_{reset_key}"
                                    )

                                valor_restante = float(total_pdv - valor_entrada)

                                if qtd_parcelas > 1 or f_pag == "Crediário":
                                    with st.expander("📅 Cronograma de vencimentos", expanded=False):
                                        if f_pag == "Crediário" and valor_entrada > 0:
                                            datas_parcelas.append(data_venda_input)
                                            if qtd_parcelas > 1:
                                                cols_p = st.columns(min(int(qtd_parcelas) - 1, 4))
                                                for i in range(2, int(qtd_parcelas) + 1):
                                                    sugestao_p = data_1_venc + timedelta(days=30 * (i - 2))
                                                    with cols_p[(i-2) % min(int(qtd_parcelas) - 1, 4)]:
                                                        dt_p = st.date_input(f"{i}ª Parc.", value=sugestao_p, format="DD/MM/YYYY", key=f"venc_p_{reset_key}_{i}")
                                                        datas_parcelas.append(dt_p)
                                        else:
                                            cols_p = st.columns(min(int(qtd_parcelas), 4))
                                            for i in range(1, int(qtd_parcelas) + 1):
                                                sugerido = data_1_venc + timedelta(days=30 * (i - 1))
                                                with cols_p[(i-1) % min(int(qtd_parcelas), 4)]:
                                                    dt_p = st.date_input(f"{i}ª Parcela", value=sugerido, format="DD/MM/YYYY", key=f"venc_p_{reset_key}_{i}")
                                                    datas_parcelas.append(dt_p)
                                else:
                                    datas_parcelas.append(data_1_venc)

                                if f_pag == "Crediário" and valor_entrada > 0:
                                    parcelas_restantes = max(int(qtd_parcelas - 1), 1)
                                    st.info(f"💵 Entrada: R$ {valor_entrada:.2f} | Restante: R$ {valor_restante:.2f} em {parcelas_restantes}x".replace('.', ','))
                                elif qtd_parcelas > 1:
                                    st.info(f"💳 Parcelamento: {int(qtd_parcelas)}x de R$ {(total_pdv / qtd_parcelas):.2f}".replace('.', ','))

                                st.markdown("#### Ações")
                                if st.button("✅ FINALIZAR VENDA", type="primary", use_container_width=True):
                                    try:
                                        conn = conectar_banco()
                                        cur = conn.cursor()

                                        cur.execute("SELECT MAX(codigo_venda) FROM vendas WHERE empresa_id=%s", (int(emp_id),))
                                        resultado = cur.fetchone()[0]
                                        novo_cod = int(resultado + 1) if resultado else 1

                                        data_v = data_venda_input.strftime("%d/%m/%Y")
                                        cli_id_v = int(df_cli[df_cli['nome'] == cliente_pdv].iloc[0]['id'])

                                        for it in st.session_state['carrinho']:
                                            cur.execute("""INSERT INTO vendas (codigo_venda, cliente_id, produto_id, quantidade, data_venda, valor_total, empresa_id, valor_unitario, desconto, forma_pagamento, valor_entrada, valor_restante, qtd_parcelas, colaborador_id) 
                                                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                                       (int(novo_cod), int(cli_id_v), int(it['id']), int(it['qtd']), str(data_v), float(it['total']), int(emp_id), float(it['unit']), float(it['desc']), str(f_pag), float(valor_entrada), float(valor_restante), int(qtd_parcelas), it['colab_id']))

                                            if it['tipo'] == 'P':
                                                cur.execute("UPDATE produtos SET quantidade = quantidade - %s WHERE id=%s", (int(it['qtd']), int(it['id'])))

                                        if f_pag == "Crediário" and valor_entrada > 0:
                                            cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, data_pagamento, empresa_id) 
                                                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                                        (int(novo_cod), int(cli_id_v), 1, int(qtd_parcelas), float(valor_entrada), data_v, 'Pago', data_v, int(emp_id)))

                                            if qtd_parcelas > 1:
                                                valor_parc_restante = valor_restante / (qtd_parcelas - 1)
                                                for i in range(2, int(qtd_parcelas) + 1):
                                                    data_venc_str = datas_parcelas[i-1].strftime("%d/%m/%Y")
                                                    cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id) 
                                                                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                                                                (int(novo_cod), int(cli_id_v), i, int(qtd_parcelas), float(valor_parc_restante), data_venc_str, 'Pendente', int(emp_id)))
                                        else:
                                            valor_parcela = total_pdv / qtd_parcelas
                                            for i in range(1, int(qtd_parcelas) + 1):
                                                data_venc_str = datas_parcelas[i-1].strftime("%d/%m/%Y")
                                                status_pg = 'Pago' if f_pag in ['Pix', 'Crédito', 'Débito', 'Dinheiro'] else 'Pendente'
                                                data_pg = data_v if status_pg == 'Pago' else None

                                                cur.execute("""INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, data_pagamento, empresa_id) 
                                                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                                                            (int(novo_cod), int(cli_id_v), i, int(qtd_parcelas), float(valor_parcela), data_venc_str, status_pg, data_pg, int(emp_id)))

                                        cur_cli = carregar_dados_cached("SELECT telefone FROM clientes WHERE nome=%s AND empresa_id=%s", (cliente_pdv, emp_id))
                                        tel_cli = cur_cli.iloc[0]['telefone'] if not cur_cli.empty else None

                                        lista_produtos_msg = ""
                                        for it in st.session_state['carrinho']:
                                            lista_produtos_msg += f"▫️ {int(it['qtd'])}x {it['nome']} (R$ {it['unit']:.2f})\n".replace('.', ',')
                                            if float(it.get('desc', 0)) > 0:
                                                desc_total_item = float(it['desc']) * int(it['qtd'])
                                                lista_produtos_msg += f"   ↳ 📉 Desconto: - R$ {desc_total_item:.2f}\n".replace('.', ',')

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
                                                if not tel_limpo.startswith('55'):
                                                    tel_limpo = '55' + tel_limpo
                                                st.session_state['zap_link'] = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                                                st.session_state['zap_msg'] = msg
                                                st.session_state['zap_codigo'] = f"PEDIDO Nº {novo_cod}"
                                                st.session_state['zap_total'] = total_pdv

                                        conn.commit()
                                        devolver_conexao(conn)
                                        st.session_state['carrinho'] = []
                                        st.session_state['pdv_reset'] += 1
                                        st.session_state['reset_prod'] += 1
                                        limpar_cache()
                                        st.rerun()

                                    except Exception as e:
                                        st.error(f"Erro no banco: {e}")
                                        if 'conn' in locals():
                                            devolver_conexao(conn)

                                c_orc, c_limpar = st.columns(2)
                                if c_orc.button("📋 Salvar orçamento", use_container_width=True):
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
                                    except Exception as e:
                                        st.error(f"Erro ao salvar orçamento: {e}")

                                    cur_cli = carregar_dados_cached("SELECT telefone FROM clientes WHERE nome=%s AND empresa_id=%s", (cliente_pdv, emp_id))
                                    tel_cli = cur_cli.iloc[0]['telefone'] if not cur_cli.empty else None

                                    lista_produtos_msg = ""
                                    for it in st.session_state['carrinho']:
                                        lista_produtos_msg += f"▫️ {int(it['qtd'])}x {it['nome']} (R$ {it['unit']:.2f})\n".replace('.', ',')
                                        if float(it.get('desc', 0)) > 0:
                                            desc_total_item = float(it['desc']) * int(it['qtd'])
                                            lista_produtos_msg += f"   ↳ 📉 Desconto: - R$ {desc_total_item:.2f}\n".replace('.', ',')

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
                                            if not tel_limpo.startswith('55'):
                                                tel_limpo = '55' + tel_limpo
                                            st.session_state['zap_link'] = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                                            st.session_state['zap_msg'] = msg
                                            st.session_state['zap_codigo'] = "ORÇAMENTO EM ABERTO"
                                            st.session_state['zap_total'] = total_pdv

                                    st.rerun()

                                if c_limpar.button("🧹 Limpar carrinho", use_container_width=True):
                                    st.session_state['carrinho'] = []
                                    st.session_state['reset_prod'] += 1
                                    st.rerun()
                else:
                    st.warning("Cadastre clientes e produtos antes de vender.")

                # --- EXPANDER: EDITAR FORMA DE PAGAMENTO ---
                # Fica FORA do bloco condicional para aparecer sempre
                st.markdown("---")
                st.markdown("### ⚙️ Ajustes administrativos")
                with st.expander("✏️ Corrigir forma de pagamento de uma venda", expanded=False):
                    st.caption("Área de manutenção: busque a venda pelo número ou cliente, altere a forma de pagamento e as parcelas serão recriadas.")

                    col_busca1, col_busca2 = st.columns(2)
                    busca_cod = col_busca1.number_input("Nº da Venda:", min_value=0, step=1, value=0, key="edit_fp_cod")
                    busca_cli = col_busca2.text_input("Ou busque pelo nome do cliente:", key="edit_fp_cli")

                    if st.button("🔍 Buscar Venda", key="btn_buscar_venda_fp"):
                        if busca_cod > 0:
                            df_busca = carregar_dados("""
                                SELECT v.codigo_venda, c.nome AS cliente, 
                                       SUM(v.valor_total) AS total,
                                       MAX(v.forma_pagamento) AS forma_pagamento,
                                       MAX(v.qtd_parcelas) AS qtd_parcelas,
                                       MAX(v.data_venda) AS data_venda,
                                       MAX(v.cliente_id) AS cliente_id
                                FROM vendas v
                                JOIN clientes c ON c.id = v.cliente_id
                                WHERE v.empresa_id = %s AND v.codigo_venda = %s
                                GROUP BY v.codigo_venda, c.nome
                            """, (emp_id, int(busca_cod)))
                        elif busca_cli:
                            df_busca = carregar_dados("""
                                SELECT v.codigo_venda, c.nome AS cliente,
                                       SUM(v.valor_total) AS total,
                                       MAX(v.forma_pagamento) AS forma_pagamento,
                                       MAX(v.qtd_parcelas) AS qtd_parcelas,
                                       MAX(v.data_venda) AS data_venda,
                                       MAX(v.cliente_id) AS cliente_id
                                FROM vendas v
                                JOIN clientes c ON c.id = v.cliente_id
                                WHERE v.empresa_id = %s AND c.nome ILIKE %s
                                GROUP BY v.codigo_venda, c.nome
                                ORDER BY v.codigo_venda DESC
                                LIMIT 10
                            """, (emp_id, f"%{busca_cli}%"))
                        else:
                            st.warning("Informe o número da venda ou o nome do cliente.")
                            df_busca = pd.DataFrame()

                        if not df_busca.empty:
                            st.session_state['edit_fp_resultado'] = df_busca
                        else:
                            st.warning("Nenhuma venda encontrada.")
                            st.session_state.pop('edit_fp_resultado', None)

                    if 'edit_fp_resultado' in st.session_state:
                        df_res = st.session_state['edit_fp_resultado']

                        opcoes = df_res.apply(
                            lambda r: f"Venda Nº {int(r['codigo_venda'])} — {r['cliente']} — R$ {float(r['total']):,.2f} — {r['forma_pagamento']}".replace(",","X").replace(".",",").replace("X","."),
                            axis=1
                        ).tolist()

                        sel = st.selectbox("Selecione a venda:", opcoes, key="edit_fp_sel")
                        idx_sel = opcoes.index(sel)
                        venda_sel = df_res.iloc[idx_sel]

                        total_venda    = float(venda_sel['total'])
                        forma_atual    = str(venda_sel['forma_pagamento'])
                        cod_venda      = int(venda_sel['codigo_venda'])
                        cli_id_venda   = int(venda_sel['cliente_id'])
                        data_venda_str = str(venda_sel['data_venda'])

                        st.info(f"💰 Total da venda: **R$ {total_venda:,.2f}** | Forma atual: **{forma_atual}**".replace(",","X").replace(".",",").replace("X","."))

                        col_fp, col_parc = st.columns(2)
                        nova_forma = col_fp.selectbox(
                            "Nova Forma de Pagamento:",
                            ["Pix", "Crédito", "Débito", "Dinheiro", "Crediário"],
                            index=["Pix", "Crédito", "Débito", "Dinheiro", "Crediário"].index(forma_atual) if forma_atual in ["Pix", "Crédito", "Débito", "Dinheiro", "Crediário"] else 0,
                            key="edit_fp_nova"
                        )
                        novas_parcelas = col_parc.number_input("Número de Parcelas:", min_value=1, max_value=24, value=1, step=1, key="edit_fp_parc")

                        datas_novas = []
                        if novas_parcelas > 1:
                            st.markdown("📅 **Datas de Vencimento das Novas Parcelas:**")
                            cols_dt = st.columns(min(int(novas_parcelas), 4))
                            for i in range(1, int(novas_parcelas) + 1):
                                sugerido = date.today() + timedelta(days=30 * (i - 1))
                                with cols_dt[(i-1) % min(int(novas_parcelas), 4)]:
                                    dt = st.date_input(f"{i}ª Parcela", value=sugerido, format="DD/MM/YYYY", key=f"edit_fp_dt_{cod_venda}_{i}")
                                    datas_novas.append(dt)
                        else:
                            datas_novas.append(date.today())

                        if st.button("💾 Salvar Alteração", type="primary", use_container_width=True, key="btn_salvar_fp"):
                            try:
                                conn = conectar_banco()
                                cur = conn.cursor()

                                cur.execute("""
                                    UPDATE vendas 
                                    SET forma_pagamento = %s, qtd_parcelas = %s
                                    WHERE codigo_venda = %s AND empresa_id = %s
                                """, (nova_forma, int(novas_parcelas), cod_venda, emp_id))

                                cur.execute("""
                                    DELETE FROM contas_receber 
                                    WHERE venda_codigo = %s AND empresa_id = %s
                                """, (cod_venda, emp_id))

                                val_parcela = float(total_venda / novas_parcelas)
                                for i, dt_venc in enumerate(datas_novas, start=1):
                                    status_p = 'Pago' if novas_parcelas == 1 and nova_forma != 'Crediário' else 'Pendente'
                                    data_pag  = data_venda_str if status_p == 'Pago' else None
                                    cur.execute("""
                                        INSERT INTO contas_receber 
                                        (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, data_pagamento, empresa_id)
                                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    """, (cod_venda, cli_id_venda, i, int(novas_parcelas), val_parcela,
                                          dt_venc.strftime("%d/%m/%Y"), status_p, data_pag, emp_id))

                                cur.close()
                                conn.commit()
                                devolver_conexao(conn)
                                st.success(f"✅ Venda Nº {cod_venda} atualizada! Forma: {nova_forma} | {novas_parcelas}x de R$ {val_parcela:,.2f}".replace(",","X").replace(".",",").replace("X","."))
                                limpar_cache()
                                st.session_state.pop('edit_fp_resultado', None)
                                st.rerun()

                            except Exception as e:
                                st.error(f"Erro ao atualizar: {e}")
                                if 'conn' in locals(): devolver_conexao(conn)        

        # Inicializa o carrinho de serviços se não existir
        if 'carrinho_servicos' not in st.session_state:
            st.session_state['carrinho_servicos'] = []

        if tab_lanca_serv:
            with tab_lanca_serv:
                # ==========================================================
                # SERVIÇOS 2.0 — Tela de Serviços com identidade do PDV
                # Mantém a lógica original: serviço, profissional, insumos,
                # financeiro, recibo WhatsApp e link de avaliação.
                # ==========================================================
                st.markdown("""
                    <style>
                    .serv2-header {
                        border-bottom: 1px solid #e5e7eb;
                        padding: 2px 0 8px 0;
                        margin: -4px 0 10px 0;
                        display: flex;
                        align-items: center;
                        justify-content: space-between;
                        gap: 10px;
                    }
                    .serv2-title {
                        font-size: 1.05rem;
                        font-weight: 900;
                        color: #111827;
                        line-height: 1.15;
                    }
                    .serv2-subtitle {
                        color: #64748b;
                        font-size: 0.78rem;
                        line-height: 1.2;
                        text-align: right;
                        white-space: nowrap;
                    }
                    .serv2-section-title {
                        font-weight: 900;
                        color: #1f2937;
                        font-size: 0.94rem;
                        margin-bottom: 4px;
                    }
                    .serv2-total-box {
                        border-radius: 14px;
                        padding: 12px 14px;
                        margin: 4px 0 10px 0;
                        background: linear-gradient(135deg, #f8fafc 0%, #f5f3ff 100%);
                        border: 1px solid #ddd6fe;
                    }
                    .serv2-total-label {
                        font-size: 0.76rem;
                        color: #6d28d9;
                        font-weight: 800;
                        text-transform: uppercase;
                        letter-spacing: .035em;
                    }
                    .serv2-total-value {
                        font-size: 1.8rem;
                        color: #0f172a;
                        font-weight: 950;
                        line-height: 1.0;
                        margin-top: 2px;
                    }
                    .serv2-small-note {
                        color: #64748b;
                        font-size: 0.78rem;
                    }
                    div[data-testid="stVerticalBlock"] { gap: 0.55rem; }
                    @media (max-width: 768px) {
                        .serv2-header {
                            display: block;
                            padding: 0 0 6px 0;
                            margin: -8px 0 8px 0;
                        }
                        .serv2-title { font-size: 0.98rem; }
                        .serv2-subtitle {
                            text-align: left;
                            white-space: normal;
                            font-size: 0.72rem;
                            margin-top: 2px;
                        }
                        .serv2-total-value { font-size: 1.45rem; }
                        .serv2-total-box { padding: 10px 12px; }
                    }
                    </style>
                """, unsafe_allow_html=True)

                st.markdown(
                    """
                    <div class="serv2-header">
                        <div class="serv2-title">✨ Lançar Serviço</div>
                        <div class="serv2-subtitle">Serviço • Profissional • Insumos • Avaliação</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

                # Carrega dados
                df_cli = carregar_dados_cached("SELECT id, nome FROM clientes WHERE empresa_id=%s ORDER BY nome", (emp_id,))
                df_serv = carregar_dados_cached("SELECT id, nome, valor FROM produtos WHERE empresa_id=%s AND tipo='S' ORDER BY nome", (emp_id,))
                df_prod_insumo = carregar_dados_cached("SELECT id, nome FROM produtos WHERE empresa_id=%s AND tipo='P' AND classe='Insumo' ORDER BY nome", (emp_id,))
                df_colab = carregar_dados_cached("SELECT id, nome FROM colaboradores WHERE ativo = TRUE AND empresa_id = %s", (emp_id,))

                if not df_cli.empty and not df_serv.empty and not df_colab.empty:
                    # Painel do recibo fica logo no topo da aba para o operador não precisar procurar após finalizar.
                    if 'zap_link_serv' in st.session_state and st.session_state['zap_link_serv']:
                        with st.container(border=True):
                            st.success(f"🎉 {st.session_state['zap_codigo_serv']} finalizado! Total: R$ {st.session_state['zap_total_serv']:.2f}".replace('.', ','))
                            st.markdown('<div class="serv2-section-title">📲 Enviar recibo e avaliação via WhatsApp</div>', unsafe_allow_html=True)

                            msg_editada = st.text_area(
                                "✏️ Edite a mensagem antes de enviar:",
                                value=st.session_state['zap_msg_serv'],
                                height=220,
                                key="msg_editada_serv_top"
                            )

                            tel_serv = st.session_state.get('zap_tel_serv', '')
                            if tel_serv:
                                link_atualizado = f"https://wa.me/{tel_serv}?text={urllib.parse.quote(msg_editada)}"
                            else:
                                link_atualizado = st.session_state['zap_link_serv']

                            c_w1, c_w2 = st.columns([2, 1])
                            c_w1.link_button("🟢 Abrir WhatsApp e Enviar", link_atualizado, type="primary", use_container_width=True)
                            if c_w2.button("➕ Novo atendimento", use_container_width=True, key="novo_atend_serv_top"):
                                for k in ['zap_link_serv', 'zap_msg_serv', 'zap_codigo_serv', 'zap_total_serv', 'zap_tel_serv']:
                                    if k in st.session_state:
                                        del st.session_state[k]
                                st.rerun()

                    col_operacao, col_resumo = st.columns([1.05, 1], gap="medium")

                    with col_operacao:
                        with st.container(border=True):
                            st.markdown('<div class="serv2-section-title">👤 Atendimento</div>', unsafe_allow_html=True)
                            c_cli, c_data = st.columns([1.8, 1], gap="small")
                            cliente_pdv = c_cli.selectbox(
                                "Cliente",
                                options=df_cli['nome'].tolist(),
                                index=None,
                                placeholder="Selecione a cliente...",
                                key="cli_serv"
                            )
                            data_venda_input = c_data.date_input(
                                "Data",
                                format="DD/MM/YYYY",
                                value=date.today(),
                                key="dt_serv"
                            )

                            c_pag, c_parc = st.columns([1.5, 1], gap="small")
                            f_pag = c_pag.selectbox(
                                "Pagamento",
                                ["Pix", "Crédito", "Débito", "Dinheiro", "Crediário"],
                                index=None,
                                placeholder="Forma...",
                                key="fpag_serv"
                            )

                            qtd_parcelas = 1
                            data_1_venc = date.today()
                            if f_pag:
                                qtd_parcelas = c_parc.number_input(
                                    "Parcelas",
                                    min_value=1,
                                    max_value=12,
                                    value=1,
                                    step=1,
                                    key="parc_serv"
                                )
                                sugestao_venc = date.today() if qtd_parcelas == 1 else date.today() + timedelta(days=30)
                                data_1_venc = st.date_input(
                                    "Data do 1º vencimento",
                                    value=sugestao_venc,
                                    format="DD/MM/YYYY",
                                    key="venc1_serv"
                                )

                        with st.container(border=True):
                            st.markdown('<div class="serv2-section-title">✨ Procedimento</div>', unsafe_allow_html=True)
                            col_s1, col_s2 = st.columns([1.4, 1], gap="small")
                            serv_display = col_s1.selectbox(
                                "Serviço",
                                options=df_serv['nome'].tolist(),
                                index=None,
                                placeholder="Escolha o procedimento...",
                                key="servico_serv2"
                            )
                            nome_colab = col_s2.selectbox(
                                "Profissional",
                                options=df_colab['nome'].tolist(),
                                index=None,
                                placeholder="Executor...",
                                key="colab_serv2"
                            )

                            opcoes_insumos = df_prod_insumo['nome'].tolist() if not df_prod_insumo.empty else []
                            msg_placeholder = "Selecione os insumos utilizados..." if opcoes_insumos else "⚠️ Nenhum insumo cadastrado."
                            insumos_selecionados = st.multiselect(
                                "Insumos utilizados na sessão",
                                options=opcoes_insumos,
                                placeholder=msg_placeholder,
                                help="Estes itens ficam salvos na ficha da cliente para consultas futuras.",
                                key="insumos_serv2"
                            )

                            if serv_display:
                                s_info = df_serv[df_serv['nome'] == serv_display].iloc[0]
                                preco_tabela = float(s_info['valor'])
                                st.info(f"🏷️ Preço base: R$ {preco_tabela:.2f}".replace('.', ','))

                                c1, c2, c3, c4 = st.columns([0.9, 1.1, 1, 1], gap="small")
                                q_pdv = c1.number_input("Sessões", min_value=1, step=1, value=1, key="qtd_serv2")
                                preco_custom = c2.number_input("Preço (R$)", min_value=0.0, value=float(preco_tabela), step=1.0, format="%.2f", key="preco_serv2")
                                desc_rs = c3.number_input("Desc. R$", min_value=0.0, step=1.0, format="%.2f", key="d_rs_s")
                                desc_perc = c4.number_input("Desc. %", min_value=0.0, max_value=100.0, step=1.0, format="%.1f", key="d_perc_s")

                                trava_add = (cliente_pdv is None) or (f_pag is None) or (nome_colab is None)
                                if trava_add:
                                    st.warning("Preencha cliente, pagamento e profissional para adicionar o serviço.")

                                if st.button("➕ ADICIONAR SERVIÇO", type="primary", disabled=trava_add, use_container_width=True, key="add_serv2"):
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
                            else:
                                st.caption("Selecione um serviço para informar profissional, insumos, sessões e desconto.")

                    with col_resumo:
                        with st.container(border=True):
                            st.markdown('<div class="serv2-section-title">🛒 Serviços adicionados</div>', unsafe_allow_html=True)

                            total_pdv = 0.0
                            desconto_total_serv = 0.0
                            qtd_sessoes_serv = 0

                            if st.session_state['carrinho_servicos']:
                                col_c1, col_c2, col_c3, col_c4 = st.columns([4, 1, 1.6, 0.6], gap="small")
                                col_c1.markdown("**Procedimento**")
                                col_c2.markdown("**Qtd**")
                                col_c3.markdown("**Total**")
                                st.markdown("<hr style='margin: 4px 0 8px 0; opacity: .25;'>", unsafe_allow_html=True)

                                for i, item in enumerate(st.session_state['carrinho_servicos']):
                                    item_total = float(item['total'])
                                    item_qtd = int(item['qtd'])
                                    item_desc = float(item.get('desc', 0)) * item_qtd
                                    total_pdv += item_total
                                    desconto_total_serv += item_desc
                                    qtd_sessoes_serv += item_qtd

                                    col_i1, col_i2, col_i3, col_i4 = st.columns([4, 1, 1.6, 0.6], gap="small")
                                    col_i1.write(f"▫️ {item['nome']}")
                                    col_i2.write(f"{item_qtd}x")
                                    col_i3.write(f"R$ {item_total:.2f}".replace('.', ','))
                                    if col_i4.button("🗑️", key=f"del_serv_{i}", help="Remover serviço"):
                                        st.session_state['carrinho_servicos'].pop(i)
                                        st.rerun()
                            else:
                                st.info("Nenhum serviço adicionado ainda.")

                            subtotal_bruto = total_pdv + desconto_total_serv
                            total_pdv_fmt = f"R$ {total_pdv:.2f}".replace('.', ',')
                            subtotal_fmt = f"R$ {subtotal_bruto:.2f}".replace('.', ',')
                            desconto_fmt = f"R$ {desconto_total_serv:.2f}".replace('.', ',')

                            st.markdown("---")
                            st.markdown(f"""
                                <div class="serv2-total-box">
                                    <div class="serv2-total-label">Total do atendimento</div>
                                    <div class="serv2-total-value">{total_pdv_fmt}</div>
                                    <div class="serv2-small-note">{qtd_sessoes_serv} sessão(ões) • Subtotal {subtotal_fmt} • Descontos {desconto_fmt}</div>
                                </div>
                            """, unsafe_allow_html=True)

                            valor_entrada = 0.0
                            valor_restante = float(total_pdv)
                            datas_parcelas = []

                            if st.session_state['carrinho_servicos']:
                                if f_pag == "Crediário":
                                    valor_entrada = st.number_input(
                                        "Valor da entrada (R$)",
                                        min_value=0.0,
                                        max_value=float(total_pdv),
                                        value=0.0,
                                        step=10.0,
                                        key="ent_s"
                                    )

                                valor_restante = float(total_pdv - valor_entrada)

                                if qtd_parcelas > 1 or f_pag == "Crediário":
                                    with st.expander("📅 Cronograma de vencimentos", expanded=False):
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

                                c1_finalizar, c3_limpar = st.columns([2, 1], gap="small")

                                if c1_finalizar.button("✅ FINALIZAR ATENDIMENTO", type="primary", use_container_width=True):
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
                                            partes = it['nome'].split(' | Insumos:')
                                            nome_serv = partes[0]
                                            lista_produtos_msg += f"▫️ {nome_serv} (R$ {it['unit']:.2f})\n".replace('.', ',')

                                        link_avaliacao = f"https://wa.me/?text=Atendimento%20N%C2%BA%20{novo_cod}%20-%20Avalia%C3%A7%C3%A3o"
                                        url_base = st.secrets.get("APP_URL", "")
                                        if url_base:
                                            nome_encoded = urllib.parse.quote(cliente_pdv)
                                            link_avaliacao = f"{url_base}?avaliacao={novo_cod}&empresa={emp_id}&cliente={nome_encoded}"

                                        msg = f"Olá, {cliente_pdv}! ✨\n\n"
                                        msg += f"Obrigada por escolher nossos serviços hoje ({data_v}). Aqui está o seu recibo:\n\n"
                                        msg += f"🧾 *Atendimento Nº {novo_cod}*\n\n"
                                        msg += f"*Procedimentos Realizados:*\n{lista_produtos_msg}\n"
                                        msg += f"💰 *Valor Total:* R$ {total_pdv:.2f}\n".replace('.', ',')
                                        msg += f"💳 *Forma de Pagto:* {f_pag}\n\n"
                                        msg += "Foi um prazer atender você. Até a próxima! 🌸\n\n"
                                        msg += f"⭐ *Avalie seu atendimento:*\n{link_avaliacao}"

                                        if tel_cli:
                                            tel_limpo = ''.join(filter(str.isdigit, str(tel_cli)))
                                            if len(tel_limpo) >= 10:
                                                if not tel_limpo.startswith('55'):
                                                    tel_limpo = '55' + tel_limpo
                                                st.session_state['zap_link_serv'] = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg)}"
                                                st.session_state['zap_msg_serv'] = msg
                                                st.session_state['zap_codigo_serv'] = f"ATENDIMENTO Nº {novo_cod}"
                                                st.session_state['zap_total_serv'] = total_pdv
                                                st.session_state['zap_tel_serv'] = tel_limpo

                                        conn.commit()
                                        devolver_conexao(conn)
                                        st.session_state['carrinho_servicos'] = []
                                        st.success(f"Ficha técnica e Atendimento {novo_cod} salvos com sucesso!")
                                        limpar_cache()
                                        st.rerun()

                                    except Exception as e:
                                        st.error(f"Erro no banco: {e}")
                                        if 'conn' in locals():
                                            devolver_conexao(conn)

                                if c3_limpar.button("🗑️ Limpar", use_container_width=True):
                                    st.session_state['carrinho_servicos'] = []
                                    st.rerun()
                else:
                    st.warning("Cadastre clientes, colaboradores e serviços para habilitar esta tela.")

                
        if tab_orcamentos:
            with tab_orcamentos:
                st.markdown('<div class="ads-screen-title">📋 Orçamentos Salvos</div><div class="ads-screen-caption">Consulte, edite, converta ou exclua propostas comerciais.</div>', unsafe_allow_html=True)
                
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
                st.markdown('<div class="ads-screen-title">📥 Entrada de Mercadorias</div><div class="ads-screen-caption">Registre compras e atualize o estoque de forma organizada.</div>', unsafe_allow_html=True)
                
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
                st.markdown('<div class="ads-screen-title">📋 Histórico de Entradas</div><div class="ads-screen-caption">Consulte os itens recebidos e realize estornos quando necessário.</div>', unsafe_allow_html=True)
                
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
        # ADS 2.0 PREMIUM — Conciliação comercial e de estoque
        # ==========================================
        if tab_trocas:
            with tab_trocas:
                st.markdown(
                    '<div class="ads-screen-title">🔄 Central de Trocas e Empréstimos</div>'
                    '<div class="ads-screen-caption">Registre o que sai para a consultora, o que retorna ao estoque e acompanhe o acerto em standby.</div>',
                    unsafe_allow_html=True
                )

                # --- INICIALIZAÇÃO DOS CARRINHOS DE TROCA ---
                if 'troca_saida' not in st.session_state:
                    st.session_state['troca_saida'] = []
                if 'troca_entrada' not in st.session_state:
                    st.session_state['troca_entrada'] = []

                # 1. SELEÇÃO DA CONSULTORA (Filtra apenas tipo = 'T')
                df_consultoras = carregar_dados_cached(
                    "SELECT id, nome FROM clientes WHERE empresa_id=%s AND tipo='T' ORDER BY nome",
                    (emp_id,)
                )

                if not df_consultoras.empty:
                    with st.container(border=True):
                        col_consultora, col_contexto = st.columns([2.2, 1])
                        lista_consultoras = df_consultoras['nome'].tolist()
                        consultora_sel = col_consultora.selectbox(
                            "👤 Consultora da negociação",
                            options=lista_consultoras,
                            index=None,
                            placeholder="Selecione a consultora...",
                            key="troca_consultora_sel"
                        )
                        id_consultora = None
                        if consultora_sel:
                            id_consultora = int(
                                df_consultoras[df_consultoras['nome'] == consultora_sel].iloc[0]['id']
                            )
                        col_contexto.markdown(
                            '<div class="ads-context-title">Status da operação</div>',
                            unsafe_allow_html=True
                        )
                        col_contexto.caption("🟡 Em preparação · estoque ainda não alterado")

                    # Carrega catálogo de produtos para os lançamentos
                    df_produtos = carregar_dados_cached(
                        "SELECT id, nome, valor, quantidade, tipo FROM produtos WHERE empresa_id=%s ORDER BY nome",
                        (emp_id,)
                    )

                    if not df_produtos.empty:
                        df_produtos['display'] = df_produtos.apply(
                            lambda x: f"{x['nome']} | R$ {x['valor']:.2f} (Estoque: {int(x['quantidade'])})",
                            axis=1
                        )
                        opcoes_prod = df_produtos['display'].tolist()

                        # 2. DOIS LADOS DA NEGOCIAÇÃO — VISÍVEIS AO MESMO TEMPO
                        col_saida, col_entrada = st.columns(2, gap="large")

                        # --- PAINEL DE SAÍDA ---
                        with col_saida:
                            with st.container(border=True):
                                st.markdown(
                                    '<div class="ads-panel-title">📤 Saída para a Consultora</div>'
                                    '<div class="ads-panel-caption">Produtos que deixam o estoque da empresa nesta negociação.</div>',
                                    unsafe_allow_html=True
                                )

                                with st.form("form_add_saida", clear_on_submit=True):
                                    item_sel_s = st.selectbox(
                                        "Produto de saída",
                                        options=opcoes_prod,
                                        index=None,
                                        placeholder="Digite ou selecione um produto...",
                                        key="troca_produto_saida"
                                    )
                                    c_qtd_s, c_val_s = st.columns(2)
                                    qtd_s = c_qtd_s.number_input(
                                        "Quantidade",
                                        min_value=1,
                                        step=1,
                                        value=1,
                                        key="troca_qtd_saida"
                                    )

                                    idx_s = opcoes_prod.index(item_sel_s) if item_sel_s else None
                                    preco_base_s = float(df_produtos.iloc[idx_s]['valor']) if idx_s is not None else 0.0
                                    preco_s = c_val_s.number_input(
                                        "Valor unitário (R$)",
                                        min_value=0.0,
                                        value=preco_base_s,
                                        step=1.0,
                                        format="%.2f",
                                        key="troca_valor_saida"
                                    )

                                    if st.form_submit_button(
                                        "➕ Adicionar à saída",
                                        type="primary",
                                        use_container_width=True
                                    ):
                                        if idx_s is None:
                                            st.error("Selecione um produto para adicionar à saída.")
                                        else:
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
                                    df_saida_ui = pd.DataFrame(st.session_state['troca_saida'])[
                                        ['nome', 'qtd', 'unit', 'total']
                                    ].rename(columns={
                                        'nome': 'Produto',
                                        'qtd': 'Qtd.',
                                        'unit': 'Valor unit.',
                                        'total': 'Total'
                                    })
                                    st.dataframe(
                                        df_saida_ui,
                                        use_container_width=True,
                                        hide_index=True,
                                        column_config={
                                            "Valor unit.": st.column_config.NumberColumn(format="R$ %.2f"),
                                            "Total": st.column_config.NumberColumn(format="R$ %.2f")
                                        }
                                    )
                                    if st.button(
                                        "🗑️ Limpar saída",
                                        key="limpar_s",
                                        use_container_width=True
                                    ):
                                        st.session_state['troca_saida'] = []
                                        st.rerun()
                                else:
                                    st.info("Nenhum produto adicionado à saída.")

                        # --- PAINEL DE ENTRADA ---
                        with col_entrada:
                            with st.container(border=True):
                                st.markdown(
                                    '<div class="ads-panel-title">📥 Retorno para a Empresa</div>'
                                    '<div class="ads-panel-caption">Produtos recebidos da consultora e que retornarão ao estoque.</div>',
                                    unsafe_allow_html=True
                                )

                                with st.form("form_add_entrada", clear_on_submit=True):
                                    item_sel_e = st.selectbox(
                                        "Produto de retorno",
                                        options=opcoes_prod,
                                        index=None,
                                        placeholder="Digite ou selecione um produto...",
                                        key="troca_produto_entrada"
                                    )
                                    c_qtd_e, c_val_e = st.columns(2)
                                    qtd_e = c_qtd_e.number_input(
                                        "Quantidade",
                                        min_value=1,
                                        step=1,
                                        value=1,
                                        key="troca_qtd_entrada"
                                    )

                                    idx_e = opcoes_prod.index(item_sel_e) if item_sel_e else None
                                    preco_base_e = float(df_produtos.iloc[idx_e]['valor']) if idx_e is not None else 0.0
                                    preco_e = c_val_e.number_input(
                                        "Valor unitário (R$)",
                                        min_value=0.0,
                                        value=preco_base_e,
                                        step=1.0,
                                        format="%.2f",
                                        key="troca_valor_entrada"
                                    )

                                    if st.form_submit_button(
                                        "➕ Adicionar ao retorno",
                                        type="primary",
                                        use_container_width=True
                                    ):
                                        if idx_e is None:
                                            st.error("Selecione um produto para adicionar ao retorno.")
                                        else:
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
                                    df_entrada_ui = pd.DataFrame(st.session_state['troca_entrada'])[
                                        ['nome', 'qtd', 'unit', 'total']
                                    ].rename(columns={
                                        'nome': 'Produto',
                                        'qtd': 'Qtd.',
                                        'unit': 'Valor unit.',
                                        'total': 'Total'
                                    })
                                    st.dataframe(
                                        df_entrada_ui,
                                        use_container_width=True,
                                        hide_index=True,
                                        column_config={
                                            "Valor unit.": st.column_config.NumberColumn(format="R$ %.2f"),
                                            "Total": st.column_config.NumberColumn(format="R$ %.2f")
                                        }
                                    )
                                    if st.button(
                                        "🗑️ Limpar retorno",
                                        key="limpar_e",
                                        use_container_width=True
                                    ):
                                        st.session_state['troca_entrada'] = []
                                        st.rerun()
                                else:
                                    st.info("Nenhum produto adicionado ao retorno.")

                        # 3. BALANÇO PROVISÓRIO DA NEGOCIAÇÃO
                        total_s = sum(item['total'] for item in st.session_state['troca_saida']) if st.session_state['troca_saida'] else 0.0
                        total_e = sum(item['total'] for item in st.session_state['troca_entrada']) if st.session_state['troca_entrada'] else 0.0
                        diferenca_balanco = total_s - total_e

                        st.markdown(
                            '<div class="ads-screen-title">⚖️ Balanço provisório</div>'
                            '<div class="ads-screen-caption">Compare o valor enviado à consultora com o retorno recebido antes de salvar a negociação.</div>',
                            unsafe_allow_html=True
                        )
                        with st.container(border=True):
                            c_m1, c_m2, c_m3 = st.columns(3)
                            c_m1.metric("📤 Total de saída", f"R$ {total_s:.2f}".replace('.', ','))
                            c_m2.metric("📥 Total de retorno", f"R$ {total_e:.2f}".replace('.', ','))

                            if diferenca_balanco == 0:
                                c_m3.metric("⚖️ Saldo", "R$ 0,00", delta="Valores equivalentes")
                                st.success("Permuta equilibrada: não há diferença financeira provisória.")
                            elif diferenca_balanco > 0:
                                c_m3.metric(
                                    "⚠️ Saldo",
                                    f"R$ {diferenca_balanco:.2f}".replace('.', ','),
                                    delta="Consultora deve",
                                    delta_color="inverse"
                                )
                                st.warning("A consultora ficará com saldo pendente para a empresa ao finalizar o acerto.")
                            else:
                                c_m3.metric(
                                    "ℹ️ Saldo",
                                    f"R$ {abs(diferenca_balanco):.2f}".replace('.', ','),
                                    delta="Empresa deve"
                                )
                                st.info("A empresa ficará com saldo pendente para a consultora ao finalizar o acerto.")

                            st.markdown(
                                '<div class="ads-panel-caption" style="margin-top:.35rem; margin-bottom:.45rem;">'
                                'Ao salvar, o estoque físico será atualizado imediatamente e a negociação permanecerá em standby até o fechamento financeiro.'
                                '</div>',
                                unsafe_allow_html=True
                            )

                            # 4. BOTÃO DE CONFIRMAÇÃO E GRAVAÇÃO
                            if st.button(
                                "💾 Salvar negociação em standby",
                                type="primary",
                                use_container_width=True,
                                key="salvar_troca_standby"
                            ):
                                if not consultora_sel or id_consultora is None:
                                    st.error("Selecione a consultora da negociação.")
                                elif not st.session_state['troca_saida'] and not st.session_state['troca_entrada']:
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
                                            cur.execute(
                                                "INSERT INTO trocas_itens (troca_id, produto_id, quantidade, valor_unitario, sentido) VALUES (%s, %s, %s, %s, 'S')",
                                                (id_troca_gerada, item['id'], item['qtd'], item['unit'])
                                            )
                                            if item['tipo'] == 'P':
                                                cur.execute(
                                                    "UPDATE produtos SET quantidade = quantidade - %s WHERE id=%s",
                                                    (item['qtd'], item['id'])
                                                )

                                        for item in st.session_state['troca_entrada']:
                                            cur.execute(
                                                "INSERT INTO trocas_itens (troca_id, produto_id, quantidade, valor_unitario, sentido) VALUES (%s, %s, %s, %s, 'E')",
                                                (id_troca_gerada, item['id'], item['qtd'], item['unit'])
                                            )
                                            if item['tipo'] == 'P':
                                                cur.execute(
                                                    "UPDATE produtos SET quantidade = quantidade + %s WHERE id=%s",
                                                    (item['qtd'], item['id'])
                                                )

                                        conn.commit()
                                        devolver_conexao(conn)

                                        st.session_state['troca_saida'] = []
                                        st.session_state['troca_entrada'] = []
                                        st.success(
                                            f"Negociação Nº {id_troca_gerada} enviada para o standby! Estoque físico atualizado."
                                        )
                                        limpar_cache()
                                        st.rerun()

                                    except Exception as e:
                                        st.error(f"Erro ao processar transação: {e}")
                                        if 'conn' in locals():
                                            devolver_conexao(conn)

                    # ==========================================
                    # ACOMPANHAMENTO DE NEGOCIAÇÕES EM STANDBY
                    # ==========================================
                    st.markdown("---")
                    st.markdown(
                        '<div class="ads-screen-title">🕒 Negociações em Standby</div>'
                        '<div class="ads-screen-caption">Consulte produtos em circulação, confira o saldo e finalize o acerto financeiro.</div>',
                        unsafe_allow_html=True
                    )

                    df_trocas_abertas = carregar_dados_cached("""
                        SELECT t.id, t.data_movimentacao, c.nome AS consultora, t.total_saida, t.total_entrada, t.cliente_id
                        FROM trocas t
                        JOIN clientes c ON t.cliente_id = c.id
                        WHERE t.empresa_id = %s AND t.status_financeiro = 'Em Aberto'
                        ORDER BY t.data_movimentacao DESC
                    """, (emp_id,))

                    if not df_trocas_abertas.empty:
                        qtd_abertas = len(df_trocas_abertas)
                        saldo_consultoras = (
                            df_trocas_abertas['total_saida'].astype(float)
                            - df_trocas_abertas['total_entrada'].astype(float)
                        )
                        c_ab1, c_ab2, c_ab3 = st.columns(3)
                        c_ab1.metric("Operações abertas", qtd_abertas)
                        c_ab2.metric(
                            "A receber de consultoras",
                            f"R$ {saldo_consultoras[saldo_consultoras > 0].sum():.2f}".replace('.', ',')
                        )
                        c_ab3.metric(
                            "Saldo a favor das consultoras",
                            f"R$ {abs(saldo_consultoras[saldo_consultoras < 0].sum()):.2f}".replace('.', ',')
                        )

                        for _, troca_aberta in df_trocas_abertas.iterrows():
                            id_t = troca_aberta['id']
                            nome_con = troca_aberta['consultora']
                            data_t = troca_aberta['data_movimentacao']
                            t_saida = float(troca_aberta['total_saida'])
                            t_entrada = float(troca_aberta['total_entrada'])
                            dif = t_saida - t_entrada

                            with st.container(border=True):
                                col_ident, col_saldo = st.columns([2.2, 1])
                                col_ident.markdown(f"**🔄 Negociação Nº {id_t} · {nome_con}**")
                                col_ident.caption(f"📅 Aberta em: {data_t}")

                                if dif == 0:
                                    col_saldo.success("⚖️ Equilibrada")
                                elif dif > 0:
                                    col_saldo.warning(f"Consultora deve R$ {dif:.2f}".replace('.', ','))
                                else:
                                    col_saldo.info(f"Empresa deve R$ {abs(dif):.2f}".replace('.', ','))

                                with st.expander("🔍 Ver itens e finalizar acerto", expanded=False):
                                    df_itens_t = carregar_dados_cached("""
                                        SELECT ti.quantidade, ti.valor_unitario, ti.sentido, p.nome
                                        FROM trocas_itens ti
                                        JOIN produtos p ON ti.produto_id = p.id
                                        WHERE ti.troca_id = %s
                                    """, (id_t,))

                                    if not df_itens_t.empty:
                                        det_saida, det_entrada = st.columns(2)

                                        with det_saida:
                                            st.markdown("**📤 Saída para a consultora**")
                                            df_s = df_itens_t[df_itens_t['sentido'] == 'S'].copy()
                                            if not df_s.empty:
                                                df_s['Total'] = df_s['quantidade'] * df_s['valor_unitario']
                                                st.dataframe(
                                                    df_s[['nome', 'quantidade', 'valor_unitario', 'Total']].rename(columns={
                                                        'nome': 'Produto',
                                                        'quantidade': 'Qtd.',
                                                        'valor_unitario': 'Valor unit.'
                                                    }),
                                                    use_container_width=True,
                                                    hide_index=True,
                                                    column_config={
                                                        "Valor unit.": st.column_config.NumberColumn(format="R$ %.2f"),
                                                        "Total": st.column_config.NumberColumn(format="R$ %.2f")
                                                    }
                                                )
                                            else:
                                                st.caption("Nenhum item de saída.")

                                        with det_entrada:
                                            st.markdown("**📥 Retorno para a empresa**")
                                            df_e = df_itens_t[df_itens_t['sentido'] == 'E'].copy()
                                            if not df_e.empty:
                                                df_e['Total'] = df_e['quantidade'] * df_e['valor_unitario']
                                                st.dataframe(
                                                    df_e[['nome', 'quantidade', 'valor_unitario', 'Total']].rename(columns={
                                                        'nome': 'Produto',
                                                        'quantidade': 'Qtd.',
                                                        'valor_unitario': 'Valor unit.'
                                                    }),
                                                    use_container_width=True,
                                                    hide_index=True,
                                                    column_config={
                                                        "Valor unit.": st.column_config.NumberColumn(format="R$ %.2f"),
                                                        "Total": st.column_config.NumberColumn(format="R$ %.2f")
                                                    }
                                                )
                                            else:
                                                st.caption("Nenhum item de retorno.")

                                    st.markdown("**Resumo financeiro**")
                                    r1, r2, r3 = st.columns(3)
                                    r1.metric("Saída", f"R$ {t_saida:.2f}".replace('.', ','))
                                    r2.metric("Retorno", f"R$ {t_entrada:.2f}".replace('.', ','))
                                    r3.metric("Diferença", f"R$ {abs(dif):.2f}".replace('.', ','))

                                    if dif == 0:
                                        st.success("⚖️ Valores equivalentes (permuta equilibrada).")
                                    elif dif > 0:
                                        st.warning(f"⚠️ Consultora pendente em: R$ {dif:.2f}".replace('.', ','))
                                    else:
                                        st.info(f"ℹ️ Empresa pendente em: R$ {abs(dif):.2f}".replace('.', ','))

                                    if st.button(
                                        "🏁 Finalizar e fechar negociação",
                                        key=f"btn_fechar_{id_t}",
                                        use_container_width=True,
                                        type="primary"
                                    ):
                                        try:
                                            conn = conectar_banco()
                                            cur = conn.cursor()

                                            if dif > 0:
                                                status_fin = 'Pendente Consultora'
                                                cur.execute("""
                                                    INSERT INTO contas_receber (venda_codigo, cliente_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id)
                                                    VALUES (%s, %s, 1, 1, %s, %s, 'Pendente', %s)
                                                """, (
                                                    int(id_t + 90000),
                                                    int(troca_aberta['cliente_id']),
                                                    float(dif),
                                                    date.today().strftime("%d/%m/%Y"),
                                                    emp_id
                                                ))
                                            else:
                                                status_fin = 'Compensado'

                                            cur.execute(
                                                "UPDATE trocas SET status_financeiro = %s, diferenca = %s WHERE id = %s",
                                                (status_fin, dif, id_t)
                                            )
                                            conn.commit()
                                            devolver_conexao(conn)
                                            st.success(f"Negociação Nº {id_t} finalizada e resolvida financeiramente!")
                                            limpar_cache()
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Erro ao finalizar: {e}")
                                            if 'conn' in locals():
                                                devolver_conexao(conn)
                    else:
                        st.info("Não há nenhuma negociação em standby no momento.")

                else:
                    st.warning(
                        "Nenhuma Consultora cadastrada no sistema. Vá em Cadastros e altere o tipo de um registro para 'Consultora'."
                    )

        # ==========================================
        # ABA: AGENDA DE ATENDIMENTOS
        # ==========================================
        if tab_agenda:
            with tab_agenda:
                st.markdown('<div class="ads-screen-title">📅 Agenda de Atendimentos</div><div class="ads-screen-caption">Visualize compromissos e marque novos horários em poucos passos.</div>', unsafe_allow_html=True)
                
                # Criamos duas sub-abas internas para organizar o espaço no celular
                aba_ver_agenda, aba_novo_agendamento = st.tabs(["📱 Visualizar Agenda", "➕ Marcar Horário"])
                
                # ---------------------------------------------------------
                # SUB-ABA 1: VISUALIZAR AGENDA (TIMELINE COM FILTROS AVANÇADOS)
                # ---------------------------------------------------------
                with aba_ver_agenda:
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
                    st.markdown('<div class="ads-screen-title">📝 Novo Agendamento</div><div class="ads-screen-caption">Selecione serviço, cliente, profissional, data e horário.</div>', unsafe_allow_html=True)
                    
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
                                hora_abertura = time(8, 0)
                                hora_fechamento = time(20, 0)
                                
                                dt_atual = datetime.combine(data_escolhida, hora_abertura)
                                dt_limite = datetime.combine(data_escolhida, hora_fechamento)
                                
                                lista_horarios = []
                                while dt_atual <= dt_limite:
                                    lista_horarios.append(dt_atual.strftime("%H:%M"))
                                    dt_atual += timedelta(minutes=duracao)
                                
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
        tab_rec, tab_pag, aba_fluxo_caixa, aba_comissoes = st.tabs(["🟢 Contas a Receber (Vendas)", "🔴 Contas a Pagar (Despesas)", "💸 Fluxo de Caixa", "🏆 Comissões"])
        
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
        
                        df_parc = carregar_dados_cached("SELECT id, venda_codigo, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id FROM contas_receber WHERE venda_codigo=%s AND empresa_id=%s ORDER BY num_parcela", (v_id, emp_id))
        
                        if not df_parc.empty:
                            total_original = float(df_parc['valor_parcela'].sum())
                            st.info(f"💰 **Valor Total Original da Venda:** R$ {total_original:,.2f}".replace(".", "v").replace(",", ".").replace("v", ","))
            
                            with st.form(f"f_reajuste_{v_id}"):
                                novos_dados = {}
                
                                for index, row in df_parc.iterrows():
                                    st.write(f"**Parcela {row['num_parcela']} de {row['total_parcelas']}** - Status: {row['status']}")
                                    
                                    # Converte a data string do banco (DD/MM/YYYY) para objeto date do Python
                                    try:
                                        data_atual = datetime.strptime(row['data_vencimento'], "%d/%m/%Y").date()
                                    except:
                                        data_atual = date.today() # Proteção anti-erro
                                        
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
                                        def _reajustar_parcelas(cur):
                                            for parcela_id, dados in novos_dados.items():
                                                # Atualiza agora o valor_parcela E a data_vencimento no banco
                                                cur.execute(
                                                    "UPDATE contas_receber SET valor_parcela=%s, data_vencimento=%s WHERE id=%s AND empresa_id=%s", 
                                                    (dados['valor'], dados['data'], parcela_id, emp_id)
                                                )
                                        executar_escrita(_reajustar_parcelas)
                        
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
                hoje = date.today()
                
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
                                # Salva como YYYY-MM-DD
                                executar_comando("UPDATE contas_pagar SET status = 'Pago', data_pagamento = %s WHERE id = %s AND empresa_id = %s", (data_pagto_real.strftime("%Y-%m-%d"), id_desp_baixa, emp_id))
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
                            def _lancar_despesas(cur):
                                for i in range(1, int(tot_parc_manual) + 1):
                                    venc_parc_manual = data_1_venc_manual + timedelta(days=30 * (i - 1))
                                    cur.execute("""
                                        INSERT INTO contas_pagar (fornecedor_id, num_parcela, total_parcelas, valor_parcela, data_vencimento, status, empresa_id)
                                        VALUES (%s, %s, %s, %s, %s, 'Pendente', %s)
                                    """, (id_forn_manual, i, int(tot_parc_manual), float(valor_total_manual), venc_parc_manual.strftime("%Y-%m-%d"), emp_id))
                            executar_escrita(_lancar_despesas)
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
                                executar_comando("""
                                    UPDATE contas_pagar 
                                    SET valor_parcela = %s, data_vencimento = %s, data_pagamento = %s 
                                    WHERE id = %s AND empresa_id = %s
                                """, (float(novo_v_desp), novo_venc_desp.strftime("%Y-%m-%d"), novo_pagto_desp_val, id_desp_crud, emp_id))
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
                                executar_comando("DELETE FROM contas_pagar WHERE id = %s AND empresa_id = %s", (id_desp_crud, emp_id))
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

            # ==========================================
            # FECHAMENTO DE CAIXA DO DIA
            # ==========================================
            st.markdown("---")
            st.subheader("🔒 Fechamento de Caixa")

            data_fechamento = st.date_input(
                "Selecione o dia para fechar o caixa:",
                value=date.today(),
                format="DD/MM/YYYY",
                key="data_fechamento_caixa"
            )

            if st.button("📊 Gerar Fechamento", type="primary"):
                data_str = data_fechamento.strftime('%d/%m/%Y')

                df_entradas_dia = carregar_dados("""
                    SELECT 
                        v.codigo_venda,
                        c.nome AS cliente,
                        p.nome AS produto,
                        p.tipo,
                        v.valor_total,
                        v.forma_pagamento
                    FROM vendas v
                    JOIN clientes c ON c.id = v.cliente_id
                    JOIN produtos p ON p.id = v.produto_id
                    WHERE v.empresa_id = %s AND v.data_venda = %s
                    ORDER BY v.codigo_venda
                """, (emp_id, data_str))

                df_recebimentos_dia = carregar_dados("""
                    SELECT 
                        cr.venda_codigo,
                        c.nome AS cliente,
                        cr.valor_parcela,
                        cr.num_parcela,
                        cr.total_parcelas,
                        cr.data_pagamento
                    FROM contas_receber cr
                    JOIN clientes c ON c.id = cr.cliente_id
                    WHERE cr.empresa_id = %s 
                      AND cr.status = 'Pago'
                      AND cr.data_pagamento = %s
                    ORDER BY cr.venda_codigo
                """, (emp_id, data_str))

                df_saidas_dia = carregar_dados("""
                    SELECT 
                        f.nome AS fornecedor,
                        cp.valor_parcela,
                        cp.num_parcela,
                        cp.total_parcelas,
                        cp.data_pagamento
                    FROM contas_pagar cp
                    JOIN fornecedores f ON f.id = cp.fornecedor_id
                    WHERE cp.empresa_id = %s 
                      AND cp.status = 'Pago'
                      AND cp.data_pagamento = %s
                    ORDER BY f.nome
                """, (emp_id, data_str))

                # Salva no session_state para persistir após clique no PDF
                st.session_state['fechamento_data_str']      = data_str
                st.session_state['fechamento_entradas']      = df_entradas_dia
                st.session_state['fechamento_recebimentos']  = df_recebimentos_dia
                st.session_state['fechamento_saidas']        = df_saidas_dia

            # Exibe o fechamento se já foi gerado
            if 'fechamento_data_str' in st.session_state:
                data_str        = st.session_state['fechamento_data_str']
                df_entradas_dia = st.session_state['fechamento_entradas']
                df_recebimentos_dia = st.session_state['fechamento_recebimentos']
                df_saidas_dia   = st.session_state['fechamento_saidas']

                total_vendas   = float(df_entradas_dia['valor_total'].sum()) if not df_entradas_dia.empty else 0.0
                total_recebido = float(df_recebimentos_dia['valor_parcela'].sum()) if not df_recebimentos_dia.empty else 0.0
                total_saidas   = float(df_saidas_dia['valor_parcela'].sum()) if not df_saidas_dia.empty else 0.0
                saldo_liquido  = total_recebido - total_saidas

                formas_pagamento = {}
                if not df_entradas_dia.empty:
                    for forma, grupo in df_entradas_dia.groupby('forma_pagamento'):
                        formas_pagamento[forma] = float(grupo['valor_total'].sum())

                st.markdown(f"### 📅 Fechamento do dia {data_str}")
                st.markdown("---")

                col1, col2, col3, col4 = st.columns(4)
                col1.metric("🛒 Vendas do Dia",    f"R$ {total_vendas:,.2f}".replace(",","X").replace(".",",").replace("X","."))
                col2.metric("💰 Total Recebido",   f"R$ {total_recebido:,.2f}".replace(",","X").replace(".",",").replace("X","."))
                col3.metric("📤 Total de Saídas",  f"R$ {total_saidas:,.2f}".replace(",","X").replace(".",",").replace("X","."))
                col4.metric("💵 Saldo Líquido",    f"R$ {saldo_liquido:,.2f}".replace(",","X").replace(".",",").replace("X","."),
                            delta=f"{'positivo' if saldo_liquido >= 0 else 'negativo'}")

                if formas_pagamento:
                    st.markdown("#### 💳 Entradas por Forma de Pagamento")
                    cols_fp = st.columns(len(formas_pagamento))
                    for idx, (forma, valor) in enumerate(formas_pagamento.items()):
                        cols_fp[idx].metric(forma, f"R$ {valor:,.2f}".replace(",","X").replace(".",",").replace("X","."))

                col_ent, col_sai = st.columns(2)

                with col_ent:
                    st.markdown("#### 📋 Vendas e Serviços")
                    if not df_entradas_dia.empty:
                        tipos = {'P': '🛍️', 'S': '✨'}
                        for _, row in df_entradas_dia.iterrows():
                            icone_tipo = tipos.get(row['tipo'], '▫️')
                            st.markdown(f"{icone_tipo} **{row['cliente']}** — {row['produto']}")
                            st.caption(f"R$ {float(row['valor_total']):,.2f} | {row['forma_pagamento']}".replace(",","X").replace(".",",").replace("X","."))
                    else:
                        st.info("Nenhuma venda neste dia.")

                with col_sai:
                    st.markdown("#### 📤 Saídas do Dia")
                    if not df_saidas_dia.empty:
                        for _, row in df_saidas_dia.iterrows():
                            st.markdown(f"🔴 **{row['fornecedor']}** — Parc {row['num_parcela']}/{row['total_parcelas']}")
                            st.caption(f"R$ {float(row['valor_parcela']):,.2f}".replace(",","X").replace(".",",").replace("X","."))
                    else:
                        st.info("Nenhuma saída neste dia.")

                st.markdown("---")

                # Geração do PDF em memória (sempre disponível após gerar fechamento)
                from reportlab.lib.pagesizes import A4
                from reportlab.lib import colors
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib.units import cm
                import io

                buffer = io.BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4,
                                        rightMargin=2*cm, leftMargin=2*cm,
                                        topMargin=2*cm, bottomMargin=2*cm)
                styles = getSampleStyleSheet()
                elementos = []

                titulo_style = ParagraphStyle('titulo', parent=styles['Title'], fontSize=16, spaceAfter=6)
                sub_style    = ParagraphStyle('sub', parent=styles['Normal'], fontSize=10, textColor=colors.grey, spaceAfter=20)
                bold_style   = ParagraphStyle('bold', parent=styles['Normal'], fontSize=11, fontName='Helvetica-Bold', spaceAfter=6)

                elementos.append(Paragraph("Fechamento de Caixa", titulo_style))
                elementos.append(Paragraph(f"Data: {data_str}", sub_style))
                elementos.append(Spacer(1, 0.3*cm))

                elementos.append(Paragraph("Resumo Geral", bold_style))
                dados_resumo = [
                    ["Descrição", "Valor"],
                    ["Total de Vendas do Dia",    f"R$ {total_vendas:,.2f}".replace(",","X").replace(".",",").replace("X",".")],
                    ["Total Recebido (Parcelas)",  f"R$ {total_recebido:,.2f}".replace(",","X").replace(".",",").replace("X",".")],
                    ["Total de Saídas",            f"R$ {total_saidas:,.2f}".replace(",","X").replace(".",",").replace("X",".")],
                    ["Saldo Líquido",              f"R$ {saldo_liquido:,.2f}".replace(",","X").replace(".",",").replace("X",".")],
                ]
                t_resumo = Table(dados_resumo, colWidths=[11*cm, 5*cm])
                t_resumo.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4a4a8a')),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0,0), (-1,-1), 10),
                    ('ALIGN', (1,0), (1,-1), 'RIGHT'),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f0f0f0')]),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                    ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
                    ('TEXTCOLOR', (0,-1), (-1,-1), colors.HexColor('#00703c') if saldo_liquido >= 0 else colors.red),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                ]))
                elementos.append(t_resumo)
                elementos.append(Spacer(1, 0.5*cm))

                if formas_pagamento:
                    elementos.append(Paragraph("Entradas por Forma de Pagamento", bold_style))
                    dados_fp = [["Forma de Pagamento", "Total"]]
                    for forma, valor in formas_pagamento.items():
                        dados_fp.append([forma, f"R$ {valor:,.2f}".replace(",","X").replace(".",",").replace("X",".")])
                    t_fp = Table(dados_fp, colWidths=[11*cm, 5*cm])
                    t_fp.setStyle(TableStyle([
                        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4a4a8a')),
                        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0,0), (-1,-1), 10),
                        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
                        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f0f0f0')]),
                        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                        ('TOPPADDING', (0,0), (-1,-1), 6),
                    ]))
                    elementos.append(t_fp)
                    elementos.append(Spacer(1, 0.5*cm))

                if not df_entradas_dia.empty:
                    elementos.append(Paragraph("Vendas e Serviços do Dia", bold_style))
                    dados_v = [["Cliente", "Produto/Serviço", "Forma Pgto", "Valor"]]
                    for _, row in df_entradas_dia.iterrows():
                        dados_v.append([
                            str(row['cliente']),
                            str(row['produto']),
                            str(row['forma_pagamento']),
                            f"R$ {float(row['valor_total']):,.2f}".replace(",","X").replace(".",",").replace("X",".")
                        ])
                    t_v = Table(dados_v, colWidths=[5*cm, 5*cm, 3*cm, 3*cm])
                    t_v.setStyle(TableStyle([
                        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4a4a8a')),
                        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0,0), (-1,-1), 9),
                        ('ALIGN', (3,0), (3,-1), 'RIGHT'),
                        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f0f0f0')]),
                        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                        ('TOPPADDING', (0,0), (-1,-1), 5),
                    ]))
                    elementos.append(t_v)
                    elementos.append(Spacer(1, 0.5*cm))

                if not df_saidas_dia.empty:
                    elementos.append(Paragraph("Saídas do Dia", bold_style))
                    dados_s = [["Fornecedor", "Parcela", "Valor"]]
                    for _, row in df_saidas_dia.iterrows():
                        dados_s.append([
                            str(row['fornecedor']),
                            f"{row['num_parcela']}/{row['total_parcelas']}",
                            f"R$ {float(row['valor_parcela']):,.2f}".replace(",","X").replace(".",",").replace("X",".")
                        ])
                    t_s = Table(dados_s, colWidths=[9*cm, 3*cm, 4*cm])
                    t_s.setStyle(TableStyle([
                        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#8a2a2a')),
                        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0,0), (-1,-1), 9),
                        ('ALIGN', (2,0), (2,-1), 'RIGHT'),
                        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#fff0f0')]),
                        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                        ('TOPPADDING', (0,0), (-1,-1), 5),
                    ]))
                    elementos.append(t_s)

                doc.build(elementos)
                buffer.seek(0)

                st.download_button(
                    label="⬇️ Baixar PDF do Fechamento",
                    data=buffer,
                    file_name=f"fechamento_caixa_{data_fechamento.strftime('%d-%m-%Y')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )

                if st.button("🔄 Novo Fechamento", use_container_width=True):
                    for k in ['fechamento_data_str', 'fechamento_entradas', 'fechamento_recebimentos', 'fechamento_saidas']:
                        if k in st.session_state: del st.session_state[k]
                    st.rerun()

        # ==========================================
        # ABA: COMISSÕES
        # ==========================================
        with aba_comissoes:
            st.subheader("🏆 Relatório de Comissões")

            col_ini, col_fim = st.columns(2)
            hoje = date.today()
            d_ini_com = col_ini.date_input("Data Inicial:", value=hoje.replace(day=1), format="DD/MM/YYYY", key="com_ini")
            d_fim_com = col_fim.date_input("Data Final:", value=hoje, format="DD/MM/YYYY", key="com_fim")

            # Seletor de colaborador
            df_colab_com = carregar_dados_cached("SELECT id, nome FROM colaboradores WHERE ativo = TRUE AND empresa_id = %s ORDER BY nome", (emp_id,))
            opcoes_colab = ["👥 Todos os Colaboradores"] + df_colab_com['nome'].tolist() if not df_colab_com.empty else ["👥 Todos os Colaboradores"]
            filtro_colab = st.selectbox("Colaborador:", opcoes_colab, key="com_colab")

            if st.button("📊 Gerar Relatório de Comissões", type="primary"):
                # Monta filtro de colaborador
                if filtro_colab != "👥 Todos os Colaboradores":
                    colab_id_filtro = int(df_colab_com[df_colab_com['nome'] == filtro_colab].iloc[0]['id'])
                    filtro_sql = "AND v.colaborador_id = %s"
                    params_com = (emp_id, d_ini_com.strftime('%Y-%m-%d'), d_fim_com.strftime('%Y-%m-%d'), colab_id_filtro)
                else:
                    filtro_sql = ""
                    params_com = (emp_id, d_ini_com.strftime('%Y-%m-%d'), d_fim_com.strftime('%Y-%m-%d'))

                df_com = carregar_dados(f"""
                    SELECT
                        col.nome AS colaborador,
                        p.nome AS servico,
                        p.comissao_percentual,
                        v.valor_total,
                        ROUND((v.valor_total * p.comissao_percentual / 100)::numeric, 2) AS valor_comissao,
                        v.data_venda,
                        c.nome AS cliente
                    FROM vendas v
                    JOIN produtos p ON p.id = v.produto_id
                    JOIN colaboradores col ON col.id = v.colaborador_id
                    JOIN clientes c ON c.id = v.cliente_id
                    WHERE v.empresa_id = %s
                      AND p.tipo = 'S'
                      AND v.colaborador_id IS NOT NULL
                      AND TO_DATE(v.data_venda, 'DD/MM/YYYY') BETWEEN %s AND %s
                      {filtro_sql}
                    ORDER BY col.nome, v.data_venda
                """, params_com)

                if df_com.empty:
                    st.info("Nenhum serviço com comissão encontrado no período.")
                else:
                    st.session_state['com_df']        = df_com
                    st.session_state['com_ini_val']   = d_ini_com
                    st.session_state['com_fim_val']   = d_fim_com

            if 'com_df' in st.session_state:
                df_com    = st.session_state['com_df']
                d_ini_com = st.session_state['com_ini_val']
                d_fim_com = st.session_state['com_fim_val']

                # --- RESUMO POR COLABORADOR ---
                st.markdown(f"#### 📅 Período: {d_ini_com.strftime('%d/%m/%Y')} a {d_fim_com.strftime('%d/%m/%Y')}")
                st.markdown("---")

                resumo = df_com.groupby('colaborador').agg(
                    atendimentos=('servico', 'count'),
                    total_servicos=('valor_total', 'sum'),
                    total_comissao=('valor_comissao', 'sum')
                ).reset_index().sort_values('total_comissao', ascending=False)

                total_geral_com = float(resumo['total_comissao'].sum())
                total_geral_serv = float(resumo['total_servicos'].sum())

                # Métricas gerais
                col1, col2, col3 = st.columns(3)
                col1.metric("👥 Colaboradores", len(resumo))
                col2.metric("💇 Total em Serviços", f"R$ {total_geral_serv:,.2f}".replace(",","X").replace(".",",").replace("X","."))
                col3.metric("💰 Total em Comissões", f"R$ {total_geral_com:,.2f}".replace(",","X").replace(".",",").replace("X","."))

                st.markdown("---")
                st.markdown("#### 👤 Resumo por Colaborador")

                for _, row in resumo.iterrows():
                    with st.container(border=True):
                        col_a, col_b, col_c, col_d = st.columns([3, 2, 2, 2])
                        col_a.markdown(f"**{row['colaborador']}**")
                        col_b.metric("Atendimentos", int(row['atendimentos']))
                        col_c.metric("Total Produzido", f"R$ {float(row['total_servicos']):,.2f}".replace(",","X").replace(".",",").replace("X","."))
                        col_d.metric("💰 Comissão", f"R$ {float(row['total_comissao']):,.2f}".replace(",","X").replace(".",",").replace("X","."))

                        # Detalhamento dos serviços do colaborador
                        df_det = df_com[df_com['colaborador'] == row['colaborador']]
                        with st.expander(f"Ver detalhes dos {int(row['atendimentos'])} atendimentos"):
                            for _, srv in df_det.iterrows():
                                st.markdown(f"▫️ **{srv['data_venda']}** — {srv['cliente']} — {srv['servico']}")
                                st.caption(f"Valor: R$ {float(srv['valor_total']):,.2f} | {float(srv['comissao_percentual'])}% = R$ {float(srv['valor_comissao']):,.2f}".replace(",","X").replace(".",",").replace("X","."))

                # --- EXPORTAR PDF ---
                st.markdown("---")
                from reportlab.lib.pagesizes import A4
                from reportlab.lib import colors
                from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib.units import cm
                import io

                buffer = io.BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4,
                                        rightMargin=2*cm, leftMargin=2*cm,
                                        topMargin=2*cm, bottomMargin=2*cm)
                styles = getSampleStyleSheet()
                elementos = []

                titulo_style = ParagraphStyle('titulo', parent=styles['Title'], fontSize=16, spaceAfter=6)
                sub_style    = ParagraphStyle('sub', parent=styles['Normal'], fontSize=10, textColor=colors.grey, spaceAfter=16)
                bold_style   = ParagraphStyle('bold', parent=styles['Normal'], fontSize=11, fontName='Helvetica-Bold', spaceAfter=6)

                elementos.append(Paragraph("Relatório de Comissões", titulo_style))
                elementos.append(Paragraph(f"Período: {d_ini_com.strftime('%d/%m/%Y')} a {d_fim_com.strftime('%d/%m/%Y')}", sub_style))
                elementos.append(Spacer(1, 0.3*cm))

                # Resumo geral
                elementos.append(Paragraph("Resumo por Colaborador", bold_style))
                dados_res = [["Colaborador", "Atendimentos", "Total Serviços", "Comissão"]]
                for _, row in resumo.iterrows():
                    dados_res.append([
                        str(row['colaborador']),
                        str(int(row['atendimentos'])),
                        f"R$ {float(row['total_servicos']):,.2f}".replace(",","X").replace(".",",").replace("X","."),
                        f"R$ {float(row['total_comissao']):,.2f}".replace(",","X").replace(".",",").replace("X","."),
                    ])
                # Linha de total
                dados_res.append([
                    "TOTAL GERAL", str(int(resumo['atendimentos'].sum())),
                    f"R$ {total_geral_serv:,.2f}".replace(",","X").replace(".",",").replace("X","."),
                    f"R$ {total_geral_com:,.2f}".replace(",","X").replace(".",",").replace("X","."),
                ])

                t_res = Table(dados_res, colWidths=[6*cm, 3*cm, 4*cm, 3*cm])
                t_res.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#4a4a8a')),
                    ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                    ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0,0), (-1,-1), 10),
                    ('ALIGN', (1,0), (-1,-1), 'CENTER'),
                    ('ROWBACKGROUNDS', (0,1), (-1,-2), [colors.white, colors.HexColor('#f0f0f0')]),
                    ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#2d2d6b')),
                    ('TEXTCOLOR', (0,-1), (-1,-1), colors.white),
                    ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                    ('TOPPADDING', (0,0), (-1,-1), 6),
                ]))
                elementos.append(t_res)
                elementos.append(Spacer(1, 0.6*cm))

                # Detalhamento por colaborador
                for colab in resumo['colaborador'].tolist():
                    elementos.append(Paragraph(f"Detalhamento — {colab}", bold_style))
                    df_det = df_com[df_com['colaborador'] == colab]
                    dados_det = [["Data", "Cliente", "Serviço", "%", "Valor", "Comissão"]]
                    for _, srv in df_det.iterrows():
                        dados_det.append([
                            str(srv['data_venda']),
                            str(srv['cliente']),
                            str(srv['servico']),
                            f"{float(srv['comissao_percentual'])}%",
                            f"R$ {float(srv['valor_total']):,.2f}".replace(",","X").replace(".",",").replace("X","."),
                            f"R$ {float(srv['valor_comissao']):,.2f}".replace(",","X").replace(".",",").replace("X","."),
                        ])
                    t_det = Table(dados_det, colWidths=[2.5*cm, 4*cm, 3.5*cm, 1.5*cm, 2.5*cm, 2.5*cm])
                    t_det.setStyle(TableStyle([
                        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#6a6a9a')),
                        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
                        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0,0), (-1,-1), 8),
                        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f5f5ff')]),
                        ('GRID', (0,0), (-1,-1), 0.3, colors.grey),
                        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
                        ('TOPPADDING', (0,0), (-1,-1), 4),
                    ]))
                    elementos.append(t_det)
                    elementos.append(Spacer(1, 0.4*cm))

                doc.build(elementos)
                buffer.seek(0)

                st.download_button(
                    label="⬇️ Baixar PDF do Relatório de Comissões",
                    data=buffer,
                    file_name=f"comissoes_{d_ini_com.strftime('%d-%m-%Y')}_a_{d_fim_com.strftime('%d-%m-%Y')}.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
                
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
                    
                    # Mensagem editável antes do envio
                    key_msg = f"msg_{tipo_contato}_{row['codigo_venda']}"
                    msg_editada = st.text_area(
                        "✏️ Editar mensagem antes de enviar:",
                        value=mensagem_padrao,
                        height=100,
                        key=key_msg,
                        label_visibility="collapsed"
                    )
                    
                    link_wpp = f"https://wa.me/{tel_limpo}?text={urllib.parse.quote(msg_editada)}"
                    
                    # Layout Lado a Lado (Link e Ação de Conclusão)
                    col_wpp, col_done = st.columns(2)
                    
                    with col_wpp:
                        st.link_button(f"💬 Abrir WhatsApp de {row['cliente'].split()[0]}", link_wpp, use_container_width=True)
                    
                    with col_done:
                        if st.button(f"✅ Marcar como Enviado", key=f"check_{tipo_contato}_{row['codigo_venda']}", use_container_width=True):
                            executar_comando("""
                                INSERT INTO crm_contatos (venda_codigo, tipo_contato, empresa_id) 
                                VALUES (%s, %s, %s)
                            """, (int(row['codigo_venda']), tipo_contato, emp_id))
                            st.success("Registrado!")
                            time_module.sleep(0.4)
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

# ==========================================
# PAINEL FINAL DE TELEMETRIA DE PERFORMANCE
# Mantido no final do script para capturar o tempo do rerun completo.
# ==========================================
exibir_telemetria_performance()
