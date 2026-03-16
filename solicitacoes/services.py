from django.db import connections

def buscar_cliente_protheus_unificado(termo_busca, cod_vendedor_protheus):
    if not termo_busca or len(termo_busca) < 3:
        return []

    termo_busca = termo_busca.upper().strip()
    
    config_busca = {
        'protheus_ciec': ['SA1010', 'SA1020'],
        'protheus_wrp': ['SA1010']
    }

    query_template = """
        SELECT 
            SA1.A1_COD, SA1.A1_LOJA, SA1.A1_NOME, SA1.A1_NREDUZ, SA1.A1_CGC, 
            ACY.ACY_DESCRI AS GRUPO_DESCRI
        FROM {tabela} AS SA1
        LEFT JOIN ACY{empresa} AS ACY ON 
            RTRIM(ACY.ACY_GRPVEN) = RTRIM(SA1.A1_GRPVEN) AND 
            ACY.D_E_L_E_T_ <> '*'
        WHERE SA1.D_E_L_E_T_ <> '*'
        AND SA1.A1_MSBLQL <> '1'
        AND (SA1.A1_NOME LIKE %s OR SA1.A1_CGC LIKE %s OR SA1.A1_NREDUZ LIKE %s)
    """
    
    params = [
        f'%{termo_busca}%', 
        f'%{termo_busca}%',
        f'%{termo_busca}%'
    ]
    
    clientes_dict = {}

    for db, tabelas in config_busca.items():
        if db not in connections:
            continue
            
        for tabela in tabelas:
            empresa_sufixo = tabela[-3:]
            
            try:
                query = query_template.format(tabela=tabela, empresa=empresa_sufixo)
                
                with connections[db].cursor() as cursor:
                    cursor.execute(query, params)
                    desc = cursor.description
                    column_names = [col[0] for col in desc]
                    
                    for row in cursor.fetchall():
                        row_dict = dict(zip(column_names, row))
                        
                        cnpj_limpo = row_dict['A1_CGC'].strip()
                        cod_limpo = row_dict['A1_COD'].strip()
                        loja_limpa = row_dict['A1_LOJA'].strip()
                        
                        chave_unica = f"{cnpj_limpo}_{cod_limpo}_{loja_limpa}"
                        
                        if chave_unica not in clientes_dict:
                            clientes_dict[chave_unica] = {
                                'nome': row_dict['A1_NOME'].strip(),
                                'fantasia': row_dict['A1_NREDUZ'].strip() if row_dict['A1_NREDUZ'] else row_dict['A1_NOME'].strip(),
                                'codigo': cod_limpo,
                                'loja': loja_limpa,
                                'cnpj': cnpj_limpo,
                                'grupo': row_dict['GRUPO_DESCRI'].strip() if row_dict['GRUPO_DESCRI'] else "GERAL",
                            }
            except Exception as e:
                print(f"ERRO SQL [{db} - {tabela}]: {e}")
                continue

    return list(clientes_dict.values())