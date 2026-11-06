"""Build the test fixtures in tests/fixtures from the full CSVs in data/raw.

Takes a seeded sample of Santa Catarina rows plus a few rows from other states, keeps the
references between files, and masks individuals.
"""

import argparse
import csv
import random
import re
from collections import defaultdict
from pathlib import Path

MAIN = "EmendasParlamentares.csv"
CONV = "EmendasParlamentares_Convenios.csv"
FAV = "EmendasParlamentares_PorFavorecido.csv"
NO_INFO = "Sem informação"
CPF_LIKE = re.compile(r"\d{11}")
SEED = 42


def read(path: Path) -> tuple[list[str], list[list[str]]]:
    with path.open(encoding="latin-1", newline="") as f:
        reader = csv.reader(f, delimiter=";")
        return next(reader), list(reader)


def write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with path.open("w", encoding="latin-1", newline="") as f:
        writer = csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
        writer.writerow(header)
        writer.writerows(rows)


def with_edge_cases(sample: list, pool: list, predicates: list, rng: random.Random) -> list:
    """Add one row per predicate when the sample has none that matches it."""
    chosen = list(sample)
    for predicate in predicates:
        if not any(predicate(r) for r in chosen):
            matches = [r for r in pool if predicate(r)]
            if matches:
                chosen.append(rng.choice(matches))
    return chosen


def cap_per_key(rows: list[list[str]], key: int, cap: int, rng: random.Random) -> list[list[str]]:
    groups: dict[str, list[list[str]]] = defaultdict(list)
    for row in rows:
        groups[row[key]].append(row)
    out: list[list[str]] = []
    for code in sorted(groups):
        group = groups[code]
        out.extend(rng.sample(group, min(cap, len(group))))
    return out


def main(raw: Path, out: Path) -> None:
    rng = random.Random(SEED)
    out.mkdir(parents=True, exist_ok=True)

    main_h, main_rows = read(raw / MAIN)
    m = {name: i for i, name in enumerate(main_h)}
    is_sc = lambda r: r[m["UF"]] == "SANTA CATARINA"  # noqa: E731
    sc_rows = [r for r in main_rows if is_sc(r)]
    other_rows = [r for r in main_rows if not is_sc(r)]

    sc_sample = rng.sample(sc_rows, 260)
    sc_sample = with_edge_cases(
        sc_sample,
        sc_rows,
        [
            lambda r: r[0] == NO_INFO,
            lambda r: r[m["Localidade de aplicação do recurso"]] == "MÚLTIPLO",
            lambda r: r[m["Localidade de aplicação do recurso"]] == "SANTA CATARINA (UF)",
            lambda r: r[m["Tipo de Emenda"]].endswith("Transferências Especiais"),
            lambda r: r[m["Tipo de Emenda"]] == "Emenda de Bancada",
            lambda r: r[m["Tipo de Emenda"]] == "Emenda de Comissão",
            lambda r: r[m["Tipo de Emenda"]] == "Emenda de Relator",
        ],
        rng,
    )
    other_sample = rng.sample(other_rows, 40)
    other_sample = with_edge_cases(
        other_sample,
        other_rows,
        [
            lambda r: r[m["Localidade de aplicação do recurso"]] == "Nacional",
            lambda r: r[m["Localidade de aplicação do recurso"]] == "MÚLTIPLO",
            lambda r: r[m["Valor Restos A Pagar Inscritos"]].startswith("-"),
        ],
        rng,
    )

    codes = {r[0] for r in sc_sample if r[0] != NO_INFO}

    fav_h, fav_rows = read(raw / FAV)
    f = {name: i for i, name in enumerate(fav_h)}
    linked = [r for r in fav_rows if r[0] in codes and not CPF_LIKE.search(r[f["Favorecido"]])]
    unlinked = [r for r in fav_rows if r[0] == NO_INFO and not CPF_LIKE.search(r[f["Favorecido"]])]
    fav_sample = cap_per_key(linked, 0, 2, rng)
    sc_linked = [r for r in fav_rows if r[0] in {x[0] for x in sc_rows if x[0] != NO_INFO}]
    sc_linked = [r for r in sc_linked if not CPF_LIKE.search(r[f["Favorecido"]])]
    fav_sample = with_edge_cases(
        fav_sample,
        sc_linked,
        [
            lambda r: r[f["Tipo Favorecido"]] == "Pessoa Fisica",
            lambda r: r[f["Tipo Favorecido"]] == "Pessoa Jurídica",
            lambda r: r[f["Tipo Favorecido"]] == "Unidade Gestora",
            lambda r: r[f["Tipo Favorecido"]].startswith("Inscrição Genéric"),
            lambda r: r[f["Tipo Favorecido"]] == "Sem informação",
            lambda r: r[f["Valor Recebido"]].startswith("-"),
            lambda r: r[f["UF Favorecido"]] != "SC",
        ],
        rng,
    )
    fav_sample += rng.sample(unlinked, 5)

    # Every linked favorecido row must point to an emenda present in the main fixture.
    present = {r[0] for r in sc_sample}
    for row in fav_sample:
        if row[0] != NO_INFO and row[0] not in present:
            sc_sample.append(next(r for r in sc_rows if r[0] == row[0]))
            present.add(row[0])

    individuals = 0
    for row in fav_sample:
        if row[f["Tipo Favorecido"]] == "Pessoa Fisica":
            individuals += 1
            row[f["Código do Favorecido"]] = "***.000.000-**"
            row[f["Favorecido"]] = f"PESSOA FISICA {individuals:03d}"

    conv_h, conv_rows = read(raw / CONV)
    c = {name: i for i, name in enumerate(conv_h)}
    all_codes = {r[0] for r in sc_sample + other_sample if r[0] != NO_INFO}
    conv_pool = [r for r in conv_rows if r[0] in all_codes]
    conv_sample = cap_per_key(conv_pool, 0, 2, rng)
    loc = c["Localidade do gasto"]
    conv_sample = with_edge_cases(
        conv_sample,
        conv_pool,
        [
            lambda r: r[loc] == "SANTA CATARINA (UF)",
            lambda r: r[loc].endswith(" - SC"),
            lambda r: not r[loc].endswith(" - SC") and r[loc] != "SANTA CATARINA (UF)",
            lambda r: r[c["Objeto Convênio"]] == "",
        ],
        rng,
    )
    present = {r[0] for r in sc_sample + other_sample}
    for row in conv_sample:
        if row[0] != NO_INFO and row[0] not in present:
            raise SystemExit(f"convenio references an emenda outside the sample: {row[0]}")

    write(out / MAIN, main_h, sc_sample + other_sample)
    write(out / CONV, conv_h, conv_sample)
    write(out / FAV, fav_h, fav_sample)
    print(f"{MAIN}: {len(sc_sample) + len(other_sample)} rows ({len(sc_sample)} from SC)")
    print(f"{CONV}: {len(conv_sample)} rows")
    print(f"{FAV}: {len(fav_sample)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--out", type=Path, default=Path("tests/fixtures"))
    args = parser.parse_args()
    main(args.raw, args.out)
