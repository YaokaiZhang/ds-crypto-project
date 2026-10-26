"""Run repository regression suites without contacting live providers or Modal."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
CHECKS = PROJECT / 'checks'
sys.path[:] = [str(PROJECT), *[path for path in sys.path if Path(path).resolve() not in (PROJECT, CHECKS)]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('all','research','backend','serving','frontend'), default='all')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()
    os.chdir(PROJECT)
    sys.dont_write_bytecode = True
    os.environ.setdefault('GRADIO_ANALYTICS_ENABLED', 'False')
    os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
    for name in ('release-pinned', 'release-models'):
        config = PROJECT / f'deploy/.build/{name}/models.json'
        if config.is_file():
            os.environ.setdefault('TEST_MODEL_CONFIG', str(config))
            break
    success = True
    if args.suite != 'frontend':
        start = CHECKS if args.suite in ('all','research') else CHECKS / args.suite
        if args.suite == 'research':
            suite = unittest.TestSuite()
            for path in sorted(CHECKS.glob('test_*.py')):
                suite.addTests(unittest.defaultTestLoader.loadTestsFromName('checks.' + path.stem))
        else:
            suite = unittest.defaultTestLoader.discover(str(start), top_level_dir=str(PROJECT))
        success = unittest.TextTestRunner(verbosity=2 if args.verbose else 1).run(suite).wasSuccessful()
    if args.suite in ('all','frontend'):
        node = shutil.which('node')
        if node is None:
            print('Node.js is required for frontend checks.', file=sys.stderr)
            success = False
        else:
            files = sorted((CHECKS / 'frontend').glob('*.test.mjs'))
            result = subprocess.run([node, '--test', *map(str, files)], cwd=PROJECT)
            success = result.returncode == 0 and success
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
