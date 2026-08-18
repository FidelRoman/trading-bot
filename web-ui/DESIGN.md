---
name: FSRPPO·BOT
description: Consola de operación del bot FSRPPO, compuesta como la lámina viva del paper que implementa
colors:
  ground: "#efece4"
  ground-demo: "#e6ebf3"
  ground-real: "#f7e3df"
  panel: "#f8f6f1"
  panel-inset: "#e9e5db"
  panel-hover: "#f1eee7"
  ink: "#14171a"
  ink-2: "#45494f"
  ink-3: "#5f646a"
  rule: "#cbc5b8"
  rule-strong: "#a9a296"
  rule-faint: "#ded8cc"
  long: "#0a6b4a"
  short: "#ae2a20"
  warn: "#8a5a00"
  accent: "#1f4fa8"
  ground-dark: "#0b0d0f"
  ground-demo-dark: "#08111f"
  ground-real-dark: "#220b0b"
  panel-dark: "#121517"
  panel-inset-dark: "#191d20"
  ink-dark: "#e9e6de"
  ink-2-dark: "#a8adb3"
  ink-3-dark: "#8a9098"
  rule-dark: "#272c31"
  rule-strong-dark: "#3a4046"
  long-dark: "#3fce8c"
  short-dark: "#ff6f62"
  warn-dark: "#f0b429"
  accent-dark: "#86a9f2"
typography:
  lede:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "2.5rem"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "-0.03em"
    fontVariant: "tabular-nums slashed-zero"
  headline:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.015em"
  readout:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "1rem"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.01em"
    fontVariant: "tabular-nums slashed-zero"
  body:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.6
  data:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.6
    fontVariant: "tabular-nums slashed-zero"
  eje:
    fontFamily: "Libre Franklin, system-ui, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 600
    lineHeight: 1.4
    letterSpacing: "0.06em"
  log:
    fontFamily: "JetBrains Mono, ui-monospace, monospace"
    fontSize: "0.75rem"
    lineHeight: 1.7
rounded:
  panel: "0px"
  control: "0px"
  dot: "50%"
spacing:
  s-1: "4px"
  s-2: "8px"
  s-3: "12px"
  s-4: "16px"
  s-5: "20px"
  s-6: "24px"
  s-8: "32px"
  s-10: "40px"
  s-12: "48px"
  s-16: "64px"
components:
  btn:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "30px"
  btn-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.panel}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "30px"
  btn-long:
    backgroundColor: "rgba(10, 107, 74, 0.1)"
    textColor: "{colors.long}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "30px"
  btn-danger:
    backgroundColor: "rgba(174, 42, 32, 0.1)"
    textColor: "{colors.short}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "30px"
  btn-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "30px"
  panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "16px"
  input:
    backgroundColor: "{colors.panel-inset}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "0 8px"
    height: "30px"
  mark:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.control}"
    padding: "2px 8px"
  notice:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
    padding: "12px 16px"
---

# Design System: FSRPPO·BOT

## Overview

**Creative North Star: "La Lámina"**

La consola es la lámina viva del paper que este bot implementa. No es un panel de
trading con tarjetas: es una figura de publicación científica que se actualiza sola.
De ahí sale toda la gramática —filetes de un píxel, paneles rotulados que cierran con
su pie explicativo, ejes con su lectura, cifras tabulares— y de ahí sale también lo
que la interfaz se niega a ser: el cuadro de mandos oscuro con velas de neón, tarjetas
flotantes y cristal esmerilado que envía por defecto esta categoría.

La lámina tiene dos soportes, y ninguno es el «modo por defecto» del otro. En claro es
la lámina impresa: papel cálido `#efece4`, tinta casi negra, filetes de tinta gris. En
oscuro es la misma lámina en la pantalla del instrumento: fondo `#0b0d0f`, tinta hueso.
El sistema decide cuál mostrar, y la elección explícita del operador manda sobre él.

La escena manda sobre la expresión. Un operador solo vigila esta pestaña durante horas
y trabaja dentro de ella a ratos, con dinero real en juego. Por eso la densidad es alta
y el color no decora nunca: solo hay dos tintas de señal —verde para largo, rojo para
corto— más un ámbar de aviso y un azul de anotación que marca lo accionable. Y por eso
el territorio (real / demo / simulado) no vive en una insignia sino en el fondo de la
página entera.

**Key Characteristics:**
- Filete de 1px como única declaración de elevación; cero sombras de reposo.
- Radio cero en todo contenedor y todo control.
- Una sola retícula de 4px, sin medios valores.
- Cifras tabulares con cero barrado en toda la interfaz.
- Monoespaciada reservada a registro, identificadores de run y nombres de dataset.
- El fondo de la página dice en qué cuenta estás, en todos los anchos.

## Colors

Paleta contenida: neutros de papel o pantalla, y cuatro tintas que solo aparecen cuando
significan algo.

### Primary
- **Azul de anotación** (`#1f4fa8` claro / `#86a9f2` oscuro): la tinta con la que se
  anota sobre una lámina. Marca lo accionable y lo seleccionado —botón primario,
  pestaña activa, enlaces, foco, bandas de Bollinger, cruz del gráfico— y nada más.

### Secondary
- **Verde de tinta (largo)** (`#0a6b4a` / `#3fce8c`): posición compradora, P&L positivo,
  modo FSR conservado, resultado que bate a comprar-y-mantener.
- **Rojo de tinta (corto)** (`#ae2a20` / `#ff6f62`): posición vendedora, P&L negativo,
  modo descartado, acción destructiva, y el territorio de cuenta real.

### Tertiary
- **Ámbar de aviso** (`#8a5a00` / `#f0b429`): estado que pide atención sin ser una
  pérdida —mercado cerrado, bot detenido, datos sintéticos, modelo no validado.

### Neutral
- **Papel** (`#efece4`) / **Pantalla** (`#0b0d0f`): el fondo de la página.
- **Panel** (`#f8f6f1` / `#121517`): la superficie de cada bloque de figura.
- **Panel hundido** (`#e9e5db` / `#191d20`): campos de formulario y celdas insertadas.
- **Tinta** (`#14171a` / `#e9e6de`): texto principal y cifras.
- **Tinta secundaria** (`#45494f` / `#a8adb3`): prosa de pie de figura.
- **Tinta terciaria** (`#5f646a` / `#8a9098`): rótulos de eje, notas y cabeceras de
  tabla. Es el valor más bajo del sistema y aun así pasa de 4,5:1 sobre papel y panel.
- **Filete** (`#cbc5b8` / `#272c31`), **filete fuerte** (`#a9a296` / `#3a4046`) y
  **filete tenue** (`#ded8cc` / `#1c2023`): las tres líneas de la lámina.

### Named Rules

**La regla del territorio.** El modo de cuenta tiñe el fondo de la página entera:
simulado deja el papel neutro, demo lo vuelve azulado (`#e6ebf3` / `#08111f`) y real lo
vuelve rojizo (`#f7e3df` / `#220b0b`), además de promover `--rule` a `--rule-strong` y
poner un filete rojo sobre la banda. Ninguna insignia puede ser el único portador de
esa señal, en ningún ancho. Se implementa con `data-account` en `<html>`, que escribe
`Shell` y lee solo `tokens.css`.

**La regla de la tinta de señal.** Verde y rojo significan dirección o resultado, nunca
jerarquía ni decoración. Si un elemento es verde y no es una posición larga, un P&L
positivo o un modo conservado, está mal pintado.

**La regla del lavado.** Cada tinta de señal tiene su `*-wash` al 10-13% para fondos de
aviso y de botón. Un fondo de señal a plena saturación solo aparece en el botón de
confirmación destructiva (`.btn.danger.solid`).

## Typography

**Body / Display Font:** Libre Franklin variable 400–800 (con `system-ui`, `sans-serif`)
**Label/Mono Font:** JetBrains Mono variable 400–700 (con `ui-monospace`, `monospace`)

Ambas viajan dentro del repositorio en `app/fonts/` y se sirven con `next/font/local`:
la app se compila y arranca sin red, que es un requisito del producto, no una
preferencia.

**Character:** una grotesca de rotulación —la cara con la que se etiquetan las figuras
de una publicación— llevando absolutamente todo el texto, con la monoespaciada
confinada a lo que de verdad es salida de máquina. La jerarquía la hacen el tamaño, el
peso y el color, nunca las mayúsculas.

### Hierarchy
- **Lede** (700, 40px / 2.5rem, 1, `-0.03em`): el precio vivo del instrumento, y solo
  eso. Es el titular de la lámina.
- **Headline** (600, 19px, 1.2, `-0.015em`): el `h1` de la banda, título de diálogo.
- **Readout** (600, 16px, 1.2, `-0.01em`): el valor de cualquier lectura de eje.
- **Body** (400, 14px, 1.6): prosa de interfaz.
- **Data** (400, 13px, 1.6): tablas, controles, campos.
- **Caption** (400, 12px, 1.6): pies de figura y notas de campo, acotados a 74ch.
- **Eje** (600, 11px, `0.06em`, versalita alta): rótulos de eje, cabeceras de tabla,
  rótulos de campo. Es el único sitio donde hay mayúsculas y letter-spacing.
- **Log** (JetBrains Mono, 12px, 1.7): registro del sistema, identificadores de run,
  nombres de dataset, volcados JSON.

### Named Rules

**La regla de la cifra tabular.** `font-variant-numeric: tabular-nums slashed-zero` va
en `body` y se hereda: ninguna cifra viva baila al actualizarse. La clase `.num` la
reafirma y alinea a la derecha en tablas.

**La regla de la voz única.** El precio vivo se compone a 40px y nada compite con él en
esa pantalla; el siguiente escalón es el `h1` de 19px. Un segundo número a escala de
titular rompe la lámina.

**La regla de la versalita.** Mayúsculas y `letter-spacing` existen solo en el escalón
`eje`, a 11px. Un título, un botón o una frase en mayúsculas es un error del sistema:
así era la interfaz anterior y por eso no se leía nada.

## Layout

Armazón de dos columnas: raíl fijo de 216px con la navegación, y hoja con `border-left`
de 1px. Dentro de la hoja, la banda de estado pegajosa arriba, la tira de lecturas de
cuenta colgando de ella, y la página.

El espaciado es una sola escala de 4px (`--s-1` a `--s-16`) sin medios valores. Las
composiciones de página son cuatro clases: `.plate.split` (contenido más columna lateral
de 340px), `.plate.halves`, `.plate.thirds` y `.stack` (columna simple con `gap` de 16px).

La densidad la fija el puntero, no el ancho: `--control-h` es 30px con puntero fino y
44px bajo `(pointer: coarse)`. Aplicar objetivos táctiles en escritorio destruye la
densidad que esta consola necesita.

**Responsive**, siempre estructural y nunca tipográfico:
- **1180px**: `.plate.split` cae a una columna; `.thirds` a dos.
- **860px**: el raíl pasa a cabecera con menú desplegable, la banda se apila a todo el
  ancho, las tablas conservan 680px de ancho mínimo y el marco se desplaza, y la lectura
  de cuenta de la banda se oculta porque el raíl ya la lleva justo encima.

**Lo que nunca se oculta al estrechar:** el modo de cuenta y el estado de conexión. En
la interfaz anterior desaparecían en móvil, que es donde más falta hacen.

## Elevation & Depth

**Este sistema no usa sombras.** La profundidad se declara una sola vez y siempre con
filete: `--rule-faint` separa dentro de un panel, `--rule` delimita el panel contra el
fondo, `--rule-strong` marca lo interactivo. Las superficies se distinguen además por
valor: fondo, panel, panel hundido.

El diálogo es lo único que se despega, y lo hace con un telón a `rgba(0,0,0,0.55)` y un
filete, no con una sombra. La variante destructiva añade un filete interior de 4px en
rojo sobre el borde superior.

### Named Rules

**La regla del filete único.** Un borde de 1px o una sombra, nunca los dos. Un panel con
borde y sombra difusa es la tarjeta fantasma que este mundo rechaza.

## Shapes

Radio cero. `--radius` y `--radius-control` valen ambos `0px`: paneles, botones, campos,
selectores, avisos y diálogos son rectángulos exactos. La lámina no tiene esquinas
redondeadas.

**Excepción nombrada:** `.mark .dot`, el punto de señal de 6px, conserva
`border-radius: 50%`. Es una marca de señal —el punto que late cuando algo está vivo—,
no un contenedor. Es el único radio no nulo del sistema y no debe «corregirse».

Los bordes son de 1px sin excepción. Las barras de color a la izquierda de tarjetas,
avisos o elementos de lista están prohibidas por encima de 1px: el elemento activo del
raíl usa `box-shadow: inset 1px 0 0 var(--accent)`.

## Components

### Buttons
- **Shape:** rectángulo exacto (`0px`), alto `--control-h` (30px, 44px táctil), padding
  lateral de 12px, peso 600, 13px.
- **Primary:** `--accent` sólido con texto `--accent-ink`. Una sola acción primaria por
  panel.
- **Long / Short / Danger:** lavado de la tinta de señal al 10-13% con borde y texto de
  esa tinta. `.solid` sobre `danger` la pinta a plena saturación, y se reserva a la
  confirmación de un diálogo destructivo.
- **Quiet:** transparente sin borde, texto `--ink-2`; al pasar, fondo `--panel-inset`.
  Es la acción secundaria dentro de una cabecera de panel.
- **Hover / Focus:** el fondo sube un escalón de valor en 120ms; el foco es
  `outline: 2px solid var(--accent)` con `offset: 1px`, común a toda la interfaz.
- **Disabled:** `opacity: 0.45` y `cursor: not-allowed`, sin cambiar de color.

### Segmented (`.seg`)
- Fila de botones dentro de un marco de 1px, separados por filete, sin radio.
- El seleccionado (`aria-selected` o `aria-pressed`) se pinta con `--accent` sólido.
- Sirve para temporalidades y para pestañas; como pestañas se usa el componente `Tabs`,
  que añade navegación por flechas, `Home` y `End` con `tabindex` móvil.

### Panel
- **Corner Style:** `0px`. **Background:** `--panel`. **Border:** 1px `--rule`.
  **Shadow:** ninguna.
- Anatomía fija: cabecera con rótulo `eje` y acciones a la derecha, cuerpo con 16px de
  relleno (`bleed` lo quita para tablas y figuras), y pie de figura opcional separado
  por `--rule-faint`.
- **El pie de figura** es donde vive la prosa explicativa. Su filete cruza el panel
  entero; lo acotado a 74ch es el texto, nunca la regla.

### Inputs / Fields
- **Style:** fondo `--panel-inset` hundido respecto al panel, borde 1px `--rule-strong`,
  radio cero, alto `--control-h`.
- **Focus:** el borde pasa a `--accent`, más el anillo de foco global.
- **Anatomía del campo:** rótulo `eje` arriba, control, y nota de campo debajo. La nota
  dice qué implica el número, no lo que ya dice el rótulo.

### Tables
- Cabecera pegajosa sobre `--panel`, en escalón `eje`, con `--rule-strong` debajo.
- Filas separadas por `--rule-faint`; `hover` pinta `--panel-hover`; la fila marcada
  (`.is-marked`) usa `--accent-wash`.
- Las columnas numéricas llevan `.num`: alineadas a la derecha y tabulares.
- El marco (`TableFrame`) es la región desplazable, con `tabindex` para que se pueda
  recorrer con teclado.

### Navigation
- Raíl de 216px con grupos rotulados en escalón `eje` y separados por filete.
- El elemento activo lleva fondo `--panel`, peso 600 y un filete interior de 1px en
  `--accent`; nunca una barra más gruesa.
- Iconos de 16px de un solo juego dibujado sobre retícula de 24 con trazo 1.6
  (`components/ui/Icon.tsx`). Ningún glifo unicode hace de icono.
- Bajo 860px el raíl es cabecera con botón de menú; las marcas de cuenta y conexión
  siguen visibles.

### Marks (`Mark`)
Una sola familia para modo de cuenta, conexión y estado del motor: 11px en escalón
`eje`, borde de 1px y lavado de su tinta. `dot` añade el punto de 6px; `live` lo hace
latir a 2s. Es el único componente que puede repetir información de la banda.

### Notices y Toast
Un solo patrón de aviso en cuatro tonos (`info`, `ok`, `warn`, `danger`): borde de 1px y
lavado de la tinta correspondiente, sin barra lateral y sin icono. Los mensajes efímeros
de acción usan el mismo componente dentro de `.toast-stack`, abajo a la derecha.

### Readouts
La única forma de presentar una cifra: rótulo `eje`, valor tabular, nota opcional.
`ReadoutRow` los alinea sobre una línea base común. La variante `chrome` —la tira de
cuenta que cuelga de la banda— pierde el marco y conserva un filete inferior, para que
se lea como parte del armazón; las tiras de página llevan rótulo propio.

### Alcance (componente de firma)
Un control consecuente enseña lo que va a afectar antes de accionarse. `useReach(key)`
pone `data-reaching` en `<html>` al apuntar o enfocar, y el sistema resalta los
elementos con el `data-reach-target` correspondiente. Hay exactamente dos claves vivas:
`positions` (la lista de posiciones, desde «Cerrar todas», desde el bloqueo del selector
de instrumento y desde el bloqueo de cambio de cuenta) y `engine` (la lectura de motor y
el mandato, desde «Detener bot»). Añadir una clave sin destino deja el mecanismo muerto.

### Figures
Los gráficos leen los tokens del documento en tiempo de ejecución (`token()` en
`components/charts.tsx`) y se rehacen cuando cambia el soporte (`useSupportTick`).
Ningún color de gráfico se escribe en hexadecimal dentro del componente. La altura es
fluida por contenedor (`clamp`), no fija.

## Do's and Don'ts

### Do:
- **Do** declarar la elevación una sola vez y con filete de 1px.
- **Do** poner toda medida en la escala de 4px y todo filete a exactamente 1px.
- **Do** usar `.num` en cualquier columna o valor numérico.
- **Do** cerrar cada panel que necesite explicación con su pie de figura, en vez de
  soltar prosa suelta entre bloques.
- **Do** dar a cada campo una nota que diga qué implica el número.
- **Do** derivar los colores de gráfico de los tokens del documento.
- **Do** escribir estados de carga (`Skeleton`) y vacíos (`EmptyState`) que enseñen la
  interfaz; «sin datos» no enseña nada.
- **Do** dejar que el fondo de la página lleve el territorio de cuenta.

### Don't:
- **Don't** añadir `box-shadow` a un panel, una tarjeta o un aviso.
- **Don't** poner radio a nada que no sea el punto de señal de 6px.
- **Don't** componer títulos, botones ni frases en mayúsculas: las versalitas viven solo
  en el escalón `eje` de 11px.
- **Don't** usar la monoespaciada como disfraz de «técnico». Solo registro,
  identificadores de run, nombres de dataset y volcados.
- **Don't** usar verde o rojo para nada que no sea dirección o resultado.
- **Don't** poner una barra de color de más de 1px a la izquierda de una tarjeta, un
  aviso o un elemento de lista.
- **Don't** usar un glifo unicode como icono; dibújalo en `Icon.tsx` con el mismo trazo.
- **Don't** aplicar objetivos táctiles de 44px en escritorio: eso lo decide
  `(pointer: coarse)`.
- **Don't** dejar que el modo de cuenta dependa de una insignia, ni ocultarlo al
  estrechar.
- **Don't** escribir un `style={{}}` con color, tamaño de fuente o espaciado que no
  venga de un token.

## Deudas registradas

Se anotan aquí para que no se lean como decisiones del sistema:

- **Leyenda de la página FSR.** Las muestras de línea de `Señal reconstruida frente al
  precio` se dibujan con rayas tipográficas (`——— precio crudo · ——— señal FSR`) donde
  el mundo tenía disponible su propio vocabulario de trazo dibujado. Observación de
  acabado, aplazada de forma deliberada; no es un patrón a imitar.
- **Procedencia de las capturas de territorio.** Los nueve archivos
  `.impeccable/review/*-territorio-{real,demo,sim}.png` se produjeron forzando
  `document.documentElement.dataset.account` en la página, porque el backend simulado
  solo reporta cuenta simulada. Consecuencia visible en ellos: la marca CUENTA sigue
  diciendo SIMULADO sobre un fondo teñido. No existe todavía ninguna captura de una
  sesión real de verdad.
- **`components/AuthGate.tsx`** es un pasa-a-través que ya no importa nadie, resto de la
  retirada de la autenticación. No forma parte del sistema.
