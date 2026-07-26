"""Gross-profit-margin calculator — Raf's "All in One Local Office" model
(2026-07-25 Loom + sheet 1Ez-mbRO…). The owner sets what they pay the rep per
product; this returns gross revenue, office profit and the margins, and
simulates a sales volume at an activation rate.

Engine (verified against Raf's sheet, e.g. gross payout $167, 42% payout,
$70.14 commission, 10 sales, 70% conversion → $619.10 office profit):

    commission_per_unit = gross_payout × pct/100          (percent method)
                        = fixed $ payout                  (dollar method)
    gross_revenue = gross_payout × sales × activation      # only activated sales earn
    rep_payout    = commission   × sales × activation      # rep paid on activated too
    payroll_tax   = rep_payout × 0.12
    office_profit = gross_revenue − rep_payout − payroll_tax   ( = revenue − rep_payout×1.12 )

Two ratios, both reported (Raf's sheet stores the first under a "Gross Profit %"
label, but it is the COST ratio, not the margin):
    cost_ratio_pct = (rep_payout + payroll_tax) / gross_revenue    # 39.74% in his example
    margin_pct     = office_profit / gross_revenue                 # 60.26% — the true margin

Base-tier assumption (Raf): New Internet = Tier 4, Wireless = Tier 3-3, ABP 100%
— always use the base tier for this math. Metrics ± tier and volume tier-bonuses
are handled separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

PAYROLL_TAX = 0.12
DEFAULT_ACTIVATION = 0.85          # Raf's algorithm block default; sim uses 70-90%

# Base-tier gross revenue ("gross payout to office") for the main products, from
# Raf's sheet. Editable starting values; the DD puller can refresh them.
MAIN_PRODUCTS = {
    "Internet 1 GIG": 310.0,       # sheet office-P&L value ($261 on the DD owner-pay plan)
    "New Line": 173.0,             # New Ported Line, ATT-RES ($215 Hybrid)
}


@dataclass
class ProductPlan:
    name: str
    gross_payout: float            # gross revenue to the office per ACTIVATED unit, base tier
    payout: float                  # $ per unit, or a percent (0-100) if pay_is_pct
    pay_is_pct: bool = False
    # Volume tier bonuses the owner pays the rep: {units_threshold: $ per sale}.
    # Raf's sheet uses 5 & 8 units. When the week's volume hits a threshold, EVERY
    # sale that week earns that per-sale bonus (the owner sets it to drive sales).
    tier_bonuses: "Dict[int, float]" = None   # e.g. {5: 40, 8: 55}

    def commission(self) -> float:
        return self.gross_payout * self.payout / 100.0 if self.pay_is_pct else self.payout

    def bonus_per_sale(self, sales: float) -> float:
        """Best (highest-threshold) tier bonus the rep qualifies for at `sales`."""
        if not self.tier_bonuses:
            return 0.0
        hit = [b for t, b in self.tier_bonuses.items() if sales >= t]
        return max(hit) if hit else 0.0


def _line(gross_payout, commission, sales, activation, payroll_tax):
    activated = sales * activation
    revenue = gross_payout * activated
    rep_payout = commission * activated
    tax = rep_payout * payroll_tax
    profit = revenue - rep_payout - tax
    return {
        "sales": sales, "activated": round(activated, 1),
        "revenue": round(revenue, 2), "rep_payout": round(rep_payout, 2),
        "payroll_tax": round(tax, 2), "profit": round(profit, 2),
        "cost_ratio_pct": round((rep_payout + tax) / revenue * 100, 2) if revenue else None,
        "margin_pct": round(profit / revenue * 100, 2) if revenue else None,
    }


def per_unit(plan: ProductPlan, activation: float = 1.0,
             payroll_tax: float = PAYROLL_TAX) -> dict:
    """One-unit economics (activation defaults to 1 = a single activated sale)."""
    d = _line(plan.gross_payout, plan.commission(), 1, activation, payroll_tax)
    d["product"] = plan.name
    d["commission"] = round(plan.commission(), 2)
    d["gross_payout"] = plan.gross_payout
    return d


def simulate(plans: "List[ProductPlan]", volumes: "Dict[str, float]",
             activation: float = DEFAULT_ACTIVATION,
             payroll_tax: float = PAYROLL_TAX) -> dict:
    """Totals for a volume of sales at an activation rate. `volumes` maps product
    name -> sales count. Returns {per_product, total_revenue, total_rep_payout,
    total_tax, total_profit, blended_margin_pct, blended_cost_ratio_pct}."""
    rows, rev, pay, tax, profit = [], 0.0, 0.0, 0.0, 0.0
    for p in plans:
        n = float(volumes.get(p.name, 0) or 0)
        if n <= 0:
            continue
        # base commission + any qualified volume tier bonus, per activated sale
        eff_comm = p.commission() + p.bonus_per_sale(n)
        d = _line(p.gross_payout, eff_comm, n, activation, payroll_tax)
        d["product"] = p.name
        d["tier_bonus"] = round(p.bonus_per_sale(n), 2)
        rows.append(d)
        rev += d["revenue"]; pay += d["rep_payout"]; tax += d["payroll_tax"]
        profit += d["profit"]
    return {
        "per_product": rows, "total_revenue": round(rev, 2),
        "total_rep_payout": round(pay, 2), "total_tax": round(tax, 2),
        "total_profit": round(profit, 2),
        "blended_margin_pct": round(profit / rev * 100, 2) if rev else None,
        "blended_cost_ratio_pct": round((pay + tax) / rev * 100, 2) if rev else None,
    }
