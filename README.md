# RR-01 Reusable Rocket

Runnable conceptual model of a hopper-class reusable rocket: boost, boostback, landing burn, reuse score.

**Pad load locked: 20% methane / 80% LOX, 4:1 by mass** (3,600 kg CH₄ + 14,400 kg LOX = 18,000 kg).

Educational simulation and architecture only. No motor construction, no mix recipe, no range-ops manual.

## Layout

```
reusable-rocket/
  README.md
  docs/DESIGN.md          architecture, mass budget, reuse loop
  docs/index.html         GitHub Pages site
  docs/assets/            plots used by the site
  docs/PROPELLANT.md      20% methane / 4:1 LOX split
  sim/rr01.py             point-mass integrator + plots + economics
  sim/last_flight.json    last run summary (written by the sim)
  plots/                  trajectory, history, max-Q
```

## Run

```
python3 sim/rr01.py
```

Requires numpy and matplotlib (present in this sandbox).

Soft landing is the reuse gate: vertical speed under 8 m/s, horizontal under 6 m/s, mass still above dry.

## Site

`docs/index.html` is the public page. After push:

GitHub repo → Settings → Pages → Source: **Deploy from a branch** → `main` / `/docs`.

Live URL will be `https://fitzyracing1.github.io/reusable-rocket/` if the repo is named `reusable-rocket`.

## Relation to other projects

- TSB-01 / Teslabotspacecruiser — on-orbit assembled ship. Not a lander. RR-01 is the booster-side analog.
- Hardware-Prototype-Tracker `Open Source Spaceship` (#3) — concept tracker this can log against.
- Amateur 3" line — expendable practice hardware; this file is the reuse argument, not a scale-up of that motor.
