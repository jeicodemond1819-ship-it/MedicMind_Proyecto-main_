from django.db import models
from django.utils import timezone
import calendar 
from datetime import date

TIPO_CELULAR = [
    ('TACTIL', 'Táctil / Smartphone'),
    ('BOTONES', 'Botones / Básico'),
]


def sumar_meses(fecha,meses):
    total = fecha.month - 1 + meses
    anio = fecha.year + total // 12
    mes = total % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


class AdultoMayor(models.Model):
    DEPENCENCIA = [
        ('AUTONOMO', 'Autónomo'),
        ('PARCIAL', 'Dependiente Parcial'),
        ('COMPLETO', 'Dependiente Completo'),
    ]

    nombre = models.CharField(max_length=100)
    rut = models.CharField(max_length=12, unique=True)
    dependencia = models.CharField(max_length=20, choices=DEPENCENCIA)
    no_sabe_leer = models.BooleanField(default=False)
    
    cuidadores = models.ManyToManyField('CuidadorHogar', related_name='adultos_mayores', blank=True)

    def __str__(self):
        return f"{self.nombre} ({self.rut})"


class CuidadorHogar(models.Model):
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=20)
    tipo_celular = models.CharField(max_length=20, choices=TIPO_CELULAR)

    def __str__(self):
        return f"Cuidador: {self.nombre}"


class Celular(models.Model):
    numero = models.CharField(max_length=20)
    tipo_celular = models.CharField(max_length=20, choices=TIPO_CELULAR)
    
    adulto_mayor = models.ForeignKey(AdultoMayor, on_delete=models.CASCADE, related_name='celulares')

    def __str__(self):
        return f"Celular {self.get_tipo_celular_display()} - {self.numero}"


class Medicamento(models.Model):
    nombre = models.CharField(max_length=100)
    dosis = models.CharField(max_length=100)

    adulto_mayor = models.ForeignKey(AdultoMayor, on_delete=models.CASCADE, related_name='medicamentos')

    def __str__(self):
        return f"{self.nombre} ({self.dosis}) - {self.adulto_mayor.nombre}"
    
    
class Receta(models.Model):
    adulto_mayor = models.ForeignKey(AdultoMayor, on_delete=models.CASCADE, related_name='recetas')
    medicamentos = models.ManyToManyField(Medicamento, related_name='recetas', blank=True)
    fecha_emision = models.DateField()
    vigencia_meses = models.PositiveSmallIntegerField()

    def vencimiento(self):
        return sumar_meses(self.fecha_emision, self.vigencia_meses)

    def __str__(self):
        return f"Receta del {self.fecha_emision:%d-%m-%Y} - {self.adulto_mayor.nombre}"

    
class Evento(models.Model):
    TIPOS = [
        ('CITA', 'Cita médica'),
        ('RETIRO', 'Retiro de medicamentos'),
        ('RENOVACION', 'Renovación de receta'),
    ]
    ESTADOS_LLAMADA = [
        ('CONFIRMADO', 'Confirmado'),
        ('RECHAZADO', 'Rechazado'),
        ('SIN_RESPUESTA', 'Sin respuesta'),
    ]
    ESTADOS_RESPUESTA_SMS = [
        ('CONFIRMADO', 'Confirmado'),
        ('NO_CONFIRMADO', 'No confirmado'),
    ]
    ESTADOS = [
        ('PENDIENTE', 'Pendiente'),
        ('REALIZADA', 'Realizada'),
        ('CANCELADA', 'Cancelada'),
    ]

    tipo = models.CharField(max_length=20, choices=TIPOS)
    fecha = models.DateField()
    hora = models.TimeField(null=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')
    estado_llamada = models.CharField(
        max_length=20, choices=ESTADOS_LLAMADA, blank=True, default='',
    )
    detalle_llamada = models.TextField(blank=True, default='')
    estado_respuesta_sms = models.CharField(
        max_length=20, choices=ESTADOS_RESPUESTA_SMS, blank=True, default='',
    )
    vencimiento_respuesta_sms = models.DateTimeField(null=True, blank=True)
    intentos_llamada_sin_respuesta = models.PositiveSmallIntegerField(default=0)
    proximo_intento_llamada = models.DateTimeField(null=True, blank=True)
    vigencia_meses = models.PositiveSmallIntegerField(null=True, blank=True)

    adulto_mayor = models.ForeignKey(AdultoMayor, on_delete=models.CASCADE, related_name='eventos')
    receta = models.ForeignKey(Receta, on_delete=models.SET_NULL, null=True, blank=True, related_name='eventos')

    @classmethod
    def marcar_respuestas_sms_vencidas(cls, ahora=None):
        ahora = ahora or timezone.now()
        return cls.objects.filter(
            estado_respuesta_sms='',
            vencimiento_respuesta_sms__lte=ahora,
        ).update(estado_respuesta_sms='NO_CONFIRMADO')
    
    def __str__(self):
        return f"{self.get_tipo_display()} {self.fecha} - {self.adulto_mayor.nombre}"
