import argparse
from pathlib import Path

import pandas as pd


DEFAULT_SOURCE = "2026-09-10T1827_Grades-FA26_COMPSCI_220_001.csv"


def name_keys(names):
    return names.str.strip().str.casefold().str.replace(r"\s+", " ", regex=True)


def validate_names(keys, label):
    if keys.eq("").any():
        raise ValueError(f"{label}: empty student name")
    if keys.duplicated().any():
        raise ValueError(f"{label}: duplicate student names; cannot match by name safely")


def main():
    parser = argparse.ArgumentParser(description="Create a lab attendance CSV or merge it into a Canvas export.")
    parser.add_argument("action", choices=["init", "merge"], nargs="?", default="init")
    parser.add_argument("--lab", default="Lab-P2", help="Lab title, e.g. Lab-P3, or its full Canvas column name")
    parser.add_argument("--source", type=Path, default=Path(DEFAULT_SOURCE))
    parser.add_argument("--scores", type=Path, help="Two-column attendance CSV")
    parser.add_argument("--output", type=Path, help="Merged Canvas CSV (merge only)")
    args = parser.parse_args()

    try:
        if args.action == "init" and args.output is not None:
            raise ValueError("Use --scores to choose the init output file")

        # Read as text so IDs, blanks, and unrelated grades survive unchanged.
        source = pd.read_csv(args.source, dtype="string", keep_default_na=False)
        if not {"Student", "ID", "Section"}.issubset(source.columns):
            raise ValueError("Source must contain Student, ID, and Section columns")
        matches = [c for c in source.columns if c == args.lab or c.startswith(args.lab + " (")]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one Canvas assignment matching {args.lab!r}")
        lab_column = matches[0]
        lab_title = lab_column.rsplit(" (", 1)[0]
        stem = lab_title.lower().replace("-", "_")
        scores_path = args.scores or Path(f"{stem}_attendance.csv")

        student_mask = source["ID"].str.strip().ne("")
        students = source.loc[student_mask]
        if students.empty:
            raise ValueError("Source contains no students")
        if students["ID"].duplicated().any():
            raise ValueError("Source contains duplicate student IDs")
        keys = name_keys(students["Student"])
        validate_names(keys, "Source")

        if args.action == "init":
            result = students[["Student"]].copy()
            result[lab_column] = 0
            destination = scores_path
        else:
            scores = pd.read_csv(scores_path, dtype="string", keep_default_na=False)
            if scores.columns.tolist() != ["Student", lab_column]:
                raise ValueError(f"Attendance columns must be Student and {lab_column}")
            score_keys = name_keys(scores["Student"])
            validate_names(score_keys, "Attendance")
            unknown = set(score_keys) - set(keys)
            missing = set(keys) - set(score_keys)
            if unknown or missing:
                raise ValueError(f"Roster mismatch: {len(unknown)} unknown and {len(missing)} missing names")

            points_rows = source.loc[
                ~student_mask & source["Student"].str.strip().eq("Points Possible"), lab_column
            ]
            if len(points_rows) != 1:
                raise ValueError("Source must contain one Points Possible row")
            max_points = float(points_rows.iloc[0])
            if not 0 < max_points < float("inf"):
                raise ValueError("Invalid Points Possible value")
            numeric = pd.to_numeric(scores[lab_column], errors="coerce")
            if numeric.isna().any() or not numeric.between(0, max_points).all():
                raise ValueError(f"Every score must be a number between 0 and {max_points:g}")

            by_name = pd.Series(scores[lab_column].str.strip().to_numpy(), index=score_keys)
            result = source.copy()
            result.loc[student_mask, lab_column] = keys.map(by_name)
            destination = args.output or Path(f"{stem}_import.csv")

        if args.action == "merge":
            for input_path in (args.source, scores_path):
                if destination.resolve() == input_path.resolve() or (
                    destination.exists() and destination.samefile(input_path)
                ):
                    raise ValueError("Merged output must not overwrite the source or attendance CSV")

        # Merge output can be regenerated; init must preserve existing scores.
        mode = "w" if args.action == "merge" else "x"
        with destination.open(mode, encoding="utf-8", newline="") as handle:
            result.to_csv(handle, index=False)
        print(f"Saved {destination} ({len(students)} students, {lab_column})")
    except (ValueError, OSError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
