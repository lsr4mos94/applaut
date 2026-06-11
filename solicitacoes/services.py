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
    
    params = [f'%{termo_busca}%', f'%{termo_busca}%', f'%{termo_busca}%']
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
                    
                    # BLINDAGEM DA COLUNA: Garante que o nome da coluna nunca seja None
                    column_names = [str(col[0]).strip() if col[0] else f"coluna_{i}" for i, col in enumerate(desc)]
                    
                    for row in cursor.fetchall():
                        row_dict = dict(zip(column_names, row))
                        
                        # TRATAMENTO SEGURO DE CAMPOS NULOS (Fallback para strings vazias)
                        cnpj_raw = row_dict.get('A1_CGC')
                        cod_raw = row_dict.get('A1_COD')
                        loja_raw = row_dict.get('A1_LOJA')
                        nome_raw = row_dict.get('A1_NOME')
                        fantasia_raw = row_dict.get('A1_NREDUZ')
                        grupo_raw = row_dict.get('GRUPO_DESCRI')

                        cnpj_limpo = str(cnpj_raw).strip() if cnpj_raw is not None else ""
                        cod_limpo = str(cod_raw).strip() if cod_raw is not None else ""
                        loja_limpa = str(loja_raw).strip() if loja_raw is not None else ""
                        nome_limpo = str(nome_raw).strip() if nome_raw is not None else "SEM RAZAO SOCIAL"
                        fantasia_limpa = str(fantasia_raw).strip() if fantasia_raw is not None else nome_limpo
                        grupo_limpo = str(grupo_raw).strip() if grupo_raw is not None else "GERAL"
                        
                        chave_unica = f"{cnpj_limpo}_{cod_limpo}_{loja_limpa}"
                        
                        if chave_unica not in clientes_dict:
                            clientes_dict[chave_unica] = {
                                'nome': nome_limpo,
                                'fantasia': fantasia_limpa,
                                'codigo': cod_limpo,
                                'loja': loja_limpa,
                                'cnpj': cnpj_limpo,
                                'grupo': grupo_limpo,
                            }
            except Exception as e:
                print(f"ERRO SQL [{db} - {tabela}]: {e}")
                continue

    return list(clientes_dict.values())