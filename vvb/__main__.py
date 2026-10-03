"""CLI: vvb run | check | preview | resume | presets."""
from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from .api import make_job
from .batch import BatchRunner, find_unfinished, job_from_journal
from .events import Event, EventBus
from .plan import plan_job
from .preset_io import PresetError, list_presets, load_preset

COLORS = {"error": "\033[31m", "warn": "\033[33m", "warning": "\033[33m", "success": "\033[32m",
          "info": "\033[0m", "debug": "\033[90m"}
RESET = "\033[0m"


def _csv(s: Optional[str]) -> Optional[list[str]]:
    return [x.strip() for x in s.split(",") if x.strip()] if s else None


def _add_job_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--preset", required=True, help="Tên preset (palm_bottom) hoặc đường dẫn .json")
    p.add_argument("--project", help="Thư mục dự án (tự nhận slot theo tên folder)")
    p.add_argument("--slot", action="append", default=[], metavar="TÊN=ĐƯỜNG_DẪN",
                   help="Chỉ định đường dẫn slot. Cũng có thể dùng --<tên_slot> <đường_dẫn>")
    p.add_argument("--out", help="Thư mục Output (mặc định <project>/Output)")
    p.add_argument("--groups", help="Chỉ chạy các nhóm: arab,french")
    p.add_argument("--clips", help="Chỉ chạy các clip: clip01,clip02")
    p.add_argument("--limit", type=int, help="Giới hạn tổng số video")
    p.add_argument("--mode", choices=["cartesian", "zip", "per_group_subset", "no_pool"])
    p.add_argument("--subset-k", type=int)
    p.add_argument("--seed", type=int)
    p.add_argument("--workers", type=int)
    p.add_argument("--quality", choices=["fast", "high", "max", "bitrate"])
    p.add_argument("--bitrate", type=float, help="Mbps khi --quality bitrate")
    p.add_argument("--codec", choices=["h264", "h265", "h264_nvenc", "hevc_nvenc", "h264_videotoolbox",
                                       "h264_qsv", "h264_amf"])
    p.add_argument("--speed", dest="preset_speed",
                   choices=["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow"])
    p.add_argument("--resolution")
    p.add_argument("--fps")
    p.add_argument("--existing", choices=["skip", "overwrite", "rename"])
    p.add_argument("--retry", type=int)
    p.add_argument("--stop-on-error", action="store_true")
    p.add_argument("--keep-temp", action="store_true")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--temp-dir")
    p.add_argument("--thumbnails", action="store_true")
    p.add_argument("--normalize", type=float, metavar="LUFS", help="Chuẩn hoá loudness, ví dụ -14")
    p.add_argument("--no-sleep-block", action="store_true")
    p.add_argument("--log-level", choices=["info", "debug"], default="info")
    p.add_argument("--json", action="store_true", help="In kết quả dạng JSON")


def _apply_overrides(job, a: argparse.Namespace) -> None:
    """CLI > preset > mặc định."""
    pr = job.preset
    c, o, r, au = pr.combine, pr.output, pr.run, pr.audio
    if a.limit:
        c.limit = a.limit
    if a.mode:
        c.mode = a.mode
    if a.subset_k:
        c.subset_k = a.subset_k
    if a.seed is not None:
        c.seed = a.seed
    if a.workers:
        r.workers = a.workers
    if a.quality:
        o.quality = a.quality
    if a.bitrate:
        o.bitrate_mbps = a.bitrate
    if a.codec:
        o.video_codec = a.codec
    if a.preset_speed:
        o.preset_speed = a.preset_speed
    if a.resolution:
        o.resolution = a.resolution
    if a.fps:
        o.fps = a.fps if a.fps == "same_as_base" else int(a.fps)
    if a.existing:
        r.existing = a.existing
    if a.retry is not None:
        r.retry = a.retry
    if a.stop_on_error:
        r.stop_on_error = True
    if a.keep_temp:
        r.keep_temp = True
    if a.no_cache:
        r.cache_normalized = False
    if a.temp_dir:
        r.temp_dir = a.temp_dir
    if a.thumbnails:
        o.thumbnails = True
    if a.normalize is not None:
        au.normalize_lufs = a.normalize
    if a.no_sleep_block:
        r.prevent_sleep = False
    r.log_level = a.log_level
    # validate lại sau khi ghi đè
    from .preset_io import preset_to_dict, validate_preset_dict
    job.preset = validate_preset_dict(preset_to_dict(pr), "dòng lệnh")


def _build_job(a: argparse.Namespace, extra: list[str]):
    preset = load_preset(a.preset)
    paths: dict[str, str] = {}
    for s in a.slot:
        if "=" not in s:
            raise SystemExit(f"--slot cần dạng tên=đường_dẫn: {s}")
        k, v = s.split("=", 1)
        paths[k.strip()] = v
    it = iter(extra)
    for tok in it:
        if tok.startswith("--") and tok[2:] in preset.slots:
            try:
                paths[tok[2:]] = next(it)
            except StopIteration:
                raise SystemExit(f"Thiếu đường dẫn cho {tok}")
        else:
            raise SystemExit(f"Tham số không hiểu: {tok}")
    job = make_job(a.preset, project=a.project, paths=paths, out_dir=a.out,
                   groups=_csv(a.groups), clips=_csv(a.clips))
    _apply_overrides(job, a)
    return job


class ConsoleView:
    def __init__(self, level: str = "info", as_json: bool = False):
        self.level = level
        self.as_json = as_json
        self._last_pct = -1.0
        self.color = sys.stdout.isatty()

    def __call__(self, ev: Event) -> None:
        if self.as_json:
            return
        if ev.type == "log":
            lv = ev.data.get("level", "info")
            if lv == "debug" and self.level != "debug":
                return
            c = COLORS.get(lv, "") if self.color else ""
            sys.stdout.write(("\r\033[K" if self.color else "") + f"{c}{ev.data.get('msg')}{RESET if c else ''}\n")
            sys.stdout.flush()
        elif ev.type == "progress":
            pct = ev.data["percent"]
            if pct == self._last_pct:
                return
            self._last_pct = pct
            eta = ev.data.get("eta_s")
            eta_s = f" • còn ~{int(eta // 60)}p{int(eta % 60):02d}s" if eta else ""
            line = (f"[{pct:5.1f}%] {ev.data['done'] + ev.data['skipped'] + ev.data['failed']}/{ev.data['total']}"
                    f" • lỗi {ev.data['failed']}{eta_s}")
            if self.color:
                sys.stdout.write("\r\033[K" + line)
                sys.stdout.flush()


def _print_plan(plan, as_json: bool) -> None:
    if as_json:
        print(json.dumps(plan.to_dict(with_tasks=True), ensure_ascii=False, indent=1, default=str))
        return
    for i in plan.issues:
        tag = {"error": "LỖI", "warning": "CẢNH BÁO", "info": "INFO"}[i.level]
        print(f"[{tag}] {i.msg}")
    d = plan.to_dict(with_tasks=False)
    if plan.out:
        print(f"\n{d['groups']} nhóm × {d['clips'] or 1} clip = {d['count']} video "
              f"({plan.out.W}×{plan.out.H} @ {plan.out.fps:g}fps) • đã có {d['existing']} • "
              f"tổng {d['total_duration'] / 60:.1f} phút video • cần ~{d['est_bytes'] / 1024 ** 3:.2f} GB • "
              f"{d['workers']} luồng")
    print("→ Sẵn sàng" if plan.ok else "→ CHƯA chạy được: " + "; ".join(plan.blockers()))


def cmd_check(a, extra) -> int:
    job = _build_job(a, extra)
    plan = plan_job(job)
    _print_plan(plan, a.json)
    return 0 if plan.ok else 2


def _run_with_signals(runner: BatchRunner) -> Any:
    def on_sigint(sig, frame):
        print("\nĐang dừng… (huỷ ffmpeg, dọn file .part)")
        runner.cancel()
    old = signal.signal(signal.SIGINT, on_sigint)
    try:
        return runner.run()
    finally:
        signal.signal(signal.SIGINT, old)


def cmd_run(a, extra) -> int:
    job = _build_job(a, extra)
    bus = EventBus()
    bus.subscribe(ConsoleView(a.log_level, a.json))
    plan = plan_job(job, bus)
    if a.dry_run or not plan.ok:
        _print_plan(plan, a.json)
        if not a.json and plan.ok:
            for t in plan.tasks:
                print(f"  {t.index:4d}. {t.out_path}")
        return 0 if plan.ok else 2
    if not a.json:
        _print_plan(plan, False)
    runner = BatchRunner(plan, bus, a.workers)
    s = _run_with_signals(runner)
    if a.json:
        print(json.dumps(runner.snapshot(), ensure_ascii=False, default=str))
    else:
        print(f"\nOutput: {job.out_dir}")
    return 0 if s.failed == 0 and not s.cancelled else 1


def cmd_resume(a, extra) -> int:
    d = find_unfinished(Path(a.out))
    if d is None:
        print("Không có job dang dở trong thư mục này.")
        return 0
    job = job_from_journal(d)
    job.preset.run.existing = "skip"
    bus = EventBus()
    bus.subscribe(ConsoleView())
    plan = plan_job(job, bus)
    _print_plan(plan, False)
    if not plan.ok:
        return 2
    s = _run_with_signals(BatchRunner(plan, bus))
    return 0 if s.failed == 0 else 1


def cmd_preview(a, extra) -> int:
    from .renderer import PreviewRunner, render_preview_clip
    job = _build_job(a, extra)
    plan = plan_job(job)
    if not plan.tasks:
        _print_plan(plan, False)
        return 2
    task = plan.tasks[0]
    out = Path(a.output)
    if a.clip5s:
        render_preview_clip(job.preset, task, out.with_suffix(".mp4"), seconds=a.seconds)
        print(out.with_suffix(".mp4"))
    else:
        png = PreviewRunner().frame(job.preset, task, a.segment, a.at, before=a.before)
        out.write_bytes(png)
        print(out)
    return 0


def cmd_presets(a, extra) -> int:
    if a.action == "list":
        for p in list_presets():
            print(f"{p['id']:20s} {p['name']}{'' if p['builtin'] else '  (người dùng)'}")
    elif a.action == "show":
        from .preset_io import preset_to_dict
        print(json.dumps(preset_to_dict(load_preset(a.name)), ensure_ascii=False, indent=2))
    elif a.action == "validate":
        load_preset(a.name)
        print("Preset hợp lệ")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vvb", description="Video Variant Builder — ghép video hàng loạt theo preset")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="Render")
    _add_job_args(r)
    r.add_argument("--dry-run", action="store_true", help="Chỉ kiểm tra + in danh sách sẽ tạo")
    c = sub.add_parser("check", help="Pre-flight, không render")
    _add_job_args(c)
    pv = sub.add_parser("preview", help="Render 1 frame (PNG) hoặc 5s xem thử")
    _add_job_args(pv)
    pv.add_argument("--at", type=float, default=1.0, help="Giây trong đoạn")
    pv.add_argument("--segment", type=int, default=0, help="Chỉ số đoạn trong timeline")
    pv.add_argument("--before", action="store_true", help="Ảnh gốc (chưa thay vùng)")
    pv.add_argument("--clip5s", action="store_true", help="Render video xem thử thay vì ảnh")
    pv.add_argument("--seconds", type=float, default=5.0)
    pv.add_argument("--output", "-o", default="preview.png")
    rs = sub.add_parser("resume", help="Tiếp tục job dang dở")
    rs.add_argument("--out", required=True)
    ps = sub.add_parser("presets", help="Quản lý preset")
    ps.add_argument("action", choices=["list", "show", "validate"])
    ps.add_argument("name", nargs="?")
    return ap


def main(argv: Optional[list[str]] = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    if sys.platform == "win32":
        import os
        os.system("")  # bật ANSI màu trên Windows console
    ap = build_parser()
    a, extra = ap.parse_known_args(argv)
    try:
        fn = {"run": cmd_run, "check": cmd_check, "preview": cmd_preview, "resume": cmd_resume,
              "presets": cmd_presets}[a.cmd]
        if a.cmd in ("resume", "presets") and extra:
            ap.error(f"Tham số không hiểu: {' '.join(extra)}")
        return fn(a, extra)
    except PresetError as e:
        print(str(e), file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
