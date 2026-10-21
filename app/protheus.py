"""
Consulta às bases do Protheus (CIEC e WRP) num só lugar.

Antes cada tela repetia o mesmo laço "para cada base, para cada tabela" e engolia os erros,
então um Protheus fora do ar aparecia como "nenhum resultado". Aqui:
- erro numa tabela vai para o log e as outras continuam;
- se nenhuma tabela pôde ser consultada, levanta ProtheusIndisponivel para a tela avisar.
"""
import logging

from django.db import connections

logger = logging.getLogger(__name__)


class ProtheusIndisponivel(Exception):
    pass


def consultar(bases, query_template, params=None):
    """
    bases: {'protheus_ciec': ['SB1010', 'SB1020'], ...}
    query_template: SQL com {tabela} e, se precisar, {empresa} (sufixo da tabela, ex. '010').
    params: valores da consulta (sempre como parâmetros, nunca colados no SQL).

    Retorna uma lista de resultados, um por tabela consultada com sucesso:
    [{'base': ..., 'tabela': ..., 'colunas': [...], 'linhas': [...]}, ...]
    """
    resultados = []
    erros = []
    for base, tabelas in bases.items():
        if base not in connections:
            erros.append(f"{base}: conexão não configurada")
            continue
        for tabela in tabelas:
            sql = query_template.format(tabela=tabela, empresa=tabela[-3:])
            try:
                with connections[base].cursor() as cursor:
                    cursor.execute(sql, params or [])
                    colunas = [str(c[0]).strip() if c[0] else f"coluna_{i}" for i, c in enumerate(cursor.description or [])]
                    resultados.append({'base': base, 'tabela': tabela, 'colunas': colunas, 'linhas': cursor.fetchall()})
            except Exception as e:
                logger.error("Erro ao consultar Protheus [%s - %s]: %s", base, tabela, e)
                erros.append(f"{base}/{tabela}: {e}")

    if not resultados:
        raise ProtheusIndisponivel("Não foi possível consultar o Protheus. " + "; ".join(erros))
    return resultados


def linhas(resultados):
    """Todas as linhas de todas as tabelas, na ordem consultada."""
    for r in resultados:
        for linha in r['linhas']:
            yield linha


def linhas_como_dict(resultados):
    """Todas as linhas como dicionários {coluna: valor}."""
    for r in resultados:
        for linha in r['linhas']:
            yield dict(zip(r['colunas'], linha))
