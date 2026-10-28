"""
Consultas ao Protheus usadas no Agendamento e na tela de Chopp.

Tudo do chopp é faturado no CIEC, empresa 01, filial 0101:
- cliente: SA1010 ativo (A1_MSBLQL <> '1') da filial 0101, com a condição de pagamento (SE4, mesma filial)
  e a tabela de preço (A1_TABELA);
- produtos: SB1010 da filial 0101, não bloqueados, dos grupos de chopp;
- preço: DA1010 da filial 0101, na tabela do cliente; produto repetido -> vale o menor R_E_C_N_O_.
- inadimplência: títulos em aberto e vencidos (SE1) em todas as empresas (CIEC, ISLA e WRP),
  por código + loja do cliente, sem adiantamentos/créditos (RA, NCC) e abatimentos (tipos terminados em '-').

Todas as funções levantam ProtheusIndisponivel se o Protheus estiver fora do ar.
"""
from datetime import datetime
from decimal import Decimal

from app.protheus import consultar, linhas, linhas_como_dict

FILIAL_CHOPP = '0101'
GRUPOS_PRODUTO_CHOPP = ['0019', '0020', '0027', '0028', '0033']

_BASE_CLIENTES = {'protheus_ciec': ['SA1010']}
_BASE_PRODUTOS = {'protheus_ciec': ['SB1010']}
_BASE_PRECOS = {'protheus_ciec': ['DA1010']}
_BASE_TITULOS = {'protheus_ciec': ['SE1010', 'SE1020'], 'protheus_wrp': ['SE1010']}


def _txt(valor):
    return str(valor or '').strip()


_SQL_CLIENTE = (
    "SELECT {topo} SA1.A1_COD, SA1.A1_LOJA, SA1.A1_NOME, SA1.A1_NREDUZ, SA1.A1_CGC, "
    "SA1.A1_COND, SA1.A1_TABELA, SE4.E4_DESCRI "
    "FROM {{tabela}} AS SA1 "
    "LEFT JOIN SE4{{empresa}} AS SE4 ON SE4.E4_FILIAL = SA1.A1_FILIAL "
    "AND SE4.E4_CODIGO = SA1.A1_COND AND SE4.D_E_L_E_T_ <> '*' "
    "WHERE SA1.D_E_L_E_T_ <> '*' AND SA1.A1_MSBLQL <> '1' AND SA1.A1_FILIAL = %s "
)


def _cliente(row):
    nome = _txt(row.get('A1_NOME'))
    return {
        'codigo': _txt(row.get('A1_COD')),
        'loja': _txt(row.get('A1_LOJA')),
        'nome': nome,
        'fantasia': _txt(row.get('A1_NREDUZ')) or nome,
        'cnpj': _txt(row.get('A1_CGC')),
        'condicao': _txt(row.get('A1_COND')),
        'condicao_descricao': _txt(row.get('E4_DESCRI')),
        'tabela': _txt(row.get('A1_TABELA')),
    }


def buscar_clientes(termo):
    """Clientes ativos da filial 0101 por razão social, fantasia, CNPJ ou código (até 50)."""
    termo = (termo or '').strip().upper()
    if len(termo) < 3:
        return []
    like = f'%{termo}%'
    sql = _SQL_CLIENTE.format(topo='TOP 50') + (
        "AND (SA1.A1_NOME LIKE %s OR SA1.A1_NREDUZ LIKE %s OR SA1.A1_CGC LIKE %s OR SA1.A1_COD LIKE %s) "
        "ORDER BY SA1.A1_NOME"
    )
    resultados = consultar(_BASE_CLIENTES, sql, [FILIAL_CHOPP, like, like, like, like])
    return [_cliente(r) for r in linhas_como_dict(resultados)]


def cliente(codigo, loja):
    """Um cliente ativo da filial 0101 (ou None se não existir / estiver bloqueado)."""
    sql = _SQL_CLIENTE.format(topo='TOP 1') + "AND SA1.A1_COD = %s AND SA1.A1_LOJA = %s"
    resultados = consultar(_BASE_CLIENTES, sql, [FILIAL_CHOPP, codigo, loja])
    for row in linhas_como_dict(resultados):
        return _cliente(row)
    return None


_SQL_PRODUTO = (
    "SELECT SB1.B1_COD, SB1.B1_DESC, ISNULL(SBM.BM_DESC, 'SEM GRUPO') AS BM_DESC "
    "FROM {tabela} AS SB1 "
    "LEFT JOIN SBM{empresa} AS SBM ON RTRIM(SBM.BM_GRUPO) = RTRIM(SB1.B1_GRUPO) AND SBM.D_E_L_E_T_ <> '*' "
    "WHERE SB1.D_E_L_E_T_ <> '*' AND SB1.B1_MSBLQL <> '1' AND SB1.B1_FILIAL = %s "
    "AND RTRIM(SB1.B1_GRUPO) IN ({grupos}) "
)


def _sql_produto(extra):
    marcadores = ', '.join(['%s'] * len(GRUPOS_PRODUTO_CHOPP))
    return _SQL_PRODUTO.replace('({grupos})', f'({marcadores})') + extra


def _produtos(resultados):
    produtos = {}
    for row in linhas(resultados):
        codigo = _txt(row[0])
        if codigo not in produtos:
            produtos[codigo] = {'codigo': codigo, 'descricao': _txt(row[1]), 'grupo_familia': _txt(row[2])}
    return produtos


def buscar_produtos(termo):
    """Produtos de chopp (filial 0101, não bloqueados) por descrição ou código."""
    termo = (termo or '').strip().upper()
    if len(termo) < 3:
        return []
    sql = _sql_produto("AND (SB1.B1_DESC LIKE %s OR SB1.B1_COD LIKE %s) ORDER BY SB1.B1_DESC")
    resultados = consultar(_BASE_PRODUTOS, sql, [FILIAL_CHOPP] + GRUPOS_PRODUTO_CHOPP + [f'%{termo}%', f'%{termo}%'])
    return list(_produtos(resultados).values())


def listar_produtos():
    """Todos os produtos de chopp ativos da filial 0101."""
    resultados = consultar(_BASE_PRODUTOS, _sql_produto("ORDER BY SB1.B1_DESC"), [FILIAL_CHOPP] + GRUPOS_PRODUTO_CHOPP)
    return list(_produtos(resultados).values())


def clientes_ao_acaso(quantidade):
    """Clientes ativos da filial 0101 com condição de pagamento e tabela de preço (para dados de teste)."""
    sql = _SQL_CLIENTE.format(topo=f'TOP {int(quantidade)}') + (
        "AND RTRIM(SA1.A1_COND) <> '' AND RTRIM(SA1.A1_TABELA) <> '' ORDER BY NEWID()"
    )
    return [_cliente(r) for r in linhas_como_dict(consultar(_BASE_CLIENTES, sql, [FILIAL_CHOPP]))]


def produtos_validos(codigos):
    """{codigo: produto} só dos códigos que são produtos de chopp válidos."""
    codigos = sorted({_txt(c) for c in codigos if _txt(c)})
    if not codigos:
        return {}
    marcadores = ', '.join(['%s'] * len(codigos))
    sql = _sql_produto(f"AND RTRIM(SB1.B1_COD) IN ({marcadores})")
    resultados = consultar(_BASE_PRODUTOS, sql, [FILIAL_CHOPP] + GRUPOS_PRODUTO_CHOPP + codigos)
    return _produtos(resultados)


def precos_tabela(tabela, codigos):
    """{codigo: Decimal} com o preço de cada produto na tabela do cliente (filial 0101)."""
    tabela = _txt(tabela)
    codigos = sorted({_txt(c) for c in codigos if _txt(c)})
    if not tabela or not codigos:
        return {}
    marcadores = ', '.join(['%s'] * len(codigos))
    sql = (
        "SELECT RTRIM(DA1_CODPRO), DA1_PRCVEN FROM {tabela} "
        "WHERE D_E_L_E_T_ <> '*' AND DA1_FILIAL = %s AND DA1_CODTAB = %s "
        f"AND RTRIM(DA1_CODPRO) IN ({marcadores}) "
        "ORDER BY R_E_C_N_O_"
    )
    precos = {}
    for codigo, preco in linhas(consultar(_BASE_PRECOS, sql, [FILIAL_CHOPP, tabela] + codigos)):
        codigo = _txt(codigo)
        if codigo not in precos and preco is not None:   # o primeiro (menor R_E_C_N_O_) vale
            precos[codigo] = Decimal(str(preco)).quantize(Decimal('0.01'))
    return precos


def inadimplencia(clientes, vencidos_antes_de):
    """
    clientes: [(codigo, loja), ...]; vencidos_antes_de: date (títulos com vencimento real anterior a ela).
    Retorna {(codigo, loja): {'titulos': n, 'valor': Decimal, 'vencimento': date mais antigo}} só dos inadimplentes.
    """
    pares = {(_txt(c), _txt(l)) for c, l in clientes if _txt(c)}
    if not pares:
        return {}
    codigos = sorted({c for c, _ in pares})
    marcadores = ', '.join(['%s'] * len(codigos))
    sql = (
        "SELECT RTRIM(E1_CLIENTE), RTRIM(E1_LOJA), COUNT(*), SUM(E1_SALDO), MIN(E1_VENCREA) FROM {tabela} "
        "WHERE D_E_L_E_T_ <> '*' AND E1_SALDO > 0 AND E1_VENCREA < %s "
        "AND E1_TIPO NOT IN ('RA', 'NCC') AND RTRIM(E1_TIPO) NOT LIKE %s "
        f"AND RTRIM(E1_CLIENTE) IN ({marcadores}) "
        "GROUP BY E1_CLIENTE, E1_LOJA"
    )
    params = [vencidos_antes_de.strftime('%Y%m%d'), '%-'] + codigos
    resultado = {}
    for codigo, loja, qtd, saldo, vencimento in linhas(consultar(_BASE_TITULOS, sql, params)):
        chave = (_txt(codigo), _txt(loja))
        if chave not in pares:
            continue
        atual = resultado.setdefault(chave, {'titulos': 0, 'valor': Decimal('0'), 'vencimento': None})
        atual['titulos'] += int(qtd or 0)
        atual['valor'] += Decimal(str(saldo or 0)).quantize(Decimal('0.01'))
        try:
            venc = datetime.strptime(_txt(vencimento), '%Y%m%d').date()
        except ValueError:
            venc = None
        if venc and (atual['vencimento'] is None or venc < atual['vencimento']):
            atual['vencimento'] = venc
    return resultado


# Nome da empresa na lista de títulos: CIEC empresa 01 = CIEC, empresa 02 = ISLA
_NOME_EMPRESA = {('protheus_ciec', 'SE1010'): 'CIEC', ('protheus_ciec', 'SE1020'): 'ISLA', ('protheus_wrp', 'SE1010'): 'WRP'}


def titulos_vencidos(codigo, loja, vencidos_antes_de):
    """Títulos em aberto e vencidos do cliente (código + loja), em todas as empresas, do mais antigo ao mais novo."""
    sql = (
        "SELECT E1_FILIAL, E1_PREFIXO, E1_NUM, E1_PARCELA, E1_TIPO, E1_EMISSAO, E1_VENCREA, E1_VALOR, E1_SALDO FROM {tabela} "
        "WHERE D_E_L_E_T_ <> '*' AND E1_SALDO > 0 AND E1_VENCREA < %s "
        "AND E1_TIPO NOT IN ('RA', 'NCC') AND RTRIM(E1_TIPO) NOT LIKE %s "
        "AND RTRIM(E1_CLIENTE) = %s AND RTRIM(E1_LOJA) = %s "
        "ORDER BY E1_VENCREA"
    )
    params = [vencidos_antes_de.strftime('%Y%m%d'), '%-', _txt(codigo), _txt(loja)]

    def data(valor):
        try:
            return datetime.strptime(_txt(valor), '%Y%m%d').date()
        except ValueError:
            return None

    titulos = []
    for resultado in consultar(_BASE_TITULOS, sql, params):
        empresa = _NOME_EMPRESA.get((resultado['base'], resultado['tabela']), resultado['tabela'])
        for row in linhas_como_dict([resultado]):
            titulos.append({
                'empresa': empresa,
                'filial': _txt(row.get('E1_FILIAL')),
                'prefixo': _txt(row.get('E1_PREFIXO')),
                'numero': _txt(row.get('E1_NUM')),
                'parcela': _txt(row.get('E1_PARCELA')),
                'tipo': _txt(row.get('E1_TIPO')),
                'emissao': data(row.get('E1_EMISSAO')),
                'vencimento': data(row.get('E1_VENCREA')),
                'valor': Decimal(str(row.get('E1_VALOR') or 0)).quantize(Decimal('0.01')),
                'saldo': Decimal(str(row.get('E1_SALDO') or 0)).quantize(Decimal('0.01')),
            })
    titulos.sort(key=lambda t: (t['vencimento'] or datetime.max.date(), t['empresa'], t['numero']))
    return titulos
