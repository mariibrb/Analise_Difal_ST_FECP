import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import re
import io
import zipfile

st.set_page_config(page_title="Auditoria DIFAL ST FECP - Sentinela", layout="wide")

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

def processar_xml(content, cnpj_auditado, chaves_processadas):
    try:
        xml_str = re.sub(r'\sxmlns(:\w+)?="[^"]+"', '', content.decode('utf-8', errors='ignore'))
        root = ET.fromstring(xml_str)
        
        # --- TRAVA DE DUPLICIDADE ---
        infNFe = root.find('.//infNFe')
        chave = infNFe.attrib.get('Id', '')[3:] if infNFe is not None else ""
        if not chave or chave in chaves_processadas:
            return []
        chaves_processadas.add(chave)
        
        emit = root.find('.//emit')
        dest = root.find('.//dest')
        ide = root.find('.//ide')
        
        cnpj_emit = re.sub(r'\D', '', buscar_tag_recursiva('CNPJ', emit) or "")
        cnpj_dest = re.sub(r'\D', '', buscar_tag_recursiva('CNPJ', dest) or "")
        cnpj_alvo = re.sub(r'\D', '', cnpj_auditado)
        tp_nf = buscar_tag_recursiva('tpNF', ide)

        # --- LÓGICA DE FLUXO (SAÍDA / ENTRADA / DEVOLUÇÃO) ---
        if cnpj_emit == cnpj_alvo:
            tipo = "SAIDA" if tp_nf == "1" else "ENTRADA"
        elif cnpj_dest == cnpj_alvo:
            tipo = "ENTRADA"
        else:
            return []

        iest_doc = buscar_tag_recursiva('IEST', emit) if tipo == "SAIDA" else buscar_tag_recursiva('IEST', dest)
        # UF que sofre o impacto do imposto
        uf_fiscal = buscar_tag_recursiva('UF', dest) if tipo == "SAIDA" else (buscar_tag_recursiva('UF', dest) if buscar_tag_recursiva('UF', emit) == 'SP' else buscar_tag_recursiva('UF', emit))
        
        detalhes = []
        for det in root.findall('.//det'):
            icms = det.find('.//ICMS')
            imp = det.find('.//imposto')
            prod = det.find('prod')
            
            detalhes.append({
                "CHAVE": chave,
                "NUM_NF": buscar_tag_recursiva('nNF', ide),
                "TIPO": tipo,
                "UF_FISCAL": uf_fiscal,
                "IEST_DOC": str(iest_doc).strip(),
                "CFOP": buscar_tag_recursiva('CFOP', prod),
                "VPROD": safe_float(buscar_tag_recursiva('vProd', prod)),
                "ST": safe_float(buscar_tag_recursiva('vICMSST', icms)) + safe_float(buscar_tag_recursiva('vFCPST', icms)),
                "DIFAL": safe_float(buscar_tag_recursiva('vICMSUFDest', imp)) + safe_float(buscar_tag_recursiva('vFCPUFDest', imp)),
                "FCP": safe_float(buscar_tag_recursiva('vFCPUFDest', imp)),
                "FCPST": safe_float(buscar_tag_recursiva('vFCPST', icms))
            })
        return detalhes
    except:
        return []

# --- INTERFACE ---
st.title("🛡️ Sentinela: Auditoria Dinâmica e Rastreável")
cnpj_empresa = st.sidebar.text_input("CNPJ da Empresa Auditada (apenas números)")
uploaded_files = st.file_uploader("Suba seus XMLs ou ZIP", accept_multiple_files=True)

if uploaded_files and cnpj_empresa:
    dados_totais = []
    chaves_unicas = set()
    
    for f in uploaded_files:
        if f.name.endswith('.xml'):
            dados_totais.extend(processar_xml(f.read(), cnpj_empresa, chaves_unicas))
        elif f.name.endswith('.zip'):
            with zipfile.ZipFile(f) as z:
                for n in z.namelist():
                    if n.lower().endswith('.xml'):
                        dados_totais.extend(processar_xml(z.open(n).read(), cnpj_empresa, chaves_unicas))
    
    if dados_totais:
        df_listagem = pd.DataFrame(dados_totais)
        st.success(f"✅ {len(chaves_unicas)} XMLs únicos processados com sucesso!")

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            # 1. ESCREVE ABA DE DETALHAMENTO (A BASE DE TUDO)
            df_listagem.to_excel(writer, sheet_name='LISTAGEM_XML', index=False)
            ws_l = writer.sheets['LISTAGEM_XML']
            ws_l.set_column('A:A', 50) # Coluna da chave larga
            
            # 2. CONSTRÓI ABA DE RESUMO DINÂMICO
            workbook = writer.book
            ws = workbook.add_worksheet('DIFAL_ST_FECP')
            
            # FORMATOS
            fmt_tit = workbook.add_format({'bold':True, 'bg_color':'#FCD5B4', 'border':1, 'align':'center'})
            fmt_head = workbook.add_format({'bold':True, 'bg_color':'#D7E4BC', 'border':1, 'align':'center'})
            fmt_num = workbook.add_format({'num_format':'#,##0.00', 'border':1})
            fmt_total = workbook.add_format({'bold':True, 'bg_color':'#F2F2F2', 'border':1, 'num_format':'#,##0.00'})
            fmt_uf = workbook.add_format({'border':1, 'align':'center'})
            fmt_orange = workbook.add_format({'bg_color': '#FFDAB9', 'border': 1, 'num_format': '#,##0.00'})

            ws.merge_range('A1:F1', '1. SAÍDAS', fmt_tit)
            ws.merge_range('H1:M1', '2. ENTRADAS', fmt_tit)
            ws.merge_range('O1:T1', '3. SALDO', fmt_tit)

            heads = ['UF', 'IEST', 'ST TOTAL', 'DIFAL TOTAL', 'FCP TOTAL', 'FCPST TOTAL']
            for i, h in enumerate(heads):
                ws.write(1, i, h, fmt_head)
                ws.write(1, i + 7, h, fmt_head)
                ws.write(1, i + 14, h, fmt_head)

            # MAPA DE COLUNAS DA ABA 'LISTAGEM_XML':
            # A=CHAVE, B=NUM_NF, C=TIPO, D=UF_FISCAL, E=IEST_DOC, F=CFOP, G=VPROD, H=ST, I=DIFAL, J=FCP, K=FCPST
            for r, uf in enumerate(UFS_BRASIL):
                row = r + 2 # Linha 3 do Excel
                
                # UF e Busca da IEST
                ws.write(row, 0, uf, fmt_uf)
                # Procura a IEST na coluna E da listagem onde a UF (col D) bate
                ws.write_formula(row, 1, f'=IFERROR(INDEX(LISTAGEM_XML!E:E, MATCH("{uf}", LISTAGEM_XML!D:D, 0)), "")', fmt_uf)

                # SAÍDAS, ENTRADAS E SALDO COM FÓRMULAS
                for i, col_let in enumerate(['H', 'I', 'J', 'K']): # Colunas de valores na listagem
                    # Saída: Soma se UF=uf e TIPO=SAIDA
                    ws.write_formula(row, i+2, f'=SUMIFS(LISTAGEM_XML!{col_let}:{col_let}, LISTAGEM_XML!D:D, "{uf}", LISTAGEM_XML!C:C, "SAIDA")', fmt_num)
                    # Entrada: Soma se UF=uf e TIPO=ENTRADA
                    ws.write_formula(row, i+9, f'=SUMIFS(LISTAGEM_XML!{col_let}:{col_let}, LISTAGEM_XML!D:D, "{uf}", LISTAGEM_XML!C:C, "ENTRADA")', fmt_num)
                    
                    # Saldo: (Saída - Entrada) se tiver IEST (Coluna B do resumo), senão apenas Saída
                    col_s = chr(65 + i + 2)
                    col_e = chr(65 + i + 9)
                    ws.write_formula(row, i+16, f'=IF(B{row+1}<>"", {col_s}{row+1}-{col_e}{row+1}, {col_s}{row+1})', fmt_num)

                ws.write(row, 14, uf, fmt_uf)
                ws.write_formula(row, 15, f'=B{row+1}', fmt_uf)

            # LINHA DE TOTAIS FINAIS (Dinâmicos)
            total_row = len(UFS_BRASIL) + 2
            ws.write(total_row, 0, "TOTAL GERAL", fmt_total)
            for c in [2,3,4,5, 9,10,11,12, 16,17,18,19]:
                col_let = chr(65 + c) if c < 26 else f"A{chr(65 + c - 26)}"
                ws.write_formula(total_row, c, f'=SUM({col_let}3:{col_let}{total_row})', fmt_total)

        st.download_button("💾 BAIXAR AUDITORIA VIVA (FINAL)", output.getvalue(), "Auditoria_DIFAL_ST_FECP_Final.xlsx")
