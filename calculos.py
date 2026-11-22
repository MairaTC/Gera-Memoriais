# -*- coding: utf-8 -*-
"""
calculos.py - tudo o que é calculado sobre os lotes.

  ETAPA 2  vértices e lados de cada lote, e a quadra do lote
  ETAPA 4  confrontantes de cada lado
  ETAPA 5  identifica a frente do lote
  ETAPA 6  distância da frente até a esquina, andando pela borda da quadra
  ETAPA 7  área, forma, dados do cadastro, etc

Cada LOTE é um dicionário que vai ganhando informações a cada etapa:
  {"codigo": "01", "quadra": "7-A", "geometria": ..., "lados": [...],
   "cadastro": {...}, "esquina": {...}, "area": 129.13, ...}

Cada LADO também é um dicionário:
  {"vertice": "P0PP",              nome do ponto onde o lado começa
   "de": ponto, "para": ponto,     ponto inicial e ponto final
   "comprimento": 6.80,            em metros
   "confrontantes": [("Rua", "RUA ALAGOAS (S 221)")],
   "frente": True}                 só no primeiro lado, depois da etapa 5

Lotes, quadras, terrenos de fora e ruas são polígonos lidos da planta.
Todas as medidas em metros (planta em SIRGAS 2000 / UTM 22S).
"""
from qgis.core import QgsGeometry, QgsPointXY
from . import geocuritiba

# ---------------------------------------------------------------
# Valores usados nas regras
# ---------------------------------------------------------------
FOLGA = 0.10            # buffer caso as divisas do CAD não coincidem perfeitamente
CONTATO_MINIMO = 0.20   # um lado só confronta com o vizinho se dividir com ele pelo menos isso de divisa
VIRADA_MINIMA = 30      # graus: o contorno da quadra precisa virar isso para ser um canto
PASSO_CANTO = 0.50      # pontos antes e depois do canto, para saber se ele aponta para fora
NA_ESQUINA = 0.05       # abaixo desta distância, o lote é na esquina
FALTA = "[PREENCHER]"   # aparece no memorial onde falta um dado


# ---------------------------------------------------------------
# ETAPA 2 — vértices e lados
# ---------------------------------------------------------------

#recupera a lista de vértices do contorno do polígono
def vertices_do_poligono(geometria):
    if geometria.isMultipart():
        contorno = geometria.asMultiPolygon()[0][0]
    else:
        contorno = geometria.asPolygon()[0]
    return contorno[:-1] #desconsidera último ponto (é igual ao primeiro)

#nomeia vértices
def nome_do_vertice(posicao):
    if posicao == 0:
        return "P0PP"
    return "P" + str(posicao).zfill(2)      # zfill(2): 1 -> "01"

#monta a lista de lados do polígono
def montar_lados(geometria):
    pontos = vertices_do_poligono(geometria)
    lados = []
    for i in range(len(pontos)):
        inicio = pontos[i]
        if i == len(pontos) - 1:
            fim = pontos[0]
        else:
            fim = pontos[i + 1]
        lados.append({"vertice": nome_do_vertice(i), "de": inicio, "para": fim,
                      "comprimento": inicio.distance(fim)})
    return lados

# monta a lista de lotes, cada um com a quadra em que está e a lista de lados
def montar_lotes(lotes, quadras, mensagens):
    resultado = []
    for lote in lotes:
        ponto = lote["geometria"].pointOnSurface()
        lote["ponto_interno"] = ponto.asPoint()
        lote["quadra"] = None
        for quadra in quadras:
            if quadra["geometria"].contains(ponto):
                lote["quadra"] = quadra["nome"]
                lote["geometria_quadra"] = quadra["geometria"]
        if lote["quadra"] is None:
            mensagens.append("Lote " + lote["codigo"] + " não está dentro de nenhuma quadra.")
            continue
        lote["lados"] = montar_lados(lote["geometria"])
        resultado.append(lote)
    return resultado


# ---------------------------------------------------------------
# ETAPA 4 — confrontantes
# ---------------------------------------------------------------

#recupera o comprimento do trecho da linha que fica dentro do buffer do vizinho
def contato(linha, vizinho):
    return linha.intersection(vizinho["buffer"]).length()

# retorna qual rua faz frente com um lado do lote
def rua_que_encosta(linha, ruas):

    melhor_nome = None                    # nenhuma rua escolhida ainda
    melhor_contato = CONTATO_MINIMO       # contato mínimo para encostar na rua
    for rua in ruas:                      # para cada rua da planta
        c = contato(linha, rua)           # quantos metros do lado ficam dentro do buffer da rua
        if c >= melhor_contato:           # se for o "melhor valor" encontrado até agora
            melhor_nome = rua["nome"]     # passa a ser a rua escolhida
            melhor_contato = c            # e o contato dela vira o valor a superar
    return melhor_nome                    # retorna nome da rua com "melhor" contato

# associa cada lado do lote com os vizinhos (lotes, terrenos e ruas)
def achar_confrontantes(lotes, terrenos, ruas):

    for vizinho in lotes + terrenos + ruas:                         # para cada polígono que pode ser vizinho
        vizinho["buffer"] = vizinho["geometria"].buffer(FOLGA, 4)   # cria o buffer para compensar pequenas diferenças de desenho

    for lote in lotes:                                              # para cada lote
        for lado in lote["lados"]:                                  # para cada lado do lote
            linha = QgsGeometry.fromPolylineXY([lado["de"], lado["para"]])   # transforma o lado numa linha (vértice inicial do lado até vértice final)
            lado["confrontantes"] = []                              # começa a lista de confrontantes do lado vazia
            for outro in lotes:                                     # testa os outros lotes
                if outro is not lote and contato(linha, outro) >= CONTATO_MINIMO:   # se não é o próprio lote e encosta pelo menos o mínimo
                    lado["confrontantes"].append(("Lote", outro["codigo"]))         # então é um confrontante
            for terreno in terrenos:                                # testa os terrenos de fora do loteamento
                if contato(linha, terreno) >= CONTATO_MINIMO:       # encosta pelo menos o mínimo
                    lado["confrontantes"].append(("Confrontante", terreno["nome"]))  # então é um confrontante
            if len(lado["confrontantes"]) == 0:                     # nenhum lote nem terreno encosta neste lado
                lado["confrontantes"].append(("Rua", rua_que_encosta(linha, ruas)))  # então o lado confronta com uma rua

# recupera o nome da rua com que o lado confronta
def rua_do_lado(lado):
    for tipo, nome in lado["confrontantes"]:
        if tipo == "Rua":
            return nome
    return None


# ---------------------------------------------------------------
# ETAPA 5 — frente do lote
# ---------------------------------------------------------------

#  reorganiza os lados do lote para o memorial começar pela frente
def ordenar_pela_frente(lados):
    total = len(lados)

    # monta a lista de rua por lado
    ruas = []
    for lado in lados:
        rua = None
        for tipo, nome in lado["confrontantes"]:
            if tipo == "Rua":
                rua = nome or "?"
        ruas.append(rua)

    # procura a frente
    # lados seguidos com a mesma rua formam um grupo, o menor grupo é a frente
    inicio_frente = None
    comprimento_frente = None
    for i in range(total):
        if ruas[i] is None or ruas[i - 1] == ruas[i]:
            continue
        comprimento = 0
        j = i
        while ruas[j] == ruas[i]:
            comprimento = comprimento + lados[j]["comprimento"]
            j = j + 1
            if j == total:
                j = 0
        if comprimento_frente is None or comprimento < comprimento_frente:
            inicio_frente = i
            comprimento_frente = comprimento

    # lote sem nenhuma rua fica como estava
    if inicio_frente is None:
        return lados

    # gira a lista para começar na frente e renomeia os vértices a partir dela (P0PP, P01, P02...)
    novos = lados[inicio_frente:] + lados[:inicio_frente]
    for i in range(len(novos)):
        novos[i]["vertice"] = nome_do_vertice(i)
    novos[0]["frente"] = True
    return novos


# ---------------------------------------------------------------
# ETAPA 6 — esquina
# ---------------------------------------------------------------


# quanto o contorno vira (em graus) ao passar pelo ponto (se: 0 = segue reto)
def virada(anterior, ponto, proximo):
    diferenca = abs(anterior.azimuth(ponto) - ponto.azimuth(proximo))
    if diferenca > 180:
        diferenca = 360 - diferenca
    return diferenca

# mantém uma posição na borda entre 0 e o perímetro (passou do fim, volta ao começo)
def posicao_na_borda(posicao, perimetro):
    if posicao < 0:
        return posicao + perimetro
    if posicao > perimetro:
        return posicao - perimetro
    return posicao

# verifica se o canto é uma ponta da quadra
def canto_para_fora(borda, quadra, posicao, perimetro):

    # pega um ponto um pouco antes e outro um pouco depois do canto e acha o meio entre eles
    antes = borda.interpolate(posicao_na_borda(posicao - PASSO_CANTO, perimetro)).asPoint()
    depois = borda.interpolate(posicao_na_borda(posicao + PASSO_CANTO, perimetro)).asPoint()
    meio = QgsPointXY((antes.x() + depois.x()) / 2, (antes.y() + depois.y()) / 2)

    # se o meio cai dentro da quadra, o canto é uma ponta
    return quadra.contains(QgsGeometry.fromPointXY(meio))

# anda pela borda da quadra a partir de um ponto até achar a esquina
def andar_pela_borda(partida, sentido, quadra, terrenos, ruas):
    vertices = vertices_do_poligono(quadra)
    total = len(vertices)
    borda = QgsGeometry.fromPolylineXY(vertices + [vertices[0]])
    perimetro = borda.length()

    # calcula a distância da partida até cada vértice da quadra
    caminho = []
    for i in range(total):
        posicao = borda.distanceToVertex(i)
        if sentido == "horario":
            distancia = posicao_na_borda(posicao - partida, perimetro)
        else:
            distancia = posicao_na_borda(partida - posicao, perimetro)
        if distancia > perimetro - NA_ESQUINA:
            distancia = 0.0
        caminho.append((distancia, i))
    caminho.sort()

    # em cada vértice decide:
    # virou menos que a virada mínima -> é curva da rua
    # canto para dentro ou terreno de forand da quadra depois do canto -> não é esquina
    # senão -> achou a esquina
    for distancia, i in caminho:
        anterior = vertices[i - 1]
        ponto = vertices[i]
        if i == total - 1:
            proximo = vertices[0]
        else:
            proximo = vertices[i + 1]

        if virada(anterior, ponto, proximo) < VIRADA_MINIMA:
            continue
        if not canto_para_fora(borda, quadra, borda.distanceToVertex(i), perimetro):
            return None
        if sentido == "horario":
            lado_seguinte = QgsGeometry.fromPolylineXY([ponto, proximo])
        else:
            lado_seguinte = QgsGeometry.fromPolylineXY([anterior, ponto])
        for terreno in terrenos:
            if contato(lado_seguinte, terreno) >= CONTATO_MINIMO:
                return None
        return {"distancia": distancia, "rua": rua_que_encosta(lado_seguinte, ruas)}
    return None

# calcula a distância da frente do lote até a esquina mais próxima
def calcular_esquina(lote, terrenos, ruas):

    # acha onde as duas pontas da frente (P0PP e P01) ficam na borda da quadra
    quadra = lote["geometria_quadra"]
    frente = lote["lados"][0]
    vertices = vertices_do_poligono(quadra)
    borda = QgsGeometry.fromPolylineXY(vertices + [vertices[0]])
    inicio = borda.lineLocatePoint(QgsGeometry.fromPointXY(frente["de"]))
    fim = borda.lineLocatePoint(QgsGeometry.fromPointXY(frente["para"]))

    # anda para os dois lados: horário a partir do P01 e anti-horário a partir do P0PP
    esquina_1 = andar_pela_borda(fim, "horario", quadra, terrenos, ruas)
    esquina_2 = andar_pela_borda(inicio, "anti-horario", quadra, terrenos, ruas)

    # fica com a esquina mais perto das duas
    if esquina_1 is None:
        esquina = esquina_2
    elif esquina_2 is None:
        esquina = esquina_1
    elif esquina_2["distancia"] < esquina_1["distancia"]:
        esquina = esquina_2
    else:
        esquina = esquina_1

    # se a distância é quase zero, o lote fica na esquina
    if esquina is not None and esquina["distancia"] < NA_ESQUINA:
        esquina["distancia"] = 0.0
    return esquina


# ---------------------------------------------------------------
# ETAPA 7 — funções de área, forma, etc
# ---------------------------------------------------------------

# extrai o código da rua do nome
def codigo_da_rua(nome):
    if not nome or "(" not in nome:
        return ""
    return nome[nome.rfind("(") + 1:nome.rfind(")")].replace(" ", "").upper()


# completa os dados do lote: área, forma e dados do cadastro
def completar_dados(lote):
    cadastro = lote["cadastro"]

    # Calculo de área pelo Qgis e classificação do lote: lote com 4 lados é regular, os outros são irregulares
    lote["area"] = lote["geometria"].area()
    if len(lote["lados"]) == 4:
        lote["forma"] = "regular"
    else:
        lote["forma"] = "irregular"

    # número predial do cadastro (só com o GeoCuritiba); se for de outra rua, não é usado
    numero = cadastro.get("numero_predial")
    rua_frente = codigo_da_rua(rua_do_lado(lote["lados"][0]))
    rua_cadastro = (cadastro.get("cod_logradouro") or "").replace(" ", "").upper()
    if numero and rua_frente and rua_cadastro and rua_frente != rua_cadastro:
        numero = None

    # guarda os dados do cadastro no lote
    lote["numero_predial"] = str(numero) if numero else None
    lote["lado_rua"] = geocuritiba.lado_da_rua(numero)
    lote["indicacao_fiscal"] = geocuritiba.formatar_if(cadastro.get("indicacao_fiscal"))
    lote["planta_cadastro"] = cadastro.get("nome_planta")
