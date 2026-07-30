# Country Sales Board — auditoría de los totales de semanas anteriores

Fecha: 2026-07-30. Pestaña `Country Sales Board` del workbook
`ATT Program - Focus Report` (`1w_KWAmlLfMR4kceaJmz_kyahnVslStTquVkVydysXTE`).
Solo lectura — no se escribió nada para hacer esta auditoría.

Cada semana cerrada existe **cuatro veces** en la pestaña, y las cuatro tienen
que dar el mismo número:

1. fila `TOTALS` del leaderboard (fila 94), en la columna de esa semana
2. la suma de las 76 filas de reps (18-93) en esa misma columna
3. la fila `WE m.d` del histórico (filas 176-227), columna J
4. la suma de las siete celdas de días (C..I) de esa misma fila

Alcance: 52 semanas cerradas, de `WE 07.26` hacia atrás hasta `WE 8.3` (agosto
2025).

## Resumen

| | Resultado |
|---|---|
| Cadena de semanas del histórico (filas hacia abajo) | ✅ 52 semanas, sin huecos, sin duplicados, -7 días exactos |
| Cadena de semanas del leaderboard (columnas) | ⚠️ 1 etiqueta duplicada (falta `WE 04.26`) |
| Semanas de la era automatizada (`WE 06.28` → `WE 07.26`) | ✅ las cuatro representaciones coinciden |
| Columnas K/L (`LAST/PREVIOUS WEEK'S TOTALS`) | ✅ 0 violaciones de la regla |
| Semanas de la era VA (2025 → `WE 06.21`) | ⚠️ 13 discrepancias reales, detalladas abajo |

Nada de lo que sigue lo produce el rollover automático: la automatización llegó
a esta pestaña el 2026-07-27 y todo lo que ha rodado desde entonces está limpio.
Son datos heredados del llenado manual.

## A. La etiqueta `WE 04.26` no existe — hay dos `WE 04.19`

- `Q16` dice `WE 04.19`, pero su total `Q94 = 7919` es el de **WE 04.26**
  (fila 189 del histórico, J = 7919).
- `R16` dice `WE 04.19` y su total `R94 = 7432` sí es el de WE 04.19
  (fila 190, J = 7432).

Los números están bien y en la columna correcta; lo único mal es el rótulo.
**Corrección: `Q16` → `WE 04.26`** (una celda).

## B. La col J del histórico está por debajo de sus propios días (4 filas)

Las celdas de días son las correctas — el leaderboard las respalda — y el total
de la fila quedó corto ~600-700:

| fila | semana | J (total de la fila) | suma de sus días C..I | leaderboard |
|---|---|---|---|---|
| 222 | WE 9.7 | 4117 | **4788** | 4780 |
| 223 | WE 8.31 | 3958 | **4599** | 4599 ✔ |
| 224 | WE 8.24 | 4222 | **5010** | 5010 ✔ |
| 225 | WE 8.17 | 4669 | **5333** | 5295 |

En WE 8.31 y WE 8.24 el leaderboard coincide **exacto** con la suma de días, así
que la suma de días es la buena y J es la mala.

Ojo: las columnas K/L se derivan de J, así que hoy K/L de las filas 221-226
heredan estos cuatro números. Si se corrige J, hay que volver a correr
`python -m automations.shared.board_prior_week_repair --board country --apply`
y K/L se re-alinean solas.

## C. Una fila con los días a medio llenar (el total sí es correcto)

- Fila 199, `WE 2.15`: días = `1065, 1243, 28, 66, 50, 71, 13` → suma 2536,
  contra J = 6947, que sí coincide con el leaderboard (`AA94 = 6947`).

O sea: el total de la semana es correcto y lo que se perdió es el desglose por
día de esa semana (miércoles a domingo quedaron con cifras de relleno). No es
recuperable desde la pestaña.

## D. El leaderboard y el histórico no coinciden (5 semanas)

En estas, el histórico es internamente consistente (J = suma de sus días), así
que el número sospechoso es el del leaderboard:

| semana | leaderboard | histórico (J = suma de días) | diferencia |
|---|---|---|---|
| WE 02.01 | `AC94` 7328 | 7143 | +185 |
| WE 10.26 | `AQ94` 6141 | 6744 | −603 |
| WE 10.12 | `AS94` 6603 | 6664 | −61 |
| WE 8.10 | `BB94` 4744 | 4179 | +565 |
| WE 8.3 | `BC94` 3631 | 3878 | −247 |

## E. La suma de reps siempre queda por debajo — esto NO es un error

En todas las semanas viejas, sumar las 76 filas de reps da menos que el total
congelado, y la diferencia crece con la antigüedad: 0 en las semanas recientes,
~70 en junio, ~250 en mayo, ~650 a finales de 2025.

Es rotación de plantilla: al rep que se va lo borran de la fila del leaderboard,
pero su producción sigue dentro del total congelado de las semanas que sí
trabajó. Por eso **el histórico no se puede re-derivar sumando reps** — solo la
columna de la semana en curso y la recién congelada admiten esa comprobación
(es justo lo que verifica `check_leaderboard_totals_front` en cada rollover).
