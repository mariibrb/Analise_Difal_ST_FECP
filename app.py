import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import re
import io
import zipfile

st.set_page_config(page_title="Auditoria DIFAL ST FECP", layout="wide")

UFS_BRASIL = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO']

def safe_float(v):
    if v is None: return 0.0
    try:
        return float(str(v).replace(',', '.'))
    except:
        return 0.0

def buscar_tag_recursiva(tag_alvo, no):
    if no is None: return ""
    for elemento in no.iter():
        tag_nome = elemento.tag.split('}')[-1]
        if tag_nome == tag_alvo:
            return elemento.text if elemento.text else ""
    return ""

def processar_xml(content, cnpj_auditado):
    try:
        xml_str = re.sub(r'\sxmlns(:\w+)?="[^"]+"', '', content.decode('utf-8', errors='ignore'))
        root = ET.fromstring(xml_str)
        
        emit = root.find('.//emit')
        dest = root.find('.//dest')
        ide = root.find('.//ide')
        
        cnpj_emit = re.sub(r'\D', '', buscar_tag_recursiva('CNPJ', emit) or "")
        cnpj_dest = re.sub(r'\D', '', buscar_tag_recursiva('CNPJ', dest) or "")
        cnpj_alvo = re.sub(r'\D', '', cnpj_auditado)
        tp_nf = buscar_tag_recursiva('tpNF', ide) # 0=Entrada, 1=Saída

        # --- LÓGICA DE ENTRADA/SAÍDA REFINADA ---
        if cnpj_emit == cnpj_alvo:
            # Se eu emiti, mas o tipo é 0, é uma DEVOLUÇÃO PRÓPRIA (Entrada)
            tipo = "SAIDA" if tp_nf == "1" else "ENTRADA"
        elif cnpj_dest == cnpj_alvo:
            # Se sou o destinatário, é uma ENTRADA de terceiros
            tipo = "ENTRADA"
        else:
            return [] # NF não pertence a esta empresa

        iest_documento = buscar_tag_recursiva('IEST', emit) if tipo == "SAIDA" else buscar_tag_recursiva('IEST', dest)
        
        detalhes = []
        for det in root.findall('.//det'):
            icms = det.find('.//ICMS')
            imp = det.find('.//imposto')
            prod = det.find('prod')
            
            detalhes.append({
                "TIPO": tipo,
                "UF_EMIT": buscar_tag_recursiva('UF', emit),
                "UF_DEST": buscar_tag_recursiva('UF', dest),
                "CFOP": buscar_tag_recursiva('CFOP', prod),
                "ST_TOTAL": safe_float(buscar_tag_recursiva('vICMSST', icms)) + safe_float(buscar_tag_recursiva('vFCPST', icms)),
                "DIFAL_TOTAL": safe_float(buscar_tag_recursiva('vICMSUFDest', imp)) + safe_float(buscar_tag_recursiva('vFCPUFDest', imp)),
                "FCP_TOTAL": safe_float(buscar_tag_recursiva('vFCPUFDest', imp)),
                "FCP_ST_TOTAL": safe_float(buscar_tag_recursiva('vFCPST', icms)),
                "IEST": str(iest_documento).strip()
            })
        return detalhes
    except:
        return []

# --- INTERFACE ---
st.title("🛡️ Sentinela: Gerador de Apuração DIFAL/ST/FECP")
cnpj_empresa = st.sidebar.text_input("CNPJ da Empresa Auditada (apenas números)")
uploaded_files = st.file_uploader("Suba seus XMLs ou ZIP", accept_multiple_files=True)

if uploaded_files and cnpj_empresa:
    dados = []
    for f in uploaded_files:
        if f.name.endswith('.xml'): dados.extend(processar_xml(f.read(), cnpj_empresa))
        elif f.name.endswith('.zip'):
            with zipfile.ZipFile(f) as z:
                for n in z.namelist():
                    if n.lower().endswith('.xml'): dados.extend(processar_xml(z.open(n).read(), cnpj_empresa))
    
    if dados:
        df_base = pd.DataFrame(dados)
        
        def preparar_blocos(df):
            base_uf = pd.DataFrame({'UF': UFS_BRASIL})
            cols_sum = ['ST_TOTAL', 'DIFAL_TOTAL', 'FCP_TOTAL', 'FCP_ST_TOTAL']
            
            # Saídas
            s = df[df['TIPO'] == "SAIDA"].copy()
            res_s = s.groupby('UF_DEST').agg({c:'sum' for c in cols_sum}).reset_index().rename(columns={'UF_DEST':'UF'})
            ie_s = s[s['IEST'] != ""].groupby('UF_DEST')['IEST'].first().to_dict()
            res_s['IEST'] = res_s['UF'].map(ie_s).fillna("")
            
            # Entradas (Melhorado: Agrupa pela UF de origem do imposto)
            e = df[df['TIPO'] == "ENTRADA"].copy()
            e['UF_ORIGEM'] = e.apply(lambda x: x['UF_DEST'] if x['UF_EMIT'] == 'SP' else x['UF_EMIT'], axis=1)
            res_e = e.groupby('UF_ORIGEM').agg({c:'sum' for c in cols_sum}).reset_index().rename(columns={'UF_ORIGEM':'UF'})
            
            return base_uf.merge(res_s, on='UF', how='left').fillna(0), base_uf.merge(res_e, on='UF', how='left').fillna(0)

        df_s, df_e = preparar_blocos(df_base)

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            workbook = writer.book
            ws = workbook.add_worksheet('DIFAL_ST_FECP')
            
            # FORMATOS
            fmt_header = workbook.add_format({'bold':True, 'bg_color':'#D7E4BC', 'border':1, 'align':'center'})
            fmt_title = workbook.add_format({'bold':True, 'bg_color':'#FCD5B4', 'border':1, 'align':'center'})
            fmt_num = workbook.add_format({'num_format':'#,##0.00', 'border':1})
            fmt_total = workbook.add_format({'bold':True, 'bg_color':'#F2F2F2', 'border':1, 'num_format':'#,##0.00'})
            fmt_uf = workbook.add_format({'border':1, 'align':'center'})
            fmt_orange = workbook.add_format({'bg_color': '#FFDAB9', 'border': 1, 'num_format': '#,##0.00'})

            # CABEÇALHOS
            ws.merge_range('A1:F1', '1. SAÍDAS', fmt_title)
            ws.merge_range('H1:M1', '2. ENTRADAS', fmt_title)
            ws.merge_range('O1:T1', '3. SALDO', fmt_title)

            heads = ['UF', 'IEST', 'ST TOTAL', 'DIFAL TOTAL', 'FCP TOTAL', 'FCP-ST TOTAL']
            for i, h in enumerate(heads):
                ws.write(1, i, h, fmt_header)
                ws.write(1, i + 7, h, fmt_header)
                ws.write(1, i + 14, h, fmt_header)

            # DADOS
            for r, uf in enumerate(UFS_BRASIL):
                row_idx = r + 2
                v_s = df_s[df_s['UF'] == uf].iloc[0]
                v_e = df_e[df_e['UF'] == uf].iloc[0]
                tem_ie = str(v_s['IEST']).strip() != ""
                
                f_n = fmt_orange if tem_ie else fmt_num
                f_u = fmt_orange if tem_ie else fmt_uf

                # Blocos 1 e 2
                ws.write(row_idx, 0, uf, f_u); ws.write(row_idx, 1, str(v_s['IEST']), f_u)
                ws.write(row_idx, 7, uf, fmt_uf); ws.write(row_idx, 8, "", fmt_uf)
                
                for i, col in enumerate(['ST_TOTAL', 'DIFAL_TOTAL', 'FCP_TOTAL', 'FCP_ST_TOTAL']):
                    ws.write(row_idx, i+2, v_s[col], f_n) # Saída
                    ws.write(row_idx, i+9, v_e[col], fmt_num) # Entrada
                    
                    # Bloco 3: Saldo
                    res = (v_s[col] - v_e[col]) if tem_ie else v_s[col]
                    ws.write(row_idx, i+16, res, f_n)
                
                ws.write(row_idx, 14, uf, f_u); ws.write(row_idx, 15, str(v_s['IEST']), f_u)

            # LINHA DE TOTAIS (Fim da tabela)
            total_row = len(UFS_BRASIL) + 2
            ws.write(total_row, 0, "TOTAL GERAL", fmt_total)
            for c in [2,3,4,5, 9,10,11,12, 16,17,18,19]:
                col_letter = chr(65 + c) if c < 26 else f"A{chr(65 + c - 26)}"
                ws.write(total_row, c, f'=SUM({col_letter}3:{col_letter}{total_row})', fmt_total)

        st.success("🔥 Auditoria completa e consolidada!")
        st.download_button("💾 BAIXAR EXCEL FINAL", output.getvalue(), "Auditoria_DIFAL_ST_FECP_Final.xlsx")
