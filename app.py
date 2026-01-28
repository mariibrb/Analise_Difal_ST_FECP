import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import re
import io
import zipfile

# --- CONFIGURAÇÃO INTERFACE ---
st.set_page_config(page_title="Analise Difal ST FECP", layout="wide")
st.title("📊 Apuração Consolidada: ST, DIFAL e FECP")

UFS_BRASIL = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO']

# --- MOTOR DE EXTRAÇÃO ---
def safe_float(v):
    if v is None: return 0.0
    try:
        return float(str(v).replace(',', '.'))
    except:
        return 0.0

def buscar_tag(tag, no):
    if no is None: return ""
    for elemento in no.iter():
        if elemento.tag.split('}')[-1] == tag:
            return elemento.text
    return ""

def processar_xml(content, cnpj_auditado):
    try:
        xml_str = re.sub(r'\sxmlns(:\w+)?="[^"]+"', '', content.decode('utf-8', errors='ignore'))
        root = ET.fromstring(xml_str)
        
        emit = root.find('.//emit')
        dest = root.find('.//dest')
        ide = root.find('.//ide')
        cnpj_emit = re.sub(r'\D', '', buscar_tag('CNPJ', emit) or "")
        cnpj_alvo = re.sub(r'\D', '', cnpj_auditado)
        
        # Define se é entrada ou saída para a empresa auditada
        tipo_operacao = "SAIDA" if cnpj_emit == cnpj_alvo else "ENTRADA"
        
        dados_xml = []
        for det in root.findall('.//det'):
            prod = det.find('prod')
            icms = det.find('.//ICMS')
            imp = det.find('.//imposto')
            
            # Tags de Valor Puro e FCP
            v_st = safe_float(buscar_tag('vICMSST', icms))
            v_fcp_st = safe_float(buscar_tag('vFCPST', icms))
            v_difal = safe_float(buscar_tag('vICMSUFDest', imp))
            v_fcp_dest = safe_float(buscar_tag('vFCPUFDest', imp))

            linha = {
                "TIPO": tipo_operacao,
                "UF_EMIT": buscar_tag('UF', emit),
                "UF_DEST": buscar_tag('UF', dest),
                "CFOP": buscar_tag('CFOP', prod),
                "ST_TOTAL": v_st + v_fcp_st,      # SOMA SOLICITADA
                "DIFAL_TOTAL": v_difal + v_fcp_dest, # SOMA SOLICITADA
                "IE_SUBST": str(buscar_tag('IEST', icms) or "").strip()
            }
            dados_xml.append(linha)
        return dados_xml
    except:
        return []

# --- INTERFACE DE UPLOAD ---
cnpj_input = st.sidebar.text_input("CNPJ da Empresa (apenas números)")
files = st.file_uploader("Upload de XMLs ou ZIP", accept_multiple_files=True)

if files and cnpj_input:
    lista_final = []
    for f in files:
        if f.name.endswith('.xml'):
            lista_final.extend(processar_xml(f.read(), cnpj_input))
        elif f.name.endswith('.zip'):
            with zipfile.ZipFile(f) as z:
                for n in z.namelist():
                    if n.lower().endswith('.xml'):
                        lista_final.extend(processar_xml(z.open(n).read(), cnpj_input))
    
    if lista_final:
        df = pd.DataFrame(lista_final)
        
        # --- APURAÇÃO POR UF ---
        def preparar_resumo(df_base):
            # Separa Saídas (5,6,7) e Entradas (1,2,3)
            df_base['PREFIXO'] = df_base['CFOP'].astype(str).str[0]
            s = df_base[df_base['TIPO'] == "SAIDA"].copy()
            e = df_base[df_base['TIPO'] == "ENTRADA"].copy()
            
            # Agrupa Saídas por UF Destino
            res_s = s.groupby('UF_DEST').agg({'ST_TOTAL':'sum', 'DIFAL_TOTAL':'sum'}).reset_index().rename(columns={'UF_DEST':'UF'})
            ie_map = s[s['IE_SUBST'] != ""].groupby('UF_DEST')['IE_SUBST'].first().to_dict()
            res_s['IE'] = res_s['UF'].map(ie_map).fillna("")

            # Agrupa Entradas (Lógica: se Emitente é SP, olha Destino, senão olha Emitente)
            e['UF_AGRUPAR'] = e.apply(lambda x: x['UF_DEST'] if x['UF_EMIT'] == 'SP' else x['UF_EMIT'], axis=1)
            res_e = e.groupby('UF_AGRUPAR').agg({'ST_TOTAL':'sum', 'DIFAL_TOTAL':'sum'}).reset_index().rename(columns={'UF_AGRUPAR':'UF'})

            # Merge Geral
            final = pd.DataFrame({'UF': UFS_BRASIL})
            final = final.merge(res_s, on='UF', how='left').fillna(0)
            final = final.merge(res_e, on='UF', how='left', suffixes=('_S', '_E')).fillna(0)

            # REGRA MESTRA: Saída - Entrada (Apenas se tiver IE)
            saldos = []
            for i, row in final.iterrows():
                tem_ie = str(row['IE']).strip() != ""
                st_liq = (row['ST_TOTAL_S'] - row['ST_TOTAL_E']) if tem_ie else row['ST_TOTAL_S']
                difal_liq = (row['DIFAL_TOTAL_S'] - row['DIFAL_TOTAL_E']) if tem_ie else row['DIFAL_TOTAL_S']
                saldos.append({'UF': row['UF'], 'IE_SUBST': row['IE'], 'ST_A_RECOLHER': st_liq, 'DIFAL_A_RECOLHER': difal_liq})
            
            return pd.DataFrame(saldos)

        df_apuracao = preparar_resumo(df)
        
        # Exibição
        st.subheader("📋 Resumo da Apuração por UF")
        st.dataframe(df_apuracao, use_container_width=True)

        # Download Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_apuracao.to_excel(writer, sheet_name='RESUMO_SALDO', index=False)
            df.to_excel(writer, sheet_name='DETALHAMENTO_NOTAS', index=False)
        
        st.download_button("💾 Baixar Relatório Completo", output.getvalue(), "Analise_DIFAL_ST_FECP.xlsx")
