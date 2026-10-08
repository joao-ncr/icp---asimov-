"""Carrega profile/*.yaml para o banco e para memoria."""
from __future__ import annotations
from app.core.settings import get_settings
from app.core.utils import jdump, load_yaml
from app.intelligence.signals import taxonomy


def load_profile() -> dict:
    d = get_settings().profile_dir
    return {"asimov": load_yaml(d / "asimov.yaml"), "icps": load_yaml(d / "icps.yaml")}


def seed_db(conn) -> None:
    p = load_profile()
    for s in p["asimov"]["services"]:
        conn.execute("INSERT OR REPLACE INTO service VALUES(?,?,?,?,?)", (s["id"], s["name"], jdump(s["stack"]), jdump(s["problems_solved"]), s["hypothesis_template"]))
    for c in p["asimov"]["case_studies"]:
        conn.execute("INSERT OR REPLACE INTO case_study VALUES(?,?,?,?,?,?,?)", (c["id"], c["client"], c["service"], c["problem"], jdump(c.get("capabilities", [])), int(c["verified"]), c["source"]))
    for i in p["icps"]["icps"]:
        conn.execute("INSERT OR REPLACE INTO icp VALUES(?,?,?,?,?,?)", (i["id"], i["name"], jdump(i["services"]), i["status"], i["confidence"], jdump(i)))
    for code, s in taxonomy().items():
        conn.execute("INSERT OR REPLACE INTO signal VALUES(?,?,?,?,?,?,?,?,?)", (code, s["category"], s["kind"], s["source"], s["strength"], s["observability"], s["description"], s["interpretation"], jdump(s.get("services") or s.get("reduces") or {})))
    conn.commit()
