# XRAY: el scoring explicado en simple

Versión larga y sin jerga de lo que hace el sistema de scoring. Para entenderlo de verdad, para
contarlo delante del jurado, y para saber dónde te pueden pinchar.

Aquí hay pocos números a propósito. Los números exactos (anclas, pesos, constantes, métricas)
están en [`docs/scoring.md`](scoring.md), que es la referencia de lo que hay en el código. Esto es
el modelo mental.

---

## 0. Qué es esto, en una frase

XRAY coge el rastro financiero de un grupo empresarial —movimientos bancarios, facturas emitidas
y recibidas, deuda— y lo convierte en un número de 0 a 100 que dice cómo está de salud financiera
ese grupo, mes a mes. Y, junto al número, la explicación de por qué sale ese número.

### La distinción que hay que tener clara desde el principio

**Esto no es un modelo de machine learning.**

No hemos cogido empresas que quebraron y empresas que no, entrenado un XGBoost y obtenido *"esta
empresa tiene un 17,3% de probabilidad de impago"*. No hay entrenamiento, no hay fichero de
modelo, no hay nada aprendido.

Lo que hay es una **scorecard determinista e interpretable**. Fórmulas, curvas y pesos escritos a
mano y congelados. Con los mismos datos de entrada sale siempre exactamente el mismo resultado,
hoy y dentro de un año.

Eso no es una limitación disimulada, es una decisión con dos motivos:

1. Hay muy pocos grupos con algo parecido a una etiqueta. Un modelo ajustado sobre tan poco se los
   memoriza y luego no generaliza.
2. Un número que no se puede explicar no se puede poner delante de un cliente al que le vas a
   denegar una línea de crédito.

### Las tres capas, que hay que mantener separadas en la cabeza

```
datos → indicadores → subscores → pilares → NIVEL 0-100      ¿dónde está?
                                       ↓
                          nivel histórico → TRAYECTORIA y alertas   ¿hacia dónde va?
                                       ↓
                          score vs eventos futuros → VALIDACIÓN     ¿esto sirve para algo?
```

- El **nivel** describe dónde está la empresa ahora.
- La **trayectoria** describe cómo se está moviendo. No entra en el nivel.
- La **validación** comprueba si ese nivel contiene información sobre problemas futuros.

Mezclar las tres es el error más común al contarlo. Si alguien pregunta "¿el score predice la
quiebra?", la respuesta empieza por separar estas tres cosas.

---

## 1. Qué entra: del caos al panel

Tienes miles de movimientos bancarios y miles de facturas. Antes de puntuar nada hay que
convertir ese caos en una representación financiera consistente.

### La unidad es el grupo, mes a mes

No una transacción. Ni siquiera una empresa suelta. La fila básica es **un grupo empresarial en un
mes concreto**.

Si un grupo tiene varias sociedades, **primero se suman los importes y después se calculan los
ratios**. Ese orden importa mucho:

> Imagina un grupo con una empresa enorme y una empresa diminuta.
> Si calculas un score a cada una y luego haces la media, la pequeña pesa lo mismo que la grande.
> Económicamente eso es absurdo.
> Sumando primero los flujos, el grupo se comporta como la unidad económica que realmente es.

Aun así también se calcula un score **por compañía**, con exactamente el mismo código. ¿Por qué?
Porque una filial podrida puede quedar escondida dentro de un grupo sano, y el que presta dinero
quiere saberlo. Y además se puede recalcular el grupo quitando cada compañía, para ver cuánto
estaba tirando cada una hacia abajo.

### Flujo operativo no es "el dinero que entró"

Esta es una de las decisiones más importantes de todo el sistema.

Supón que una empresa recibe un préstamo de medio millón. Ese mes entra muchísimo dinero al banco.
¿Significa que el negocio va estupendamente? **No.** Significa que se ha endeudado.

Por eso, cuando XRAY habla de entradas y salidas operativas, deja fuera las cosas que no son
negocio: transferencias entre cuentas propias, movimientos de inversión, retiradas de efectivo,
devoluciones de préstamo e intereses.

La deuda no se ignora, se mira aparte, en su propio pilar. Así se evita el titular falso:

> "Qué bien funciona esta empresa, ha ingresado medio millón."

cuando lo único que ha pasado es que ha pedido prestado medio millón.

### Las facturas se reconstruyen en el tiempo

Una factura hoy pone `paid`. Pero eso es lo que sabemos *hoy*. En marzo estaba pendiente, y en
marzo el sistema tiene que ver que estaba pendiente.

Por eso las facturas se reconstruyen mes a mes usando sus fechas de emisión, vencimiento y pago.
No se coge el estado actual y se asume que siempre fue así. Esto va a importar mucho cuando
hablemos de leakage.

Lo mismo con la caja: el fichero de saldos es una foto del último día del dataset, así que el saldo
de los meses anteriores se reconstruye hacia atrás a partir de los movimientos.

### La regla de oro: nada del futuro

Una fila del mes `t` solo puede leer datos de meses anteriores o iguales a `t`. Todas las ventanas
móviles miran hacia atrás, nunca hacia delante.

Esto no es una intención, está comprobado: el sistema puede reproducir el dataset mes a mes, como
si fuese llegando en tiempo real, y verificar que el score que un mes recibe en vivo es
exactamente el mismo que tiene en la ejecución completa. Si hubiese contaminación del futuro, esos
dos números no cuadrarían.

---

## 2. Los nueve indicadores

Ya tenemos el panel mensual limpio. Pero todavía no podemos decir "empresa = 73/100". Primero se
calculan nueve indicadores financieros, agrupados en cinco pilares.

Un detalle transversal: las ventanas se cuentan en **meses con datos**. Si un grupo tiene un hueco
sin actividad, el hueco se salta; no se rellena con ceros, porque un cero es una afirmación y un
hueco no lo es.

---

### Pilar 1 · Liquidez

El más importante de los cinco. Tiene dos indicadores que miden cosas distintas.

**Días de colchón (`buffer_days`)**

La idea es todo lo intuitiva que se puede pedir:

> ¿Cuántos días podría seguir pagando sus gastos operativos esta empresa con la caja que tiene?

Es, simplificando, caja disponible dividida entre gasto diario.

Ejemplo: si tienes 300.000 € de caja y gastas 150.000 € al mes, estás gastando unos 5.000 € al
día. 300.000 entre 5.000 son **60 días de colchón**: unos dos meses de gasto cubiertos.

Lo que **no** significa: "quiebras dentro de 60 días". Es un colchón, no una cuenta atrás.

Dos detalles de construcción que suenan a manía y son importantes:

- Tanto la caja como el gasto van promediados a tres meses. Así un mes con una entrada gorda o un
  pago extraordinario solo mueve el indicador un tercio de lo que lo movería.
- El gasto diario se calcula desde la media mensual, no dividiendo una suma trimestral entre 91
  días. Si no, los primeros meses de historia de una empresa saldrían inflados porque la ventana
  todavía no está llena.

**Proporción de meses en negativo (`negative_cash_share`)**

Todavía más simple. Mira los últimos tres cierres de mes y pregunta: ¿en cuántos estuve en
descubierto?

Ninguno de tres → cero. Uno de tres → un tercio. Los tres → uno.

Hay un detalle fino: el umbral no es "por debajo de cero" sino "por debajo de un euro negativo".
Suena arbitrario y no lo es: una cuenta vaciada del todo reconstruye a un número
infinitesimalmente positivo o negativo según en qué orden se sumen los movimientos. Con un umbral
en cero exacto, medio dataset dispararía por ruido de redondeo.

> Los dos juntos: **`buffer_days` mide colchón. `negative_cash_share` mide persistencia del
> descubierto.** Una empresa puede tener poco colchón y no haber entrado nunca en negativo, u
> otra puede tener colchón y estar entrando en números rojos todos los meses. Son señales
> distintas y por eso van las dos.

---

### Pilar 2 · Disciplina de pagos

Aquí miramos cómo paga la empresa a sus proveedores. AP viene de *accounts payable*, cuentas a
pagar.

**Días de retraso al pagar (`ap_days_late`)**

Cuando pago facturas, ¿con cuánto retraso las pago? Y —esto es lo que lo hace útil— **ponderado por
importe**.

Tiene todo el sentido: llegar veinte días tarde en una factura de veinte euros no puede pesar lo
mismo que llegar veinte días tarde en una de doscientos mil.

Otro detalle: se calcula como una única división de totales del trimestre, no como la media de los
porcentajes mensuales. Así, un mes en el que no se pagó casi nada no distorsiona la serie entera.

**Volumen vencido (`ap_overdue_months`)**

Compara lo que tengo vencido y sin pagar contra lo que normalmente pago cada mes. La lectura es
casi literal:

> ¿Cuántos meses de mi ritmo habitual de pagos llevo acumulados en facturas vencidas?

Si sale 2, debes el equivalente a dos meses de tu flujo normal de pagos. Eso ya no es un despiste
administrativo.

Hubo una versión anterior de este indicador que comparaba lo vencido con el total del libro
abierto, y se descartó por un motivo muy concreto del dataset: aquí las facturas impagadas no se
cierran nunca, así que ese ratio sube hacia uno para todo el mundo con el paso de los meses. Medía
el calendario, no la empresa.

---

### Pilar 3 · Generación de caja

Este pilar contesta una pregunta distinta a la de liquidez, y la diferencia es sutil pero central.

Una empresa puede tener caja porque levantó financiación, o porque acumuló dinero en años buenos.
Eso dice cómo está su balance. Aquí preguntamos otra cosa:

> ¿La actividad de hoy genera caja?

**Margen operativo (`op_margin`)**

Entradas operativas menos salidas operativas, dividido entre las entradas operativas. Si entra un
millón y salen ochocientos mil, el margen es del 20%.

Es una especie de margen de caja, no un margen contable: no hay amortizaciones ni provisiones,
solo dinero que se mueve.

Se calcula sobre seis meses y no sobre uno, porque los márgenes mensuales oscilan salvajemente
según cuándo caiga una factura gorda. Con seis meses la serie se comporta; con doce no se gana
nada adicional.

**Crecimiento de entradas (`inflow_growth`)**

Compara el ritmo reciente de ingresos con la referencia del último año: la media de los últimos
tres meses contra la media de los últimos doce.

Alrededor de 1 significa estable. 1,25 significa que el ritmo reciente va un 25% por encima de la
base anual. 0,5 significa que las entradas recientes están a la mitad.

Este indicador existe por un motivo muy concreto: **los ratios no ven un negocio que se encoge
proporcionalmente**. Si una empresa factura la mitad pero también gasta la mitad, todos los ratios
se quedan igual de bonitos mientras el negocio se deshace. Este sí lo ve.

---

### Pilar 4 · Cobros

El espejo exacto de pagos, del otro lado del balance. AR viene de *accounts receivable*, cuentas a
cobrar. Mismos dos indicadores, mismas fórmulas, cambiando "yo pago" por "me pagan".

La pregunta ahora es:

> ¿Mis clientes me están pagando tarde?

Y esto no es un detalle administrativo. Una empresa puede vender muchísimo, tener una cuenta de
resultados preciosa, y estar ahogada: si nadie le paga, lo que tiene no es un problema comercial,
es un problema de liquidez. De hecho esa es la forma más típica en que una empresa que crece se
muere.

---

### Pilar 5 · Carga de deuda

Un único indicador: **el servicio de deuda del año contra la entrada operativa del año**.

> ¿Qué proporción de todo lo que genera la empresa se está yendo en devolver principal e
> intereses?

Si entra mucho dinero pero una parte enorme va directa al banco, hay presión financiera aunque el
negocio funcione.

**Y aquí hay una decisión que el jurado puede preguntar: tener cero deuda no da 100 puntos. Da
75.**

¿Por qué? Porque no tener deuda significa que no tienes esa carga, y eso está bien. Pero no
demuestra que seas una empresa perfecta, ni que tengas capacidad de financiación, ni que un banco
te fuese a dar una línea si la necesitaras. Hay empresas sin deuda porque son sólidas y empresas
sin deuda porque nadie se la daría.

Equiparar *deuda cero* con *empresa perfecta* sería regalar la nota máxima por una ausencia de
información.

---

### Y si falta un indicador, falta

Si un grupo no tiene ERP conectado, no tiene facturas, y los cuatro indicadores de pagos y cobros
no se pueden calcular. No se ponen a cero: se marcan como ausentes. La sección 4 explica qué pasa
entonces, porque es una de las partes más importantes del diseño.

---

## 3. De ratios a puntos: las anclas

Aquí está la pieza central para entender el scoring.

Los nueve indicadores viven en escalas que no tienen nada que ver entre sí. Los días de colchón
van de 0 a varios cientos. El margen operativo va de negativo a 0,4. El crecimiento de entradas
ronda 1. **No se pueden promediar directamente**: sumar días con porcentajes no significa nada.

Así que cada indicador pasa por una **curva** que lo traduce a una escala común de 0 a 100.

### Cómo funciona una curva

Una curva se define con unos pocos puntos de referencia, las **anclas**. Por ejemplo, para los días
de colchón: cero días valen cero puntos, trece días valen treinta y cinco, veintisiete valen
sesenta, sesenta y dos valen ochenta y cinco, ciento veinte valen cien.

¿Y si una empresa tiene cuarenta días, que no es ninguna de las anclas? No hace falta un ancla en
cada valor posible: se interpola en línea recta entre las dos anclas que lo rodean. Cuarenta días
cae entre veintisiete (sesenta puntos) y sesenta y dos (ochenta y cinco puntos), así que sacará
algo entre sesenta y ochenta y cinco, proporcional a dónde caiga.

¿Y si tiene quinientos días de colchón? Tampoco saca cuatrocientos puntos. **La curva satura**:
máximo cien, mínimo cero. Tener un año y medio de colchón en vez de cuatro meses no te hace una
empresa cuatro veces mejor.

Las curvas de las cosas malas van al revés: cero días de retraso valen cien puntos, y a más
retraso menos puntos, hasta cero.

### La ventaja: se puede abrir y mirar dentro

Esto es lo que hace que el sistema sea explicable de verdad:

> "Tenías veintiocho días de colchón. Según estas anclas, que están escritas en el código y no han
> cambiado, eso son sesenta y un puntos."

No hay ninguna red neuronal escondida aprendiendo una función que nadie sabe describir. La
traducción de dato a puntos se puede leer, discutir y auditar línea a línea.

### La pregunta incómoda: ¿de dónde salen esas anclas?

Aquí hay que ser honesto, porque es el sitio por donde un jurado bueno va a entrar.

**No son umbrales científicos universales.** No digas eso, porque no lo son.

Lo que sí son, y hay que contarlo desglosado:

- Para los días de colchón, los cortes vienen de un estudio externo real del JPMorgan Chase
  Institute sobre días de buffer de caja en PYMEs. No nos los hemos inventado.
- Para los retrasos de pago y de cobro, vienen de la tabla Paydex de Dun & Bradstreet, que es el
  estándar del sector para traducir días de retraso a una escala de comportamiento.
- Para el resto, se colocaron mirando cómo se distribuían los 250 grupos del dataset, comprobando
  que la tasa de problemas fuese creciendo de forma ordenada al empeorar el indicador, y después se
  congelaron.

Eso es **calibración manual con criterio**, no entrenamiento estadístico. Y la defensa correcta es
justo esa:

> "Hay juicio de diseño, sí. Pero ese juicio está explicitado, versionado y es auditable, y donde
> existe una referencia externa la hemos usado en lugar de inventarnos un número. Si cambia el
> dominio —otro país, otro sector, datos reales en vez de sintéticos— haría falta recalibrar, y se
> recalibra tocando un solo fichero."

Eso es muchísimo más defendible que intentar venderlas como verdad universal. Si intentas lo
segundo y te preguntan por una sola de las anclas, se cae todo.

---

## 4. De indicadores a pilares, y el problema de la información que falta

Dentro de cada pilar se hace una media ponderada de sus indicadores. Los días de colchón pesan más
que los meses en negativo, el margen pesa más que el crecimiento, y pagos y cobros reparten a
partes iguales entre sus dos indicadores. Deuda solo tiene uno, así que el pilar es el indicador.

Hasta aquí es aritmética de instituto. Pero entonces aparece la pregunta interesante:

### ¿Qué pasa si falta información?

Una empresa sin ERP conectado no tiene facturas. No se puede saber cómo paga ni cómo cobra.

Una implementación perezosa haría lo obvio: *falta información, pues cero puntos*. Pero fíjate en
lo que eso está afirmando realmente:

> "No sé cómo pagas, luego pagas fatal."

Eso es sencillamente falso, y además castiga a la empresa por una carencia del dato, no por una
carencia suya.

Por eso XRAY deja esos indicadores como **ausentes** y **renormaliza los pesos** sobre lo que sí
está disponible. Si falta el pilar de cobros, el peso que le tocaba se reparte proporcionalmente
entre los demás. Si un pilar entero no tiene ningún indicador disponible, simplemente no existe
para esa empresa.

### Pero eso crea un problema nuevo: la cobertura

Imagina dos empresas:

- Empresa A: score 75, con toda la información disponible.
- Empresa B: score 75, con el 70% de la información disponible.

¿Son equivalentes? **No.** El número es 75 en las dos, pero detrás del segundo hay bastante menos
evidencia.

Por eso XRAY publica la **cobertura** pegada al score, siempre. Es la proporción del peso total que
estaba realmente disponible para calcular ese número.

La frase, que es una de las mejores del proyecto para decir en voz alta:

> "Ausencia de evidencia no es evidencia negativa. Pero sí reduce nuestra confianza en la
> comparabilidad del score, y por eso la cobertura viaja pegada al número en vez de esconderse."

### Un detalle sutil: todo disponible desde el primer mes

Todos los indicadores se calculan desde el primer mes con datos, aunque la ventana todavía no esté
llena.

¿Por qué? Porque si un pilar apareciese más tarde, movería el nivel por un motivo que no tiene
nada que ver con la empresa. Como el nivel es una media renormalizada, un pilar que entra por
debajo de los demás se lee exactamente igual que un deterioro real que no ha ocurrido. Sería una
alerta falsa fabricada por el propio sistema.

---

## 5. De pilares al score final

### Los pesos

Liquidez se lleva el 40%. Pagos y generación de caja, un 20% cada uno. Cobros y deuda, un 10% cada
uno.

Liquidez domina porque es la que mata empresas. Una empresa puede aguantar años con márgenes
malos; no aguanta tres meses sin poder pagar las nóminas.

### La fórmula, que parece rara y no lo es

El nivel no se escribe como una media ponderada al uso, sino así:

```
nivel = 50 + la suma de lo que aporta cada pilar respecto a 50
```

Y lo que aporta cada pilar es su peso multiplicado por lo que se separa de 50.

Un pilar en 50 aporta cero. Un pilar por encima de 50 empuja hacia arriba. Uno por debajo, hacia
abajo.

Matemáticamente **es exactamente la misma media ponderada de siempre**, solo que reescrita.
Entonces, ¿por qué escribirla así?

Porque escrita así, **la explicación es la propia fórmula**.

Puedes decir: liquidez está por encima de la media y aporta +9 puntos; generación está algo por
debajo y resta 1; cobros aporta +3. Y las sumas cuadran exactamente con el score final, hasta el
último decimal.

Esto **no es SHAP. No es una explicación post-hoc aproximada.** No es un modelo secundario que
intenta adivinar por qué el modelo principal dijo lo que dijo. Es el cálculo mismo, contado en voz
alta.

### Y de ahí sale gratis la mejor propiedad del sistema

Como el nivel es una suma, el cambio del nivel de un mes a otro **es exactamente la suma de los
cambios de cada aportación**.

Eso responde la pregunta cinco del reto —*por qué cambió el score*— sin aproximar nada y sin
inventar nada:

> "Bajaste 6 puntos. Cuatro vienen de liquidez y dos de cobros. Generación no se movió."

### El tope de seguridad

Hay una regla especial por encima de todo lo anterior. Si el pilar de liquidez o el de disciplina
de pagos está muy bajo, el score publicado no puede superar el punto medio de la escala, por buena
que sea la media ponderada.

¿Por qué? Porque sería absurdo enseñar como financieramente fuerte a una empresa que está en
situación extrema de caja o de impagos. Un pilar suspendido no se puede promediar hasta hacerlo
desaparecer detrás de cuatro pilares buenos.

Esto viene del principio CAMELS de la supervisión bancaria, donde un componente crítico en rojo
limita la calificación global por muy bien que estén los demás.

Si el jurado pregunta de dónde sale el umbral exacto, **no te inventes una teoría estadística**. La
respuesta buena es: es una regla explícita de producto, está escrita en un sitio donde cualquiera
la puede auditar, y apenas afecta a un puñado de casos extremos. La honestidad aquí vale más que
una justificación inventada.

### Y por último, los tres tramos

El número se acompaña de una etiqueta: sana, aguantando, o vulnerable. Un número suelto no le dice
nada a alguien que no conoce la escala.

---

## 6. Trayectoria: el nivel no es lo mismo que el movimiento

Esto es fundamental, y es lo que separa este proyecto de un cuadro de mandos cualquiera.

Una empresa tiene 72 puntos. Está bien, ¿no? ¿Y si viene de aquí?

```
92 → 87 → 82 → 76 → 72
```

Sigue siendo un 72 razonablemente alto. Pero lleva cuatro meses bajando escalones y nadie la ha
mirado, porque el semáforo sigue en verde.

Por eso existe una capa aparte que mira la serie histórica del nivel. **Y no entra en el score
principal**: el nivel describe dónde estás, la trayectoria describe hacia dónde vas, y mezclarlas
haría que ninguna de las dos significase nada.

La trayectoria se construye en tres pasos.

### Paso 1 · Suavizado

Primero se suaviza la serie con una media exponencial: cada mes pesa lo suyo, los anteriores pesan
menos, y los muy antiguos casi nada.

¿Por qué? Porque las finanzas mensuales tienen ruido de cojones. No quieres activar una sirena
porque un mes haya caído en viernes el pago de un proveedor grande.

La contrapartida hay que decirla en voz alta: **suavizar mete retraso**, alrededor de mes y medio.
Es el precio de no gritar por cualquier cosa, y es un intercambio consciente, no un descuido.

### Paso 2 · Pendiente robusta

Sobre los últimos seis valores suavizados se calcula una pendiente, pero no con una regresión
lineal normal. Se usa **Theil-Sen**: se calculan las pendientes entre todos los pares de puntos y
se coge la mediana.

La diferencia práctica es grande. En una regresión normal, un mes extremadamente raro tira de la
recta y puede inventarse una tendencia que no existe. Con la mediana, ese mes es un voto más entre
muchos y no puede destrozar nada.

El resultado sale en unidades que se entienden sin traducción: *menos dos puntos por mes*. Eso es
una caída persistente, y se puede decir tal cual.

### Paso 3 · Acumuladores de desviación (CUSUM)

La pendiente mide inclinación. Los acumuladores buscan otra cosa distinta: **cambios persistentes
de régimen**.

La idea: cada mes se compara el nivel suavizado con lo que era normal para esa empresa en los
últimos meses, y la diferencia se va acumulando. Con una holgura, para que las desviaciones
pequeñas se perdonen y el acumulador vuelva a cero solo.

Pero si empiezas a desviarte sistemáticamente hacia abajo —un poquito, otro poquito, otro
poquito, otro poquito— **el acumulador acaba saltando aunque ningún mes por separado haya sido
llamativo**. Eso es exactamente el tipo de deterioro que se le escapa a un humano mirando un
gráfico: nunca hay un mes malo, solo hay veinte meses ligeramente peores.

Hay **dos** acumuladores, uno hacia abajo y otro hacia arriba, porque deterioro y mejora son
señales distintas y el reto pide explícitamente las dos direcciones. Detectar que alguien pasa de
45 a 65 es tan valioso como detectar que cae de 82 a 68, y muchas veces es mejor negocio.

Y si la pendiente se da la vuelta con fuerza, se limpia el acumulador contrario: una empresa que se
recupera de verdad no debe seguir arrastrando la alarma vieja.

Una vez que salta, la alarma **queda enganchada** hasta que el acumulador vuelve del todo a cero.
No parpadea. Una alerta que aparece y desaparece cada mes no la atiende nadie.

### Los estados que salen de todo esto

| Estado | Qué significa |
|---|---|
| `falling` | está cayendo y ya está en zona baja |
| `bending` | **está cayendo pero todavía parece sana** |
| `improving` | está subiendo de forma sostenida |
| `healthy` | sin alarma y en zona alta |
| `stable` | sin alarma, en zona media |
| `weak` | sin alarma, pero en zona baja |
| `not_enough_data` | menos de seis meses de historia |

**`bending` es la joya de la corona.** Es literalmente la pregunta 3 del reto: la empresa que va de
82 a 68 y sigue teniendo cara de sana. Ningún umbral fijo la detecta, porque 68 sigue siendo un
número bueno. Solo la detecta una capa que mira el movimiento y no el nivel.

Y `not_enough_data` importa tanto como los demás: con menos de seis meses, el sistema **dice que no
sabe** en vez de inventarse una tendencia. Un producto que admite lo que no sabe es más creíble que
uno que siempre tiene respuesta.

Además, cada alarma guarda **el mes en el que empezó a acumularse**, no el mes en el que saltó. Eso
es lo que permite decir "esto venía de marzo" y lo que hace medible la anticipación.

### Honestidad sobre la trayectoria

Esto está medido y conviene decirlo tú antes de que lo pregunten: **la tendencia no añade poder
predictivo sobre el nivel**. Las empresas que caen en mitad de la banda no acaban peor que las
demás, y combinar nivel con tendencia para predecir el nivel futuro funciona peor que el nivel
solo.

La tendencia es una **descripción**, no un segundo predictor. Sirve para contar lo que está
pasando, para ordenar la cola de alertas y para saber a quién llamar primero. No sirve para
mejorar la ordenación de riesgo, y venderla como si lo hiciera sería mentir sobre un número que
está a un experimento de distancia de ser refutado.

Lo que sí está medido es la anticipación sobre el nivel: en los grupos que acabaron entrando en
caja negativa después de meses limpios, el nivel llevaba varios meses por debajo de su máximo antes
de que pasara nada, y la alarma saltó con una mediana de medio año de antelación en la gran
mayoría de ellos.

---

## 7. Los saltos: ¿bache o caída?

Además de la tendencia hay un detector de saltos, que resuelve un caso que la tendencia no ve. Por
ejemplo:

```
72 → 73 → 71 → 72 → 54
```

Eso no es una tendencia progresiva. Ahí ha pasado *algo*, de golpe, y esperar seis meses a que una
pendiente lo confirme sería absurdo.

**Cuándo salta**: cuando el cambio de un mes supera a la vez un mínimo absoluto y la volatilidad
histórica propia de ese grupo. Las dos condiciones hacen falta. Un grupo que siempre se mueve poco
salta con menos; uno que es volátil de por sí necesita más para que sea noticia. Un umbral fijo
igual para todos llenaría la cola de alertas de las empresas ruidosas.

Y esto salta **sin retraso**, sobre el nivel sin suavizar, precisamente porque para esto el
suavizado estorba.

### Y aquí está lo más elegante del sistema

El salto se publica como **provisional**.

Dos meses después, el sistema vuelve a mirar:

- Si se recuperó buena parte del movimiento → era un **bache**.
- Si la máquina de estados sigue alarmando en la misma dirección → era un **cambio sostenido**.

¿Por qué hacerlo así? Porque **el mismo día del salto es imposible saber si es ruido o cambio
estructural**. Nadie puede. Un cliente que paga con dos meses de retraso y un cliente que ha dejado
de pagar se ven exactamente igual el primer mes.

Fingir lo contrario sería usar información del futuro para describir una alerta del pasado, que es
la trampa de evaluación más típica del mundo: mirar los datos completos, ver cuáles fueron baches
de verdad, y presumir de haberlos distinguido en el momento.

Aquí el sistema hace lo que haría un analista honesto: **avisa ya, y confirma después**. Y guarda
las dos cosas por separado, para que se vea qué sabía en cada momento.

Esto responde directamente a la pregunta 4 del reto.

### El otro tipo de alerta

También se avisa cuando la máquina de estados entra en alarma desde la calma, o cambia de
dirección.

Pero pasar de "doblándose" a "cayendo" **no** genera una alerta nueva: es la misma caída cruzando
una línea, no una noticia. Si no, el sistema avisaría dos veces del mismo problema y el usuario
aprendería a ignorarlo.

Cada alerta lleva desde cuándo viene, qué nivel tenía entonces y cuál tiene ahora, y los dos
pilares que más se movieron en ese intervalo. O sea: no solo *qué* pasó, sino *por qué*.

---

## 8. La validación: ¿esto sirve para algo?

Hasta ahora no hemos predicho nada. Tenemos una scorecard que describe. Ahora toca la pregunta
incómoda: **¿este número contiene información sobre problemas futuros, o es un adorno bonito?**

### Primer problema: no hay quiebras

El dataset es sintético y no trae ninguna etiqueta de impago. No podemos validar "¿predice el
concurso de acreedores?" porque en estos datos no hay concursos.

Así que se construyen **eventos proxy**: cosas malas y observables que pasan en los seis meses
siguientes.

- La caja del grupo se va por debajo de cero en alguno de esos meses.
- Desaparece el pago de nóminas en una empresa que llevaba meses pagándolas.
- Los ingresos se desploman a menos de la mitad.

Y uno combinado, que junta la caja negativa con la nómina desaparecida, como aproximación a
"empresa en apuros de verdad".

**Esto es crítico y hay que repetirlo**: estos eventos **nunca entran como ingrediente del score**.
Son una regla de medir, no un dato de entrada. Si se colaran dentro, todo lo que viene después
sería un espejismo.

### El resultado principal, y cómo no presentarlo

El número que sale es un **AUC de 0,910** para la caja negativa futura, en grupos que el sistema
no vio al ajustar nada.

Aquí es donde alguien puede meter la pata delante del jurado. Lo que ese número **NO** significa:

- No significa "acertamos el 91% de las empresas".
- No significa "tenemos un 91% de accuracy".
- No significa "con este score sabemos la probabilidad de impago de esta empresa".

Lo que **sí** significa, dicho de la forma intuitiva:

> Si coges al azar una empresa que va a tener el problema y otra que no, hay un 91% de
> probabilidad de que el score ponga a la mala en peor posición que a la buena.

Eso es **ordenación**. Es discriminación, ranking, "sé a quién llamar primero". **No es
calibración**: el sistema no dice, ni puede decir, "score 30 significa 70% de probabilidad de
problema". Para eso haría falta un paso de calibración que no existe en el proyecto.

Y la historia cambia muchísimo según el evento. La caja negativa se ordena muy bien. El combinado
de apuros razonablemente. La desaparición de nóminas, a duras penas. El desplome de ingresos,
directamente no: ese no se lee en el rastro bancario con este score.

Decir tú esos tres números peores vale más que esconderlos, porque un jurado técnico los va a
pedir.

### La ablación: el punto donde te pueden pinchar de verdad

Un jurado técnico bueno va a mirar esto. Consiste en quitar un pilar entero y repetir la medición.

Los resultados, en palabras:

- **Sin liquidez, el sistema se hunde.** Pasa de ordenar muy bien a ordenar poco mejor que una
  moneda al aire. Liquidez es el motor.
- **Sin deuda, prácticamente igual.** Aporta muy poco a este objetivo concreto.
- **Y lo incómodo: sin pagos, sin cobros o sin generación de caja, el AUC sube un poco.**

Es decir: **para este objetivo concreto, quitar tres de los cinco pilares mejora la métrica.**

#### "¿Entonces el score está mal?"

No necesariamente. Pero hay que contestarlo bien, y sin trampa.

Lo que la ablación demuestra es que liquidez es el motor predictivo de *la caja negativa futura*, y
que los otros tres pilares están ahí por otra razón: cobertura conceptual y capacidad de
explicación.

Piénsalo desde el producto. Un sistema que dice "tu score es 41" y solo sabe hablar de caja no le
sirve a nadie. El usuario necesita saber que el problema es que sus clientes le pagan a sesenta
días, o que lleva medio año con margen negativo, porque **eso es sobre lo que puede actuar**. Y eso
vive en los pilares que, según la ablación, "sobran".

Lo que **no puedes decir de ninguna manera**: "los cinco pilares mejoran el AUC". Los resultados
dicen literalmente lo contrario para tres de ellos, están medidos, y si lo afirmas y alguien mira
la tabla, pierdes toda la credibilidad de golpe.

Lo que **sí puedes decir**, que además es más fuerte:

> "Si la competición fuese exclusivamente predecir caja negativa futura, la versión ganadora sería
> una mucho más concentrada en liquidez. Lo sabemos porque lo hemos medido y lo hemos publicado
> nosotros. Hemos elegido conscientemente pagar un poco de AUC a cambio de un score que se puede
> explicar y sobre el que se puede actuar, porque el entregable no es el AUC: es un producto."

Esa respuesta convierte el punto débil en una decisión de diseño consciente. Que es lo que es.

### Por qué liquidez funciona tan bien: la limitación grande

Aquí está la mayor limitación de toda la validación, y también conviene decirla tú.

Piénsalo despacio:

- Lo que intentamos detectar: **caja negativa dentro de seis meses**.
- Lo que hay dentro del pilar de liquidez: **caja actual respecto al gasto**.

Pues claro que están muy relacionados. Si hoy tienes ocho días de colchón, tienes muchísimas
papeletas de entrar en negativo pronto. Eso no es una predicción brillante, es casi una
tautología con retraso.

Hay una **dependencia conceptual** entre el predictor y el objetivo. No es leakage temporal —no se
está mirando el futuro, eso está comprobado— pero sí es un parentesco que infla la impresión de
poder predictivo.

Por eso el resultado es buena evidencia de que la señal de liquidez está bien construida y bien
ordenada, pero **no** demuestra "hemos construido un predictor universal de distress empresarial".
El número del evento combinado, bastante más bajo, es una medida más honesta de hasta dónde llega
la cosa de verdad.

### ¿Está realmente fuera de muestra?

Aquí también hay que ser fino.

La validación separa **grupos completos**: un porcentaje de los grupos se aparta entero y no se
mira al ajustar nada.

¿Por qué no un reparto aleatorio de filas? Porque tendrías a la empresa X en enero en
entrenamiento y a la misma empresa X en febrero en test. Esas dos observaciones son casi la misma
observación: están brutalmente correlacionadas, y la validación saldría preciosa y sería mentira.

Partir por grupo imita cómo va a funcionar el test oculto de verdad, donde llegan grupos enteros
que el sistema no ha visto nunca.

**Pero hay una salvedad que hay que decir en voz alta**: las anclas y los pesos se revisaron
mirando resultados sobre este mismo conjunto sintético. Así que ese holdout **no es un test final
virgen que nadie ha mirado jamás**. Es una validación fuera-de-grupo útil, y hay algo de selección
acumulada sobre el dataset completo.

La prueba fuerte de verdad es congelar absolutamente todo ahora y pasarlo por los grupos ocultos.
Que es exactamente lo que hace el comando de submission, sobre un código que no lee ninguna
estadística de población.

---

## 9. La propiedad que sostiene todo lo demás

**Ningún score lee una estadística de la población.** Ni percentiles, ni z-scores, ni rankings, ni
medias entre grupos. Todas las anclas son constantes fijas.

Suena técnico y es la clave de todo. Significa que **un grupo puntúa exactamente igual solo que
dentro de la cartera**. Hay un test automático que lo fija, y está comprobado sobre grupos reales
recortados del dataset: ni una sola fila cambia.

¿Por qué importa tanto? Porque el test oculto son 60-80 grupos que el sistema no ha visto. Si el
score dependiera de con quién le toque estar en el fichero, el resultado sería una lotería: el
mismo grupo sacaría un número distinto según qué otras empresas lo acompañen. Y un cliente al que
le dices "tu score ha bajado porque ha entrado otra empresa en la cartera" te echa de su despacho.

Es también lo que hace posible el replay mes a mes: como nada depende del conjunto, el score de
enero calculado en enero es idéntico al score de enero calculado en septiembre.

---

## 10. Las seis preguntas del reto, y dónde se contestan

| # | Pregunta | Dónde vive la respuesta |
|---|---|---|
| 1 | Quién está sano | el nivel alto, con su etiqueta y su estado `healthy` |
| 2 | Quién está mejorando | el acumulador al alza → estado `improving` y su alerta |
| 3 | Quién empieza a doblarse | el estado `bending`: cayendo pero con cara de sana |
| 4 | Bache o caída | el salto provisional, resuelto dos meses después |
| 5 | Por qué cambió | las aportaciones de cada pilar, que suman exactamente al cambio |
| 6 | Cuándo fue visible | el mes de inicio de la alarma, y la anticipación medida |

Ninguna de las seis se contesta con "el modelo lo dice". Todas se contestan con un mecanismo que
se puede abrir y mirar.

---

## 11. Chuleta de defensa: las cinco preguntas duras

**"¿Esto es un modelo o es una fórmula?"**

Una scorecard determinista, y a propósito. Con tan pocos grupos etiquetables, un modelo ajustado se
los memoriza y no generaliza; y un número que no se puede explicar no se le puede enseñar a un
cliente al que le deniegas crédito. Lo que sí hemos hecho es medirla **como si fuese un modelo**:
validación fuera de grupo, ablación por pilares, estabilidad mes a mes. Renunciar a entrenar no es
renunciar a medir.

**"¿De dónde salen los umbrales?"**

De tres sitios distintos, y los decimos uno por uno: los días de colchón vienen de un estudio
externo sobre PYMEs, los retrasos de pago de la tabla estándar del sector, y el resto de los
percentiles del dataset comprobando que la tasa de problemas crece de forma ordenada. Es juicio de
diseño explicitado y versionado, no verdad universal, y en otro dominio habría que recalibrar.

**"El 0,910 huele a leakage."**

Leakage temporal no hay: cada mes usa solo datos hasta ese mes, las facturas se reconstruyen por
fechas en vez de dar por hecho su estado final, y el replay mes a mes lo verifica. Lo que sí hay,
y lo decimos nosotros, es **dependencia conceptual**: la caja de hoy y la caja negativa de dentro
de seis meses están emparentadas por definición. Por eso publicamos también los otros eventos, que
salen bastante menos favorecedores.

**"La ablación dice que os sobran pilares."**

Correcto para ese objetivo concreto, y lo publicamos nosotros en la documentación. Quitar pagos o
cobros mejora ligeramente la ordenación de la caja negativa. Los mantenemos porque el entregable
no es una métrica: es un score que hay que poder explicar y sobre el que hay que poder actuar, y
la métrica del test oculto no está publicada. Es un intercambio consciente y medido, no un
descuido.

**"¿Y si el grupo oculto es raro?"**

No hay estadísticas de población en ninguna parte del cálculo, así que un grupo puntúa igual solo
que acompañado, y está comprobado fila a fila. Lo que sí se degrada con datos escasos es la
cobertura, y por eso la publicamos pegada al número en lugar de esconderla: el score sigue siendo
el que es, pero decimos con cuánta evidencia se ha calculado.

---

## 12. Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Anclas, pesos, tope de seguridad, tramos | `src/xray/scoring/anchors.py` |
| Indicadores, subscores, pilares, nivel | `src/xray/scoring/score.py` |
| Suavizado, pendiente, acumuladores, estados | `src/xray/scoring/trend.py` |
| Saltos, cambios de estado, alertas | `src/xray/scoring/monitor.py` |
| Explicación por pilares | `src/xray/scoring/explain.py` |
| Oferta y acciones recomendadas | `src/xray/scoring/offer.py` |
| Eventos proxy y métricas | `src/xray/scoring/events.py`, `validate.py` |
| Test oculto | `src/xray/scoring/submit.py` |

Los números exactos de todo lo de arriba: [`docs/scoring.md`](scoring.md).
El porqué del diseño y las fuentes: [`docs/health-score-research.md`](health-score-research.md).
