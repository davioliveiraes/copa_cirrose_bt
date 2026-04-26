import json

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_POST

from .models import Dupla, Jogo, Torneio
from .services import (
    calcular_classificacao,
    calcular_mata_mata,
    gerar_jogos_round_robin,
)


def home(request):
    """Roteia para setup ou placar conforme status do torneio."""
    torneio = Torneio.get_atual()
    if torneio.status == Torneio.STATUS_SETUP:
        return setup(request)
    return placar(request)


def setup(request):
    """Tela de cadastro de duplas."""
    torneio = Torneio.get_atual()
    duplas = torneio.duplas.all()
    total_duplas = duplas.count()
    return render(request, 'torneio/setup.html', {
        'torneio': torneio,
        'duplas': duplas,
        'pode_iniciar': total_duplas >= 4,
        'jogos_previstos': total_duplas * (total_duplas - 1) // 2,
    })


@require_POST
def adicionar_dupla(request):
    """POST com 'nome' -> cria dupla. Retorna JSON."""
    torneio = Torneio.get_atual()
    if torneio.status != Torneio.STATUS_SETUP:
        return _json_error('Nao e possivel adicionar duplas com o torneio em andamento.')

    data = _request_data(request)
    nome = data.get('nome', '').strip()
    erro = _validar_nome_dupla(nome)
    if erro:
        return _json_error(erro)

    ultima = torneio.duplas.order_by('-ordem').first()
    dupla = Dupla.objects.create(
        torneio=torneio,
        nome=nome,
        ordem=(ultima.ordem + 1) if ultima else 1,
    )

    duplas = torneio.duplas.all()
    return JsonResponse({
        'ok': True,
        'dupla': _serializar_dupla(dupla),
        'lista_html': _render_lista_duplas(request, torneio),
        'pode_iniciar': duplas.count() >= 4,
    })


@require_POST
def remover_dupla(request, dupla_id):
    """Remove dupla, somente se o torneio estiver em SETUP."""
    torneio = Torneio.get_atual()
    if torneio.status != Torneio.STATUS_SETUP:
        return _json_error('Nao e possivel remover duplas com o torneio em andamento.')

    dupla = get_object_or_404(Dupla, pk=dupla_id, torneio=torneio)
    dupla.delete()

    duplas = torneio.duplas.all()
    return JsonResponse({
        'ok': True,
        'lista_html': _render_lista_duplas(request, torneio),
        'pode_iniciar': duplas.count() >= 4,
    })


@require_POST
@transaction.atomic
def iniciar_torneio(request):
    """Gera jogos round-robin, cria mata-mata vazio, muda status."""
    torneio = Torneio.get_atual()
    if torneio.status != Torneio.STATUS_SETUP:
        return redirect('torneio:placar')

    if torneio.duplas.count() < 4:
        return _json_error('Cadastre pelo menos 4 duplas para iniciar o torneio.')

    torneio.jogos.all().delete()
    gerar_jogos_round_robin(torneio)
    torneio.status = Torneio.STATUS_ANDAMENTO
    torneio.iniciado_em = timezone.now()
    torneio.save(update_fields=['status', 'iniciado_em'])
    return redirect('torneio:placar')


def placar(request):
    """Tela do torneio em andamento."""
    torneio = Torneio.get_atual()
    if torneio.status != Torneio.STATUS_ANDAMENTO:
        return redirect('torneio:home')

    jogos_grupos = torneio.jogos.filter(fase=Jogo.FASE_GRUPOS)
    classificacao = calcular_classificacao(torneio)
    mata_mata = calcular_mata_mata(torneio)

    return render(request, 'torneio/placar.html', {
        'torneio': torneio,
        'jogos_grupos': jogos_grupos,
        'classificacao': classificacao,
        'mata_mata': mata_mata,
    })


@require_POST
def salvar_placar(request, jogo_id):
    """POST com sets_a, sets_b -> salva placar e retorna JSON atualizado."""
    torneio = Torneio.get_atual()
    if torneio.status != Torneio.STATUS_ANDAMENTO:
        return _json_error('O torneio ainda nao esta em andamento.')

    jogo = get_object_or_404(Jogo, pk=jogo_id, torneio=torneio)
    if not jogo.dupla_a_id or not jogo.dupla_b_id:
        return _json_error('Este jogo ainda nao possui duplas definidas.')

    data = _request_data(request)
    sets_a, erro = _parse_set(data.get('sets_a'), 'sets_a')
    if erro:
        return _json_error(erro)

    sets_b, erro = _parse_set(data.get('sets_b'), 'sets_b')
    if erro:
        return _json_error(erro)

    erro = _validar_placar(sets_a, sets_b)
    if erro:
        return _json_error(erro)

    jogo.sets_a = sets_a
    jogo.sets_b = sets_b
    jogo.save(update_fields=['sets_a', 'sets_b'])

    return _json_estado_torneio(torneio)


@require_POST
def limpar_jogo(request, jogo_id):
    """Zera placar de um jogo especifico."""
    torneio = Torneio.get_atual()
    if torneio.status != Torneio.STATUS_ANDAMENTO:
        return _json_error('O torneio ainda nao esta em andamento.')

    jogo = get_object_or_404(Jogo, pk=jogo_id, torneio=torneio)
    jogo.sets_a = None
    jogo.sets_b = None
    jogo.save(update_fields=['sets_a', 'sets_b'])

    return _json_estado_torneio(torneio)


@require_POST
@transaction.atomic
def reiniciar_torneio(request):
    """Apaga duplas e jogos, voltando para SETUP."""
    torneio = Torneio.get_atual()
    torneio.jogos.all().delete()
    torneio.duplas.all().delete()
    torneio.status = Torneio.STATUS_SETUP
    torneio.iniciado_em = None
    torneio.save(update_fields=['status', 'iniciado_em'])

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'ok': True, 'redirect_url': reverse('torneio:home')})
    return redirect('torneio:home')


def exportar(request):
    """Retorna texto formatado para colar no WhatsApp."""
    torneio = Torneio.get_atual()
    classificacao = calcular_classificacao(torneio)
    mata_mata = None
    if torneio.status == Torneio.STATUS_ANDAMENTO:
        mata_mata = calcular_mata_mata(torneio)

    linhas = [f'*{torneio.nome}*', '']
    if classificacao:
        linhas.append('*Classificacao*')
        for posicao, item in enumerate(classificacao, start=1):
            linhas.append(
                f'{posicao}. {item["nome"]} - {item["pts"]} pts '
                f'({item["v"]}V/{item["d"]}D, saldo {item["ss"]})'
            )

    jogos_grupos = torneio.jogos.filter(fase=Jogo.FASE_GRUPOS).select_related(
        'dupla_a',
        'dupla_b',
    )
    if jogos_grupos:
        linhas.extend(['', '*Jogos da fase de grupos*'])
        for jogo in jogos_grupos:
            placar = _formatar_placar(jogo)
            linhas.append(f'{jogo.numero}. {jogo.dupla_a} x {jogo.dupla_b}: {placar}')

    if mata_mata:
        linhas.extend(['', '*Mata-mata*'])
        for rotulo, chave in [('SF1', 'sf1'), ('SF2', 'sf2'), ('Final', 'final')]:
            linhas.append(f'{rotulo}: {_formatar_jogo_dict(mata_mata[chave])}')

        if mata_mata['campeao']:
            linhas.extend([
                '',
                f'Campeao: {mata_mata["campeao"].nome}',
                f'Vice: {mata_mata["vice"].nome}',
            ])

    return HttpResponse('\n'.join(linhas), content_type='text/plain; charset=utf-8')


def _json_estado_torneio(torneio):
    return JsonResponse({
        'ok': True,
        'classificacao': calcular_classificacao(torneio),
        'mata_mata': _serializar_mata_mata(calcular_mata_mata(torneio)),
    })


def _render_lista_duplas(request, torneio):
    return render_to_string(
        'torneio/_lista_duplas.html',
        {'torneio': torneio, 'duplas': torneio.duplas.all()},
        request=request,
    )


def _parse_set(valor, campo):
    if isinstance(valor, bool):
        return None, f'O campo {campo} deve ser um numero inteiro.'

    try:
        sets = int(valor)
    except (TypeError, ValueError):
        return None, f'O campo {campo} deve ser um numero inteiro.'

    if sets < 0 or sets > 3:
        return None, f'O campo {campo} deve estar entre 0 e 3.'

    return sets, None


def _request_data(request):
    if request.content_type == 'application/json':
        try:
            return json.loads(request.body.decode('utf-8') or '{}')
        except json.JSONDecodeError:
            return {}
    return request.POST


def _validar_nome_dupla(nome):
    if not nome:
        return 'Informe o nome da dupla.'
    if len(nome) > 100:
        return 'O nome da dupla deve ter no maximo 100 caracteres.'
    if strip_tags(nome) != nome:
        return 'O nome da dupla nao pode conter HTML.'
    return None


def _validar_placar(sets_a, sets_b):
    if sets_a == sets_b:
        return 'O placar nao pode terminar empatado.'
    if 3 not in [sets_a, sets_b]:
        return 'Uma dupla precisa vencer 3 sets.'
    return None


def _json_error(message, status=400):
    return JsonResponse({'ok': False, 'error': message}, status=status)


def _serializar_dupla(dupla):
    if dupla is None:
        return None
    return {'id': dupla.id, 'nome': dupla.nome}


def _serializar_jogo_dict(jogo):
    return {
        'id': jogo['id'],
        'fase': jogo['fase'],
        'dupla_a': _serializar_dupla(jogo['dupla_a']),
        'dupla_b': _serializar_dupla(jogo['dupla_b']),
        'sets_a': jogo['sets_a'],
        'sets_b': jogo['sets_b'],
        'vencedor': _serializar_dupla(jogo['vencedor']),
    }


def _serializar_mata_mata(mata_mata):
    return {
        'grupos_completo': mata_mata['grupos_completo'],
        'sf1': _serializar_jogo_dict(mata_mata['sf1']),
        'sf2': _serializar_jogo_dict(mata_mata['sf2']),
        'final': _serializar_jogo_dict(mata_mata['final']),
        'campeao': _serializar_dupla(mata_mata['campeao']),
        'vice': _serializar_dupla(mata_mata['vice']),
    }


def _formatar_placar(jogo):
    if not jogo.preenchido:
        return 'pendente'
    return f'{jogo.sets_a}x{jogo.sets_b}'


def _formatar_jogo_dict(jogo):
    dupla_a = jogo['dupla_a'].nome if jogo['dupla_a'] else 'A definir'
    dupla_b = jogo['dupla_b'].nome if jogo['dupla_b'] else 'A definir'
    sets_a = jogo['sets_a']
    sets_b = jogo['sets_b']
    placar = 'pendente' if sets_a is None or sets_b is None else f'{sets_a}x{sets_b}'
    return f'{dupla_a} x {dupla_b}: {placar}'
