import calendar
from datetime import date, time, timedelta
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from .forms import EstadoLlamadaForm, RespuestaSmsForm
from .models import AdultoMayor, Celular, CuidadorHogar, Evento, Receta, TIPO_CELULAR

CANAL_LLAMADA = 'Llamada'
CANAL_SMS = 'SMS'

TIPOS_CELULAR_VALIDOS = dict(TIPO_CELULAR)
DEPENDENCIAS_VALIDAS = dict(AdultoMayor.DEPENCENCIA)
TIPOS_EVENTO_VALIDOS = dict(Evento.TIPOS)

DIAS_AVISO_RENOVACION = 7
MAX_VIGENCIA_MESES = 6
CUPOS_POR_HORARIO = 1
MAX_INTENTOS_LLAMADA = 3
INTERVALO_INTENTO_LLAMADA = timedelta(minutes=15)
PLAZO_RESPUESTA_SMS = timedelta(hours=2)


def canal_para(tipo_celular, no_sabe_leer=False):
    if no_sabe_leer or tipo_celular == 'BOTONES':
        return CANAL_LLAMADA
    return CANAL_SMS


def contactos_de(adulto):
    contactos = []

    if adulto.dependencia in ('AUTONOMO', 'PARCIAL'):
        for cel in adulto.celulares.all():
            contactos.append({
                'rol': 'Adulto mayor',
                'nombre': adulto.nombre,
                'telefono': cel.numero,
                'tipo_celular': cel.get_tipo_celular_display(),
                'canal': canal_para(cel.tipo_celular, adulto.no_sabe_leer),
            })

    if adulto.dependencia in ('COMPLETO', 'PARCIAL'):
        for cuidador in adulto.cuidadores.all():
            contactos.append({
                'rol': 'Cuidador del hogar',
                'nombre': cuidador.nombre,
                'telefono': cuidador.telefono,
                'tipo_celular': cuidador.get_tipo_celular_display(),
                'canal': canal_para(cuidador.tipo_celular),
            })

    return contactos


def sumar_meses(fecha, meses):
    total = fecha.month - 1 + meses
    anio = fecha.year + total // 12
    mes = total % 12 + 1
    dia = min(fecha.day, calendar.monthrange(anio, mes)[1])
    return date(anio, mes, dia)


def _leer_fecha(texto):
    try:
        return date.fromisoformat((texto or '').strip())
    except ValueError:
        return None


def _leer_hora(texto):
    try:
        return time.fromisoformat((texto or '').strip())
    except ValueError:
        return None


def _hay_cupo(fecha, hora, excluir_id=None):
    citas = Evento.objects.filter(
        tipo='CITA', estado='PENDIENTE', fecha=fecha, hora=hora,
    )
    if excluir_id:
        citas = citas.exclude(id=excluir_id)
    return citas.count() < CUPOS_POR_HORARIO


def _recetas_de(adulto):
    return (
        adulto.recetas
        .prefetch_related('medicamentos')
        .order_by('-fecha_emision', '-id')
    )


def _destino_seguro(request, por_defecto):
    destino = request.POST.get('next') or request.GET.get('next') or ''
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        return destino
    return por_defecto


def _texto_aviso(adulto):
    contactos = contactos_de(adulto)
    if not contactos:
        return 'Este paciente no tiene contactos registrados para avisar.'
    partes = [f"{c['nombre']} ({c['canal']})" for c in contactos]
    return 'Avisar a: ' + ', '.join(partes)


def home_view(request):
    proximos_eventos = (
        Evento.objects.filter(
            estado='PENDIENTE',
            fecha__gte=timezone.localdate(),
        )
        .select_related('adulto_mayor')
        .order_by('fecha')[:5]
    )
    return render(request, 'inicio.html', {
        'total_pacientes': AdultoMayor.objects.count(),
        'total_eventos_pendientes': Evento.objects.filter(estado='PENDIENTE').count(),
        'proximos_eventos': proximos_eventos,
    })


def lista_pacientes(request):
    pacientes = AdultoMayor.objects.all().order_by('nombre')
    rut = request.GET.get('rut', '').strip()
    if rut:
        rut_limpio = rut.replace('.', '').replace(' ', '')
        pacientes = pacientes.filter(rut__icontains=rut_limpio)
    return render(request, 'lista_pacientes.html', {
        'pacientes': pacientes,
        'rut': rut,
    })


def registrar_paciente(request):
    contexto = {
        'errores': [],
        'datos': {},
        'dependencias': AdultoMayor.DEPENCENCIA,
        'tipos_celular': TIPO_CELULAR,
    }

    if request.method != 'POST':
        return render(request, 'registrar_paciente.html', contexto)

    datos = request.POST
    errores = []

    nombre = datos.get('nombre', '').strip()
    rut = datos.get('rut', '').strip()
    dependencia = datos.get('dependencia', '')
    no_sabe_leer = datos.get('no_sabe_leer') in ('on', 'true', '1')

    celular_numero = datos.get('celular_numero', '').strip()
    celular_tipo = datos.get('celular_tipo', '')
    cuidador_nombre = datos.get('cuidador_nombre', '').strip()
    cuidador_telefono = datos.get('cuidador_telefono', '').strip()
    cuidador_tipo = datos.get('cuidador_tipo', '')

    if not nombre:
        errores.append('El nombre es obligatorio.')
    if not rut:
        errores.append('El RUT es obligatorio.')
    elif AdultoMayor.objects.filter(rut=rut).exists():
        errores.append('Ya existe un paciente con ese RUT.')
    if dependencia not in DEPENDENCIAS_VALIDAS:
        errores.append('Selecciona un nivel de dependencia válido.')

    pide_celular_adulto = dependencia in ('AUTONOMO', 'PARCIAL')
    pide_cuidador = dependencia in ('COMPLETO', 'PARCIAL')

    if pide_celular_adulto:
        if not celular_numero:
            errores.append('Falta el celular del adulto mayor.')
        if celular_tipo not in TIPOS_CELULAR_VALIDOS:
            errores.append('Selecciona el tipo de celular del adulto mayor.')

    if pide_cuidador:
        if not cuidador_nombre or not cuidador_telefono:
            errores.append('Falta el nombre o el celular del cuidador del hogar.')
        if cuidador_tipo not in TIPOS_CELULAR_VALIDOS:
            errores.append('Selecciona el tipo de celular del cuidador del hogar.')

    if errores:
        contexto['errores'] = errores
        contexto['datos'] = datos
        return render(request, 'registrar_paciente.html', contexto)

    with transaction.atomic():
        adulto = AdultoMayor.objects.create(
            nombre=nombre, rut=rut,
            dependencia=dependencia, no_sabe_leer=no_sabe_leer,
        )
        if pide_celular_adulto:
            Celular.objects.create(
                adulto_mayor=adulto, numero=celular_numero, tipo_celular=celular_tipo,
            )
        if pide_cuidador:
            cuidador = CuidadorHogar.objects.filter(telefono=cuidador_telefono).first()
            if cuidador is None:
                cuidador = CuidadorHogar.objects.create(
                    nombre=cuidador_nombre, telefono=cuidador_telefono,
                    tipo_celular=cuidador_tipo,
                )
            adulto.cuidadores.add(cuidador)

    messages.success(request, f'Paciente {adulto.nombre} registrado correctamente.')
    return redirect('sugerir_canal', paciente_id=adulto.id)


def sugerir_canal(request, paciente_id):
    adulto = get_object_or_404(AdultoMayor, id=paciente_id)
    contexto = {
        'paciente': adulto,
        'contactos': contactos_de(adulto),
    }
    return render(request, 'sugerir_canal.html', contexto)


def lista_eventos(request):
    if Evento.objects.filter(
        estado_respuesta_sms='',
        vencimiento_respuesta_sms__isnull=False,
    ).exists():
        Evento.marcar_respuestas_sms_vencidas()
    eventos = (
        Evento.objects.select_related('adulto_mayor')
        .order_by('fecha')
    )
    estado = request.GET.get('estado')
    if estado in dict(Evento.ESTADOS):
        eventos = eventos.filter(estado=estado)
    return render(request, 'lista_eventos.html', {
        'eventos': eventos,
        'estados': Evento.ESTADOS,
        'estado_actual': estado,
    })


def seguimiento_contactos(request):
    if Evento.objects.filter(
        estado_respuesta_sms='',
        vencimiento_respuesta_sms__isnull=False,
    ).exists():
        Evento.marcar_respuestas_sms_vencidas()

    eventos = list(
        Evento.objects.select_related('adulto_mayor')
        .prefetch_related('adulto_mayor__celulares', 'adulto_mayor__cuidadores')
        .order_by('-fecha', '-id')
    )
    eventos_pendientes = []
    llamadas_registradas = []
    respuestas_sms = []

    for evento in eventos:
        canales = {contacto['canal'] for contacto in contactos_de(evento.adulto_mayor)}
        evento.tiene_contacto_llamada = CANAL_LLAMADA in canales
        evento.necesita_llamada = (
            evento.estado == 'PENDIENTE'
            and evento.tiene_contacto_llamada
            and not evento.estado_llamada
            and evento.intentos_llamada_sin_respuesta < MAX_INTENTOS_LLAMADA
        )
        evento.sms_pendiente = (
            evento.estado == 'PENDIENTE'
            and evento.vencimiento_respuesta_sms is not None
            and not evento.estado_respuesta_sms
        )
        evento.llamada_registrada = bool(
            evento.estado_llamada or evento.intentos_llamada_sin_respuesta
        )
        if evento.necesita_llamada or evento.sms_pendiente:
            eventos_pendientes.append(evento)
        if evento.llamada_registrada:
            llamadas_registradas.append(evento)
        if evento.estado_respuesta_sms:
            respuestas_sms.append(evento)

    return render(request, 'seguimiento_contactos.html', {
        'eventos_pendientes': eventos_pendientes,
        'llamadas_registradas': llamadas_registradas,
        'respuestas_sms': respuestas_sms,
        'estados_llamada': Evento.ESTADOS_LLAMADA,
        'estados_sms': Evento.ESTADOS_RESPUESTA_SMS,
    })


def crear_evento(request, paciente_id):
    adulto = get_object_or_404(AdultoMayor, id=paciente_id)
    receta_vinculada = _recetas_de(adulto).first()
    contexto = {
        'paciente': adulto,
        'receta_vinculada': receta_vinculada,
        'tipos': Evento.TIPOS,
        'vigencias': range(1, MAX_VIGENCIA_MESES + 1),
        'errores': [],
        'datos': {},
    }

    if request.method != 'POST':
        return render(request, 'crear_evento.html', contexto)

    tipo = request.POST.get('tipo', '')
    fecha = _leer_fecha(request.POST.get('fecha'))
    hora = _leer_hora(request.POST.get('hora'))
    vigencia_texto = request.POST.get('vigencia_meses', '').strip()
    errores = []

    if tipo not in TIPOS_EVENTO_VALIDOS:
        errores.append('Selecciona un tipo de evento válido.')
    if fecha is None:
        errores.append('Ingresa una fecha válida.')
    if tipo == 'CITA':
        if hora is None:
            errores.append('Ingresa una hora válida.')
        elif fecha is not None and not _hay_cupo(fecha, hora):
            errores.append('Ese horario ya está ocupado. Elige otra fecha u hora.')

    vigencia = None
    if tipo == 'RETIRO' and vigencia_texto:
        if vigencia_texto.isdigit() and 1 <= int(vigencia_texto) <= MAX_VIGENCIA_MESES:
            vigencia = int(vigencia_texto)
        else:
            errores.append(f'La vigencia debe ser entre 1 y {MAX_VIGENCIA_MESES} meses.')
    if tipo == 'RENOVACION' and receta_vinculada is None:
        errores.append('Este paciente no tiene recetas registradas para renovar.')

    if errores:
        contexto['errores'] = errores
        contexto['datos'] = request.POST
        return render(request, 'crear_evento.html', contexto)

    hay_contacto_sms = any(
        contacto['canal'] == CANAL_SMS
        for contacto in contactos_de(adulto)
    )
    Evento.objects.create(
        adulto_mayor=adulto,
        tipo=tipo,
        fecha=fecha,
        hora=hora,
        vigencia_meses=vigencia,
        receta=receta_vinculada if tipo == 'RENOVACION' else None,
        vencimiento_respuesta_sms=(
            timezone.now() + PLAZO_RESPUESTA_SMS if hay_contacto_sms else None
        ),
    )
    messages.success(request, 'Evento programado correctamente.')
    return redirect('lista_eventos')


def reprogramar_evento(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)

    if evento.estado != 'PENDIENTE':
        messages.error(request, 'Solo se pueden reprogramar eventos pendientes.')
        return redirect('lista_eventos')

    if request.method != 'POST':
        return render(request, 'reprogramar_evento.html', {
            'evento': evento, 'errores': [],
        })

    nueva_fecha = _leer_fecha(request.POST.get('fecha'))
    nueva_hora = _leer_hora(request.POST.get('hora'))
    errores = []

    if nueva_fecha is None:
        errores.append('Ingresa una fecha válida.')
    if evento.tipo == 'CITA':
        if nueva_hora is None:
            errores.append('Ingresa una hora válida.')
        elif nueva_fecha is not None and not _hay_cupo(nueva_fecha, nueva_hora, evento.id):
            errores.append('Ese horario ya está ocupado. Elige otra fecha u hora.')

    if errores:
        return render(request, 'reprogramar_evento.html', {
            'evento': evento,
            'errores': errores,
            'fecha_ingresada': request.POST.get('fecha', ''),
            'hora_ingresada': request.POST.get('hora', ''),
        })

    evento.fecha = nueva_fecha
    evento.hora = nueva_hora
    evento.save()
    texto_hora = f' a las {nueva_hora:%H:%M}' if nueva_hora else ''
    messages.success(
        request,
        f'Evento reprogramado para el {nueva_fecha:%d-%m-%Y}{texto_hora}. '
        + _texto_aviso(evento.adulto_mayor),
    )
    return redirect('lista_eventos')


@require_POST
def cancelar_evento(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)

    if evento.estado != 'PENDIENTE':
        messages.error(request, 'Solo se pueden cancelar eventos pendientes.')
        return redirect('lista_eventos')

    evento.estado = 'CANCELADA'
    evento.save()
    messages.success(request, 'Evento cancelado. ' + _texto_aviso(evento.adulto_mayor))
    return redirect('lista_eventos')


@require_POST
def marcar_realizada(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)

    if evento.estado != 'PENDIENTE':
        messages.error(request, 'Solo se pueden registrar como cumplidos los eventos pendientes.')
        return redirect('lista_eventos')

    evento.estado = 'REALIZADA'
    evento.save()

    if evento.tipo == 'RETIRO' and evento.vigencia_meses:
        vencimiento = sumar_meses(evento.fecha, evento.vigencia_meses)
        fecha_renovacion = vencimiento - timedelta(days=DIAS_AVISO_RENOVACION)

        receta, _ = Receta.objects.get_or_create(
            adulto_mayor=evento.adulto_mayor,
            fecha_emision=evento.fecha,
            vigencia_meses=evento.vigencia_meses,
        )
        renovacion, creada = Evento.objects.get_or_create(
            adulto_mayor=evento.adulto_mayor,
            tipo='RENOVACION',
            fecha=fecha_renovacion,
            estado='PENDIENTE',
        )
        if renovacion.receta_id is None:
            renovacion.receta = receta
            renovacion.save(update_fields=['receta'])
        if creada:
            messages.success(
                request,
                f'Retiro registrado. Se creó la renovación de receta para el '
                f'{fecha_renovacion:%d-%m-%Y} (la receta vence el {vencimiento:%d-%m-%Y}).',
            )
            return redirect('lista_eventos')

    messages.success(request, 'Evento registrado como cumplido.')
    return redirect('lista_eventos')


@require_POST
def registrar_estado_llamada(request, evento_id):
    evento = get_object_or_404(Evento, id=evento_id)
    form = EstadoLlamadaForm(request.POST, instance=evento)
    if not form.is_valid():
        return HttpResponseBadRequest('Selecciona un estado de llamada válido.')

    estado_llamada = form.cleaned_data['estado_llamada']
    evento.detalle_llamada = (
        form.cleaned_data['detalle_llamada']
        if estado_llamada in ('CONFIRMADO', 'RECHAZADO')
        else ''
    )
    if estado_llamada == 'SIN_RESPUESTA':
        if evento.intentos_llamada_sin_respuesta >= MAX_INTENTOS_LLAMADA:
            messages.error(request, 'Ya se completaron los 3 intentos de llamada.')
            return redirect('seguimiento_contactos')

        ahora = timezone.now()
        if evento.proximo_intento_llamada and ahora < evento.proximo_intento_llamada:
            messages.error(
                request,
                'Debes esperar 15 minutos entre intentos. '
                f'Puedes volver a llamar a partir de '
                f'{timezone.localtime(evento.proximo_intento_llamada):%H:%M}.',
            )
            return redirect('seguimiento_contactos')

        evento.intentos_llamada_sin_respuesta += 1
        if evento.intentos_llamada_sin_respuesta >= MAX_INTENTOS_LLAMADA:
            evento.estado_llamada = 'SIN_RESPUESTA'
            evento.proximo_intento_llamada = None
            mensaje = 'Se registraron 3 intentos sin respuesta. Estado final: Sin respuesta.'
        else:
            evento.estado_llamada = ''
            evento.proximo_intento_llamada = ahora + INTERVALO_INTENTO_LLAMADA
            intentos_restantes = MAX_INTENTOS_LLAMADA - evento.intentos_llamada_sin_respuesta
            mensaje = (
                f'Intento sin respuesta registrado. Quedan {intentos_restantes} '
                f'intento(s); puedes volver a llamar a partir de '
                f'{timezone.localtime(evento.proximo_intento_llamada):%H:%M}.'
            )
    else:
        evento.estado_llamada = estado_llamada
        evento.intentos_llamada_sin_respuesta = 0
        evento.proximo_intento_llamada = None
        mensaje = f'Estado de llamada registrado: {evento.get_estado_llamada_display()}.'

    evento.save(update_fields=[
        'estado_llamada',
        'detalle_llamada',
        'intentos_llamada_sin_respuesta',
        'proximo_intento_llamada',
    ])
    messages.success(request, mensaje)
    return redirect('seguimiento_contactos')


@require_POST
def registrar_respuesta_sms(request, evento_id):
    Evento.marcar_respuestas_sms_vencidas()
    evento = get_object_or_404(Evento, id=evento_id)
    if evento.vencimiento_respuesta_sms is None:
        return HttpResponseBadRequest('Este evento no tiene una respuesta SMS pendiente.')
    if evento.estado_respuesta_sms:
        messages.error(request, 'La respuesta SMS de este evento ya fue registrada.')
        return redirect('seguimiento_contactos')

    form = RespuestaSmsForm(request.POST, instance=evento)
    if not form.is_valid():
        return HttpResponseBadRequest('Selecciona una respuesta SMS válida.')

    form.save()
    messages.success(
        request,
        f'Respuesta SMS registrada: {evento.get_estado_respuesta_sms_display()}.',
    )
    return redirect('seguimiento_contactos')


def registrar_receta(request, paciente_id):
    adulto = get_object_or_404(AdultoMayor, id=paciente_id)
    medicamentos = adulto.medicamentos.order_by('nombre')
    volver = _destino_seguro(request, reverse('crear_evento', args=[adulto.id]))
    contexto = {
        'paciente': adulto,
        'medicamentos': medicamentos,
        'vigencias': range(1, MAX_VIGENCIA_MESES + 1),
        'volver': volver,
        'errores': [],
        'datos': {},
        'medicamentos_marcados': [],
    }

    if request.method != 'POST':
        return render(request, 'registrar_receta.html', contexto)

    fecha_emision = _leer_fecha(request.POST.get('fecha_emision'))
    vigencia_texto = request.POST.get('vigencia_meses', '').strip()
    ids_medicamentos = [i for i in request.POST.getlist('medicamentos') if i.isdigit()]
    errores = []

    if fecha_emision is None:
        errores.append('Ingresa una fecha de emisión válida.')

    vigencia = None
    if vigencia_texto.isdigit() and 1 <= int(vigencia_texto) <= MAX_VIGENCIA_MESES:
        vigencia = int(vigencia_texto)
    else:
        errores.append(f'La vigencia debe ser entre 1 y {MAX_VIGENCIA_MESES} meses.')

    if errores:
        contexto['errores'] = errores
        contexto['datos'] = request.POST
        contexto['medicamentos_marcados'] = ids_medicamentos
        return render(request, 'registrar_receta.html', contexto)

    with transaction.atomic():
        receta = Receta.objects.create(
            adulto_mayor=adulto, fecha_emision=fecha_emision, vigencia_meses=vigencia,
        )
        receta.medicamentos.set(medicamentos.filter(id__in=ids_medicamentos))

    messages.success(
        request,
        f'Receta del {fecha_emision:%d-%m-%Y} registrada '
        f'(vence el {receta.vencimiento():%d-%m-%Y}).',
    )
    return redirect(volver)


def cambiar_receta(request, evento_id):
    evento = get_object_or_404(
        Evento.objects.select_related('adulto_mayor', 'receta'), id=evento_id,
    )

    if evento.tipo != 'RENOVACION':
        messages.error(request, 'Solo las renovaciones de receta tienen una receta asociada.')
        return redirect('lista_eventos')
    if evento.estado != 'PENDIENTE':
        messages.error(request, 'Solo se puede cambiar la receta de eventos pendientes.')
        return redirect('lista_eventos')

    recetas = list(_recetas_de(evento.adulto_mayor))
    contexto = {
        'evento': evento,
        'recetas': recetas,
        'seleccionada': evento.receta_id,
        'errores': [],
    }

    if request.method != 'POST':
        return render(request, 'cambiar_receta.html', contexto)

    receta_id = request.POST.get('receta', '')
    receta = next((r for r in recetas if str(r.id) == receta_id), None)
    if receta is None:
        contexto['errores'] = ['Selecciona una de las recetas del paciente.']
        return render(request, 'cambiar_receta.html', contexto)

    evento.receta = receta
    evento.save()
    messages.success(
        request,
        f'Receta actualizada: ahora la renovación usa la receta del {receta.fecha_emision:%d-%m-%Y}.',
    )
    return redirect('lista_eventos')
