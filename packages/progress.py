"""Terminal progress on stderr; redirected jobs are quiet unless requested."""
import sys
import os
import shutil
import threading
import time

PROGRESS_MODES = ("auto", "on", "off")


def progress_output():
    """Animations go to the actual terminal, not into durable text logs."""
    return getattr(sys.stderr, 'progress_stream', sys.stderr)


def progress_bar(iterable=None, *, mode="auto", **options):
    if mode not in PROGRESS_MODES:
        raise ValueError("progress must be auto, on or off")
    from tqdm import tqdm
    stream = options.pop('file', progress_output())
    options.setdefault('dynamic_ncols', True)
    return tqdm(iterable, file=stream,
                disable=mode == "off" or (mode == "auto" and not stream.isatty()),
                **options)


class NestedSampleProgress:
    """Two fixed terminal rows; focus stays on the oldest active sample.

    Non-terminal `on` output uses periodic plain summaries instead of cursor
    controls. Detailed per-sample state belongs in the durable progress JSON.
    """
    def __init__(self, total, initial=0, *, mode='auto', stream=None, clock=None, initial_failed=0):
        if mode not in PROGRESS_MODES:
            raise ValueError('progress must be auto, on or off')
        self.stream = stream if stream is not None else progress_output()
        self.log_stream = stream if stream is not None else sys.stderr
        self.clock = clock or time.monotonic
        self.mode = mode
        self.live = mode != 'off' and self.stream.isatty() and os.environ.get('TERM') != 'dumb'
        self.total, self.completed, self.failed = total, initial, initial_failed
        self.samples = {}
        self.lock = threading.RLock()
        self.last_render = self.last_text = float('-inf')
        self.outer = self.inner = None
        if self.live:
            self.outer = progress_bar(mode='on', file=self.stream, total=total, initial=initial,
                desc='Samples', unit='sample', position=0, leave=True, mininterval=1,
                dynamic_ncols=False, ncols=self._width())
            self.inner = progress_bar(mode='on', file=self.stream, total=0, desc='Waiting',
                unit='query', position=1, leave=False, mininterval=1, dynamic_ncols=False,
                ncols=self._width(), bar_format='{desc} {n_fmt}/{total_fmt} |{bar}| [{elapsed}] {postfix}')
        self._render(force=True)

    def _width(self):
        try:
            width = os.get_terminal_size(self.stream.fileno()).columns
        except (AttributeError, OSError, ValueError):
            width = shutil.get_terminal_size(fallback=(80, 24)).columns
        return max(20, width - 1)

    def start(self, key, target):
        with self.lock:
            self.samples[key] = {'sample_id': key, 'target': target, 'phase': 'starting',
                'completed_queries': 0, 'total_queries': 0, 'http_attempts': 0, 'cache_hits': 0,
                'started_at': self.clock()}
            self._render()

    def observe(self, state):
        with self.lock:
            current = self.samples.get(state['sample_id'])
            if current is not None:
                current.update(state)
                self._render()

    def phase(self, key, phase):
        self.observe({'sample_id': key, 'phase': phase})

    def finish(self, key, *, success=True, excluded=False):
        with self.lock:
            self.samples.pop(key, None)
            if success or excluded:
                self.completed += 1
            if not success:
                self.failed += 1
            self._render()

    def snapshot(self):
        with self.lock:
            now = self.clock()
            return [{**{k: v for k, v in state.items() if k != 'started_at'},
                     'elapsed_seconds': now - state['started_at']} for state in self.samples.values()]

    def discard(self, key):
        """Remove an interrupted root without counting it as a bad sample."""
        with self.lock:
            self.samples.pop(key, None)
            self._render()

    def _render(self, *, force=False, final=False):
        now = self.clock()
        if self.live:
            if not force and now - self.last_render < 1:
                return
            self.last_render = now
            self.outer.ncols = self.inner.ncols = self._width()
            self.outer.n = self.completed
            self.outer.set_postfix_str(f'active={len(self.samples)} fail={self.failed}', refresh=False)
            if self.samples:
                current = next(iter(self.samples.values()))
                target = current['target']
                label = target[:6] + '..' + target[-4:]
                self.inner.desc = f"{label} {current['phase']}"
                self.inner.n = current['completed_queries']
                self.inner.total = current['total_queries']
                self.inner.start_t = time.time() - (now - current['started_at'])
                action = {'txlist': 'tx', 'txlistinternal': 'internal',
                          'getLogs': 'logs', 'eth_call': 'call',
                          'eth_getTransactionReceipt': 'receipt'}.get(current.get('action'), current.get('action', ''))
                self.inner.set_postfix_str(f"{action} h:{current['http_attempts']} c:{current['cache_hits']}", refresh=False)
            else:
                self.inner.desc = 'Waiting' if not final else 'Finished'
                self.inner.n = self.inner.total = 0
                self.inner.set_postfix_str('', refresh=False)
            self.outer.refresh()
            self.inner.refresh()
        elif self.mode == 'on' and (final or now - self.last_text >= 30):
            self.last_text = now
            detail = ''
            if self.samples:
                current = next(iter(self.samples.values()))
                detail = (f" root={current['target']} phase={current['phase']} "
                          f"queries={current['completed_queries']}/{current['total_queries']}")
            print(f'[progress] samples={self.completed}/{self.total} active={len(self.samples)} failed={self.failed}',
                  detail, file=self.log_stream, flush=True)

    def message(self, message):
        from tqdm import tqdm
        with self.lock, tqdm.external_write_mode(file=self.stream):
            print(message, file=self.log_stream, flush=True)

    def close(self):
        with self.lock:
            self._render(force=True, final=True)
            if self.live:
                self.inner.close()
                self.outer.close()


def add_progress_arguments(parser, *, default="auto"):
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--progress", choices=PROGRESS_MODES, default=default,
                         help="Progress bars: auto (terminal only), on, or off; written to stderr")
    display.add_argument("--no-progress", dest="progress", action="store_const", const="off",
                         help="Disable progress bars")
