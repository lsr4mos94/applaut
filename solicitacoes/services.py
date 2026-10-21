from app.protheus import consultar, linhas, linhas_como_dict, ProtheusIndisponivel  # noqa: F401


def _txt(valor, padrao=""):
    return str(valor).strip() if valor is not None else padrao


def buscar_cliente_protheus_unificado(termo_busca, cod_vendedor_protheus=None):
    """
    Clientes do Protheus (CIEC e WRP) por nome, nome fantasia ou CNPJ.
    O código do vendedor não filtra a busca: todo vendedor encontra qualquer cliente.
    Levanta ProtheusIndisponivel se nenhuma base puder ser consultada.
    """
    if not termo_busca or len(termo_busca.strip()) < 3:
        return []
    termo_busca = termo_busca.upper().strip()

    bases = {
        'protheus_ciec': ['SA1010', 'SA1020'],
        'protheus_wrp': ['SA1010'],
    }
    query = """
        SELECT 
            SA1.A1_COD, SA1.A1_LOJA, SA1.A1_NOME, SA1.A1_NREDUZ, SA1.A1_CGC, 
            SA1.A1_CEP, SA1.A1_EST, SA1.A1_MUN, SA1.A1_BAIRRO, SA1.A1_END, SA1.A1_COMPLEM,
            ACY.ACY_DESCRI AS GRUPO_DESCRI
        FROM {tabela} AS SA1
        LEFT JOIN ACY{empresa} AS ACY ON 
            RTRIM(ACY.ACY_GRPVEN) = RTRIM(SA1.A1_GRPVEN) AND 
            ACY.D_E_L_E_T_ <> '*'
        WHERE SA1.D_E_L_E_T_ <> '*'
        AND SA1.A1_MSBLQL <> '1'
        AND (SA1.A1_NOME LIKE %s OR SA1.A1_CGC LIKE %s OR SA1.A1_NREDUZ LIKE %s)
    """
    params = [f'%{termo_busca}%'] * 3

    clientes = {}
    for row in linhas_como_dict(consultar(bases, query, params)):
        nome = _txt(row.get('A1_NOME'), "SEM RAZAO SOCIAL")
        cnpj, codigo, loja = _txt(row.get('A1_CGC')), _txt(row.get('A1_COD')), _txt(row.get('A1_LOJA'))
        chave = f"{cnpj}_{codigo}_{loja}"
        if chave in clientes:
            continue
        clientes[chave] = {
            'nome': nome,
            'fantasia': _txt(row.get('A1_NREDUZ'), nome),
            'codigo': codigo,
            'loja': loja,
            'cnpj': cnpj,
            'grupo': _txt(row.get('GRUPO_DESCRI'), "GERAL"),
            'cep': _txt(row.get('A1_CEP')),
            'estado': _txt(row.get('A1_EST')),
            'cidade': _txt(row.get('A1_MUN')),
            'bairro': _txt(row.get('A1_BAIRRO')),
            'endereco': _txt(row.get('A1_END')),
            'complemento': _txt(row.get('A1_COMPLEM')),
            'numero': '',  # O Protheus padrão geralmente embute o número no A1_END
        }
    return list(clientes.values())


def buscar_produtos_protheus(termo):
    """Produtos ativos com preço na tabela 214. Levanta ProtheusIndisponivel se o Protheus estiver fora."""
    termo = (termo or '').upper().strip()
    if len(termo) < 3:
        return []
    bases = {
        'protheus_ciec': ['SB1010', 'SB1020'],
        'protheus_wrp': ['SB1010'],
    }
    query = """
        SELECT 
            SB1.B1_COD, 
            SB1.B1_DESC, 
            ISNULL(SBM.BM_DESC, 'SEM GRUPO') as BM_DESC, 
            DA1.DA1_PRCVEN
        FROM {tabela} AS SB1
        LEFT JOIN SBM{empresa} AS SBM ON 
            RTRIM(SBM.BM_GRUPO) = RTRIM(SB1.B1_GRUPO) AND SBM.D_E_L_E_T_ <> '*'
        INNER JOIN DA1{empresa} AS DA1 ON 
            DA1.DA1_CODTAB = '214' 
            AND RTRIM(DA1.DA1_CODPRO) = RTRIM(SB1.B1_COD) 
            AND DA1.D_E_L_E_T_ <> '*'
        WHERE SB1.D_E_L_E_T_ <> '*' 
        AND SB1.B1_MSBLQL <> '1' 
        AND (SB1.B1_DESC LIKE %s OR SB1.B1_COD LIKE %s)
    """
    produtos = {}
    for row in linhas(consultar(bases, query, [f'%{termo}%', f'%{termo}%'])):
        codigo = _txt(row[0])
        if codigo not in produtos:
            produtos[codigo] = {
                'codigo': codigo,
                'descricao': _txt(row[1]),
                'grupo_familia': _txt(row[2]),
                'preco': float(row[3]) if row[3] is not None else 0.0,
            }
    return list(produtos.values())


def buscar_precos_protheus(codigos):
    """
    Preço de venda (tabela 214) de cada código de produto, consultado no Protheus.
    Retorna {codigo: preco}. Códigos sem preço ficam fora do dicionário.
    Levanta ProtheusIndisponivel se nenhuma base do Protheus puder ser consultada.
    """
    codigos = sorted({str(c).strip() for c in codigos if c})
    if not codigos:
        return {}
    bases = {
        'protheus_ciec': ['DA1010', 'DA1020'],
        'protheus_wrp': ['DA1010'],
    }
    marcadores = ', '.join(['%s'] * len(codigos))
    query = (
        "SELECT RTRIM(DA1_CODPRO), DA1_PRCVEN FROM {tabela} "
        "WHERE D_E_L_E_T_ <> '*' AND DA1_CODTAB = '214' "
        f"AND RTRIM(DA1_CODPRO) IN ({marcadores})"
    )
    precos = {}
    for cod, preco in linhas(consultar(bases, query, codigos)):
        cod = _txt(cod)
        if cod not in precos and preco is not None:
            precos[cod] = preco
    return precos
