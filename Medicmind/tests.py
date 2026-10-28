from datetime import date, datetime, timedelta
from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from .models import AdultoMayor, Celular, Evento, Medicamento, Receta


class PortalViewsTests(TestCase):
    def setUp(self):
        self.paciente = AdultoMayor.objects.create(
            nombre='Ana Ejemplo',
            rut='12345678-9',
            dependencia='AUTONOMO',
        )
        Celular.objects.create(
            adulto_mayor=self.paciente,
            numero='+56912345678',
            tipo_celular='TACTIL',
        )

    def test_home_shows_summary_and_upcoming_events(self):
        fecha_proxima = timezone.localdate() + timedelta(days=1)
        Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=fecha_proxima,
        )

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ana Ejemplo')
        self.assertContains(response, 'Pacientes registrados')
        self.assertContains(response, '/static/Medicmind/styles.css')

    def test_nested_pages_use_root_relative_stylesheet_url(self):
        response = self.client.get(reverse('lista_pacientes'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/static/Medicmind/styles.css"')

    def test_registration_creates_patient_and_redirects_to_contact_suggestion(self):
        response = self.client.post(reverse('registrar_paciente'), {
            'nombre': 'Beatriz Ejemplo',
            'rut': '98765432-1',
            'dependencia': 'AUTONOMO',
            'celular_numero': '+56987654321',
            'celular_tipo': 'TACTIL',
        })

        paciente_creado = AdultoMayor.objects.get(rut='98765432-1')
        self.assertRedirects(
            response,
            reverse('sugerir_canal', args=[paciente_creado.id]),
        )
        self.assertTrue(AdultoMayor.objects.filter(rut='98765432-1').exists())

    def test_invalid_registration_preserves_form_data(self):
        response = self.client.post(reverse('registrar_paciente'), {
            'nombre': 'Paciente sin RUT',
            'dependencia': 'AUTONOMO',
            'celular_numero': '+56987654321',
            'celular_tipo': 'TACTIL',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'El RUT es obligatorio.')
        self.assertContains(response, 'Paciente sin RUT')
        self.assertEqual(AdultoMayor.objects.count(), 1)

    def test_event_can_be_scheduled_and_marked_done(self):
        self.client.post(
            reverse('crear_evento', args=[self.paciente.id]),
            {
                'tipo': 'RETIRO',
                'fecha': '2026-10-25',
                'vigencia_meses': '3',
            },
        )
        evento = Evento.objects.get(adulto_mayor=self.paciente)

        response = self.client.post(
            reverse('marcar_realizada', args=[evento.id]),
        )

        evento.refresh_from_db()
        self.assertRedirects(response, reverse('lista_eventos'))
        self.assertEqual(evento.estado, 'REALIZADA')
        self.assertTrue(
            Evento.objects.filter(
                adulto_mayor=self.paciente,
                tipo='RENOVACION',
                fecha=date(2027, 1, 18),
            ).exists()
        )

    def test_scheduled_event_with_sms_contact_starts_two_hour_response_window(self):
        ahora = timezone.make_aware(datetime(2026, 10, 27, 12, 0))
        with patch('Medicmind.views.timezone.now', return_value=ahora):
            self.client.post(
                reverse('crear_evento', args=[self.paciente.id]),
                {'tipo': 'CITA', 'fecha': '2026-11-01'},
            )

        evento = Evento.objects.get(adulto_mayor=self.paciente)
        self.assertEqual(
            evento.vencimiento_respuesta_sms,
            ahora + timedelta(hours=2),
        )
        self.assertEqual(evento.estado_respuesta_sms, '')

    def test_scheduled_event_without_sms_contact_has_no_sms_response_window(self):
        Celular.objects.filter(adulto_mayor=self.paciente).update(tipo_celular='BOTONES')

        self.client.post(
            reverse('crear_evento', args=[self.paciente.id]),
            {'tipo': 'CITA', 'fecha': '2026-11-01'},
        )

        evento = Evento.objects.get(adulto_mayor=self.paciente)
        self.assertIsNone(evento.vencimiento_respuesta_sms)
        self.assertEqual(evento.estado_respuesta_sms, '')

    def test_sms_response_form_is_rendered_on_followup_page(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
            vencimiento_respuesta_sms=timezone.now() + timedelta(hours=2),
        )

        response = self.client.get(reverse('seguimiento_contactos'))

        self.assertContains(response, 'Registrar respuesta por SMS')
        self.assertContains(response, 'name="estado_respuesta_sms"')
        self.assertContains(response, 'value="CONFIRMADO"')
        self.assertContains(response, 'value="NO_CONFIRMADO"')
        self.assertNotContains(response, 'Respuesta SMS:</strong>')
        self.assertNotContains(self.client.get(reverse('lista_eventos')), 'name="estado_respuesta_sms"')

    def test_sms_response_can_be_recorded_once(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
            vencimiento_respuesta_sms=timezone.now() + timedelta(hours=2),
        )

        response = self.client.post(
            reverse('registrar_respuesta_sms', args=[evento.id]),
            {'estado_respuesta_sms': 'CONFIRMADO'},
        )

        self.assertRedirects(response, reverse('seguimiento_contactos'))
        evento.refresh_from_db()
        self.assertEqual(evento.estado_respuesta_sms, 'CONFIRMADO')
        response = self.client.get(reverse('seguimiento_contactos'))
        self.assertContains(response, '<span class="badge ok">Confirmado</span>')
        self.assertNotContains(response, 'Registrar respuesta por SMS')
        self.assertNotContains(self.client.get(reverse('lista_eventos')), 'Respuesta SMS:</strong>')

        response = self.client.post(
            reverse('registrar_respuesta_sms', args=[evento.id]),
            {'estado_respuesta_sms': 'NO_CONFIRMADO'},
        )
        self.assertRedirects(response, reverse('seguimiento_contactos'))
        evento.refresh_from_db()
        self.assertEqual(evento.estado_respuesta_sms, 'CONFIRMADO')

    def test_sms_response_automatically_expires_when_agenda_is_opened(self):
        ahora = timezone.make_aware(datetime(2026, 10, 27, 14, 0))
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
            vencimiento_respuesta_sms=ahora - timedelta(seconds=1),
        )

        with patch('Medicmind.models.timezone.now', return_value=ahora):
            response = self.client.get(reverse('lista_eventos'))

        self.assertEqual(response.status_code, 200)
        evento.refresh_from_db()
        self.assertEqual(evento.estado_respuesta_sms, 'NO_CONFIRMADO')

    def test_expired_sms_response_is_marked_no_confirmado_on_submission(self):
        ahora = timezone.make_aware(datetime(2026, 10, 27, 14, 0))
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
            vencimiento_respuesta_sms=ahora - timedelta(seconds=1),
        )

        with patch('Medicmind.models.timezone.now', return_value=ahora):
            response = self.client.post(
                reverse('registrar_respuesta_sms', args=[evento.id]),
                {'estado_respuesta_sms': 'CONFIRMADO'},
            )

        self.assertRedirects(response, reverse('seguimiento_contactos'))
        evento.refresh_from_db()
        self.assertEqual(evento.estado_respuesta_sms, 'NO_CONFIRMADO')

    def test_event_filter_only_shows_requested_state(self):
        Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
            estado='REALIZADA',
        )
        Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='RETIRO',
            fecha=date(2026, 11, 2),
        )

        response = self.client.get(
            reverse('lista_eventos'),
            {'estado': 'REALIZADA'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['eventos']), 1)
        self.assertEqual(response.context['eventos'][0].estado, 'REALIZADA')

    def test_call_status_can_be_recorded_for_an_event(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
        )

        for valor, etiqueta in Evento.ESTADOS_LLAMADA:
            with self.subTest(estado_llamada=valor):
                response = self.client.post(
                    reverse('registrar_estado_llamada', args=[evento.id]),
                    {'estado_llamada': valor},
                )

                self.assertRedirects(response, reverse('seguimiento_contactos'))
                evento.refresh_from_db()
                if valor == 'SIN_RESPUESTA':
                    self.assertEqual(evento.estado_llamada, '')
                    self.assertEqual(evento.intentos_llamada_sin_respuesta, 1)
                else:
                    self.assertEqual(evento.estado_llamada, valor)
                    self.assertEqual(evento.get_estado_llamada_display(), etiqueta)

    def test_confirmed_call_saves_discussion_details(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
        )

        response = self.client.post(
            reverse('registrar_estado_llamada', args=[evento.id]),
            {
                'estado_llamada': 'CONFIRMADO',
                'detalle_llamada': 'Confirmó su asistencia a la cita.',
            },
        )

        self.assertRedirects(response, reverse('seguimiento_contactos'))
        evento.refresh_from_db()
        self.assertEqual(
            evento.detalle_llamada,
            'Confirmó su asistencia a la cita.',
        )

    def test_rejected_call_saves_discussion_details(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
            estado_llamada='CONFIRMADO',
            detalle_llamada='Confirmó asistencia.',
        )

        self.client.post(
            reverse('registrar_estado_llamada', args=[evento.id]),
            {
                'estado_llamada': 'RECHAZADO',
                'detalle_llamada': 'Prefiere reprogramar la cita.',
            },
        )

        evento.refresh_from_db()
        self.assertEqual(evento.estado_llamada, 'RECHAZADO')
        self.assertEqual(evento.detalle_llamada, 'Prefiere reprogramar la cita.')

    def test_call_record_is_only_shown_on_followup_page_after_a_call(self):
        Celular.objects.filter(adulto_mayor=self.paciente).update(tipo_celular='BOTONES')
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
            estado_llamada='CONFIRMADO',
            detalle_llamada='Confirmó asistencia.',
        )

        response = self.client.get(reverse('seguimiento_contactos'))

        self.assertContains(response, 'Llamadas registradas')
        self.assertContains(response, 'Confirmado')
        self.assertContains(response, evento.detalle_llamada)
        self.assertNotContains(response, 'Registrar intento de llamada')
        self.assertNotContains(self.client.get(reverse('lista_eventos')), evento.detalle_llamada)

    def test_call_form_is_only_on_followup_page_for_pending_call_contact(self):
        Celular.objects.filter(adulto_mayor=self.paciente).update(tipo_celular='BOTONES')
        Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
        )

        response = self.client.get(reverse('seguimiento_contactos'))

        self.assertContains(response, 'Registrar intento de llamada')
        self.assertContains(response, 'value="CONFIRMADO"')
        self.assertContains(response, 'value="RECHAZADO"')
        self.assertContains(response, 'value="SIN_RESPUESTA"')
        self.assertContains(response, '¿Qué se habló en esta llamada?')
        self.assertNotContains(self.client.get(reverse('lista_eventos')), 'Registrar intento de llamada')

    def test_invalid_call_status_is_rejected_without_changing_event(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
            estado_llamada='CONFIRMADO',
        )

        response = self.client.post(
            reverse('registrar_estado_llamada', args=[evento.id]),
            {'estado_llamada': 'INVALIDO'},
        )

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            'Selecciona un estado de llamada válido.',
            status_code=400,
        )
        evento.refresh_from_db()
        self.assertEqual(evento.estado_llamada, 'CONFIRMADO')

    def test_unanswered_calls_allow_two_retries_thirty_minutes_apart(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
        )
        inicio = timezone.make_aware(datetime(2026, 10, 27, 12, 0))

        with patch(
            'Medicmind.views.timezone.now',
            side_effect=[
                inicio,
                inicio + timedelta(minutes=30),
                inicio + timedelta(minutes=60),
            ],
        ):
            for intento in range(1, 4):
                response = self.client.post(
                    reverse('registrar_estado_llamada', args=[evento.id]),
                    {'estado_llamada': 'SIN_RESPUESTA'},
                )
                self.assertRedirects(response, reverse('seguimiento_contactos'))
                evento.refresh_from_db()
                self.assertEqual(evento.intentos_llamada_sin_respuesta, intento)
                if intento < 3:
                    self.assertEqual(evento.estado_llamada, '')
                    self.assertEqual(
                        evento.proximo_intento_llamada,
                        inicio + timedelta(minutes=30 * intento),
                    )
                else:
                    self.assertEqual(evento.estado_llamada, 'SIN_RESPUESTA')
                    self.assertIsNone(evento.proximo_intento_llamada)

    def test_unanswered_retry_before_thirty_minutes_is_not_recorded(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
        )
        ahora = timezone.make_aware(datetime(2026, 10, 27, 12, 0))

        with patch('Medicmind.views.timezone.now', return_value=ahora):
            self.client.post(
                reverse('registrar_estado_llamada', args=[evento.id]),
                {'estado_llamada': 'SIN_RESPUESTA'},
            )

        with patch(
            'Medicmind.views.timezone.now',
            return_value=ahora + timedelta(minutes=29),
        ):
            response = self.client.post(
                reverse('registrar_estado_llamada', args=[evento.id]),
                {'estado_llamada': 'SIN_RESPUESTA'},
            )

        self.assertRedirects(response, reverse('seguimiento_contactos'))
        evento.refresh_from_db()
        self.assertEqual(evento.intentos_llamada_sin_respuesta, 1)
        self.assertEqual(evento.estado_llamada, '')
        self.assertEqual(
            evento.proximo_intento_llamada,
            ahora + timedelta(minutes=30),
        )

    def test_answered_call_stops_unanswered_retries(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
            intentos_llamada_sin_respuesta=1,
            proximo_intento_llamada=timezone.now() + timedelta(minutes=30),
        )

        response = self.client.post(
            reverse('registrar_estado_llamada', args=[evento.id]),
            {'estado_llamada': 'CONFIRMADO'},
        )

        self.assertRedirects(response, reverse('seguimiento_contactos'))
        evento.refresh_from_db()
        self.assertEqual(evento.estado_llamada, 'CONFIRMADO')
        self.assertEqual(evento.intentos_llamada_sin_respuesta, 0)
        self.assertIsNone(evento.proximo_intento_llamada)

    def test_no_more_unanswered_attempts_are_recorded_after_third_attempt(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
            estado_llamada='SIN_RESPUESTA',
            intentos_llamada_sin_respuesta=3,
        )

        response = self.client.post(
            reverse('registrar_estado_llamada', args=[evento.id]),
            {'estado_llamada': 'SIN_RESPUESTA'},
        )

        self.assertRedirects(response, reverse('seguimiento_contactos'))
        evento.refresh_from_db()
        self.assertEqual(evento.estado_llamada, 'SIN_RESPUESTA')
        self.assertEqual(evento.intentos_llamada_sin_respuesta, 3)

    def test_invalid_reprogramming_preserves_submitted_date(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente,
            tipo='CITA',
            fecha=date(2026, 11, 1),
        )

        response = self.client.post(
            reverse('reprogramar_evento', args=[evento.id]),
            {'fecha': 'fecha-invalida'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ingresa una fecha válida.')
        self.assertContains(response, 'value="fecha-invalida"')
        evento.refresh_from_db()
        self.assertEqual(evento.fecha, date(2026, 11, 1))


class RecetaTests(TestCase):
    def setUp(self):
        self.paciente = AdultoMayor.objects.create(
            nombre='Ana Ejemplo',
            rut='12345678-9',
            dependencia='AUTONOMO',
        )
        self.receta = Receta.objects.create(
            adulto_mayor=self.paciente,
            fecha_emision=date(2026, 10, 1),
            vigencia_meses=3,
        )

    def test_vencimiento_se_calcula_con_la_vigencia(self):
        self.assertEqual(self.receta.vencimiento(), date(2027, 1, 1))

    def test_formulario_de_evento_muestra_la_receta_bloqueada(self):
        response = self.client.get(reverse('crear_evento', args=[self.paciente.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Receta del 01/10/2026')
        self.assertContains(response, 'vence el 01/01/2027')
        self.assertContains(response, 'disabled')
        self.assertNotContains(response, 'Registrar receta')

    def test_formulario_ofrece_registrar_receta_solo_si_no_tiene(self):
        self.receta.delete()

        response = self.client.get(reverse('crear_evento', args=[self.paciente.id]))

        self.assertContains(response, 'aún no tiene recetas registradas')
        self.assertContains(response, 'Registrar receta')

    def test_renovacion_se_vincula_a_la_receta_del_paciente(self):
        response = self.client.post(
            reverse('crear_evento', args=[self.paciente.id]),
            {'tipo': 'RENOVACION', 'fecha': '2026-12-25'},
        )

        self.assertRedirects(response, reverse('lista_eventos'))
        evento = Evento.objects.get(tipo='RENOVACION')
        self.assertEqual(evento.receta, self.receta)

    def test_renovacion_usa_la_receta_mas_reciente(self):
        nueva = Receta.objects.create(
            adulto_mayor=self.paciente, fecha_emision=date(2026, 11, 1), vigencia_meses=6,
        )

        self.client.post(
            reverse('crear_evento', args=[self.paciente.id]),
            {'tipo': 'RENOVACION', 'fecha': '2026-12-25'},
        )

        self.assertEqual(Evento.objects.get(tipo='RENOVACION').receta, nueva)

    def test_renovacion_sin_recetas_muestra_error(self):
        self.receta.delete()

        response = self.client.post(
            reverse('crear_evento', args=[self.paciente.id]),
            {'tipo': 'RENOVACION', 'fecha': '2026-12-25'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'no tiene recetas registradas')
        self.assertFalse(Evento.objects.filter(tipo='RENOVACION').exists())

    def test_renovacion_ignora_receta_de_otro_paciente(self):
        otro = AdultoMayor.objects.create(
            nombre='Otro Paciente', rut='11111111-1', dependencia='AUTONOMO',
        )
        receta_ajena = Receta.objects.create(
            adulto_mayor=otro, fecha_emision=date(2026, 9, 1), vigencia_meses=2,
        )

        self.client.post(
            reverse('crear_evento', args=[self.paciente.id]),
            {'tipo': 'RENOVACION', 'fecha': '2026-12-25', 'receta': str(receta_ajena.id)},
        )

        self.assertEqual(Evento.objects.get(tipo='RENOVACION').receta, self.receta)

    def test_se_puede_cambiar_la_receta_de_una_renovacion(self):
        nueva = Receta.objects.create(
            adulto_mayor=self.paciente, fecha_emision=date(2026, 11, 1), vigencia_meses=6,
        )
        evento = Evento.objects.create(
            adulto_mayor=self.paciente, tipo='RENOVACION',
            fecha=date(2026, 12, 25), receta=self.receta,
        )

        response = self.client.post(
            reverse('cambiar_receta', args=[evento.id]),
            {'receta': str(nueva.id)},
        )

        self.assertRedirects(response, reverse('lista_eventos'))
        evento.refresh_from_db()
        self.assertEqual(evento.receta, nueva)

    def test_no_se_cambia_la_receta_de_eventos_que_no_son_renovacion(self):
        evento = Evento.objects.create(
            adulto_mayor=self.paciente, tipo='CITA', fecha=date(2026, 12, 25),
        )

        response = self.client.get(reverse('cambiar_receta', args=[evento.id]))

        self.assertRedirects(response, reverse('lista_eventos'))

    def test_registrar_receta_con_medicamentos(self):
        medicamento = Medicamento.objects.create(
            adulto_mayor=self.paciente, nombre='Losartán', dosis='50mg cada 12 horas',
        )

        response = self.client.post(
            reverse('registrar_receta', args=[self.paciente.id]),
            {
                'fecha_emision': '2026-11-15',
                'vigencia_meses': '6',
                'medicamentos': [str(medicamento.id)],
            },
        )

        self.assertRedirects(
            response,
            reverse('crear_evento', args=[self.paciente.id]),
        )
        receta = Receta.objects.get(fecha_emision=date(2026, 11, 15))
        self.assertEqual(receta.vigencia_meses, 6)
        self.assertEqual(list(receta.medicamentos.all()), [medicamento])

    def test_registrar_receta_invalida_no_guarda(self):
        response = self.client.post(
            reverse('registrar_receta', args=[self.paciente.id]),
            {'fecha_emision': 'no-es-fecha', 'vigencia_meses': '99'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ingresa una fecha de emisión válida.')
        self.assertEqual(Receta.objects.count(), 1)

    def test_retiro_cumplido_crea_receta_y_la_vincula_a_la_renovacion(self):
        retiro = Evento.objects.create(
            adulto_mayor=self.paciente, tipo='RETIRO',
            fecha=date(2026, 10, 25), vigencia_meses=3,
        )

        self.client.post(reverse('marcar_realizada', args=[retiro.id]))

        renovacion = Evento.objects.get(tipo='RENOVACION')
        self.assertEqual(renovacion.fecha, date(2027, 1, 18))
        self.assertEqual(renovacion.receta.fecha_emision, date(2026, 10, 25))
        self.assertEqual(renovacion.receta.vigencia_meses, 3)
