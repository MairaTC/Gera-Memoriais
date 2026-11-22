# -*- coding: utf-8 -*-
"""
leitura.py - ETAPA 1: ler a planta (DXF) e montar os polígonos limpos

- abre o DXF (o QGIS abre o DXF como uma tabela);
- separa as linhas e os textos das camadas do CAD escolhidas na janela;
- transforma as linhas em polígonos limpos;
- associa cada polígono ao texto que está dentro dele;

"""
import processing   # ferramentas da Caixa de Ferramentas de Processamento
from qgis.core import QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY, QgsField
from qgis.PyQt.QtCore import QVariant  # tipo de campo (texto) da camada de textos

# Vértices a menos de 1 cm um do outro, ou a menos de 1 cm da reta entre os
# vizinhos, são tirados na limpeza (não são cantos de verdade).
TOLERANCIA = 0.01

#abre dxf
def abrir_dxf(caminho):
    planta = QgsVectorLayer(caminho, "planta", "ogr")
    if not planta.isValid():
        raise ValueError("Não foi possível abrir a planta: " + caminho)
    return planta

#recupera os nomes das camadas do dxf
def nomes_das_camadas(caminho):
    planta = abrir_dxf(caminho)
    indice = planta.fields().indexOf("Layer")
    nomes = []
    for nome in planta.uniqueValues(indice):
        nomes.append(str(nome))
    nomes.sort()
    return nomes

#corrige acentos com problema de codificação
def corrigir_acentos(texto):
    try:
        return texto.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return texto

#cria camada temporária para as linhas
def separar_linhas(planta, crs, camadas_cad):
    linhas = QgsVectorLayer("LineString?crs=" + crs.authid(), "linhas", "memory")
    for feicao in planta.getFeatures():
        if str(feicao["Layer"]) not in camadas_cad: 
            continue #descarta camadas que não foram selecionadas                         
        pontos = []
        for vertice in feicao.geometry().vertices():
            pontos.append(QgsPointXY(vertice.x(), vertice.y())) 
        if len(pontos) < 3:
            continue # descarta linhas com menos de 3 vértices
        nova = QgsFeature()
        nova.setGeometry(QgsGeometry.fromPolylineXY(pontos))
        linhas.dataProvider().addFeature(nova)
    return linhas

#cria camada temporária para os pontos (rótulos)
def separar_textos(planta, crs, camadas_cad):
    textos = QgsVectorLayer("Point?crs=" + crs.authid(), "textos", "memory")
    textos.dataProvider().addAttributes([QgsField("texto", QVariant.String)])
    textos.updateFields()
    for feicao in planta.getFeatures():
        if str(feicao["Layer"]) not in camadas_cad:
            continue #descarta camadas que não foram selecionadas   
        conteudo = feicao["Text"]
        if conteudo is None or str(conteudo) in ("", "NULL"):
            continue #descarta se não é texto
        ponto = feicao.geometry().vertexAt(0) # ponto de inserção do texto
        nova = QgsFeature(textos.fields())
        nova.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(ponto.x(), ponto.y())))
        nova["texto"] = corrigir_acentos(str(conteudo)).strip()
        textos.dataProvider().addFeature(nova)
    return textos

#transforma linhas em polígonos limpos
def limpar_poligonos(linhas):
    """Quatro ferramentas do QGIS, uma depois da outra:
    Linhas para polígonos -> Remover vértices duplicados -> Simplificar ->
    Forçar regra da mão direita (deixa todos os polígonos em sentido horário)."""
    resultado = processing.run("qgis:linestopolygons",
                               {"INPUT": linhas, "OUTPUT": "memory:"}) #linhas para polígonos
    resultado = processing.run("native:removeduplicatevertices",
                               {"INPUT": resultado["OUTPUT"], "TOLERANCE": TOLERANCIA, #remove vértices duplicados ou muito próximos
                                "USE_Z_VALUE": False, "OUTPUT": "memory:"})
    resultado = processing.run("native:simplifygeometries",
                               {"INPUT": resultado["OUTPUT"], "METHOD": 0, #simplifica a geometria dos polígonos
                                "TOLERANCE": TOLERANCIA, "OUTPUT": "memory:"})
    resultado = processing.run("native:forcerhr",
                               {"INPUT": resultado["OUTPUT"], "OUTPUT": "memory:"}) #ordena o sentido do desenho do polígono no sentido horário
    return resultado["OUTPUT"]

# associa polígonos e seus rótulos
def juntar_textos(poligonos, textos):
    resultado = processing.run("native:joinattributesbylocation", {
        "INPUT": poligonos, "JOIN": textos,
        "PREDICATE": [1],            # 1 = contém
        "JOIN_FIELDS": ["texto"],
        "METHOD": 1,       
        "DISCARD_NONMATCHING": False,
        "PREFIX": "",
        "OUTPUT": "memory:"})
    return resultado["OUTPUT"]

# retorna o conteúdo da coluna 'texto' de um polígono
def texto_do_poligono(feicao):
    texto = str(feicao["texto"])
    if texto == "NULL" or texto == "None":
        return ""
    return texto.strip()

# devolve uma lista de polígonos nomeados {"nome": texto, "geometria": polígono}
def poligonos_com_nome(planta, crs, camadas_linhas, camadas_textos):
    poligonos = limpar_poligonos(separar_linhas(planta, crs, camadas_linhas))
    if camadas_textos:
        poligonos = juntar_textos(poligonos, separar_textos(planta, crs, camadas_textos))
    lista = []
    for feicao in poligonos.getFeatures():
        nome = ""
        if camadas_textos:
            nome = texto_do_poligono(feicao)
        lista.append({"nome": nome, "geometria": QgsGeometry(feicao.geometry())})
    return lista

# lê a planta e devolve uma lista com nome e geometria de cada "classe" de polígono 
def ler_planta(caminho, crs, camadas, mensagens):

    planta = abrir_dxf(caminho)

    lotes = []
    for item in poligonos_com_nome(planta, crs, camadas["lotes"], camadas["lotes_txt"]):
        codigo = item["nome"].replace("Lote", "").strip()          # "Lote 01" -> "01"
        if codigo == "":
            mensagens.append("Um lote não tem rótulo em seu interior, confira a camada de rótulos.")
            continue
        lotes.append({"codigo": codigo, "geometria": item["geometria"]})

    quadras = poligonos_com_nome(planta, crs, camadas["quadras"], camadas["quadras_txt"])
    for quadra in quadras:
        quadra["nome"] = quadra["nome"].replace("Q", "", 1).strip()  # "Q7-A" -> "7-A"

    terrenos = poligonos_com_nome(planta, crs, camadas["confrontantes"], camadas["confrontantes_txt"])
    ruas = poligonos_com_nome(planta, crs, camadas["ruas"], camadas["ruas_txt"])

    mensagens.append(f"Lidos: {len(lotes)} lotes, {len(quadras)} quadras, "
                     f"{len(terrenos)} terrenos de fora e {len(ruas)} ruas.")
    return lotes, quadras, terrenos, ruas
