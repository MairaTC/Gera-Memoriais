# -*- coding: utf-8 -*-
"""
geocuritiba.py - ETAPA 3: consultas ao GeoCuritiba (serviço REST do IPPUC).

Quando ligada, recupera:
  - da camada "Lote Cadastral": indicação fiscal, número predial e planta
    de cada lote do loteamento ou fora dele (confrontantes)
  - da camada "Trecho Logradouro": os eixos das ruas, com o nome e o código
    oficiais

"""
import json                     # transforma a resposta (texto JSON) em dicionário
import urllib.parse             # monta a URL da consulta
import urllib.request           # faz a consulta pela internet
from qgis.core import QgsGeometry, QgsPointXY

SERVICO = ("https://geocuritiba.ippuc.org.br/server/rest/services/"
           "GeoCuritiba/Publico_GeoCuritiba_MapaCadastral/MapServer")
EPSG = 31982            # SIRGAS 2000 / UTM 22S
TEMPO_LIMITE = 20       # tempo de espera por resposta
ENVOLVE_RUAS = 30.0       # metros em volta do loteamento para buscar as ruas
CAMADA_LOTE = 15        # id da camada "Lote Cadastral" no serviço
CAMADA_EIXO = 11        # id da camada "Trecho Logradouro" no serviço


# faz a consulta pela internet e devolve a resposta como dicionário
def baixar_json(url):
    try:
        resposta = urllib.request.urlopen(url, timeout=TEMPO_LIMITE)
        return json.loads(resposta.read().decode("utf-8"))
    except Exception:
        return None


# faz uma consulta a uma camada do serviço e devolve a lista de feições
def consultar(numero_camada, parametros):

    # parâmetros comuns a todas as consultas
    parametros["f"] = "json"
    parametros["inSR"] = EPSG
    parametros["outSR"] = EPSG
    parametros["spatialRel"] = "esriSpatialRelIntersects"
    parametros["outFields"] = "*"

    # monta a URL, faz a consulta e devolve as feições
    url = SERVICO + "/" + str(numero_camada) + "/query?" + urllib.parse.urlencode(parametros)
    dados = baixar_json(url)
    if dados is None or "features" not in dados:
        return None
    return dados["features"]


# consulta os dados do cadastro de um lote a partir de um ponto dentro dele
def consultar_lote(ponto):

    # busca o lote do cadastro que contém o ponto
    feicoes = consultar(CAMADA_LOTE, {
        "geometry": f"{ponto.x()},{ponto.y()}",
        "geometryType": "esriGeometryPoint",
        "returnGeometry": "false",
    })
    if not feicoes:
        return {}

    # pega só os dados que o memorial usa
    atributos = feicoes[0]["attributes"]
    return {
        "indicacao_fiscal": limpar(atributos["gtm_ind_fiscal"]),
        "numero_predial": limpar(atributos["gtm_num_predial"]),
        "cod_logradouro": limpar(atributos["gtm_cod_logradouro"]),
        "nome_planta": limpar(atributos["gtm_nm_planta"]),
    }


# tira os espaços das pontas; vazio (o cadastro manda "", " " ou nada) vira None
def limpar(valor):
    valor = (valor or "").strip()
    if valor == "":
        return None
    return valor


# busca os eixos de rua em volta do loteamento, com o nome e o código oficiais
def buscar_eixos(caixa):

    # busca os eixos dentro do retângulo do loteamento, aumentado em ENVOLVE_RUAS
    retangulo = (f"{caixa.xMinimum() - ENVOLVE_RUAS},{caixa.yMinimum() - ENVOLVE_RUAS},"
                 f"{caixa.xMaximum() + ENVOLVE_RUAS},{caixa.yMaximum() + ENVOLVE_RUAS}")
    feicoes = consultar(CAMADA_EIXO, {
        "geometry": retangulo,
        "geometryType": "esriGeometryEnvelope",
        "returnGeometry": "true",
    })
    if feicoes is None:
        return None

    # para cada eixo: monta o nome com o código, ex.: "RUA ALAGOAS (S221)",
    # e transforma a linha do eixo (lista de pontos [x, y]) em geometria do QGIS
    eixos = []
    for feicao in feicoes:
        atributos = feicao["attributes"]
        nome = limpar(atributos["gtm_nm_logradouro"])
        codigo = limpar(atributos["gtm_cod_logradouro"])
        if not nome:
            continue
        if codigo:
            nome = nome + " (" + codigo + ")"
        partes = []
        for caminho in feicao["geometry"]["paths"]:
            partes.append([QgsPointXY(x, y) for x, y in caminho])
        eixos.append({"nome": nome, "geometria": QgsGeometry.fromMultiPolylineXY(partes)})
    return eixos


# acha o nome oficial de uma rua da planta: o do eixo com o maior trecho dentro dela
def nome_oficial(rua, eixos):
    melhor_nome = None
    melhor_comprimento = 0
    for eixo in eixos:
        comprimento = eixo["geometria"].intersection(rua["geometria"]).length()
        if comprimento > melhor_comprimento:
            melhor_nome = eixo["nome"]
            melhor_comprimento = comprimento
    return melhor_nome


# formata a indicação fiscal no padrão do memorial: 62038031 -> 62.038.031.000
def formatar_if(valor):
    if valor is None:
        return None

    # o cadastro manda 8 dígitos (planta, quadra e lote): coloca os pontos e o sublote 000
    # se vier fora desse padrão, devolve como veio
    if len(valor) != 8:
        return valor
    return valor[0:2] + "." + valor[2:5] + "." + valor[5:8] + ".000"


# diz se o número predial é par ou ímpar ("" se não houver número)
def lado_da_rua(numero_predial):
    try:
        if int(numero_predial) % 2 == 0:
            return "par"
        return "ímpar"
    except (TypeError, ValueError):
        return ""
