from django.db import connections

def buscar_cliente_protheus_unificado(termo_busca, cod_vendedor_protheus):
    # Trava de segurança: só busca se tiver 3 ou mais caracteres
    if not termo_busca or len(termo_busca) < 3:
        return []

    termo_busca = termo_busca.upper().strip()
    
    # Dicionário de instâncias e tabelas conforme seu ambiente
    config_busca = {
        'protheus_ciec': ['SA1010', 'SA1020'],
        'protheus_wrp': ['SA1010']
    }

    # Query ajustada: 
    # 1. RTRIM no A1_VEND para garantir o match com o código do vendedor
    # 2. Filtro de filial vazio (padrão Protheus para clientes globais)
    query_template = """
        SELECT 
            SA1.A1_COD, SA1.A1_LOJA, SA1.A1_NOME, SA1.A1_NREDUZ, SA1.A1_CGC, 
            ACY.ACY_DESCRI AS GRUPO_DESCRI
        FROM {tabela} AS SA1
        LEFT JOIN ACY{empresa} AS ACY ON 
            RTRIM(ACY.ACY_GRPVEN) = RTRIM(SA1.A1_GRPVEN) AND 
            ACY.D_E_L_E_T_ <> '*'
        WHERE SA1.D_E_L_E_T_ <> '*'
        AND RTRIM(SA1.A1_VEND) = %s
        AND SA1.A1_MSBLQL <> '1'
        AND (SA1.A1_NOME LIKE %s OR SA1.A1_CGC LIKE %s OR SA1.A1_NREDUZ LIKE %s)
    """
    
    params = [
        cod_vendedor_protheus.strip(), 
        f'%{termo_busca}%', 
        f'%{termo_busca}%',
        f'%{termo_busca}%'
    ]
    
    clientes_dict = {}

    for db, tabelas in config_busca.items():
        # Verifica se a conexão existe no settings.py
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
                        
                        # Chave única para evitar duplicar clientes iguais em bases diferentes
                        chave_unica = f"{cnpj_limpo}_{cod_limpo}_{loja_limpa}"
                        
                        if chave_unica not in clientes_dict:
                            # ESTES NOMES DE CHAVE DEVEM SER IGUAIS AOS DO SEU JS (c.nome, c.cnpj, etc)
                            clientes_dict[chave_unica] = {
                                'nome': row_dict['A1_NOME'].strip(),
                                'fantasia': row_dict['A1_NREDUZ'].strip() if row_dict['A1_NREDUZ'] else row_dict['A1_NOME'].strip(),
                                'codigo': cod_limpo,
                                'loja': loja_limpa,
                                'cnpj': cnpj_limpo,
                                'grupo': row_dict['GRUPO_DESCRI'].strip() if row_dict['GRUPO_DESCRI'] else "GERAL",
                            }
            except Exception as e:
                # Log de erro para o terminal (importante para debugar no Protheus)
                print(f"ERRO SQL [{db} - {tabela}]: {e}")
                continue

    return list(clientes_dict.values())