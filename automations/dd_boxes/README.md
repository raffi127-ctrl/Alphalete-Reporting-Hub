# DD Boxes — los cuadros de Due Diligence dentro del Focus Report

Llena, semana a semana, los cuadros estilo Due Diligence que viven **dentro de
las tabs ICD** del *ATT Program - Focus Report* — distintos de los "Next
Promotion" (esos los hace `team_breakdowns`) y distintos de la Sheet propia de
Jiraiya (`automations/due_diligence`).

Hasta 2026-08-17 estos cuadros **no los llenaba nada**: se cargaban a mano y se
quedaban atrás sin que nadie se enterara.

## Dónde están

Se **auto-detectan**: cualquier tab con un encabezado `Reps Names` +
`8 WK … Average` entra sola, sin tocar código. Hoy son tres cuadros en dos tabs:

| Tab | fila | tipo | reps |
|---|---|---|---|
| Starr Rodenhurst | 107 | New INT | Miguel Carranza |
| Kimberly Rodriguez | 145 | New INT | 9 |
| Kimberly Rodriguez | 160 | Wireless | 9 |

Todo se ubica **por etiqueta, nunca por índice**: el encabezado puede estar en
la columna B (Kimberly) o en la AG (Starr), las columnas de métricas pueden ir
antes o después del bloque semanal, y las filas `Total` / `Per rep AVG` son
opcionales.

## De dónde salen los números

Las mismas fuentes que usa el resto de los reps de ATT fiber:

| Campo | Fuente |
|---|---|
| Ventas de la semana | PRODUCT SALES SUMMARY (`opt_phase.parse_personal_production`) — el crosstab que el OPT phase ya baja |
| 0-30 / 30-60 Cancel Rate | `MetricsINTfullyEXP` / `MetricsWIRfullyEXP` (30-60 = 100 − activación) |
| 0-30 / 30 / 60 / 90 Churn | `INTAllTeams` / `WirelessAllTeams`, sliceados al rep |
| Start Date | el mapa `_first_sale` (Order Log completo) |

Las URLs se resuelven vía `due_diligence.config`, así que una vista que se mueve
se repointea en **un solo lugar** para este reporte y para Jiraiya.

## Reglas de escritura

- **Ventas: append-only por celda.** Una semana ya cargada nunca se pisa, así
  que una corrección a mano sobrevive a una re-corrida.
- **Cancel / churn / start date: se re-seedean todas las semanas.** Son medidas
  rodantes: el valor de la semana pasada está viejo, no es historia.
- **Cero, nunca vacío.** Un rep que las fuentes no traen no vendió → `0`. Una
  celda en blanco se lee como "el reporte no corrió".
- **Los promedios se corren solos** a las últimas 8 / últimas 4 semanas con
  datos. Si no, el `8 WK Average` se congela en una ventana vieja — que es
  exactamente cómo estaba el cuadro de Starr antes de esto.
- **Avisa cuando se acaban las columnas.** A un cuadro con ≤4 columnas de
  semana libres se lo marca en el log, porque cuando se llenan hay que agregar
  más a mano.

## Correrlo

```bash
# preview, no escribe nada
python -m automations.dd_boxes.run --dry-run
python -m automations.dd_boxes.run --dry-run --only "Starr Rodenhurst"

# en serio
python -m automations.dd_boxes.run

# reusar los crosstabs ya bajados (iterar sin volver a Tableau)
python -m automations.dd_boxes.run --dry-run --skip-download
```

Corre como último paso del OPT phase, al lado de `production_breakdown` y
`team_breakdowns`. No tiene tarjeta propia en el Hub.

## Trampas conocidas

- **Una vista puede volver COLAPSADA** (sin la columna `Rep Name`) y entonces
  el cancel queda vacío para *todos* los reps, no para uno. El pull lo detecta y
  lo registra como gap en vez de dejarlo pasar en silencio — fue lo que rompió
  el cancel de fiber durante semanas.
- **Los nombres se resuelven por el ICD Aliases** antes del matcher difuso, así
  que un typo tipo `Candace Grager` → `Candace Granger` se arregla en la Sheet
  de aliases, no acá.
- **`WE 6.07` no trae año.** Las columnas escritas en ese formato corto se
  reconcilian contra los domingos reales por mes/día.
