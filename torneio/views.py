import json
from io import BytesIO
from xml.sax.saxutils import escape

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_POST
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

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
        return _json_error('Não é possível adicionar duplas com o torneio em andamento.')

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
        return _json_error('Não é possível remover duplas com o torneio em andamento.')

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
        return _json_error('O torneio ainda não está em andamento.')

    jogo = get_object_or_404(Jogo, pk=jogo_id, torneio=torneio)
    if not jogo.dupla_a_id or not jogo.dupla_b_id:
        return _json_error('Este jogo ainda não possui duplas definidas.')

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
        return _json_error('O torneio ainda não está em andamento.')

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
    """Gera um relatório PDF com o estado atual do torneio."""
    torneio = Torneio.get_atual()
    classificacao = calcular_classificacao(torneio)
    mata_mata = None
    if torneio.status == Torneio.STATUS_ANDAMENTO:
        mata_mata = calcular_mata_mata(torneio)

    jogos_grupos = torneio.jogos.filter(fase=Jogo.FASE_GRUPOS).select_related(
        'dupla_a',
        'dupla_b',
    )
    pdf = _gerar_relatorio_pdf(torneio, classificacao, jogos_grupos, mata_mata)
    response = HttpResponse(pdf, content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="copa-cirrose-bt-relatorio.pdf"'
    return response


def _json_estado_torneio(torneio):
    return JsonResponse({
        'ok': True,
        'classificacao': calcular_classificacao(torneio),
        'mata_mata': _serializar_mata_mata(calcular_mata_mata(torneio)),
    })


def _gerar_relatorio_pdf(torneio, classificacao, jogos_grupos, mata_mata):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title=f'Relatório - {torneio.nome}',
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='ReportTitle',
        parent=styles['Title'],
        fontName='Helvetica-Bold',
        fontSize=22,
        leading=26,
        textColor=colors.HexColor('#0b0f14'),
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name='SectionTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#0f4c81'),
        spaceBefore=14,
        spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name='SmallText',
        parent=styles['BodyText'],
        fontSize=9,
        leading=12,
        textColor=colors.HexColor('#4b5563'),
    ))
    styles.add(ParagraphStyle(
        name='TableText',
        parent=styles['BodyText'],
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#0b0f14'),
    ))
    styles.add(ParagraphStyle(
        name='TableHeader',
        parent=styles['TableText'],
        fontName='Helvetica-Bold',
        textColor=colors.white,
    ))

    story = [
        Paragraph(_pdf_text(torneio.nome), styles['ReportTitle']),
        Paragraph(
            'O troféu é da glória, mas o fígado é de todos.',
            styles['SmallText'],
        ),
        Paragraph(_pdf_meta_torneio(torneio), styles['SmallText']),
        Spacer(1, 8),
    ]

    story.append(Paragraph('Resumo rápido', styles['SectionTitle']))
    story.append(_pdf_table([
        ['Abertura', 'Dose coletiva antes do primeiro jogo.'],
        ['Confronto', 'Uma dose por jogador ao entrar em quadra.'],
        ['3x0', 'Perdedor 3 doses por jogador. Vencedor 1 dose por jogador.'],
        ['3x1 ou 3x2', 'Perdedor 2 doses por jogador. Vencedor 1 dose por jogador.'],
    ], [4.0 * cm, 12.5 * cm], styles))

    story.append(Paragraph('Classificação', styles['SectionTitle']))
    if classificacao:
        linhas = [['Pos', 'Dupla', 'J', 'V', 'D', 'SF', 'SC', 'SS', 'Pts']]
        for posicao, item in enumerate(classificacao, start=1):
            linhas.append([
                str(posicao),
                item['nome'],
                str(item['j']),
                str(item['v']),
                str(item['d']),
                str(item['sf']),
                str(item['sc']),
                str(item['ss']),
                str(item['pts']),
            ])
        story.append(_pdf_table(
            linhas,
            [1.1 * cm, 6.2 * cm, 1.1 * cm, 1.1 * cm, 1.1 * cm,
             1.2 * cm, 1.2 * cm, 1.2 * cm, 1.4 * cm],
            styles,
        ))
    else:
        story.append(Paragraph('Nenhuma classificação disponível.', styles['SmallText']))

    story.append(Paragraph('Jogos da fase de grupos', styles['SectionTitle']))
    if jogos_grupos:
        linhas = [['#', 'Dupla A', 'Placar', 'Dupla B']]
        for jogo in jogos_grupos:
            linhas.append([
                str(jogo.numero),
                jogo.dupla_a.nome,
                _formatar_placar(jogo),
                jogo.dupla_b.nome,
            ])
        story.append(_pdf_table(
            linhas,
            [1.1 * cm, 6.2 * cm, 2.0 * cm, 6.2 * cm],
            styles,
        ))
    else:
        story.append(Paragraph('Nenhum jogo gerado ainda.', styles['SmallText']))

    if mata_mata:
        story.append(Paragraph('Mata-mata', styles['SectionTitle']))
        linhas = [['Fase', 'Confronto', 'Vencedor']]
        for rotulo, chave in [('SF1', 'sf1'), ('SF2', 'sf2'), ('Final', 'final')]:
            jogo = mata_mata[chave]
            vencedor = jogo['vencedor'].nome if jogo['vencedor'] else 'Pendente'
            linhas.append([
                rotulo,
                _formatar_jogo_dict(jogo),
                vencedor,
            ])
        story.append(_pdf_table(
            linhas,
            [1.8 * cm, 10.8 * cm, 3.9 * cm],
            styles,
        ))

        if mata_mata['campeao']:
            story.append(Paragraph('Resultado final', styles['SectionTitle']))
            story.append(_pdf_table([
                ['Campeão', mata_mata['campeao'].nome],
                ['Vice', mata_mata['vice'].nome],
            ], [4.0 * cm, 12.5 * cm], styles))

    doc.build(story, onFirstPage=_pdf_footer, onLaterPages=_pdf_footer)
    return buffer.getvalue()


def _pdf_meta_torneio(torneio):
    gerado_em = timezone.localtime().strftime('%d/%m/%Y %H:%M')
    iniciado = (
        timezone.localtime(torneio.iniciado_em).strftime('%d/%m/%Y %H:%M')
        if torneio.iniciado_em
        else 'não iniciado'
    )
    return (
        f'Status: {torneio.get_status_display()} | '
        f'Início: {iniciado} | '
        f'Gerado em: {gerado_em}'
    )


def _pdf_text(value):
    return escape(str(value))


def _pdf_table(rows, col_widths, styles):
    table_rows = []
    for row_index, row in enumerate(rows):
        style_name = 'TableHeader' if row_index == 0 else 'TableText'
        table_rows.append([
            Paragraph(_pdf_text(cell), styles[style_name])
            for cell in row
        ])

    table = Table(table_rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f4c81')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#d9e1ea')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f4f7fb')]),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    return table


def _pdf_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#7b8794'))
    canvas.drawString(1.5 * cm, 1.0 * cm, 'Copa Cirrose BT')
    canvas.drawRightString(19.5 * cm, 1.0 * cm, f'Página {doc.page}')
    canvas.restoreState()


def _render_lista_duplas(request, torneio):
    return render_to_string(
        'torneio/_lista_duplas.html',
        {'torneio': torneio, 'duplas': torneio.duplas.all()},
        request=request,
    )


def _parse_set(valor, campo):
    if isinstance(valor, bool):
        return None, f'O campo {campo} deve ser um número inteiro.'

    try:
        sets = int(valor)
    except (TypeError, ValueError):
        return None, f'O campo {campo} deve ser um número inteiro.'

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
        return 'O nome da dupla deve ter no máximo 100 caracteres.'
    if strip_tags(nome) != nome:
        return 'O nome da dupla não pode conter HTML.'
    return None


def _validar_placar(sets_a, sets_b):
    if sets_a == sets_b:
        return 'O placar não pode terminar empatado.'
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
