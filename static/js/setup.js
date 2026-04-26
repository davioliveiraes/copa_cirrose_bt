document.getElementById('form-dupla')?.addEventListener('submit', async (event) => {
    event.preventDefault();

    const nome = event.target.nome.value.trim();
    if (!nome) {
        return;
    }

    const response = await fetch('/duplas/adicionar/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify({ nome }),
    });

    if (response.ok) {
        window.location.reload();
    }
});

document.querySelectorAll('[data-remover]').forEach((button) => {
    button.addEventListener('click', async () => {
        const id = button.dataset.remover;
        if (!window.confirm('Remover esta dupla?')) {
            return;
        }

        const response = await fetch(`/duplas/${id}/remover/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() },
        });

        if (response.ok) {
            window.location.reload();
        }
    });
});

document.getElementById('btn-iniciar')?.addEventListener('click', async (event) => {
    event.preventDefault();

    if (!window.confirm('Iniciar o torneio? Nao sera possivel adicionar/remover duplas depois.')) {
        return;
    }

    const response = await fetch('/iniciar/', {
        method: 'POST',
        headers: { 'X-CSRFToken': getCsrfToken() },
    });

    if (response.ok) {
        window.location.href = '/';
    }
});

function getCsrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]').value;
}
