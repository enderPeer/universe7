"""Enumerate and verify all 256 one-byte Universe 7 programs locally.

    python tools/byte_catalog.py

The original ISA and 127-step horizon are unchanged. This host-side observer
saves every screen and head position, plus a readable list and a compact trace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import struct
import time
from collections import Counter, defaultdict

import ref


ROOT = pathlib.Path(__file__).resolve().parent.parent
STEPS = 127
NAMES = ("F4", "F8", "S3", "C3")
MOVES = (4, 8, 3, 3)


def execute(screen: int, head: int, opcode: int) -> tuple[int, int]:
    """Independent observer implementation; ref.run is the verification oracle."""
    mask = 1 << head
    if opcode < 2:
        screen ^= mask
    elif opcode == 2:
        screen |= mask
    else:
        screen &= ~mask
    return screen, (head + MOVES[opcode]) % 64


def symmetry_names(screen: int) -> list[str]:
    transforms = {
        "left-right": lambda x, y: (7 - x, y),
        "top-bottom": lambda x, y: (x, 7 - y),
        "half-turn": lambda x, y: (7 - x, 7 - y),
        "quarter-turn": lambda x, y: (7 - y, x),
        "main-diagonal": lambda x, y: (y, x),
        "anti-diagonal": lambda x, y: (7 - y, 7 - x),
    }
    names = []
    for name, transform in transforms.items():
        transformed = 0
        for bit in range(64):
            if screen & (1 << bit):
                x, y = transform(bit % 8, bit // 8)
                transformed |= 1 << (8 * y + x)
        if screen == transformed:
            names.append(name)
    return names


def cycle_for(opcodes: list[int]) -> dict[str, int]:
    """Find an exact repeated (screen, head, next instruction index) state.

    The guard is deliberately explicit: never silently infer a cycle from a
    repeated screen alone. These one-byte machines all repeat within it.
    """
    seen = {}
    screen = head = 0
    for step in range(4097):
        state = (screen, head, step % 4)
        if state in seen:
            return {"start_step": seen[state], "period_steps": step - seen[state]}
        seen[state] = step
        screen, head = execute(screen, head, opcodes[step % 4])
    raise RuntimeError("No exact cycle found within the bounded observer search")


def program_record(program: int) -> dict:
    opcodes = [(program >> shift) & 3 for shift in (6, 4, 2, 0)]
    screens = [0]
    heads = [0]
    visits = [0] * 64
    changes = 0
    for step in range(STEPS):
        visits[heads[-1]] += 1
        screen, head = execute(screens[-1], heads[-1], opcodes[step % 4])
        changes += screen != screens[-1]
        screens.append(screen)
        heads.append(head)
    final = screens[-1]
    return {
        "id": program,
        "hex": f"{program:02X}",
        "bits": f"{program:08b}",
        "instructions": [NAMES[opcode] for opcode in opcodes],
        "opcodes": opcodes,
        "final_screen": f"{final:016x}",
        "final_head": heads[-1],
        "lit_pixels": final.bit_count(),
        "visited_pixels": sum(count > 0 for count in visits),
        "pixel_changes": changes,
        "visit_counts": visits,
        "symmetries": symmetry_names(final),
        "cycle": cycle_for(opcodes),
        "trace": {
            "screens": [f"{screen:016x}" for screen in screens],
            "heads": heads,
        },
    }


def build_catalog() -> dict:
    records = [program_record(program) for program in range(256)]
    equivalent = defaultdict(list)
    for record in records:
        equivalent[record["final_screen"]].append(record["id"])
    for record in records:
        record["equivalent_program_ids"] = equivalent[record["final_screen"]]
    groups = sorted(equivalent.values(), key=lambda ids: ids[0])
    distinct_traces = len({tuple(p["trace"]["screens"]) for p in records})
    return {
        "schema_version": "universe7-one-byte-v1",
        "machine": {
            "name": "Universe 7",
            "program_bits": 8,
            "instructions_per_program": 4,
            "decode_order": "Most significant two bits first; cyclic four-instruction program.",
            "steps": STEPS,
            "screen_width": 8,
            "screen_height": 8,
            "initial_screen": "0000000000000000",
            "initial_head": 0,
            "pixel_order": "Bit i is pixel x=i%8, y=i//8; top-left is bit 0.",
            "head_update": "Apply pixel operation at old head, then add stride modulo 64.",
            "instructions": [
                {"bits": "00", "name": "F4", "operation": "flip", "stride": 4},
                {"bits": "01", "name": "F8", "operation": "flip", "stride": 8},
                {"bits": "10", "name": "S3", "operation": "set", "stride": 3},
                {"bits": "11", "name": "C3", "operation": "clear", "stride": 3},
            ],
            "scope": "No inputs, arithmetic registers, conditionals, or code mutation; outputs are screens.",
        },
        "summary": {
            "programs": len(records),
            "distinct_final_screens": len(equivalent),
            "distinct_screen_traces": distinct_traces,
            "programs_with_unique_final_screen": sum(len(ids) == 1 for ids in groups),
            "duplicate_final_screen_groups": [ids for ids in groups if len(ids) > 1],
            "dark_final_program_ids": equivalent.get("0000000000000000", []),
            "full_final_program_ids": equivalent.get("ffffffffffffffff", []),
            "lit_pixel_histogram": dict(sorted(Counter(p["lit_pixels"] for p in records).items())),
            "visited_pixel_histogram": dict(sorted(Counter(p["visited_pixels"] for p in records).items())),
            "max_cycle_period_steps": max(p["cycle"]["period_steps"] for p in records),
            "max_cycle_start_step": max(p["cycle"]["start_step"] for p in records),
        },
        "trace_format": {
            "file": "traces.bin",
            "program_order": "Program integer 0 through 255",
            "frames_per_program": STEPS + 1,
            "frame_order": "State after 0 (initial) through 127 instructions",
            "bytes_per_frame": 9,
            "screen": "First 8 bytes: unsigned little-endian 64-bit integer",
            "head": "Ninth byte: unsigned 8-bit position, 0..63",
            "offset_formula": "(program_id * 128 + step) * 9",
            "next_instruction_index": "step % 4 (not stored)",
        },
        "metric_definitions": {
            "lit_pixels": "Lit pixels on the final screen after 127 instructions.",
            "visited_pixels": "Distinct positions at which a pixel operation executed within the first 127 instructions.",
            "pixel_changes": "Instructions that changed a pixel within the first 127 instructions; set/clear can leave a pixel unchanged.",
            "equivalent_program_ids": "Exactly the programs with the same final screen at step 127, including this program; trajectories need not match.",
            "symmetries": "Geometric symmetries of the final 8x8 screen, with the screen center fixed.",
            "cycle": "Exact eventual cycle of (screen, head, next instruction index) if execution continues indefinitely. The observer searches beyond step 127 when needed; saved traces still end at 127.",
        },
        "programs": records,
    }


def verify(catalog: dict, trace_bytes: bytes) -> dict:
    screen_checks = head_checks = binary_checks = 0
    for program in catalog["programs"]:
        for step in range(STEPS + 1):
            actual = int(program["trace"]["screens"][step], 16)
            expected = ref.run(program["bits"], steps=step)
            if actual != expected:
                raise AssertionError(f"Reference mismatch for {program['hex']} step {step}")
            screen_checks += 1
            expected_head = sum(MOVES[program["opcodes"][i % 4]] for i in range(step)) % 64
            if program["trace"]["heads"][step] != expected_head:
                raise AssertionError(f"Head mismatch for {program['hex']} step {step}")
            head_checks += 1
            offset = (program["id"] * (STEPS + 1) + step) * 9
            binary_screen, binary_head = struct.unpack_from("<QB", trace_bytes, offset)
            if (binary_screen, binary_head) != (actual, expected_head):
                raise AssertionError("Binary trace round-trip mismatch")
            binary_checks += 1
        cycle = program["cycle"]
        start = cycle["start_step"]
        end = start + cycle["period_steps"]
        if ref.run(program["bits"], start) != ref.run(program["bits"], end):
            raise AssertionError("Cycle screen does not repeat in the reference")
        if cycle["period_steps"] % 4 != 0:
            raise AssertionError("Cycle does not preserve the next instruction")
        cycle_displacement = sum(MOVES[opcode] for opcode in program["opcodes"]) * (cycle["period_steps"] // 4)
        if cycle_displacement % 64 != 0:
            raise AssertionError("Cycle does not preserve the head")
    return {
        "reference": "tools/ref.py:run(bits, steps)",
        "reference_screen_comparisons": screen_checks,
        "independent_head_checks": head_checks,
        "binary_frame_round_trips": binary_checks,
        "reference_cycle_checks": 256,
        "mismatches": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, default=ROOT / "results" / "one-byte")
    args = parser.parse_args()
    started = time.perf_counter()
    catalog = build_catalog()
    generated = time.perf_counter()
    traces = b"".join(
        struct.pack("<QB", int(screen, 16), head)
        for p in catalog["programs"]
        for screen, head in zip(p["trace"]["screens"], p["trace"]["heads"])
    )
    checks = verify(catalog, traces)
    verified = time.perf_counter()
    catalog["trace_format"]["sha256"] = hashlib.sha256(traces).hexdigest()
    catalog["trace_format"]["size_bytes"] = len(traces)
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    (output / "catalog.json").write_text(json.dumps(catalog, separators=(",", ":")) + "\n", encoding="utf-8")
    (output / "traces.bin").write_bytes(traces)
    columns = ["id", "hex", "bits", "instructions", "final_screen_hex", "lit_pixels", "final_head", "visited_pixels", "pixel_changes", "cycle_start", "cycle_period", "same_final_program_hex", "symmetries", "screen_rows"]
    lines = ["\t".join(columns)]
    for p in catalog["programs"]:
        rows = ref.picture(int(p["final_screen"], 16)).strip().replace("\n", "/")
        fields = [p["id"], p["hex"], p["bits"], " ".join(p["instructions"]), p["final_screen"], p["lit_pixels"], p["final_head"], p["visited_pixels"], p["pixel_changes"], p["cycle"]["start_step"], p["cycle"]["period_steps"], " ".join(f"{n:02X}" for n in p["equivalent_program_ids"]), ",".join(p["symmetries"]), rows]
        lines.append("\t".join(map(str, fields)))
    (output / "all-programs.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    checks["source_sha256"] = {
        "tools/ref.py": hashlib.sha256((ROOT / "tools" / "ref.py").read_bytes()).hexdigest(),
        "tools/byte_catalog.py": hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
    }
    checks["artifact_sha256"] = {
        name: hashlib.sha256((output / name).read_bytes()).hexdigest()
        for name in ("catalog.json", "all-programs.tsv", "traces.bin")
    }
    checks["timings_seconds"] = {
        "catalog_generation": round(generated - started, 6),
        "trace_packing_and_verification": round(verified - generated, 6),
        "total_before_verification_report": round(time.perf_counter() - started, 6),
    }
    checks["timing_note"] = "Single local Python process; timings include exhaustive reference reruns and are not a GPU/cluster benchmark."
    (output / "verification.json").write_text(json.dumps(checks, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": catalog["summary"], "verification": checks}, indent=2))


if __name__ == "__main__":
    main()
