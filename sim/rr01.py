#!/usr/bin/env python3
"""
RR-01 Reusable Rocket — point-mass flight + recovery simulation.

Educational / conceptual model only.
No propellant chemistry, grain design, or hardware construction.

Physics:
  - 2-D point mass in a non-rotating flat Earth with exponential atmosphere
  - Variable-mass rocket equation with constant Isp
  - Quadratic drag
  - Open-loop phase schedule: boost → coast → boostback → fall → landing burn
  - Touchdown scored on vertical speed, horizontal speed, and remaining propellant

Run:
  python3 rr01.py
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

G0 = 9.80665  # m/s^2
R_EARTH = 6_371_000.0
RHO0 = 1.225  # kg/m^3 sea-level
H_SCALE = 8500.0  # m, exponential atmosphere scale height


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------

# Locked pad load: 4:1 oxidizer:fuel by mass = 20% methane / 80% LOX.
# Stoichiometric CH4 + 2 O2 mass ratio. Allocation only — not a mix recipe.
OF_RATIO = 4.0
METHANE_FRAC = 1.0 / (1.0 + OF_RATIO)  # 0.20
LOX_FRAC = OF_RATIO / (1.0 + OF_RATIO)  # 0.80
RHO_LCH4 = 422.0  # kg/m^3, liquid methane
RHO_LOX = 1141.0  # kg/m^3, liquid oxygen


@dataclass
class Vehicle:
    name: str = "RR-01"
    dry_mass_kg: float = 8_000.0
    propellant_kg: float = 18_000.0
    of_ratio: float = OF_RATIO
    isp_sl_s: float = 282.0
    isp_vac_s: float = 311.0
    thrust_sl_n: float = 490_000.0
    thrust_vac_n: float = 540_000.0
    ref_area_m2: float = 3.8  # ~2.2 m diameter
    cd: float = 0.45
    landing_legs_extra_kg: float = 350.0
    grid_fins_extra_kg: float = 180.0

    @property
    def wet_mass_kg(self) -> float:
        return self.dry_mass_kg + self.propellant_kg

    @property
    def twr_liftoff(self) -> float:
        return self.thrust_sl_n / (self.wet_mass_kg * G0)

    @property
    def methane_frac(self) -> float:
        return 1.0 / (1.0 + self.of_ratio)

    @property
    def methane_loaded_kg(self) -> float:
        return self.propellant_kg * self.methane_frac

    @property
    def lox_loaded_kg(self) -> float:
        return self.propellant_kg * (1.0 - self.methane_frac)


# ---------------------------------------------------------------------------
# Atmosphere + propulsion helpers
# ---------------------------------------------------------------------------

def density(h: float) -> float:
    h = max(h, 0.0)
    return RHO0 * math.exp(-h / H_SCALE)


def pressure_ratio(h: float) -> float:
    """Crude 0..1 sea-level to vacuum blend for Isp / thrust."""
    return min(1.0, max(0.0, density(h) / RHO0))


def thrust_and_isp(v: Vehicle, h: float) -> tuple[float, float]:
    pr = pressure_ratio(h)
    thrust = v.thrust_vac_n - pr * (v.thrust_vac_n - v.thrust_sl_n)
    isp = v.isp_vac_s - pr * (v.isp_vac_s - v.isp_sl_s)
    return thrust, isp


def g_local(h: float) -> float:
    r = R_EARTH + max(h, 0.0)
    return G0 * (R_EARTH / r) ** 2


# ---------------------------------------------------------------------------
# Integrator state: [x, y, vx, vy, mass]
# ---------------------------------------------------------------------------

BOOST = "boost"
COAST = "coast"
BOOSTBACK = "boostback"
FALL = "fall"
LANDING = "landing"
LANDED = "landed"
FAILED = "failed"


@dataclass
class Mission:
    boost_s: float = 16.5
    pitch_start_s: float = 4.0
    pitch_rate_deg_s: float = 0.55  # mostly-vertical hopper with a little downrange
    max_pitch_deg: float = 8.0
    boostback_s: float = 3.2
    landing_start_alt_m: float = 2_400.0
    landing_throttle: float = 0.95
    dt: float = 0.04
    target_downrange_m: float = 2_000.0


def aero_accel(vx: float, vy: float, h: float, mass: float, veh: Vehicle) -> tuple[float, float]:
    rho = density(h)
    spd = math.hypot(vx, vy)
    if spd < 1e-6 or mass <= 0:
        return 0.0, 0.0
    q = 0.5 * rho * spd * spd
    drag = q * veh.cd * veh.ref_area_m2
    ax = -drag * vx / (spd * mass)
    ay = -drag * vy / (spd * mass)
    return ax, ay


def integrate(veh: Vehicle, msn: Mission) -> dict:
    x = 0.0
    y = 0.0
    vx = 0.0
    vy = 0.0
    m = veh.wet_mass_kg
    t = 0.0
    phase = BOOST
    pitch_deg = 0.0

    log = {
        "t": [],
        "x": [],
        "y": [],
        "vx": [],
        "vy": [],
        "m": [],
        "phase": [],
        "thrust": [],
        "mach": [],
        "q": [],
    }

    meco_state = None
    apogee = 0.0
    max_q = 0.0
    max_mach = 0.0
    touchdown = None

    def record(th: float):
        log["t"].append(t)
        log["x"].append(x)
        log["y"].append(y)
        log["vx"].append(vx)
        log["vy"].append(vy)
        log["m"].append(m)
        log["phase"].append(phase)
        log["thrust"].append(th)
        spd = math.hypot(vx, vy)
        a_sound = 340.0 * math.exp(-y / (2 * H_SCALE))  # crude
        mach = spd / max(a_sound, 200.0)
        qdyn = 0.5 * density(y) * spd * spd
        log["mach"].append(mach)
        log["q"].append(qdyn)

    steps = 0
    max_steps = int(400.0 / msn.dt)

    while steps < max_steps and phase not in (LANDED, FAILED):
        steps += 1
        h = y
        if h < -2.0:
            phase = FAILED
            break

        thrust_n = 0.0
        isp = veh.isp_sl_s
        throttle = 0.0
        ux, uy = 0.0, 1.0  # thrust unit vector (body)

        if phase == BOOST:
            if t >= msn.boost_s or m <= veh.dry_mass_kg + 50:
                phase = COAST
                meco_state = dict(t=t, x=x, y=y, vx=vx, vy=vy, m=m)
            else:
                throttle = 1.0
                if t > msn.pitch_start_s:
                    pitch_deg = min(msn.max_pitch_deg, (t - msn.pitch_start_s) * msn.pitch_rate_deg_s)
                rad = math.radians(pitch_deg)
                ux, uy = math.sin(rad), math.cos(rad)

        elif phase == COAST:
            # wait until vertical speed near zero-ish after MECO, then boostback
            if vy < 40.0 and t > msn.boost_s + 4.0:
                phase = BOOSTBACK
                bb_t0 = t

        elif phase == BOOSTBACK:
            if t - bb_t0 >= msn.boostback_s or m <= veh.dry_mass_kg + 80:
                phase = FALL
            else:
                throttle = 0.85
                # fire mostly retrograde horizontal, slight down
                spd = math.hypot(vx, vy)
                if spd > 1.0:
                    ux, uy = -vx / spd, -0.15
                    nrm = math.hypot(ux, uy)
                    ux, uy = ux / nrm, uy / nrm
                else:
                    ux, uy = -1.0, 0.0

        elif phase == FALL:
            # suicide-burn estimate: start when remaining altitude ≈ v^2 / (2 a_net)
            thrust_est, _ = thrust_and_isp(veh, h)
            a_net = max(thrust_est / max(m, 1.0) - g_local(h), 1.0)
            burn_alt = (vy * vy) / (2.0 * a_net) + 80.0 if vy < 0 else msn.landing_start_alt_m
            start_alt = max(burn_alt, 250.0)
            start_alt = min(start_alt, msn.landing_start_alt_m)
            if vy < 0 and y <= start_alt:
                phase = LANDING
            vx *= 1.0 - 0.0012  # grid-fin damping proxy, not a control law

        elif phase == LANDING:
            if y <= 0.4:
                phase = LANDED
                touchdown = dict(
                    t=t, x=x, y=max(y, 0.0), vx=vx, vy=vy, m=m,
                    v_vert=vy, v_horiz=vx,
                    remaining_prop=max(0.0, m - veh.dry_mass_kg),
                )
                break
            # hover-slam: full thrust while fast and high, bleed to hover near deck
            spd = math.hypot(vx, vy)
            if spd > 1.0:
                ux, uy = -0.35 * vx / spd, 1.0
                nrm = math.hypot(ux, uy)
                ux, uy = ux / nrm, uy / nrm
            else:
                ux, uy = 0.0, 1.0
            if vy < -25:
                throttle = 1.0
            elif vy < -8:
                throttle = msn.landing_throttle
            else:
                # near hover: hold T ≈ weight
                th_cap, _ = thrust_and_isp(veh, h)
                throttle = min(1.0, max(0.35, (m * g_local(h)) / max(th_cap, 1.0)))
            if y < 40 and vy > -6:
                th_cap, _ = thrust_and_isp(veh, h)
                throttle = min(1.0, (m * g_local(h)) / max(th_cap, 1.0))

        if throttle > 0 and m > veh.dry_mass_kg:
            thrust_n, isp = thrust_and_isp(veh, h)
            thrust_n *= throttle
            mdot = thrust_n / (isp * G0)
            dm = mdot * msn.dt
            if m - dm < veh.dry_mass_kg:
                dm = m - veh.dry_mass_kg
                thrust_n = 0.0
            m -= dm
        else:
            thrust_n = 0.0

        ax_a, ay_a = aero_accel(vx, vy, h, m, veh)
        ax_t = thrust_n * ux / m if m > 0 else 0.0
        ay_t = thrust_n * uy / m if m > 0 else 0.0
        ax = ax_a + ax_t
        ay = ay_a + ay_t - g_local(h)

        # Euler (small dt)
        vx += ax * msn.dt
        vy += ay * msn.dt
        x += vx * msn.dt
        y += vy * msn.dt
        t += msn.dt
        if y < 0 and phase != LANDED:
            y = 0.0
            if phase != LANDING:
                phase = FAILED
                touchdown = dict(t=t, x=x, y=0.0, vx=vx, vy=vy, m=m,
                                 v_vert=vy, v_horiz=vx,
                                 remaining_prop=max(0.0, m - veh.dry_mass_kg),
                                 reason="impact_before_landing_burn")
                break
            else:
                phase = LANDED
                touchdown = dict(t=t, x=x, y=0.0, vx=vx, vy=vy, m=m,
                                 v_vert=vy, v_horiz=vx,
                                 remaining_prop=max(0.0, m - veh.dry_mass_kg))
                break

        apogee = max(apogee, y)
        spd = math.hypot(vx, vy)
        a_sound = 340.0
        max_mach = max(max_mach, spd / a_sound)
        max_q = max(max_q, 0.5 * density(y) * spd * spd)
        record(thrust_n)

    if touchdown is None:
        touchdown = dict(t=t, x=x, y=y, vx=vx, vy=vy, m=m,
                         v_vert=vy, v_horiz=vx,
                         remaining_prop=max(0.0, m - veh.dry_mass_kg),
                         reason="timeout")

    v_td = math.hypot(touchdown["vx"], touchdown["vy"])
    soft = (
        phase == LANDED
        and abs(touchdown["vy"]) < 8.0
        and abs(touchdown["vx"]) < 6.0
        and touchdown["remaining_prop"] >= 0
    )

    summary = {
        "vehicle": veh.name,
        "wet_mass_kg": veh.wet_mass_kg,
        "dry_mass_kg": veh.dry_mass_kg,
        "twr_liftoff": round(veh.twr_liftoff, 3),
        "flight_time_s": round(touchdown["t"], 2),
        "apogee_km": round(apogee / 1000.0, 3),
        "downrange_at_td_km": round(touchdown["x"] / 1000.0, 3),
        "meco": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in (meco_state or {}).items()},
        "max_q_kpa": round(max_q / 1000.0, 2),
        "max_mach": round(max_mach, 2),
        "touchdown_v_vert_mps": round(touchdown["vy"], 2),
        "touchdown_v_horiz_mps": round(touchdown["vx"], 2),
        "touchdown_speed_mps": round(v_td, 2),
        "remaining_prop_kg": round(touchdown["remaining_prop"], 1),
        "prop_used_kg": round(veh.propellant_kg - touchdown["remaining_prop"], 1),
        "of_ratio": veh.of_ratio,
        "methane_frac": round(veh.methane_frac, 4),
        "methane_loaded_kg": round(veh.methane_loaded_kg, 1),
        "lox_loaded_kg": round(veh.lox_loaded_kg, 1),
        "methane_used_kg": round((veh.propellant_kg - touchdown["remaining_prop"]) * veh.methane_frac, 1),
        "lox_used_kg": round((veh.propellant_kg - touchdown["remaining_prop"]) * (1.0 - veh.methane_frac), 1),
        "methane_left_kg": round(touchdown["remaining_prop"] * veh.methane_frac, 1),
        "lox_left_kg": round(touchdown["remaining_prop"] * (1.0 - veh.methane_frac), 1),
        "methane_loaded_m3": round(veh.methane_loaded_kg / RHO_LCH4, 2),
        "lox_loaded_m3": round(veh.lox_loaded_kg / RHO_LOX, 2),
        "soft_landing": soft,
        "final_phase": phase,
        "reuse_verdict": (
            "SOFT LANDING — vehicle recoverable for inspect/refuel/reflight"
            if soft
            else "HARD/FAILED LANDING — not a reuse cycle this flight"
        ),
    }
    return {"summary": summary, "log": log, "touchdown": touchdown}


def save_plots(result: dict, out_dir: Path) -> list[str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    log = result["log"]
    t = np.array(log["t"])
    x = np.array(log["x"]) / 1000.0
    y = np.array(log["y"]) / 1000.0
    vx = np.array(log["vx"])
    vy = np.array(log["vy"])
    m = np.array(log["m"])
    q = np.array(log["q"]) / 1000.0
    phases = log["phase"]

    colors = {
        BOOST: "#e4572e",
        COAST: "#29335c",
        BOOSTBACK: "#f3a712",
        FALL: "#669bbc",
        LANDING: "#2a9d8f",
        LANDED: "#2a9d8f",
        FAILED: "#6d2e46",
    }

    def phase_segments(arr_x, arr_y):
        segs = []
        if not phases:
            return segs
        start = 0
        cur = phases[0]
        for i, p in enumerate(phases):
            if p != cur:
                segs.append((cur, arr_x[start:i], arr_y[start:i]))
                start, cur = i, p
        segs.append((cur, arr_x[start:], arr_y[start:]))
        return segs

    paths = []

    # Trajectory
    fig, ax = plt.subplots(figsize=(9.5, 6.2))
    for p, xs, ys in phase_segments(x, y):
        ax.plot(xs, ys, color=colors.get(p, "#333"), lw=2.2, label=p)
    ax.scatter([0], [0], marker="^", s=80, c="#111", zorder=5, label="pad")
    ax.scatter([x[-1]], [max(y[-1], 0)], marker="s", s=70, c="#2a9d8f", zorder=5, label="touchdown")
    ax.set_xlabel("Downrange (km)")
    ax.set_ylabel("Altitude (km)")
    ax.set_title("RR-01 reusable hop — trajectory by phase")
    ax.grid(True, alpha=0.3)
    # unique legend
    handles, labels = ax.get_legend_handles_labels()
    seen = set()
    h2, l2 = [], []
    for h, l in zip(handles, labels):
        if l not in seen:
            seen.add(l)
            h2.append(h)
            l2.append(l)
    ax.legend(h2, l2, loc="upper right", framealpha=0.92)
    fig.tight_layout()
    p1 = out_dir / "trajectory.png"
    fig.savefig(p1, dpi=140)
    plt.close(fig)
    paths.append(str(p1))

    # Time histories
    fig, axes = plt.subplots(3, 1, figsize=(9.5, 8.2), sharex=True)
    axes[0].plot(t, y, color="#29335c", lw=2)
    axes[0].set_ylabel("Altitude (km)")
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(t, vy, color="#e4572e", lw=1.8, label="vy")
    axes[1].plot(t, vx, color="#669bbc", lw=1.6, label="vx")
    axes[1].axhline(0, color="#888", lw=0.8)
    axes[1].set_ylabel("Velocity (m/s)")
    axes[1].legend(loc="upper right")
    axes[1].grid(True, alpha=0.3)
    axes[2].plot(t, m, color="#2a9d8f", lw=2)
    axes[2].set_ylabel("Mass (kg)")
    axes[2].set_xlabel("Time (s)")
    axes[2].grid(True, alpha=0.3)
    fig.suptitle("RR-01 flight history", y=0.995)
    fig.tight_layout()
    p2 = out_dir / "history.png"
    fig.savefig(p2, dpi=140)
    plt.close(fig)
    paths.append(str(p2))

    # Dynamic pressure
    fig, ax = plt.subplots(figsize=(9.5, 4.2))
    ax.plot(t, q, color="#f3a712", lw=2)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Dynamic pressure (kPa)")
    ax.set_title("Max-Q environment")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    p3 = out_dir / "maxq.png"
    fig.savefig(p3, dpi=140)
    plt.close(fig)
    paths.append(str(p3))

    return paths


def reuse_cycle_cost(veh: Vehicle, flights: int = 10) -> dict:
    """Order-of-magnitude reuse economics. Not a business plan."""
    expendable_unit = 4_800_000  # conceptual airframe+engine replacement $
    refurb_per_flight = 180_000
    propellant_per_flight = veh.propellant_kg * 1.6  # ~$1.6/kg class LOX/RP conceptual
    pad_ops = 45_000
    expendable_10 = expendable_unit * flights
    reusable_10 = expendable_unit + flights * (refurb_per_flight + propellant_per_flight + pad_ops)
    return {
        "flights": flights,
        "expendable_campaign_usd": expendable_10,
        "reusable_campaign_usd": round(reusable_10),
        "savings_usd": round(expendable_10 - reusable_10),
        "cost_per_flight_reusable_usd": round(reusable_10 / flights),
        "note": "Conceptual dollars for a small hopper-class vehicle. Not a quote.",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    plots = root / "plots"
    veh = Vehicle()
    msn = Mission()
    result = integrate(veh, msn)
    paths = save_plots(result, plots)
    econ = reuse_cycle_cost(veh)
    rel_plots = [str(Path(p).relative_to(root)) for p in paths]

    out_json = root / "sim" / "last_flight.json"
    slim = {
        "summary": result["summary"],
        "propellant": {
            "name": "LOX / methane",
            "of_ratio_mass": veh.of_ratio,
            "methane_percent": 20.0,
            "note": "4:1 oxidizer:fuel by mass. Stoichiometric allocation. Not a mix recipe.",
        },
        "economics": econ,
        "plots": rel_plots,
        "samples": {
            "t_head": result["log"]["t"][:3],
            "y_head_m": result["log"]["y"][:3],
            "n_samples": len(result["log"]["t"]),
        },
    }
    out_json.write_text(json.dumps(slim, indent=2))

    s = result["summary"]
    print("=== RR-01 reusable rocket sim ===")
    for k, v in s.items():
        print(f"  {k}: {v}")
    print("=== reuse economics (conceptual) ===")
    for k, v in econ.items():
        print(f"  {k}: {v}")
    print("plots:")
    for p in paths:
        print(" ", p)
    print("json:", out_json)


if __name__ == "__main__":
    main()
