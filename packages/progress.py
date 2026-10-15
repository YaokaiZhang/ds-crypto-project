"""Terminal progress on stderr; redirected jobs are quiet unless requested."""
import sys

PROGRESS_MODES = ("auto", "on", "off")


def progress_bar(iterable=None, *, mode="auto", **options):
    if mode not in PROGRESS_MODES:
        raise ValueError("progress must be auto, on or off")
    from tqdm import tqdm
    return tqdm(iterable, file=sys.stderr, dynamic_ncols=True,
                disable=mode == "off" or (mode == "auto" and not sys.stderr.isatty()),
                **options)


def add_progress_arguments(parser, *, default="auto"):
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--progress", choices=PROGRESS_MODES, default=default,
                         help="Progress bars: auto (terminal only), on, or off; written to stderr")
    display.add_argument("--no-progress", dest="progress", action="store_const", const="off",
                         help="Disable progress bars")
