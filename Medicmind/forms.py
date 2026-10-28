from django import forms

from .models import Evento


class EstadoLlamadaForm(forms.ModelForm):
    estado_llamada = forms.ChoiceField(
        choices=Evento.ESTADOS_LLAMADA,
        required=True,
        widget=forms.RadioSelect,
    )
    detalle_llamada = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 4}),
    )

    class Meta:
        model = Evento
        fields = ['estado_llamada', 'detalle_llamada']


class RespuestaSmsForm(forms.ModelForm):
    estado_respuesta_sms = forms.ChoiceField(
        choices=Evento.ESTADOS_RESPUESTA_SMS,
        required=True,
        widget=forms.RadioSelect,
    )

    class Meta:
        model = Evento
        fields = ['estado_respuesta_sms']
