from django.contrib import admin
from .models import AdultoMayor, CuidadorHogar, Celular, Medicamento, Receta, Evento

admin.site.register([AdultoMayor, CuidadorHogar, Celular, Medicamento, Receta, Evento])
