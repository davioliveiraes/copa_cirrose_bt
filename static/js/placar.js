const feedback = document.querySelector('#placar-feedback');
const classificacaoBody = document.querySelector('#classificacao-body');
const mataMataGrid = document.querySelector('#mata-mata-grid');
const exportButton = document.querySelector('#btn-exportar');
const reiniciarForm = document.querySelector('#form-reiniciar');
const debounceTimers = new Map();

document.addEventListener('input', (event) => {
    const input = event.target.closest('input[data-lado]');
    if (!input) {
        return;
    }

    const jogo = input.closest('[data-jogo-id]');
    if (!jogo) {
        return;
    }

    clearTimeout(debounceTimers.get(jogo.dataset.jogoId));
    debounceTimers.set(jogo.dataset.jogoId, setTimeout(() => salvarJogo(jogo), 300));
});

document.addEventListener('click', async (event) => {
    const button = event.target.closest('[data-clear]');
    if (!button) {
        return;
    }

    try {
        const data = await postJson(appUrl(`/jogos/${button.dataset.clear}/limpar/`));
        limparInputsDoJogo(button.dataset.clear);
        aplicarEstado(data);
        showFeedback('Placar limpo.');
    } catch (error) {
        showFeedback(error.message, true);
    }
});

exportButton?.addEventListener('click', async () => {
    window.location.href = exportButton.dataset.exportUrl;
    showFeedback('Gerando relatório em PDF.');
});

reiniciarForm?.addEventListener('submit', async (event) => {
    event.preventDefault();

    const primeira = window.confirm('Reiniciar o torneio e apagar todas as duplas, jogos e placares?');
    if (!primeira) {
        return;
    }

    const segunda = window.confirm('Confirmar reinício definitivo? Esta ação não pode ser desfeita.');
    if (!segunda) {
        return;
    }

    const response = await fetch(reiniciarForm.action, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCsrfToken(),
            'X-Requested-With': 'XMLHttpRequest',
        },
    });

    if (response.ok) {
        const data = await response.json();
        window.location.href = data.redirect_url || '/';
    }
});

async function salvarJogo(jogo) {
    const jogoId = jogo.dataset.jogoId;
    const inputA = jogo.querySelector('[data-lado="a"]');
    const inputB = jogo.querySelector('[data-lado="b"]');
    const setsA = inputA?.value.trim() ?? '';
    const setsB = inputB?.value.trim() ?? '';

    if (!setsA || !setsB) {
        return;
    }

    if (!isSetValido(setsA) || !isSetValido(setsB)) {
        showFeedback('Use apenas números inteiros de 0 a 3.', true);
        return;
    }

    try {
        const data = await postJson(appUrl(`/jogos/${jogoId}/salvar/`), {
            sets_a: Number(setsA),
            sets_b: Number(setsB),
        });
        jogo.classList.add('preenchido');
        aplicarEstado(data);
        showFeedback('Placar salvo.');
    } catch (error) {
        showFeedback(error.message, true);
    }
}

async function postJson(url, body = null) {
    const response = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            'X-Requested-With': 'XMLHttpRequest',
        },
        body: body ? JSON.stringify(body) : null,
    });
    const data = await response.json();
    if (!response.ok || !data.ok) {
        throw new Error(data.error || 'Não foi possível concluir a ação.');
    }
    return data;
}

function aplicarEstado(data) {
    renderClassificacao(data.classificacao || []);
    renderMataMata(data.mata_mata);
}

function renderClassificacao(classificacao) {
    if (!classificacaoBody) {
        return;
    }

    classificacaoBody.innerHTML = classificacao.map((dupla, index) => {
        const pos = index + 1;
        const classificado = pos <= 4;
        return `
            <tr class="${classificado ? 'classificado' : ''}">
                <td>${String(pos).padStart(2, '0')} ${classificado ? '<span class="check">✓</span>' : ''}</td>
                <td>${escapeHtml(dupla.nome)}</td>
                <td>${dupla.j}</td>
                <td>${dupla.v}</td>
                <td>${dupla.d}</td>
                <td>${dupla.sf}</td>
                <td>${dupla.sc}</td>
                <td>${dupla.ss}</td>
                <td><strong>${dupla.pts}</strong></td>
            </tr>
        `;
    }).join('');
}

function renderMataMata(mataMata) {
    if (!mataMataGrid || !mataMata) {
        return;
    }

    mataMataGrid.innerHTML = `
        <div class="knockout-column">
            ${renderJogoMataMata('SF1 · 1º x 4º', mataMata.sf1, 'aguardando grupos')}
            ${renderJogoMataMata('SF2 · 2º x 3º', mataMata.sf2, 'aguardando grupos')}
        </div>
        <div class="knockout-column final-column">
            ${renderJogoMataMata('Final', mataMata.final, 'aguardando SF1 e SF2')}
        </div>
        <div class="knockout-column winners-column">
            <article class="winner-card champion">
                <span>Campeão</span>
                <strong id="campeao-nome">${mataMata.campeao ? escapeHtml(mataMata.campeao.nome) : 'aguardando final'}</strong>
            </article>
            <article class="winner-card">
                <span>Vice</span>
                <strong id="vice-nome">${mataMata.vice ? escapeHtml(mataMata.vice.nome) : 'aguardando final'}</strong>
            </article>
        </div>
    `;
}

function renderJogoMataMata(titulo, jogo, aguardando) {
    const preenchido = jogo?.vencedor ? 'preenchido' : '';
    if (!jogo?.dupla_a || !jogo?.dupla_b) {
        return `
            <article class="match-card ${preenchido}" data-jogo-id="${jogo?.id || ''}">
                <div class="match-title">${escapeHtml(titulo)}</div>
                <p class="pending-text">${escapeHtml(aguardando)}</p>
            </article>
        `;
    }

    return `
        <article class="match-card ${preenchido}" data-jogo-id="${jogo.id}">
            <div class="match-title">${escapeHtml(titulo)}</div>
            <div class="match-row">
                <span>${escapeHtml(jogo.dupla_a.nome)}</span>
                <input type="number" min="0" max="3" data-lado="a" value="${valueOrEmpty(jogo.sets_a)}" aria-label="Sets ${escapeHtml(jogo.dupla_a.nome)}">
            </div>
            <div class="match-row">
                <span>${escapeHtml(jogo.dupla_b.nome)}</span>
                <input type="number" min="0" max="3" data-lado="b" value="${valueOrEmpty(jogo.sets_b)}" aria-label="Sets ${escapeHtml(jogo.dupla_b.nome)}">
            </div>
            <button class="text-button" data-clear="${jogo.id}" type="button">limpar</button>
        </article>
    `;
}

function limparInputsDoJogo(jogoId) {
    const jogo = document.querySelector(`[data-jogo-id="${jogoId}"]`);
    if (!jogo) {
        return;
    }
    jogo.querySelectorAll('input[data-lado]').forEach((input) => {
        input.value = '';
    });
    jogo.classList.remove('preenchido');
}

function isSetValido(value) {
    if (!/^\d+$/.test(value)) {
        return false;
    }
    const number = Number(value);
    return Number.isInteger(number) && number >= 0 && number <= 3;
}

function getCsrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]').value;
}

function appUrl(path) {
    const basePath = (window.APP_BASE_PATH || '').replace(/\/$/, '');
    return `${basePath}${path}`;
}

function valueOrEmpty(value) {
    return value === null || value === undefined ? '' : String(value);
}

function showFeedback(message, isError = false) {
    if (!feedback) {
        return;
    }
    feedback.textContent = message;
    feedback.classList.toggle('error', isError);
}

function escapeHtml(value) {
    return String(value)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}
