from ui.views.view_results import _dataset_basename as b
cases = [
    ("/app/storage/datasets/eve_100k_fixed.json", "eve_100k_fixed.json"),
    ("D:\\Program\\TA\\storage\\datasets\\ALLFLOWMETER_HIKARI2021.csv", "ALLFLOWMETER_HIKARI2021.csv"),
    ("eve_sample_1000000.jsonl", "eve_sample_1000000.jsonl"),
    ("", "-"),
    (None, "-"),
    ("/mixed/with\\backslash/foo.csv", "foo.csv"),
    ("C:/forward/on/windows.json", "windows.json"),
]
ok = 0
for raw, expect in cases:
    got = b(raw)
    mark = "OK" if got == expect else "FAIL"
    if got == expect:
        ok += 1
    print(f"  {mark}  input={raw!r:65s} -> {got!r:30s}  expect={expect!r}")
print(f"\n{ok}/{len(cases)} passed")
