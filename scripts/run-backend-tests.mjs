import { accessSync, constants } from 'node:fs';
import { spawnSync } from 'node:child_process';

const candidates = process.platform === 'win32'
  ? ['backend/.venv/Scripts/python.exe']
  : ['backend/.venv/bin/python'];

const python = candidates.find((candidate) => {
  try {
    accessSync(candidate, constants.X_OK);
    return true;
  } catch {
    return false;
  }
});

if (!python) {
  console.error('Backend environment missing. Create backend/.venv and install: pip install -e "backend[dev]"');
  process.exit(1);
}

const result = spawnSync(
  python,
  ['-m', 'pytest', '-q', '-c', 'backend/pyproject.toml', 'backend/tests'],
  { stdio: 'inherit' },
);
process.exit(result.status ?? 1);
