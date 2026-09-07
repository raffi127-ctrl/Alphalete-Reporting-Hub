"""_sso_to_tableau: las dos navegaciones llevan timeout PROPIO, no el default de 30s.

    python -m automations.shared.test_sso_nav_timeout

El 2026-09-07 `captainship_activations` murio cuatro veces en
`page.goto(sso_url)` con "Timeout 30000ms exceeded", mientras org_sales_board
—mismo codigo, mismo perfil— pasaba en su tercer intento. Ese salto no es una
carga de pagina: es ownerville entregandole el browser a Tableau, y el codigo
que sigue ya se queda 15s fijos esperandolo. 30s era un limite sin relacion con
lo que la operacion cuesta.

No abre ningun browser: `page` es un doble que anota como lo llamaron.
"""
from __future__ import annotations

from automations.shared import tableau_patchright as tp


class _FakePage:
    """Anota cada goto. `url` trae el rqst para que _sso_to_tableau siga derecho."""

    def __init__(self):
        self.url = "https://v2.ownerville.com/index.cfm?rqst=ABC123_DEF&x=1"
        self.gotos = []          # (url, kwargs)

    def goto(self, url, **kw):
        self.gotos.append((url, kw))

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        return ""


def _check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"\n        got  {got!r}\n        want {want!r}"))
    return ok


def _run():
    page = _FakePage()
    tp._sso_to_tableau(page, verbose=False)
    return page.gotos


def test_both_navigations_carry_the_timeout():
    """Las DOS: si solo la segunda lo lleva, el primer goto sigue muriendo a los
    30s en la misma red degradada y el reporte falla un paso antes."""
    gotos = _run()
    ok = _check("hace las dos navegaciones", len(gotos), 2)
    ok &= _check("ambas con timeout explicito",
                 [kw.get("timeout") for _, kw in gotos],
                 [tp.SSO_NAV_TIMEOUT_MS, tp.SSO_NAV_TIMEOUT_MS])
    return ok


def test_timeout_is_bigger_than_the_default_that_failed():
    """30s es exactamente el numero que fallo cuatro veces; el margen tiene que
    ser real, no cosmetico."""
    return _check("el timeout supera holgadamente los 30s del default",
                  tp.SSO_NAV_TIMEOUT_MS >= 60_000, True)


def test_second_goto_is_the_sso_handoff():
    """La segunda navegacion es el link SSO (p=81 + el rqst leido de la pagina)
    — la que efectivamente moria."""
    gotos = _run()
    url = gotos[1][0]
    ok = _check("la segunda va al link SSO", "p=81" in url and "ssook=1" in url, True)
    ok &= _check("lleva el rqst leido de la pagina", "rqst=ABC123_DEF" in url, True)
    return ok


def main() -> int:
    ok = True
    for fn in (test_both_navigations_carry_the_timeout,
               test_timeout_is_bigger_than_the_default_that_failed,
               test_second_goto_is_the_sso_handoff):
        print(f"\n--- {fn.__name__} ---")
        ok &= fn()
    print("\nALL PASS" if ok else "\nFAILURES ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
