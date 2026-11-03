"""Plant care: a tiny JoeBro plugin. State lives in JOEBRO_PLUGIN_DATA/plants.json."""
import json
import os
import time

DATA = os.path.join(os.environ.get("JOEBRO_PLUGIN_DATA", "."), "plants.json")
DAY = 86400


def _load():
    try:
        with open(DATA) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def _save(d):
    tmp = DATA + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, DATA)


def _row(name, p, now):
    days = (now - p["watered"]) / DAY if p.get("watered") else None
    return {"plant": name, "every_days": p["every"], "days_since": None if days is None else round(days, 1),
            "due": days is None or days >= p["every"]}


def plant_add(plant, every_days=7):
    d = _load()
    d[plant.strip()] = {"every": int(every_days), "watered": d.get(plant.strip(), {}).get("watered")}
    _save(d)
    return "Tracking %s, every %d days." % (plant.strip(), int(every_days))


def plant_watered(plant):
    d = _load()
    key = next((k for k in d if k.lower() == plant.strip().lower()), plant.strip())
    d.setdefault(key, {"every": 7})["watered"] = time.time()
    _save(d)
    return "Noted: %s watered." % key


def plants_all():
    now = time.time()
    return sorted((_row(k, v, now) for k, v in _load().items()), key=lambda r: r["plant"].lower())


def plants_due():
    return [r for r in plants_all() if r["due"]]
