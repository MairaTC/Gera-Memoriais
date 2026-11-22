# -*- coding: utf-8 -*-
"""
saida.py — ETAPA 8: o texto do memorial, o GeoPackage e o DOCX.

  1. montar_texto: o texto corrido do memorial de um lote, no modelo da COHAB-CT;
  2. salvar_gpkg:  uma camada com um polígono por lote e as informações na tabela;
  3. salvar_docx:  um DOCX (editável) com um memorial por página, a partir do modelo_memorial.docx.
"""
import json                               
import os                                 
import zipfile            
from html import escape                        
from qgis.core import (QgsVectorLayer, QgsFeature, QgsField, QgsGeometry,
                       QgsProject, QgsVectorFileWriter)
from qgis.PyQt.QtCore import QVariant

from .calculos import FALTA, rua_do_lado

PASTA_PLUGIN = os.path.dirname(__file__)


# ---------------------------------------------------------------
# 1. Texto do memorial
# ---------------------------------------------------------------

# converte um número para o padrão brasileiro
def numero_br(valor):
    texto = f"{valor:,.2f}"
    texto = texto.replace(",", "X")
    texto = texto.replace(".", ",")
    texto = texto.replace("X", ".")
    return texto


# monta as coordenadas do ponto no formato usado pelo memorial
def coordenadas(ponto):
    return f"(coordenadas X: {ponto.x():.4f} e Y: {ponto.y():.4f})"


# padroniza a grafia do nome da rua
def nome_da_rua(nome):
    if not nome:
        return FALTA
    nome = str(nome).title()
    if "(" in nome:
        abre = nome.rfind("(")
        nome = nome[:abre] + nome[abre:].replace(" ", "")
    for palavra in ["De", "Da", "Do", "Das", "Dos"]:
        nome = nome.replace(" " + palavra + " ", " " + palavra.lower() + " ")
    return nome


# junta uma lista em texto com "e" antes do último item
def juntar_com_e(lista):
    if len(lista) == 1:
        return lista[0]
    return ", ".join(lista[:-1]) + " e " + lista[-1]


# monta os confrontantes de um lado no formato usado no memorial
def texto_confrontantes(lado):
    ruas = []
    lotes = []
    indicacoes = []
    for tipo, nome in lado["confrontantes"]:
        if tipo == "Rua":
            ruas.append("a " + nome_da_rua(nome))
        elif tipo == "Lote":
            lotes.append(nome)
        else:
            indicacoes.append(str(nome))           # terreno de fora: indicação fiscal

    partes = ruas
    if len(lotes) == 1:
        partes.append("o lote " + lotes[0])
    if len(lotes) > 1:
        partes.append("os lotes " + juntar_com_e(lotes))
    if len(indicacoes) == 1:
        partes.append("o lote de Indicação Fiscal " + indicacoes[0])
    if len(indicacoes) > 1:
        indicacoes.sort()
        partes.append("os lotes de Indicações Fiscais " + juntar_com_e(indicacoes))
    return juntar_com_e(partes)


# informa se o lote está na esquina ou a distância até ela
def texto_esquina(lote):
    esquina = lote["esquina"]
    if esquina is None:
        return f"a {FALTA} metros da esquina formada com a {FALTA}"
    if esquina["distancia"] == 0:
        return "na esquina formada com a " + nome_da_rua(esquina["rua"])
    return f"a {numero_br(esquina['distancia'])} metros da esquina formada com a {nome_da_rua(esquina['rua'])}"


# monta o texto corrido do memorial de um lote
def montar_texto(lote, dados):
    # planta: só o nome, o digitado na janela; se ficou em branco, o do cadastro
    planta = (dados["planta"] or lote["planta_cadastro"] or FALTA).upper()
    texto = (f"Lote de terreno {lote['codigo']}, da quadra {lote['quadra']}, "
             f"da planta {planta}, "
             f"localizado nesta capital, no bairro {dados['bairro'] or FALTA}, "
             f"no lado {lote['lado_rua'] or FALTA} da {nome_da_rua(rua_do_lado(lote['lados'][0]))}, "
             f"número {lote['numero_predial'] or FALTA}, {texto_esquina(lote)}, "
             f"de forma {lote['forma']}, e com as seguintes medidas, características e confrontações "
             f"do ponto de vista de quem da frente o observa: ")

    # monta um trecho para cada lado, seguindo o P0PP e os vértices seguintes
    lados = lote["lados"]
    trechos = []
    for i in range(len(lados)):
        lado = lados[i]
        primeiro = (i == 0)
        ultimo = (i == len(lados) - 1)
        if ultimo:
            proximo = lados[0]                  # o último lado volta ao P0PP
        else:
            proximo = lados[i + 1]

        trecho = ""
        if primeiro:
            trecho = "partindo "
        if ultimo:
            trecho = "e "
        trecho = trecho + "do ponto " + lado["vertice"] + " "
        if primeiro:
            trecho = trecho + coordenadas(lado["de"]) + " "
        trecho = trecho + "até o ponto " + proximo["vertice"] + " "
        if not ultimo:                          # o último não repete as coordenadas do P0PP
            trecho = trecho + coordenadas(proximo["de"]) + " "
        if lado.get("frente"):
            trecho = trecho + f"apresenta {numero_br(lado['comprimento'])} metros de frente para {texto_confrontantes(lado)}"
        else:
            trecho = trecho + f"apresenta {numero_br(lado['comprimento'])} metros e confronta com {texto_confrontantes(lado)}"
        trechos.append(trecho)

    # fecha o memorial com o perímetro completo e a indicação fiscal
    texto = texto + "; ".join(trechos)
    texto = texto + f", fechando o perímetro e perfazendo a área total de {numero_br(lote['area'])} m². "
    texto = texto + f"Indicação fiscal {lote['indicacao_fiscal'] or FALTA}."
    return texto


# define a ordem dos lotes no GeoPackage e no DOCX
def ordem(lote):
    return (lote["quadra"].zfill(5), lote["codigo"].zfill(5))


# ---------------------------------------------------------------
# 2. GeoPackage
# ---------------------------------------------------------------

# colunas da tabela: (nome, tipo)
COLUNAS = [
    ("quadra", QVariant.String), ("lote", QVariant.String),
    ("planta", QVariant.String), ("bairro", QVariant.String),
    ("carimbo", QVariant.String), ("arquiteto", QVariant.String), ("cau", QVariant.String),
    ("area_m2", QVariant.Double), ("perimetro_m", QVariant.Double), ("n_vertices", QVariant.Int),
    ("rua_frente", QVariant.String), ("numero_predial", QVariant.String),
    ("lado_rua", QVariant.String), ("indicacao_fiscal", QVariant.String),
    ("forma", QVariant.String), ("distancia_esquina", QVariant.Double),
    ("rua_esquina", QVariant.String),
    ("vertices", QVariant.String),   # lista de vértices em texto JSON
    ("lados", QVariant.String),      # lista de lados em texto JSON
    ("memorial", QVariant.String),   # texto do memorial
]


# cria a camada de lotes na memória e grava no GeoPackage
def salvar_gpkg(lotes, crs, dados, caminho, mensagens):
    camada = QgsVectorLayer("Polygon?crs=" + crs.authid(), "lotes", "memory")
    campos = []
    for nome, tipo in COLUNAS:
        campos.append(QgsField(nome, tipo))
    camada.dataProvider().addAttributes(campos)
    camada.updateFields()

    # percorre os lotes em ordem para preencher uma feição por lote
    for lote in sorted(lotes, key=ordem):
        lados = lote["lados"]

        # o polígono é refeito a partir dos lados, para começar no P0PP
        pontos = []
        for lado in lados:
            pontos.append(lado["de"])
        pontos.append(lados[0]["de"])               # fecha o polígono

        perimetro = 0
        vertices = []
        lista_lados = []
        for i in range(len(lados)):
            lado = lados[i]
            perimetro = perimetro + lado["comprimento"]
            vertices.append({"vertice": lado["vertice"], "x": lado["de"].x(), "y": lado["de"].y()})
            if i == len(lados) - 1:
                para = lados[0]["vertice"]
            else:
                para = lados[i + 1]["vertice"]
            # guarda os confrontantes em uma estrutura simples para o JSON
            confrontantes = []
            for tipo, nome in lado["confrontantes"]:
                confrontantes.append({"tipo": tipo, "nome": nome})
            lista_lados.append({"de": lado["vertice"], "para": para,
                                "comprimento": lado["comprimento"], "confrontantes": confrontantes})

        # no GeoPackage, lote sem esquina tem os dois campos vazios
        if lote["esquina"] is None:
            distancia_esquina = None
            rua_esquina = None
        else:
            distancia_esquina = round(lote["esquina"]["distancia"], 2)
            rua_esquina = lote["esquina"]["rua"]

        # monta a geometria e escreve todos os atributos da tabela
        feicao = QgsFeature(camada.fields())
        feicao.setGeometry(QgsGeometry.fromPolygonXY([pontos]))
        feicao.setAttributes([
            lote["quadra"], lote["codigo"],
            dados["planta"], dados["bairro"],
            dados["carimbo"], dados["arquiteto"], dados["cau"],
            round(lote["area"], 2), round(perimetro, 2), len(lados),
            rua_do_lado(lados[0]), lote["numero_predial"],
            lote["lado_rua"], lote["indicacao_fiscal"],
            lote["forma"], distancia_esquina, rua_esquina,
            json.dumps(vertices, ensure_ascii=False),
            json.dumps(lista_lados, ensure_ascii=False),
            montar_texto(lote, dados),
        ])
        camada.dataProvider().addFeature(feicao)

    # configura o formato de saída e grava o arquivo GPKG
    opcoes = QgsVectorFileWriter.SaveVectorOptions()
    opcoes.driverName = "GPKG"
    opcoes.layerName = "lotes"
    opcoes.fileEncoding = "UTF-8"
    erro = QgsVectorFileWriter.writeAsVectorFormatV3(camada, caminho,
                                                     QgsProject.instance().transformContext(), opcoes)
    if erro[0] != QgsVectorFileWriter.NoError:
        raise ValueError("Não foi possível gravar o GeoPackage: " + erro[1])
    mensagens.append(f"GeoPackage salvo em {caminho} ({len(lotes)} lotes)")


# ---------------------------------------------------------------
# 3. DOCX
# ---------------------------------------------------------------

MODELO = os.path.join(PASTA_PLUGIN, "modelo_memorial.docx")

# um trecho de texto, em negrito e/ou vermelho
def trecho_xml(texto, negrito=False, vermelho=False):
    formato = ""
    if negrito:
        formato = formato + "<w:b/>"
    if vermelho:
        formato = formato + '<w:color w:val="FF0000"/>'
    return f'<w:r><w:rPr>{formato}</w:rPr><w:t xml:space="preserve">{escape(texto)}</w:t></w:r>'

# um trecho de texto em que o [PREENCHER] sai em vermelho
def trecho_com_falta(texto, negrito=False):
    pedacos = texto.split(FALTA)
    xml = ""
    for i in range(len(pedacos)):
        if i > 0:
            xml = xml + trecho_xml(FALTA, negrito, vermelho=True)
        if pedacos[i] != "":
            xml = xml + trecho_xml(pedacos[i], negrito)
    return xml

# um parágrafo com um dos estilos do modelo
def paragrafo_xml(estilo, conteudo):
    return f'<w:p><w:pPr><w:pStyle w:val="{estilo}"/></w:pPr>{conteudo}</w:p>'

# o memorial de um lote: título, texto e assinatura
# (menos no último lote, a assinatura termina com uma quebra de página)
def memorial_xml(lote, dados, ultimo):

    # monta o título com o carimbo, marcando falta de dado em vermelho
    titulo = trecho_com_falta("MEMORIAL DESCRITIVO DO " + (dados["carimbo"].upper() or FALTA))

    # monta o texto em partes; lote e indicação fiscal ficam em negrito
    texto = montar_texto(lote, dados)
    abertura = "Lote de terreno " + lote["codigo"]
    inicio_if = texto.rfind("Indicação fiscal")
    corpo = (trecho_com_falta("Lote de terreno ")
             + trecho_com_falta(lote["codigo"], negrito=True)
             + trecho_com_falta(texto[len(abertura):inicio_if])
             + trecho_com_falta(texto[inicio_if:].rstrip("."), negrito=True)
             + trecho_com_falta("."))

    # monta a assinatura com título, arquiteto e CAU
    assinatura = (trecho_com_falta(dados["titulo"] + " " + (dados["arquiteto"] or FALTA))
                  + "<w:r><w:br/></w:r>"
                  + trecho_com_falta("CAU " + (dados["cau"] or FALTA)))
    # exceto no último lote, termina cada memorial com uma quebra de página
    if not ultimo:
        assinatura = assinatura + '<w:r><w:br w:type="page"/></w:r>'

    return (paragrafo_xml("MemorialTitulo", titulo)
            + paragrafo_xml("MemorialTexto", corpo)
            + paragrafo_xml("MemorialAssinatura", assinatura))

# um DOCX com todos os memoriais, um lote por página, na ordem de quadra e lote
def salvar_docx(lotes, dados, caminho, mensagens):

    # monta os parágrafos de todos os lotes em ordem
    ordenados = sorted(lotes, key=ordem)
    paragrafos = ""
    for i in range(len(ordenados)):
        paragrafos = paragrafos + memorial_xml(ordenados[i], dados, ultimo=(i == len(ordenados) - 1))
    if paragrafos == "":
        paragrafos = "<w:p/>"          # o Word exige pelo menos um parágrafo

    # copia o modelo, trocando o corpo do documento pelos memoriais
    with zipfile.ZipFile(MODELO) as modelo:
        documento = modelo.read("word/document.xml").decode("utf-8")
        # preserva a marcação final da seção e substitui apenas o corpo
        inicio = documento.index("<w:body>") + len("<w:body>")
        fim = documento.rindex("<w:sectPr")
        documento = documento[:inicio] + paragrafos + documento[fim:]
        with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as novo:
            for arquivo in modelo.infolist():
                if arquivo.filename == "word/document.xml":
                    novo.writestr(arquivo, documento.encode("utf-8"))
                else:
                    novo.writestr(arquivo, modelo.read(arquivo.filename))
    mensagens.append(f"DOCX com {len(lotes)} memoriais salvo em {caminho}")
