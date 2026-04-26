from django.db import models


class Torneio(models.Model):
    """Singleton - so existe um torneio ativo por vez."""

    STATUS_SETUP = 'setup'
    STATUS_ANDAMENTO = 'andamento'
    STATUS_CHOICES = [
        (STATUS_SETUP, 'Em Setup'),
        (STATUS_ANDAMENTO, 'Em Andamento'),
    ]

    nome = models.CharField(max_length=100, default='Copa Cirrose BT')
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_SETUP,
    )
    criado_em = models.DateTimeField(auto_now_add=True)
    iniciado_em = models.DateTimeField(null=True, blank=True)

    @classmethod
    def get_atual(cls):
        """Sempre retorna (criando se necessario) o torneio unico."""
        torneio, _ = cls.objects.get_or_create(pk=1)
        return torneio

    def __str__(self):
        return self.nome


class Dupla(models.Model):
    torneio = models.ForeignKey(
        Torneio,
        on_delete=models.CASCADE,
        related_name='duplas',
    )
    nome = models.CharField(max_length=100)
    ordem = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['ordem']

    def __str__(self):
        return self.nome


class Jogo(models.Model):
    FASE_GRUPOS = 'grupos'
    FASE_SF1 = 'sf1'
    FASE_SF2 = 'sf2'
    FASE_FINAL = 'final'
    FASE_CHOICES = [
        (FASE_GRUPOS, 'Fase de Grupos'),
        (FASE_SF1, 'Semifinal 1'),
        (FASE_SF2, 'Semifinal 2'),
        (FASE_FINAL, 'Final'),
    ]

    torneio = models.ForeignKey(
        Torneio,
        on_delete=models.CASCADE,
        related_name='jogos',
    )
    numero = models.PositiveSmallIntegerField()
    fase = models.CharField(
        max_length=10,
        choices=FASE_CHOICES,
        default=FASE_GRUPOS,
    )
    dupla_a = models.ForeignKey(
        Dupla,
        on_delete=models.CASCADE,
        related_name='jogos_como_a',
        null=True,
        blank=True,
    )
    dupla_b = models.ForeignKey(
        Dupla,
        on_delete=models.CASCADE,
        related_name='jogos_como_b',
        null=True,
        blank=True,
    )
    sets_a = models.PositiveSmallIntegerField(null=True, blank=True)
    sets_b = models.PositiveSmallIntegerField(null=True, blank=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['fase', 'numero']

    @property
    def preenchido(self):
        return self.sets_a is not None and self.sets_b is not None

    @property
    def vencedor(self):
        if not self.preenchido:
            return None
        if self.sets_a > self.sets_b:
            return self.dupla_a
        if self.sets_b > self.sets_a:
            return self.dupla_b
        return None
