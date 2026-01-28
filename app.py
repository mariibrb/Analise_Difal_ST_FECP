import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
import re
import io
import zipfile

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Apuração DIFAL/ST/FCP", layout="wide")

UFS_BRASIL = ['AC', 'AL', 'AM', 'AP', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 'MG', 'MS', 'MT', 'PA', 'PB', 'PE', 'PI', 'PR', 'RJ', 'RN', 'RO', 'RR', 'RS', 'SC', 'SE', 'SP', 'TO']

# --- MOTOR DE LEITURA (EXTRAÇÃO) ---
def safe_float(v):
    if not v: return 0.0
    try:
        return float(str(v).replace(',', '.'))
    except:
        return 0.0

def buscar_tag(tag, no):
    for elemento in no.iter():
        if elemento.tag.split('}')[-1] == tag:
            return elemento.text
    return ""

def processar_xml(content, cnpj_auditado):
    try:
        xml_str = re.sub(r'\sxmlns(:\w+)?="[^"]+"', '', content.decode('utf-8', errors='ignore'))
        root = ET.fromstring(xml_str)
        
        # Identificação básica
        emit = root.find('.//emit')
        dest = root.find('.//dest')
        ide = root.find('.//ide')
        cnpj_emit = re.sub(r'\D', '', buscar_tag('CNPJ', emit) or "")
        cnpj_alvo = re.sub(r'\D', '', cnpj_auditado)
        
        tipo_operacao = "SAIDA" if cnpj_emit == cnpj_alvo else "ENTRADA"
        
        dados = []
        for det in root.findall('.//det'):
            prod = det.find('prod')
            icms = det.find('.//ICMS')
            imp = det.find('.//imposto')
            
            # Captura de valores conforme regra de consolidação
            v_st = safe_float(buscar_tag('vICMSST', icms))
            v_fcp_st = safe_float(buscar_tag('vFCPST', icms))
            v_difal = safe_float(buscar_tag('vICMSUFDest', imp))
            v_fcp_dest = safe_float(buscar_tag('vFCPUFDest', imp))

            linha = {
                "TIPO": tipo_operacao,
                "UF_EMIT": buscar_tag('UF', emit),
                "UF_DEST": buscar_tag('UF', dest),
                "CFOP": buscar_tag('CFOP', prod),
                "VAL-ICMS-ST": v_st + v_fcp_st, # CONSOLIDADO
                "VAL-DIFAL": v_difal + v_fcp_dest, # CONSOLIDADO
                "VAL-FCP-DEST": v_fcp_dest,
                "VAL-FCP-ST": v_fcp_st,
                "IE_SUBST": str(buscar_tag('IEST', icms) or "").strip()
            }
            dados.append(linha)
        return dados
    except:
        return []

# --- LÓGICA DE APURAÇÃO ---
def gerar_apuracao(df, writer):
    df_s = df[df['TIPO'] == "SAIDA"].copy()
    df_e = df[df['TIPO'] == "ENTRADA"].copy()

    def agrupar(df_temp, tipo):
        col_uf = 'UF_DEST' if tipo == 'saida' else 'UF_AGRUPAR'
        if tipo == 'entrada':
            df_temp['UF_AGRUPAR'] = df_temp.apply(lambda x: x['UF_DEST'] if x['UF_EMIT'] == 'SP' else x['UF_EMIT'], axis=1)
        
        res = df_temp.groupby(col_uf).agg({
            'VAL-ICMS-ST': 'sum', 'VAL-DIFAL': 'sum', 'VAL-FCP-DEST': 'sum', 'VAL-FCP-ST': 'sum'
        }).reset_index().rename(columns={col_uf: 'UF'})
        
        ie_map = df_temp[df_temp['IE_SUBST'] != ""].groupby(col_uf)['IE_SUBST'].first().to_dict()
        res['IE_SUBST'] = res['UF'].map(ie_map).fillna("")
        return res

    res_s = agrupar(df_s, 'saida')
    res_e = agrupar(df_e, 'entrada')

    # Unir para saldo
    final = pd.DataFrame({'UF': UFS_BRASIL})
    final = final.merge(res_s, on='UF', how='left', suffixes=('', '_S')).fillna(0)
    final = final.merge(res_e, on='UF', how='left', suffixes=('_S', '_E')).fillna(0)

    # Cálculo do Saldo Líquido
    saldos = []
    for i, row in final.iterrows():
        tem_ie = str(row['IE_SUBST_S']).strip() != ""
        # Se tem IE, subtrai. Se não tem, paga a Saída cheia.
        st_liq = (row['VAL-ICMS-ST_S'] - row['VAL-ICMS-ST_E']) if tem_ie else row['VAL-ICMS-ST_S']
        difal_liq = (row['VAL-DIFAL_S'] - row['VAL-DIFAL_E']) if tem_ie else row['VAL-DIFAL_S']
        saldos.append({'UF': row['UF'], 'IE': row['IE_SUBST_S'], 'ST_LIQ': st_liq, 'DIFAL_LIQ': difal_liq})
    
    df_saldo = pd.DataFrame(saldos)

    # Escrita no Excel
    df_saldo.to_excel(writer, sheet_name="RESUMO_FINAL", index=False)
    final.to_excel(writer, sheet_name="MEMORIA_CALCULO", index=False)

# --- INTERFACE STREAMLIT ---
st.title("🛡️ Sentinela: Validador de Apuração UF")
cnpj_empresa = st.sidebar.text_input("CNPJ da Empresa Auditada")
uploaded_files = st.file_uploader("Arraste seus XMLs ou ZIP aqui", accept_multiple_files=True)

if uploaded_files and cnpj_empresa:
    todos_dados = []
    for f in uploaded_files:
        if f.name.endswith('.xml'):
            todos_dados.extend(processar_xml(f.read(), cnpj_empresa))
        elif f.name.endswith('.zip'):
            with zipfile.ZipFile(f) as z:
                for n in z.namelist():
                    if n.endswith('.xml'):
                        todos_dados.extend(processar_xml(z.open(n).read(), cnpj_empresa))
    
    if todos_dados:
        df_total = pd.DataFrame(todos_dados)
        st.success(f"Processadas {len(df_total)} linhas de XML.")
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            gerar_apuracao(df_total, writer)
        
        st.download_button("💾 Baixar Apuração Consolidada", output.getvalue(), "Apuracao_UF.xlsx")
        st.dataframe(df_total)
