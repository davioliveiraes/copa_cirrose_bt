from django.urls import path

from . import views

app_name = 'torneio'

urlpatterns = [
    path('', views.home, name='home'),
    path('placar/', views.placar, name='placar'),
    path('duplas/adicionar/', views.adicionar_dupla, name='adicionar_dupla'),
    path('duplas/<int:dupla_id>/remover/', views.remover_dupla, name='remover_dupla'),
    path('iniciar/', views.iniciar_torneio, name='iniciar_torneio'),
    path('reiniciar/', views.reiniciar_torneio, name='reiniciar_torneio'),
    path('jogos/<int:jogo_id>/salvar/', views.salvar_placar, name='salvar_placar'),
    path('jogos/<int:jogo_id>/limpar/', views.limpar_jogo, name='limpar_jogo'),
    path('exportar/', views.exportar, name='exportar'),
]
