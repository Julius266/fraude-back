# Ejemplos de Referencia para Scoring de Fraude en Siniestros

> **Uso en el sistema:** este archivo alimenta la IA de auditoria (`AIScoringService`) como biblioteca
> de casos adicionales de fraude y contraejemplos. No reemplaza el expediente real: sirve para
> calibrar las senales RF-01..RF-07 comparando patrones similares.

Este documento define el comportamiento esperado del modelo al evaluar cada regla de fraude.
Para cada regla se presenta un caso que NO la activa y un caso que SI la activa, con la justificación de la decision.

Las reglas se dividen en dos niveles de severidad:
- Clasificacion ROJO: indica fraude probable o evidencia directa. Requiere derivacion inmediata a investigacion especial.
- Clasificacion AMARILLO: indica señal de alerta que debe sumarse al score general para evaluacion.


## RF-01 | Cobertura Perdida Total por Robo (PTxRB)
Clasificacion: ROJO

Descripcion de la regla: Esta regla se activa unicamente cuando la cobertura del siniestro es Perdida Total por Robo. No importa el contexto ni los detalles del caso. Si la cobertura es PTxRB, la regla activa automaticamente.

CASO QUE NO ACTIVA RF-01:

Siniestro: SIN-2024-101
Cobertura: Danos al Vehiculo por colision
Descripcion: El asegurado Juan Perez reporto el 10/04/2024 un choque frontal en la Av. Amazonas. El vehiculo presento danos en capo y parachoques delantero. El vehiculo fue evaluado fisicamente en taller autorizado.
Monto reclamado: 3200 USD

Razon por la que NO activa RF-01: La cobertura es danos por colision, no perdida total por robo. El vehiculo fue recuperado y evaluado fisicamente. RF-01 no aplica.


CASO QUE SI ACTIVA RF-01:

Siniestro: SIN-2024-102
Cobertura: Perdida Total por Robo (PTxRB)
Descripcion: El asegurado reporta que su vehiculo Toyota Hilux 2022 fue sustraido el 02/05/2024 en el parqueadero de un centro comercial. No hay testigos ni camaras que confirmen el evento. El vehiculo no ha sido recuperado.
Monto reclamado: 28500 USD (suma asegurada completa)

Razon por la que SI activa RF-01: La cobertura declarada es explicitamente PTxRB. Todo siniestro con esta cobertura activa la regla en rojo sin excepcion, independientemente de otros factores.


## RF-02 | Falsificacion o Adulteracion Documental Evidente
Clasificacion: ROJO

Descripcion de la regla: Esta regla se activa cuando los documentos presentados muestran signos claros de alteracion. Los casos mas comunes son: factura con fecha anterior a la ocurrencia del siniestro, montos con trazos superpuestos o corregidos, firmas duplicadas o inconsistentes, o documentos ilegibles de forma intencional.

CASO QUE NO ACTIVA RF-02:

Siniestro: SIN-2024-201
Fecha de ocurrencia: 17/03/2024
Documentos recibidos:
  Denuncia policial emitida el 18/03/2024
  Informe pericial firmado el 20/03/2024
  Factura de reparacion emitida el 25/03/2024 por Taller Automotriz Norte
Observacion: Todos los documentos tienen fechas posteriores al evento y coherentes entre si. Sin alteraciones visibles.

Razon por la que NO activa RF-02: La cronologia es logica. La denuncia es posterior al evento, la pericia es posterior a la denuncia, y la factura es posterior a la pericia. No hay inconsistencias ni signos de adulteracion.


CASO QUE SI ACTIVA RF-02:

Siniestro: SIN-2024-202
Fecha de ocurrencia: 15/03/2024
Documentos recibidos:
  Factura de reparacion emitida el 10/03/2024 por Taller Centro
  Monto en factura: campo con trazos superpuestos, valor original aparente 1800 USD, valor modificado 4800 USD
Observacion: La factura tiene fecha cinco dias anterior al siniestro. El campo de monto total presenta alteracion visible.

Razon por la que SI activa RF-02: La factura fue emitida antes de que ocurriera el siniestro, lo cual es imposible en condiciones normales. Ademas el monto presenta alteracion fisica evidente. Ambas condiciones por separado ya activan la regla.


## RF-03 | Coincidencia con Lista Restrictiva
Clasificacion: ROJO

Descripcion de la regla: Esta regla se activa cuando cualquiera de las partes del siniestro aparece en la lista restrictiva interna. Las partes a verificar son: el asegurado, el beneficiario, y el proveedor o taller (APS). Basta con que una sola parte este en la lista para activar la regla.

CASO QUE NO ACTIVA RF-03:

Siniestro: SIN-2024-301
Asegurado: Maria Fernanda Castro, ID ASG-0024891
Beneficiario: Maria Fernanda Castro (misma persona)
Taller asignado: Automotores del Norte S.A., RUC 1791234560001
Verificacion lista restrictiva:
  Asegurado: no encontrado
  Beneficiario: no encontrado
  Taller: no encontrado

Razon por la que NO activa RF-03: Ninguna de las tres partes aparece en la lista restrictiva. La regla no aplica.


CASO QUE SI ACTIVA RF-03:

Siniestro: SIN-2024-302
Asegurado: Roberto Salinas, ID ASG-0031045
Beneficiario: Taller Express Cars, RUC 1760987430001
Verificacion lista restrictiva:
  Asegurado: no encontrado
  Taller Express Cars: ENCONTRADO en lista restrictiva por participacion confirmada en cuatro siniestros fraudulentos entre 2022 y 2023

Razon por la que SI activa RF-03: El taller beneficiario esta en la lista restrictiva. Aunque el asegurado sea legitimo, la presencia de cualquier parte en la lista activa la regla de forma inmediata.


## RF-04 | Dinamica del Accidente Fisicamente Imposible
Clasificacion: ROJO

Descripcion de la regla: Esta regla se activa cuando la descripcion del evento es incompatible con los danos fisicos observados en el vehiculo. El modelo debe evaluar si la ubicacion de los danos es coherente con la direccion y tipo de impacto declarado.

CASO QUE NO ACTIVA RF-04:

Siniestro: SIN-2024-401
Descripcion del evento: El vehiculo asegurado estaba detenido en un semaforo y fue impactado por detras por un taxi.
Danos reportados: paragolpes trasero hundido, tapa de maletero deformada, luz trasera derecha rota.
Evaluacion pericial: danos consistentes con impacto posterior de baja velocidad. Coherente con el relato.

Razon por la que NO activa RF-04: Los danos estan en la parte trasera del vehiculo, que es exactamente donde corresponde un impacto por detras. La dinamica es fisicamente coherente.


CASO QUE SI ACTIVA RF-04:

Siniestro: SIN-2024-402
Descripcion del evento: El asegurado reporta que otro vehiculo lo impacto por la parte trasera mientras estaba estacionado.
Danos reportados: paragolpes delantero destruido, capo hundido, radiador danado. Sin danos en parte trasera.
Evaluacion pericial: todos los danos se concentran en el frente del vehiculo. No existe ninguna marca de impacto en la parte trasera.

Razon por la que SI activa RF-04: Un impacto trasero no puede producir danos exclusivamente en el frente del vehiculo. La contradiccion entre el relato y la evidencia fisica es directa e inexplicable por condiciones normales del accidente.


## RF-05 | Siniestro al Borde de Vigencia (menos de 48 horas)
Clasificacion: AMARILLO

Descripcion de la regla: Esta regla se activa cuando el siniestro ocurre dentro de las primeras 48 horas desde el inicio de la poliza, o dentro de las ultimas 48 horas antes de su vencimiento. Se debe calcular la diferencia en horas entre la fecha de inicio o fin de vigencia y la fecha de ocurrencia.

CASO QUE NO ACTIVA RF-05:

Siniestro: SIN-2024-501
Fecha inicio poliza: 01/01/2024
Fecha ocurrencia: 15/03/2024
Horas desde inicio de vigencia: 1752 horas (73 dias)
Fecha vencimiento poliza: 31/12/2024
Horas antes del vencimiento: 6984 horas (291 dias)

Razon por la que NO activa RF-05: El siniestro ocurre en la mitad del periodo de vigencia, a mas de 1700 horas del inicio y a mas de 6900 horas del vencimiento. Ninguno de los dos umbrales de 48 horas se supera.


CASO QUE SI ACTIVA RF-05:

Siniestro: SIN-2024-502
Fecha inicio poliza: 10/05/2024 hora 00:00
Fecha ocurrencia: 10/05/2024 hora 18:45
Horas desde inicio de vigencia: 18.75 horas
Descripcion: El asegurado reporta robo del vehiculo el mismo dia en que contrato la poliza.

Razon por la que SI activa RF-05: El siniestro ocurrio 18.75 horas despues del inicio de la poliza, por debajo del umbral de 48 horas. Esto sugiere posible contratacion con conocimiento previo del evento o premeditacion del reclamo.


## RF-06 | Demora Atipica en Denuncia de Robo (mas de 4 dias)
Clasificacion: AMARILLO

Descripcion de la regla: Esta regla aplica unicamente a siniestros de tipo robo. Se activa cuando el asegurado tarda mas de 4 dias (96 horas) en presentar la denuncia formal ante las autoridades, contando desde la fecha de ocurrencia del robo.

CASO QUE NO ACTIVA RF-06:

Siniestro: SIN-2024-601
Tipo: robo de vehiculo
Fecha de ocurrencia: 22/04/2024 hora 23:00
Fecha de denuncia policial: 23/04/2024 hora 09:30
Horas transcurridas: 10.5 horas

Razon por la que NO activa RF-06: La denuncia se realizo aproximadamente 10 horas despues del robo. Esta dentro del rango normal y muy por debajo del umbral de 96 horas.


CASO QUE SI ACTIVA RF-06:

Siniestro: SIN-2024-602
Tipo: robo de vehiculo
Fecha de ocurrencia: 05/06/2024
Fecha de denuncia policial: 12/06/2024
Dias transcurridos: 7 dias (168 horas)
Justificacion del asegurado: esperaba que el vehiculo apareciera por sus propios medios y estaba de viaje.

Razon por la que SI activa RF-06: La denuncia tardio 168 horas, casi el doble del umbral de 96 horas. La justificacion presentada no es suficiente para explicar la demora en un caso de robo de vehiculo, donde la denuncia oportuna es un requisito habitual de las autoridades y de la aseguradora.


## RF-07 | Narrativa Identica o Clonada
Clasificacion: AMARILLO

Descripcion de la regla: Esta regla se activa cuando la descripcion textual del evento tiene una similitud igual o superior al 85% con la narrativa de otro siniestro ya registrado en el sistema, correspondiente a una poliza o asegurado diferente. Una similitud del 85% al 100% entre siniestros distintos es estadisticamente improbable en condiciones normales y sugiere uso de una plantilla de relato compartida.

CASO QUE NO ACTIVA RF-07:

Siniestro: SIN-2024-701
Narrativa: El dia 03/07/2024 aproximadamente a las 14:30, el asegurado conducia su vehiculo por la Av. Republica y al llegar a la interseccion con Av. Naciones Unidas, un vehiculo Hyundai azul invadio el carril contrario impactando el costado derecho. El conductor del otro vehiculo se detuvo y se intercambiaron datos de contacto e identificacion.
Similitud maxima encontrada en base de datos: 31%

Razon por la que NO activa RF-07: La narrativa contiene detalles especificos como nombre de calles, hora exacta, color y marca del vehiculo tercero, y descripcion de la interaccion posterior. La similitud con otros siniestros es baja (31%), bien por debajo del umbral del 85%.


CASO QUE SI ACTIVA RF-07:

Siniestro: SIN-2024-702
Narrativa: Circulaba por la avenida principal cuando un vehiculo de color rojo cruzo el semaforo en rojo impactando el frente de mi auto. El conductor huyo del lugar sin identificarse. No hubo testigos presenciales y las camaras de seguridad del sector no funcionaban.

Siniestro de referencia en base de datos: SIN-2024-389, registrado dos meses antes con distinto asegurado
Narrativa de referencia: Circulaba por la avenida principal cuando un vehiculo de color rojo cruzo el semaforo en rojo impactando el frente de mi auto. El conductor huyo del lugar sin identificarse. No hubo testigos presenciales y las camaras de seguridad del sector no funcionaban.

Similitud textual detectada: 97%

Razon por la que SI activa RF-07: La narrativa es practicamente identica a la de otro siniestro de un asegurado diferente. Una coincidencia del 97% entre dos relatos independientes es estadisticamente imposible de forma casual. Indica uso de una plantilla de fraude compartida entre reclamantes.


## Referencia rapida de condiciones de activacion

RF-01: cobertura del siniestro es PTxRB. Clasificacion ROJO.
RF-02: documento con fecha anterior al evento, o monto con alteracion visible. Clasificacion ROJO.
RF-03: asegurado, beneficiario o taller aparece en lista restrictiva. Clasificacion ROJO.
RF-04: ubicacion de los danos fisicos es incompatible con la dinamica declarada. Clasificacion ROJO.
RF-05: siniestro ocurre dentro de las primeras o ultimas 48 horas de vigencia de la poliza. Clasificacion AMARILLO.
RF-06: en siniestros de robo, denuncia policial presentada despues de 96 horas del evento. Clasificacion AMARILLO.
RF-07: narrativa con similitud mayor o igual al 85% respecto a otro siniestro de diferente asegurado. Clasificacion AMARILLO.

## Escala de color segun puntaje total (score)

| Puntaje | Color   | Banda | Interpretacion |
|---------|---------|-------|----------------|
| 0-35    | Verde   | Bajo  | Riesgo bajo, triaje estandar |
| 36-70   | Amarillo| Medio | Alertas moderadas, revision documental |
| 71+     | Rojo    | Alto  | Fraude probable, investigacion urgente |

A mayor puntaje acumulado por reglas activas, mayor probabilidad de fraude.
