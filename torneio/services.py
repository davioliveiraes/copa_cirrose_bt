from collections import defaultdict

from django.db import transaction

from .models import Jogo


@transaction.atomic
def gerar_jogos_round_robin(torneio):
    """
    Gera todos os jogos da fase de grupos usando Round-Robin (Circle Method).
    Garante que cada dupla joga contra todas as outras exatamente 1 vez.
    Distribui os jogos em rodadas para reduzir partidas seguidas.
    """
    duplas = list(torneio.duplas.all())
    n = len(duplas)

    if n % 2 != 0:
        duplas.append(None)
        n += 1

    rodadas = []
    fixa = duplas[0]
    rotativa = duplas[1:]

    for _ in range(n - 1):
        rodada = [(fixa, rotativa[0])]
        for i in range(1, n // 2):
            rodada.append((rotativa[i], rotativa[-i]))
        rodadas.append(rodada)
        rotativa = [rotativa[-1]] + rotativa[:-1]

    numero = 1
    for rodada in rodadas:
        for dupla_a, dupla_b in rodada:
            if dupla_a is None or dupla_b is None:
                continue
            Jogo.objects.create(
                torneio=torneio,
                numero=numero,
                fase=Jogo.FASE_GRUPOS,
                dupla_a=dupla_a,
                dupla_b=dupla_b,
            )
            numero += 1

    for fase in [Jogo.FASE_SF1, Jogo.FASE_SF2, Jogo.FASE_FINAL]:
        Jogo.objects.create(torneio=torneio, numero=1, fase=fase)


def calcular_classificacao(torneio):
    stats = {
        dupla.id: {
            'id': dupla.id,
            'nome': dupla.nome,
            'j': 0,
            'v': 0,
            'd': 0,
            'sf': 0,
            'sc': 0,
            'ss': 0,
            'pts': 0,
            '_ordem': dupla.ordem,
        }
        for dupla in torneio.duplas.all()
    }

    jogos = (
        torneio.jogos
        .filter(
            fase=Jogo.FASE_GRUPOS,
            dupla_a__isnull=False,
            dupla_b__isnull=False,
            sets_a__isnull=False,
            sets_b__isnull=False,
        )
        .select_related('dupla_a', 'dupla_b')
    )

    for jogo in jogos:
        stat_a = stats[jogo.dupla_a_id]
        stat_b = stats[jogo.dupla_b_id]

        stat_a['j'] += 1
        stat_b['j'] += 1
        stat_a['sf'] += jogo.sets_a
        stat_a['sc'] += jogo.sets_b
        stat_b['sf'] += jogo.sets_b
        stat_b['sc'] += jogo.sets_a

        if jogo.sets_a > jogo.sets_b:
            stat_a['v'] += 1
            stat_a['pts'] += 3
            stat_b['d'] += 1
        elif jogo.sets_b > jogo.sets_a:
            stat_b['v'] += 1
            stat_b['pts'] += 3
            stat_a['d'] += 1

    for item in stats.values():
        item['ss'] = item['sf'] - item['sc']

    grupos_por_vitorias = defaultdict(list)
    for item in stats.values():
        grupos_por_vitorias[item['v']].append(item)

    classificacao = []
    for vitorias in sorted(grupos_por_vitorias.keys(), reverse=True):
        grupo = grupos_por_vitorias[vitorias]
        if len(grupo) == 2:
            classificacao.extend(_ordenar_duas_por_confronto_direto(torneio, grupo))
        else:
            classificacao.extend(_ordenar_por_sets(grupo))

    for item in classificacao:
        item.pop('_ordem', None)

    return classificacao


def calcular_mata_mata(torneio):
    sf1 = _get_jogo_mata_mata(torneio, Jogo.FASE_SF1)
    sf2 = _get_jogo_mata_mata(torneio, Jogo.FASE_SF2)
    final = _get_jogo_mata_mata(torneio, Jogo.FASE_FINAL)

    jogos_grupos = list(torneio.jogos.filter(fase=Jogo.FASE_GRUPOS))
    grupos_completo = bool(jogos_grupos) and all(
        jogo.preenchido for jogo in jogos_grupos
    )

    if grupos_completo:
        classificacao = calcular_classificacao(torneio)
        duplas_por_id = {dupla.id: dupla for dupla in torneio.duplas.all()}

        if len(classificacao) >= 4:
            _atualizar_participantes(
                sf1,
                duplas_por_id[classificacao[0]['id']],
                duplas_por_id[classificacao[3]['id']],
            )
            _atualizar_participantes(
                sf2,
                duplas_por_id[classificacao[1]['id']],
                duplas_por_id[classificacao[2]['id']],
            )
    else:
        _limpar_jogo(sf1)
        _limpar_jogo(sf2)

    if sf1.vencedor and sf2.vencedor:
        _atualizar_participantes(final, sf1.vencedor, sf2.vencedor)
    else:
        _limpar_jogo(final)

    campeao = final.vencedor
    vice = None
    if campeao:
        vice = final.dupla_b if campeao == final.dupla_a else final.dupla_a

    return {
        'grupos_completo': grupos_completo,
        'sf1': _jogo_para_dict(sf1),
        'sf2': _jogo_para_dict(sf2),
        'final': _jogo_para_dict(final),
        'campeao': campeao,
        'vice': vice,
    }


def _ordenar_por_sets(grupo):
    return sorted(
        grupo,
        key=lambda item: (-item['ss'], -item['sf'], item['_ordem']),
    )


def _ordenar_duas_por_confronto_direto(torneio, grupo):
    primeira, segunda = grupo
    jogo = (
        torneio.jogos
        .filter(
            fase=Jogo.FASE_GRUPOS,
            dupla_a_id__in=[primeira['id'], segunda['id']],
            dupla_b_id__in=[primeira['id'], segunda['id']],
            sets_a__isnull=False,
            sets_b__isnull=False,
        )
        .first()
    )

    if jogo and jogo.vencedor:
        if jogo.vencedor.id == primeira['id']:
            return [primeira, segunda]
        return [segunda, primeira]

    return _ordenar_por_sets(grupo)


def _get_jogo_mata_mata(torneio, fase):
    jogo, _ = Jogo.objects.get_or_create(
        torneio=torneio,
        fase=fase,
        numero=1,
    )
    return jogo


def _atualizar_participantes(jogo, dupla_a, dupla_b):
    participantes_mudaram = (
        jogo.dupla_a_id != dupla_a.id or jogo.dupla_b_id != dupla_b.id
    )
    if not participantes_mudaram:
        return

    jogo.dupla_a = dupla_a
    jogo.dupla_b = dupla_b
    jogo.sets_a = None
    jogo.sets_b = None
    jogo.save(update_fields=['dupla_a', 'dupla_b', 'sets_a', 'sets_b'])


def _limpar_jogo(jogo):
    if (
        jogo.dupla_a_id is None
        and jogo.dupla_b_id is None
        and jogo.sets_a is None
        and jogo.sets_b is None
    ):
        return

    jogo.dupla_a = None
    jogo.dupla_b = None
    jogo.sets_a = None
    jogo.sets_b = None
    jogo.save(update_fields=['dupla_a', 'dupla_b', 'sets_a', 'sets_b'])


def _jogo_para_dict(jogo):
    return {
        'id': jogo.id,
        'fase': jogo.fase,
        'dupla_a': jogo.dupla_a,
        'dupla_b': jogo.dupla_b,
        'sets_a': jogo.sets_a,
        'sets_b': jogo.sets_b,
        'vencedor': jogo.vencedor,
    }
