"""Build the Transferegov test fixtures in tests/fixtures/transferegov from the live API.

Takes a seeded sample of Santa Catarina plans, always including the plans of the special
transfers present in the federal fixture, plus plans from two other states. Keeps only the
fields the pipeline loads and drops plans whose text carries an 11-digit sequence.
"""

import argparse
import csv
import json
import random
import re
from pathlib import Path

from rastro.config import get_settings
from rastro.ingest.transferegov import (
    BENEFICIARIOS,
    EMPENHOS,
    EXECUTORES,
    PLANOS_ACAO,
    PLANOS_TRABALHO,
    RESOURCES,
    TransferegovClient,
    fetch_santa_catarina,
)

SEED = 42
RANDOM_PLANS = 30
PLANS_PER_CODE = 3
OTHER_STATE = "PR"
OTHER_BENEFICIARIES = 2
CPF_LIKE = re.compile(r"(?<![0-9])[0-9]{11}(?![0-9])")
FEDERAL_FIXTURE = Path("tests/fixtures/EmendasParlamentares.csv")


def federal_special_codes() -> set[str]:
    with FEDERAL_FIXTURE.open(encoding="latin-1", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        header = next(reader)
        uf, kind, code = (
            header.index("UF"),
            header.index("Tipo de Emenda"),
            header.index("Código da Emenda"),
        )
        return {
            r[code]
            for r in reader
            if r[uf] == "SANTA CATARINA" and r[kind].endswith("Transferências Especiais")
        }


def has_cpf_like(row: dict) -> bool:
    return any(isinstance(v, str) and CPF_LIKE.search(v) for v in row.values())


def pick_plans(data: dict[str, list[dict]], rng: random.Random) -> set[int]:
    planos = data[PLANOS_ACAO.table]
    by_plan = {resource.table: {} for resource in (EXECUTORES, PLANOS_TRABALHO, EMPENHOS)}
    for table, groups in by_plan.items():
        for row in data[table]:
            groups.setdefault(row["id_plano_acao"], []).append(row)
    beneficiary = {b["id_beneficiario"]: b["nome_beneficiario"] for b in data[BENEFICIARIOS.table]}

    def children(plan, table):
        return by_plan[table].get(plan["id_plano_acao"], [])

    clean = [
        p
        for p in planos
        if not has_cpf_like(p) and not any(has_cpf_like(r) for t in by_plan for r in children(p, t))
    ]
    special = federal_special_codes()
    linked = []
    for code in sorted(special):
        of_code = [p for p in clean if str(p["numero_emenda_parlamentar_plano_acao"]) == code]
        linked += rng.sample(of_code, min(PLANS_PER_CODE, len(of_code)))
    chosen = {p["id_plano_acao"] for p in linked}
    chosen |= {p["id_plano_acao"] for p in rng.sample(clean, RANDOM_PLANS)}

    edge_cases = [
        lambda p: p["situacao_plano_acao"] == "IMPEDIDO" and p["motivo_impedimento_plano_acao"],
        lambda p: p["situacao_plano_acao"].startswith("Plano de Trabalho em Elaboração"),
        lambda p: not p["nome_objeto"],
        lambda p: bool(p["nome_objeto"]),
        lambda p: beneficiary[p["id_beneficiario"]] == "ESTADO DE SANTA CATARINA",
        lambda p: not beneficiary[p["id_beneficiario"]].startswith("MUNICIPIO DE "),
        lambda p: len(children(p, EMPENHOS.table)) == 2,
        lambda p: any(e["situacao_empenho"] == 1 for e in children(p, EMPENHOS.table)),
        lambda p: len(children(p, EXECUTORES.table)) == 2,
        lambda p: not children(p, EXECUTORES.table),
        lambda p: not children(p, PLANOS_TRABALHO.table),
        lambda p: any(
            e["nome_executor"] != beneficiary[p["id_beneficiario"]]
            for e in children(p, EXECUTORES.table)
        ),
    ]
    for predicate in edge_cases:
        if not any(predicate(p) for p in clean if p["id_plano_acao"] in chosen):
            matches = [p for p in clean if predicate(p)]
            if matches:
                chosen.add(rng.choice(matches)["id_plano_acao"])
    return chosen


def other_state(client: TransferegovClient) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {resource.table: [] for resource in RESOURCES}
    for beneficiary in list(client.rows(BENEFICIARIOS.endpoint, uf_beneficiario=OTHER_STATE))[
        :OTHER_BENEFICIARIES
    ]:
        result[BENEFICIARIOS.table].append(beneficiary)
        planos = list(
            client.rows(PLANOS_ACAO.endpoint, id_beneficiario=beneficiary["id_beneficiario"])
        )[:1]
        result[PLANOS_ACAO.table] += planos
        for plano in planos:
            for resource in (EXECUTORES, PLANOS_TRABALHO, EMPENHOS):
                result[resource.table] += list(
                    client.rows(resource.endpoint, id_plano_acao=plano["id_plano_acao"])
                )
    return result


def main(out: Path) -> None:
    client = TransferegovClient(get_settings().transferegov_base_url)
    sc = fetch_santa_catarina(client)
    chosen = pick_plans(sc, random.Random(SEED))
    sample = {PLANOS_ACAO.table: [p for p in sc[PLANOS_ACAO.table] if p["id_plano_acao"] in chosen]}
    wanted = {p["id_beneficiario"] for p in sample[PLANOS_ACAO.table]}
    sample[BENEFICIARIOS.table] = [
        b for b in sc[BENEFICIARIOS.table] if b["id_beneficiario"] in wanted
    ]
    for resource in (EXECUTORES, PLANOS_TRABALHO, EMPENHOS):
        sample[resource.table] = [r for r in sc[resource.table] if r["id_plano_acao"] in chosen]

    for table, rows in other_state(client).items():
        sample[table] += rows

    out.mkdir(parents=True, exist_ok=True)
    for resource in RESOURCES:
        rows = [{c: row[c] for c in resource.columns} for row in sample[resource.table]]
        rows.sort(key=lambda row: row[resource.key])
        (out / f"{resource.endpoint}.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1, default=lambda d: float(d)) + "\n",
            encoding="utf-8",
        )
        print(f"{resource.endpoint}: {len(rows)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path("tests/fixtures/transferegov"))
    main(parser.parse_args().out)
