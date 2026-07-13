from __future__ import annotations
import importlib.util
from pathlib import Path
REPO_ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('upd', REPO_ROOT/'scripts/update_iss_tle.py'); upd=importlib.util.module_from_spec(spec); spec.loader.exec_module(upd)  # type: ignore

def test_updater_retains_old_valid_data_on_validation_failure(tmp_path):
    path=tmp_path/'iss.tle'; old=(REPO_ROOT/'tests/fixtures/iss_fixed.tle').read_text(); path.write_text(old)
    try: upd.validate('bad')
    except ValueError: pass
    assert path.read_text()==old

def test_updater_atomic_write_and_validate(tmp_path):
    path=tmp_path/'iss.tle'; text=(REPO_ROOT/'tests/fixtures/iss_fixed.tle').read_text(); upd.validate(text); upd.atomic_write(path,text)
    assert path.read_text()==text
    assert not list(tmp_path.glob('*.tmp'))
