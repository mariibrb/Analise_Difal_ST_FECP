import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import re
import io
import zipfile
import random

# --- CONFIGURAÇÃO E ESTILO "RIHANNA / GARIMPEIRO" ---
st.set_page_config(page_title="DIAMOND TAX | Premium Audit", layout="wide", page_icon="💎")

def aplicar_estilo_diamond():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;800&display=swap');

        /* 1. FUNDAÇÃO GRADIENTE PINK/SOFT */
        header, [data-testid="stHeader"] { display: none !important; }
        .stApp { 
            background: radial-gradient(circle at top right, #FFDEEF 0%, #F8F9FA 100%) !important; 
        }

        /* 2. TÍTULOS EM ROSA SENTINELA */
        h1, h2, h3 {
            font-family: 'Montserrat', sans-serif;
            font-weight: 800;
            color: #FF69B4 !important;
            text-align: center;
            text-transform: uppercase;
            letter-spacing: 2px;
        }

        /* 3. BOTÕES BRANCOS COM HOVER PINK */
        div.stButton > button {
            color: #6C757D !important; 
            background-color: #FFFFFF !important; 
            border: 1px solid #DEE2E6 !important;
            border-radius: 15px !important;
            font-family: 'Montserrat', sans-serif !important;
            font-weight: 800 !important;
            height: 50px !important;
            text-transform: uppercase;
            transition: all 0.4s ease !important;
            width: 100% !important;
            box-shadow: 0 4px 6px rgba(0,0,0,0.05) !important;
        }

        div.stButton > button:hover {
            transform: translateY(-3px) !important;
            box-shadow: 0 10px 20px rgba(255,105,180,0.2) !important;
            border-color: #FF69B4 !important;
            color: #FF69B4 !important;
        }

        /* 4. DOWNLOAD BUTTON (DESTAQUE PINK) */
        div.stDownloadButton > button {
            background-color: #FF69B4 !important; 
            color: white !important; 
            border: 2px solid #FFFFFF !important;
            font-weight: 700 !important;
            border-radius: 15px !important;
            box-shadow: 0 5px 15px rgba(255, 105, 180, 0.3) !important;
            text-transform: uppercase;
        }

        /* 5. SIDEBAR E INPUTS */
        [data-testid="stSidebar"] {
            background-color: #FFFFFF !important;
            border-right: 1px solid #FFDEEF !important;
        }
        
        .stTextInput>div>div>input {
            border-radius: 10px !important;
            border: 1px solid #FFDEEF !important;
        }

        /* 6. TABELAS E MÉTRICAS */
        [data-testid="stMetric"] {
            background: white !important;
            border-radius: 20px !important;
            border: 1px solid #FFDEEF !important;
            padding: 15px !important;
            box-shadow: 0 4px 10px rgba(0,0,0,0.03) !important;
        }
        </style>
    """, unsafe_allow_html=True)

aplicar_estilo_diamond()

# --- REGRAS FISCAIS (MANTENDO O CÉREBRO DO PROJETO) ---
UFS_BRASIL = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO']
CFOP_DEVOLUCAO = ['1201', '1202', '1203', '1204', '1410', '1411', '1660', '1661', '1662', '2201', '2202', '2203', '2204', '2410', '2411', '2660', '2661', '2662', '3201', '3202', '3411']

def safe_float(v):
    if v is None: return 0.0
    try: return float(str(v).replace(',', '.'))
    except: return 0.0

def buscar_tag_recursiva(tag_alvo, no):
    if no is None: return ""
    for elemento in no.iter():
        if elemento.tag.split('}')[-1] == tag_alvo:
            return elemento.text if elemento.text else ""
    return ""

def processar_xml(content, cnpj_auditado, chaves_processadas, chaves_canceladas):
    try:
        xml_str = re.sub(r'\sxmlns(:\w+)?="[^"]+"', '', content.decode('utf-8', errors='ignore'))
        root = ET.fromstring(xml_str)
        infNFe = root.find('.//infNFe')
        chave = infNFe.attrib.get('Id', '')[3:] if infNFe is not None else ""
        if not chave or chave in chaves_processadas or chave in chaves_canceladas: return []
        chaves_processadas.add(chave)
        emit, dest, ide = root.find('.//emit'), root.find('.//dest'), root.find('.//ide')
        cnpj_emit = re.sub(r'\D', '', buscar_tag_recursiva('CNPJ', emit) or "")
        cnpj_alvo = re.sub(r'\D', '', cnpj_auditado)
        tp_nf = buscar_tag_recursiva('tpNF', ide)
        tipo = "SAIDA" if (cnpj_emit == cnpj_alvo and tp_nf == "1") else "ENTRADA"
        iest_doc = buscar_tag_recursiva('IEST', emit) if tipo == "SAIDA" else buscar_tag_recursiva('IEST', dest)
        uf_fiscal = buscar_tag_recursiva('UF', dest) if tipo == "SAIDA" else (buscar_tag_recursiva('UF', dest) if buscar_tag_recursiva('UF', emit) == 'SP' else buscar_tag_recursiva('UF', emit))
        detalhes = []
        for det in root.findall('.//det'):
            icms, imp, prod = det.find('.//ICMS'), det.find('.//imposto'), det.find('prod')
            cfop = buscar_tag_recursiva('CFOP', prod)
            if tipo == "ENTRADA" and cfop not in CFOP_DEVOLUCAO: continue
            detalhes.append({
                "CHAVE": chave, "NUM_NF": buscar_tag_recursiva('nNF', ide), "TIPO": tipo, "UF_FISCAL": uf_fiscal, "IEST_DOC": str(iest_doc).strip(), "CFOP": cfop,
                "ST": safe_float(buscar_tag_recursiva('vICMSST', icms)) + safe_float(buscar_tag_recursiva('vFCPST', icms)),
                "DIFAL": safe_float(buscar_tag_recursiva('vICMSUFDest', imp)) + safe_float(buscar_tag_recursiva('vFCPUFDest', imp)),
                "FCP": safe_float(buscar_tag_recursiva('vFCPUFDest', imp)), "FCPST": safe_float(buscar_tag_recursiva('vFCPST', icms))
            })
        return detalhes
    except: return []

# --- INTERFACE ---
st.markdown("<h1>💎 DIAMOND TAX</h1>", unsafe_allow_html=True)
st.markdown("<h3 style='font-size: 14px; margin-top: -20px; color: #6C757D !important;'>Apuração de DIFAL, ST e FECP - Versão Luxo</h3>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### 🔍 CONFIGURAÇÃO")
    file_status = st.file_uploader("LISTA DE STATUS (SIEG)", type=['csv', 'xlsx'])
    cnpj_input = st.text_input("CNPJ DO CLIENTE")
    cnpj_limpo = "".join(filter(str.isdigit, cnpj_input))
    st.divider()
    if st.button("🗑️ RESETAR SISTEMA"):
        st.session_state.clear()
        st.rerun()

uploaded_files = st.file_uploader("ARRASTE SEUS XMLS OU ZIP AQUI:", accept_multiple_files=True)

chaves_canceladas = set()
if file_status:
    try:
        skip = 0 if file_status.name.endswith('.csv') else 2
        df_status = pd.read_csv(file_status, skiprows=skip, sep=',', encoding='utf-8') if file_status.name.endswith('.csv') else pd.read_excel(file_status, skiprows=2)
        col_ch, col_sit = df_status.columns[10], df_status.columns[14]
        mask = df_status[col_sit].astype(str).str.upper().str.contains("CANCEL", na=False)
        chaves_canceladas = set(df_status[mask][col_ch].astype(str).str.replace('NFe', '').str.strip())
        if chaves_canceladas: st.sidebar.warning(f"🚫 {len(chaves_canceladas)} Canceladas filtradas.")
    except: pass

if uploaded_files and len(cnpj_limpo) == 14:
    if st.button("🚀 INICIAR APURAÇÃO DIAMANTE"):
        dados_totais, chaves_unicas = [], set()
        with st.status("⛏️ Garimpando impostos...", expanded=True):
            for f in uploaded_files:
                f_content = f.read()
                if f.name.endswith('.xml'):
                    dados_totais.extend(processar_xml(f_content, cnpj_limpo, chaves_unicas, chaves_canceladas))
                elif f.name.endswith('.zip'):
                    with zipfile.ZipFile(io.BytesIO(f_content)) as z:
                        for n in z.namelist():
                            if n.lower().endswith('.xml'):
                                dados_totais.extend(processar_xml(z.read(n), cnpj_limpo, chaves_unicas, chaves_canceladas))
        
        if dados_totais:
            df_base = pd.DataFrame(dados_totais)
            st.success("💎 APURAÇÃO CONCLUÍDA!")
            
            c1, c2 = st.columns(2)
            c1.metric("📦 NOTAS PROCESSADAS", len(chaves_unicas))
            c2.metric("❌ NOTAS CANCELADAS", len(chaves_canceladas))

            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df_base.to_excel(writer, sheet_name='LISTAGEM_XML', index=False)
                workbook, ws = writer.book, writer.book.add_worksheet('DIFAL_ST_FECP')
                
                # FORMATOS EXCEL (Adaptados para o estilo Garimpeiro)
                f_tit = workbook.add_format({'bold':True, 'bg_color':'#FF69B4', 'font_color':'#FFFFFF', 'border':1, 'align':'center'})
                f_head = workbook.add_format({'bold':True, 'bg_color':'#F8F9FA', 'font_color':'#6C757D', 'border':1, 'align':'center'})
                f_num = workbook.add_format({'num_format':'#,##0.00', 'border':1})
                f_orange = workbook.add_format({'bg_color': '#FFDAB9', 'border': 1, 'align':'center'})

                ws.merge_range('A1:F1', '1. SAÍDAS', f_tit)
                ws.merge_range('H1:M1', '2. ENTRADAS (DEV)', f_tit)
                ws.merge_range('O1:T1', '3. SALDO', f_tit)

                heads = ['UF', 'IEST', 'ST TOTAL', 'DIFAL TOTAL', 'FCP TOTAL', 'FCPST TOTAL']
                for i, h in enumerate(heads):
                    ws.write(1, i, h, f_head); ws.write(1, i + 7, h, f_head); ws.write(1, i + 14, h, f_head)

                for r, uf in enumerate(UFS_BRASIL):
                    row = r + 2 
                    ws.write(row, 0, uf); ws.write_formula(row, 1, f'=IFERROR(INDEX(LISTAGEM_XML!E:E, MATCH("{uf}", LISTAGEM_XML!D:D, 0)) & "", "")')
                    for i, col_let in enumerate(['H', 'I', 'J', 'K']): 
                        ws.write_formula(row, i+2, f'=SUMIFS(LISTAGEM_XML!{col_let}:{col_let}, LISTAGEM_XML!D:D, "{uf}", LISTAGEM_XML!C:C, "SAIDA")', f_num)
                        ws.write_formula(row, i+9, f'=SUMIFS(LISTAGEM_XML!{col_let}:{col_let}, LISTAGEM_XML!D:D, "{uf}", LISTAGEM_XML!C:C, "ENTRADA")', f_num)
                        col_s, col_e = chr(65 + i + 2), chr(65 + i + 9)
                        if i == 1: # REGRA RJ NO SALDO DIFAL
                            f_sal = f'=IF(B{row+1}<>"", IF(A{row+1}="RJ", ({col_s}{row+1}-{col_e}{row+1})-(E{row+1}-L{row+1}), {col_s}{row+1}-{col_e}{row+1}), IF(A{row+1}="RJ", {col_s}{row+1}-E{row+1}, {col_s}{row+1}))'
                        else:
                            f_sal = f'=IF(B{row+1}<>"", {col_s}{row+1}-{col_e}{row+1}, {col_s}{row+1})'
                        ws.write_formula(row, i+16, f_sal, f_num)
                    ws.write(row, 14, uf); ws.write_formula(row, 15, f'=B{row+1}')

                ws.conditional_format(f'A3:F29', {'type':'formula', 'criteria':'=LEN($B3)>0', 'format':f_orange})
                ws.conditional_format(f'O3:T29', {'type':'formula', 'criteria':'=LEN($P3)>0', 'format':f_orange})
                
                # TOTAIS
                total_row = 29
                for c in [2,3,4,5, 9,10,11,12, 16,17,18,19]:
                    col_let = chr(65 + c) if c < 26 else f"A{chr(65 + c - 26)}"
                    ws.write_formula(total_row, c, f'=SUM({col_let}3:{col_let}{total_row})', f_num)

            st.markdown("---")
            st.download_button("📥 BAIXAR RELATÓRIO DIAMANTE (EXCEL)", output.getvalue(), "Diamond_Tax_Audit.xlsx", use_container_width=True)
