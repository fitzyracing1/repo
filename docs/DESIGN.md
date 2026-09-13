# RR-01 — Reusable Rocket (conceptual)

**Status:** paper + simulation baseline. Nothing here is flight hardware.
**Scope:** educational architecture, mass budget, reuse loop, and a runnable point-mass flight model.
**Out of scope:** propellant chemistry, motor construction, grain geometry, range operations, or any live-fire how-to.

RR-01 is a *hopper-class* reusable first-stage stand-in. It exists to make the reuse loop concrete: launch, land, inspect, refuel, fly again. It is not an orbital vehicle. Orbit is ~7.8 km/s; this sim flies a short downrange hop and returns the same airframe to a pad.

This sits next to existing fitzyracing1 work:

- Open Source Spaceship / TSB-01 hex-panel ship (on-orbit assembly, not a lander)
- Amateur / 3" airframe line (sounding-scale expendable practice)
- Hardware-Prototype-Tracker issue #3

The split that already showed up in the TSB-01 work still holds: **the reusable booster is a different machine from the on-orbit assembled ship.** RR-01 is the booster side of that split.

---

## 1. Why reuse first

An expendable hopper is a science project. A reusable hopper is a factory test article.

The deciding cost is not the propellant. It is the airframe + engine + avionics that you either throw in the ocean or park on legs and fly again. The sim's economics block makes that visible at order-of-magnitude dollars: one vehicle + refurb + prop vs ten new vehicles.

Reuse only pays if three things are true at the same time:

1. Landing is soft enough that the structure and engine survive.
2. Turnaround is a checklist, not a rebuild.
3. The flight profile leaves margin in propellant and loads (max-Q, landing speed).

If any one fails, you are flying expendable with extra landing mass.

---

## 2. Vehicle allocation (Rev A)

| Item | Allocation | Note |
|---|---|---|
| Dry mass | 8,000 kg | structure, tanks, engine, avionics, legs, fins |
| Propellant | 18,000 kg | LOX / methane, **4:1 by mass = 20% CH₄** |
| Methane loaded | 3,600 kg | 20% of 18 t |
| LOX loaded | 14,400 kg | 80% of 18 t |
| Wet mass | 26,000 kg | |
| Sea-level thrust | 490 kN | liftoff T/W ≈ 1.92 |
| Vacuum thrust | 540 kN | |
| Isp SL / vac | 282 s / 311 s | public-domain gas-gen class numbers |
| Diameter / ref area | ~2.2 m / 3.8 m² | Cd 0.45 |
| Landing legs | +350 kg in dry | crush-core conceptual |
| Grid fins (aero control mass) | +180 kg in dry | modeled only as extra mass + crude fall damping |

These numbers are *allocations*. They exist so the integrator has a closed mass budget. They are not a BOM you can order.

---

## 3. Flight profile the sim actually flies

Open-loop phases. No Kalman filter, no closed-loop guidance. That is deliberate: the first artifact is a transparent energy budget, not a GNC thesis.

1. **Boost** — full throttle, shallow pitch after t = 4 s, cutoff at 16.5 s or dry-mass floor.
2. **Coast** — engine off, wait for vertical speed to drop.
3. **Boostback** — short retrograde burn to kill residual downrange velocity.
4. **Fall** — unpowered, grid-fin damping proxy.
5. **Landing burn** — suicide-burn altitude trigger + throttle against velocity with an upward bias.
6. **Touchdown** — scored soft if |vy| < 8 m/s and |vx| < 6 m/s with mass still above dry.

Success condition for *reuse* is the soft-landing flag, not apogee. A high hop that craters is an expendable flight that happened to go up first.

---

## 4. Reuse loop (the actual product)

```
pad prep → tank → launch → land → safing →
inspect (engine, tanks, legs, avionics) →
replace limited-life items → recertify →
refuel → pad
```

Turnaround gates (conceptual, not a procedure):

- Structure: no buckling, no leak at tank/feed interfaces
- Engine: start count and mixture-ratio / chamber-pressure health within band
- Landing gear: stroke used vs remaining crush margin
- Avionics: IMU / GNSS / flight computer power-on self test
- Thermal: no overtemp on base / engine bell from landing plume

Anything that requires cutting metal is not turnaround. It is a rebuild, and the economics block stops working.

---

## 5. What this does *not* do

- It does not get TSB-01 to orbit. Buy the ride or design a real orbital first stage later.
- It does not land TSB-01 on Mars. That vehicle is a transfer hull; EDL is a different stack.
- It does not tell you how to mix propellant or machine a chamber.
- It does not replace range safety, licensing, or a real GNC stack.

---

## 6. Baseline flight (this sandbox run)

| Metric | Value |
|---|---|
| Liftoff T/W | 1.92 |
| MECO | t = 16.5 s, 1.32 km, vy = 164 m/s |
| Apogee | 2.58 km |
| Downrange at touchdown | 0.25 km |
| Touchdown | vy = −7.4 m/s, vx ≈ 0 |
| Prop used / remaining | 6,995 kg / 11,005 kg |
| Of that, methane used / left | 1,399 kg / 2,201 kg |
| Of that, LOX used / left | 5,596 kg / 8,804 kg |
| Max-Q | 14.5 kPa |
| Soft landing | YES — reuse cycle open |

The landing burn starts on a suicide-burn altitude estimate and bleeds to hover-ish T/W near the deck. Open-loop. Margin is the leftover 11 t of propellant, not elegance.

---

## 7. Next increment (one only)

Close the landing burn with a simple gravity-turn + suicide-burn predictor (time-to-go = v / a_net) instead of the altitude trigger. Same vehicle, same file, one function.
