from django.urls import path

from . import views

urlpatterns = [
    path('pacientes/', views.lista_pacientes, name='lista_pacientes'),
    path('pacientes/nuevo/', views.registrar_paciente, name='registrar_paciente'),
    path('pacientes/<int:paciente_id>/canal/', views.sugerir_canal, name='sugerir_canal'),
    path('pacientes/<int:paciente_id>/eventos/nuevo/', views.crear_evento, name='crear_evento'),
    path('pacientes/<int:paciente_id>/recetas/nueva/', views.registrar_receta, name='registrar_receta'),
    path('eventos/', views.lista_eventos, name='lista_eventos'),
    path('seguimiento/', views.seguimiento_contactos, name='seguimiento_contactos'),
    path('eventos/<int:evento_id>/reprogramar/', views.reprogramar_evento, name='reprogramar_evento'),
    path('eventos/<int:evento_id>/cancelar/', views.cancelar_evento, name='cancelar_evento'),
    path('eventos/<int:evento_id>/realizada/', views.marcar_realizada, name='marcar_realizada'),
    path('eventos/<int:evento_id>/llamada/estado/', views.registrar_estado_llamada, name='registrar_estado_llamada'),
    path('eventos/<int:evento_id>/sms/respuesta/', views.registrar_respuesta_sms, name='registrar_respuesta_sms'),
    path('eventos/<int:evento_id>/receta/', views.cambiar_receta, name='cambiar_receta'),
]
